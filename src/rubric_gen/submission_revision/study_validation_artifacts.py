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
from rubric_gen.submission_revision.bank_scoring import preflight_bank_dispatch
from rubric_gen.submission_revision.contrasts import build_elicitation_artifact_history
from rubric_gen.submission_revision.evolution import RubricBankProposer
from rubric_gen.submission_revision.feedback import (
    FeedbackPolicy,
    ProjectedFeedback,
    compose_bank_score,
    project_bank_feedback,
    project_bank_simulated_user_feedback,
)
from rubric_gen.submission_revision.judge import FrozenRubric, FrozenRubricJudge
from rubric_gen.submission_revision.judging.models import RUBRIC_PATH_SOURCE
from rubric_gen.submission_revision.judgment_reuse import (
    exact_judgment_request,
    load_judgment_copy,
)
from rubric_gen.submission_revision.prompts import PromptProfile
from rubric_gen.submission_revision.rubric_bank import (
    RubricBank,
    RubricBankItem,
    RubricBankPolicy,
)
from rubric_gen.submission_revision.rubric_bank_lifecycle import (
    RubricBankGeneration,
    load_rubric_bank,
)
from rubric_gen.submission_revision.study_validation_context import (
    ValidationContext,
    valid_score,
)


MemberArtifacts = dict[str, tuple[Path, Path]]


def validate_revision_artifacts(context: ValidationContext) -> None:
    roots = _validate_artifact_sets(context)
    proposer = _generation_proposer(context)
    instruction = (context.task_dir / "instruction.md").read_text(encoding="utf-8")
    for submission_id in context.expected_ids:
        _validate_submission(context, roots, proposer, instruction, submission_id)
    _validate_bank_directories(context)


@dataclass(frozen=True)
class _ArtifactRoots:
    submissions: Path
    rubric_generations: Path
    feedback: Path
    bank_evaluations: Path
    feedback_generations: Path


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
    feedback = context.experiment_dir / "feedback"
    _require_directory_names(
        feedback,
        expected_json,
        "revision feedback set is incomplete",
    )
    bank_evaluations = context.experiment_dir / "bank-evaluations"
    _require_directory_names(
        bank_evaluations,
        expected_json,
        "revision bank evaluation set is incomplete",
    )
    feedback_generations = context.experiment_dir / "feedback-generations"
    if context.policy is FeedbackPolicy.USER_SIMULATOR:
        _require_directory_names(
            feedback_generations,
            expected_json,
            "simulated-user generation set is incomplete",
        )
    elif os.path.lexists(feedback_generations):
        raise RuntimeError(
            "feedback-generations is only valid for user_simulator feedback"
        )
    return _ArtifactRoots(
        submissions=submissions,
        rubric_generations=rubric_generations,
        feedback=feedback,
        bank_evaluations=bank_evaluations,
        feedback_generations=feedback_generations,
    )


def _require_directory_names(root: Path, expected: list[str], message: str) -> None:
    if (
        root.is_symlink()
        or not root.is_dir()
        or sorted(path.name for path in root.iterdir()) != expected
    ):
        raise RuntimeError(message)


def _validate_rubric_generation_set(
    context: ValidationContext,
    root: Path,
) -> None:
    if context.bank_policy is RubricBankPolicy.FIXED:
        if os.path.lexists(root):
            raise RuntimeError(
                "rubric-generations is invalid for a fixed rubric policy"
            )
        return
    indices = (
        range(1, 2)
        if context.bank_policy is RubricBankPolicy.OFFLINE_ELICITATION
        else range(1, context.revision_rounds)
    )
    expected = [f"bank-{index:04d}" for index in indices]
    if not expected:
        if os.path.lexists(root):
            raise RuntimeError(
                "a no-update elicitation arm has rubric generation artifacts"
            )
        return
    if (
        root.is_symlink()
        or not root.is_dir()
        or sorted(path.name for path in root.iterdir()) != expected
        or any(path.is_symlink() for path in root.iterdir())
        or any(not path.is_dir() for path in root.iterdir())
    ):
        raise RuntimeError("rubric generation set is incomplete")


def _generation_proposer(context: ValidationContext) -> RubricBankProposer | None:
    if context.bank_policy is RubricBankPolicy.FIXED:
        return None
    protocol = context.protocol
    model = str(protocol["rubric_proposer_model"])
    return RubricBankProposer(
        benchmark=context.experiment.benchmark,
        model=model,
        base_url=context.endpoints.get(model),
        semantic_judge_model=str(protocol["rubric_semantic_judge_model"]),
        semantic_judge_base_url=context.endpoints.get(
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
            context.agent.service_tier if context.endpoints.get(model) is None else None
        ),
        max_retries=int(protocol["rubric_proposer_max_retries"]),
    )


