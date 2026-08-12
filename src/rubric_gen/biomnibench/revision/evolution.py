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

from rubric_gen.biomnibench.agent.costs import RunCost
from rubric_gen.biomnibench.agent.models import AgentRunConfig, RunPaths
from rubric_gen.biomnibench.agent.runners import AgentRunner
from rubric_gen.biomnibench.forensics.evidence_index import (
    build_evidence_index,
    indexable_event_contents,
    write_query_tool,
)
from rubric_gen.biomnibench.judging.scoring import parse_rubric_levels_strict
from rubric_gen.biomnibench.revision.artifacts import make_read_only
from rubric_gen.biomnibench.utils.hashing import sha256_text
from rubric_gen.biomnibench.utils.serialization import write_json_atomic


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
    rubric_text: str
    cost: dict[str, float | str | None]
    generation: dict[str, object]


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
_MAX_PROBLEMS = 4
_MAX_PROBLEM_CHARS = 1_000
_MAX_INSPECTION_CHARS = 1_000
_MAX_UNCERTAINTY_CHARS = 1_000
_PROPOSER_MAX_OUTPUT_TOKENS = 32_768
_DIRECT_REQUEST_TIMEOUT_SECONDS = 600.0
_AUDITOR_PROMPT_VERSION = "trajectory-evidence-auditor-v1"
_AUDITOR_PACKET_SCHEMA_VERSION = 1
_PROPOSER_PROMPT_VERSION = "audited-complete-rubric-v1"
_PROPOSER_REASONING_EFFORT = "high"
_PROPOSER_TEXT_VERBOSITY = "low"
_METADATA_KEYS = frozenset({
    "schema_version",
    "kind",
    "version",
    "mode",
    "source_submission_id",
    "source_answer_sha256",
    "source_trajectory_sha256",
    "auditor",
    "auditor_packet_sha256",
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
    "event_id", "start_offset", "end_offset", "text",
})
_PACKET_KEYS = frozenset({
    "schema_version",
    "status",
    "inspected",
    "problems",
    "counterevidence",
    "uncertainty",
})
_PROBLEM_KEYS = frozenset({"hypothesis", "evidence"})

