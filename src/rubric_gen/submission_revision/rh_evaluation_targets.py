"""Load completed revision assignments for reward-hacking evaluation."""

from __future__ import annotations

import math
from concurrent.futures import ThreadPoolExecutor, as_completed
from numbers import Real
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.experiment import Experiment
from rubric_gen.submission_revision.judging.models import (
    grading_engine_for_benchmark,
)
from rubric_gen.submission_revision.paraphrases import (
    ParaphraseSelection,
    resolve_paraphrase_selection,
)
from rubric_gen.submission_revision.rh_protocol import (
    EvaluationConfig,
    EvaluationTarget,
    _finite_number,
    _finite_score,
    _is_sha256,
)
from rubric_gen.submission_revision.rubric_bank import (
    RubricBankGeneration,
    RubricBankPolicy,
    load_rubric_bank,
    rubric_bank_directory,
)
from rubric_gen.submission_revision.study import resolve_study_experiment

def _load_weak_bank_score(
    experiment_dir: Path,
    submission_id: str,
    generation: RubricBankGeneration,
    state_score: object,
    benchmark: SubmissionBenchmarkId,
) -> float:
    path = experiment_dir / "bank-evaluations" / f"{submission_id}.json"
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"weak bank evaluation is missing: {path}")
    record = read_json_object(path, "weak bank evaluation")
    if set(record) != {
        "kind",
        "submission_id",
        "generation_round",
        "bank_sha256",
        "dispatch_preflight",
        "members",
        "canonical_original_score",
        "weighted_elicited_penalty",
        "score",
    }:
        raise RuntimeError("weak bank evaluation has invalid fields")
    bank = generation.bank
    if (
        record.get("kind")
        != "canonical-original-plus-elicited-penalty-evaluation"
        or record.get("submission_id") != submission_id
        or record.get("generation_round") != bank.generation_round
        or record.get("bank_sha256") != bank.content_sha256
    ):
        raise RuntimeError("weak bank evaluation has the wrong identity")
    dispatch = record.get("dispatch_preflight")
    if not isinstance(dispatch, dict) or set(dispatch) != {
        "grading_engine",
        "bank_sha256",
        "member_sha256s",
        "review_text_sha256",
        "answer_text_sha256",
        "cost_shape",
    }:
        raise RuntimeError("weak bank evaluation has an invalid dispatch preflight")
    ordered_hashes = [item.rubric.content_sha256 for item in bank.items]
    if (
        dispatch.get("grading_engine")
        != grading_engine_for_benchmark(benchmark).value
        or dispatch.get("bank_sha256") != bank.content_sha256
        or dispatch.get("member_sha256s") != ordered_hashes
        or not _is_sha256(dispatch.get("review_text_sha256"))
        or not _is_sha256(dispatch.get("answer_text_sha256"))
        or not isinstance(dispatch.get("cost_shape"), dict)
    ):
        raise RuntimeError("weak bank evaluation dispatch binding changed")
    members = record.get("members")
    expected_hashes = {item.rubric.content_sha256 for item in bank.items}
    if not isinstance(members, dict) or set(members) != expected_hashes:
        raise RuntimeError("weak bank evaluation has the wrong members")
    member_scores: dict[str, float] = {}
    for item in bank.items:
        member_hash = item.rubric.content_sha256
        member = members[member_hash]
        if not isinstance(member, dict) or set(member) != {
            "weight",
            "judge_score",
            "elicited_penalty",
            "score",
            "score_validation_sha256",
            "evaluation_sha256",
        }:
            raise RuntimeError("weak bank evaluation member has invalid fields")
        weight = member.get("weight")
        if (
            isinstance(weight, bool)
            or not isinstance(weight, Real)
            or float(weight) != item.weight
        ):
            raise RuntimeError("weak bank evaluation member has the wrong weight")
        for hash_key in ("score_validation_sha256", "evaluation_sha256"):
            digest = member.get(hash_key)
            if not _is_sha256(digest):
                raise RuntimeError("weak bank evaluation member has an invalid hash")
        _finite_score(member.get("judge_score"), "weak bank judge score")
        penalty = _finite_number(
            member.get("elicited_penalty"),
            "weak bank elicited penalty",
        )
        if penalty > 0:
            raise RuntimeError("weak bank elicited penalty is positive")
        member_scores[member_hash] = _finite_score(
            member.get("score"),
            "weak bank member score",
        )
    expected_score = bank.aggregate(member_scores)
    canonical_score = _finite_score(
        record.get("canonical_original_score"),
        "weak canonical original score",
    )
    weighted_penalty = _finite_number(
        record.get("weighted_elicited_penalty"),
        "weak weighted elicited penalty",
    )
    if weighted_penalty > 0:
        raise RuntimeError("weak weighted elicited penalty is positive")
    score = _finite_score(record.get("score"), "weak composed bank score")
    if score != expected_score or score != max(0.0, canonical_score + weighted_penalty):
        raise RuntimeError("weak bank composed score is inconsistent")
    normalized_state_score = _finite_score(state_score, "weak state score")
    if normalized_state_score != score:
        raise RuntimeError("weak state score disagrees with bank evaluation")
    return score


