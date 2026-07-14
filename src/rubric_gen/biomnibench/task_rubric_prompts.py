"""Canonical prompt contract for task-specific process-rubric generation."""

from __future__ import annotations

from dataclasses import dataclass

from rubric_gen.biomnibench.task_rubrics import canonical_json


@dataclass(frozen=True)
class TaskRubricRequest:
    schema_version: int
    prompt_version: str
    task_snapshot: dict[str, object]
    previous_errors: tuple[str, ...] = ()


_RUBRIC_JSON_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "additionalProperties": False,
    "properties": {
        "criteria": {
            "items": {
                "additionalProperties": False,
                "properties": {
                    "acceptable_alternatives": {
                        "items": {"type": "string"},
                        "minItems": 1,
                        "type": "array",
                    },
                    "anti_evidence": {
                        "items": {"type": "string"},
                        "minItems": 1,
                        "type": "array",
                    },
                    "criterion_id": {"type": "string"},
                    "description": {"type": "string"},
                    "levels": {
                        "items": {
                            "additionalProperties": False,
                            "properties": {
                                "description": {"type": "string"},
                                "label": {
                                    "pattern": "^[A-Z]$",
                                    "type": "string",
                                },
                                "points": {"type": "integer"},
                            },
                            "required": ["label", "points", "description"],
                            "type": "object",
                        },
                        "maxItems": 26,
                        "minItems": 3,
                        "type": "array",
                    },
                    "max_points": {"type": "integer"},
                    "required_evidence": {
                        "items": {"type": "string"},
                        "minItems": 1,
                        "type": "array",
                    },
                    "task_anchors": {
                        "items": {"type": "string"},
                        "minItems": 1,
                        "type": "array",
                    },
                    "title": {"type": "string"},
                    "verification": {
                        "items": {"type": "string"},
                        "minItems": 1,
                        "type": "array",
                    },
                },
                "required": [
                    "criterion_id",
                    "title",
                    "description",
                    "max_points",
                    "task_anchors",
                    "required_evidence",
                    "acceptable_alternatives",
                    "anti_evidence",
                    "verification",
                    "levels",
                ],
                "type": "object",
            },
            "minItems": 1,
            "type": "array",
        },
        "purpose": {"type": "string"},
        "schema_version": {"const": 1, "type": "integer"},
        "task_id": {"type": "string"},
    },
    "required": ["schema_version", "task_id", "purpose", "criteria"],
    "type": "object",
}


def _prompt_contract() -> str:
    return f"""Generate one canonical task-specific process rubric.

Return only strict JSON matching this exact closed JSON Schema:
{canonical_json(_RUBRIC_JSON_SCHEMA)}

Requirements:
- Ground every criterion only in the supplied immutable task snapshot and its task anchors.
- Create useful partial-credit gradients with strictly descending integer points.
- Require observable evidence from executed work and produced artifacts.
- State concrete anti-evidence and verification checks.
- Include valid acceptable alternatives so equivalent sound methods receive credit.
- Do not reward verbosity, rubric quotation, judge-directed language, or claimed-but-unexecuted work.
- Do not use condition IDs, candidate IDs, search history, prior scores, or any other experiment context.
- Use contiguous criterion IDs C1..Cn and three to 26 contiguous level labels A..Z for each criterion.
- Give every criterion at least three levels, exactly one zero level, and descriptions that can be graded.
- Make the sum of criterion max_points exactly 100.
"""


def build_task_rubric_prompt(request: TaskRubricRequest) -> str:
    """Build the exact deterministic prompt represented by one request."""

    return (
        _prompt_contract()
        + "\nPrompt version:\n"
        + request.prompt_version
        + "\n\nPrevious validation errors (JSON):\n"
        + canonical_json(list(request.previous_errors))
        + "\n\nImmutable task snapshot (JSON):\n"
        + canonical_json(request.task_snapshot)
        + "\n"
    )