_AUDITOR_OUTPUT_SCHEMA: dict[str, object] = {
    "type": "object",
    "properties": {
        "schema_version": {"type": "integer", "enum": [1]},
        "status": {
            "type": "string",
            "enum": ["no_supported_problem", "supported_problem"],
        },
        "inspected": {"type": "string", "maxLength": _MAX_INSPECTION_CHARS},
        "problems": {
            "type": "array",
            "maxItems": _MAX_PROBLEMS,
            "items": {
                "type": "object",
                "properties": {
                    "hypothesis": {
                        "type": "string",
                        "maxLength": _MAX_PROBLEM_CHARS,
                    },
                    "evidence": {
                        "type": "array",
                        "maxItems": 4,
                        "items": {"$ref": "#/$defs/snippet"},
                    },
                },
                "required": ["hypothesis", "evidence"],
                "additionalProperties": False,
            },
        },
        "counterevidence": {
            "type": "array",
            "maxItems": 8,
            "items": {"$ref": "#/$defs/snippet"},
        },
        "uncertainty": {
            "type": ["string", "null"],
            "maxLength": _MAX_UNCERTAINTY_CHARS,
        },
    },
    "required": [
        "schema_version",
        "status",
        "inspected",
        "problems",
        "counterevidence",
        "uncertainty",
    ],
    "additionalProperties": False,
    "$defs": {
        "snippet": {
            "type": "object",
            "properties": {
                "event_id": {"type": "integer", "minimum": 1},
                "start_offset": {"type": "integer", "minimum": 0},
                "end_offset": {"type": "integer", "minimum": 1},
                "text": {"type": "string", "maxLength": _MAX_SNIPPET_CHARS},
            },
            "required": ["event_id", "start_offset", "end_offset", "text"],
            "additionalProperties": False,
        }
    },
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
        answer: str,
        trajectory_path: Path,
        version: int,
        source_submission_id: str,
        output_dir: Path,
    ) -> EvolvedRubric:
        output_dir.mkdir(parents=True, exist_ok=True)
        rubric_path = output_dir / f"r{version:04d}.txt"
        metadata_path = output_dir / f"r{version:04d}.proposer.json"
        packet_path = output_dir / f"r{version:04d}.auditor.json"
        diff_path = output_dir / f"r{version:04d}.diff"
        event_contents = indexable_event_contents(trajectory_path)
        source_hashes = {
            "source_answer_sha256": sha256_text(answer),
            "source_trajectory_sha256": sha256_text(
                trajectory_path.read_text(encoding="utf-8", errors="replace")
            ),
        }
        result_paths = (rubric_path, metadata_path, packet_path, diff_path)
        if any(path.exists() for path in result_paths):
            return self._load_existing(
                rubric_path,
                metadata_path,
                packet_path,
                diff_path,
                version,
                source_submission_id,
                current_rubric,
                event_contents,
                source_hashes,
            )

        auditor_output = self.run_auditor(trajectory_path=trajectory_path)
        self._validate_auditor_output(auditor_output, event_contents)
        packet_text = _validated_evidence_packet(
            auditor_output.packet_text,
            event_contents=event_contents,
            retrieved_events=frozenset(auditor_output.retrieved_event_ids),
        )
        packet_sha256 = sha256_text(packet_text)

        last_error: Exception | None = None
        text = ""
        proposer_output: ProposerOutput | None = None
        proposer_attempts: list[dict[str, object]] = []
        attempt = 0
        for attempt in range(1, self.max_retries + 2):
            proposer_output = None
            attempt_recorded = False
            try:
                proposer_output = self.run_proposer(
                    instruction=instruction,
                    current_rubric=current_rubric,
                    answer=answer,
                    auditor_packet=packet_text,
                    repair_error=str(last_error) if last_error else None,
                )
                _validate_proposer_output(proposer_output)
                proposer_attempts.append({
                    "cost": dict(proposer_output.cost),
                    "generation": dict(proposer_output.generation),
                })
                attempt_recorded = True
                text = _validated_complete_rubric(
                    proposer_output.rubric_text,
                    current_rubric=current_rubric,
                )
                break
            except Exception as exc:
                if proposer_output is not None:
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
        diff_path.write_text(rubric_diff, encoding="utf-8")
        metadata: dict[str, object] = {
            "schema_version": 3,
            "kind": "audited-complete-rubric-generation",
            "version": version,
            "mode": RubricEvolution.PROSPECTIVE.value,
            "source_submission_id": source_submission_id,
            **source_hashes,
            "auditor": self._auditor_identity(
                auditor_output,
                available_events=len(event_contents),
            ),
            "auditor_packet_sha256": packet_sha256,
            "proposer": self._proposer_identity(),
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
    ) -> dict[str, object]:
        task_prompt = _auditor_prompt(
            query_tool=Path("data/trajectory_query.py"),
            query_limit=self.query_limit,
            available_events=available_events,
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
            "packet_schema_version": _AUDITOR_PACKET_SCHEMA_VERSION,
            "query_limit": self.query_limit,
            "query_count": output.query_count,
            "retrieved_event_ids": list(output.retrieved_event_ids),
            "cost": dict(output.cost),
        }

    def _proposer_identity(self) -> dict[str, object]:
        return {
            "provider": "vllm" if self.proposer_base_url is not None else "openai",
            "model": self.proposer_model,
            "base_url": (
                self.proposer_base_url.rstrip("/") + "/"
                if self.proposer_base_url is not None else None
            ),
            "prompt_version": _PROPOSER_PROMPT_VERSION,
            "prompt_sha256": sha256_text(
                _proposer_instructions(repair_error=None)
            ),
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
        (failure_dir / f"{stem}.txt").write_text(
            proposer_output.rubric_text,
            encoding="utf-8",
        )
        write_json_atomic(
            failure_dir / f"{stem}.json",
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

    def _load_existing(
        self,
        rubric_path: Path,
        metadata_path: Path,
        packet_path: Path,
        diff_path: Path,
        version: int,
        source_submission_id: str,
        current_rubric: str,
        event_contents: dict[int, str],
        source_hashes: dict[str, str],
    ) -> EvolvedRubric:
        if not all(path.is_file() for path in (
            rubric_path, metadata_path, packet_path, diff_path
        )):
            raise RuntimeError(f"incomplete evolved rubric version r{version:04d}")
        try:
            text = rubric_path.read_text(encoding="utf-8")
            stored = json.loads(metadata_path.read_text(encoding="utf-8"))
            packet_text = packet_path.read_text(encoding="utf-8")
            rubric_diff = diff_path.read_text(encoding="utf-8")
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
                )
                expected_packet = _validated_evidence_packet(
                    packet_text,
                    event_contents=event_contents,
                    retrieved_events=frozenset(output.retrieved_event_ids),
                )
            except (KeyError, TypeError, ValueError):
                expected_packet = None
        else:
            expected_packet = None
        if (
            not isinstance(stored, dict)
            or set(stored) != _METADATA_KEYS
            or stored.get("schema_version") != 3
            or stored.get("kind") != "audited-complete-rubric-generation"
            or stored.get("version") != version
            or stored.get("mode") != RubricEvolution.PROSPECTIVE.value
            or stored.get("source_submission_id") != source_submission_id
            or any(stored.get(key) != value for key, value in source_hashes.items())
            or stored.get("auditor") != expected_auditor_identity
            or expected_packet != packet_text
            or stored.get("auditor_packet_sha256") != sha256_text(packet_text)
            or stored.get("proposer") != self._proposer_identity()
            or type(stored.get("attempt_count")) is not int
            or stored["attempt_count"] < 1
            or not _valid_proposer_attempts(
                stored.get("proposer_attempts"), stored["attempt_count"]
            )
            or stored.get("rubric_sha256") != sha256_text(text)
            or stored.get("parent_rubric_sha256") != sha256_text(current_rubric)
            or stored.get("rubric_changed") is not changed
            or stored.get("rubric_diff_sha256") != sha256_text(rubric_diff)
            or rubric_diff != expected_diff
            or stored.get("parent_criterion_count") != parent_criterion_count
            or stored.get("criterion_count") != criterion_count
            or stored.get("available_trajectory_events") != len(event_contents)
            or expected_text != text
        ):
            raise RuntimeError(f"invalid evolved rubric version r{version:04d}")
        return EvolvedRubric(text, sha256_text(text), changed, stored)

    def _run_trajectory_auditor(
        self,
        *,
        trajectory_path: Path,
    ) -> AuditorOutput:
        temporary = Path(tempfile.mkdtemp(prefix="biomnibench-trajectory-auditor-"))
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
            counter = query_state / "query-count.txt"
            audit = query_state / "query-audit.jsonl"
            if not counter.is_file() or not audit.is_file():
                raise RuntimeError("trajectory auditor query audit is missing")
            query_count = int(counter.read_text())
            audit_records = [
                json.loads(line)
                for line in audit.read_text(encoding="utf-8").splitlines()
            ]
            if len(audit_records) != query_count:
                raise RuntimeError(
                    "trajectory auditor query audit disagrees with query count"
                )
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
        answer: str,
        auditor_packet: str,
        repair_error: str | None,
    ) -> ProposerOutput:
        instructions = _proposer_instructions(repair_error=repair_error)
        evidence = _proposer_evidence(
            instruction=instruction,
            current_rubric=current_rubric,
            answer=answer,
            auditor_packet=auditor_packet,
        )
        return _generate_complete_rubric(
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
) -> str:
    return f"""Prompt contract: {_AUDITOR_PROMPT_VERSION}

Audit the raw trajectory for supported problems in the work and for evidence
that weakens or contradicts those problem hypotheses. You select evidence; you
do not design the rubric.

The trajectory is available only through at most {query_limit} bounded calls:
`{query_tool} inventory`
`{query_tool} timeline --start EVENT --limit COUNT`
`{query_tool} search QUERY --limit COUNT`
`{query_tool} show EVENT_ID --start OFFSET --limit CHARS`

The index contains {available_events} distinct events. Inspect at least one
event. Do not read the SQLite database directly. Treat the trajectory as an
audit record, not a list of accomplishments. Look for concrete failures,
contradictions, unsupported decisions, missing checks that invalidate an
outcome, and evidence that the work is valid despite an apparent concern.

Do not force a problem. Use `no_supported_problem` when the inspected evidence
does not support one. A longer or busier trajectory is not evidence of better or
worse quality. Do not infer facts that are absent from the retrieved text.

Return one JSON object with this exact structure:
- `schema_version`: 1.
- `status`: `no_supported_problem` or `supported_problem`.
- `inspected`: a short factual statement of what parts or issue types you
  inspected.
- `problems`: zero or more objects with a short `hypothesis` and one or more
  exact `evidence` snippets. It must be empty for `no_supported_problem`.
- `counterevidence`: zero or more exact snippets that weaken a problem
  hypothesis or support uncertainty.
- `uncertainty`: a short statement or null.

Every snippet must contain `event_id`, zero-based `start_offset`, exclusive
`end_offset`, and `text`. The text must be the exact character slice returned
for that event, including whitespace and punctuation. Use `show` with a known
offset to obtain exact text. Keep each snippet at most {_MAX_SNIPPET_CHARS}
characters and all snippets together at most {_MAX_PACKET_CHARS} characters.

Never propose criterion wording, weights, edits, penalties, or rubric strategy.
You have not received and must not seek judge reasoning, reward-hacking detector
results, the current rubric, or other evaluation output. Return only the JSON
packet.
"""


