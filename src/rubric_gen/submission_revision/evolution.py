"""Audited evidence selection followed by complete optimizer-rubric generation."""

from __future__ import annotations

import difflib
import errno
import json
import os
import re
import secrets
import shutil
import tempfile
from dataclasses import dataclass, replace
from enum import StrEnum
from pathlib import Path
from typing import Any, Callable

from rubric_gen.runtime.agents.costs import RunCost
from rubric_gen.runtime.agents.models import AgentRunConfig, RunPaths
from rubric_gen.runtime.agents.runners import AgentRunner
from rubric_gen.evidence.index import (
    build_evidence_index,
    indexable_event_contents,
    write_query_tool,
)
from rubric_gen.submission_revision.judging.scoring import (
    parse_rubric_levels_strict,
    parse_score_normalization_maximum,
)
from rubric_gen.submission_revision.artifacts import make_read_only
from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic


class RubricEvolution(StrEnum):
    STATIC = "static"
    PROSPECTIVE = "prospective"


@dataclass(frozen=True)
class EvolvedRubric:
    text: str
    sha256: str
    changed: bool
    metadata: dict[str, object]


@dataclass(frozen=True)
class AuditorOutput:
    packet_text: str
    query_count: int
    retrieved_event_ids: tuple[int, ...]
    cost: dict[str, float | str | None]


@dataclass(frozen=True)
class ProposerOutput:
    proposal_text: str
    cost: dict[str, float | str | None]
    generation: dict[str, object]


@dataclass(frozen=True)
class RubricScoreContext:
    """Validated scoring context supplied to prospective rubric evolution."""

    score: int
    raw_score: int
    selected_levels: dict[str, str]
    criterion_scores: dict[str, int]
    score_history: tuple[int, ...]

    def __post_init__(self) -> None:
        if type(self.score) is not int or not 0 <= self.score <= 100:
            raise ValueError("rubric score context has an invalid normalized score")
        if type(self.raw_score) is not int:
            raise ValueError("rubric score context has an invalid raw score")
        if (
            not self.selected_levels
            or set(self.selected_levels) != set(self.criterion_scores)
            or any(
                type(key) is not str
                or type(value) is not str
                or not value
                for key, value in self.selected_levels.items()
            )
            or any(
                type(key) is not str or type(value) is not int
                for key, value in self.criterion_scores.items()
            )
        ):
            raise ValueError("rubric score context has invalid criterion results")
        if (
            not self.score_history
            or self.score_history[-1] != self.score
            or any(type(value) is not int or not 0 <= value <= 100 for value in self.score_history)
        ):
            raise ValueError("rubric score context has invalid score history")

    @property
    def saturated(self) -> bool:
        return self.score == 100 or all(
            level == "A" for level in self.selected_levels.values()
        )

    def as_json(self) -> dict[str, object]:
        return {
            "score": self.score,
            "raw_score": self.raw_score,
            "selected_levels": dict(self.selected_levels),
            "criterion_scores": dict(self.criterion_scores),
            "score_history": list(self.score_history),
            "saturated": self.saturated,
        }


_CRITERION_HEADER = re.compile(
    r"^[ \t]*Criterion[ \t]+(\d+)[ \t]*:", re.MULTILINE
)
_CRITERION_TITLE = re.compile(
    r"^[ \t]*Criterion[ \t]+\d+[ \t]*:[ \t]*(\S.*?)[ \t]*$",
    re.MULTILINE,
)
_LEVEL_DESCRIPTION = re.compile(
    r"^[ \t]*\[([A-Z])\]:[ \t]*\S", re.MULTILINE
)
_MAX_RUBRIC_CHARS = 100_000
_MAX_PACKET_CHARS = 24_000
_MAX_PACKET_SNIPPETS = 16
_MAX_SNIPPET_CHARS = 4_000
_MAX_PROBLEM_CHARS = 1_000
_MAX_INSPECTION_CHARS = 1_000
_MAX_UNCERTAINTY_CHARS = 1_000
_PROPOSER_MAX_OUTPUT_TOKENS = 32_768
_DIRECT_REQUEST_TIMEOUT_SECONDS = 600.0
_AUDITOR_PROMPT_VERSION = "trajectory-frontier-auditor-v3"
_AUDITOR_PACKET_SCHEMA_VERSION = 3
_PROPOSER_PROMPT_VERSION = "structured-frontier-rubric-v6"
_PROPOSER_SCHEMA_VERSION = 1
_AUDITOR_VALIDATION_MAX_RETRIES = 1
_PROPOSER_REASONING_EFFORT = "high"
_PROPOSER_TEXT_VERBOSITY = "low"
_FRONTIER_GATE_ERROR_PREFIX = (
    "candidate rubric did not move the saturated submission below its frontier"
)
_METADATA_KEYS = frozenset({
    "schema_version",
    "kind",
    "version",
    "mode",
    "source_submission_id",
    "source_submission_sha256",
    "source_trajectory_sha256",
    "auditor",
    "auditor_packet_sha256",
    "proposal_sha256",
    "proposal_decision",
    "challenge_changes",
    "score_context",
    "candidate_cross_score",
    "proposer",
    "attempt_count",
    "proposer_attempts",
    "parent_rubric_sha256",
    "rubric_sha256",
    "rubric_changed",
    "rubric_diff_sha256",
    "parent_criterion_count",
    "criterion_count",
    "available_trajectory_events",
})
_COST_KEYS = frozenset({"cost_usd", "estimated_cost_usd", "cost_source"})
_SNIPPET_KEYS = frozenset({
    "event_id", "start_offset", "end_offset",
})
_VERIFIED_SNIPPET_KEYS = _SNIPPET_KEYS | {"text"}
_PACKET_KEYS = frozenset({
    "schema_version",
    "inspected",
    "findings",
})
_FINDING_KEYS = frozenset({
    "finding_id",
    "kind",
    "hypothesis",
    "basis",
    "evidence",
    "counterevidence",
    "uncertainty",
    "verification_question",
})
_PROPOSAL_KEYS = frozenset({
    "schema_version",
    "decision",
    "rubric_title",
    "criteria",
    "challenge_changes",
})
_PROPOSAL_CRITERION_KEYS = frozenset({"title", "description", "levels"})
_PROPOSAL_LEVEL_KEYS = frozenset({"label", "points", "description"})
_CHALLENGE_CHANGE_KEYS = frozenset({
    "criterion_title",
    "finding_ids",
    "stable_quality_dimension",
    "current_evidence_gap",
    "future_submission_test",
})

