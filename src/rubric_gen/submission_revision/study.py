"""Execute and validate a randomized submission-revision experiment."""

from __future__ import annotations

import fcntl
import json
import math
import os
import socket
import stat
import sys
import threading
import traceback
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import datetime
from pathlib import Path
from numbers import Real

from rubric_gen.submission_revision.prompts import PromptProfile
from rubric_gen.submission_revision.experiment import Experiment
from rubric_gen.submission_revision.controller import (
    fixed_original_attempt_id,
    run_submission_revision,
)
from rubric_gen.submission_revision.feedback import (
    FeedbackPolicy,
    compose_bank_score,
    project_bank_feedback,
    project_bank_simulated_user_feedback,
)
from rubric_gen.submission_revision.bank_scoring import preflight_bank_dispatch
from rubric_gen.submission_revision.evolution import (
    RubricBankProposer,
    rubric_generation_implementation_identity,
)
from rubric_gen.submission_revision.contrasts import (
    build_elicitation_artifact_history,
)
from rubric_gen.submission_revision.judgment_reuse import (
    ExactJudgmentReuseStore,
    ExactSimulatorReuseStore,
    exact_judgment_request,
    exact_simulator_request,
)
from rubric_gen.submission_revision.judge import (
    FrozenRubric,
    FrozenRubricJudge,
    SubmissionJudgeConfig,
    resolve_optimizer_rubric,
)
from rubric_gen.submission_revision.judging.models import RUBRIC_PATH_SOURCE
from rubric_gen.submission_revision.models import SubmissionRevisionConfig
from rubric_gen.submission_revision.artifacts import (
    read_json_object,
    revision_manifest_keys,
    sha256_file,
    tree_sha256,
    verify_submission_snapshot,
)
from rubric_gen.submission_revision.rubric_bank import (
    RubricBankPolicy,
    load_rubric_bank,
)
from rubric_gen.submission_revision.seeds import resolve_seed
from rubric_gen.submission_revision.paraphrases import (
    resolve_paraphrase_selection,
    validate_paraphrase_run,
)
from rubric_gen.submission_revision.store import (
    extract_judge_execution_contract,
    extract_seed_scoring_contract,
)
from rubric_gen.submission_revision.user_simulator import SimulatedUserFeedback
from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.benchmarks import get_submission_benchmark


STUDY_RUN_KIND = "rubric-gen-randomized-revision-study"
_STUDY_LEASE_NAME = ".study.lock"


@dataclass(frozen=True)
class StudyRunConfig:
    experiment: Experiment
    seed_run_dir: Path
    paraphrase_run_dir: Path
    output_dir: Path
    max_concurrency: int
    resume: bool = False
    vllm_endpoints: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.max_concurrency) is not int or self.max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")


