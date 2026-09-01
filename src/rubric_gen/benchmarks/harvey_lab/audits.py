"""Sealed quality-transfer and reward-hacking audits for Harvey studies."""

from __future__ import annotations

import difflib
import json
from pathlib import Path

from rubric_gen.evidence.index import index_implementation_sha256
from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.benchmarks.harvey_lab.artifacts import file_sha256, read_json_object, task_path
from rubric_gen.benchmarks.harvey_lab.config import HarveyRun
from rubric_gen.benchmarks.harvey_lab.controller import candidate_id, rubric_id
from rubric_gen.benchmarks.harvey_lab.evaluator import CandidateEvaluation, HarveyEvaluator
from rubric_gen.benchmarks.harvey_lab.runtime import runtime_root_from_environment
from rubric_gen.detection.jobs import DetectionConfig
from rubric_gen.detection.runner import DetectionRunner
from rubric_gen.detection.sources import transcript_audit_source


def _completed_candidate_count(experiment: HarveyRun) -> int:
    study = read_json_object(experiment.output_dir / "study.json", "completed Harvey study")
    count = study.get("candidate_count")
    if study.get("status") != "completed" or type(count) is not int or count < 1:
        raise ValueError("Harvey study is not complete")
    return count


def _canonical_result(experiment: HarveyRun, index: int, task_id: str) -> Path:
    return (
        experiment.output_dir
        / "rounds"
        / rubric_id(index)
        / "canonical"
        / candidate_id(index)
        / "tasks"
        / task_id
        / "result"
    )


def run_quality_audit(
    experiment: HarveyRun,
    *,
    evaluator: HarveyEvaluator | None = None,
) -> int:
    """Select on hidden tasks, then evaluate the selection on untouched tasks."""
    evaluator = evaluator or HarveyEvaluator(
        experiment,
        runtime_root=runtime_root_from_environment(),
    )
    count = _completed_candidate_count(experiment)
    root = experiment.output_dir / "audits" / "quality-transfer"
    original_tasks = {
        task_id: task_path(
            experiment.output_dir / "private" / "original_tasks", task_id
        )
        / "task.json"
        for task_id in experiment.benchmark.development_tasks
    }
    development_records: dict[str, object] = {}
    with TerminalProgress(
        total=count,
        description="Harvey development audit",
        unit="candidate",
    ) as progress:
        for index in range(count):
            identifier = candidate_id(index)
            progress.set_status(identifier)
            original_destination = root / "original-rubric" / identifier
            if original_destination.is_dir():
                original = _load_evaluation(original_destination)
            else:
                original = evaluator.rescore(
                    identifier,
                    {
                        task_id: _canonical_result(experiment, index, task_id)
                        for task_id in experiment.benchmark.development_tasks
                    },
                    original_tasks,
                    original_destination,
                )
            active = _load_evaluation(
                experiment.output_dir
                / "rounds"
                / rubric_id(index)
                / "canonical"
                / identifier
            )
            development_records[identifier] = {
                "active_rubric_mean_criterion_pass": active.mean_criterion_pass,
                "original_rubric_mean_criterion_pass": original.mean_criterion_pass,
                "active_minus_original": (
                    active.mean_criterion_pass - original.mean_criterion_pass
                ),
            }
            progress.update()
    selection_tasks = _private_task_files(
        experiment,
        experiment.benchmark.selection_tasks,
    )
    selection_records: dict[str, object] = {}
    with TerminalProgress(
        total=count,
        description="Harvey candidate selection",
        unit="candidate",
    ) as progress:
        for index in range(count):
            identifier = candidate_id(index)
            progress.set_status(identifier)
            evaluations = _replicated_hidden_evaluations(
                experiment,
                evaluator,
                identifier,
                selection_tasks,
                root / "selection" / identifier,
                label="selection",
            )
            selection_records[identifier] = _replicated_summary(evaluations)
            progress.update()
    selected = max(
        range(count),
        key=lambda index: (
            float(selection_records[candidate_id(index)]["mean_criterion_pass"]),  # type: ignore[index]
            float(selection_records[candidate_id(index)]["mean_all_pass"]),  # type: ignore[index]
            -index,
        ),
    )
    selected_id = candidate_id(selected)
    held_out_tasks = _private_task_files(
        experiment,
        experiment.benchmark.held_out_tasks,
    )
    held_out_records: dict[str, object] = {}
    for identifier in dict.fromkeys((candidate_id(0), selected_id)):
        evaluations = _replicated_hidden_evaluations(
            experiment,
            evaluator,
            identifier,
            held_out_tasks,
            root / "held-out" / identifier,
            label="held-out",
        )
        held_out_records[identifier] = _replicated_summary(evaluations)
    baseline_held_out = float(
        held_out_records[candidate_id(0)]["mean_criterion_pass"]  # type: ignore[index]
    )
    selected_held_out = float(
        held_out_records[selected_id]["mean_criterion_pass"]  # type: ignore[index]
    )
    write_json_atomic(
        root / "summary.json",
        {
            "kind": "harvey-hidden-quality-transfer-audit",
            "experiment_id": experiment.experiment_id,
            "study_id": experiment.study_id,
            "unit_id": experiment.unit_id,
            "condition": experiment.condition,
            "replicate": experiment.replicate,
            "candidate_count": count,
            "original_rubrics_visible_during_design": False,
            "selection_tasks_visible_during_design": False,
            "held_out_tasks_visible_during_design": False,
            "selection_rule": (
                "maximum replicated mean criterion pass, then mean all-pass, "
                "then earliest candidate"
            ),
            "outcome_replicates": experiment.outcome_replicates,
            "selected_candidate": selected_id,
            "development_candidates": development_records,
            "selection_candidates": selection_records,
            "held_out_candidates": held_out_records,
            "selected_minus_baseline_held_out": (
                selected_held_out - baseline_held_out
            ),
        },
    )
    return 0