_AUDITOR_OUTPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "integer", "enum": [3]},
        "inspected": {"type": "string", "maxLength": _MAX_INSPECTION_CHARS},
        "findings": {
            "type": "array",
            "maxItems": 8,
            "items": {
                "type": "object",
                "properties": {
                    "finding_id": {"type": "string"},
                    "kind": {
                        "type": "string",
                        "enum": ["supported_problem", "potential_concern"],
                    },
                    "hypothesis": {
                        "type": "string",
                        "maxLength": _MAX_PROBLEM_CHARS,
                    },
                    "basis": {
                        "type": "string",
                        "maxLength": _MAX_PROBLEM_CHARS,
                    },
                    "evidence": {
                        "type": "array",
                        "maxItems": 4,
                        "items": {"$ref": "#/$defs/snippet"},
                    },
                    "counterevidence": {
                        "type": "array",
                        "maxItems": 4,
                        "items": {"$ref": "#/$defs/snippet"},
                    },
                    "uncertainty": {
                        "type": "string",
                        "maxLength": _MAX_UNCERTAINTY_CHARS,
                    },
                    "verification_question": {
                        "type": "string",
                        "maxLength": _MAX_PROBLEM_CHARS,
                    },
                },
                "required": [
                    "finding_id",
                    "kind",
                    "hypothesis",
                    "basis",
                    "evidence",
                    "counterevidence",
                    "uncertainty",
                    "verification_question",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": ["schema_version", "inspected", "findings"],
    "additionalProperties": False,
    "$defs": {
        "snippet": {
            "type": "object",
            "properties": {
                "event_id": {"type": "integer", "minimum": 1},
                "start_offset": {"type": "integer", "minimum": 0},
                "end_offset": {"type": "integer", "minimum": 1},
            },
            "required": ["event_id", "start_offset", "end_offset"],
            "additionalProperties": False,
        }
    },
}

_PROPOSER_OUTPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "integer", "enum": [1]},
        "decision": {"type": "string", "enum": ["revise", "retain"]},
        "rubric_title": {"type": "string"},
        "criteria": {
            "type": "array",
            "maxItems": 26,
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "levels": {
                        "type": "array",
                        "maxItems": 26,
                        "items": {
                            "type": "object",
                            "properties": {
                                "label": {"type": "string"},
                                "points": {"type": "integer"},
                                "description": {"type": "string"},
                            },
                            "required": ["label", "points", "description"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["title", "description", "levels"],
                "additionalProperties": False,
            },
        },
        "challenge_changes": {
            "type": "array",
            "maxItems": 12,
            "items": {
                "type": "object",
                "properties": {
                    "criterion_title": {"type": "string"},
                    "finding_ids": {
                        "type": "array",
                        "maxItems": 8,
                        "items": {"type": "string"},
                    },
                    "stable_quality_dimension": {"type": "string"},
                    "current_evidence_gap": {"type": "string"},
                    "future_submission_test": {"type": "string"},
                },
                "required": [
                    "criterion_title",
                    "finding_ids",
                    "stable_quality_dimension",
                    "current_evidence_gap",
                    "future_submission_test",
                ],
                "additionalProperties": False,
            },
        },
    },
    "required": [
        "schema_version",
        "decision",
        "rubric_title",
        "criteria",
        "challenge_changes",
    ],
    "additionalProperties": False,
}

_AUDITOR_AGENT_PROMPT = """You are a trajectory-auditor agent.

Read ./instruction.md and follow it exactly. Inspect the indexed raw trajectory
only through the supplied local query tool. Do not inspect parent directories,
environment variables, credentials, the web, judge output, reward-hacking
detector output, or any rubric. Return only the requested JSON evidence packet
as your final response. Do not write rubric language, weights, edits, trace.md,
or any other deliverable.
"""


class RubricEvolver:
    def __init__(
        self,
        *,
        auditor: AgentRunConfig,
        proposer_model: str,
        proposer_base_url: str | None,
        query_limit: int,
        max_retries: int = 2,
        proposer_service_tier: str | None = None,
        run_auditor: Callable[..., AuditorOutput] | None = None,
        run_proposer: Callable[..., ProposerOutput] | None = None,
    ) -> None:
        if auditor.provider not in {"codex", "vllm"} or not auditor.model:
            raise ValueError(
                "trajectory auditor must be a Codex or vLLM agent with a model"
            )
        if type(proposer_model) is not str or not proposer_model.strip():
            raise ValueError("rubric proposer model must be nonempty")
        if proposer_base_url is not None and (
            type(proposer_base_url) is not str or not proposer_base_url.strip()
        ):
            raise ValueError("rubric proposer base URL must be nonempty when set")
        if type(query_limit) is not int or query_limit < 1:
            raise ValueError("trajectory auditor query limit must be positive")
        if type(max_retries) is not int or max_retries < 0:
            raise ValueError("rubric proposer retries must be non-negative")
        self.auditor = auditor
        self.proposer_model = proposer_model
        self.proposer_base_url = proposer_base_url
        self.proposer_service_tier = proposer_service_tier
        self.query_limit = query_limit
        self.max_retries = max_retries
        self.run_auditor = run_auditor or self._run_trajectory_auditor
        self.run_proposer = run_proposer or self._run_direct_proposer

    def evolve(
        self,
        *,
        instruction: str,
        current_rubric: str,
        current_submission: str,
        score_context: RubricScoreContext,
        trajectory_path: Path,
        version: int,
        source_submission_id: str,
        output_dir: Path,
        candidate_gate: Callable[[str, int], dict[str, object]] | None = None,
        candidate_validator: (
            Callable[[str, str], dict[str, object]] | None
        ) = None,
    ) -> EvolvedRubric:
        if candidate_gate is None or candidate_validator is None:
            raise ValueError(
                "prospective rubric evolution requires candidate gate and validator"
            )
        output_dir.mkdir(parents=True, exist_ok=True)
        rubric_path = output_dir / f"r{version:04d}.txt"
        metadata_path = output_dir / f"r{version:04d}.proposer.json"
        packet_path = output_dir / f"r{version:04d}.auditor.json"
        proposal_path = output_dir / f"r{version:04d}.proposal.json"
        diff_path = output_dir / f"r{version:04d}.diff"
        event_contents = indexable_event_contents(trajectory_path)
        source_hashes = {
            "source_submission_sha256": sha256_text(current_submission),
            "source_trajectory_sha256": sha256_text(
                trajectory_path.read_text(encoding="utf-8", errors="replace")
            ),
        }
        result_paths = (
            rubric_path,
            metadata_path,
            packet_path,
            proposal_path,
            diff_path,
        )
        if any(path.exists() for path in result_paths):
            return self._load_existing(
                rubric_path,
                metadata_path,
                packet_path,
                proposal_path,
                diff_path,
                version,
                source_submission_id,
                current_rubric,
                event_contents,
                source_hashes,
                score_context,
                instruction,
                current_submission,
                candidate_validator,
            )

        auditor_output: AuditorOutput | None = None
        auditor_error: Exception | None = None
        auditor_repair_error: str | None = None
        auditor_rejected_packet: str | None = None
        packet_text = ""
        rejected_packet: str | None = None
        for auditor_attempt in range(1, _AUDITOR_VALIDATION_MAX_RETRIES + 2):
            auditor_output = None
            auditor_repair_error = (
                str(auditor_error) if auditor_error is not None else None
            )
            auditor_rejected_packet = rejected_packet
            try:
                auditor_output = self.run_auditor(
                    trajectory_path=trajectory_path,
                    task_instruction=instruction,
                    score_context=score_context,
                    repair_error=auditor_repair_error,
                    rejected_packet=auditor_rejected_packet,
                )
                self._validate_auditor_output(auditor_output, event_contents)
                packet_text = _validated_evidence_packet(
                    auditor_output.packet_text,
                    event_contents=event_contents,
                    retrieved_events=frozenset(auditor_output.retrieved_event_ids),
                    materialized=False,
                    require_finding=score_context.saturated,
                )
                break
            except Exception as exc:
                if auditor_output is not None:
                    rejected_packet = auditor_output.packet_text
                    self._archive_failed_auditor_attempt(
                        output_dir,
                        version,
                        auditor_attempt,
                        auditor_output,
                        exc,
                    )
                auditor_error = exc
        else:
            assert auditor_error is not None
            raise auditor_error

        assert auditor_output is not None
        packet_sha256 = sha256_text(packet_text)

        last_error: Exception | None = None
        text = ""
        proposer_output: ProposerOutput | None = None
        proposal: dict[str, object] | None = None
        proposal_text = ""
        rejected_attempts: list[dict[str, str]] = []
        proposer_repair_error: str | None = None
        proposer_rejected_attempts: tuple[dict[str, str], ...] = ()
        candidate_cross_score: dict[str, object] | None = None
        proposer_attempts: list[dict[str, object]] = []
        attempt = 0
        for attempt in range(1, self.max_retries + 2):
            proposer_output = None
            attempt_recorded = False
            proposer_repair_error = str(last_error) if last_error is not None else None
            proposer_rejected_attempts = tuple(
                dict(rejected) for rejected in rejected_attempts
            )
            try:
                proposer_output = self.run_proposer(
                    instruction=instruction,
                    current_rubric=current_rubric,
                    current_submission=current_submission,
                    auditor_packet=packet_text,
                    score_context=score_context,
                    repair_error=proposer_repair_error,
                    rejected_attempts=proposer_rejected_attempts,
                )
                _validate_proposer_output(proposer_output)
                proposer_attempts.append({
                    "cost": dict(proposer_output.cost),
                    "generation": dict(proposer_output.generation),
                })
                attempt_recorded = True
                proposal, proposal_text = _validated_structured_proposal(
                    proposer_output.proposal_text,
                    current_rubric=current_rubric,
                    packet_text=packet_text,
                    saturated=score_context.saturated,
                )
                text = _proposal_rubric_text(
                    proposal,
                    current_rubric=current_rubric,
                )
                text = _validated_complete_rubric(text, current_rubric=current_rubric)
                changed_candidate = text != _normalize_rubric_text(current_rubric)
                if proposal["decision"] == "revise" and not changed_candidate:
                    raise ValueError("a revised rubric proposal must change the rubric")
                if changed_candidate:
                    candidate_cross_score = candidate_gate(text, attempt)
                    if candidate_cross_score.get("rubric_sha256") != sha256_text(text):
                        raise ValueError("candidate crossed score attests another rubric")
                _validate_candidate_cross_score(
                    candidate_cross_score,
                    score_context=score_context,
                    changed=changed_candidate,
                )
                break
            except Exception as exc:
                if proposer_output is not None:
                    rejected_attempts.append({
                        "validation_error": str(exc) or type(exc).__name__,
                        "structured_proposal": proposer_output.proposal_text,
                    })
                    self._archive_failed_attempt(
                        output_dir,
                        version,
                        attempt,
                        packet_sha256,
                        proposer_output,
                        exc,
                    )
                if not attempt_recorded:
                    proposer_attempts.append({
                        "cost": {
                            "cost_usd": None,
                            "estimated_cost_usd": None,
                            "cost_source": "unavailable_due_to_exception",
                        },
                        "generation": {
                            "status": "unavailable_due_to_exception",
                        },
                    })
                last_error = exc
        else:
            raise RuntimeError(
                "rubric proposer failed after "
                f"{self.max_retries + 1} attempts: {last_error}"
            )

        assert proposer_output is not None
        assert proposal is not None
        rubric_sha256 = sha256_text(text)
        parent_rubric_sha256 = sha256_text(current_rubric)
        changed = rubric_sha256 != parent_rubric_sha256
        rubric_diff = _rubric_diff(
            current_rubric,
            text,
            previous_version=version - 1,
            next_version=version,
        )
        temporary = output_dir / f".r{version:04d}.{secrets.token_hex(8)}.tmp"
        try:
            temporary.write_text(text, encoding="utf-8")
            os.replace(temporary, rubric_path)
        finally:
            if os.path.lexists(temporary):
                temporary.unlink()
        packet_path.write_text(packet_text, encoding="utf-8")
        proposal_path.write_text(proposal_text, encoding="utf-8")
        diff_path.write_text(rubric_diff, encoding="utf-8")
        metadata: dict[str, object] = {
            "schema_version": 7,
            "kind": "audited-complete-rubric-generation",
            "version": version,
            "mode": RubricEvolution.PROSPECTIVE.value,
            "source_submission_id": source_submission_id,
            **source_hashes,
            "auditor": self._auditor_identity(
                auditor_output,
                available_events=len(event_contents),
                score_context=score_context,
                task_instruction=instruction,
                repair_error=auditor_repair_error,
                rejected_packet=auditor_rejected_packet,
            ),
            "auditor_packet_sha256": packet_sha256,
            "proposal_sha256": sha256_text(proposal_text),
            "proposal_decision": proposal["decision"],
            "challenge_changes": proposal["challenge_changes"],
            "score_context": score_context.as_json(),
            "candidate_cross_score": candidate_cross_score,
            "proposer": self._proposer_identity(
                current_rubric,
                instruction=instruction,
                current_submission=current_submission,
                auditor_packet=packet_text,
                score_context=score_context,
                repair_error=proposer_repair_error,
                rejected_attempts=proposer_rejected_attempts,
            ),
            "attempt_count": attempt,
            "proposer_attempts": proposer_attempts,
            "parent_rubric_sha256": parent_rubric_sha256,
            "rubric_sha256": rubric_sha256,
            "rubric_changed": changed,
            "rubric_diff_sha256": sha256_text(rubric_diff),
            "parent_criterion_count": len(parse_rubric_levels_strict(current_rubric)),
            "criterion_count": len(parse_rubric_levels_strict(text)),
            "available_trajectory_events": len(event_contents),
        }
        write_json_atomic(metadata_path, metadata)
        for path in result_paths:
            make_read_only(path)
        return EvolvedRubric(text, rubric_sha256, changed, metadata)

    def _validate_auditor_output(
        self,
        output: AuditorOutput,
        event_contents: dict[int, str],
    ) -> None:
        if set(output.cost) != _COST_KEYS:
            raise ValueError("trajectory auditor returned invalid cost metadata")
        if (
            type(output.query_count) is not int
            or not 1 <= output.query_count <= self.query_limit
            or not isinstance(output.retrieved_event_ids, tuple)
            or tuple(sorted(set(output.retrieved_event_ids)))
            != output.retrieved_event_ids
            or not output.retrieved_event_ids
            or any(
                type(event) is not int or event not in event_contents
                for event in output.retrieved_event_ids
            )
        ):
            raise ValueError("trajectory auditor returned invalid retrieval metadata")

    def _auditor_identity(
        self,
        output: AuditorOutput,
        *,
        available_events: int,
        score_context: RubricScoreContext,
        task_instruction: str,
        repair_error: str | None,
        rejected_packet: str | None,
    ) -> dict[str, object]:
        task_prompt = _auditor_prompt(
            query_tool=Path("data/trajectory_query.py"),
            query_limit=self.query_limit,
            available_events=available_events,
            task_instruction=task_instruction,
            score_context=score_context,
            repair_error=repair_error,
            rejected_packet=rejected_packet,
        )
        return {
            "provider": self.auditor.provider,
            "model": self.auditor.model,
            "base_url": self.auditor.base_url,
            "reasoning_effort": self.auditor.reasoning_effort,
            "service_tier": self.auditor.service_tier,
            "timeout_seconds": self.auditor.timeout_seconds,
            "executable": self.auditor.executable,
            "prompt_version": _AUDITOR_PROMPT_VERSION,
            "prompt_sha256": sha256_text(
                _AUDITOR_AGENT_PROMPT + "\0" + task_prompt
            ),
            "repair_error": repair_error,
            "rejected_packet": rejected_packet,
            "packet_schema_version": _AUDITOR_PACKET_SCHEMA_VERSION,
            "query_limit": self.query_limit,
            "query_count": output.query_count,
            "retrieved_event_ids": list(output.retrieved_event_ids),
            "cost": dict(output.cost),
        }

    def _proposer_identity(
        self,
        current_rubric: str,
        *,
        instruction: str,
        current_submission: str,
        auditor_packet: str,
        score_context: RubricScoreContext,
        repair_error: str | None,
        rejected_attempts: tuple[dict[str, str], ...],
    ) -> dict[str, object]:
        instructions = _proposer_instructions(
            current_rubric=current_rubric,
            repair_error=repair_error,
        )
        evidence = _proposer_evidence(
            instruction=instruction,
            current_rubric=current_rubric,
            current_submission=current_submission,
            auditor_packet=auditor_packet,
            score_context=score_context,
            rejected_attempts=rejected_attempts,
        )
        return {
            "provider": "vllm" if self.proposer_base_url is not None else "openai",
            "model": self.proposer_model,
            "base_url": (
                self.proposer_base_url.rstrip("/") + "/"
                if self.proposer_base_url is not None else None
            ),
            "prompt_version": _PROPOSER_PROMPT_VERSION,
            "output_schema_version": _PROPOSER_SCHEMA_VERSION,
            "prompt_sha256": sha256_text(instructions + "\0" + evidence),
            "repair_error": repair_error,
            "rejected_attempts": [dict(attempt) for attempt in rejected_attempts],
            "max_output_tokens": _PROPOSER_MAX_OUTPUT_TOKENS,
            "reasoning_effort": (
                None if self.proposer_base_url is not None
                else _PROPOSER_REASONING_EFFORT
            ),
            "text_verbosity": (
                None if self.proposer_base_url is not None
                else _PROPOSER_TEXT_VERBOSITY
            ),
            "service_tier": self.proposer_service_tier,
        }

    @staticmethod
    def _archive_failed_auditor_attempt(
        output_dir: Path,
        version: int,
        evolve_attempt: int,
        auditor_output: AuditorOutput,
        error: Exception,
    ) -> None:
        failure_dir = output_dir / f"r{version:04d}.auditor-failures"
        failure_dir.mkdir(exist_ok=True)
        sequence = len(list(failure_dir.glob("attempt-*.json"))) + 1
        stem = f"attempt-{sequence:04d}"
        packet_path = failure_dir / f"{stem}.txt"
        metadata_path = failure_dir / f"{stem}.json"
        packet_path.write_text(
            auditor_output.packet_text,
            encoding="utf-8",
        )
        write_json_atomic(
            metadata_path,
            {
                "schema_version": 1,
                "evolve_attempt": evolve_attempt,
                "error_type": type(error).__name__,
                "error": str(error) or type(error).__name__,
                "query_count": auditor_output.query_count,
                "retrieved_event_ids": list(auditor_output.retrieved_event_ids),
                "cost": auditor_output.cost,
            },
        )
        make_read_only(packet_path)
        make_read_only(metadata_path)

    @staticmethod
    def _archive_failed_attempt(
        output_dir: Path,
        version: int,
        evolve_attempt: int,
        packet_sha256: str,
        proposer_output: ProposerOutput,
        error: Exception,
    ) -> None:
        failure_dir = output_dir / f"r{version:04d}.proposer-failures"
        failure_dir.mkdir(exist_ok=True)
        sequence = len(list(failure_dir.glob("attempt-*.json"))) + 1
        stem = f"attempt-{sequence:04d}"
        proposal_path = failure_dir / f"{stem}.txt"
        metadata_path = failure_dir / f"{stem}.json"
        proposal_path.write_text(
            proposer_output.proposal_text,
            encoding="utf-8",
        )
        write_json_atomic(
            metadata_path,
            {
                "schema_version": 2,
                "evolve_attempt": evolve_attempt,
                "auditor_packet_sha256": packet_sha256,
                "error_type": type(error).__name__,
                "error": str(error) or type(error).__name__,
                "cost": proposer_output.cost,
                "generation": proposer_output.generation,
            },
        )
        make_read_only(proposal_path)
        make_read_only(metadata_path)

    def _load_existing(
        self,
        rubric_path: Path,
        metadata_path: Path,
        packet_path: Path,
        proposal_path: Path,
        diff_path: Path,
        version: int,
        source_submission_id: str,
        current_rubric: str,
        event_contents: dict[int, str],
        source_hashes: dict[str, str],
        score_context: RubricScoreContext,
        instruction: str,
        current_submission: str,
        candidate_validator: Callable[[str, str], dict[str, object]],
    ) -> EvolvedRubric:
        if not all(path.is_file() for path in (
            rubric_path, metadata_path, packet_path, proposal_path, diff_path
        )):
            raise RuntimeError(f"incomplete evolved rubric version r{version:04d}")
        try:
            text = rubric_path.read_text(encoding="utf-8")
            stored = json.loads(metadata_path.read_text(encoding="utf-8"))
            packet_text = packet_path.read_text(encoding="utf-8")
            proposal_text = proposal_path.read_text(encoding="utf-8")
            rubric_diff = diff_path.read_text(encoding="utf-8")
            proposal, expected_proposal = _validated_structured_proposal(
                proposal_text,
                current_rubric=current_rubric,
                packet_text=packet_text,
                saturated=score_context.saturated,
            )
            proposal_rubric = _proposal_rubric_text(
                proposal,
                current_rubric=current_rubric,
            )
            expected_text = _validated_complete_rubric(
                text,
                current_rubric=current_rubric,
            )
            parent_criterion_count = len(
                parse_rubric_levels_strict(current_rubric)
            )
            criterion_count = len(parse_rubric_levels_strict(text))
        except (
            OSError,
            UnicodeError,
            json.JSONDecodeError,
            TypeError,
            ValueError,
        ) as exc:
            raise RuntimeError(
                f"invalid evolved rubric version r{version:04d}"
            ) from exc

        expected_diff = _rubric_diff(
            current_rubric,
            text,
            previous_version=version - 1,
            next_version=version,
        )
        changed = sha256_text(text) != sha256_text(current_rubric)
        auditor = stored.get("auditor") if isinstance(stored, dict) else None
        retrieved = auditor.get("retrieved_event_ids") if isinstance(auditor, dict) else None
        expected_auditor_identity = None
        if isinstance(auditor, dict) and isinstance(retrieved, list):
            try:
                auditor_repair_error, rejected_packet = _repair_context(
                    auditor,
                    rejected_field="rejected_packet",
                )
                output = AuditorOutput(
                    packet_text=packet_text,
                    query_count=auditor["query_count"],
                    retrieved_event_ids=tuple(retrieved),
                    cost=auditor["cost"],
                )
                self._validate_auditor_output(output, event_contents)
                expected_auditor_identity = self._auditor_identity(
                    output,
                    available_events=len(event_contents),
                    score_context=score_context,
                    task_instruction=instruction,
                    repair_error=auditor_repair_error,
                    rejected_packet=rejected_packet,
                )
                expected_packet = _validated_evidence_packet(
                    packet_text,
                    event_contents=event_contents,
                    retrieved_events=frozenset(output.retrieved_event_ids),
                    materialized=True,
                    require_finding=score_context.saturated,
                )
            except (KeyError, TypeError, ValueError):
                expected_packet = None
        else:
            expected_packet = None
        proposer = stored.get("proposer") if isinstance(stored, dict) else None
        expected_proposer_identity = None
        if isinstance(proposer, dict):
            try:
                proposer_repair_error, rejected_attempts = (
                    _proposer_repair_context(proposer)
                )
                expected_proposer_identity = self._proposer_identity(
                    current_rubric,
                    instruction=instruction,
                    current_submission=current_submission,
                    auditor_packet=packet_text,
                    score_context=score_context,
                    repair_error=proposer_repair_error,
                    rejected_attempts=rejected_attempts,
                )
            except (KeyError, TypeError, ValueError):
                expected_proposer_identity = None
        candidate_cross_score = (
            stored.get("candidate_cross_score")
            if isinstance(stored, dict)
            else None
        )
        expected_candidate_cross_score = None
        if changed and isinstance(candidate_cross_score, dict):
            attempt_id = candidate_cross_score.get("attempt_id")
            if type(attempt_id) is str:
                try:
                    expected_candidate_cross_score = candidate_validator(
                        text,
                        attempt_id,
                    )
                except (OSError, RuntimeError, TypeError, ValueError):
                    expected_candidate_cross_score = None
        if (
            not isinstance(stored, dict)
            or set(stored) != _METADATA_KEYS
            or stored.get("schema_version") != 7
            or stored.get("kind") != "audited-complete-rubric-generation"
            or stored.get("version") != version
            or stored.get("mode") != RubricEvolution.PROSPECTIVE.value
            or stored.get("source_submission_id") != source_submission_id
            or any(stored.get(key) != value for key, value in source_hashes.items())
            or stored.get("auditor") != expected_auditor_identity
            or expected_packet != packet_text
            or stored.get("auditor_packet_sha256") != sha256_text(packet_text)
            or expected_proposal != proposal_text
            or stored.get("proposal_sha256") != sha256_text(proposal_text)
            or stored.get("proposal_decision") != proposal["decision"]
            or stored.get("challenge_changes") != proposal["challenge_changes"]
            or stored.get("score_context") != score_context.as_json()
            or not _valid_candidate_cross_score(
                candidate_cross_score,
                score_context=score_context,
                changed=changed,
            )
            or (
                isinstance(stored.get("candidate_cross_score"), dict)
                and stored["candidate_cross_score"].get("rubric_sha256")
                != sha256_text(text)
            )
            or candidate_cross_score != expected_candidate_cross_score
            or stored.get("proposer") != expected_proposer_identity
            or type(stored.get("attempt_count")) is not int
            or stored["attempt_count"] < 1
            or not _valid_proposer_attempts(
                stored.get("proposer_attempts"), stored["attempt_count"]
            )
            or stored.get("rubric_sha256") != sha256_text(text)
            or stored.get("parent_rubric_sha256") != sha256_text(current_rubric)
            or stored.get("rubric_changed") is not changed
            or (proposal["decision"] == "revise") is not changed
            or stored.get("rubric_diff_sha256") != sha256_text(rubric_diff)
            or rubric_diff != expected_diff
            or stored.get("parent_criterion_count") != parent_criterion_count
            or stored.get("criterion_count") != criterion_count
            or stored.get("available_trajectory_events") != len(event_contents)
            or expected_text != text
            or proposal_rubric != text
        ):
            raise RuntimeError(f"invalid evolved rubric version r{version:04d}")
        return EvolvedRubric(text, sha256_text(text), changed, stored)

    def _run_trajectory_auditor(
        self,
        *,
        trajectory_path: Path,
        task_instruction: str,
        score_context: RubricScoreContext,
        repair_error: str | None,
        rejected_packet: str | None,
    ) -> AuditorOutput:
        temporary = Path(tempfile.mkdtemp(prefix="submission-trajectory-auditor-"))
        try:
            task = temporary / "task"
            data = task / "environment" / "data"
            data.mkdir(parents=True)
            workspace = temporary / "workspace"
            evidence = temporary / "evidence"
            evidence.mkdir()
            linked_trajectory = evidence / "trajectory.stream.jsonl"
            _link_or_copy(trajectory_path, linked_trajectory)
            write_json_atomic(evidence / "manifest.json", {
                "schema_version": 1,
                "kind": "trajectory-auditor-evidence",
                "evidence_files": [linked_trajectory.name],
            })
            database = data / "trajectory.sqlite"
            inventory = build_evidence_index(evidence, database)
            query_tool = data / "trajectory_query.py"
            write_query_tool(
                query_tool,
                database,
                max_queries=self.query_limit,
                state_directory=data.parent / "artifacts",
            )
            (task / "instruction.md").write_text(
                _auditor_prompt(
                    query_tool=Path("data/trajectory_query.py"),
                    query_limit=self.query_limit,
                    available_events=int(inventory["events"]),
                    task_instruction=task_instruction,
                    score_context=score_context,
                    repair_error=repair_error,
                    rejected_packet=rejected_packet,
                ),
                encoding="utf-8",
            )
            run = temporary / "run"
            run.mkdir()
            schema_path = run / "auditor-output.schema.json"
            write_json_atomic(schema_path, _AUDITOR_OUTPUT_SCHEMA)
            packet_output_path = workspace / "auditor.packet.json"
            paths = RunPaths(
                provider=self.auditor.provider,
                run_dir=run,
                workspace_dir=workspace,
                prompt_path=run / "prompt.txt",
                policy_path=run / "no-web-policy.toml",
                stream_path=run / "trajectory.stream.jsonl",
                status_path=run / "status.json",
                output_schema_path=schema_path,
                output_last_message_path=packet_output_path,
            )
            config = replace(self.auditor, quiet=True)
            exit_code, _ = AgentRunner(
                config,
                prompt=_AUDITOR_AGENT_PROMPT,
                required_outputs=(packet_output_path.name,),
            ).run(task, paths=paths)
            if exit_code != 0:
                raise RuntimeError(
                    f"{self.auditor.provider} trajectory auditor exited with code "
                    f"{exit_code}"
                )
            query_state = workspace / "artifacts"
            audit = query_state / "query-audit.jsonl"
            if not audit.is_file():
                raise RuntimeError("trajectory auditor query audit is missing")
            audit_records = [
                json.loads(line)
                for line in audit.read_text(encoding="utf-8").splitlines()
            ]
            query_count = len(audit_records)
            retrieved = tuple(sorted({
                event
                for record in audit_records
                for event in record.get("event_ids", [])
                if type(event) is int
            }))
            cost = RunCost.from_stream(
                paths.stream_path,
                model=self.auditor.model,
                service_tier=self.auditor.service_tier,
            ).fields()
            return AuditorOutput(
                packet_text=packet_output_path.read_text(encoding="utf-8"),
                query_count=query_count,
                retrieved_event_ids=retrieved,
                cost=cost,
            )
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def _run_direct_proposer(
        self,
        *,
        instruction: str,
        current_rubric: str,
        current_submission: str,
        auditor_packet: str,
        score_context: RubricScoreContext,
        repair_error: str | None,
        rejected_attempts: tuple[dict[str, str], ...],
    ) -> ProposerOutput:
        instructions = _proposer_instructions(
            current_rubric=current_rubric,
            repair_error=repair_error,
        )
        evidence = _proposer_evidence(
            instruction=instruction,
            current_rubric=current_rubric,
            current_submission=current_submission,
            auditor_packet=auditor_packet,
            score_context=score_context,
            rejected_attempts=rejected_attempts,
        )
        return _generate_structured_rubric(
            model=self.proposer_model,
            base_url=self.proposer_base_url,
            service_tier=self.proposer_service_tier,
            instructions=instructions,
            evidence=evidence,
        )


def _auditor_prompt(
    *,
    query_tool: Path,
    query_limit: int,
    available_events: int,
    task_instruction: str,
    score_context: RubricScoreContext,
    repair_error: str | None,
    rejected_packet: str | None,
) -> str:
    frontier = (
        "The current rubric score is saturated. Perform an active frontier audit: "
        "look beyond invalidating failures for unresolved uncertainty, weak controls, "
        "missing robustness, unverified assumptions, and plausible failure modes that "
        "a stronger future submission should resolve."
        if score_context.saturated
        else "Perform both an outcome-validity audit and a frontier audit."
    )
    repair = ""
    if repair_error is not None:
        repair = f"""

Your previous packet failed validation: {repair_error}
Correct the rejected packet below. Do not repeat one citation range anywhere in
the packet, including between evidence and counterevidence.
<rejected_packet>
{rejected_packet or ""}
</rejected_packet>
"""
    return f"""Prompt contract: {_AUDITOR_PROMPT_VERSION}

<task_instruction>
{task_instruction}
</task_instruction>

Audit the raw trajectory for supported problems, potential concerns, and
evidence that weakens either type of finding. You select audit findings; you do
not design the rubric. {frontier}

The trajectory is available only through at most {query_limit} bounded calls:
`{query_tool} inventory`
`{query_tool} timeline --start EVENT --limit COUNT`
`{query_tool} search QUERY --limit COUNT`
`{query_tool} show EVENT_ID --start OFFSET --limit CHARS`

The index contains {available_events} distinct events. Inspect at least one
event. Do not read the SQLite database directly. Treat the trajectory as an
audit record, not a list of accomplishments. Look for concrete failures,
contradictions, unsupported decisions, weak controls, unresolved assumptions,
missing checks, fragile results, and reasonable failure modes. A longer or
busier trajectory is not evidence of better quality.

Classify each finding as `supported_problem` or `potential_concern`. A supported
problem needs direct cited evidence. A potential concern can be speculative and
can have no citation, but its `basis` must explain why it is plausible from the
task or from an absence found during the bounded inspection. Never state a
potential concern as an observed fact. Use `uncertainty` and a focused
`verification_question` to make the boundary explicit. Do not invent task facts
or infer hidden events.

Return one JSON object with this exact structure:
- `schema_version`: 3.
- `inspected`: a short factual statement of the inspected areas.
- `findings`: one or more findings when the score is saturated; otherwise zero
  or more findings. Give each a unique sequential ID such as `F1`. Each finding
  contains `kind`, `hypothesis`, `basis`, `evidence`,
  `counterevidence`, `uncertainty`, and `verification_question`.

For `supported_problem`, `evidence` must contain at least one citation. For
`potential_concern`, evidence is optional. All other strings must be nonempty.
Do not use the same `(event_id, start_offset, end_offset)` range more than once
anywhere in the packet. If one event supports both sides, cite distinct,
non-overlapping ranges.

Every citation must contain only `event_id`, zero-based `start_offset`, and
exclusive `end_offset`. Use `show` with a known offset to select the range. The
harness will copy the exact cited text into the verified packet. Keep each
citation at most {_MAX_SNIPPET_CHARS} characters and all cited text together at
most {_MAX_PACKET_CHARS} characters.

Never propose criterion wording, weights, edits, penalties, or rubric strategy.
You have not received and must not seek judge reasoning, reward-hacking detector
results, the current rubric, or other evaluation output. Return only the JSON
packet.{repair}
"""


def _proposer_instructions(
    *,
    current_rubric: str,
    repair_error: str | None,
) -> str:
    repair = ""
    if repair_error is not None:
        repair = (
            "\n\nThe previous structured proposal failed validation: "
            + repair_error
        )
        if repair_error.startswith(_FRONTIER_GATE_ERROR_PREFIX):
            repair += """

The rejected rubric failed an empirical cross-score against the frozen current
submission. Treat the score and level counts in the validation error as proof
that the rejected A-level thresholds did not expose a new quality frontier.
Review every entry in `rejected_structured_proposal_history`; do not repeat a
failed threshold, cosmetic rewrite, or equivalent challenge set.

Before returning the corrected proposal:
1. Compare the current submission with each verified auditor finding and each
   rejected A-level requirement.
2. Select a different stable, task-valid outcome gap that the current submission
   does not establish. If one finding is already resolved, use another finding
   or a materially stronger unresolved dimension that the packet supports.
3. Put the missing outcome directly into at least one A-level description cited
   by `challenge_changes`; make its next lower level give appropriate credit for
   the bounded outcome that is established.
4. Privately verify that the frozen current submission should score below A on
   that criterion before you return the JSON.

Do not manufacture a gap through arbitrary busywork, submission-specific
wording, or a method that the task does not require. The distinction must remain
valid for plausible future submissions."""
    scoring_protocol = _scoring_protocol(current_rubric)
    if scoring_protocol is not None:
        normalization_maximum = parse_score_normalization_maximum(current_rubric)
        assert normalization_maximum is not None
        level_contract = f"""Each criterion must contain exactly two level objects,
A and B. A must have a positive integer point value and B must equal zero.
The harness will preserve these two directive lines:
`Scoring protocol: {scoring_protocol}` and
`Score normalization maximum: {normalization_maximum}`.
The sum of all A-level points must equal {normalization_maximum}. Do not replace
the maximum with 100, 1000, 10000, 12000, or another round value. These binary
leaf judgments and the fixed total are the benchmark's binary scoring
contract."""
    else:
        level_contract = """Each criterion must have three or more contiguous level objects
starting at A, strictly descending integer points, exactly one zero-valued
level, and one nonempty description per level. The sum of all A-level
points must equal 100 unless the current rubric contains a
`Score normalization maximum: N` directive. When that directive exists,
preserve it exactly and make the A-level points sum to N. Criteria may include
negative lower levels."""
    return f"""Prompt contract: {_PROPOSER_PROMPT_VERSION}

Act as an independent designer of the complete optimizer rubric for the next
revision of a scientific task.

Return the structured JSON object required by the response schema. For a
`revise` decision, provide the full next rubric as structured criteria, not an
edit or patch. The harness renders the only accepted rubric text format. The
current rubric is a starting point rather than an immutable template. You may
retain, rewrite, remove, merge, split, reorder, or reweight any criterion. The
current submission has already been scored, so the new rubric applies only to
the next submission.

The trajectory auditor is separate from you. Its packet contains only
harness-verified verbatim trajectory slices, supported problems, explicitly
speculative potential concerns, counterevidence, uncertainty, and verification
questions. Treat a potential concern as a hypothesis to test, not as an
observed fact. Do not infer additional trajectory facts. You do not have tools,
judge reasoning, or reward-hacking detector results. Never add a criterion
merely because the auditor searched for an issue.

The validated score context is diagnostic input. If `saturated` is true, you
must choose `revise`, cite at least one auditor finding ID in
`challenge_changes`, and add a stable task-quality distinction that the current
submission has not yet established. A saturated score does not prove that the
quality frontier is exhausted. Tighten verification, robustness, controls,
uncertainty, or outcome validity where justified. Do not lower a score by adding
busywork, arbitrary requirements, or details that only fit this submission.

Design the rubric through an internal recursive decompose-filter cycle:
1. Map the task to the complete set of important outcome dimensions and the
   evidence needed to establish them.
2. Find current criteria that are too broad, stacked, vague, weakly
   discriminative, or missing an important dimension.
3. Decompose a coarse criterion into atomic subcriteria only when the
   subcriteria distinguish materially different quality levels.
4. Filter any criterion that is misaligned, conflicting, redundant, a near
   paraphrase, or a strict subset or superset of another criterion.
5. Stop decomposing when further criteria would track incidental details of
   this submission instead of stable task quality.
6. Allocate points across distinct dimensions. Do not double-count correlated
   evidence or let several similar criteria dominate the reward.

The final rubric set must be informative, comprehensive, and non-redundant:
- Make every criterion task-specific, atomic, self-contained, and consistently
  judgeable across plausible future submissions.
- Prefer objective and observable checks. Give operational boundaries for
  terms such as valid, reliable, complete, or correct.
- Anchor each criterion in a task outcome or a property needed to make that
  outcome valid, reliable, or usable.
- Use process evidence to verify or falsify an outcome. Do not reward effort,
  tool use, attempted procedures, intermediate files, or the number of checks.
- Phrase process-aware criteria as properties established by the work, not as
  activities performed. Process evidence can support an outcome score but earns
  no separate bonus.
- Give credit for equivalent valid methods. Do not prescribe one exact command,
  filename, wording, numerical result, or analysis path unless the task requires
  it.
- Do not reward documentation, a checklist, a PASS label, a manifest, file
  existence, or a solver claim that work occurred without independent support.
- Make level descriptions meaningfully discriminative. A must describe a
  complete supported outcome. Each intermediate level must describe an
  independently useful but bounded outcome or a material outcome defect. Do
  not reward partial execution toward an unusable result. The lowest level must describe a
  missing, contradicted, invalid, unusable, or merely asserted outcome.
- Keep preference direction positive. Higher levels must represent genuinely
  better task results, validity, reliability, or usability, not more visible
  activity or closer imitation of evaluator language.
- Prevent one failure from losing points under several criteria. Cover all
  important dimensions without semantic overlap.
- Use the current submission and verified packet as evidence about rubric weakness,
  not as an answer key. Do not fit or punish an incidental feature of this one
  submission.
- Privately test each criterion against a complete supported outcome, an
  independently useful bounded outcome, and an unusable outcome accompanied by
  extensive activity. Keep only criteria whose scores track outcome quality.
- Apply an activity-invariance test. If two submissions establish the same
  outcome, do not prefer the one with a longer or busier trajectory. If removing
  an activity leaves the established outcome unchanged, that activity deserves
  no rubric weight.

The complete rubric must use contiguous `Criterion 1:` through `Criterion N:`
sections after harness rendering. {level_contract}

For every `revise` decision, populate `challenge_changes`. Each change must name
one criterion title in the proposed rubric, cite one or more valid finding IDs,
identify a stable quality dimension, state the current evidence gap without
turning speculation into fact, and define how a future submission can establish
the stronger outcome. If the score is not saturated and no task-valid revision
improves discrimination, choose `retain` and return empty `rubric_title`,
`rubric_title` as an empty string and return empty `criteria` and
`challenge_changes` arrays. Return only the schema-conforming JSON object.{repair}
"""


def _proposer_evidence(
    *,
    instruction: str,
    current_rubric: str,
    current_submission: str,
    auditor_packet: str,
    score_context: RubricScoreContext,
    rejected_attempts: tuple[dict[str, str], ...],
) -> str:
    repair = (
        ""
        if not rejected_attempts
        else f"""<rejected_structured_proposal_history>
{json.dumps(rejected_attempts, ensure_ascii=False, sort_keys=True)}
</rejected_structured_proposal_history>
"""
    )
    return f"""<task_instruction>
{instruction}
</task_instruction>
<current_submission>
{current_submission}
</current_submission>
<current_complete_rubric>
{current_rubric}
</current_complete_rubric>
<verified_auditor_packet>
{auditor_packet}</verified_auditor_packet>
<validated_score_context>
{json.dumps(score_context.as_json(), ensure_ascii=False, sort_keys=True)}
</validated_score_context>
{repair}
"""


def _generate_structured_rubric(
    *,
    model: str,
    base_url: str | None,
    service_tier: str | None,
    instructions: str,
    evidence: str,
) -> ProposerOutput:
    from openai import OpenAI

    if base_url is not None:
        normalized_base_url = base_url.rstrip("/") + "/"
        response = OpenAI(
            base_url=normalized_base_url,
            api_key=os.getenv("VLLM_API_KEY", "EMPTY"),
            timeout=_DIRECT_REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        ).chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": instructions},
                {"role": "user", "content": evidence},
            ],
            max_tokens=_PROPOSER_MAX_OUTPUT_TOKENS,
            temperature=0,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "submission_frontier_rubric_proposal",
                    "strict": True,
                    "schema": _PROPOSER_OUTPUT_SCHEMA,
                },
            },
        )
        text = response.choices[0].message.content or ""
        if not text:
            raise RuntimeError("vLLM returned an empty rubric response")
        usage = _jsonable(getattr(response, "usage", None))
        generation = {
            "provider": "vllm",
            "requested_model": model,
            "effective_model": str(getattr(response, "model", model)),
            "response_id": getattr(response, "id", None),
            "request_parameters": {
                "base_url": normalized_base_url,
                "max_tokens": _PROPOSER_MAX_OUTPUT_TOKENS,
                "temperature": 0,
                "client_timeout_seconds": _DIRECT_REQUEST_TIMEOUT_SECONDS,
                "client_max_retries": 0,
                "response_format": "json_schema",
            },
            "usage": usage,
        }
        return ProposerOutput(
            proposal_text=text,
            cost=_cost_from_usage(usage, model=model, service_tier=None),
            generation=generation,
        )

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY must be set for the rubric proposer")
    arguments: dict[str, object] = {
        "model": model,
        "input": [
            {
                "role": "developer",
                "content": [{
                    "type": "input_text",
                    "text": instructions,
                    "prompt_cache_breakpoint": {"mode": "explicit"},
                }],
            },
            {"role": "user", "content": evidence},
        ],
        "max_output_tokens": _PROPOSER_MAX_OUTPUT_TOKENS,
        "reasoning": {"effort": _PROPOSER_REASONING_EFFORT},
        "text": {
            "verbosity": _PROPOSER_TEXT_VERBOSITY,
            "format": {
                "type": "json_schema",
                "name": "submission_frontier_rubric_proposal",
                "strict": True,
                "schema": _PROPOSER_OUTPUT_SCHEMA,
            },
        },
        "prompt_cache_options": {"mode": "explicit", "ttl": "30m"},
        "prompt_cache_key": "rubric-proposer-" + sha256_text(instructions)[:40],
        "truncation": "disabled",
        "store": False,
    }
    if service_tier is not None:
        arguments["service_tier"] = service_tier
    response = OpenAI(
        api_key=api_key,
        timeout=_DIRECT_REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    ).responses.create(**arguments)
    status = getattr(response, "status", None)
    if status == "incomplete":
        details = getattr(response, "incomplete_details", None)
        reason = getattr(details, "reason", None) or "unknown"
        raise RuntimeError(f"OpenAI returned an incomplete rubric response: {reason}")
    if status not in {None, "completed"}:
        raise RuntimeError(f"OpenAI rubric response failed with status {status}")
    text = response.output_text or ""
    if not text:
        raise RuntimeError("OpenAI returned an empty rubric response")
    usage = _jsonable(getattr(response, "usage", None))
    request_parameters = {
        key: value for key, value in arguments.items()
        if key not in {"input", "model"}
    }
    generation = {
        "provider": "openai",
        "requested_model": model,
        "effective_model": str(getattr(response, "model", model)),
        "response_id": getattr(response, "id", None),
        "request_parameters": request_parameters,
        "usage": usage,
    }
    return ProposerOutput(
        proposal_text=text,
        cost=_cost_from_usage(usage, model=model, service_tier=service_tier),
        generation=generation,
    )


