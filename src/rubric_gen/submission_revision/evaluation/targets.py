"""Load completed assignments for revision evaluation."""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from numbers import Real
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.submission_revision.artifacts import (
    read_json_object,
    revision_manifest_keys,
)
from rubric_gen.submission_revision import paraphrase_validation
from rubric_gen.submission_revision.paraphrase_validation import ParaphraseSelection
from rubric_gen.submission_revision.prompts import prompt_implementation_sha256
from rubric_gen.submission_revision.evaluation.jobs import (
    EvaluationConfig,
    EvaluationTarget,
)
from rubric_gen.submission_revision.rubric_generation import (
    RubricGeneration,
    RubricPolicy,
)
from rubric_gen.submission_revision.rubric_generation_store import (
    load_rubric_generation,
    rubric_generation_directory,
)
from rubric_gen.submission_revision.study_layout import resolve_study_experiment
from rubric_gen.submission_revision.seeds import seed_generator_identity
from rubric_gen.submission_revision.assignments import ExperimentAssignment

def load_evaluation_targets(
    config: EvaluationConfig,
) -> tuple[EvaluationTarget, ...]:
    study_root = config.study_dir.resolve()
    study = read_json_object(study_root / "study.json", "study manifest")
    study_experiment_id = study.get("experiment_id")
    if (
        study.get("kind") != "rubric-gen-randomized-revision-study"
        or study.get("status") not in {"completed", "failed"}
        or type(study_experiment_id) is not str
        or not study_experiment_id
        or study.get("experiment_path") != str(config.experiment.path)
        or type(study.get("seed_run_dir")) is not str
        or study.get("paraphrase_run_dir") != str(config.paraphrase_dir.resolve())
        or study.get("pretreatment_rubric_root")
        != str(study_root / "pretreatment-rubrics")
        or not isinstance(study.get("records"), list)
    ):
        raise RuntimeError("revision evaluation requires a terminal source study")
    raw_records = study["records"]
    if any(not isinstance(record, dict) for record in raw_records):
        raise RuntimeError("evaluation source study records are invalid")
    records = {str(record.get("assignment_id")): record for record in raw_records}
    configured_assignments = config.experiment.assignments
    assignment_ids = {
        assignment.assignment_id for assignment in configured_assignments
    }
    if len(records) != len(raw_records) or set(records) != assignment_ids:
        raise RuntimeError("evaluation source study ledger differs from the experiment")
    if any(
        record.get("status") not in {"completed", "failed", "invalid"}
        for record in records.values()
    ):
        raise RuntimeError(
            "revision evaluation requires every source assignment to be terminal"
        )
    assignments = tuple(
        assignment
        for assignment in configured_assignments
        if records[assignment.assignment_id].get("status") == "completed"
    )
    if not assignments:
        raise RuntimeError("revision evaluation has no completed assignments")
    selection_keys = {assignment.task_id for assignment in assignments}
    selections = {
        task_id: paraphrase_validation.resolve_paraphrase_selection(
            config.paraphrase_dir,
            config.experiment,
            task_id,
        )
        for task_id in sorted(selection_keys)
    }
    targets: list[EvaluationTarget | None] = [None] * len(assignments)
    with TerminalProgress(
        total=len(assignments),
        description="evaluation target loading",
        unit="assignment",
    ) as progress:
        futures = {}
        with ThreadPoolExecutor(
            max_workers=min(config.max_concurrency, len(assignments))
        ) as pool:
            for index, assignment in enumerate(assignments):
                assignment_id = assignment.assignment_id
                record = records.get(assignment_id)
                if record is None or record.get("status") != "completed":
                    raise RuntimeError(
                        f"study assignment is not complete: {assignment_id}"
                    )
                selection_key = assignment.task_id
                future = pool.submit(
                    _load_evaluation_target,
                    config,
                    study_root,
                    study_experiment_id,
                    assignment,
                    record,
                    selections[selection_key],
                )
                futures[future] = (index, assignment_id)
            for future in as_completed(futures):
                index, assignment_id = futures[future]
                targets[index] = future.result()
                progress.set_status(assignment_id)
                progress.update()
    if any(target is None for target in targets):
        raise RuntimeError("evaluation target loading did not return every assignment")
    return tuple(target for target in targets if target is not None)