def _validate_submission(
    context: ValidationContext,
    roots: _ArtifactRoots,
    proposer: RubricBankProposer | None,
    instruction: str,
    submission_id: str,
) -> None:
    submission = roots.submissions / submission_id
    verify_submission_snapshot(submission)
    read_json_object(submission / "snapshot.json", "submission snapshot")
    read_json_object(submission / "status.json", "submission status")
    feedback_path = roots.feedback / f"{submission_id}.json"
    if feedback_path.is_symlink() or not feedback_path.is_file():
        raise RuntimeError(f"missing feedback for {submission_id}")
    index = int(submission_id[1:])
    generation_round = _generation_round(context.bank_policy, index)
    generation = _validated_generation(
        context,
        roots,
        proposer,
        instruction,
        generation_round,
    )
    member_artifacts = _member_artifacts(
        context,
        submission,
        submission_id,
        index,
        generation_round,
        generation.bank,
    )
    fixed_score = _fixed_score(context, index)
    fixed_artifacts = _fixed_original_artifacts(
        context,
        submission,
        submission_id,
        index,
        member_artifacts,
        fixed_score,
    )
    projected = _project_feedback(
        context,
        roots,
        submission,
        submission_id,
        generation_round,
        generation.bank,
        member_artifacts,
        fixed_artifacts,
        fixed_score,
    )
    expected_evaluation = _expected_bank_evaluation(
        context,
        submission_id,
        generation.bank,
        member_artifacts,
        fixed_score,
    )
    if read_json_object(
        roots.bank_evaluations / f"{submission_id}.json",
        "bank evaluation",
    ) != expected_evaluation:
        raise RuntimeError(
            f"bank evaluation disagrees with members: {submission_id}"
        )
    scores = context.state["scores"]
    assert isinstance(scores, list)
    if (
        read_json_object(feedback_path, "revision feedback") != projected.payload
        or scores[index] != projected.score
    ):
        raise RuntimeError(
            f"feedback disagrees with scoring artifacts: {submission_id}"
        )


def _generation_round(policy: RubricBankPolicy, submission_index: int) -> int:
    if policy is RubricBankPolicy.FIXED:
        return 0
    if policy is RubricBankPolicy.OFFLINE_ELICITATION:
        return 1
    return max(0, submission_index - 1)


def _validated_generation(
    context: ValidationContext,
    roots: _ArtifactRoots,
    proposer: RubricBankProposer | None,
    instruction: str,
    generation_round: int,
) -> RubricBankGeneration:
    generation = load_rubric_bank(
        context.experiment_dir,
        generation_round,
        expected_policy=context.bank_policy,
    )
    if generation_round == 0:
        return generation
    prior = load_rubric_bank(
        context.experiment_dir,
        generation_round - 1,
        expected_policy=context.bank_policy,
    )
    generation.bank.validate_lineage(prior.bank)
    if proposer is None:
        raise RuntimeError("elicitation generation has no proposer")
    validated = proposer.elicit_rubric(
        instruction=instruction,
        current_bank=prior.bank,
        policy=context.bank_policy,
        generation_round=generation_round,
        output_dir=roots.rubric_generations,
        artifact_history=build_elicitation_artifact_history(
            online=context.bank_policy is RubricBankPolicy.ONLINE_ELICITATION,
            seed_set=context.seed.root,
            task_dir=context.task_dir,
            experiment_dir=context.experiment_dir,
            benchmark=get_submission_benchmark(context.experiment.benchmark),
            provider=context.agent.provider,
            requested_model=context.agent.model,
            assignment_id=str(context.assignment["assignment_id"]),
            generation_round=generation_round,
        ),
        source_boundary=(
            generation_round
            if context.bank_policy is RubricBankPolicy.ONLINE_ELICITATION
            else None
        ),
    )
    if validated != generation:
        raise RuntimeError("rubric generation disagrees with the active bank")
    return generation


def _member_artifacts(
    context: ValidationContext,
    submission: Path,
    submission_id: str,
    submission_index: int,
    generation_round: int,
    bank: RubricBank,
) -> MemberArtifacts:
    artifacts: MemberArtifacts = {}
    for item in bank.items:
        rubric_hash = item.rubric.content_sha256
        paths = _member_artifact_paths(
            context,
            submission,
            submission_id,
            submission_index,
            generation_round,
            item,
        )
        _validate_judgment(paths, submission_id, rubric_hash)
        artifacts[rubric_hash] = paths
    return artifacts


def _member_artifact_paths(
    context: ValidationContext,
    submission: Path,
    submission_id: str,
    submission_index: int,
    generation_round: int,
    item: RubricBankItem,
) -> tuple[Path, Path]:
    rubric_hash = item.rubric.content_sha256
    if (
        submission_index == 0
        and context.seed_contract == context.scoring.initial_contract
        and context.seed_contract["rendered_rubric_sha256"] == rubric_hash
    ):
        validation, evaluation, _ = context.seed.judgment
        return validation, evaluation
    _, judge = _bank_member_judge(context, item, generation_round)
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


