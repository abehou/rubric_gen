"""Round controller for Harvey LAB harness evolution."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import asdict
from pathlib import Path
from typing import Protocol

from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.benchmarks.harvey_lab.artifacts import (
    copy_regular_tree,
    file_sha256,
    make_tree_read_only,
    read_json_object,
    task_path,
    tree_sha256,
    validate_checkout,
    validate_task,
    write_identity,
)
from rubric_gen.benchmarks.harvey_lab.config import (
    HarnessDesigner,
    HarveyRun,
    rubric_identity,
)
from rubric_gen.benchmarks.harvey_lab.designer import (
    CodexHarnessDesigner,
    DesignedCandidate,
    copy_designed_candidate,
)
from rubric_gen.benchmarks.harvey_lab.evaluator import (
    CandidateEvaluation,
    HarveyEvaluator,
    aggregate_scores,
    read_harvey_score,
    validate_harvey_score,
)
from rubric_gen.benchmarks.harvey_lab.rubrics import RubricProposal, TaskRubricProposer
from rubric_gen.benchmarks.harvey_lab.rtt import (
    ATTACKER_INSTRUCTION,
    ATTACKER_PROMPT,
    DELIVERY,
    RTT_VERSION,
    RedTeamTraceTaskRubricProposer,
    render_public_output,
    text_patch,
    validate_candidate_criteria,
)
from rubric_gen.benchmarks.harvey_lab.runtime import ensure_runtime_root


class Designer(Protocol):
    def prepare_workspace(
        self,
        workspace: Path,
        *,
        candidate_harnesses: dict[str, Path],
        canonical_evaluations: dict[str, Path],
        current_dir: Path,
    ) -> str: ...

    def run(
        self,
        workspace: Path,
        run_dir: Path,
        *,
        expected_input_sha256: str,
        candidate_harnesses: dict[str, Path],
    ) -> DesignedCandidate: ...


class Evaluator(Protocol):
    def evaluate(
        self,
        candidate_id: str,
        harness: Path,
        task_files: dict[str, Path],
        destination: Path,
    ) -> CandidateEvaluation: ...

    def rescore(
        self,
        candidate_id: str,
        source_results: dict[str, Path],
        task_files: dict[str, Path],
        destination: Path,
    ) -> CandidateEvaluation: ...


class Proposer(Protocol):
    def propose(self, task_file: Path, observation: dict[str, object]) -> RubricProposal: ...


def candidate_id(index: int) -> str:
    return f"h{index:04d}"


def rubric_id(index: int) -> str:
    return f"r{index:04d}"


def _evaluation_from_summary(path: Path) -> CandidateEvaluation:
    value = read_json_object(path / "summary.json", "candidate evaluation summary")
    candidate = value.get("candidate_id")
    tasks = value.get("tasks")
    if type(candidate) is not str or not isinstance(tasks, dict) or any(
        type(key) is not str or not isinstance(item, dict) for key, item in tasks.items()
    ):
        raise ValueError(f"invalid candidate evaluation summary: {path}")
    validated = {
        task_id: validate_harvey_score(score, f"Harvey score for {task_id}")
        for task_id, score in tasks.items()
    }
    return aggregate_scores(candidate, validated)


def build_ranking(
    rubric_version: str,
    evaluations: dict[str, CandidateEvaluation],
) -> dict[str, object]:
    records = [
        {
            "candidate_id": candidate,
            "mean_criterion_pass": evaluation.mean_criterion_pass,
            "mean_all_pass": evaluation.mean_all_pass,
        }
        for candidate, evaluation in evaluations.items()
    ]
    records.sort(
        key=lambda item: (
            -float(item["mean_criterion_pass"]),
            -float(item["mean_all_pass"]),
            str(item["candidate_id"]),
        )
    )
    frontier = []
    for record in records:
        dominated = any(
            (
                float(other["mean_criterion_pass"]) >= float(record["mean_criterion_pass"])
                and float(other["mean_all_pass"]) >= float(record["mean_all_pass"])
                and (
                    float(other["mean_criterion_pass"]) > float(record["mean_criterion_pass"])
                    or float(other["mean_all_pass"]) > float(record["mean_all_pass"])
                )
            )
            for other in records
        )
        if not dominated:
            frontier.append(str(record["candidate_id"]))
    return {
        "kind": "harvey-current-rubric-ranking",
        "rubric_version": rubric_version,
        "objectives": ["mean_criterion_pass", "mean_all_pass"],
        "ranking": records,
        "pareto_frontier": frontier,
        "note": "Parent selection is free; this ranking does not promote a candidate.",
    }


class HarveyEvolutionController:
    def __init__(
        self,
        experiment: HarveyRun,
        *,
        runtime_root: Path,
        evaluator: Evaluator | None = None,
        designer: Designer | None = None,
        proposer: Proposer | None = None,
        attacker: Designer | None = None,
    ) -> None:
        self.experiment = experiment
        self.root = experiment.output_dir
        self.runtime_root = runtime_root
        self.evaluator = evaluator or HarveyEvaluator(
            experiment,
            runtime_root=runtime_root,
        )
        self.designer = designer or CodexHarnessDesigner(
            experiment.designer,
            runtime_root=runtime_root,
        )
        if proposer is not None:
            self.proposer = proposer
        elif experiment.rubric.mode == "prospective":
            assert experiment.rubric.proposer_model is not None
            self.proposer = TaskRubricProposer(
                experiment.rubric.proposer_model,
                max_changes=experiment.rubric.max_changes_per_task,
                max_output_tokens=experiment.rubric.max_output_tokens,
            )
        elif experiment.rubric.mode == "red_team_trace":
            assert experiment.rubric.proposer_model is not None
            self.proposer = RedTeamTraceTaskRubricProposer(
                experiment.rubric.proposer_model,
                max_changes=experiment.rubric.max_changes_per_task,
                max_output_tokens=experiment.rubric.max_output_tokens,
            )
        else:
            self.proposer = None
        if attacker is not None:
            self.attacker = attacker
        elif experiment.rubric.mode == "red_team_trace":
            rubric = experiment.rubric
            assert rubric.attacker_model is not None
            self.attacker = CodexHarnessDesigner(
                HarnessDesigner(
                    model=rubric.attacker_model,
                    rounds=experiment.designer.rounds,
                    reasoning_effort=rubric.attacker_reasoning_effort,
                    service_tier=rubric.attacker_service_tier,
                    timeout_seconds=rubric.attacker_timeout_seconds,
                    retries=rubric.attacker_retries,
                ),
                runtime_root=runtime_root,
                prompt=ATTACKER_PROMPT,
                instruction=ATTACKER_INSTRUCTION,
            )
        else:
            self.attacker = None

    def run(self, *, resume: bool = False) -> int:
        ensure_runtime_root(self.runtime_root)
        self._initialize(resume=resume)
        with TerminalProgress(
            total=self.experiment.designer.rounds + 1,
            description="Harvey evolution",
            unit="candidate",
        ) as progress:
            progress.set_status("baseline h0000")
            self._ensure_baseline()
            baseline = self._ensure_canonical(0)
            self._write_current_round(0, {candidate_id(0): baseline})
            progress.update()
            for index in range(1, self.experiment.designer.rounds + 1):
                progress.set_status(f"round {index} {candidate_id(index)}")
                if self.experiment.rubric.mode == "red_team_trace":
                    self._ensure_red_team(index)
                self._ensure_rubric(index)
                current = self._crossed_prior_evaluations(index)
                candidate_exists = self._candidate_dir(index).is_dir()
                canonical_exists = self._canonical_dir(index).is_dir()
                if candidate_exists and canonical_exists:
                    current[candidate_id(index)] = self._ensure_canonical(index)
                    self._write_current_round(index, current)
                    progress.update()
                    continue
                if not candidate_exists:
                    self._write_current_round(index, current)
                    self._ensure_candidate(index)
                current[candidate_id(index)] = self._ensure_canonical(index)
                self._write_current_round(
                    index,
                    current,
                    replace=True,
                )
                progress.update()
        write_json_atomic(
            self.root / "study.json",
            {
                "kind": "harvey-harness-evolution-study",
                "experiment_id": self.experiment.experiment_id,
                "study_id": self.experiment.study_id,
                "unit_id": self.experiment.unit_id,
                "condition": self.experiment.condition,
                "replicate": self.experiment.replicate,
                "status": "completed",
                "rubric_mode": self.experiment.rubric.mode,
                "candidate_count": self.experiment.designer.rounds + 1,
                "final_candidate": candidate_id(self.experiment.designer.rounds),
                "hidden_audits_visible_to_designer": False,
                "red_team_trace_version": (
                    RTT_VERSION
                    if self.experiment.rubric.mode == "red_team_trace"
                    else None
                ),
            },
        )
        return 0

    def _identity(self) -> dict[str, object]:
        value = {
            "kind": "harvey-harness-evolution-experiment",
            "experiment_id": self.experiment.experiment_id,
            "study_id": self.experiment.study_id,
            "unit_id": self.experiment.unit_id,
            "condition": self.experiment.condition,
            "replicate": self.experiment.replicate,
            "experiment_path": str(self.experiment.source),
            "experiment_sha256": file_sha256(self.experiment.source),
            "benchmark_revision": self.experiment.benchmark.revision,
            "development_tasks": list(self.experiment.benchmark.development_tasks),
            "selection_tasks": list(self.experiment.benchmark.selection_tasks),
            "held_out_tasks": list(self.experiment.benchmark.held_out_tasks),
            "task_agent": asdict(self.experiment.task_agent),
            "judge": asdict(self.experiment.judge),
            "designer": asdict(self.experiment.designer),
            "rubric": rubric_identity(self.experiment.rubric),
            "audit": asdict(self.experiment.audit),
            "outcome_replicates": self.experiment.outcome_replicates,
            "parent_selection": "codex_free_choice_from_all_prior_candidates",
            "red_team_trace_version": (
                RTT_VERSION
                if self.experiment.rubric.mode == "red_team_trace"
                else None
            ),
        }
        return json.loads(json.dumps(value))

    def _initialize(self, *, resume: bool) -> None:
        validate_checkout(
            self.experiment.benchmark.checkout,
            self.experiment.benchmark.revision,
            (
                *self.experiment.benchmark.development_tasks,
                *self.experiment.benchmark.selection_tasks,
                *self.experiment.benchmark.held_out_tasks,
            ),
        )
        if self.root.exists() and not self.root.is_dir():
            raise ValueError(f"Harvey output is not a directory: {self.root}")
        if self.root.is_dir() and any(self.root.iterdir()) and not (self.root / "experiment.json").is_file():
            raise FileExistsError(f"Harvey output is non-empty and unrecognized: {self.root}")
        self.root.mkdir(parents=True, exist_ok=True)
        write_identity(self.root / "experiment.json", self._identity(), resume=resume)
        private = self.root / "private" / "original_tasks"
        if private.exists():
            return
        for task_id in (
            *self.experiment.benchmark.development_tasks,
            *self.experiment.benchmark.selection_tasks,
            *self.experiment.benchmark.held_out_tasks,
        ):
            source = task_path(self.experiment.benchmark.checkout / "tasks", task_id) / "task.json"
            validate_task(source)
            destination = task_path(private, task_id)
            destination.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination / "task.json")
        make_tree_read_only(private)

    def _ensure_baseline(self) -> None:
        destination = self._candidate_dir(0)
        if destination.is_dir():
            record = read_json_object(destination / "candidate.json", "baseline candidate")
            if record.get("parent_harness") is not None or record.get("harness_sha256") != tree_sha256(destination / "harness"):
                raise ValueError("baseline candidate changed")
        else:
            destination.mkdir(parents=True)
            copy_regular_tree(
                self.experiment.benchmark.checkout / "harness",
                destination / "harness",
            )
            write_json_atomic(
                destination / "candidate.json",
                {
                    "kind": "harvey-harness-candidate",
                    "parent_harness": None,
                    "harness_sha256": tree_sha256(destination / "harness"),
                    "proposal": None,
                    "source": "stock Harvey LAB harness at the pinned benchmark revision",
                },
            )
            make_tree_read_only(destination)
        self._ensure_rubric(0)

    def _ensure_rubric(self, index: int) -> None:
        destination = self._rubric_dir(index)
        if destination.is_dir():
            metadata = read_json_object(destination / "rubric.json", "rubric version")
            if metadata.get("rubric_version") != rubric_id(index) or metadata.get("mode") != self.experiment.rubric.mode:
                raise ValueError(f"rubric checkpoint differs: {destination}")
            return
        pending = destination.with_name("." + destination.name + ".pending")
        if pending.exists():
            shutil.rmtree(pending)
        pending.mkdir(parents=True)
        proposals: dict[str, object] = {}
        for task_id in self.experiment.benchmark.development_tasks:
            task_destination = task_path(pending / "tasks", task_id)
            task_destination.mkdir(parents=True, exist_ok=True)
            if index == 0:
                source = task_path(self.root / "private" / "original_tasks", task_id) / "task.json"
                shutil.copy2(source, task_destination / "task.json")
                continue
            previous = task_path(self._rubric_dir(index - 1) / "tasks", task_id) / "task.json"
            if self.experiment.rubric.mode == "static":
                shutil.copy2(previous, task_destination / "task.json")
                continue
            assert self.proposer is not None
            if self.experiment.rubric.mode == "red_team_trace":
                task, record = self._ensure_rtt_task_rubric(
                    index,
                    task_id,
                    previous,
                )
                (task_destination / "task.json").write_text(
                    json.dumps(task, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                proposals[task_id] = record
                continue
            proposal = self.proposer.propose(
                previous,
                self._rubric_observation(index - 1, task_id),
            )
            (task_destination / "task.json").write_text(
                json.dumps(proposal.task, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )
            proposals[task_id] = {
                "proposal": proposal.proposal,
                "generation": proposal.generation,
            }
        write_json_atomic(
            pending / "rubric.json",
            {
                "kind": "harvey-task-rubric",
                "rubric_version": rubric_id(index),
                "parent_rubric": None if index == 0 else rubric_id(index - 1),
                "mode": self.experiment.rubric.mode,
                "source_candidate": None if index == 0 else candidate_id(index - 1),
                "task_proposals": proposals,
            },
        )
        make_tree_read_only(pending)
        os.replace(pending, destination)

    def _ensure_red_team(self, index: int) -> None:
        if index < 1 or self.experiment.rubric.mode != "red_team_trace":
            raise ValueError("red-team sidecars require a positive RTT round")
        if self.attacker is None:
            raise RuntimeError("red-team-trace treatment has no attacker")
        root = self._red_team_dir(index)
        parent_id = candidate_id(index - 1)
        candidate = root / "candidate"
        if candidate.is_dir():
            record = read_json_object(candidate / "candidate.json", "RTT sidecar candidate")
            if (
                record.get("parent_harness") != parent_id
                or record.get("harness_sha256")
                != tree_sha256(candidate / "harness")
            ):
                raise ValueError(f"RTT sidecar candidate changed: {candidate}")
        else:
            attempts = root / "design-attempts"
            attempt_number = (
                len(tuple(attempts.glob("attempt-*"))) + 1
                if attempts.exists()
                else 1
            )
            attempt = attempts / f"attempt-{attempt_number:03d}"
            workspace = attempt / "workspace"
            parents = {parent_id: self._candidate_dir(index - 1) / "harness"}
            expected = self.attacker.prepare_workspace(
                workspace,
                candidate_harnesses=parents,
                canonical_evaluations={
                    parent_id: self._canonical_dir(index - 1),
                },
                current_dir=(
                    self.root
                    / "rounds"
                    / rubric_id(index - 1)
                    / "visible-current"
                ),
            )
            designed = self.attacker.run(
                workspace,
                attempt / "agent",
                expected_input_sha256=expected,
                candidate_harnesses=parents,
            )
            if designed.parent_id != parent_id:
                raise ValueError("RTT sidecar selected an unexpected parent")
            copy_designed_candidate(designed, candidate)
            write_json_atomic(
                attempt / "accepted.json",
                {
                    "sidecar_id": f"a{index:04d}",
                    "parent_harness": designed.parent_id,
                    "harness_sha256": designed.harness_sha256,
                },
            )
            make_tree_read_only(attempt)
        destination = root / "evaluation"
        if destination.is_dir():
            evaluation = _evaluation_from_summary(destination)
        else:
            evaluation = self.evaluator.evaluate(
                f"a{index:04d}",
                candidate / "harness",
                self._active_task_files(index - 1),
                destination,
            )
        record = {
            "kind": "harvey-red-team-trace-sidecar",
            "red_team_trace_version": RTT_VERSION,
            "round": rubric_id(index),
            "sidecar_id": f"a{index:04d}",
            "parent_harness": parent_id,
            "active_rubric": rubric_id(index - 1),
            "mean_criterion_pass": evaluation.mean_criterion_pass,
            "mean_all_pass": evaluation.mean_all_pass,
            "hidden_selection_or_held_out_used": False,
        }
        path = root / "sidecar.json"
        if path.is_file():
            if read_json_object(path, "RTT sidecar record") != record:
                raise ValueError(f"RTT sidecar record changed: {path}")
        else:
            write_json_atomic(path, record)

    def _ensure_rtt_task_rubric(
        self,
        index: int,
        task_id: str,
        previous: Path,
    ) -> tuple[dict[str, object], dict[str, object]]:
        learning = task_path(
            self._red_team_dir(index) / "learning" / "tasks",
            task_id,
        )
        final_task_path = learning / "task.json"
        result_path = learning / "result.json"
        if final_task_path.is_file() and result_path.is_file():
            return (
                validate_task(final_task_path),
                read_json_object(result_path, "RTT task learning result"),
            )
        learning.mkdir(parents=True, exist_ok=True)
        proposal_path = learning / "proposal.json"
        if proposal_path.is_file():
            saved = read_json_object(proposal_path, "RTT rubric proposal")
            task = saved.get("task")
            proposal = saved.get("proposal")
            generation = saved.get("generation")
            if (
                not isinstance(task, dict)
                or not isinstance(proposal, dict)
                or not isinstance(generation, dict)
            ):
                raise ValueError("saved RTT rubric proposal is invalid")
            proposed = RubricProposal(task, proposal, generation)
        else:
            assert self.proposer is not None
            observation = self._rtt_observation(index, task_id)
            observation["checkpoint_dir"] = str(learning / "provider-calls")
            proposed = self.proposer.propose(
                previous,
                observation,
            )
            write_json_atomic(
                proposal_path,
                {
                    "task": proposed.task,
                    "proposal": proposed.proposal,
                    "generation": proposed.generation,
                },
            )
        original = validate_task(previous)
        original_criteria = original["criteria"]
        proposed_criteria = proposed.task.get("criteria")
        if not isinstance(original_criteria, list) or not isinstance(proposed_criteria, list):
            raise ValueError("RTT task proposal has invalid criteria")
        accepted_ids: tuple[str, ...] = ()
        rejected_ids: tuple[str, ...] = ()
        final_task = original
        validation_record: dict[str, object] | None = None
        if len(proposed_criteria) > len(original_criteria):
            proposed_dir = learning / "proposed"
            proposed_dir.mkdir(exist_ok=True)
            proposed_task_path = proposed_dir / "task.json"
            if not proposed_task_path.is_file():
                proposed_task_path.write_text(
                    json.dumps(proposed.task, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
            task_files = {task_id: proposed_task_path}
            clean_result = (
                self._canonical_dir(index - 1) / "tasks" / task_id / "result"
            )
            sidecar_result = (
                self._red_team_dir(index)
                / "evaluation"
                / "tasks"
                / task_id
                / "result"
            )
            clean_destination = learning / "validation" / "clean"
            sidecar_destination = learning / "validation" / "sidecar"
            clean_evaluation = (
                _evaluation_from_summary(clean_destination)
                if clean_destination.is_dir()
                else self.evaluator.rescore(
                    f"rtt-clean-r{index:04d}",
                    {task_id: clean_result},
                    task_files,
                    clean_destination,
                )
            )
            sidecar_evaluation = (
                _evaluation_from_summary(sidecar_destination)
                if sidecar_destination.is_dir()
                else self.evaluator.rescore(
                    f"rtt-sidecar-r{index:04d}",
                    {task_id: sidecar_result},
                    task_files,
                    sidecar_destination,
                )
            )
            validated = validate_candidate_criteria(
                original,
                proposed.task,
                clean_evaluation.task_scores[task_id],
                sidecar_evaluation.task_scores[task_id],
            )
            final_task = validated.task
            accepted_ids = validated.accepted_ids
            rejected_ids = validated.rejected_ids
            validation_record = {
                "clean": clean_evaluation.task_scores[task_id],
                "sidecar": sidecar_evaluation.task_scores[task_id],
            }
        final_task_path.write_text(
            json.dumps(final_task, indent=2, ensure_ascii=False) + "\n",
            encoding="utf-8",
        )
        record = {
            "red_team_trace_version": RTT_VERSION,
            "proposal": proposed.proposal,
            "generation": proposed.generation,
            "accepted_criterion_ids": list(accepted_ids),
            "rejected_criterion_ids": list(rejected_ids),
            "blind_public_output_validation": validation_record,
        }
        write_json_atomic(result_path, record)
        make_tree_read_only(learning)
        return validate_task(final_task_path), record

    def _rtt_observation(self, index: int, task_id: str) -> dict[str, object]:
        clean_result = self._canonical_dir(index - 1) / "tasks" / task_id / "result"
        sidecar_result = (
            self._red_team_dir(index)
            / "evaluation"
            / "tasks"
            / task_id
            / "result"
        )
        clean_score = read_harvey_score(clean_result / "scores.json", "RTT clean score")
        sidecar_score = read_harvey_score(
            sidecar_result / "scores.json",
            "RTT sidecar score",
        )

        def fraction(score: dict[str, object]) -> float:
            passed, count = score["n_passed"], score["n_criteria"]
            assert type(passed) is int and type(count) is int and count > 0
            return passed / count

        clean_trace = (clean_result / "transcript.jsonl").read_text(
            encoding="utf-8",
            errors="replace",
        )
        sidecar_trace = (sidecar_result / "transcript.jsonl").read_text(
            encoding="utf-8",
            errors="replace",
        )
        return {
            "task_id": task_id,
            "round_index": index,
            "red_team_trace_version": RTT_VERSION,
            "clean": {
                "candidate_id": candidate_id(index - 1),
                "active_criterion_pass": fraction(clean_score),
                "active_score": clean_score,
                "public_output": render_public_output(clean_result / "output"),
                "task_agent_trajectory_jsonl": (
                    clean_trace
                    if len(clean_trace) <= 120_000
                    else clean_trace[:60_000] + "\n[...bounded...]\n" + clean_trace[-60_000:]
                ),
            },
            "sidecar": {
                "candidate_id": f"a{index:04d}",
                "active_criterion_pass": fraction(sidecar_score),
                "active_score": sidecar_score,
                "public_output": render_public_output(sidecar_result / "output"),
                "task_agent_trajectory_jsonl": (
                    sidecar_trace
                    if len(sidecar_trace) <= 120_000
                    else sidecar_trace[:60_000] + "\n[...bounded...]\n" + sidecar_trace[-60_000:]
                ),
                "harness_patch": text_patch(
                    self._candidate_dir(index - 1) / "harness",
                    self._red_team_dir(index) / "candidate" / "harness",
                ),
            },
        }

    def _rubric_observation(self, candidate_index: int, task_id: str) -> dict[str, object]:
        result = self._canonical_dir(candidate_index) / "tasks" / task_id / "result"
        score = read_harvey_score(result / "scores.json", "Harvey score")
        metrics = read_json_object(result / "metrics.json", "Harvey metrics")
        transcript_path = result / "transcript.jsonl"
        transcript = transcript_path.read_text(encoding="utf-8", errors="replace")
        if len(transcript) > 120_000:
            transcript = transcript[:60_000] + "\n[...bounded...]\n" + transcript[-60_000:]
        output = result / "output"
        inventory = []
        if output.is_dir():
            for path in sorted(output.rglob("*")):
                if path.is_file():
                    inventory.append(
                        {
                            "path": path.relative_to(output).as_posix(),
                            "bytes": path.stat().st_size,
                            "sha256": file_sha256(path),
                        }
                    )
        return {
            "candidate_id": candidate_id(candidate_index),
            "task_id": task_id,
            "score": score,
            "metrics": metrics,
            "task_agent_trajectory_jsonl": transcript,
            "output_inventory": inventory,
        }

    def _crossed_prior_evaluations(self, index: int) -> dict[str, CandidateEvaluation]:
        evaluations: dict[str, CandidateEvaluation] = {}
        task_files = self._active_task_files(index)
        for candidate_index in range(index):
            current = self._current_eval_dir(index, candidate_index)
            if current.is_dir():
                evaluations[candidate_id(candidate_index)] = _evaluation_from_summary(current)
                continue
            source_results = {
                task_id: self._canonical_dir(candidate_index) / "tasks" / task_id / "result"
                for task_id in self.experiment.benchmark.development_tasks
            }
            evaluations[candidate_id(candidate_index)] = self.evaluator.rescore(
                candidate_id(candidate_index),
                source_results,
                task_files,
                current,
            )
        return evaluations

    def _ensure_candidate(self, index: int) -> None:
        destination = self._candidate_dir(index)
        if destination.is_dir():
            record = read_json_object(destination / "candidate.json", "harness candidate")
            if record.get("harness_sha256") != tree_sha256(destination / "harness"):
                raise ValueError(f"candidate changed: {destination}")
            return
        attempts = self.root / "rounds" / rubric_id(index) / "design-attempts"
        attempt_number = len(tuple(attempts.glob("attempt-*"))) + 1 if attempts.exists() else 1
        attempt = attempts / f"attempt-{attempt_number:03d}"
        workspace = attempt / "workspace"
        candidates = self._candidate_harnesses(index)
        expected = self.designer.prepare_workspace(
            workspace,
            candidate_harnesses=candidates,
            canonical_evaluations={
                candidate_id(value): self._canonical_dir(value)
                for value in range(index)
            },
            current_dir=self.root / "rounds" / rubric_id(index) / "visible-current",
        )
        designed = self.designer.run(
            workspace,
            attempt / "agent",
            expected_input_sha256=expected,
            candidate_harnesses=candidates,
        )
        copy_designed_candidate(designed, destination)
        write_json_atomic(
            attempt / "accepted.json",
            {
                "candidate_id": candidate_id(index),
                "parent_harness": designed.parent_id,
                "harness_sha256": designed.harness_sha256,
            },
        )
        make_tree_read_only(attempt)

    def _ensure_canonical(self, index: int) -> CandidateEvaluation:
        destination = self._canonical_dir(index)
        if destination.is_dir():
            return _evaluation_from_summary(destination)
        return self.evaluator.evaluate(
            candidate_id(index),
            self._candidate_dir(index) / "harness",
            self._active_task_files(index),
            destination,
        )

    def _write_current_round(
        self,
        index: int,
        evaluations: dict[str, CandidateEvaluation],
        *,
        replace: bool = False,
    ) -> None:
        round_dir = self.root / "rounds" / rubric_id(index)
        current = round_dir / "current"
        visible = round_dir / "visible-current"
        if replace:
            for path in (current, visible):
                if path.exists():
                    self._remove_owned_tree(path)
        if current.exists():
            existing = read_json_object(current / "ranking.json", "current ranking")
            expected = build_ranking(rubric_id(index), evaluations)
            if existing != expected:
                raise ValueError(f"current ranking differs: {current}")
            return
        current.mkdir(parents=True)
        ranking = build_ranking(rubric_id(index), evaluations)
        write_json_atomic(current / "ranking.json", ranking)
        for candidate, evaluation in evaluations.items():
            write_json_atomic(
                current / "scores" / candidate / "summary.json",
                {
                    "candidate_id": candidate,
                    "mean_criterion_pass": evaluation.mean_criterion_pass,
                    "mean_all_pass": evaluation.mean_all_pass,
                    "tasks": evaluation.task_scores,
                },
            )
        make_tree_read_only(current)
        visible.mkdir(parents=True)
        copy_regular_tree(self._rubric_dir(index) / "tasks", visible / "active_task_rubrics")
        shutil.copy2(current / "ranking.json", visible / "ranking.json")
        copy_regular_tree(current / "scores", visible / "current_scores")
        if self.experiment.rubric.mode == "red_team_trace":
            (visible / "red-team-trace-delivery.md").write_text(
                DELIVERY,
                encoding="utf-8",
            )
        make_tree_read_only(visible)

    def _active_task_files(self, index: int) -> dict[str, Path]:
        return {
            task_id: task_path(self._rubric_dir(index) / "tasks", task_id) / "task.json"
            for task_id in self.experiment.benchmark.development_tasks
        }

    def _candidate_harnesses(self, count: int) -> dict[str, Path]:
        return {
            candidate_id(index): self._candidate_dir(index) / "harness"
            for index in range(count)
        }

    def _candidate_dir(self, index: int) -> Path:
        return self.root / "candidates" / candidate_id(index)

    def _rubric_dir(self, index: int) -> Path:
        return self.root / "rubrics" / rubric_id(index)

    def _canonical_dir(self, index: int) -> Path:
        return self.root / "rounds" / rubric_id(index) / "canonical" / candidate_id(index)

    def _current_eval_dir(self, round_index: int, candidate_index: int) -> Path:
        return self.root / "rounds" / rubric_id(round_index) / "crossed" / candidate_id(candidate_index)

    def _red_team_dir(self, index: int) -> Path:
        return self.root / "red-team" / rubric_id(index)

    @staticmethod
    def _remove_owned_tree(path: Path) -> None:
        if path.is_symlink() or not path.is_dir():
            raise ValueError(f"invalid owned Harvey directory: {path}")
        for child in path.rglob("*"):
            try:
                child.chmod(child.stat().st_mode | 0o700)
            except OSError:
                pass
        path.chmod(path.stat().st_mode | 0o700)
        shutil.rmtree(path)