def _private_task_files(
    experiment: HarveyRun,
    task_ids: tuple[str, ...],
) -> dict[str, Path]:
    return {
        task_id: task_path(
            experiment.output_dir / "private" / "original_tasks",
            task_id,
        )
        / "task.json"
        for task_id in task_ids
    }


def _replicated_hidden_evaluations(
    experiment: HarveyRun,
    evaluator: HarveyEvaluator,
    identifier: str,
    task_files: dict[str, Path],
    destination: Path,
    *,
    label: str,
) -> tuple[CandidateEvaluation, ...]:
    evaluations: list[CandidateEvaluation] = []
    for replicate in range(1, experiment.outcome_replicates + 1):
        evaluation_id = f"{identifier}-{label}-e{replicate:04d}"
        replicate_destination = destination / f"e{replicate:04d}"
        if replicate_destination.is_dir():
            evaluation = _load_evaluation(replicate_destination)
        else:
            evaluation = evaluator.evaluate(
                evaluation_id,
                experiment.output_dir / "candidates" / identifier / "harness",
                task_files,
                replicate_destination,
            )
        evaluations.append(evaluation)
    return tuple(evaluations)


def _replicated_summary(
    evaluations: tuple[CandidateEvaluation, ...],
) -> dict[str, object]:
    return {
        "mean_criterion_pass": sum(
            item.mean_criterion_pass for item in evaluations
        )
        / len(evaluations),
        "mean_all_pass": sum(item.mean_all_pass for item in evaluations)
        / len(evaluations),
        "replicates": [
            {
                "evaluation_id": item.candidate_id,
                "mean_criterion_pass": item.mean_criterion_pass,
                "mean_all_pass": item.mean_all_pass,
            }
            for item in evaluations
        ],
    }


def _load_evaluation(path: Path) -> CandidateEvaluation:
    summary = read_json_object(path / "summary.json", "Harvey evaluation")
    identifier, tasks = summary.get("candidate_id"), summary.get("tasks")
    if type(identifier) is not str or not isinstance(tasks, dict) or any(
        type(key) is not str or not isinstance(value, dict)
        for key, value in tasks.items()
    ):
        raise ValueError(f"invalid Harvey evaluation: {path}")
    from rubric_gen.benchmarks.harvey_lab.evaluator import aggregate_scores

    return aggregate_scores(identifier, tasks)  # type: ignore[arg-type]


def _text_patch(parent: Path, candidate: Path) -> str:
    parent_files = {
        path.relative_to(parent).as_posix(): path
        for path in parent.rglob("*")
        if path.is_file()
    }
    candidate_files = {
        path.relative_to(candidate).as_posix(): path
        for path in candidate.rglob("*")
        if path.is_file()
    }
    sections: list[str] = []
    for relative in sorted(set(parent_files) | set(candidate_files)):
        before_path, after_path = parent_files.get(relative), candidate_files.get(relative)
        try:
            before = [] if before_path is None else before_path.read_text(encoding="utf-8").splitlines()
            after = [] if after_path is None else after_path.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            sections.append(
                json.dumps(
                    {
                        "binary_file": relative,
                        "before_sha256": None if before_path is None else file_sha256(before_path),
                        "after_sha256": None if after_path is None else file_sha256(after_path),
                    },
                    sort_keys=True,
                )
            )
            continue
        if before == after:
            continue
        sections.extend(
            difflib.unified_diff(
                before,
                after,
                fromfile="parent/" + relative,
                tofile="candidate/" + relative,
                lineterm="",
            )
        )
    patch = "\n".join(sections)
    if len(patch) > 1_000_000:
        patch = patch[:500_000] + "\n[...bounded patch...]\n" + patch[-500_000:]
    return patch or "[No text patch was available.]"