def _proposer_instructions(*, repair_error: str | None) -> str:
    repair = (
        "\nThe previous complete rubric failed structural validation: "
        + repair_error
        if repair_error else ""
    )
    return f"""Prompt contract: {_PROPOSER_PROMPT_VERSION}

Act as an independent designer of the complete optimizer rubric for the next
revision of a scientific task.

Produce the full next rubric, not an edit, patch, action list, JSON object, or
explanation. The current rubric is a starting point rather than an immutable
template. You may retain, rewrite, remove, merge, split, reorder, or reweight any
criterion. The current submission has already been scored, so the new rubric
applies only to the next submission.

The trajectory auditor is separate from you. Its packet contains only
harness-verified verbatim trajectory slices and its bounded hypotheses,
counterevidence, uncertainty, and inspection statement. Do not infer additional
trajectory facts. You do not have tools, judge reasoning, or reward-hacking
detector results. Never add a criterion merely because the auditor searched for
an issue. `no_supported_problem` is valid evidence for leaving the complete
rubric unchanged.

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
- Use the current answer and verified packet as evidence about rubric weakness,
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
sections. Each criterion must have three or more contiguous level labels
starting at A, strictly descending integer points, exactly one zero-valued
level, and one nonempty `[LABEL]:` description per level. The sum of all A-level
points must equal 100. Criteria may include negative lower levels.

If no supported revision improves the complete set, reproduce the current
rubric unchanged. An unchanged complete rubric is the only abstention mechanism.
Return only the complete rubric as plain text. Do not use JSON, XML, commentary,
or Markdown code fences.{repair}
"""