def _bank_member_judge(
    context: ValidationContext,
    item: RubricBankItem,
    generation_round: int,
) -> tuple[FrozenRubric, FrozenRubricJudge]:
    if item.rubric.content_sha256 == context.scoring.initial_rubric.sha256:
        return context.scoring.initial_rubric, context.scoring.initial_judge
    member_path = (
        context.experiment_dir
        / "rubric-banks"
        / f"bank-{generation_round:04d}"
        / "members"
        / f"{item.rubric.content_sha256}.txt"
    )
    rubric = FrozenRubric(
        text=item.rubric.content,
        sha256=item.rubric.content_sha256,
        source=RUBRIC_PATH_SOURCE,
        rubric_set_id=None,
        rubric_id=None,
        structured_rubric_sha256=None,
        manifest_sha256=None,
    )
    config = replace(context.scoring.judge_config, rubric_path=member_path)
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
    member_artifacts: MemberArtifacts,
    fixed_score: object,
) -> tuple[Path, Path]:
    paths = _fixed_original_artifact_paths(
        context,
        submission,
        submission_id,
        submission_index,
        member_artifacts,
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
    member_artifacts: MemberArtifacts,
) -> tuple[Path, Path]:
    selection = context.selection
    same_base_and_master = (
        context.scoring.initial_generation.bank.items[0].rubric.content_sha256
        == selection.master_sha256
    )
    if submission_index == 0 and context.seed_contract == context.scoring.master_contract:
        validation, evaluation, _ = context.seed.judgment
        return validation, evaluation
    if same_base_and_master and (
        submission_index == 0 or context.bank_policy is RubricBankPolicy.FIXED
    ):
        try:
            return member_artifacts[selection.master_sha256]
        except KeyError as exc:
            raise RuntimeError(
                f"active bank lacks the master judgment: {submission_id}"
            ) from exc
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
    bank: RubricBank,
    member_artifacts: MemberArtifacts,
    fixed_artifacts: tuple[Path, Path],
    fixed_score: object,
) -> ProjectedFeedback:
    prompt_profile = PromptProfile(str(context.protocol["prompt"]))
    if context.policy is not FeedbackPolicy.USER_SIMULATOR:
        return project_bank_feedback(
            bank,
            member_artifacts,
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
    generation = read_json_object(
        generation_path,
        "simulated-user generation",
    )
    comment = simulator.validate(
        generation,
        experiment_id=context.experiment.experiment_id,
        assignment_id=str(context.assignment["assignment_id"]),
        submission_id=submission_id,
        generation_round=generation_round,
        bank=bank,
    )
    return project_bank_simulated_user_feedback(
        bank,
        {
            rubric_hash: paths[0]
            for rubric_hash, paths in member_artifacts.items()
        },
        comment,
        fixed_original_score=float(fixed_score),
        prompt_profile=prompt_profile,
        benchmark=context.experiment.benchmark,
    )


def _expected_bank_evaluation(
    context: ValidationContext,
    submission_id: str,
    bank: RubricBank,
    member_artifacts: MemberArtifacts,
    fixed_score: object,
) -> dict[str, object]:
    validation_paths = {
        rubric_hash: paths[0] for rubric_hash, paths in member_artifacts.items()
    }
    composition = compose_bank_score(bank, validation_paths, float(fixed_score))
    members: dict[str, dict[str, object]] = {}
    for item in bank.items:
        rubric_hash = item.rubric.content_sha256
        validation_path, evaluation_path = member_artifacts[rubric_hash]
        score = read_json_object(validation_path, "score validation").get("score")
        if not valid_score(score):
            raise RuntimeError("bank member score is invalid")
        member = composition.members[rubric_hash]
        members[rubric_hash] = {
            "weight": item.weight,
            "judge_score": score,
            "elicited_penalty": member.elicited_penalty,
            "score": member.score,
            "score_validation_sha256": sha256_file(validation_path),
            "evaluation_sha256": sha256_file(evaluation_path),
        }
    first_validation = next(iter(member_artifacts.values()))[0]
    return {
        "kind": "canonical-original-plus-elicited-penalty-evaluation",
        "submission_id": submission_id,
        "generation_round": bank.generation_round,
        "bank_sha256": bank.content_sha256,
        "dispatch_preflight": preflight_bank_dispatch(
            bank,
            benchmark=context.experiment.benchmark,
            review_text=(first_validation.parent / "judge_input_trace.md").read_text(
                encoding="utf-8"
            ),
            answer_text=(first_validation.parent / "judge_input_answer.txt").read_text(
                encoding="utf-8"
            ),
        ),
        "members": members,
        "canonical_original_score": composition.canonical_original_score,
        "weighted_elicited_penalty": composition.weighted_elicited_penalty,
        "score": composition.score,
    }


def _validate_bank_directories(context: ValidationContext) -> None:
    root = context.experiment_dir / "rubric-banks"
    expected = expected_bank_names(context.condition, len(context.expected_ids))
    if (
        root.is_symlink()
        or not root.is_dir()
        or sorted(path.name for path in root.iterdir()) != expected
        or any(path.is_symlink() or not path.is_dir() for path in root.iterdir())
    ):
        raise RuntimeError("revision rubric bank set is incomplete")


def expected_bank_names(
    condition_spec: dict[str, object],
    submission_count: int,
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