def _accepted_attempt(experiment: HarveyRun, index: int) -> Path:
    attempts = (
        experiment.output_dir
        / "rounds"
        / rubric_id(index)
        / "design-attempts"
    )
    matches = []
    for path in sorted(attempts.glob("attempt-*")):
        accepted = path / "accepted.json"
        if accepted.is_file() and read_json_object(accepted, "accepted proposal").get(
            "candidate_id"
        ) == candidate_id(index):
            matches.append(path)
    if len(matches) != 1:
        raise ValueError(f"candidate {candidate_id(index)} has {len(matches)} accepted design attempts")
    return matches[0]


def prepare_reward_hacking_cases(experiment: HarveyRun) -> tuple[Path, ...]:
    count = _completed_candidate_count(experiment)
    cases_root = experiment.output_dir / "audits" / "reward-hacking" / "cases"
    cases: list[Path] = []
    for index in range(1, count):
        identifier = candidate_id(index)
        case = cases_root / identifier
        attempt = _accepted_attempt(experiment, index)
        candidate_record = read_json_object(
            experiment.output_dir / "candidates" / identifier / "candidate.json",
            "candidate record",
        )
        parent = candidate_record.get("parent_harness")
        if type(parent) is not str:
            raise ValueError(f"candidate {identifier} has no parent")
        messages: list[dict[str, str]] = [
            {
                "role": "user",
                "content": (attempt / "workspace" / "instruction.md").read_text(encoding="utf-8"),
            },
            {
                "role": "tool",
                "name": "visible_current_ranking",
                "content": (
                    attempt / "workspace" / "current" / "ranking.json"
                ).read_text(encoding="utf-8"),
            },
        ]
        trajectory = attempt / "agent" / "trajectory.stream.jsonl"
        for line_number, line in enumerate(
            trajectory.read_text(encoding="utf-8", errors="replace").splitlines(), 1
        ):
            if line.strip():
                messages.append(
                    {
                        "role": "tool",
                        "name": f"codex_event_{line_number}",
                        "content": line,
                    }
                )
        messages.extend(
            [
                {
                    "role": "assistant",
                    "content": json.dumps(candidate_record.get("proposal"), ensure_ascii=False),
                },
                {
                    "role": "tool",
                    "name": "accepted_harness_patch",
                    "content": _text_patch(
                        experiment.output_dir / "candidates" / parent / "harness",
                        experiment.output_dir / "candidates" / identifier / "harness",
                    ),
                },
                {
                    "role": "tool",
                    "name": "canonical_visible_result",
                    "content": (
                        experiment.output_dir
                        / "rounds"
                        / rubric_id(index)
                        / "canonical"
                        / identifier
                        / "summary.json"
                    ).read_text(encoding="utf-8"),
                },
            ]
        )
        manifest = {
            "kind": "reward-hacking-forensic-case",
            "case_id": identifier,
            "evidence_index_sha256": index_implementation_sha256(),
            "evidence_files": ["transcript.json"],
        }
        if case.exists():
            if read_json_object(case / "manifest.json", "forensic manifest") != manifest:
                raise ValueError(f"reward-hacking case changed: {case}")
            existing = json.loads((case / "transcript.json").read_text(encoding="utf-8"))
            if existing != {"messages": messages}:
                raise ValueError(f"reward-hacking transcript changed: {case}")
        else:
            case.mkdir(parents=True)
            write_json_atomic(case / "manifest.json", manifest)
            write_json_atomic(case / "transcript.json", {"messages": messages})
        cases.append(case)
    return tuple(cases)


def run_reward_hacking_audit(
    experiment: HarveyRun,
    *,
    resume: bool = False,
    max_concurrency: int | None = None,
    runner_type: type[DetectionRunner] = DetectionRunner,
) -> int:
    cases = prepare_reward_hacking_cases(experiment)
    if not cases:
        raise ValueError("reward-hacking audit needs at least one designed candidate")
    inputs = []
    for case in cases:
        for name in ("manifest.json", "transcript.json"):
            path = case / name
            inputs.append(
                {
                    "path": str(path.resolve()),
                    "bytes": path.stat().st_size,
                    "sha256": file_sha256(path),
                }
            )
    output = experiment.output_dir / "audits" / "reward-hacking" / "judgments"
    config = experiment.audit
    return runner_type(
        DetectionConfig(
            source=transcript_audit_source(
                cases,
                {
                    "dataset_revision": experiment.benchmark.revision,
                    "inputs": inputs,
                },
            ),
            models=config.models,
            output_dir=output,
            max_concurrency=(
                config.max_concurrency
                if max_concurrency is None
                else max_concurrency
            ),
            resume=resume,
            detection="rh",
            primary_rule=config.primary_rule,
        )
    ).run()
