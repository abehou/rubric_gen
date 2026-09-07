"""Resolve independently bound selected and master checkpoint judgments."""

from __future__ import annotations

import math
from numbers import Real
from pathlib import Path
from typing import TYPE_CHECKING

from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.controller_recovery_artifacts import (
    fixed_original_attempt_id,
)
from rubric_gen.submission_revision.judge import FrozenRubric, JudgeArtifacts, SubmissionJudge

if TYPE_CHECKING:
    from rubric_gen.submission_revision.controller_scoring import RevisionScorer


def resolve_reference_judgment(
    scorer: RevisionScorer,
    *,
    rubric: FrozenRubric,
    judge: SubmissionJudge,
    reuse_seed: bool,
    submission_dir: Path,
    submission_id: str,
    turn_index: int,
    active_artifacts: JudgeArtifacts,
    allow_generation: bool,
) -> tuple[float, JudgeArtifacts]:
    """Reuse only a judgment of this artifact under this exact reference."""
    generation = scorer.active_rubric_generation(turn_index)
    seeded = turn_index == 0 and reuse_seed
    if seeded:
        validation_path, evaluation_path, _ = scorer.seed.judgment
        artifacts = JudgeArtifacts(validation_path, evaluation_path)
    elif generation.rubric.content_sha256 == rubric.sha256:
        artifacts = active_artifacts
    else:
        artifacts = scorer.assignment_judgment(
            judge=judge,
            submission_dir=submission_dir,
            submission_id=submission_id,
            rubric_sha256=rubric.sha256,
            attempt_id=fixed_original_attempt_id(
                scorer.config.assignment_id, submission_id, rubric.sha256,
            ),
            allow_generation=allow_generation,
        )
    scorer.verify_round_scoring_identity(
        artifacts.score_validation_path, rubric, judge, seeded=seeded,
    )
    validation = read_json_object(artifacts.score_validation_path, "reference judgment")
    score = validation.get("score")
    if (
        isinstance(score, bool) or not isinstance(score, Real)
        or not math.isfinite(float(score)) or not 0 <= float(score) <= 100
    ):
        raise RuntimeError("reference judgment has an invalid score")
    return float(score), artifacts
