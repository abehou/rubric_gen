"""Validate completed revision artifacts and their exact provenance."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from rubric_gen.benchmarks import get_submission_benchmark
from rubric_gen.submission_revision.artifacts import (
    read_json_object,
    sha256_file,
    verify_submission_snapshot,
)
from rubric_gen.submission_revision.generation_scoring import (
    preflight_generation_dispatch,
)
from rubric_gen.submission_revision.contrasts import build_elicitation_artifact_history
from rubric_gen.submission_revision.evolution import RubricProposer
from rubric_gen.submission_revision.feedback import (
    FeedbackPolicy,
    ProjectedFeedback,
    compose_rubric_score,
    project_rubric_feedback,
    project_rubric_simulated_user_feedback,
)
from rubric_gen.submission_revision.judge import FrozenRubric, FrozenRubricJudge
from rubric_gen.submission_revision.judging.models import RUBRIC_PATH_SOURCE
from rubric_gen.submission_revision.judgment_reuse import (
    exact_judgment_request,
    load_judgment_copy,
)
from rubric_gen.submission_revision.prompts import PromptProfile
from rubric_gen.submission_revision.rubric_generation import (
    RubricGeneration,
    RubricPolicy,
)
from rubric_gen.submission_revision.rubric_generation_store import (
    load_rubric_generation,
    rubric_generation_directory,
)
from rubric_gen.submission_revision.study_validation_context import (
    ValidationContext,
    valid_score,
)
from rubric_gen.submission_revision.user_simulator_history import (
    build_simulated_user_history,
)


RubricArtifacts = tuple[Path, Path]


def validate_revision_artifacts(context: ValidationContext) -> None:
    roots = _validate_artifact_sets(context)
    proposer = _generation_proposer(context)
    instruction = (context.task_dir / "instruction.md").read_text(encoding="utf-8")
    for submission_id in context.expected_ids:
        _validate_submission(context, roots, proposer, instruction, submission_id)


@dataclass(frozen=True)
class _ArtifactRoots:
    submissions: Path
    rubric_generations: Path
    feedback: Path
    rubric_evaluations: Path
    feedback_generations: Path
    feedback_history_summaries: Path


def _feedback_submission_ids(context: ValidationContext) -> tuple[str, ...]:
    """Return submissions whose feedback was used by a solver turn."""

    extra_turn = (
        context.experiment_dir
        / "turns"
        / f"turn-{len(context.expected_ids):03d}"
    )
    if extra_turn.is_dir() and not extra_turn.is_symlink():
        return context.expected_ids
    return context.expected_ids[:-1]


def _validate_artifact_sets(context: ValidationContext) -> _ArtifactRoots:
    submissions = context.experiment_dir / "submissions"
    _require_directory_names(
        submissions,
        list(context.expected_ids),
        "revision submission set is incomplete",
    )
    rubric_generations = context.experiment_dir / "rubric-generations"
    _validate_rubric_generation_set(context, rubric_generations)
    expected_json = [f"{submission_id}.json" for submission_id in context.expected_ids]
    feedback_ids = _feedback_submission_ids(context)
    actionable_json = [f"{submission_id}.json" for submission_id in feedback_ids]
    feedback = context.experiment_dir / "feedback"
    _require_directory_names(
        feedback,
        actionable_json,
        "revision feedback set is incomplete",
    )
    rubric_evaluations = context.experiment_dir / "rubric-evaluations"
    _require_directory_names(
        rubric_evaluations,
        expected_json,
        "revision rubric evaluation set is incomplete",
    )
    feedback_generations = context.experiment_dir / "feedback-generations"
    feedback_history_summaries = (
        context.experiment_dir / "feedback-history-summaries"
    )
    if context.policy is FeedbackPolicy.USER_SIMULATOR:
        _require_directory_names(
            feedback_generations,
            actionable_json,
            "simulated-user generation set is incomplete",
        )
        assert context.simulator is not None
        benchmark = get_submission_benchmark(context.experiment.benchmark)
        summary_names = [
            f"{submission_id}.json"
            for submission_id in feedback_ids
            if context.simulator.history_requires_summary(
                build_simulated_user_history(
                    context.experiment_dir,
                    benchmark,
                    int(submission_id[1:]),
                )
            )
        ]
        _validate_optional_directory_names(
            feedback_history_summaries,
            summary_names,
            "simulated-user history summary set is invalid",
        )
    elif os.path.lexists(feedback_generations):
        raise RuntimeError(
            "feedback-generations is only valid for user_simulator feedback"
        )
    elif os.path.lexists(feedback_history_summaries):
        raise RuntimeError(
            "feedback-history-summaries is only valid for user_simulator feedback"
        )
    return _ArtifactRoots(
        submissions=submissions,
        rubric_generations=rubric_generations,
        feedback=feedback,
        rubric_evaluations=rubric_evaluations,
        feedback_generations=feedback_generations,
        feedback_history_summaries=feedback_history_summaries,
    )


def _require_directory_names(root: Path, expected: list[str], message: str) -> None:
    if (
        root.is_symlink()
        or not root.is_dir()
        or sorted(path.name for path in root.iterdir()) != expected
    ):
        raise RuntimeError(message)


def _validate_optional_directory_names(
    root: Path,
    expected: list[str],
    message: str,
) -> None:
    if not expected:
        if os.path.lexists(root):
            raise RuntimeError(message)
        return
    _require_directory_names(root, expected, message)


def _validate_rubric_generation_set(
    context: ValidationContext,
    root: Path,
) -> None:
    indices = (
        range(1)
        if context.rubric_policy is RubricPolicy.FIXED
        else (
            range(2)
            if context.rubric_policy is RubricPolicy.OFFLINE_ELICITATION
            else range(max(1, len(context.expected_ids) - 1))
        )
    )
    expected = [f"generation-{index:04d}" for index in indices]
    if (
        root.is_symlink()
        or not root.is_dir()
        or sorted(path.name for path in root.iterdir()) != expected
        or any(path.is_symlink() for path in root.iterdir())
        or any(not path.is_dir() for path in root.iterdir())
    ):
        raise RuntimeError("rubric generation set is incomplete")


def _generation_proposer(context: ValidationContext) -> RubricProposer | None:
    if context.rubric_policy is RubricPolicy.FIXED:
        return None
    protocol = context.protocol
    model = str(protocol["rubric_proposer_model"])
    return RubricProposer(
        benchmark=context.experiment.benchmark,
        model=model,
        semantic_judge_model=str(protocol["rubric_semantic_judge_model"]),
        semantic_judge_max_calls=int(
            protocol["rubric_semantic_judge_max_calls_per_assignment"]
        ),
        semantic_judge_max_request_bytes=int(
            protocol["rubric_semantic_judge_max_request_bytes_per_call"]
        ),
        semantic_judge_max_output_tokens=int(
            protocol["rubric_semantic_judge_max_output_tokens_per_call"]
        ),
        service_tier=context.agent.service_tier,
        max_retries=int(protocol["rubric_proposer_max_retries"]),
    )


def _validate_submission(
    context: ValidationContext,
    roots: _ArtifactRoots,
    proposer: RubricProposer | None,
    instruction: str,
    submission_id: str,
) -> None:
    submission = roots.submissions / submission_id
    verify_submission_snapshot(submission)
    read_json_object(submission / "snapshot.json", "submission snapshot")
    read_json_object(submission / "status.json", "submission status")
    feedback_path = roots.feedback / f"{submission_id}.json"
    index = int(submission_id[1:])
    has_next_turn = submission_id in _feedback_submission_ids(context)
    if has_next_turn and (
        feedback_path.is_symlink() or not feedback_path.is_file()
    ):
        raise RuntimeError(f"missing feedback for {submission_id}")
    if not has_next_turn and os.path.lexists(feedback_path):
        raise RuntimeError(f"terminal submission contains feedback: {submission_id}")
    generation_round = _generation_round(context.rubric_policy, index)
    generation = _validated_generation(
        context,
        roots,
        proposer,
        instruction,
        generation_round,
    )
    rubric_artifacts = _rubric_artifacts(
        context,
        submission,
        submission_id,
        index,
        generation,
    )
    fixed_score = _fixed_score(context, index)
    fixed_artifacts = _fixed_original_artifacts(
        context,
        submission,
        submission_id,
        index,
        rubric_artifacts,
        fixed_score,
    )
    expected_evaluation = _expected_rubric_evaluation(
        context,
        submission_id,
        generation,
        rubric_artifacts,
        fixed_score,
    )
    if read_json_object(
        roots.rubric_evaluations / f"{submission_id}.json",
        "rubric evaluation",
    ) != expected_evaluation:
        raise RuntimeError(f"rubric evaluation disagrees: {submission_id}")
    scores = context.state["scores"]
    assert isinstance(scores, list)
    if scores[index] != expected_evaluation["score"]:
        raise RuntimeError(f"score disagrees with artifacts: {submission_id}")
    if has_next_turn:
        projected = _project_feedback(
            context,
            roots,
            submission,
            submission_id,
            generation_round,
            generation,
            rubric_artifacts,
            fixed_artifacts,
            fixed_score,
        )
        if (
            read_json_object(feedback_path, "revision feedback")
            != projected.payload
            or scores[index] != projected.score
        ):
            raise RuntimeError(
                f"feedback disagrees with scoring artifacts: {submission_id}"
            )


def _generation_round(policy: RubricPolicy, submission_index: int) -> int:
    if policy is RubricPolicy.FIXED:
        return 0
    if policy is RubricPolicy.OFFLINE_ELICITATION:
        return 1
    return max(0, submission_index - 1)


def _validated_generation(
    context: ValidationContext,
    roots: _ArtifactRoots,
    proposer: RubricProposer | None,
    instruction: str,
    generation_round: int,
) -> RubricGeneration:
    generation = load_rubric_generation(
        context.experiment_dir,
        generation_round,
        expected_policy=context.rubric_policy,
    )
    if generation_round == 0:
        return generation
    prior = load_rubric_generation(
        context.experiment_dir,
        generation_round - 1,
        expected_policy=context.rubric_policy,
    )
    generation.validate_successor(prior)
    if proposer is None:
        raise RuntimeError("elicitation generation has no proposer")
    validated = proposer.elicit_rubric(
        instruction=instruction,
        original_rubric=context.scoring.initial_generation.rubric,
        current_generation=prior,
        policy=context.rubric_policy,
        generation_round=generation_round,
        output_dir=context.experiment_dir,
        artifact_history=build_elicitation_artifact_history(
            online=context.rubric_policy is RubricPolicy.ONLINE_ELICITATION,
            seed_set=context.seed.root,
            task_dir=context.task_dir,
            experiment_dir=context.experiment_dir,
            benchmark=get_submission_benchmark(context.experiment.benchmark),
            provider=context.agent.provider,
            requested_model=context.agent.model,
            assignment_id=str(context.assignment["assignment_id"]),
            generation_round=generation_round,
        ),
        source_checkpoint=(
            generation_round
            if context.rubric_policy is RubricPolicy.ONLINE_ELICITATION
            else None
        ),
    )
    if validated != generation:
        raise RuntimeError("rubric generation disagrees with the active rubric")
    return generation


def _rubric_artifacts(
    context: ValidationContext,
    submission: Path,
    submission_id: str,
    submission_index: int,
    generation: RubricGeneration,
) -> RubricArtifacts:
    paths = _rubric_artifact_paths(
        context,
        submission,
        submission_id,
        submission_index,
        generation,
    )
    _validate_judgment(
        paths,
        submission_id,
        generation.rubric.content_sha256,
    )
    return paths


def _rubric_artifact_paths(
    context: ValidationContext,
    submission: Path,
    submission_id: str,
    submission_index: int,
    generation: RubricGeneration,
) -> tuple[Path, Path]:
    rubric_hash = generation.rubric.content_sha256
    if (
        submission_index == 0
        and context.seed_contract == context.scoring.initial_contract
        and context.seed_contract["rendered_rubric_sha256"] == rubric_hash
    ):
        validation, evaluation, _ = context.seed.judgment
        return validation, evaluation
    _, judge = _generation_judge(context, generation)
    review_text, answer_text = judge.review_inputs(submission)
    expected_request = exact_judgment_request(
        task_id=str(context.assignment["task_id"]),
        replicate=int(context.assignment["replicate"]),
        rubric_sha256=rubric_hash,
        review_text=review_text,
        answer_text=answer_text,
        scoring_identity=judge.scoring_identity(),
    )
    artifacts = load_judgment_copy(
        experiment_dir=context.experiment_dir,
        submission_id=submission_id,
        rubric_sha256=rubric_hash,
        expected_request=expected_request,
    )
    return artifacts.score_validation_path, artifacts.evaluation_path


def _generation_judge(
    context: ValidationContext,
    generation: RubricGeneration,
) -> tuple[FrozenRubric, FrozenRubricJudge]:
    if generation.rubric.content_sha256 == context.scoring.initial_rubric.sha256:
        return context.scoring.initial_rubric, context.scoring.initial_judge
    rubric_path = (
        rubric_generation_directory(
            context.experiment_dir,
            generation.generation_round,
        )
        / "rubric.txt"
    )
    rubric = FrozenRubric(
        text=generation.rubric.content,
        sha256=generation.rubric.content_sha256,
        source=RUBRIC_PATH_SOURCE,
        rubric_set_id=None,
        rubric_id=None,
        structured_rubric_sha256=None,
        manifest_sha256=None,
    )
    config = replace(context.scoring.judge_config, rubric_path=rubric_path)
    return rubric, FrozenRubricJudge(config, rubric)


def _validate_judgment(
    paths: tuple[Path, Path],
    submission_id: str,
    rubric_hash: str,
) -> None:
    validation_path, evaluation_path = paths
    if (
        validation_path.is_symlink()
        or evaluation_path.is_symlink()
        or not validation_path.is_file()
        or not evaluation_path.is_file()
    ):
        raise RuntimeError(
            f"scoring artifacts are incomplete for {submission_id}/{rubric_hash}"
        )
    validation = read_json_object(validation_path, "score validation")
    if validation.get("evaluation_sha256") != sha256_file(evaluation_path):
        raise RuntimeError(
            "evaluation disagrees with score validation: "
            f"{submission_id}/{rubric_hash}"
        )


def _fixed_score(context: ValidationContext, index: int) -> object:
    scores = context.state["fixed_original_scores"]
    assert isinstance(scores, list)
    return scores[index]


def _fixed_original_artifacts(
    context: ValidationContext,
    submission: Path,
    submission_id: str,
    submission_index: int,
    rubric_artifacts: RubricArtifacts,
    fixed_score: object,
) -> tuple[Path, Path]:
    paths = _fixed_original_artifact_paths(
        context,
        submission,
        submission_id,
        submission_index,
        rubric_artifacts,
    )
    validation_path, evaluation_path = paths
    if (
        validation_path.is_symlink()
        or evaluation_path.is_symlink()
        or not validation_path.is_file()
        or not evaluation_path.is_file()
    ):
        raise RuntimeError(
            f"fixed-original scoring artifacts are incomplete for {submission_id}"
        )
    validation = read_json_object(
        validation_path,
        "fixed-original score validation",
    )
    if (
        validation.get("evaluation_sha256") != sha256_file(evaluation_path)
        or validation.get("score") != fixed_score
    ):
        raise RuntimeError(
            "fixed-original score disagrees with scoring artifacts: "
            f"{submission_id}"
        )
    return paths


def _fixed_original_artifact_paths(
    context: ValidationContext,
    submission: Path,
    submission_id: str,
    submission_index: int,
    rubric_artifacts: RubricArtifacts,
) -> tuple[Path, Path]:
    selection = context.selection
    same_base_and_master = (
        context.scoring.initial_generation.rubric.content_sha256
        == selection.master_sha256
    )
    if submission_index == 0 and context.seed_contract == context.scoring.master_contract:
        validation, evaluation, _ = context.seed.judgment
        return validation, evaluation
    if same_base_and_master and (
        submission_index == 0 or context.rubric_policy is RubricPolicy.FIXED
    ):
        return rubric_artifacts
    review_text, answer_text = context.scoring.master_judge.review_inputs(submission)
    expected_request = exact_judgment_request(
        task_id=str(context.assignment["task_id"]),
        replicate=int(context.assignment["replicate"]),
        rubric_sha256=selection.master_sha256,
        review_text=review_text,
        answer_text=answer_text,
        scoring_identity=context.scoring.master_judge.scoring_identity(),
    )
    artifacts = load_judgment_copy(
        experiment_dir=context.experiment_dir,
        submission_id=submission_id,
        rubric_sha256=selection.master_sha256,
        expected_request=expected_request,
    )
    return artifacts.score_validation_path, artifacts.evaluation_path


def _project_feedback(
    context: ValidationContext,
    roots: _ArtifactRoots,
    submission: Path,
    submission_id: str,
    generation_round: int,
    generation: RubricGeneration,
    rubric_artifacts: RubricArtifacts,
    fixed_artifacts: tuple[Path, Path],
    fixed_score: object,
) -> ProjectedFeedback:
    prompt_profile = PromptProfile(str(context.protocol["prompt"]))
    if context.policy is not FeedbackPolicy.USER_SIMULATOR:
        return project_rubric_feedback(
            generation,
            rubric_artifacts,
            context.policy,
            fixed_original_artifacts=fixed_artifacts,
            fixed_original_rubric_text=context.selection.master_path.read_text(
                encoding="utf-8"
            ),
            fixed_original_rubric_sha256=context.selection.master_sha256,
            prompt_profile=prompt_profile,
            benchmark=context.experiment.benchmark,
        )
    simulator = context.simulator
    if simulator is None:
        raise RuntimeError("user-simulator feedback has no simulator")
    generation_path = roots.feedback_generations / f"{submission_id}.json"
    if generation_path.is_symlink() or not generation_path.is_file():
        raise RuntimeError(f"missing simulated-user generation for {submission_id}")
    simulated_record = read_json_object(
        generation_path,
        "simulated-user generation",
    )
    history = build_simulated_user_history(
        context.experiment_dir,
        get_submission_benchmark(context.experiment.benchmark),
        int(submission_id[1:]),
    )
    summary_path = roots.feedback_history_summaries / f"{submission_id}.json"
    history_summary = None
    if simulator.history_requires_summary(history):
        if summary_path.is_symlink() or not summary_path.is_file():
            raise RuntimeError(
                f"missing simulated-user history summary for {submission_id}"
            )
        history_summary = read_json_object(
            summary_path,
            "simulated-user history summary",
        )
        simulator.validate_history_summary(
            history_summary,
            experiment_id=context.experiment.experiment_id,
            assignment_id=str(context.assignment["assignment_id"]),
            submission_id=submission_id,
            history=history,
        )
    current_artifact = get_submission_benchmark(
        context.experiment.benchmark
    ).render_user_review(submission / "workspace")
    user_feedback = simulator.validate(
        simulated_record,
        experiment_id=context.experiment.experiment_id,
        assignment_id=str(context.assignment["assignment_id"]),
        submission_id=submission_id,
        generation_round=generation_round,
        generation=generation,
        current_artifact=current_artifact,
        history=history,
        history_summary=history_summary,
    )
    return project_rubric_simulated_user_feedback(
        generation,
        rubric_artifacts[0],
        user_feedback,
        fixed_original_score=float(fixed_score),
        prompt_profile=prompt_profile,
        benchmark=context.experiment.benchmark,
    )


def _expected_rubric_evaluation(
    context: ValidationContext,
    submission_id: str,
    generation: RubricGeneration,
    rubric_artifacts: RubricArtifacts,
    fixed_score: object,
) -> dict[str, object]:
    validation_path, evaluation_path = rubric_artifacts
    composition = compose_rubric_score(
        generation,
        validation_path,
        float(fixed_score),
    )
    score = read_json_object(validation_path, "score validation").get("score")
    if not valid_score(score):
        raise RuntimeError("rubric score is invalid")
    return {
        "kind": "canonical-original-plus-elicited-penalty-evaluation",
        "submission_id": submission_id,
        "generation_round": generation.generation_round,
        "generation_sha256": generation.generation_sha256,
        "rubric_sha256": generation.rubric.content_sha256,
        "dispatch_preflight": preflight_generation_dispatch(
            generation,
            benchmark=context.experiment.benchmark,
            review_text=(validation_path.parent / "judge_input_trace.md").read_text(
                encoding="utf-8"
            ),
            answer_text=(validation_path.parent / "judge_input_answer.txt").read_text(
                encoding="utf-8"
            ),
        ),
        "judge_score": score,
        "canonical_original_score": composition.canonical_original_score,
        "elicited_penalty": composition.elicited_penalty,
        "score_validation_sha256": sha256_file(validation_path),
        "evaluation_sha256": sha256_file(evaluation_path),
        "score": composition.score,
    }
