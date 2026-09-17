"""Deterministic criterion masks for solver-facing RTT revision signals."""

from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_file

from .judging.scoring import parse_rubric_levels_strict, validate_judge_score
from .rubric_generation import RubricGeneration


VERSION = "rtt-rubric-dropout-fixed-count-v1"
EXECUTION_VERIFIED_VERSION = "attack_defense_v2.1_execution_verified"
_RATE_SUFFIX = re.compile(r"-dropout-(?:0|30|50)\Z")


def implementation_sha256() -> str:
    return sha256_file(Path(__file__))


def validate_dropout_rate(rate: object, trace_version: str | None) -> float:
    if isinstance(rate, bool) or type(rate) not in {int, float}:
        raise ValueError("rubric_dropout_rate must be a number")
    value = float(rate)
    if not math.isfinite(value) or not 0 <= value < 1:
        raise ValueError("rubric_dropout_rate must satisfy 0.0 <= rate < 1.0")
    if value and trace_version != EXECUTION_VERIFIED_VERSION:
        raise ValueError(
            "nonzero rubric_dropout_rate requires attack_defense_v2.1_execution_verified"
        )
    return value


def _criterion_number(value: str) -> int:
    match = re.fullmatch(r"criterion_(\d+)", value)
    if match is None:
        raise ValueError(f"invalid rubric criterion ID: {value!r}")
    return int(match.group(1))


def _paired_assignment_id(assignment_id: str) -> str:
    """Remove only the condition's rate so 30% is nested within 50%."""

    paired = _RATE_SUFFIX.sub("-dropout-shared", assignment_id)
    if paired == assignment_id:
        raise ValueError("execution-verified assignment ID lacks a dropout-rate suffix")
    return paired


@dataclass(frozen=True)
class RubricDropout:
    rate: float
    deterministic_key: str
    assignment_id: str
    mask_assignment_id: str
    eligible_ids: tuple[str, ...]
    protected_ids: tuple[str, ...]
    retained_ids: tuple[str, ...]
    dropped_ids: tuple[str, ...]
    retained_learned_ids: tuple[str, ...]
    dropped_learned_ids: tuple[str, ...]

    @property
    def realized_fraction(self) -> float:
        return len(self.dropped_ids) / len(self.eligible_ids) if self.eligible_ids else 0.0

    def project(self, payload: dict[str, object], rubric_text: str) -> dict[str, object]:
        """Mask one complete solver-facing payload without changing its judgment."""

        if not self.dropped_ids:
            return payload
        levels = parse_rubric_levels_strict(rubric_text)
        retained_levels = {key: levels[key] for key in self.retained_ids}
        criteria = payload.get("criteria")
        if type(criteria) is not dict:
            raise ValueError("dropout requires criterion-level feedback")
        retained = {key: criteria[key] for key in self.retained_ids}
        maximum = sum(max(0, max(points.values())) for points in retained_levels.values())
        if maximum <= 0:
            raise ValueError("dropout retained no positive-weight rubric criteria")
        masked_score = validate_judge_score(
            rubric_levels=retained_levels,
            evaluation={"criteria": retained},
            reward={"score": payload["score"]},
            normalization_maximum=maximum,
        ).score
        result = {**payload, "score": masked_score, "criteria": retained}
        if "rubric_text" in result:
            headers = list(
                re.finditer(r"(?m)^[ \t]*Criterion[ \t]+(\d+)[ \t]*:", rubric_text)
            )
            if not headers:
                raise ValueError("dropout could not locate rubric criteria")
            context = rubric_text[: headers[0].start()]
            context = re.sub(
                r"(?m)^[ \t]*Score normalization maximum:.*$", "", context
            ).strip()
            sections = [context, f"Score normalization maximum: {maximum}\n"]
            retained_set = set(self.retained_ids)
            for index, header in enumerate(headers):
                criterion_id = f"criterion_{header.group(1)}"
                if criterion_id not in retained_set:
                    continue
                end = headers[index + 1].start() if index + 1 < len(headers) else len(rubric_text)
                sections.append(rubric_text[header.start() : end].rstrip())
            result["rubric_text"] = "\n\n".join(sections).strip() + "\n"
            # The canonical overall summary is not attributable to the retained subset.
            result["overall_reasoning"] = ""
        return result

    def record(
        self,
        *,
        full_canonical_score: float,
        solver_visible_score: float,
        protected_ids: tuple[str, ...] = (),
        protected_reason: str | None = None,
    ) -> dict[str, object]:
        return {
            "kind": VERSION,
            "configured_rate": self.rate,
            "deterministic_key": self.deterministic_key,
            "assignment_id": self.assignment_id,
            "mask_assignment_id": self.mask_assignment_id,
            "eligible_criterion_ids": list(self.eligible_ids),
            "protected_ids": list(protected_ids),
            "protected_reason": protected_reason,
            "retained_criterion_ids": list(self.retained_ids),
            "dropped_criterion_ids": list(self.dropped_ids),
            "retained_learned_criterion_ids": list(self.retained_learned_ids),
            "dropped_learned_criterion_ids": list(self.dropped_learned_ids),
            "configured_fraction": self.rate,
            "realized_fraction": self.realized_fraction,
            "full_canonical_score": full_canonical_score,
            "solver_visible_masked_score": solver_visible_score,
        }


