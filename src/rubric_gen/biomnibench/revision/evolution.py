"""Complete optimizer-rubric generation with bounded trajectory retrieval."""

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
from typing import Callable

from rubric_gen.biomnibench.agent.models import AgentRunConfig, RunPaths
from rubric_gen.biomnibench.agent.costs import RunCost
from rubric_gen.biomnibench.agent.runners import AgentRunner
from rubric_gen.biomnibench.forensics.evidence_index import (
    build_evidence_index,
    indexable_event_count,
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
class ProposerOutput:
    rubric_text: str
    trace: str
    query_count: int
    retrieved_event_ids: tuple[int, ...]
    cost: dict[str, float | str | None]


_EVIDENCE_REFERENCE = re.compile(r"\btrajectory:event-(\d+)\b")
_CRITERION_HEADER = re.compile(r"^[ \t]*Criterion[ \t]+(\d+)[ \t]*:", re.MULTILINE)
_CRITERION_TITLE = re.compile(
    r"^[ \t]*Criterion[ \t]+\d+[ \t]*:[ \t]*(\S.*?)[ \t]*$",
    re.MULTILINE,
)
_LEVEL_DESCRIPTION = re.compile(r"^[ \t]*\[([A-Z])\]:[ \t]*\S", re.MULTILINE)
_MAX_RUBRIC_CHARS = 100_000
_PROPOSER_PROMPT_VERSION = "complete-rubric-rrd-v1"
_METADATA_KEYS = frozenset({
    "schema_version",
    "kind",
    "version",
    "mode",
    "source_submission_id",
    "source_answer_sha256",
    "source_trace_sha256",
    "source_trajectory_sha256",
    "source_evaluation_sha256",
    "provider",
    "model",
    "prompt_version",
    "query_limit",
    "attempt_count",
    "proposer_attempt_costs",
    "trajectory_query_count",
    "proposer_trace_sha256",
    "parent_rubric_sha256",
    "rubric_sha256",
    "rubric_changed",
    "rubric_diff_sha256",
    "parent_criterion_count",
    "criterion_count",
    "available_trajectory_events",
    "retrieved_trajectory_events",
})


class RubricEvolver:
    def __init__(
        self,
        *,
        agent: AgentRunConfig,
        query_limit: int,
        max_retries: int = 2,
        run_proposer: Callable[..., ProposerOutput] | None = None,
    ) -> None:
        if agent.provider not in {"codex", "vllm"} or not agent.model:
            raise ValueError("rubric proposer must be a Codex or vLLM agent with a model")
        if type(query_limit) is not int or query_limit < 1:
            raise ValueError("rubric proposer query limit must be positive")
        if type(max_retries) is not int or max_retries < 0:
            raise ValueError("rubric proposer retries must be non-negative")
        self.agent = agent
        self.model = agent.model
        self.query_limit = query_limit
        self.max_retries = max_retries
        self.run_proposer = run_proposer or self._run_codex_proposer

    def evolve(
        self,
        *,
        instruction: str,
        current_rubric: str,
        answer: str,
        trace: str,
        trajectory_path: Path,
        evaluation: dict[str, object],
        version: int,
        source_submission_id: str,
        output_dir: Path,
    ) -> EvolvedRubric:
        output_dir.mkdir(parents=True, exist_ok=True)
        rubric_path = output_dir / f"r{version:04d}.txt"
        metadata_path = output_dir / f"r{version:04d}.proposer.json"
        trace_path = output_dir / f"r{version:04d}.proposer.trace.md"
        diff_path = output_dir / f"r{version:04d}.diff"
        available_events = indexable_event_count(trajectory_path)
        source_hashes = {
            "source_answer_sha256": sha256_text(answer),
            "source_trace_sha256": sha256_text(trace),
            "source_trajectory_sha256": sha256_text(
                trajectory_path.read_text(encoding="utf-8", errors="replace")
            ),
            "source_evaluation_sha256": sha256_text(
                json.dumps(evaluation, sort_keys=True, separators=(",", ":"))
            ),
        }
        if any(
            path.exists()
            for path in (rubric_path, metadata_path, trace_path, diff_path)
        ):
            return self._load_existing(
                rubric_path,
                metadata_path,
                trace_path,
                diff_path,
                version,
                source_submission_id,
                current_rubric,
                available_events,
                source_hashes,
            )

        last_error: Exception | None = None
        text = ""
        proposer_output: ProposerOutput | None = None
        proposer_attempt_costs: list[dict[str, float | str | None]] = []
        attempt = 0
        for attempt in range(1, self.max_retries + 2):
            proposer_output = None
            cost_recorded = False
            try:
                proposer_output = self.run_proposer(
                    instruction=instruction,
                    current_rubric=current_rubric,
                    answer=answer,
                    trace=trace,
                    trajectory_path=trajectory_path,
                    evaluation=evaluation,
                    repair_error=str(last_error) if last_error else None,
                )
                if set(proposer_output.cost) != {
                    "cost_usd", "estimated_cost_usd", "cost_source"
                }:
                    raise ValueError("rubric proposer returned invalid cost metadata")
                proposer_attempt_costs.append(dict(proposer_output.cost))
                cost_recorded = True
                if (
                    not proposer_output.trace.strip()
                    or type(proposer_output.query_count) is not int
                    or not 0 <= proposer_output.query_count <= self.query_limit
                    or not isinstance(proposer_output.retrieved_event_ids, tuple)
                    or any(
                        type(event) is not int
                        or event < 1
                        or event > available_events
                        for event in proposer_output.retrieved_event_ids
                    )
                ):
                    raise ValueError("rubric proposer returned invalid trace metadata")
                if (
                    proposer_output.query_count == 0
                    or not proposer_output.retrieved_event_ids
                ):
                    raise ValueError(
                        "rubric proposer must retrieve at least one trajectory event"
                    )
                _validate_trace_evidence(
                    proposer_output.trace,
                    available_events=available_events,
                    retrieved_events=frozenset(proposer_output.retrieved_event_ids),
                )
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
                        proposer_output,
                        exc,
                    )
                if not cost_recorded:
                    proposer_attempt_costs.append({
                        "cost_usd": None,
                        "estimated_cost_usd": None,
                        "cost_source": "unavailable_due_to_exception",
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
        diff_path.write_text(rubric_diff, encoding="utf-8")
        metadata: dict[str, object] = {
            "schema_version": 1,
            "kind": "complete-rubric-generation",
            "version": version,
            "mode": RubricEvolution.PROSPECTIVE.value,
            "source_submission_id": source_submission_id,
            **source_hashes,
            "provider": self.agent.provider,
            "model": self.model,
            "prompt_version": _PROPOSER_PROMPT_VERSION,
            "query_limit": self.query_limit,
            "attempt_count": attempt,
            "proposer_attempt_costs": proposer_attempt_costs,
            "trajectory_query_count": proposer_output.query_count,
            "proposer_trace_sha256": sha256_text(proposer_output.trace),
            "parent_rubric_sha256": parent_rubric_sha256,
            "rubric_sha256": rubric_sha256,
            "rubric_changed": changed,
            "rubric_diff_sha256": sha256_text(rubric_diff),
            "parent_criterion_count": len(parse_rubric_levels_strict(current_rubric)),
            "criterion_count": len(parse_rubric_levels_strict(text)),
            "available_trajectory_events": available_events,
            "retrieved_trajectory_events": sorted(
                set(proposer_output.retrieved_event_ids)
            ),
        }
        write_json_atomic(metadata_path, metadata)
        trace_path.write_text(proposer_output.trace, encoding="utf-8")
        make_read_only(rubric_path)
        make_read_only(metadata_path)
        make_read_only(trace_path)
        make_read_only(diff_path)
        return EvolvedRubric(text, rubric_sha256, changed, metadata)

    @staticmethod
    def _archive_failed_attempt(
        output_dir: Path,
        version: int,
        evolve_attempt: int,
        proposer_output: ProposerOutput,
        error: Exception,
    ) -> None:
        failure_dir = output_dir / f"r{version:04d}.proposer-failures"
        failure_dir.mkdir(exist_ok=True)
        sequence = len(list(failure_dir.glob("attempt-*.json"))) + 1
        stem = f"attempt-{sequence:04d}"
        (failure_dir / f"{stem}.answer.txt").write_text(
            proposer_output.rubric_text,
            encoding="utf-8",
        )
        (failure_dir / f"{stem}.trace.md").write_text(
            proposer_output.trace,
            encoding="utf-8",
        )
        write_json_atomic(
            failure_dir / f"{stem}.json",
            {
                "schema_version": 1,
                "evolve_attempt": evolve_attempt,
                "error_type": type(error).__name__,
                "error": str(error) or type(error).__name__,
                "query_count": proposer_output.query_count,
                "retrieved_event_ids": list(proposer_output.retrieved_event_ids),
                "cost": proposer_output.cost,
            },
        )

    def _load_existing(
        self,
        rubric_path: Path,
        metadata_path: Path,
        trace_path: Path,
        diff_path: Path,
        version: int,
        source_submission_id: str,
        current_rubric: str,
        available_events: int,
        source_hashes: dict[str, str],
    ) -> EvolvedRubric:
        if (
            not rubric_path.is_file()
            or not metadata_path.is_file()
            or not trace_path.is_file()
            or not diff_path.is_file()
        ):
            raise RuntimeError(f"incomplete evolved rubric version r{version:04d}")
        try:
            text = rubric_path.read_text(encoding="utf-8")
            stored = json.loads(metadata_path.read_text(encoding="utf-8"))
            proposer_trace = trace_path.read_text(encoding="utf-8")
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
        if (
            not isinstance(stored, dict)
            or set(stored) != _METADATA_KEYS
            or stored.get("schema_version") != 1
            or stored.get("kind") != "complete-rubric-generation"
            or stored.get("version") != version
            or stored.get("mode") != RubricEvolution.PROSPECTIVE.value
            or stored.get("source_submission_id") != source_submission_id
            or any(stored.get(key) != value for key, value in source_hashes.items())
            or stored.get("provider") != self.agent.provider
            or stored.get("model") != self.model
            or stored.get("prompt_version") != _PROPOSER_PROMPT_VERSION
            or stored.get("query_limit") != self.query_limit
            or type(stored.get("attempt_count")) is not int
            or stored["attempt_count"] < 1
            or not isinstance(stored.get("proposer_attempt_costs"), list)
            or len(stored["proposer_attempt_costs"]) != stored.get("attempt_count")
            or any(
                not isinstance(cost, dict)
                or set(cost) != {
                    "cost_usd", "estimated_cost_usd", "cost_source"
                }
                for cost in stored["proposer_attempt_costs"]
            )
            or stored.get("rubric_sha256") != sha256_text(text)
            or stored.get("parent_rubric_sha256") != sha256_text(current_rubric)
            or stored.get("rubric_changed") is not changed
            or stored.get("rubric_diff_sha256") != sha256_text(rubric_diff)
            or rubric_diff != expected_diff
            or stored.get("parent_criterion_count") != parent_criterion_count
            or stored.get("criterion_count") != criterion_count
            or stored.get("available_trajectory_events") != available_events
            or not isinstance(stored.get("retrieved_trajectory_events"), list)
            or not stored.get("retrieved_trajectory_events")
            or any(
                type(event) is not int or event < 1 or event > available_events
                for event in stored.get("retrieved_trajectory_events", [])
            )
            or stored.get("proposer_trace_sha256") != sha256_text(proposer_trace)
            or type(stored.get("trajectory_query_count")) is not int
            or not 1 <= stored["trajectory_query_count"] <= self.query_limit
        ):
            raise RuntimeError(f"invalid evolved rubric version r{version:04d}")
        try:
            _validate_trace_evidence(
                proposer_trace,
                available_events=available_events,
                retrieved_events=frozenset(stored["retrieved_trajectory_events"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"invalid evolved rubric version r{version:04d}"
            ) from exc
        if expected_text != text:
            raise RuntimeError(f"invalid evolved rubric version r{version:04d}")
        return EvolvedRubric(text, sha256_text(text), changed, stored)

    def _run_codex_proposer(
        self,
        *,
        instruction: str,
        current_rubric: str,
        answer: str,
        trace: str,
        trajectory_path: Path,
        evaluation: dict[str, object],
        repair_error: str | None,
    ) -> ProposerOutput:
        temporary = Path(tempfile.mkdtemp(prefix="biomnibench-rubric-proposer-"))
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
                "kind": "rubric-proposer-evidence",
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
            prompt = _proposer_prompt(
                instruction=instruction,
                current_rubric=current_rubric,
                answer=answer,
                trace=trace,
                evaluation=evaluation,
                query_tool=Path("data/trajectory_query.py"),
                query_limit=self.query_limit,
                available_events=int(inventory["events"]),
                repair_error=repair_error,
            )
            (task / "instruction.md").write_text(prompt, encoding="utf-8")
            run = temporary / "run"
            paths = RunPaths(
                provider=self.agent.provider,
                run_dir=run,
                workspace_dir=workspace,
                prompt_path=run / "prompt.txt",
                policy_path=run / "no-web-policy.toml",
                stream_path=run / "trajectory.stream.jsonl",
                status_path=run / "status.json",
                output_last_message_path=workspace / "answer.txt",
            )
            config = replace(
                self.agent,
                quiet=True,
            )
            exit_code, _ = AgentRunner(config).run(task, paths=paths)
            if exit_code != 0:
                raise RuntimeError(
                    f"{self.agent.provider} rubric proposer exited with code {exit_code}"
                )
            query_state = workspace / "artifacts"
            counter = query_state / "query-count.txt"
            audit = query_state / "query-audit.jsonl"
            if not counter.is_file() or not audit.is_file():
                raise RuntimeError("trajectory query audit is missing")
            query_count = int(counter.read_text())
            audit_records = [
                json.loads(line)
                for line in audit.read_text(encoding="utf-8").splitlines()
            ]
            if len(audit_records) != query_count:
                raise RuntimeError("trajectory query audit disagrees with query count")
            retrieved = sorted({
                event
                for record in audit_records
                for event in record.get("event_ids", [])
                if type(event) is int
            })
            cost = RunCost.from_stream(
                paths.stream_path,
                model=self.model,
                service_tier=self.agent.service_tier,
            ).fields()
            return ProposerOutput(
                rubric_text=(workspace / "answer.txt").read_text(encoding="utf-8"),
                trace=(workspace / "trace.md").read_text(encoding="utf-8"),
                query_count=query_count,
                retrieved_event_ids=tuple(retrieved),
                cost=cost,
            )
        finally:
            shutil.rmtree(temporary, ignore_errors=True)


def _proposer_prompt(
    *,
    instruction: str,
    current_rubric: str,
    answer: str,
    trace: str,
    evaluation: dict[str, object],
    query_tool: Path,
    query_limit: int,
    available_events: int,
    repair_error: str | None,
) -> str:
    repair = (
        "\nThe previous complete rubric failed validation: " + repair_error
        if repair_error else ""
    )
    return f"""Prompt contract: {_PROPOSER_PROMPT_VERSION}

Act as an independent designer of the complete optimizer rubric for the next revision of a scientific task.

The scoring judge is separate from you. Produce the full next rubric, not an edit, patch, action list, JSON object, or explanation. The current rubric is a starting point rather than an immutable template. You may retain, rewrite, remove, merge, split, reorder, or reweight any criterion. The current submission has already been scored, so your rubric applies only to the next submission.

The full trajectory is deliberately absent. Selectively inspect it with at most {query_limit} bounded calls:
`{query_tool} inventory`
`{query_tool} timeline --start EVENT --limit COUNT`
`{query_tool} search QUERY --limit COUNT`
`{query_tool} show EVENT_ID --start OFFSET --limit CHARS`

Use the supplied trace only as a navigation summary. Retrieve evidence needed to test execution, data lineage, intermediate decisions, omissions, robustness checks, final claims, and contrary evidence. The trajectory index contains {available_events} events. You must retrieve at least one event before returning either a changed or unchanged rubric. Cite each event used in trace.md as `trajectory:event-N`. Do not read the SQLite database directly.

Design the rubric through an internal recursive decompose-filter cycle:
1. Map the task to the complete set of important outcome and analysis-process dimensions.
2. Find current criteria that are too broad, stacked, vague, weakly discriminative, or missing an important dimension.
3. Decompose a coarse criterion into atomic subcriteria only when the subcriteria distinguish materially different quality levels.
4. Filter any criterion that is misaligned, conflicting, redundant, a near paraphrase, or a strict subset or superset of another criterion.
5. Stop decomposing when further criteria would track incidental details of this submission instead of stable task quality.
6. Allocate points across distinct dimensions. Do not double-count correlated evidence or let several similar criteria dominate the reward.

The final rubric set must be informative, comprehensive, and non-redundant. Apply these requirements:
- Make every criterion task-specific, atomic, self-contained, and consistently judgeable across plausible future submissions.
- Prefer objective and observable checks. Avoid vague terms such as good, appropriate, high-quality, thorough, or correct without an operational boundary.
- Emphasize process evidence where process quality matters: executed analyses, justified data selection, valid transformations, provenance, robustness checks, uncertainty handling, artifact consistency, and reconciliation of contrary results.
- Give credit for equivalent valid methods. Do not prescribe one exact command, filename, wording, numerical result, or analysis path unless the task requires it.
- Do not reward documentation, a checklist, a PASS label, a manifest, file existence, or a solver claim that work occurred without independent supporting evidence.
- Make the level descriptions meaningfully discriminative. A must describe complete supported performance, intermediate levels must describe specific partial evidence or defects, and the lowest level must describe missing, contradicted, invalid, or merely asserted work.
- Keep preference direction positive: a higher level must always represent a genuinely better task result or process, not closer imitation of evaluator language.
- Prevent one failure from losing points under several criteria. Cover all important dimensions without semantic overlap.
- Use the current answer and trajectory as evidence about rubric weaknesses, not as an answer key. Do not make a criterion merely to fit or punish an incidental feature of this submission.
- Privately test each criterion against three counterfactuals: a strong executed solution, a partial but honest solution, and a superficial compliance attempt. Keep only criteria that separate them for substantive reasons.

The complete rubric must use contiguous `Criterion 1:` through `Criterion N:` sections. Each criterion must have three or more contiguous level labels starting at A, strictly descending integer points, exactly one zero-valued level, and one nonempty `[LABEL]:` description per level. The sum of all A-level points must equal 100. Criteria may include negative lower levels.

If no supported revision improves the complete set, reproduce the current rubric unchanged. An unchanged complete rubric is the only abstention mechanism.

The query tool writes harness-managed `query-count.txt` and `query-audit.jsonl` files directly under `./artifacts`. Do not move, edit, replace, or delete those files.

Write trace.md with the coverage audit, retrieved evidence, decomposition decisions, rejected overlaps or conflicts, cheap-compliance tests, and weight rationale. Write the complete next rubric to answer.txt. Return exactly the same complete rubric as the final response. Do not use JSON, XML, commentary, or Markdown code fences in answer.txt.{repair}

<task>
{instruction}
</task>
<current_rubric>
{current_rubric}
</current_rubric>
<current_answer>
{answer}
</current_answer>
<current_trace>
{trace}
</current_trace>
<preliminary_evaluation_json>
{json.dumps(evaluation, ensure_ascii=False)}
</preliminary_evaluation_json>
"""


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
                f"{criterion_key} level labels must be contiguous from A with at least three levels"
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


def _validate_trace_evidence(
    trace: str,
    *,
    available_events: int,
    retrieved_events: frozenset[int],
) -> None:
    references = [int(value) for value in _EVIDENCE_REFERENCE.findall(trace)]
    if not references:
        raise ValueError("rubric proposer trace lacks a trajectory:event-N reference")
    if any(event < 1 or event > available_events for event in references):
        raise ValueError("rubric proposer trace references an unavailable trajectory event")
    if any(event not in retrieved_events for event in references):
        raise ValueError("rubric proposer trace references an event that was not retrieved")


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