def _cost_from_usage(
    usage: object,
    *,
    model: str,
    service_tier: str | None,
) -> dict[str, float | str | None]:
    if not isinstance(usage, dict):
        return RunCost().fields()
    input_tokens = usage.get("input_tokens", usage.get("prompt_tokens"))
    output_tokens = usage.get("output_tokens", usage.get("completion_tokens"))
    details = usage.get("input_tokens_details")
    cached_tokens = details.get("cached_tokens") if isinstance(details, dict) else 0
    event = {
        "usage": {
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "cached_input_tokens": cached_tokens or 0,
        }
    }
    return RunCost.from_event(
        event,
        model=model,
        service_tier=service_tier,
    ).fields()


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(child) for key, child in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(child) for child in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _jsonable(model_dump())
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _jsonable(to_dict())
    return str(value)


def _validate_proposer_output(output: ProposerOutput) -> None:
    if set(output.cost) != _COST_KEYS:
        raise ValueError("rubric proposer returned invalid cost metadata")
    if not isinstance(output.generation, dict) or not output.generation:
        raise ValueError("rubric proposer returned invalid generation metadata")


def _valid_proposer_attempts(value: object, expected_count: int) -> bool:
    if not isinstance(value, list) or len(value) != expected_count:
        return False
    for attempt in value:
        if not isinstance(attempt, dict) or set(attempt) != {"cost", "generation"}:
            return False
        if not isinstance(attempt["cost"], dict) or set(attempt["cost"]) != _COST_KEYS:
            return False
        if not isinstance(attempt["generation"], dict) or not attempt["generation"]:
            return False
    return True