@dataclass(frozen=True)
class DropoutProjectedFeedback:
    """A version-local feedback view; the shared feedback module stays frozen."""

    score: float
    payload: dict[str, object]
    prompt: str
    rubric_dropout: dict[str, object]


def project_feedback(
    projected,
    mask: RubricDropout | None,
    generation: RubricGeneration,
    *,
    policy,
    task_instruction: str,
    first_revision: bool,
    prompt_profile,
    benchmark,
):
    """Apply one mask after canonical projection and rerender the same signal."""

    if mask is None:
        return projected
    from .feedback import FeedbackPolicy, render_revision_prompt

    resolved_policy = FeedbackPolicy(policy)
    if resolved_policy is FeedbackPolicy.USER_SIMULATOR:
        raise ValueError("mask the simulator's Full input before user projection")
    payload = mask.project(projected.payload, generation.rubric.content)
    if resolved_policy is FeedbackPolicy.SCORE_ONLY:
        payload = {"score": payload["score"]}
    record = mask.record(
        full_canonical_score=float(projected.score),
        solver_visible_score=float(payload["score"]),
    )
    return DropoutProjectedFeedback(
        score=float(projected.score),
        payload=payload,
        prompt=render_revision_prompt(
            resolved_policy,
            payload,
            task_instruction=task_instruction,
            first_revision=first_revision,
            prompt_profile=prompt_profile,
            benchmark=benchmark,
        ),
        rubric_dropout=record,
    )


def attach_record(projected, record: dict[str, object] | None):
    if record is None:
        return projected
    return DropoutProjectedFeedback(
        score=float(projected.score),
        payload=projected.payload,
        prompt=projected.prompt,
        rubric_dropout=record,
    )


def revision_dropout(
    generation: RubricGeneration,
    *,
    rate: float,
    seed: int,
    assignment_id: str,
    revision_round: int,
) -> RubricDropout | None:
    """Create one fixed-count mask for an assignment and solver revision."""

    resolved_rate = validate_dropout_rate(rate, generation.red_team_trace_version)
    if resolved_rate == 0:
        return None
    if type(seed) is not int:
        raise ValueError("rubric dropout seed must be an integer")
    if type(revision_round) is not int or revision_round < 1:
        raise ValueError("rubric dropout revision_round must be positive")

    levels = parse_rubric_levels_strict(generation.rubric.content)
    rubric_ids = tuple(sorted(levels, key=_criterion_number))
    learned_count = len(generation.elicited_criteria)
    base_count = len(rubric_ids) - learned_count
    if base_count < 0:
        raise ValueError("active rubric has fewer criteria than its learned set")
    positive_base = tuple(
        criterion_id
        for criterion_id in rubric_ids[:base_count]
        if max(levels[criterion_id].values()) > 0
    )
    learned_rubric_ids = rubric_ids[base_count:]
    learned_identity = {
        rubric_id: criterion.criterion_id
        for rubric_id, criterion in zip(
            learned_rubric_ids, generation.elicited_criteria, strict=True
        )
    }
    eligible = tuple(
        criterion_id
        for criterion_id in rubric_ids
        if criterion_id in positive_base or criterion_id in learned_identity
    )
    stable_identity = {
        criterion_id: learned_identity.get(criterion_id, criterion_id)
        for criterion_id in eligible
    }
    mask_assignment_id = _paired_assignment_id(assignment_id)
    deterministic_key = json.dumps(
        ["rubric_dropout", VERSION, seed, mask_assignment_id, revision_round],
        separators=(",", ":"),
    )
    ranking = sorted(
        eligible,
        key=lambda criterion_id: (
            hashlib.sha256(
                f"{deterministic_key}\0{stable_identity[criterion_id]}".encode("utf-8")
            ).hexdigest(),
            stable_identity[criterion_id],
        ),
    )
    minimum_positive = min(3, len(positive_base))
    maximum_drop = len(eligible) - minimum_positive
    target = min(math.floor(resolved_rate * len(eligible)), maximum_drop)
    positive_remaining = len(positive_base)
    dropped: list[str] = []
    for criterion_id in ranking:
        if len(dropped) == target:
            break
        if criterion_id in positive_base and positive_remaining <= minimum_positive:
            continue
        dropped.append(criterion_id)
        if criterion_id in positive_base:
            positive_remaining -= 1
    if len(dropped) != target:
        raise RuntimeError("dropout could not realize its fixed criterion count")
    dropped_set = set(dropped)
    retained = tuple(key for key in rubric_ids if key not in dropped_set)
    retained_learned = tuple(
        learned_identity[key] for key in learned_rubric_ids if key not in dropped_set
    )
    dropped_learned = tuple(
        learned_identity[key] for key in learned_rubric_ids if key in dropped_set
    )
    return RubricDropout(
        rate=resolved_rate,
        deterministic_key=deterministic_key,
        assignment_id=assignment_id,
        mask_assignment_id=mask_assignment_id,
        eligible_ids=eligible,
        protected_ids=(),
        retained_ids=retained,
        dropped_ids=tuple(key for key in rubric_ids if key in dropped_set),
        retained_learned_ids=retained_learned,
        dropped_learned_ids=dropped_learned,
    )
