"""Ephemeral criterion views for revision signals; full judgments stay intact."""

from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass

from .judging.scoring import parse_rubric_levels_strict, validate_judge_score


def validate_dropout_rate(rate: object, policy: str) -> None:
    if type(rate) not in (int, float) or not 0 <= rate < 1:
        raise ValueError("rubric_dropout_rate must satisfy 0.0 <= rate < 1.0")
    if rate and policy != "red_team_trace":
        raise ValueError("nonzero rubric_dropout_rate requires red_team_trace")


@dataclass(frozen=True)
class RubricDropout:
    rate: float
    deterministic_key: str
    retained_ids: tuple[str, ...]
    dropped_ids: tuple[str, ...]

    def project(self, payload: dict[str, object], rubric_text: str) -> dict[str, object]:
        """Reuse the signed scorer on retained, canonically sourced judgments."""
        if not self.dropped_ids:
            return payload
        levels = parse_rubric_levels_strict(rubric_text)
        retained_levels = {key: levels[key] for key in self.retained_ids}
        criteria = payload["criteria"]
        retained = {key: criteria[key] for key in self.retained_ids}
        maximum = sum(max(0, max(points.values())) for points in retained_levels.values())
        score = validate_judge_score(
            rubric_levels=retained_levels,
            evaluation={"criteria": retained},
            reward={"score": payload["score"]},
            normalization_maximum=maximum,
        ).score
        result = {**payload, "score": score, "criteria": retained}
        if "rubric_text" in result:
            # Preserve criterion IDs and wording. This text is a feedback view,
            # never a CompleteRubric or a persisted learned generation.
            headers = list(re.finditer(r"(?m)^[ \t]*Criterion[ \t]+(\d+)[ \t]*:", rubric_text))
            context = rubric_text[:headers[0].start()]
            context = re.sub(r"(?m)^[ \t]*Score normalization maximum:.*$", "", context).strip()
            sections = [context, f"Score normalization maximum: {maximum}\n\n"]
            for index, header in enumerate(headers):
                if f"criterion_{header.group(1)}" in self.retained_ids:
                    end = headers[index + 1].start() if index + 1 < len(headers) else len(rubric_text)
                    sections.append(rubric_text[header.start():end])
            result["rubric_text"] = "\n".join(sections).strip() + "\n"
            # A free-form all-criteria summary cannot be safely attributed to
            # the retained subset. Retained per-criterion reasons remain intact.
            result["overall_reasoning"] = ""
        return result

    def record(self, optimization_score: float) -> dict[str, object]:
        return {
            "rate": self.rate,
            "deterministic_key": self.deterministic_key,
            "retained_criterion_ids": list(self.retained_ids),
            "dropped_criterion_ids": list(self.dropped_ids),
            "optimization_score": optimization_score,
        }


def revision_dropout(
    rubric_text: str, *, rate: float, seed: int, assignment_id: str, revision_round: int,
) -> RubricDropout | None:
    """One Bernoulli mask per assignment/solver turn, reproducible on replay."""
    validate_dropout_rate(rate, "red_team_trace")
    if rate == 0:
        return None
    levels = parse_rubric_levels_strict(rubric_text)
    eligible = sorted(key for key, points in levels.items() if max(points.values()) > 0)
    key = json.dumps(["rubric_dropout", seed, assignment_id, revision_round], separators=(",", ":"))
    rng = random.Random(int.from_bytes(hashlib.sha256(key.encode("utf-8")).digest(), "big"))
    kept = {key for key in eligible if rng.random() >= rate}
    minimum = min(3, len(eligible))
    if len(kept) < minimum:
        kept.update(rng.sample([key for key in eligible if key not in kept], minimum - len(kept)))
    dropped = set(eligible) - kept
    return RubricDropout(
        float(rate), key,
        tuple(key for key in levels if key not in dropped),
        tuple(key for key in levels if key in dropped),
    )