class StudyRunner:
    def __init__(self, config: StudyRunConfig) -> None:
        self.config = config
        self.experiment = config.experiment
        self.root = config.output_dir.resolve()
        self.seed_root = config.seed_run_dir.resolve()
        self.paraphrase_root = config.paraphrase_run_dir.resolve()
        self._manifest_lock = threading.Lock()

    def run(self) -> int:
        assignments = sorted(
            self.experiment.assignments,
            key=lambda item: int(item["execution_order"]),
        )
        validate_paraphrase_run(self.paraphrase_root, self.experiment)
        existed = os.path.lexists(self.root)
        if existed and not self.config.resume:
            raise FileExistsError(f"study output already exists: {self.root}")
        if existed and (self.root.is_symlink() or not self.root.is_dir()):
            raise RuntimeError(f"study output is not a regular directory: {self.root}")
        if not existed:
            self.root.mkdir(parents=True)
        with _exclusive_study_lease(self.root):
            return self._run_locked(assignments, existed)

    def _run_locked(
        self,
        assignments: list[dict[str, object]],
        existed: bool,
    ) -> int:
        if not existed:
            manifest = self._new_manifest(assignments)
            self._write_manifest(manifest)
        else:
            manifest = self._load_manifest()
            self._validate_manifest_identity(manifest, assignments)
            _reclaim_interrupted_records(manifest)
        pending: list[dict[str, object]] = []
        for assignment in assignments:
            assignment_id = str(assignment["assignment_id"])
            record = _record_for(manifest, assignment_id)
            experiment = self._experiment_dir(assignment)
            if record.get("status") == "completed":
                try:
                    validate_completed_revision(
                        experiment,
                        assignment,
                        self.experiment,
                        self.seed_root,
                        self.paraphrase_root,
                        vllm_endpoints=self.config.vllm_endpoints,
                        judgment_reuse_root=self.root / "shared-judgments",
                    )
                except Exception as exc:
                    record.update({
                        "status": "invalid",
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                    })
                continue
            if record.get("status") == "invalid":
                continue
            pending.append(assignment)
        manifest["status"] = "running"
        manifest["finished_at"] = None
        manifest["max_concurrency_last_invocation"] = self.config.max_concurrency
        self._write_manifest(manifest)
        if not pending:
            statuses = {str(record["status"]) for record in _records(manifest)}
            manifest["status"] = (
                "completed" if statuses == {"completed"} else "failed"
            )
            manifest["finished_at"] = _now()
            self._write_manifest(manifest)
            _report_noncompleted_records(manifest)
            return int(manifest["status"] != "completed")

        positions: list[int] = list(range(1, self.config.max_concurrency + 1))
        position_lock = threading.Lock()

        def acquire_position() -> int:
            with position_lock:
                return positions.pop(0)

        def release_position(position: int) -> None:
            with position_lock:
                positions.append(position)
                positions.sort()

        def execute(assignment: dict[str, object]) -> None:
            position = acquire_position()
            assignment_id = str(assignment["assignment_id"])
            try:
                with self._manifest_lock:
                    latest = self._load_manifest()
                    record = _record_for(latest, assignment_id)
                    record.update({
                        "status": "running",
                        "started_at": _now(),
                        "finished_at": None,
                        "hostname": socket.gethostname(),
                        "pid": os.getpid(),
                        "attempt_count": int(record.get("attempt_count", 0)) + 1,
                    })
                    for key in ("error_type", "error", "traceback"):
                        record.pop(key, None)
                    self._write_manifest(latest)
                experiment = self._experiment_dir(assignment)
                revision = self._revision_config(
                    assignment,
                    resume=os.path.lexists(experiment),
                )
                run_submission_revision(
                    replace(revision, progress_position=position),
                    judgment_reuse_root=self.root / "shared-judgments",
                )
                validate_completed_revision(
                    experiment,
                    assignment,
                    self.experiment,
                    self.seed_root,
                    self.paraphrase_root,
                    vllm_endpoints=self.config.vllm_endpoints,
                    judgment_reuse_root=self.root / "shared-judgments",
                )
                with self._manifest_lock:
                    latest = self._load_manifest()
                    _record_for(latest, assignment_id).update({
                        "status": "completed",
                        "finished_at": _now(),
                    })
                    self._write_manifest(latest)
            except (Exception, SystemExit) as exc:
                with self._manifest_lock:
                    latest = self._load_manifest()
                    _record_for(latest, assignment_id).update({
                        "status": "failed",
                        "finished_at": _now(),
                        "error_type": type(exc).__name__,
                        "error": str(exc),
                        "traceback": traceback.format_exc(),
                    })
                    self._write_manifest(latest)
            finally:
                release_position(position)

        with TerminalProgress(
            total=len(assignments),
            description="randomized study",
            unit="assignment",
            position=0,
        ) as progress:
            for _ in range(len(assignments) - len(pending)):
                progress.update()
            with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as pool:
                futures = [pool.submit(execute, assignment) for assignment in pending]
                for future in as_completed(futures):
                    future.result()
                    progress.update()
        manifest = self._load_manifest()
        statuses = [str(record["status"]) for record in _records(manifest)]
        manifest["status"] = (
            "completed" if statuses and set(statuses) == {"completed"} else "failed"
        )
        manifest["finished_at"] = _now()
        self._write_manifest(manifest)
        _report_noncompleted_records(manifest)
        return int(manifest["status"] != "completed")

    def _revision_config(
        self,
        assignment: dict[str, object],
        *,
        resume: bool,
    ) -> SubmissionRevisionConfig:
        protocol = self.experiment.protocol
        condition = self.experiment.condition(str(assignment["condition_id"]))
        feedback_policy = FeedbackPolicy(str(condition["feedback_policy"]))
        selection = resolve_paraphrase_selection(
            self.paraphrase_root,
            self.experiment,
            str(assignment["task_id"]),
            int(assignment["replicate"]),
        )
        return SubmissionRevisionConfig(
            task_dir=self.experiment.task_dir(str(assignment["task_id"])),
            experiment_dir=self._experiment_dir(assignment),
            revision_rounds=int(protocol["revision_rounds"]),
            seed_run_dir=self.seed_root,
            agent=self.experiment.agent_config(
                quiet=True,
                vllm_endpoints=self.config.vllm_endpoints
            ),
            experiment_id=self.experiment.experiment_id,
            assignment_id=str(assignment["assignment_id"]),
            condition_id=str(assignment["condition_id"]),
            replicate=int(assignment["replicate"]),
            execution_order=int(assignment["execution_order"]),
            optimizer_rubric_path=selection.optimizer_path,
            master_rubric_name=str(protocol["rubric_name"]),
            benchmark=self.experiment.benchmark,
            judge_max_retries=int(protocol["judge_max_retries"]),
            rubric_proposer_max_retries=int(
                protocol["rubric_proposer_max_retries"]
            ),
            feedback_policy=feedback_policy,
            feedback_simulator=self.experiment.feedback_simulator_config(
                feedback_policy,
                vllm_endpoints=self.config.vllm_endpoints
            ),
            prompt_profile=PromptProfile(str(protocol["prompt"])),
            rubric_policy=RubricBankPolicy(str(condition["rubric_policy"])),
            rubric_proposer_model=str(protocol["rubric_proposer_model"]),
            rubric_proposer_base_url=self.config.vllm_endpoints.get(
                str(protocol["rubric_proposer_model"])
            ),
            rubric_semantic_judge_model=str(
                protocol["rubric_semantic_judge_model"]
            ),
            rubric_semantic_judge_max_calls=int(
                protocol["rubric_semantic_judge_max_calls_per_assignment"]
            ),
            rubric_semantic_judge_max_request_bytes=int(
                protocol["rubric_semantic_judge_max_request_bytes_per_call"]
            ),
            rubric_semantic_judge_max_output_tokens=int(
                protocol["rubric_semantic_judge_max_output_tokens_per_call"]
            ),
            rubric_semantic_judge_base_url=self.config.vllm_endpoints.get(
                str(protocol["rubric_semantic_judge_model"])
            ),
            review=str(protocol["review"]),
            judge_model=str(protocol["judge_model"]),
            judge_base_url=self.config.vllm_endpoints.get(
                str(protocol["judge_model"])
            ),
            max_review_chars=protocol["max_review_chars"],  # type: ignore[arg-type]
            resume=resume,
            show_progress=True,
            publish_report=False,
        )

    def _experiment_dir(self, assignment: dict[str, object]) -> Path:
        return self.root / study_experiment_relative_path(assignment)

    def _new_manifest(
        self, assignments: list[dict[str, object]]
    ) -> dict[str, object]:
        return {
            "kind": STUDY_RUN_KIND,
            "status": "pending",
            "experiment_path": str(self.experiment.path),
            "experiment_id": self.experiment.experiment_id,
            "seed_run_dir": str(self.seed_root),
            "paraphrase_run_dir": str(self.paraphrase_root),
            "started_at": _now(),
            "finished_at": None,
            "max_concurrency_last_invocation": self.config.max_concurrency,
            "records": [
                {
                    "assignment_id": str(item["assignment_id"]),
                    "task_id": str(item["task_id"]),
                    "replicate": int(item["replicate"]),
                    "condition_id": str(item["condition_id"]),
                    "execution_order": int(item["execution_order"]),
                    "experiment_dir": str(self._experiment_dir(item).relative_to(self.root)),
                    "status": "pending",
                    "attempt_count": 0,
                    "started_at": None,
                    "finished_at": None,
                }
                for item in assignments
            ],
        }

    def _load_manifest(self) -> dict[str, object]:
        return read_json_object(self.root / "study.json", "study manifest")

    def _write_manifest(self, manifest: dict[str, object]) -> None:
        write_json_atomic(self.root / "study.json", manifest)

    def _validate_manifest_identity(
        self,
        manifest: dict[str, object],
        assignments: list[dict[str, object]],
    ) -> None:
        if (
            manifest.get("kind") != STUDY_RUN_KIND
            or manifest.get("experiment_path") != str(self.experiment.path)
            or manifest.get("experiment_id") != self.experiment.experiment_id
            or manifest.get("seed_run_dir") != str(self.seed_root)
            or manifest.get("paraphrase_run_dir") != str(self.paraphrase_root)
        ):
            raise RuntimeError("study resume identity differs from the experiment")
        records = _records(manifest)
        if [record.get("assignment_id") for record in records] != [
            item["assignment_id"] for item in assignments
        ]:
            raise RuntimeError("study assignment ledger differs from the experiment")
        for record, assignment in zip(records, assignments, strict=True):
            resolve_study_experiment(self.root, record, assignment)