def _load_evaluation_target(
    config: EvaluationConfig,
    study_root: Path,
    study_experiment_id: str,
    assignment: ExperimentAssignment,
    record: dict[str, object],
    selection: ParaphraseSelection,
) -> EvaluationTarget:
    assignment_id = assignment.assignment_id
    experiment_dir = resolve_study_experiment(
        study_root,
        record,
        assignment,
    )
    state = _load_terminal_revision_state(
        experiment_dir,
        assignment,
        config,
        selection,
        study_experiment_id,
    )
    submission_ids = state["submission_ids"]
    scores = state["scores"]
    fixed_original_scores = state["fixed_original_scores"]
    task_id = assignment.task_id
    replicate = assignment.replicate
    condition = config.experiment.condition(assignment.condition_id)
    rubric_policy = RubricPolicy(str(condition["rubric_policy"]))
    initial_generation_round = _active_generation_round(rubric_policy, 0)
    final_generation_round = _active_generation_round(
        rubric_policy,
        len(submission_ids) - 1,
    )
    generations = {
        generation_round: load_rubric_generation(
            experiment_dir,
            generation_round,
            expected_policy=rubric_policy,
        )
        for generation_round in {
            0,
            initial_generation_round,
            final_generation_round,
        }
    }
    selected_generation = generations[0]
    initial_generation = generations[initial_generation_round]
    final_generation = generations[final_generation_round]
    initial_manifest_path = (
        rubric_generation_directory(experiment_dir, initial_generation_round)
        / "manifest.json"
    ).resolve()
    final_manifest_path = (
        rubric_generation_directory(experiment_dir, final_generation_round)
        / "manifest.json"
    ).resolve()
    if selected_generation.rubric.content_sha256 != selection.optimizer_sha256:
        raise RuntimeError(
            "initial generation differs from the selected rubric: "
            f"{assignment_id}"
        )
    return EvaluationTarget(
        study_experiment_id=study_experiment_id,
        assignment_id=assignment_id,
        task_id=task_id,
        replicate=replicate,
        solver_id=assignment.solver_id,
        condition_id=assignment.condition_id,
        rubric_policy=rubric_policy,
        benchmark=config.experiment.benchmark,
        experiment_dir=experiment_dir.resolve(),
        task_dir=config.experiment.task_dir(task_id).resolve(),
        review=str(config.experiment.protocol["review"]),
        max_review_chars=config.experiment.protocol["max_review_chars"],  # type: ignore[arg-type]
        initial_submission=(
            experiment_dir / "submissions" / str(submission_ids[0])
        ).resolve(),
        final_submission=(
            experiment_dir / "submissions" / str(submission_ids[-1])
        ).resolve(),
        submission_ids=tuple(str(value) for value in submission_ids),
        active_scores=tuple(float(value) for value in scores),
        fixed_original_scores=tuple(
            float(value) for value in fixed_original_scores
        ),
        initial_generation=initial_generation,
        final_generation=final_generation,
        initial_manifest_path=initial_manifest_path,
        final_manifest_path=final_manifest_path,
        initial_manifest_sha256=sha256_file(initial_manifest_path),
        final_manifest_sha256=sha256_file(final_manifest_path),
        selection=selection,
    )


