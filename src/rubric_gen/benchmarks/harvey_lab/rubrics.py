"""Prospective task-level rubric changes for Harvey LAB."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from rubric_gen.benchmarks.harvey_lab.artifacts import validate_task
from rubric_gen.runtime.llm import (
    GenerationResult,
    StructuredRequest,
    generate_structured,
    generate_structured_vllm,
)


@dataclass(frozen=True)
class RubricProposal:
    task: dict[str, object]
    proposal: dict[str, object]
    generation: dict[str, object]


Generate = Callable[[str, StructuredRequest], GenerationResult]
GenerateVllm = Callable[[str, StructuredRequest, str], GenerationResult]


_INSTRUCTIONS = """You revise one Harvey LAB task rubric after a completed harness run.

The next rubric must measure the legal-work quality requested by the task. Use the
run only to find gaps, ambiguities, and accidental incentives in the current
rubric. Do not add criteria that reward the observed output merely because it was
observed. Do not refer to a harness, model, score, trajectory, or candidate in
rubric text. Preserve each criterion ID and deliverable scope. Propose a bounded
set of replacements for criterion titles and PASS/FAIL match criteria. A change
must remain independently usable on a new output from an unseen harness.

Return only the requested JSON object.
"""


def _schema(max_changes: int) -> dict[str, object]:
    return {
        "type": "object",
        "additionalProperties": False,
        "required": ["summary", "changes"],
        "properties": {
            "summary": {"type": "string", "minLength": 1},
            "changes": {
                "type": "array",
                "maxItems": max_changes,
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["criterion_id", "title", "match_criteria", "reason"],
                    "properties": {
                        "criterion_id": {"type": "string", "minLength": 1},
                        "title": {"type": "string", "minLength": 1},
                        "match_criteria": {"type": "string", "minLength": 1},
                        "reason": {"type": "string", "minLength": 1},
                    },
                },
            },
        },
    }


def _extract(text: str) -> dict[str, object]:
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end < start:
        raise ValueError("rubric proposer returned no JSON object")
    value = json.loads(text[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("rubric proposer output is not an object")
    return value


class TaskRubricProposer:
    def __init__(
        self,
        model: str,
        *,
        base_url: str | None,
        max_changes: int,
        max_output_tokens: int,
        generate_response: Generate = generate_structured,
        generate_vllm_response: GenerateVllm = generate_structured_vllm,
    ) -> None:
        self.model = model
        self.base_url = base_url
        self.max_changes = max_changes
        self.max_output_tokens = max_output_tokens
        self.generate_response = generate_response
        self.generate_vllm_response = generate_vllm_response

    def propose(
        self,
        task_file: Path,
        observation: dict[str, object],
    ) -> RubricProposal:
        task = validate_task(task_file)
        request = StructuredRequest(
            instructions=_INSTRUCTIONS,
            evidence=(
                "<current_task_json>\n"
                + json.dumps(task, ensure_ascii=False, sort_keys=True)
                + "\n</current_task_json>\n<completed_run_observation_json>\n"
                + json.dumps(observation, ensure_ascii=False, sort_keys=True)
                + "\n</completed_run_observation_json>\n"
            ),
            schema_name="harvey_task_rubric_revision",
            schema=_schema(self.max_changes),
            max_output_tokens=self.max_output_tokens,
        )
        generation = (
            self.generate_vllm_response(self.model, request, self.base_url)
            if self.base_url is not None
            else self.generate_response(self.model, request)
        )
        proposal = _extract(generation.text)
        revised = self._apply(task, proposal)
        return RubricProposal(revised, proposal, generation.provenance())

    def _apply(
        self, task: dict[str, object], proposal: dict[str, object]
    ) -> dict[str, object]:
        if set(proposal) != {"summary", "changes"} or type(proposal.get("summary")) is not str or not str(proposal["summary"]).strip():
            raise ValueError("rubric proposal has invalid top-level fields")
        changes = proposal.get("changes")
        if not isinstance(changes, list) or len(changes) > self.max_changes:
            raise ValueError("rubric proposal has invalid changes")
        by_id: dict[str, dict[str, object]] = {}
        for item in changes:
            if not isinstance(item, dict) or set(item) != {"criterion_id", "title", "match_criteria", "reason"}:
                raise ValueError("rubric proposal change has invalid fields")
            if any(type(item.get(key)) is not str or not str(item[key]).strip() for key in item):
                raise ValueError("rubric proposal change has an empty field")
            criterion_id = str(item["criterion_id"])
            if criterion_id in by_id:
                raise ValueError(f"rubric proposal repeats criterion {criterion_id}")
            by_id[criterion_id] = item
        current = task["criteria"]
        assert isinstance(current, list)
        known = {str(item["id"]) for item in current if isinstance(item, dict)}
        unknown = sorted(set(by_id) - known)
        if unknown:
            raise ValueError("rubric proposal names unknown criteria: " + ", ".join(unknown))
        revised_criteria = []
        for criterion in current:
            assert isinstance(criterion, dict)
            change = by_id.get(str(criterion["id"]))
            revised_criteria.append(
                dict(criterion)
                if change is None
                else {
                    **criterion,
                    "title": change["title"],
                    "match_criteria": change["match_criteria"],
                }
            )
        return {**task, "criteria": revised_criteria}
