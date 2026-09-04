"""Input validation for one rubric-evolution generation."""

from __future__ import annotations

from rubric_gen.submission_revision.rubric_generation import (
    CompleteRubric,
    RubricGeneration,
    RubricPolicy,
    render_augmented_rubric,
)


def validate_evolution_request(
    *,
    instruction: str,
    original_rubric: CompleteRubric,
    development_rubric: CompleteRubric,
    current_generation: RubricGeneration,
    policy: RubricPolicy,
    generation_round: int,
    source_checkpoint: int | None,
) -> None:
    """Reject an invalid request before model dispatch or filesystem mutation."""

    if type(instruction) is not str or not instruction.strip():
        raise ValueError("task instruction must be nonempty")
    if not isinstance(original_rubric, CompleteRubric):
        raise ValueError("original_rubric must be a CompleteRubric")
    if not isinstance(development_rubric, CompleteRubric):
        raise ValueError("development_rubric must be a CompleteRubric")
    if development_rubric.content_sha256 == original_rubric.content_sha256:
        raise ValueError("development rubric must differ from the selected rubric")
    if not isinstance(current_generation, RubricGeneration):
        raise ValueError("current_generation must be a RubricGeneration")

    development_generation = RubricGeneration(
        generation_round=current_generation.generation_round,
        source_checkpoint=current_generation.source_checkpoint,
        rubric=render_augmented_rubric(
            development_rubric,
            current_generation.elicited_criteria,
        ),
        elicited_criteria=current_generation.elicited_criteria,
        proposer_call_budget=current_generation.proposer_call_budget,
    )
    if (
        development_generation.normalization_maximum
        != current_generation.normalization_maximum
        or development_generation.scoring_protocol
        != current_generation.scoring_protocol
    ):
        raise ValueError(
            "development and selected rubrics must use the same score scale"
        )

    if type(policy) is not RubricPolicy or policy not in {
        RubricPolicy.OFFLINE_ELICITATION,
        RubricPolicy.ONLINE_ELICITATION,
        RubricPolicy.RED_TEAM_ARTIFACT,
        RubricPolicy.RED_TEAM_TRACE,
    }:
        raise ValueError("criterion elicitation requires an elicitation policy")
    if type(generation_round) is not int:
        raise ValueError("generation_round must be an integer")
    if generation_round != current_generation.generation_round + 1:
        raise ValueError("rubric generations must be consecutive")
    if policy is RubricPolicy.OFFLINE_ELICITATION:
        if generation_round != 1:
            raise ValueError("offline elicitation has one pre-treatment generation")
        if source_checkpoint is not None:
            raise ValueError("offline elicitation cannot use a live checkpoint")
    elif generation_round == 1:
        if source_checkpoint is not None:
            raise ValueError(
                "the pre-treatment online rubric cannot use live evidence"
            )
    elif (
        type(source_checkpoint) is not int
        or source_checkpoint != generation_round - 1
    ):
        raise ValueError("online elicitation needs the preceding live checkpoint")