def _load_terminal_revision_state(
    experiment_dir: Path,
    assignment: ExperimentAssignment,
    config: EvaluationConfig,
    selection: ParaphraseSelection,
    study_experiment_id: str,
) -> dict[str, object]:
    """Load terminal revision metadata without scanning submission contents."""

    if experiment_dir.is_symlink() or not experiment_dir.is_dir():
        raise RuntimeError(
            f"revision is not a regular directory: {experiment_dir}"
        )
    manifest = read_json_object(
        experiment_dir / "manifest.json",
        "revision manifest",
    )
    state = read_json_object(experiment_dir / "state.json", "revision state")
    experiment = config.experiment
    protocol = experiment.protocol
    condition = experiment.condition(assignment.condition_id)
    agent = experiment.solver_config(
        assignment.solver_id,
        quiet=True,
    )
    seed_agent = experiment.seed_agent_config(quiet=True)
    manifest_identity = {
        "kind": "rubric-gen-submission-revision-experiment",
        "experiment_id": study_experiment_id,
        "benchmark": str(experiment.benchmark),
        "assignment_id": assignment.assignment_id,
        "condition_id": assignment.condition_id,
        "solver_id": assignment.solver_id,
        "task_id": assignment.task_id,
        "replicate": assignment.replicate,
        "execution_order": assignment.execution_order,
        "task_dir": str(experiment.task_dir(assignment.task_id)),
        "max_revisions": protocol["max_revisions"],
        "min_revisions": protocol["min_revisions"],
        "provider": agent.provider,
        "model": agent.model,
        "executable": agent.executable,
        "reasoning_effort": agent.reasoning_effort,
        "service_tier": agent.service_tier,
        "turn_timeout_seconds": agent.timeout_seconds,
        "feedback_policy": condition["feedback_policy"],
        "prompt": protocol["prompt"],
        "prompt_implementation_sha256": prompt_implementation_sha256(),
        "rubric_policy": condition["rubric_policy"],
        "rubric_proposer_model": protocol["rubric_proposer_model"],
        "rubric_proposer_max_retries": protocol[
            "rubric_proposer_max_retries"
        ],
        "review": protocol["review"],
        "judge_model": protocol["judge_model"],
        "max_review_chars": protocol["max_review_chars"],
        "initial_rubric_path": str(selection.optimizer_path.resolve()),
        "initial_rubric_sha256": selection.optimizer_sha256,
        "master_rubric_name": protocol["rubric_name"],
        "master_rubric_sha256": selection.master_sha256,
        "seed_generator": seed_generator_identity(seed_agent),
        "live_workspace_removed": True,
    }
    if (
        set(manifest) != revision_manifest_keys(str(condition["feedback_policy"]))
        or any(
        manifest.get(key) != value
        for key, value in manifest_identity.items()
        )
    ):
        raise RuntimeError(
            f"revision is not in the current format: {experiment_dir}"
        )
    submission_ids = state.get("submission_ids")
    scores = state.get("scores")
    fixed_original_scores = state.get("fixed_original_scores")
    if (
        set(state) != {
            "phase",
            "next_turn_index",
            "session_id",
            "effective_solver_model",
            "submission_ids",
            "scores",
            "fixed_original_scores",
            "judge_attempts",
            "next_prompt",
            "stop_reason",
        }
        or
        state.get("phase") != "completed"
        or not isinstance(submission_ids, list)
        or not submission_ids
        or any(type(value) is not str for value in submission_ids)
        or submission_ids
        != [f"s{index:03d}" for index in range(len(submission_ids))]
        or state.get("next_turn_index") != len(submission_ids)
        or state.get("stop_reason") not in {"no_change", "max_revisions"}
        or (
            state.get("stop_reason") == "no_change"
            and len(submission_ids) < int(protocol["min_revisions"])
        )
        or state.get("next_prompt") != ""
        or manifest.get("submission_count") != len(submission_ids)
        or state.get("session_id") != manifest.get("session_id")
        or state.get("effective_solver_model")
        != manifest.get("effective_solver_model")
        or not isinstance(scores, list)
        or len(scores) != len(submission_ids)
        or any(
            isinstance(score, bool)
            or not isinstance(score, Real)
            or not math.isfinite(float(score))
            or not 0 <= float(score) <= 100
            for score in scores
        )
        or not isinstance(fixed_original_scores, list)
        or len(fixed_original_scores) != len(submission_ids)
        or any(
            isinstance(score, bool)
            or not isinstance(score, Real)
            or not math.isfinite(float(score))
            or not 0 <= float(score) <= 100
            for score in fixed_original_scores
        )
    ):
        raise RuntimeError(f"revision artifacts are invalid: {experiment_dir}")
    submissions = experiment_dir / "submissions"
    if submissions.is_symlink() or not submissions.is_dir():
        raise RuntimeError(f"revision submissions are invalid: {experiment_dir}")
    for submission_id in submission_ids:
        submission = submissions / submission_id
        if submission.is_symlink() or not submission.is_dir():
            raise RuntimeError(f"revision submission is missing: {submission}")
    return state


def _active_generation_round(
    rubric_policy: RubricPolicy,
    checkpoint: int,
) -> int:
    if checkpoint < 0:
        raise ValueError("active rubric checkpoint must be nonnegative")
    if rubric_policy is RubricPolicy.FIXED or checkpoint == 0:
        return 0
    if rubric_policy is RubricPolicy.OFFLINE_ELICITATION:
        return 1
    return checkpoint