def study_experiment_relative_path(assignment: dict[str, object]) -> Path:
    task_id = assignment.get("task_id")
    replicate = assignment.get("replicate")
    condition_id = assignment.get("condition_id")
    if (
        type(task_id) is not str
        or not task_id
        or Path(task_id).name != task_id
        or type(replicate) is not int
        or replicate < 1
        or type(condition_id) is not str
        or not condition_id
        or Path(condition_id).name != condition_id
    ):
        raise RuntimeError("assignment has an unsafe experiment identity")
    return (
        Path("experiments")
        / task_id
        / f"rep-{replicate:03d}"
        / condition_id
    )


def resolve_study_experiment(
    study_root: Path,
    record: dict[str, object],
    assignment: dict[str, object],
) -> Path:
    expected_relative = study_experiment_relative_path(assignment)
    expected_identity = {
        "assignment_id": assignment.get("assignment_id"),
        "task_id": assignment.get("task_id"),
        "replicate": assignment.get("replicate"),
        "condition_id": assignment.get("condition_id"),
        "execution_order": assignment.get("execution_order"),
        "experiment_dir": expected_relative.as_posix(),
    }
    if any(record.get(key) != value for key, value in expected_identity.items()):
        raise RuntimeError("study record identity differs from its assignment")
    current = study_root
    for component in expected_relative.parts:
        current = current / component
        if current.is_symlink():
            raise RuntimeError(f"study experiment path contains a symlink: {current}")
    return study_root / expected_relative


