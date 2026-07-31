"""Codex-agent optimizer-rubric evolution with bounded trajectory retrieval."""

from __future__ import annotations

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
    AGENT = "agent"


@dataclass(frozen=True)
class EvolvedRubric:
    text: str
    sha256: str
    proposal: dict[str, object]


@dataclass(frozen=True)
class ProposerOutput:
    answer: str
    trace: str
    query_count: int
    retrieved_event_ids: tuple[int, ...]


_EVIDENCE_REFERENCE = re.compile(r"\btrajectory:event-(\d+)\b")
_CRITERION_HEADER = re.compile(r"^Criterion\s+(\d+)\s*:", re.MULTILINE)
_CRITERION_TITLE = re.compile(
    r"^Criterion\s+\d+\s*:\s*(.+?)\s*$", re.MULTILINE
)
_PROPOSER_CONTRACT_TERMS = (
    "rubric_text",
    "change_summary",
    "failure_evidence",
    "generalization_rationale",
    "validation_plan",
)


class RubricEvolver:
    def __init__(
        self,
        *,
        agent: AgentRunConfig,
        query_limit: int,
        max_retries: int = 2,
        run_proposer: Callable[..., ProposerOutput] | None = None,
    ) -> None:
        if agent.provider != "codex" or not agent.model:
            raise ValueError("rubric proposer must be a Codex agent with a model")
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
        output_dir: Path,
    ) -> EvolvedRubric:
        rubric_path = output_dir / f"r{version:04d}.txt"
        proposal_path = output_dir / f"r{version:04d}.proposal.json"
        trace_path = output_dir / f"r{version:04d}.proposer.trace.md"
        available_events = indexable_event_count(trajectory_path)
        if rubric_path.exists() or proposal_path.exists() or trace_path.exists():
            return self._load_existing(
                rubric_path,
                proposal_path,
                trace_path,
                version,
                current_rubric,
                available_events,
            )

        last_error: Exception | None = None
        proposal: dict[str, object] | None = None
        text = ""
        proposer_output: ProposerOutput | None = None
        attempt = 0
        for attempt in range(1, self.max_retries + 2):
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
                proposal, text = _parse_proposal(
                    proposer_output.answer,
                    current_rubric=current_rubric,
                    available_events=available_events,
                    retrieved_events=frozenset(proposer_output.retrieved_event_ids),
                )
                parse_rubric_levels_strict(text)
                break
            except Exception as exc:
                last_error = exc
        else:
            raise RuntimeError(
                "rubric proposer failed after "
                f"{self.max_retries + 1} attempts: {last_error}"
            )

        assert proposal is not None
        assert proposer_output is not None
        output_dir.mkdir(parents=True, exist_ok=True)
        temporary = output_dir / f".r{version:04d}.{secrets.token_hex(8)}.tmp"
        try:
            temporary.write_text(text, encoding="utf-8")
            os.replace(temporary, rubric_path)
        finally:
            if os.path.lexists(temporary):
                temporary.unlink()
        write_json_atomic(proposal_path, {
            "schema_version": 4,
            "kind": "optimizer-process-rubric-patch",
            "version": version,
            "mode": RubricEvolution.AGENT.value,
            "provider": "codex",
            "model": self.model,
            "query_limit": self.query_limit,
            "attempt_count": attempt,
            "trajectory_query_count": proposer_output.query_count,
            "proposer_trace_sha256": sha256_text(proposer_output.trace),
            "rubric_sha256": sha256_text(text),
            "available_trajectory_events": available_events,
            "retrieved_trajectory_events": sorted(
                set(proposer_output.retrieved_event_ids)
            ),
            **proposal,
        })
        trace_path.write_text(proposer_output.trace, encoding="utf-8")
        make_read_only(rubric_path)
        make_read_only(proposal_path)
        make_read_only(trace_path)
        return EvolvedRubric(text, sha256_text(text), proposal)

    def _load_existing(
        self,
        rubric_path: Path,
        proposal_path: Path,
        trace_path: Path,
        version: int,
        current_rubric: str,
        available_events: int,
    ) -> EvolvedRubric:
        if (
            not rubric_path.is_file()
            or not proposal_path.is_file()
            or not trace_path.is_file()
        ):
            raise RuntimeError(f"incomplete evolved rubric version r{version:04d}")
        text = rubric_path.read_text(encoding="utf-8")
        stored = json.loads(proposal_path.read_text(encoding="utf-8"))
        proposer_trace = trace_path.read_text(encoding="utf-8")
        if (
            not isinstance(stored, dict)
            or stored.get("schema_version") != 4
            or stored.get("kind") != "optimizer-process-rubric-patch"
            or stored.get("version") != version
            or stored.get("mode") != RubricEvolution.AGENT.value
            or stored.get("provider") != "codex"
            or stored.get("model") != self.model
            or stored.get("query_limit") != self.query_limit
            or stored.get("rubric_sha256") != sha256_text(text)
            or stored.get("available_trajectory_events") != available_events
            or not isinstance(stored.get("retrieved_trajectory_events"), list)
            or any(
                type(event) is not int or event < 1 or event > available_events
                for event in stored.get("retrieved_trajectory_events", [])
            )
            or stored.get("proposer_trace_sha256") != sha256_text(proposer_trace)
            or type(stored.get("trajectory_query_count")) is not int
            or not 0 <= stored["trajectory_query_count"] <= self.query_limit
        ):
            raise RuntimeError(f"invalid evolved rubric version r{version:04d}")
        parse_rubric_levels_strict(text)
        proposal = {
            key: stored[key]
            for key in (
                "action",
                "criterion_text",
                "change_summary",
                "failure_evidence",
                "generalization_rationale",
                "validation_plan",
            )
        }
        try:
            validated_proposal, expected_text = _parse_proposal(
                json.dumps(proposal),
                current_rubric=current_rubric,
                available_events=available_events,
                retrieved_events=frozenset(stored["retrieved_trajectory_events"]),
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise RuntimeError(
                f"invalid evolved rubric version r{version:04d}"
            ) from exc
        if validated_proposal != proposal or expected_text != text:
            raise RuntimeError(f"invalid evolved rubric version r{version:04d}")
        return EvolvedRubric(text, sha256_text(text), proposal)

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
            workspace_data = workspace / "data"
            workspace_data.mkdir(parents=True)
            evidence = temporary / "evidence"
            evidence.mkdir()
            linked_trajectory = evidence / "trajectory.stream.jsonl"
            os.link(trajectory_path, linked_trajectory)
            write_json_atomic(evidence / "manifest.json", {
                "schema_version": 1,
                "kind": "rubric-proposer-evidence",
                "evidence_files": [linked_trajectory.name],
            })
            database = workspace_data / "trajectory.sqlite"
            inventory = build_evidence_index(evidence, database)
            query_tool = workspace_data / "trajectory_query.py"
            write_query_tool(
                query_tool,
                database,
                max_queries=self.query_limit,
                counter_path=workspace_data / "query-count.txt",
                audit_path=workspace_data / "query-audit.jsonl",
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
                provider="codex",
                run_dir=run,
                workspace_dir=workspace,
                prompt_path=run / "prompt.txt",
                policy_path=run / "no-web-policy.toml",
                stream_path=run / "trajectory.stream.jsonl",
                status_path=run / "status.json",
            )
            config = replace(
                self.agent,
                quiet=True,
                allow_web=False,
                allow_network=False,
                extra_args=("--ephemeral", "--ignore-user-config"),
            )
            exit_code, _ = AgentRunner(config).run(task, paths=paths)
            if exit_code != 0:
                raise RuntimeError(f"Codex rubric proposer exited with code {exit_code}")
            counter = workspace_data / "query-count.txt"
            query_count = int(counter.read_text()) if counter.exists() else 0
            audit = workspace_data / "query-audit.jsonl"
            audit_records = [
                json.loads(line)
                for line in audit.read_text(encoding="utf-8").splitlines()
            ] if audit.exists() else []
            if len(audit_records) != query_count:
                raise RuntimeError("trajectory query audit disagrees with query count")
            retrieved = sorted({
                event
                for record in audit_records
                for event in record.get("event_ids", [])
                if type(event) is int
            })
            return ProposerOutput(
                answer=(workspace / "answer.txt").read_text(encoding="utf-8"),
                trace=(workspace / "trace.md").read_text(encoding="utf-8"),
                query_count=query_count,
                retrieved_event_ids=tuple(retrieved),
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
        "\nThe previous proposal failed validation: " + repair_error
        if repair_error else ""
    )
    return f"""Act as an independent rubric proposer for a scientific task.

The scoring judge is separate from you. Investigate whether the current submission reveals one generalizable process failure that the stable rubric does not already cover. Never rewrite, merge, remove, or reweight the stable rubric.

The full trajectory is deliberately absent. Selectively inspect it with at most {query_limit} bounded calls:
`{query_tool} inventory`
`{query_tool} timeline --start EVENT --limit COUNT`
`{query_tool} search QUERY --limit COUNT`
`{query_tool} show EVENT_ID --start OFFSET --limit CHARS`

Use trace.md as a navigation summary, then retrieve only evidence needed to test claims, provenance, execution, omissions, and contrary evidence. Cite retrieved evidence as `trajectory:event-N` in failure_evidence. Do not read the SQLite database directly.

The stable task rubric must not be rewritten. Return either one additive process-penalty criterion or no patch. An additive criterion begins with `Criterion 1: Title`, contains exactly `Levels: A=0 B=-5 C=-10`, and uses `[A]:`, `[B]:`, and `[C]:`. It must evaluate evidence/provenance rather than answer wording, exact values, filenames, or proposer output formatting. The runner will renumber it. Do not mention the proposer JSON keys inside the criterion.

The trajectory index contains {available_events} events. For `add_process_criterion`, failure_evidence must be nonempty and every entry must cite at least one retrieved `trajectory:event-N`. If evidence is unavailable or no generalizable process failure is supported, use `no_patch` rather than speculating.

Write trace.md explaining your investigation. Write answer.txt containing exactly one JSON object with keys action, criterion_text, change_summary, failure_evidence, generalization_rationale, and validation_plan. action is `add_process_criterion` or `no_patch`. For no_patch, criterion_text and failure_evidence are empty. validation_plan explains how to test the check against valid and perturbed submissions.{repair}

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


def _parse_proposal(
    response: str,
    *,
    current_rubric: str,
    available_events: int,
    retrieved_events: frozenset[int],
) -> tuple[dict[str, object], str]:
    start, end = response.find("{"), response.rfind("}")
    if start < 0 or end < start:
        raise ValueError("rubric proposer returned no JSON object")
    proposal = json.loads(response[start:end + 1])
    if (
        not isinstance(proposal, dict)
        or set(proposal) != {
            "action", "criterion_text", "change_summary", "failure_evidence",
            "generalization_rationale", "validation_plan",
        }
        or proposal["action"] not in {"add_process_criterion", "no_patch"}
        or not isinstance(proposal["criterion_text"], str)
        or not isinstance(proposal["change_summary"], str)
        or not proposal["change_summary"].strip()
        or not isinstance(proposal["generalization_rationale"], str)
        or not proposal["generalization_rationale"].strip()
        or not isinstance(proposal["validation_plan"], str)
        or not proposal["validation_plan"].strip()
        or not isinstance(proposal["failure_evidence"], list)
        or not all(isinstance(item, str) and item for item in proposal["failure_evidence"])
    ):
        raise ValueError("rubric proposer returned an invalid proposal")
    if proposal["action"] == "no_patch":
        if proposal["criterion_text"].strip() or proposal["failure_evidence"]:
            raise ValueError("no_patch must not contain a criterion or failure evidence")
        return proposal, current_rubric

    criterion = proposal["criterion_text"].strip()
    if len(criterion) < 200:
        raise ValueError("process criterion is too short")
    lowered = criterion.lower()
    if any(term in lowered for term in _PROPOSER_CONTRACT_TERMS):
        raise ValueError("process criterion leaks the rubric proposer contract")
    levels = parse_rubric_levels_strict(criterion)
    if len(levels) != 1 or next(iter(levels.values())) != {"A": 0, "B": -5, "C": -10}:
        raise ValueError("process criterion must use Levels: A=0 B=-5 C=-10")
    headers = list(_CRITERION_HEADER.finditer(criterion))
    if len(headers) != 1:
        raise ValueError("process patch must contain exactly one criterion")
    if not proposal["failure_evidence"]:
        raise ValueError("process patch requires trajectory-grounded failure evidence")
    for evidence in proposal["failure_evidence"]:
        references = [int(value) for value in _EVIDENCE_REFERENCE.findall(evidence)]
        if not references:
            raise ValueError("failure evidence lacks a trajectory:event-N reference")
        if any(event < 1 or event > available_events for event in references):
            raise ValueError("failure evidence references an unavailable trajectory event")
        if any(event not in retrieved_events for event in references):
            raise ValueError("failure evidence references an event that was not retrieved")
    proposed_title = _CRITERION_TITLE.search(criterion)
    assert proposed_title is not None
    normalized_title = " ".join(proposed_title.group(1).lower().split())
    existing_titles = {
        " ".join(title.lower().split())
        for title in _CRITERION_TITLE.findall(current_rubric)
    }
    if normalized_title in existing_titles:
        raise ValueError("process criterion duplicates an existing criterion title")
    existing_numbers = [
        int(value) for value in _CRITERION_HEADER.findall(current_rubric)
    ]
    if not existing_numbers:
        raise ValueError("current rubric contains no numbered criteria")
    next_number = max(existing_numbers) + 1
    criterion = _CRITERION_HEADER.sub(
        f"Criterion {next_number}:", criterion, count=1
    )
    if criterion in current_rubric:
        raise ValueError("process criterion duplicates an existing criterion")
    text = current_rubric.rstrip() + "\n\n" + criterion + "\n"
    parse_rubric_levels_strict(text)
    return {**proposal, "criterion_text": criterion}, text