def _proposer_evidence(
    *,
    instruction: str,
    current_rubric: str,
    answer: str,
    auditor_packet: str,
) -> str:
    return f"""<task_instruction>
{instruction}
</task_instruction>
<current_answer>
{answer}
</current_answer>
<current_complete_rubric>
{current_rubric}
</current_complete_rubric>
<verified_auditor_packet>
{auditor_packet}</verified_auditor_packet>
"""


def _generate_complete_rubric(
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
            },
            "usage": usage,
        }
        return ProposerOutput(
            rubric_text=text,
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
        "text": {"verbosity": _PROPOSER_TEXT_VERBOSITY},
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
        rubric_text=text,
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


def _validated_evidence_packet(
    response: str,
    *,
    event_contents: dict[int, str],
    retrieved_events: frozenset[int],
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
    status = packet.get("status")
    if status not in {"no_supported_problem", "supported_problem"}:
        raise ValueError("trajectory auditor packet has an invalid status")
    inspected = packet.get("inspected")
    if (
        type(inspected) is not str
        or not inspected.strip()
        or inspected != inspected.strip()
        or len(inspected) > _MAX_INSPECTION_CHARS
    ):
        raise ValueError("trajectory auditor packet has an invalid inspection statement")
    uncertainty = packet.get("uncertainty")
    if uncertainty is not None and (
        type(uncertainty) is not str
        or not uncertainty.strip()
        or uncertainty != uncertainty.strip()
        or len(uncertainty) > _MAX_UNCERTAINTY_CHARS
    ):
        raise ValueError("trajectory auditor packet has invalid uncertainty")
    problems = packet.get("problems")
    counterevidence = packet.get("counterevidence")
    if (
        not isinstance(problems, list)
        or len(problems) > _MAX_PROBLEMS
        or not isinstance(counterevidence, list)
        or len(counterevidence) > 8
    ):
        raise ValueError("trajectory auditor packet has invalid evidence lists")
    if (status == "no_supported_problem") != (not problems):
        raise ValueError("trajectory auditor status disagrees with its problems")

    snippets: list[dict[str, object]] = []
    for problem in problems:
        if not isinstance(problem, dict) or set(problem) != _PROBLEM_KEYS:
            raise ValueError("trajectory auditor packet has an invalid problem")
        hypothesis = problem.get("hypothesis")
        evidence = problem.get("evidence")
        if (
            type(hypothesis) is not str
            or not hypothesis.strip()
            or hypothesis != hypothesis.strip()
            or len(hypothesis) > _MAX_PROBLEM_CHARS
            or not isinstance(evidence, list)
            or not 1 <= len(evidence) <= 4
        ):
            raise ValueError("trajectory auditor packet has an invalid problem")
        snippets.extend(evidence)
    snippets.extend(counterevidence)
    if len(snippets) > _MAX_PACKET_SNIPPETS:
        raise ValueError("trajectory auditor packet contains too many snippets")
    seen: set[tuple[int, int, int]] = set()
    total_chars = 0
    for snippet in snippets:
        if not isinstance(snippet, dict) or set(snippet) != _SNIPPET_KEYS:
            raise ValueError("trajectory auditor packet has an invalid snippet")
        event_id = snippet.get("event_id")
        start = snippet.get("start_offset")
        end = snippet.get("end_offset")
        text = snippet.get("text")
        if (
            type(event_id) is not int
            or event_id not in event_contents
            or event_id not in retrieved_events
            or type(start) is not int
            or type(end) is not int
            or type(text) is not str
            or not 0 <= start < end <= len(event_contents[event_id])
            or end - start > _MAX_SNIPPET_CHARS
            or text != event_contents[event_id][start:end]
        ):
            raise ValueError(
                "trajectory auditor snippet is not a verbatim event slice"
            )
        key = (event_id, start, end)
        if key in seen:
            raise ValueError("trajectory auditor packet repeats a snippet")
        seen.add(key)
        total_chars += len(text)
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

    total_maximum = 0
    for index, (criterion_key, levels) in enumerate(levels_by_criterion.items()):
        labels = list(levels)
        expected_labels = [chr(ord("A") + offset) for offset in range(len(labels))]
        if len(labels) < 3 or labels != expected_labels:
            raise ValueError(
                f"{criterion_key} level labels must be contiguous from A with at "
                "least three levels"
            )
        points = list(levels.values())
        if any(left <= right for left, right in zip(points, points[1:])):
            raise ValueError(f"{criterion_key} level points must strictly descend")
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

    if total_maximum != 100:
        raise ValueError("complete rubric A-level points must sum to 100")

    if text == _normalize_rubric_text(current_rubric):
        return current_rubric
    return text


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