def validate_completed_revision(
    experiment_dir: Path,
    assignment: dict[str, object],
    experiment: Experiment,
    seed_run_dir: Path,
    paraphrase_run_dir: Path,
    *,
    vllm_endpoints: dict[str, str] | None = None,
    judgment_reuse_root: Path | None = None,
) -> None:
    if experiment_dir.is_symlink() or not experiment_dir.is_dir():
        raise RuntimeError(f"revision is not a regular directory: {experiment_dir}")
    manifest = read_json_object(experiment_dir / "manifest.json", "revision manifest")
    state = read_json_object(experiment_dir / "state.json", "revision state")
    protocol = experiment.protocol
    condition_spec = experiment.condition(str(assignment["condition_id"]))
    policy = FeedbackPolicy(str(condition_spec["feedback_policy"]))
    endpoints = vllm_endpoints or {}
    simulator_config = experiment.feedback_simulator_config(
        policy,
        vllm_endpoints=endpoints
    )
    simulator = (
        SimulatedUserFeedback(simulator_config)
        if simulator_config is not None
        else None
    )
    agent = experiment.agent_config(vllm_endpoints=endpoints)
    task_dir = experiment.task_dir(str(assignment["task_id"])).resolve()
    selection = resolve_paraphrase_selection(
        paraphrase_run_dir,
        experiment,
        str(assignment["task_id"]),
        int(assignment["replicate"]),
    )
    seed = resolve_seed(
        seed_run_dir,
        task_dir,
        int(assignment["replicate"]),
        provider=agent.provider,
        requested_model=agent.model,
    )
    seed_scoring_identity = seed.manifest.get("scoring_identity")
    if not isinstance(seed_scoring_identity, dict):
        raise RuntimeError("revision seed has invalid scoring identity")
    manifest_scoring_identity = manifest.get("initial_member_scoring_identity")
    if not isinstance(manifest_scoring_identity, dict):
        raise RuntimeError("revision manifest has invalid scoring identity")
    seed_contract = extract_seed_scoring_contract(
        seed_scoring_identity,
        context="revision seed",
    )
    manifest_contract = extract_seed_scoring_contract(
        manifest_scoring_identity,
        context="revision manifest",
    )
    if extract_judge_execution_contract(
        seed_contract,
        context="revision seed",
    ) != extract_judge_execution_contract(
        manifest_contract,
        context="revision manifest",
    ):
        raise RuntimeError(
            "revision seed and judge use different execution contracts"
        )
    reuse_store = (
        ExactJudgmentReuseStore(judgment_reuse_root / "judge")
        if judgment_reuse_root is not None
        else None
    )
    simulator_reuse_store = (
        ExactSimulatorReuseStore(judgment_reuse_root / "simulated-user")
        if judgment_reuse_root is not None
        else None
    )
    revision_rounds = int(protocol["revision_rounds"])
    expected_count = revision_rounds + 1
    expected_ids = [f"s{index:03d}" for index in range(expected_count)]
    bank_policy = RubricBankPolicy(str(condition_spec["rubric_policy"]))
    initial_generation = load_rubric_bank(
        experiment_dir,
        0,
        expected_policy=bank_policy,
    )
    if (
        initial_generation.bank.rubric_count != 1
        or initial_generation.bank.items[0].rubric.content_sha256
        != selection.optimizer_sha256
    ):
        raise RuntimeError("initial rubric bank differs from randomized selection")
    judge_config = SubmissionJudgeConfig(
        task_dir=task_dir,
        experiment_dir=experiment_dir,
        benchmark=experiment.benchmark,
        review=str(protocol["review"]),
        judge_model=str(protocol["judge_model"]),
        base_url=endpoints.get(str(protocol["judge_model"])),
        rubric_name=None,
        rubric_set=None,
        rubric_path=selection.optimizer_path,
        max_review_chars=protocol["max_review_chars"],  # type: ignore[arg-type]
        max_retries=int(protocol["judge_max_retries"]),
    )
    initial_rubric = resolve_optimizer_rubric(judge_config)
    initial_judge = FrozenRubricJudge(judge_config, initial_rubric)
    initial_identity = initial_judge.scoring_identity()
    initial_contract = extract_seed_scoring_contract(
        initial_identity,
        context="resolved initial rubric",
    )
    master_judge_config = replace(
        judge_config,
        rubric_name=str(protocol["rubric_name"]),
        rubric_path=None,
    )
    master_rubric = resolve_optimizer_rubric(master_judge_config)
    master_judge = FrozenRubricJudge(master_judge_config, master_rubric)
    master_contract = extract_seed_scoring_contract(
        master_judge.scoring_identity(),
        context="resolved master rubric",
    )
    if (
        initial_rubric.sha256 != selection.optimizer_sha256
        or master_rubric.sha256 != selection.master_sha256
        or manifest_scoring_identity != initial_identity
        or manifest_contract != initial_contract
    ):
        raise RuntimeError(
            "resolved study rubric identities differ from the sealed manifest"
        )

    def bank_member_judge(item, generation_round: int):
        if item.rubric.content_sha256 == initial_rubric.sha256:
            return initial_rubric, initial_judge
        member_path = (
            experiment_dir
            / "rubric-banks"
            / f"bank-{generation_round:04d}"
            / "members"
            / f"{item.rubric.content_sha256}.txt"
        )
        member_rubric = FrozenRubric(
            text=item.rubric.content,
            sha256=item.rubric.content_sha256,
            source=RUBRIC_PATH_SOURCE,
            rubric_set_id=None,
            rubric_id=None,
            structured_rubric_sha256=None,
            manifest_sha256=None,
        )
        member_config = replace(
            judge_config,
            rubric_path=member_path,
        )
        return member_rubric, FrozenRubricJudge(member_config, member_rubric)
    manifest_expectations = {
        "kind": "rubric-gen-submission-revision-experiment",
        "experiment_id": experiment.experiment_id,
        "benchmark": str(experiment.benchmark),
        "assignment_id": assignment.get("assignment_id"),
        "condition_id": assignment.get("condition_id"),
        "task_id": assignment.get("task_id"),
        "task_dir": str(task_dir),
        "replicate": assignment.get("replicate"),
        "execution_order": assignment.get("execution_order"),
        "revision_rounds": revision_rounds,
        "provider": agent.provider,
        "model": agent.model,
        "executable": agent.executable,
        "isolation": "codex-custom-permission-profile",
        "command_network_access": False,
        "web_search": False,
        "reasoning_effort": agent.reasoning_effort,
        "service_tier": agent.service_tier,
        "solver_base_url": agent.base_url,
        "turn_timeout_seconds": agent.timeout_seconds,
        "feedback_policy": condition_spec["feedback_policy"],
        "prompt": protocol["prompt"],
        "rubric_policy": condition_spec["rubric_policy"],
        "rubric_proposer_model": protocol["rubric_proposer_model"],
        "rubric_proposer_base_url": endpoints.get(
            str(protocol["rubric_proposer_model"])
        ),
        "rubric_proposer_max_retries": protocol["rubric_proposer_max_retries"],
        "rubric_semantic_judge_model": protocol["rubric_semantic_judge_model"],
        "rubric_semantic_judge_base_url": endpoints.get(
            str(protocol["rubric_semantic_judge_model"])
        ),
        "rubric_semantic_judge_max_calls": protocol[
            "rubric_semantic_judge_max_calls_per_assignment"
        ],
        "rubric_semantic_judge_max_request_bytes": protocol[
            "rubric_semantic_judge_max_request_bytes_per_call"
        ],
        "rubric_semantic_judge_max_output_tokens": protocol[
            "rubric_semantic_judge_max_output_tokens_per_call"
        ],
        "rubric_generation_implementation_identity": (
            rubric_generation_implementation_identity()
        ),
        "review": protocol["review"],
        "judge_model": protocol["judge_model"],
        "judge_base_url": endpoints.get(str(protocol["judge_model"])),
        "judge_max_retries": protocol["judge_max_retries"],
        "max_review_chars": protocol["max_review_chars"],
        "initial_rubric_path": str(selection.optimizer_path.resolve()),
        "initial_bank_sha256": initial_generation.bank.content_sha256,
        "initial_bank_member_count": initial_generation.bank.rubric_count,
        "initial_member_scoring_identity": initial_identity,
        "master_rubric_name": protocol["rubric_name"],
        "master_rubric_sha256": selection.master_sha256,
        "instruction_sha256": sha256_file(task_dir / "instruction.md"),
        "data_sha256": tree_sha256(task_dir / "environment" / "data"),
        "seed_run_dir": str(seed.root),
        "seed_sha256": seed.sha256,
        "submission_count": expected_count,
        "live_workspace_removed": True,
    }
    if simulator_config is not None:
        manifest_expectations["feedback_simulator"] = simulator_config.identity()
    if (
        set(manifest) != revision_manifest_keys(policy.value)
        or any(
            manifest.get(key) != value
            for key, value in manifest_expectations.items()
        )
        or type(manifest.get("live_workspace_dir")) is not str
        or type(manifest.get("session_id")) is not str
        or not manifest["session_id"]
        or type(manifest.get("effective_solver_model")) is not str
        or not manifest["effective_solver_model"]
        or set(state) != {
            "phase", "next_turn_index", "session_id",
            "effective_solver_model", "submission_ids", "scores",
            "fixed_original_scores", "judge_attempts", "next_prompt",
        }
        or state.get("phase") != "completed"
        or state.get("submission_ids") != expected_ids
        or state.get("next_turn_index") != expected_count
        or state.get("session_id") != manifest.get("session_id")
        or state.get("effective_solver_model")
        != manifest.get("effective_solver_model")
        or not isinstance(state.get("scores"), list)
        or len(state["scores"]) != expected_count
        or any(
            isinstance(score, bool)
            or not isinstance(score, Real)
            or not math.isfinite(float(score))
            or not 0 <= float(score) <= 100
            for score in state["scores"]
        )
        or not isinstance(state.get("fixed_original_scores"), list)
        or len(state["fixed_original_scores"]) != expected_count
        or any(
            isinstance(score, bool)
            or not isinstance(score, Real)
            or not math.isfinite(float(score))
            or not 0 <= float(score) <= 100
            for score in state["fixed_original_scores"]
        )
        or not isinstance(state.get("judge_attempts"), dict)
        or set(state["judge_attempts"]) != set(expected_ids)
        or any(
            type(attempt) is not str
            or len(attempt) != 32
            or any(character not in "0123456789abcdef" for character in attempt)
            for attempt in state["judge_attempts"].values()
        )
    ):
        raise RuntimeError(f"revision is not complete: {experiment_dir}")
    submissions = experiment_dir / "submissions"
    if submissions.is_symlink() or not submissions.is_dir():
        raise RuntimeError("revision submission root is invalid")
    observed = sorted(path.name for path in submissions.iterdir())
    if observed != expected_ids:
        raise RuntimeError("revision submission set is incomplete")
    rubric_generation_root = experiment_dir / "rubric-generations"
    if bank_policy is RubricBankPolicy.FIXED:
        if os.path.lexists(rubric_generation_root):
            raise RuntimeError(
                "rubric-generations is invalid for a fixed rubric policy"
            )
    else:
        generation_indices = (
            range(1, 2)
            if bank_policy is RubricBankPolicy.OFFLINE_ELICITATION
            else range(1, revision_rounds)
        )
        expected_rubric_generations = [
            name
            for index in generation_indices
            for name in (
                f"bank-{index:04d}",
                f"bank-{index:04d}.provider-attempts.json",
            )
        ]
        if not expected_rubric_generations:
            if os.path.lexists(rubric_generation_root):
                raise RuntimeError(
                    "a no-update elicitation arm has rubric generation artifacts"
                )
        elif (
            rubric_generation_root.is_symlink()
            or not rubric_generation_root.is_dir()
            or sorted(path.name for path in rubric_generation_root.iterdir())
            != expected_rubric_generations
            or any(path.is_symlink() for path in rubric_generation_root.iterdir())
            or any(
                (
                    path.name.endswith(".provider-attempts.json")
                    and not path.is_file()
                )
                or (
                    not path.name.endswith(".provider-attempts.json")
                    and not path.is_dir()
                )
                for path in rubric_generation_root.iterdir()
            )
        ):
            raise RuntimeError("rubric generation set is incomplete")
    feedback_root = experiment_dir / "feedback"
    expected_feedback = [f"{submission_id}.json" for submission_id in expected_ids]
    if (
        feedback_root.is_symlink()
        or not feedback_root.is_dir()
        or sorted(path.name for path in feedback_root.iterdir()) != expected_feedback
    ):
        raise RuntimeError("revision feedback set is incomplete")
    bank_evaluation_root = experiment_dir / "bank-evaluations"
    if (
        bank_evaluation_root.is_symlink()
        or not bank_evaluation_root.is_dir()
        or sorted(path.name for path in bank_evaluation_root.iterdir())
        != expected_feedback
    ):
        raise RuntimeError("revision bank evaluation set is incomplete")
    generation_root = experiment_dir / "feedback-generations"
    if policy is FeedbackPolicy.USER_SIMULATOR:
        expected_generations = [
            f"{submission_id}.json" for submission_id in expected_ids
        ]
        if (
            generation_root.is_symlink()
            or not generation_root.is_dir()
            or sorted(path.name for path in generation_root.iterdir())
            != expected_generations
        ):
            raise RuntimeError("simulated-user generation set is incomplete")
    elif os.path.lexists(generation_root):
        raise RuntimeError(
            "feedback-generations is only valid for user_simulator feedback"
        )
    prompt_profile = PromptProfile(str(protocol["prompt"]))
    generation_proposer = (
        None
        if bank_policy is RubricBankPolicy.FIXED
        else RubricBankProposer(
            benchmark=experiment.benchmark,
            model=str(protocol["rubric_proposer_model"]),
            base_url=endpoints.get(str(protocol["rubric_proposer_model"])),
            semantic_judge_model=str(protocol["rubric_semantic_judge_model"]),
            semantic_judge_base_url=endpoints.get(
                str(protocol["rubric_semantic_judge_model"])
            ),
            semantic_judge_max_calls=int(
                protocol["rubric_semantic_judge_max_calls_per_assignment"]
            ),
            semantic_judge_max_request_bytes=int(
                protocol["rubric_semantic_judge_max_request_bytes_per_call"]
            ),
            semantic_judge_max_output_tokens=int(
                protocol["rubric_semantic_judge_max_output_tokens_per_call"]
            ),
            service_tier=(
                agent.service_tier
                if endpoints.get(str(protocol["rubric_proposer_model"])) is None
                else None
            ),
            max_retries=int(protocol["rubric_proposer_max_retries"]),
        )
    )
    instruction = (task_dir / "instruction.md").read_text(encoding="utf-8")
    for submission_id in expected_ids:
        submission = submissions / submission_id
        verify_submission_snapshot(submission)
        snapshot = read_json_object(
            submission / "snapshot.json", "submission snapshot"
        )
        status = read_json_object(submission / "status.json", "submission status")
        feedback = experiment_dir / "feedback" / f"{submission_id}.json"
        if feedback.is_symlink() or not feedback.is_file():
            raise RuntimeError(f"missing feedback for {submission_id}")
        index = int(submission_id[1:])
        generation_round = (
            0
            if bank_policy is RubricBankPolicy.FIXED
            else (
                1
                if bank_policy is RubricBankPolicy.OFFLINE_ELICITATION
                else max(0, index - 1)
            )
        )
        generation = load_rubric_bank(
            experiment_dir,
            generation_round,
            expected_policy=bank_policy,
        )
        if generation_round > 0:
            prior = load_rubric_bank(
                experiment_dir,
                generation_round - 1,
                expected_policy=bank_policy,
            )
            generation.bank.validate_lineage(prior.bank)
            assert generation_proposer is not None
            validated_generation = generation_proposer.elicit_rubric(
                instruction=instruction,
                current_bank=prior.bank,
                policy=bank_policy,
                generation_round=generation_round,
                output_dir=rubric_generation_root,
                artifact_history=build_elicitation_artifact_history(
                    online=(
                        bank_policy is RubricBankPolicy.ONLINE_ELICITATION
                    ),
                    seed_set=seed.root,
                    task_dir=task_dir,
                    experiment_dir=experiment_dir,
                    benchmark=get_submission_benchmark(experiment.benchmark),
                    provider=agent.provider,
                    requested_model=agent.model,
                    assignment_id=str(assignment["assignment_id"]),
                    generation_round=generation_round,
                ),
                source_boundary=(
                    generation_round
                    if bank_policy is RubricBankPolicy.ONLINE_ELICITATION
                    else None
                ),
            )
            if validated_generation != generation:
                raise RuntimeError(
                    "rubric generation disagrees with the active bank"
                )
        bank = generation.bank
        member_artifacts: dict[str, tuple[Path, Path]] = {}
        attempt = str(state["judge_attempts"][submission_id])
        for item in bank.items:
            rubric_hash = item.rubric.content_sha256
            if (
                index == 0
                and seed_contract == initial_contract
                and seed_contract["rendered_rubric_sha256"] == rubric_hash
            ):
                validation_path, evaluation_path, _ = seed.judgment
            elif reuse_store is not None:
                _, member_judge = bank_member_judge(item, generation_round)
                review_text, answer_text = member_judge.review_inputs(submission)
                expected_request = exact_judgment_request(
                    task_id=str(assignment["task_id"]),
                    replicate=int(assignment["replicate"]),
                    rubric_sha256=rubric_hash,
                    review_text=review_text,
                    answer_text=answer_text,
                    scoring_identity=member_judge.scoring_identity(),
                )
                reused = reuse_store.validate_alias(
                    experiment_dir
                    / "judgment-aliases"
                    / submission_id
                    / (reuse_store.request_sha256(expected_request) + ".json"),
                    assignment_id=str(assignment["assignment_id"]),
                    replicate=int(assignment["replicate"]),
                    submission_id=submission_id,
                    rubric_sha256=rubric_hash,
                    expected_request=expected_request,
                )
                validation_path = reused.artifacts.score_validation_path
                evaluation_path = reused.artifacts.evaluation_path
            else:
                evaluation_root = (
                    experiment_dir
                    / "evaluations"
                    / submission_id
                    / rubric_hash
                    / attempt
                    / "run"
                    / "judges"
                    / str(protocol["review"])
                    / str(assignment["task_id"])
                )
                validation_path = evaluation_root / "score_validation.json"
                evaluation_path = evaluation_root / "evaluation.json"
            if (
                validation_path.is_symlink()
                or evaluation_path.is_symlink()
                or not validation_path.is_file()
                or not evaluation_path.is_file()
            ):
                raise RuntimeError(
                    "scoring artifacts are incomplete for "
                    f"{submission_id}/{rubric_hash}"
                )
            validation_record = read_json_object(
                validation_path,
                "score validation",
            )
            if (
                validation_record.get("evaluation_sha256")
                != sha256_file(evaluation_path)
            ):
                raise RuntimeError(
                    "evaluation disagrees with score validation: "
                    f"{submission_id}/{rubric_hash}"
                )
            member_artifacts[rubric_hash] = (validation_path, evaluation_path)

        fixed_score = state["fixed_original_scores"][index]
        same_base_and_master = (
            initial_generation.bank.items[0].rubric.content_sha256
            == selection.master_sha256
        )
        if index == 0 and seed_contract == master_contract:
            fixed_validation_path, fixed_evaluation_path, _ = seed.judgment
        elif same_base_and_master and (
            index == 0 or bank_policy is RubricBankPolicy.FIXED
        ):
            try:
                fixed_validation_path, fixed_evaluation_path = member_artifacts[
                    selection.master_sha256
                ]
            except KeyError as exc:
                raise RuntimeError(
                    f"active bank lacks the master judgment: {submission_id}"
                ) from exc
        elif reuse_store is not None:
            review_text, answer_text = master_judge.review_inputs(submission)
            expected_request = exact_judgment_request(
                task_id=str(assignment["task_id"]),
                replicate=int(assignment["replicate"]),
                rubric_sha256=selection.master_sha256,
                review_text=review_text,
                answer_text=answer_text,
                scoring_identity=master_judge.scoring_identity(),
            )
            reused = reuse_store.validate_alias(
                experiment_dir
                / "judgment-aliases"
                / submission_id
                / (reuse_store.request_sha256(expected_request) + ".json"),
                assignment_id=str(assignment["assignment_id"]),
                replicate=int(assignment["replicate"]),
                submission_id=submission_id,
                rubric_sha256=selection.master_sha256,
                expected_request=expected_request,
            )
            fixed_validation_path = reused.artifacts.score_validation_path
            fixed_evaluation_path = reused.artifacts.evaluation_path
        else:
            fixed_attempt = fixed_original_attempt_id(
                str(assignment["assignment_id"]),
                submission_id,
                selection.master_sha256,
            )
            fixed_root = (
                experiment_dir
                / "evaluations"
                / submission_id
                / selection.master_sha256
                / fixed_attempt
                / "run"
                / "judges"
                / str(protocol["review"])
                / str(assignment["task_id"])
            )
            fixed_validation_path = fixed_root / "score_validation.json"
            fixed_evaluation_path = fixed_root / "evaluation.json"
        if (
            fixed_validation_path.is_symlink()
            or fixed_evaluation_path.is_symlink()
            or not fixed_validation_path.is_file()
            or not fixed_evaluation_path.is_file()
        ):
            raise RuntimeError(
                f"fixed-original scoring artifacts are incomplete for "
                f"{submission_id}"
            )
        fixed_validation = read_json_object(
            fixed_validation_path,
            "fixed-original score validation",
        )
        if (
            fixed_validation.get("evaluation_sha256")
            != sha256_file(fixed_evaluation_path)
            or fixed_validation.get("score") != fixed_score
        ):
            raise RuntimeError(
                f"fixed-original score disagrees with scoring artifacts: "
                f"{submission_id}"
            )
        if policy is FeedbackPolicy.USER_SIMULATOR:
            assert simulator is not None
            generation_path = generation_root / f"{submission_id}.json"
            if generation_path.is_symlink() or not generation_path.is_file():
                raise RuntimeError(
                    f"missing simulated-user generation for {submission_id}"
                )
            comment = simulator.validate(
                (
                    read_json_object(
                        generation_path,
                        "simulated-user generation",
                    )
                ),
                experiment_id=experiment.experiment_id,
                assignment_id=str(assignment["assignment_id"]),
                submission_id=submission_id,
                generation_round=generation_round,
                bank=bank,
            )
            if simulator_reuse_store is not None:
                instruction = (task_dir / "instruction.md").read_text(
                    encoding="utf-8"
                )
                current_submission = get_submission_benchmark(
                    experiment.benchmark
                ).render_submission(submission / "workspace")
                expected_simulator_request = exact_simulator_request(
                    experiment_id=experiment.experiment_id,
                    task_id=str(assignment["task_id"]),
                    replicate=int(assignment["replicate"]),
                    instruction=instruction,
                    bank_sha256=bank.content_sha256,
                    current_submission=current_submission,
                    simulator_identity=simulator.identity(),
                )
                reused_simulator = simulator_reuse_store.validate_alias(
                    experiment_dir
                    / "simulated-user-aliases"
                    / f"{submission_id}.json",
                    assignment_id=str(assignment["assignment_id"]),
                    replicate=int(assignment["replicate"]),
                    submission_id=submission_id,
                    expected_request=expected_simulator_request,
                )
                expected_simulator_generation = (
                    simulator_reuse_store.assignment_record(
                        reused_simulator,
                        experiment_id=experiment.experiment_id,
                        assignment_id=str(assignment["assignment_id"]),
                        submission_id=submission_id,
                        generation_round=generation_round,
                        bank_sha256=bank.content_sha256,
                        simulator_identity=simulator.identity(),
                    )
                )
                if read_json_object(
                    generation_path,
                    "simulated-user generation",
                ) != expected_simulator_generation:
                    raise RuntimeError(
                        "simulated-user generation differs from its shared artifact"
                    )
            projected = project_bank_simulated_user_feedback(
                bank,
                {
                    rubric_hash: paths[0]
                    for rubric_hash, paths in member_artifacts.items()
                },
                comment,
                fixed_original_score=float(fixed_score),
                prompt_profile=prompt_profile,
                benchmark=experiment.benchmark,
            )
        else:
            projected = project_bank_feedback(
                bank,
                member_artifacts,
                policy,
                fixed_original_artifacts=(
                    fixed_validation_path,
                    fixed_evaluation_path,
                ),
                fixed_original_rubric_text=selection.master_path.read_text(
                    encoding="utf-8"
                ),
                fixed_original_rubric_sha256=selection.master_sha256,
                prompt_profile=prompt_profile,
                benchmark=experiment.benchmark,
            )
        composition = compose_bank_score(
            bank,
            {
                rubric_hash: paths[0]
                for rubric_hash, paths in member_artifacts.items()
            },
            float(fixed_score),
        )
        bank_members: dict[str, dict[str, object]] = {}
        for item in bank.items:
            rubric_hash = item.rubric.content_sha256
            validation_path, evaluation_path = member_artifacts[rubric_hash]
            member_score = read_json_object(
                validation_path,
                "score validation",
            ).get("score")
            if (
                isinstance(member_score, bool)
                or not isinstance(member_score, Real)
                or not math.isfinite(float(member_score))
                or not 0 <= float(member_score) <= 100
            ):
                raise RuntimeError("bank member score is invalid")
            member_composition = composition.members[rubric_hash]
            bank_members[rubric_hash] = {
                "weight": item.weight,
                "judge_score": member_score,
                "elicited_penalty": member_composition.elicited_penalty,
                "score": member_composition.score,
                "score_validation_sha256": sha256_file(validation_path),
                "evaluation_sha256": sha256_file(evaluation_path),
            }
        expected_bank_evaluation = {
            "kind": "canonical-original-plus-elicited-penalty-evaluation",
            "submission_id": submission_id,
            "generation_round": bank.generation_round,
            "bank_sha256": bank.content_sha256,
            "dispatch_preflight": preflight_bank_dispatch(
                bank,
                benchmark=experiment.benchmark,
                review_text=(
                    next(iter(member_artifacts.values()))[0].parent
                    / "judge_input_trace.md"
                ).read_text(encoding="utf-8"),
                answer_text=(
                    next(iter(member_artifacts.values()))[0].parent
                    / "judge_input_answer.txt"
                ).read_text(encoding="utf-8"),
            ),
            "members": bank_members,
            "canonical_original_score": composition.canonical_original_score,
            "weighted_elicited_penalty": (
                composition.weighted_elicited_penalty
            ),
            "score": composition.score,
        }
        if read_json_object(
            experiment_dir / "bank-evaluations" / f"{submission_id}.json",
            "bank evaluation",
        ) != expected_bank_evaluation:
            raise RuntimeError(
                f"bank evaluation disagrees with members: {submission_id}"
            )
        if (
            read_json_object(feedback, "revision feedback") != projected.payload
            or state["scores"][index] != projected.score
        ):
            raise RuntimeError(
                f"feedback disagrees with scoring artifacts: {submission_id}"
            )
    expected_banks = _expected_bank_names(condition_spec, expected_count)
    bank_root = experiment_dir / "rubric-banks"
    if (
        bank_root.is_symlink()
        or not bank_root.is_dir()
        or sorted(path.name for path in bank_root.iterdir()) != expected_banks
        or any(
            path.is_symlink() or not path.is_dir()
            for path in bank_root.iterdir()
        )
    ):
        raise RuntimeError("revision rubric bank set is incomplete")