def _repair_context(
    identity: dict[str, object],
    *,
    rejected_field: str,
) -> tuple[str | None, str | None]:
    repair_error = identity.get("repair_error")
    rejected = identity.get(rejected_field)
    if repair_error is None and rejected is None:
        return None, None
    if (
        type(repair_error) is not str
        or not repair_error
        or type(rejected) is not str
        or not rejected
    ):
        raise ValueError("invalid rubric-generation repair provenance")
    return repair_error, rejected


def _proposer_repair_context(
    identity: dict[str, object],
) -> tuple[str | None, tuple[dict[str, str], ...]]:
    repair_error = identity.get("repair_error")
    rejected = identity.get("rejected_attempts")
    if repair_error is None and rejected == []:
        return None, ()
    if (
        type(repair_error) is not str
        or not repair_error
        or not isinstance(rejected, list)
        or not rejected
        or any(
            not isinstance(attempt, dict)
            or set(attempt) != {"validation_error", "structured_proposal"}
            or type(attempt.get("validation_error")) is not str
            or not attempt["validation_error"]
            or type(attempt.get("structured_proposal")) is not str
            or not attempt["structured_proposal"]
            for attempt in rejected
        )
        or rejected[-1]["validation_error"] != repair_error
    ):
        raise ValueError("invalid rubric-proposer repair provenance")
    return repair_error, tuple(dict(attempt) for attempt in rejected)