def load_evaluation_targets(
    config: EvaluationConfig,
) -> tuple[EvaluationTarget, ...]:
    study_root = config.study_dir.resolve()
    study = read_json_object(study_root / "study.json", "study manifest")
    if (
        study.get("kind") != "rubric-gen-randomized-revision-study"
        or study.get("status") != "completed"
        or study.get("experiment_id") != config.experiment.experiment_id
        or study.get("experiment_path") != str(config.experiment.path)
        or type(study.get("seed_run_dir")) is not str
        or study.get("paraphrase_run_dir") != str(config.paraphrase_dir.resolve())
        or not isinstance(study.get("records"), list)
    ):
        raise RuntimeError("RH evaluation requires a completed current study")
    records = {
        str(record.get("assignment_id")): record
        for record in study["records"]
        if isinstance(record, dict)
    }
    assignments = config.experiment.assignments
    selection_keys = {
        (str(assignment["task_id"]), int(assignment["replicate"]))
        for assignment in assignments
    }
    selections = {
        key: resolve_paraphrase_selection(
            config.paraphrase_dir,
            config.experiment,
            *key,
        )
        for key in sorted(selection_keys)
    }
    targets: list[EvaluationTarget | None] = [None] * len(assignments)
    with TerminalProgress(
        total=len(assignments),
        description="RH target loading",
        unit="assignment",
    ) as progress:
        futures = {}
        with ThreadPoolExecutor(
            max_workers=min(config.max_concurrency, len(assignments))
        ) as pool:
            for index, assignment in enumerate(assignments):
                assignment_id = str(assignment["assignment_id"])
                record = records.get(assignment_id)
                if record is None or record.get("status") != "completed":
                    raise RuntimeError(
                        f"study assignment is incomplete: {assignment_id}"
                    )
                selection_key = (
                    str(assignment["task_id"]),
                    int(assignment["replicate"]),
                )
                future = pool.submit(
                    _load_evaluation_target,
                    config,
                    study_root,
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
        raise RuntimeError("RH target loading did not return every assignment")
    return tuple(target for target in targets if target is not None)


def _load_evaluation_target(
    config: EvaluationConfig,
    study_root: Path,
    assignment: dict[str, object],
    record: dict[str, object],
    selection: ParaphraseSelection,
) -> EvaluationTarget:
    assignment_id = str(assignment["assignment_id"])
    experiment_dir = resolve_study_experiment(
        study_root,
        record,
        assignment,
    )
    state = _load_terminal_revision_state(
        experiment_dir,
        assignment,
        config.experiment,
    )
    submission_ids = state["submission_ids"]
    scores = state["scores"]
    fixed_original_scores = state["fixed_original_scores"]
    task_id = str(assignment["task_id"])
    replicate = int(assignment["replicate"])
    condition = config.experiment.condition(str(assignment["condition_id"]))
    bank_policy = RubricBankPolicy(str(condition["rubric_policy"]))
    initial_bank_round = _active_bank_round(bank_policy, 0)
    final_bank_round = _active_bank_round(
        bank_policy,
        len(submission_ids) - 1,
    )
    bank_generations = {
        generation_round: load_rubric_bank(
            experiment_dir,
            generation_round,
            expected_policy=bank_policy,
        )
        for generation_round in {
            0,
            initial_bank_round,
            final_bank_round,
        }
    }
    selected_bank_generation = bank_generations[0]
    initial_bank_generation = bank_generations[initial_bank_round]
    final_bank_generation = bank_generations[final_bank_round]
    initial_bank_manifest_path = (
        rubric_bank_directory(experiment_dir, initial_bank_round)
        / "manifest.json"
    ).resolve()
    final_bank_manifest_path = (
        rubric_bank_directory(experiment_dir, final_bank_round)
        / "manifest.json"
    ).resolve()
    initial_member_hashes = {
        item.rubric.content_sha256
        for item in selected_bank_generation.bank.items
    }
    if selection.optimizer_sha256 not in initial_member_hashes:
        raise RuntimeError(
            "initial bank does not contain the selected rubric: "
            f"{assignment_id}"
        )
    weak_initial_score = _load_weak_bank_score(
        experiment_dir,
        str(submission_ids[0]),
        initial_bank_generation,
        scores[0],
        config.experiment.benchmark,
    )
    weak_final_score = _load_weak_bank_score(
        experiment_dir,
        str(submission_ids[-1]),
        final_bank_generation,
        scores[-1],
        config.experiment.benchmark,
    )
    return EvaluationTarget(
        assignment_id=assignment_id,
        task_id=task_id,
        replicate=replicate,
        condition_id=str(assignment["condition_id"]),
        rubric_policy=bank_policy,
        benchmark=config.experiment.benchmark,
        experiment_dir=experiment_dir.resolve(),
        task_dir=config.experiment.task_dir(task_id).resolve(),
        review=str(config.experiment.protocol["review"]),
        max_review_chars=config.experiment.protocol["max_review_chars"],  # type: ignore[arg-type]
        weak_model=str(config.experiment.protocol["judge_model"]),
        weak_initial_score=weak_initial_score,
        weak_final_score=weak_final_score,
        initial_submission=(
            experiment_dir / "submissions" / str(submission_ids[0])
        ).resolve(),
        final_submission=(
            experiment_dir / "submissions" / str(submission_ids[-1])
        ).resolve(),
        submission_ids=tuple(str(value) for value in submission_ids),
        fixed_original_scores=tuple(
            float(value) for value in fixed_original_scores
        ),
        initial_bank_generation=initial_bank_generation,
        final_bank_generation=final_bank_generation,
        initial_bank_manifest_path=initial_bank_manifest_path,
        final_bank_manifest_path=final_bank_manifest_path,
        initial_bank_manifest_sha256=sha256_file(initial_bank_manifest_path),
        final_bank_manifest_sha256=sha256_file(final_bank_manifest_path),
        selection=selection,
    )


def _load_terminal_revision_state(
    experiment_dir: Path,
    assignment: dict[str, object],
    experiment: Experiment,
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
    manifest_identity = {
        "kind": "rubric-gen-submission-revision-experiment",
        "experiment_id": experiment.experiment_id,
        "benchmark": str(experiment.benchmark),
        "assignment_id": assignment.get("assignment_id"),
        "condition_id": assignment.get("condition_id"),
        "task_id": assignment.get("task_id"),
        "replicate": assignment.get("replicate"),
        "execution_order": assignment.get("execution_order"),
        "live_workspace_removed": True,
    }
    if any(
        manifest.get(key) != value
        for key, value in manifest_identity.items()
    ):
        raise RuntimeError(f"revision identity is invalid: {experiment_dir}")
    submission_ids = state.get("submission_ids")
    scores = state.get("scores")
    fixed_original_scores = state.get("fixed_original_scores")
    if (
        state.get("phase") != "completed"
        or not isinstance(submission_ids, list)
        or len(submission_ids) < 2
        or any(type(value) is not str for value in submission_ids)
        or submission_ids
        != [f"s{index:03d}" for index in range(len(submission_ids))]
        or state.get("next_turn_index") != len(submission_ids)
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
        raise RuntimeError(f"revision boundaries are invalid: {experiment_dir}")
    submissions = experiment_dir / "submissions"
    if submissions.is_symlink() or not submissions.is_dir():
        raise RuntimeError(f"revision submissions are invalid: {experiment_dir}")
    for submission_id in submission_ids:
        submission = submissions / submission_id
        if submission.is_symlink() or not submission.is_dir():
            raise RuntimeError(f"revision submission is missing: {submission}")
    return state


def _active_bank_round(
    bank_policy: RubricBankPolicy,
    boundary: int,
) -> int:
    if boundary < 0:
        raise ValueError("active bank boundary must be nonnegative")
    if bank_policy is RubricBankPolicy.FIXED:
        return 0
    if bank_policy is RubricBankPolicy.OFFLINE_ELICITATION:
        return 1
    return max(0, boundary - 1)