def _expected_bank_names(
    condition_spec: dict[str, object], submission_count: int
) -> list[str]:
    policy = RubricBankPolicy(str(condition_spec["rubric_policy"]))
    if policy is RubricBankPolicy.FIXED:
        return ["bank-0000"]
    if policy is RubricBankPolicy.OFFLINE_ELICITATION:
        return ["bank-0000", "bank-0001"]
    return [
        f"bank-{index:04d}"
        for index in range(max(1, submission_count - 1))
    ]


@contextmanager
def _exclusive_study_lease(root: Path):
    """Hold the one-writer lease for a study invocation."""

    lock_path = root / _STUDY_LEASE_NAME
    flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o664)
    locked = False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError(f"study lease is not a regular file: {lock_path}")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except BlockingIOError:
            os.lseek(descriptor, 0, os.SEEK_SET)
            owner = os.read(descriptor, 4096).decode("utf-8", errors="replace").strip()
            detail = f": {owner}" if owner else ""
            raise RuntimeError(f"study already has an active invocation{detail}") from None
        owner = json.dumps(
            {
                "hostname": socket.gethostname(),
                "pid": os.getpid(),
                "started_at": _now(),
            },
            sort_keys=True,
        ).encode("utf-8")
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.write(descriptor, owner + b"\n")
        os.fsync(descriptor)
        yield
    finally:
        if locked:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _reclaim_interrupted_records(manifest: dict[str, object]) -> int:
    """Make records abandoned by the previous leased invocation retryable."""

    reclaimed = 0
    for record in _records(manifest):
        if record.get("status") != "running":
            continue
        owner_hostname = record.get("hostname")
        owner_pid = record.get("pid")
        record.update(
            {
                "status": "failed",
                "finished_at": _now(),
                "error_type": "InterruptedStudyInvocation",
                "error": (
                    "reclaimed assignment from interrupted study invocation "
                    f"on {owner_hostname} pid {owner_pid}"
                ),
            }
        )
        record.pop("traceback", None)
        reclaimed += 1
    return reclaimed


def _report_noncompleted_records(manifest: dict[str, object]) -> None:
    for record in _records(manifest):
        status = str(record.get("status"))
        if status == "completed":
            continue
        print(
            f"assignment {status}: {record.get('assignment_id')}: "
            f"{record.get('error_type')}: {record.get('error')}",
            file=sys.stderr,
        )


def _records(manifest: dict[str, object]) -> list[dict[str, object]]:
    records = manifest.get("records")
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise RuntimeError("study manifest records are invalid")
    return records


def _record_for(manifest: dict[str, object], assignment_id: str) -> dict[str, object]:
    matches = [
        item for item in _records(manifest) if item.get("assignment_id") == assignment_id
    ]
    if len(matches) != 1:
        raise RuntimeError(f"study record is missing or duplicated: {assignment_id}")
    return matches[0]


def _now() -> str:
    return datetime.now().astimezone().isoformat()