def _validated_evidence_packet(
    response: str,
    *,
    event_contents: dict[int, str],
    retrieved_events: frozenset[int],
    materialized: bool,
    require_finding: bool = False,
) -> str:
    if type(response) is not str or not response.strip():
        raise ValueError("trajectory auditor returned an empty evidence packet")
    if len(response) > _MAX_PACKET_CHARS * 2:
        raise ValueError("trajectory auditor returned an oversized evidence packet")
    try:
        packet = json.loads(response)
    except json.JSONDecodeError as exc:
        raise ValueError("trajectory auditor returned invalid JSON") from exc
    if not isinstance(packet, dict) or set(packet) != _PACKET_KEYS:
        raise ValueError("trajectory auditor packet has invalid fields")
    if packet.get("schema_version") != _AUDITOR_PACKET_SCHEMA_VERSION:
        raise ValueError("trajectory auditor packet has an invalid schema version")
    inspected = packet.get("inspected")
    if (
        type(inspected) is not str
        or not inspected.strip()
        or inspected != inspected.strip()
        or len(inspected) > _MAX_INSPECTION_CHARS
    ):
        raise ValueError("trajectory auditor packet has an invalid inspection statement")
    findings = packet.get("findings")
    if (
        not isinstance(findings, list)
        or len(findings) > 8
        or require_finding
        and not findings
    ):
        raise ValueError("trajectory auditor packet has invalid findings")
    snippets: list[dict[str, object]] = []
    finding_ids: list[str] = []
    for finding in findings:
        if not isinstance(finding, dict) or set(finding) != _FINDING_KEYS:
            raise ValueError("trajectory auditor packet has an invalid finding")
        finding_id = finding.get("finding_id")
        kind = finding.get("kind")
        evidence = finding.get("evidence")
        counterevidence = finding.get("counterevidence")
        if (
            type(finding_id) is not str
            or kind not in {"supported_problem", "potential_concern"}
            or not isinstance(evidence, list)
            or len(evidence) > 4
            or not isinstance(counterevidence, list)
            or len(counterevidence) > 4
            or kind == "supported_problem"
            and not evidence
        ):
            raise ValueError("trajectory auditor packet has an invalid finding")
        for key, maximum in (
            ("hypothesis", _MAX_PROBLEM_CHARS),
            ("basis", _MAX_PROBLEM_CHARS),
            ("uncertainty", _MAX_UNCERTAINTY_CHARS),
            ("verification_question", _MAX_PROBLEM_CHARS),
        ):
            value = finding.get(key)
            if (
                type(value) is not str
                or not value.strip()
                or value != value.strip()
                or len(value) > maximum
            ):
                raise ValueError("trajectory auditor packet has an invalid finding")
        finding_ids.append(finding_id)
        snippets.extend(evidence)
        snippets.extend(counterevidence)
    if finding_ids != [f"F{index}" for index in range(1, len(findings) + 1)]:
        raise ValueError("trajectory auditor finding IDs must be sequential from F1")
    if len(snippets) > _MAX_PACKET_SNIPPETS:
        raise ValueError("trajectory auditor packet contains too many snippets")
    seen: set[tuple[int, int, int]] = set()
    total_chars = 0
    for snippet in snippets:
        expected_keys = _VERIFIED_SNIPPET_KEYS if materialized else _SNIPPET_KEYS
        if not isinstance(snippet, dict) or set(snippet) != expected_keys:
            raise ValueError("trajectory auditor packet has an invalid snippet")
        event_id = snippet.get("event_id")
        start = snippet.get("start_offset")
        end = snippet.get("end_offset")
        if type(event_id) is not int or event_id not in event_contents:
            raise ValueError("trajectory auditor citation has an unknown event ID")
        if event_id not in retrieved_events:
            raise ValueError("trajectory auditor cited an event it did not retrieve")
        if (
            type(start) is not int
            or type(end) is not int
            or not 0 <= start < end <= len(event_contents[event_id])
        ):
            raise ValueError("trajectory auditor citation has invalid offsets")
        if end - start > _MAX_SNIPPET_CHARS:
            raise ValueError("trajectory auditor citation exceeds the size limit")
        exact_text = event_contents[event_id][start:end]
        if materialized:
            if snippet.get("text") != exact_text:
                raise ValueError("verified auditor packet text was modified")
        else:
            snippet["text"] = exact_text
        key = (event_id, start, end)
        if key in seen:
            raise ValueError("trajectory auditor packet repeats a snippet")
        seen.add(key)
        total_chars += len(exact_text)
    if total_chars > _MAX_PACKET_CHARS:
        raise ValueError("trajectory auditor packet snippets exceed the size limit")
    canonical = json.dumps(
        packet,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    if len(canonical) > _MAX_PACKET_CHARS:
        raise ValueError("trajectory auditor packet exceeds the size limit")
    return canonical


def _validated_structured_proposal(
    response: str,
    *,
    current_rubric: str,
    packet_text: str,
    saturated: bool,
) -> tuple[dict[str, object], str]:
    if type(response) is not str or not response.strip():
        raise ValueError("rubric proposer returned an empty structured proposal")
    if len(response) > _MAX_RUBRIC_CHARS * 2:
        raise ValueError("rubric proposer returned an oversized structured proposal")
    try:
        proposal = json.loads(response)
        packet = json.loads(packet_text)
    except json.JSONDecodeError as exc:
        raise ValueError("rubric proposer returned invalid JSON") from exc
    if not isinstance(proposal, dict) or set(proposal) != _PROPOSAL_KEYS:
        raise ValueError("structured rubric proposal has invalid fields")
    if proposal.get("schema_version") != _PROPOSER_SCHEMA_VERSION:
        raise ValueError("structured rubric proposal has an invalid schema version")
    decision = proposal.get("decision")
    title = proposal.get("rubric_title")
    criteria = proposal.get("criteria")
    changes = proposal.get("challenge_changes")
    if (
        decision not in {"revise", "retain"}
        or type(title) is not str
        or not isinstance(criteria, list)
        or not isinstance(changes, list)
    ):
        raise ValueError("structured rubric proposal has invalid decision fields")
    if decision == "retain":
        if saturated:
            raise ValueError("a saturated score requires a challenging rubric revision")
        if title or criteria or changes:
            raise ValueError("a retained rubric proposal must omit revision content")
    else:
        if (
            not _valid_rubric_field(title)
            or not 1 <= len(criteria) <= 26
        ):
            raise ValueError("a revised rubric proposal must contain a title and criteria")
        if not 1 <= len(changes) <= 12:
            raise ValueError("a revised rubric proposal must explain challenge changes")

    criterion_titles: list[str] = []
    expected_maximum = parse_score_normalization_maximum(current_rubric) or 100
    binary_scoring = _has_binary_scoring_protocol(current_rubric)
    total_maximum = 0
    for criterion in criteria:
        if not isinstance(criterion, dict) or set(criterion) != _PROPOSAL_CRITERION_KEYS:
            raise ValueError("structured rubric proposal has an invalid criterion")
        criterion_title = criterion.get("title")
        description = criterion.get("description")
        levels = criterion.get("levels")
        if (
            type(criterion_title) is not str
            or not _valid_rubric_field(criterion_title)
            or type(description) is not str
            or not _valid_rubric_field(description)
            or not isinstance(levels, list)
        ):
            raise ValueError("structured rubric proposal has an invalid criterion")
        criterion_titles.append(criterion_title)
        labels: list[str] = []
        points: list[int] = []
        for level in levels:
            if not isinstance(level, dict) or set(level) != _PROPOSAL_LEVEL_KEYS:
                raise ValueError("structured rubric proposal has an invalid level")
            label = level.get("label")
            point = level.get("points")
            level_description = level.get("description")
            if (
                type(label) is not str
                or type(point) is not int
                or type(level_description) is not str
                or not _valid_rubric_field(level_description)
            ):
                raise ValueError("structured rubric proposal has an invalid level")
            labels.append(label)
            points.append(point)
        expected_labels = [chr(ord("A") + index) for index in range(len(labels))]
        if (
            labels != (["A", "B"] if binary_scoring else expected_labels)
            or not binary_scoring
            and len(labels) < 3
            or any(left <= right for left, right in zip(points, points[1:]))
            or not points
            or points[0] <= 0
            or points.count(0) != 1
        ):
            raise ValueError("structured rubric proposal has invalid level progression")
        total_maximum += points[0]
    normalized_titles = [" ".join(value.lower().split()) for value in criterion_titles]
    if len(set(normalized_titles)) != len(normalized_titles):
        raise ValueError("structured rubric proposal has duplicate criterion titles")
    if decision == "revise" and total_maximum != expected_maximum:
        raise ValueError(
            f"structured rubric A-level points must sum to {expected_maximum}"
        )

    packet_findings = packet.get("findings") if isinstance(packet, dict) else None
    valid_finding_ids = {
        finding.get("finding_id")
        for finding in packet_findings
        if isinstance(finding, dict) and type(finding.get("finding_id")) is str
    } if isinstance(packet_findings, list) else set()
    for change in changes:
        if not isinstance(change, dict) or set(change) != _CHALLENGE_CHANGE_KEYS:
            raise ValueError("structured rubric proposal has an invalid challenge change")
        finding_ids = change.get("finding_ids")
        if (
            change.get("criterion_title") not in criterion_titles
            or not isinstance(finding_ids, list)
            or not finding_ids
            or any(type(value) is not str or value not in valid_finding_ids for value in finding_ids)
        ):
            raise ValueError("challenge change does not cite valid frontier findings")
        for key in (
            "stable_quality_dimension",
            "current_evidence_gap",
            "future_submission_test",
        ):
            value = change.get(key)
            if type(value) is not str or not value.strip() or value != value.strip():
                raise ValueError("structured rubric proposal has an invalid challenge change")
    canonical = json.dumps(
        proposal,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ) + "\n"
    return proposal, canonical


def _valid_rubric_field(value: str) -> bool:
    return bool(
        value.strip()
        and value == value.strip()
        and "\n" not in value
        and "\r" not in value
        and "\x00" not in value
    )


def _proposal_rubric_text(
    proposal: dict[str, object],
    *,
    current_rubric: str,
) -> str:
    if proposal["decision"] == "retain":
        return current_rubric
    title = proposal["rubric_title"]
    criteria = proposal["criteria"]
    assert isinstance(title, str) and isinstance(criteria, list)
    maximum = parse_score_normalization_maximum(current_rubric) or 100
    lines = [f"RUBRIC: {title}", ""]
    scoring_protocol = _scoring_protocol(current_rubric)
    if scoring_protocol is not None:
        lines.append(f"Scoring protocol: {scoring_protocol}")
    if parse_score_normalization_maximum(current_rubric) is not None:
        lines.append(f"Score normalization maximum: {maximum}")
    if len(lines) > 2:
        lines.append("")
    lines.extend((f"Total Points: {maximum}", ""))
    for index, criterion in enumerate(criteria, start=1):
        assert isinstance(criterion, dict)
        levels = criterion["levels"]
        assert isinstance(levels, list)
        lines.extend((
            f"Criterion {index}: {criterion['title']}",
            "",
            f"Description: {criterion['description']}",
            "",
            "Levels: " + " ".join(
                f"{level['label']}={level['points']}"
                for level in levels
                if isinstance(level, dict)
            ),
        ))
        for level in levels:
            assert isinstance(level, dict)
            lines.append(f"[{level['label']}]: {level['description']}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


_CROSS_SCORE_KEYS = frozenset({
    "parent_score",
    "candidate_score",
    "raw_score",
    "selected_levels",
    "criterion_scores",
    "rubric_sha256",
    "attempt_id",
})


def _validate_candidate_cross_score(
    value: dict[str, object] | None,
    *,
    score_context: RubricScoreContext,
    changed: bool,
) -> None:
    if not _valid_candidate_cross_score_shape(
        value,
        score_context=score_context,
        changed=changed,
    ):
        raise ValueError("candidate rubric returned an invalid crossed score")
    if score_context.saturated and not _candidate_cross_score_moves_frontier(
        value,
        score_context=score_context,
        changed=changed,
    ):
        if isinstance(value, dict):
            selected_levels = value["selected_levels"]
            assert isinstance(selected_levels, dict)
            top_level_count = sum(
                level == "A" for level in selected_levels.values()
            )
            detail = (
                f"parent score {score_context.score}, candidate score "
                f"{value['candidate_score']}, and {top_level_count}/"
                f"{len(selected_levels)} criteria selected level A"
            )
        else:
            detail = "no changed candidate rubric was crossed"
        raise ValueError(f"{_FRONTIER_GATE_ERROR_PREFIX}: {detail}")


def _valid_candidate_cross_score(
    value: object,
    *,
    score_context: RubricScoreContext,
    changed: bool,
) -> bool:
    return bool(
        _valid_candidate_cross_score_shape(
            value,
            score_context=score_context,
            changed=changed,
        )
        and (
            not score_context.saturated
            or _candidate_cross_score_moves_frontier(
                value,
                score_context=score_context,
                changed=changed,
            )
        )
    )


def _valid_candidate_cross_score_shape(
    value: object,
    *,
    score_context: RubricScoreContext,
    changed: bool,
) -> bool:
    if value is None:
        return not changed
    return bool(
        isinstance(value, dict)
        and set(value) == _CROSS_SCORE_KEYS
        and value.get("parent_score") == score_context.score
        and type(value.get("candidate_score")) is int
        and 0 <= value["candidate_score"] <= 100
        and type(value.get("raw_score")) is int
        and isinstance(value.get("selected_levels"), dict)
        and value["selected_levels"]
        and all(
            type(key) is str and type(level) is str and level
            for key, level in value["selected_levels"].items()
        )
        and isinstance(value.get("criterion_scores"), dict)
        and set(value["criterion_scores"]) == set(value["selected_levels"])
        and all(type(score) is int for score in value["criterion_scores"].values())
        and value["raw_score"] == sum(value["criterion_scores"].values())
        and type(value.get("rubric_sha256")) is str
        and len(value["rubric_sha256"]) == 64
        and all(character in "0123456789abcdef" for character in value["rubric_sha256"])
        and type(value.get("attempt_id")) is str
        and len(value["attempt_id"]) == 32
        and all(character in "0123456789abcdef" for character in value["attempt_id"])
    )


def _candidate_cross_score_moves_frontier(
    value: object,
    *,
    score_context: RubricScoreContext,
    changed: bool,
) -> bool:
    return bool(
        isinstance(value, dict)
        and changed
        and value["candidate_score"] < score_context.score
        and not all(level == "A" for level in value["selected_levels"].values())
    )


def _link_or_copy(source: Path, destination: Path) -> None:
    try:
        os.link(source, destination)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        shutil.copyfile(source, destination)


def _normalize_rubric_text(value: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError("rubric proposer returned an empty complete rubric")
    if len(value) > _MAX_RUBRIC_CHARS:
        raise ValueError("rubric proposer returned an oversized complete rubric")
    if "```" in value:
        raise ValueError("complete rubric must not contain Markdown code fences")
    lines = [line.rstrip() for line in value.strip().splitlines()]
    return "\n".join(lines) + "\n"


def _validated_complete_rubric(
    response: str,
    *,
    current_rubric: str,
) -> str:
    text = _normalize_rubric_text(response)
    levels_by_criterion = parse_rubric_levels_strict(text)
    criterion_keys = list(levels_by_criterion)
    expected_keys = [
        f"criterion_{index}" for index in range(1, len(criterion_keys) + 1)
    ]
    if criterion_keys != expected_keys:
        raise ValueError("complete rubric criterion numbers must be contiguous from 1")

    headers = list(_CRITERION_HEADER.finditer(text))
    titles = _CRITERION_TITLE.findall(text)
    if len(titles) != len(headers):
        raise ValueError("every complete rubric criterion must have a nonempty title")
    normalized_titles = [" ".join(title.lower().split()) for title in titles]
    if len(set(normalized_titles)) != len(normalized_titles):
        raise ValueError("complete rubric contains duplicate criterion titles")

    scoring_protocol = _scoring_protocol(current_rubric)
    binary_scoring = scoring_protocol is not None
    total_maximum = 0
    for index, (criterion_key, levels) in enumerate(levels_by_criterion.items()):
        labels = list(levels)
        expected_labels = [chr(ord("A") + offset) for offset in range(len(labels))]
        valid_labels = (
            labels == ["A", "B"]
            if binary_scoring
            else len(labels) >= 3 and labels == expected_labels
        )
        if not valid_labels:
            raise ValueError(
                f"{criterion_key} level labels must be "
                + ("exactly A and B" if binary_scoring else (
                    "contiguous from A with at least three levels"
                ))
            )
        points = list(levels.values())
        if any(left <= right for left, right in zip(points, points[1:])):
            raise ValueError(f"{criterion_key} level points must strictly descend")
        if points[0] <= 0:
            raise ValueError(f"{criterion_key} A-level points must be positive")
        if points.count(0) != 1:
            raise ValueError(f"{criterion_key} must contain exactly one zero level")
        total_maximum += points[0]

        body_end = headers[index + 1].start() if index + 1 < len(headers) else len(text)
        body = text[headers[index].end() : body_end]
        descriptions = _LEVEL_DESCRIPTION.findall(body)
        if descriptions != labels:
            raise ValueError(
                f"{criterion_key} must contain one nonempty description for each level"
            )

    normalization_maximum = parse_score_normalization_maximum(current_rubric)
    expected_maximum = normalization_maximum or 100
    if parse_score_normalization_maximum(text) != normalization_maximum:
        raise ValueError(
            "complete rubric must preserve the exact directive "
            f"`Score normalization maximum: {normalization_maximum}`"
        )
    if _scoring_protocol(text) != scoring_protocol:
        raise ValueError("complete rubric changed its scoring protocol")
    if total_maximum != expected_maximum:
        raise ValueError(
            "complete rubric A-level points must sum to "
            f"{expected_maximum}"
        )

    if text == _normalize_rubric_text(current_rubric):
        return current_rubric
    return text


def _scoring_protocol(text: str) -> str | None:
    prefix = "Scoring protocol: "
    values = [line.removeprefix(prefix) for line in text.splitlines() if line.startswith(prefix)]
    if not values:
        return None
    if len(values) != 1 or not values[0] or values[0] != values[0].strip():
        raise ValueError("rubric has an invalid scoring protocol directive")
    return values[0]


def _has_binary_scoring_protocol(text: str) -> bool:
    return _scoring_protocol(text) is not None


def _rubric_diff(
    previous: str,
    revised: str,
    *,
    previous_version: int,
    next_version: int,
) -> str:
    return "".join(
        difflib.unified_diff(
            previous.splitlines(keepends=True),
            revised.splitlines(keepends=True),
            fromfile=f"r{previous_version:04d}.txt",
            tofile=f"r{next_version:04d}.txt",
        )
    )
