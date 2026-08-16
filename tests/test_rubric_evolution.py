from __future__ import annotations

import errno
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from rubric_gen.runtime.agents.models import AgentRunConfig
from rubric_gen.runtime.agents.workspaces import TaskWorkspace
from rubric_gen.evidence.index import (
    build_evidence_index,
    indexable_event_contents,
    write_query_tool,
)
import rubric_gen.submission_revision.evolution as evolution_module
from rubric_gen.submission_revision.evolution import (
    AuditorOutput,
    ProposerOutput,
    RubricEvolver,
    RubricScoreContext,
)
from rubric_gen.submission_revision.judging.scoring import parse_rubric_levels_strict
from rubric_gen.artifacts.hashing import sha256_text


def _current_rubric() -> str:
    return (
        "# Optimizer rubric\n\n"
        "Criterion 1: Scientific validity\n"
        "Levels: A=100 B=50 C=0\n"
        "[A]: The analysis is complete, executed, and scientifically valid.\n"
        "[B]: The analysis is partly complete or has one material limitation.\n"
        "[C]: The analysis is missing, invalid, or unsupported.\n"
    )


def _revised_rubric() -> str:
    return (
        "# Optimizer rubric\n\n"
        "Criterion 1: Data preparation integrity\n"
        "Levels: A=75 B=35 C=0\n"
        "[A]: Executed transformations preserve the intended cohort and variables, "
        "with results traceable to source data.\n"
        "[B]: The result is valid for a useful, clearly bounded subset, but a "
        "material lineage gap prevents broader use.\n"
        "[C]: The result is invalid, unusable, contradicted, or only asserted.\n\n"
        "Criterion 2: Independent result validation\n"
        "Levels: A=25 B=10 C=0\n"
        "[A]: An independent check reproduces the central result and any discrepancy "
        "is resolved in the conclusion.\n"
        "[B]: The central result remains useful only within a stated boundary "
        "because a material discrepancy is unresolved.\n"
        "[C]: The central result lacks independent support or is contradicted by "
        "available evidence.\n"
    )


def _replacement_rubric() -> str:
    return (
        "Criterion 1: Reproducible task completion\n"
        "Levels: A=100 B=40 C=0\n"
        "[A]: The required analysis is executed and independently reproducible from "
        "the task data and persisted artifacts.\n"
        "[B]: The result is reproducible for a useful, clearly bounded subset but "
        "not for the full required scope.\n"
        "[C]: The result is invalid, unusable, or supported only by prose.\n"
    )


def _revised_proposal() -> dict[str, object]:
    return {
        "schema_version": 2,
        "decision": "revise",
        "rubric_title": "Stronger scientific outcome rubric",
        "criteria": [
            {
                "title": "Data preparation integrity",
                "description": "The analysis preserves the intended data meaning.",
                "levels": [
                    {
                        "label": "A",
                        "points": 75,
                        "description": (
                            "Executed transformations preserve the intended cohort "
                            "and variables, with results traceable to source data."
                        ),
                    },
                    {
                        "label": "B",
                        "points": 35,
                        "description": (
                            "The result is valid for a useful, clearly bounded subset, "
                            "but a material lineage gap prevents broader use."
                        ),
                    },
                    {
                        "label": "C",
                        "points": 0,
                        "description": (
                            "The result is invalid, unusable, contradicted, or only "
                            "asserted."
                        ),
                    },
                ],
            },
            {
                "title": "Independent result validation",
                "description": "The central result survives an independent check.",
                "levels": [
                    {
                        "label": "A",
                        "points": 25,
                        "description": (
                            "An independent check reproduces the central result and "
                            "any discrepancy is resolved in the conclusion."
                        ),
                    },
                    {
                        "label": "B",
                        "points": 10,
                        "description": (
                            "The central result remains useful only within a stated "
                            "boundary because a material discrepancy is unresolved."
                        ),
                    },
                    {
                        "label": "C",
                        "points": 0,
                        "description": (
                            "The central result lacks independent support or is "
                            "contradicted by available evidence."
                        ),
                    },
                ],
            },
        ],
        "challenge_changes": [
            {
                "criterion_title": "Independent result validation",
                "finding_ids": ["F1"],
                "stable_quality_dimension": "Independent validity",
                "current_evidence_gap": "The reported result has limited support.",
                "future_submission_test": (
                    "A future submission must reproduce the result independently."
                ),
            }
        ],
    }


def _replacement_proposal() -> dict[str, object]:
    proposal = _revised_proposal()
    proposal["rubric_title"] = "Replacement outcome rubric"
    proposal["criteria"] = [
        {
            "title": "Reproducible task completion",
            "description": "The required result is reproducible from task data.",
            "levels": [
                {
                    "label": "A",
                    "points": 100,
                    "description": (
                        "The required analysis is executed and independently "
                        "reproducible from the task data and persisted artifacts."
                    ),
                },
                {
                    "label": "B",
                    "points": 40,
                    "description": (
                        "The result is reproducible for a useful, clearly bounded "
                        "subset but not for the full required scope."
                    ),
                },
                {
                    "label": "C",
                    "points": 0,
                    "description": (
                        "The result is invalid, unusable, or supported only by prose."
                    ),
                },
            ],
        }
    ]
    proposal["challenge_changes"][0]["criterion_title"] = (  # type: ignore[index]
        "Reproducible task completion"
    )
    return proposal


def _retain_proposal() -> dict[str, object]:
    return {
        "schema_version": 2,
        "decision": "retain",
        "rubric_title": "",
        "criteria": [],
        "challenge_changes": [],
    }


def _score_context(*, saturated: bool = False) -> RubricScoreContext:
    score = 100 if saturated else 56
    level = "A" if saturated else "B"
    return RubricScoreContext(
        score=score,
        raw_score=score,
        selected_levels={"criterion_1": level},
        criterion_scores={"criterion_1": score},
        score_history=(score,),
    )


def _rendered(proposal: dict[str, object]) -> str:
    return evolution_module._proposal_rubric_text(
        proposal,
        current_rubric=_current_rubric(),
    )


def _agent(*, model: str = "auditor-model") -> AgentRunConfig:
    return AgentRunConfig(provider="codex", model=model, retries=0)


def _cost() -> dict[str, float | str | None]:
    return {
        "cost_usd": None,
        "estimated_cost_usd": 0.01,
        "cost_source": "test-estimate",
    }


def _generation() -> dict[str, object]:
    return {
        "provider": "openai",
        "requested_model": "proposer-model",
        "effective_model": "proposer-model-served",
        "response_id": "response-1",
    }


def _packet(
    event_text: str,
    *,
    status: str = "supported_problem",
    snippet_text: str = "evidence",
    start: int | None = None,
) -> str:
    if start is None:
        start = event_text.index(snippet_text)
    findings = []
    if status == "supported_problem":
        findings = [{
            "finding_id": "F1",
            "kind": "supported_problem",
            "hypothesis": "The trajectory contains an unsupported result.",
            "basis": "The result claim lacks a complete verification record.",
            "evidence": [{
                "event_id": 1,
                "start_offset": start,
                "end_offset": start + len(snippet_text),
            }],
            "counterevidence": [],
            "uncertainty": "The bounded trace can omit external evidence.",
            "verification_question": "Can an independent check reproduce it?",
        }]
    return json.dumps({
        "schema_version": 3,
        "inspected": "Inspected the result claim and its stated support.",
        "findings": findings,
    })


def _auditor_output(
    event_text: str,
    *,
    packet_text: str | None = None,
    queries: int = 2,
    events: tuple[int, ...] = (1,),
) -> AuditorOutput:
    return AuditorOutput(
        packet_text=packet_text or _packet(event_text),
        query_count=queries,
        retrieved_event_ids=events,
        cost=_cost(),
    )


def _proposer_output(
    proposal: dict[str, object] | None = None,
) -> ProposerOutput:
    return ProposerOutput(
        proposal_text=json.dumps(proposal or _revised_proposal()),
        cost=_cost(),
        generation=_generation(),
    )


def _arguments(
    tmp_path: Path,
    *,
    saturated: bool = False,
) -> dict[str, object]:
    trajectory = tmp_path / "trajectory.stream.jsonl"
    trajectory.write_text('{"type":"message","content":"evidence"}\n')
    score_context = _score_context(saturated=saturated)

    def candidate_gate(text: str, attempt: int) -> dict[str, object]:
        levels = parse_rubric_levels_strict(text)
        selected_levels = {key: "B" for key in levels}
        criterion_scores = {key: value["B"] for key, value in levels.items()}
        raw_score = sum(criterion_scores.values())
        return {
            "parent_score": score_context.score,
            "candidate_score": max(0, min(100, raw_score)),
            "raw_score": raw_score,
            "selected_levels": selected_levels,
            "criterion_scores": criterion_scores,
            "rubric_sha256": sha256_text(text),
            "attempt_id": f"{attempt:032x}",
        }

    def candidate_validator(text: str, attempt_id: str) -> dict[str, object]:
        return candidate_gate(text, int(attempt_id, 16))

    return {
        "instruction": "TASK",
        "current_rubric": _current_rubric(),
        "current_submission": "SUBMISSION",
        "trajectory_path": trajectory,
        "score_context": score_context,
        "version": 1,
        "source_submission_id": "s000",
        "output_dir": tmp_path / "rubrics",
        "candidate_gate": candidate_gate,
        "candidate_validator": candidate_validator,
    }


def _event_text(arguments: dict[str, object]) -> str:
    path = arguments["trajectory_path"]
    assert isinstance(path, Path)
    return indexable_event_contents(path)[1]


def _evolver(
    *,
    run_auditor=None,
    run_proposer=None,
    query_limit: int = 3,
    max_retries: int = 2,
    auditor: AgentRunConfig | None = None,
    proposer_model: str = "proposer-model",
    proposer_base_url: str | None = None,
) -> RubricEvolver:
    return RubricEvolver(
        auditor=auditor or _agent(),
        proposer_model=proposer_model,
        proposer_base_url=proposer_base_url,
        query_limit=query_limit,
        max_retries=max_retries,
        run_auditor=run_auditor,
        run_proposer=run_proposer,
    )


def test_trajectory_staging_copies_across_filesystems(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = tmp_path / "source.jsonl"
    destination = tmp_path / "destination.jsonl"
    source.write_text('{"event":1}\n')

    def cross_device_link(_source: Path, _destination: Path) -> None:
        raise OSError(errno.EXDEV, "cross-device link")

    monkeypatch.setattr(evolution_module.os, "link", cross_device_link)
    evolution_module._link_or_copy(source, destination)

    assert destination.read_bytes() == source.read_bytes()


def test_trajectory_query_tool_is_self_contained(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "trajectory.jsonl").write_text(
        '{"type":"message","content":"evidence"}\n'
    )
    (evidence / "manifest.json").write_text(json.dumps({
        "evidence_files": ["trajectory.jsonl"],
    }))
    database = tmp_path / "data" / "trajectory.sqlite"
    build_evidence_index(evidence, database)
    query_tool = database.parent / "trajectory_query.py"
    state_directory = tmp_path / "artifacts"
    write_query_tool(
        query_tool,
        database,
        max_queries=3,
        state_directory=state_directory,
    )

    source = query_tool.read_text()
    assert "rubric_gen" not in source
    assert str(tmp_path) not in source
    relocated = tmp_path / "relocated"
    relocated_data = relocated / "data"
    relocated_data.mkdir(parents=True)
    for artifact in (query_tool, database):
        (relocated_data / artifact.name).write_bytes(artifact.read_bytes())
    result = subprocess.run(
        [sys.executable, str(relocated_data / query_tool.name), "timeline"],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        check=True,
        env={"PATH": "/usr/bin:/bin"},
    )

    assert "event:1" in result.stdout
    counter = relocated / "artifacts" / "query-count.txt"
    audit = relocated / "artifacts" / "query-audit.jsonl"
    assert counter.read_text() == "1"
    assert json.loads(audit.read_text())["event_ids"] == [1]


def test_trajectory_query_tool_enforces_parallel_budget(tmp_path: Path) -> None:
    evidence = tmp_path / "evidence"
    evidence.mkdir()
    (evidence / "trajectory.jsonl").write_text(
        '{"type":"message","content":"evidence"}\n'
    )
    (evidence / "manifest.json").write_text(json.dumps({
        "evidence_files": ["trajectory.jsonl"],
    }))
    database = tmp_path / "data" / "trajectory.sqlite"
    build_evidence_index(evidence, database)
    query_tool = database.parent / "trajectory_query.py"
    state_directory = tmp_path / "artifacts"
    write_query_tool(
        query_tool,
        database,
        max_queries=3,
        state_directory=state_directory,
    )

    processes = [
        subprocess.Popen(
            [sys.executable, str(query_tool), "timeline"],
            cwd=tmp_path,
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PATH": "/usr/bin:/bin"},
        )
        for _ in range(24)
    ]
    results = [(*process.communicate(), process.returncode) for process in processes]

    assert sum(return_code == 0 for _, _, return_code in results) == 3
    assert all(
        not stderr or "trajectory query budget exhausted" in stderr
        for _, stderr, _ in results
    )
    assert (state_directory / "query-count.txt").read_text() == "3"
    audit_records = [
        json.loads(line)
        for line in (state_directory / "query-audit.jsonl").read_text().splitlines()
    ]
    assert len(audit_records) == 3
    assert all(record["event_ids"] == [1] for record in audit_records)


def test_codex_auditor_uses_audit_log_as_query_count(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trajectory = tmp_path / "trajectory.stream.jsonl"
    trajectory.write_text('{"type":"message","content":"evidence"}\n')
    event_text = indexable_event_contents(trajectory)[1]

    def fake_run(self, task_dir, runs_dir=None, *, paths=None):
        assert paths is not None
        assert self.required_outputs == ("auditor.packet.json",)
        assert "trajectory-auditor agent" in self.prompt
        assert "trace.md" in self.prompt
        prompt = (task_dir / "instruction.md").read_text()
        assert "Prompt contract: trajectory-frontier-auditor-v3" in prompt
        assert "<task_instruction>\nTASK\n</task_instruction>" in prompt
        assert "potential_concern" in prompt
        assert "Never propose criterion wording, weights, edits" in prompt
        assert "judge reasoning" in prompt
        assert "reward-hacking detector" in prompt
        assert "<current_rubric>" not in prompt
        assert paths.output_schema_path is not None
        schema = json.loads(paths.output_schema_path.read_text())
        assert schema["properties"]["findings"]["items"]["properties"][
            "kind"
        ]["enum"] == ["supported_problem", "potential_concern"]
        assert "text" not in schema["$defs"]["snippet"]["properties"]
        TaskWorkspace(task_dir, paths.workspace_dir).create()
        artifacts = paths.workspace_dir / "artifacts"
        artifacts.mkdir()
        # A query can fail after consuming budget but before appending an audit
        # row. Successful audit rows are the only downstream count source.
        (artifacts / "query-count.txt").write_text("2")
        (artifacts / "query-audit.jsonl").write_text('{"event_ids":[1]}\n')
        assert paths.output_last_message_path is not None
        paths.output_last_message_path.write_text(_packet(event_text))
        paths.stream_path.parent.mkdir(parents=True, exist_ok=True)
        paths.stream_path.write_text("")
        return 0, paths

    monkeypatch.setattr(evolution_module.AgentRunner, "run", fake_run)
    output = _evolver()._run_trajectory_auditor(
        trajectory_path=trajectory,
        task_instruction="TASK",
        score_context=_score_context(),
        repair_error=None,
        rejected_packet=None,
    )

    assert json.loads(output.packet_text)["findings"][0]["kind"] == (
        "supported_problem"
    )
    assert output.query_count == 1
    assert output.retrieved_event_ids == (1,)


def test_codex_auditor_rejects_missing_query_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trajectory = tmp_path / "trajectory.stream.jsonl"
    trajectory.write_text('{"type":"message","content":"evidence"}\n')
    event_text = indexable_event_contents(trajectory)[1]

    def fake_run(self, task_dir, runs_dir=None, *, paths=None):
        assert paths is not None
        TaskWorkspace(task_dir, paths.workspace_dir).create()
        (paths.workspace_dir / "artifacts").mkdir()
        assert paths.output_last_message_path is not None
        paths.output_last_message_path.write_text(_packet(event_text))
        paths.stream_path.parent.mkdir(parents=True, exist_ok=True)
        paths.stream_path.write_text("")
        return 0, paths

    monkeypatch.setattr(evolution_module.AgentRunner, "run", fake_run)
    with pytest.raises(RuntimeError, match="auditor query audit is missing"):
        _evolver()._run_trajectory_auditor(
            trajectory_path=trajectory,
            task_instruction="TASK",
            score_context=_score_context(),
            repair_error=None,
            rejected_packet=None,
        )


def test_proposer_prompt_preserves_recursive_cycle_and_has_explicit_context() -> None:
    instructions = evolution_module._proposer_instructions(
        current_rubric=(
            "Criterion 1: Result\nLevels: A=100 B=50 C=0\n"
            "[A]: complete\n[B]: partial\n[C]: missing\n"
        ),
        repair_error=None,
    )
    packet = '{"schema_version":3,"inspected":"x","findings":[]}\n'
    evidence = evolution_module._proposer_evidence(
        instruction="TASK",
        current_rubric="RUBRIC",
        current_submission="SUBMISSION",
        auditor_packet=packet,
        score_context=_score_context(),
        rejected_attempts=(),
    )

    assert "Prompt contract: structured-frontier-rubric-v6" in instructions
    assert "recursive decompose-filter cycle" in instructions
    assert "informative, comprehensive, and non-redundant" in instructions
    assert "Do not reward effort" in instructions
    assert "independently useful but bounded outcome" in instructions
    assert "longer or busier trajectory" in instructions
    assert "structured JSON object" in instructions
    assert "If `saturated` is true" in instructions
    assert "trace.md" not in instructions
    assert "query tool" not in instructions
    assert evidence.count("<task_instruction>") == 1
    assert evidence.count("<current_submission>") == 1
    assert evidence.count("<current_complete_rubric>") == 1
    assert evidence.count("<verified_auditor_packet>") == 1
    assert evidence.count("<validated_score_context>") == 1
    assert "trajectory_path" not in evidence


def test_frontier_retry_prompt_requires_a_distinct_unmet_outcome() -> None:
    error = (
        "candidate rubric did not move the saturated submission below its "
        "frontier: parent score 100, candidate score 100, and 9/9 criteria "
        "selected level A"
    )
    rejected_attempts = ({
        "validation_error": error,
        "structured_proposal": '{"schema_version":1}',
    },)
    instructions = evolution_module._proposer_instructions(
        current_rubric=_current_rubric(),
        repair_error=error,
    )
    evidence = evolution_module._proposer_evidence(
        instruction="TASK",
        current_rubric=_current_rubric(),
        current_submission="SUBMISSION",
        auditor_packet='{"schema_version":3}',
        score_context=_score_context(saturated=True),
        rejected_attempts=rejected_attempts,
    )

    assert "empirical cross-score" in instructions
    assert "different stable, task-valid outcome gap" in instructions
    assert "should score below A" in instructions
    assert "arbitrary busywork" in instructions
    assert "<rejected_structured_proposal_history>" in evidence
    assert error in evidence
    assert '"structured_proposal": "{\\"schema_version\\":1}"' in evidence


def test_direct_proposer_makes_one_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def generate(**kwargs):
        calls.append(kwargs)
        return _proposer_output()

    monkeypatch.setattr(evolution_module, "_generate_structured_rubric", generate)
    output = _evolver()._run_direct_proposer(
        instruction="TASK",
        current_rubric=_current_rubric(),
        current_submission="SUBMISSION",
        auditor_packet='{"schema_version":3}\n',
        score_context=_score_context(),
        repair_error=None,
        rejected_attempts=(),
    )

    assert output.proposal_text == json.dumps(_revised_proposal())
    assert len(calls) == 1
    assert "trajectory" not in calls[0]
    assert "trace" not in calls[0]


def test_openai_proposer_call_returns_structured_proposal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class Responses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(
                status="completed",
                output_text=json.dumps(_revised_proposal()),
                model="gpt-proposer-served",
                id="response-1",
                usage=types.SimpleNamespace(
                    model_dump=lambda: {
                        "input_tokens": 100,
                        "output_tokens": 200,
                        "input_tokens_details": {"cached_tokens": 20},
                    }
                ),
            )

    class OpenAI:
        def __init__(self, **_kwargs):
            self.responses = Responses()

    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=OpenAI))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    output = evolution_module._generate_structured_rubric(
        model="gpt-proposer",
        base_url=None,
        service_tier=None,
        instructions="INSTRUCTIONS",
        evidence="EVIDENCE",
    )

    assert output.proposal_text == json.dumps(_revised_proposal())
    assert len(calls) == 1
    assert calls[0]["text"]["format"]["type"] == "json_schema"
    proposal_schema = calls[0]["text"]["format"]["schema"]
    assert proposal_schema["properties"]["schema_version"]["enum"] == [2]
    assert "maxItems" not in proposal_schema["properties"]["criteria"]
    assert calls[0]["input"][-1] == {"role": "user", "content": "EVIDENCE"}
    assert calls[0]["store"] is False


def test_evolver_seals_verified_packet_complete_rubric_and_diff(
    tmp_path: Path,
) -> None:
    arguments = _arguments(tmp_path)
    event_text = _event_text(arguments)
    auditor_calls: list[dict[str, object]] = []
    proposer_calls: list[dict[str, object]] = []
    evolver = _evolver(
        query_limit=7,
        run_auditor=lambda **kwargs: auditor_calls.append(kwargs)
        or _auditor_output(event_text),
        run_proposer=lambda **kwargs: proposer_calls.append(kwargs)
        or _proposer_output(),
    )

    result = evolver.evolve(**arguments)

    assert auditor_calls == [{
        "trajectory_path": arguments["trajectory_path"],
        "task_instruction": "TASK",
        "score_context": arguments["score_context"],
        "repair_error": None,
        "rejected_packet": None,
    }]
    assert len(proposer_calls) == 1
    assert set(proposer_calls[0]) == {
        "instruction",
        "current_rubric",
        "current_submission",
        "auditor_packet",
        "score_context",
        "repair_error",
        "rejected_attempts",
    }
    assert "trajectory_path" not in proposer_calls[0]
    output_dir = arguments["output_dir"]
    assert isinstance(output_dir, Path)
    paths = (
        output_dir / "r0001.txt",
        output_dir / "r0001.proposer.json",
        output_dir / "r0001.auditor.json",
        output_dir / "r0001.proposal.json",
        output_dir / "r0001.diff",
    )
    assert all(path.is_file() and not path.stat().st_mode & 0o222 for path in paths)
    assert not (output_dir / "r0001.proposer.trace.md").exists()
    metadata = json.loads((output_dir / "r0001.proposer.json").read_text())
    packet_text = (output_dir / "r0001.auditor.json").read_text()
    assert metadata["mode"] == "prospective"
    assert metadata["schema_version"] == 7
    assert metadata["kind"] == "audited-complete-rubric-generation"
    assert metadata["auditor"]["model"] == "auditor-model"
    assert metadata["auditor"]["prompt_version"] == (
        "trajectory-frontier-auditor-v3"
    )
    assert metadata["auditor"]["query_count"] == 2
    assert metadata["auditor"]["retrieved_event_ids"] == [1]
    assert metadata["auditor"]["repair_error"] is None
    assert metadata["auditor"]["rejected_packet"] is None
    assert metadata["auditor_packet_sha256"] == sha256_text(packet_text)
    assert metadata["proposer"]["model"] == "proposer-model"
    assert metadata["proposer"]["prompt_version"] == (
        "structured-frontier-rubric-v6"
    )
    assert metadata["proposer"]["output_schema_version"] == 2
    assert metadata["proposer"]["repair_error"] is None
    assert metadata["proposer"]["rejected_attempts"] == []
    assert metadata["attempt_count"] == 1
    assert metadata["proposer_attempts"][0]["cost"][
        "estimated_cost_usd"
    ] == 0.01
    assert metadata["source_submission_id"] == "s000"
    assert metadata["parent_criterion_count"] == 1
    assert metadata["criterion_count"] == 2
    assert metadata["rubric_changed"] is True
    assert metadata["proposal_decision"] == "revise"
    assert metadata["candidate_cross_score"]["candidate_score"] == 45
    assert metadata["rubric_sha256"] == result.sha256
    assert result.text == _rendered(_revised_proposal())
    assert json.loads(packet_text)["findings"][0]["evidence"][0]["text"] == (
        "evidence"
    )
    diff = (output_dir / "r0001.diff").read_text()
    assert "-Criterion 1: Scientific validity" in diff
    assert "+Criterion 1: Data preparation integrity" in diff
    assert evolver.evolve(**arguments) == result
    assert len(auditor_calls) == len(proposer_calls) == 1


def test_evolver_accepts_full_replacement_rubric(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    event_text = _event_text(arguments)
    result = _evolver(
        run_auditor=lambda **_: _auditor_output(event_text),
        run_proposer=lambda **_: _proposer_output(_replacement_proposal()),
    ).evolve(**arguments)

    assert result.text == _rendered(_replacement_proposal())
    assert "Scientific validity" not in result.text
    assert result.metadata["criterion_count"] == 1


def test_evolver_rejects_unsupported_auditor() -> None:
    with pytest.raises(ValueError, match="trajectory auditor"):
        _evolver(auditor=AgentRunConfig(provider="gemini", model="gemini-model"))


def test_evolver_accepts_vllm_auditor_and_proposer() -> None:
    evolver = _evolver(
        auditor=AgentRunConfig(
            provider="vllm",
            model="Qwen/Auditor",
            base_url="http://auditor:43117/v1",
        ),
        proposer_model="Qwen/Proposer",
        proposer_base_url="http://proposer:43117/v1",
    )
    assert evolver.auditor.provider == "vllm"
    assert evolver._proposer_identity(
        "Criterion 1: Result\nLevels: A=100 B=50 C=0\n",
        instruction="TASK",
        current_submission="SUBMISSION",
        auditor_packet="{}",
        score_context=_score_context(),
        repair_error=None,
        rejected_attempts=(),
    )["provider"] == "vllm"


def test_evolver_reuses_packet_when_retrying_invalid_rubric(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    event_text = _event_text(arguments)
    malformed = _revised_proposal()
    malformed["criteria"][0]["levels"][2]["points"] = 35  # type: ignore[index]
    responses = iter((malformed, _revised_proposal()))
    auditor_calls = 0
    proposer_calls: list[dict[str, object]] = []

    def audit(**_kwargs):
        nonlocal auditor_calls
        auditor_calls += 1
        return _auditor_output(event_text)

    evolver = _evolver(
        run_auditor=audit,
        run_proposer=lambda **kwargs: proposer_calls.append(kwargs)
        or _proposer_output(next(responses)),
    )
    result = evolver.evolve(**arguments)

    assert result.text == _rendered(_revised_proposal())
    assert auditor_calls == 1
    assert len(proposer_calls) == 2
    assert proposer_calls[0]["auditor_packet"] == proposer_calls[1][
        "auditor_packet"
    ]
    assert "level progression" in str(proposer_calls[1]["repair_error"])
    rejected_attempt = {
        "validation_error": str(proposer_calls[1]["repair_error"]),
        "structured_proposal": json.dumps(malformed),
    }
    assert proposer_calls[1]["rejected_attempts"] == (rejected_attempt,)
    failure_dir = tmp_path / "rubrics" / "r0001.proposer-failures"
    failure = json.loads((failure_dir / "attempt-0001.json").read_text())
    assert failure["evolve_attempt"] == 1
    assert failure["auditor_packet_sha256"] == result.metadata[
        "auditor_packet_sha256"
    ]
    assert (failure_dir / "attempt-0001.txt").read_text() == json.dumps(malformed)
    assert not (failure_dir / "attempt-0001.trace.md").exists()
    proposer_identity = result.metadata["proposer"]
    assert isinstance(proposer_identity, dict)
    assert "level progression" in str(proposer_identity["repair_error"])
    assert proposer_identity["rejected_attempts"] == [rejected_attempt]
    initial_identity = evolver._proposer_identity(
        str(arguments["current_rubric"]),
        instruction=str(arguments["instruction"]),
        current_submission=str(arguments["current_submission"]),
        auditor_packet=str(proposer_calls[0]["auditor_packet"]),
        score_context=arguments["score_context"],  # type: ignore[arg-type]
        repair_error=None,
        rejected_attempts=(),
    )
    assert proposer_identity["prompt_sha256"] != initial_identity["prompt_sha256"]
    assert evolver.evolve(**arguments) == result


def test_evolver_retries_and_archives_an_invalid_auditor_packet(
    tmp_path: Path,
) -> None:
    arguments = _arguments(tmp_path)
    event_text = _event_text(arguments)
    invalid_packet = json.loads(_packet(event_text))
    invalid_packet["findings"][0]["evidence"][0]["event_id"] = 2
    invalid = json.dumps(invalid_packet)
    outputs = iter((
        _auditor_output(event_text, packet_text=invalid),
        _auditor_output(event_text),
    ))
    auditor_calls = 0

    auditor_requests: list[dict[str, object]] = []

    def audit(**kwargs):
        nonlocal auditor_calls
        auditor_calls += 1
        auditor_requests.append(kwargs)
        return next(outputs)

    evolver = _evolver(
        run_auditor=audit,
        run_proposer=lambda **_: _proposer_output(),
    )
    result = evolver.evolve(**arguments)

    assert result.text == _rendered(_revised_proposal())
    assert auditor_calls == 2
    assert "unknown event ID" in str(auditor_requests[1]["repair_error"])
    assert auditor_requests[1]["rejected_packet"] == invalid
    failure_dir = tmp_path / "rubrics" / "r0001.auditor-failures"
    failure = json.loads((failure_dir / "attempt-0001.json").read_text())
    assert failure["evolve_attempt"] == 1
    assert failure["error"] == (
        "trajectory auditor citation has an unknown event ID: 2"
    )
    assert failure["cost"] == _cost()
    assert (failure_dir / "attempt-0001.txt").read_text() == invalid
    auditor_identity = result.metadata["auditor"]
    assert isinstance(auditor_identity, dict)
    assert "unknown event ID" in str(auditor_identity["repair_error"])
    assert auditor_identity["rejected_packet"] == invalid
    initial_identity = evolver._auditor_identity(
        _auditor_output(event_text),
        available_events=1,
        score_context=arguments["score_context"],  # type: ignore[arg-type]
        task_instruction=str(arguments["instruction"]),
        repair_error=None,
        rejected_packet=None,
    )
    assert auditor_identity["prompt_sha256"] != initial_identity["prompt_sha256"]
    assert evolver.evolve(**arguments) == result


def test_evolver_allows_two_auditor_repairs(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    event_text = _event_text(arguments)
    invalid_packet = json.loads(_packet(event_text))
    invalid_packet["findings"][0]["evidence"][0]["event_id"] = 2
    invalid = json.dumps(invalid_packet)
    outputs = iter((
        _auditor_output(event_text, packet_text=invalid),
        _auditor_output(event_text, packet_text=invalid),
        _auditor_output(event_text),
    ))
    requests: list[dict[str, object]] = []

    def audit(**kwargs):
        requests.append(kwargs)
        return next(outputs)

    result = _evolver(
        run_auditor=audit,
        run_proposer=lambda **_: _proposer_output(),
    ).evolve(**arguments)

    assert result.text == _rendered(_revised_proposal())
    assert len(requests) == 3
    assert requests[1]["rejected_packet"] == invalid
    assert requests[2]["rejected_packet"] == invalid
    failure_dir = tmp_path / "rubrics" / "r0001.auditor-failures"
    assert sorted(path.name for path in failure_dir.glob("*.json")) == [
        "attempt-0001.json",
        "attempt-0002.json",
    ]


def test_resume_rejects_different_auditor_or_proposer_identity(
    tmp_path: Path,
) -> None:
    arguments = _arguments(tmp_path)
    event_text = _event_text(arguments)
    _evolver(
        run_auditor=lambda **_: _auditor_output(event_text),
        run_proposer=lambda **_: _proposer_output(),
    ).evolve(**arguments)

    with pytest.raises(RuntimeError, match="invalid evolved rubric"):
        _evolver(
            auditor=_agent(model="different-auditor"),
            run_auditor=lambda **_: _auditor_output(event_text),
            run_proposer=lambda **_: _proposer_output(),
        ).evolve(**arguments)
    with pytest.raises(RuntimeError, match="invalid evolved rubric"):
        _evolver(
            proposer_model="different-proposer",
            run_auditor=lambda **_: _auditor_output(event_text),
            run_proposer=lambda **_: _proposer_output(),
        ).evolve(**arguments)


def test_no_supported_problem_and_unchanged_rubric_are_valid(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    event_text = _event_text(arguments)
    no_problem = _packet(event_text, status="no_supported_problem")
    current_rubric = str(arguments["current_rubric"])
    result = _evolver(
        run_auditor=lambda **_: _auditor_output(
            event_text, packet_text=no_problem
        ),
        run_proposer=lambda **_: _proposer_output(_retain_proposal()),
    ).evolve(**arguments)

    assert result.text == current_rubric
    assert result.changed is False
    assert result.metadata["rubric_changed"] is False
    assert json.loads(
        (tmp_path / "rubrics" / "r0001.auditor.json").read_text()
    )["findings"] == []
    assert (tmp_path / "rubrics" / "r0001.diff").read_text() == ""


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (
            lambda packet: packet["findings"][0]["evidence"][0].update(
                {"text": "hallucinated"}
            ),
            "invalid snippet",
        ),
        (
            lambda packet: packet["findings"][0]["evidence"][0].update(
                {"event_id": 2}
            ),
            "unknown event ID",
        ),
        (
            lambda packet: packet["findings"][0]["evidence"][0].update(
                {"start_offset": -1}
            ),
            "invalid offsets",
        ),
    ),
)
def test_evolver_rejects_invalid_citation_references(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    arguments = _arguments(tmp_path)
    event_text = _event_text(arguments)
    packet = json.loads(_packet(event_text))
    mutate(packet)
    evolver = _evolver(
        run_auditor=lambda **_: _auditor_output(
            event_text, packet_text=json.dumps(packet)
        ),
        run_proposer=lambda **_: _proposer_output(),
    )

    with pytest.raises(ValueError, match=message):
        evolver.evolve(**arguments)


def test_evolver_rejects_snippet_from_event_not_retrieved(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    trajectory = arguments["trajectory_path"]
    assert isinstance(trajectory, Path)
    trajectory.write_text(
        '{"type":"message","content":"evidence"}\n'
        '{"type":"message","content":"other"}\n'
    )
    event_text = _event_text(arguments)
    evolver = _evolver(
        run_auditor=lambda **_: _auditor_output(
            event_text, events=(2,)
        ),
        run_proposer=lambda **_: _proposer_output(),
    )

    with pytest.raises(
        ValueError,
        match="cited event 1 that it did not retrieve in this attempt",
    ):
        evolver.evolve(**arguments)


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (
            lambda proposal: proposal["criteria"][1].update(  # type: ignore[index]
                {"title": "Data preparation integrity"}
            ),
            "duplicate criterion titles",
        ),
        (
            lambda proposal: proposal["criteria"][1]["levels"][1].update(  # type: ignore[index]
                {"label": "D"}
            ),
            "invalid level progression",
        ),
        (
            lambda proposal: proposal["criteria"][1]["levels"][1].update(  # type: ignore[index]
                {"description": ""}
            ),
            "invalid level",
        ),
        (
            lambda proposal: proposal["criteria"][1]["levels"][0].update(  # type: ignore[index]
                {"points": 24}
            ),
            (
                "A-level points must sum to 100; the proposed sum is 99, "
                "so increase it by 1"
            ),
        ),
        (
            lambda proposal: proposal["challenge_changes"][0].update(  # type: ignore[index]
                {"finding_ids": ["F9"]}
            ),
            "does not cite valid frontier findings",
        ),
    ),
)
def test_evolver_rejects_invalid_structured_rubric_proposal(
    tmp_path: Path,
    mutate,
    message: str,
) -> None:
    arguments = _arguments(tmp_path)
    event_text = _event_text(arguments)
    proposal = _revised_proposal()
    mutate(proposal)
    evolver = _evolver(
        max_retries=0,
        run_auditor=lambda **_: _auditor_output(event_text),
        run_proposer=lambda **_: _proposer_output(proposal),
    )

    with pytest.raises(RuntimeError, match=message):
        evolver.evolve(**arguments)


def test_resume_rejects_tampered_rubric_diff(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    event_text = _event_text(arguments)
    evolver = _evolver(
        run_auditor=lambda **_: _auditor_output(event_text),
        run_proposer=lambda **_: _proposer_output(),
    )
    evolver.evolve(**arguments)
    diff_path = tmp_path / "rubrics" / "r0001.diff"
    diff_path.chmod(0o644)
    diff_path.write_text("tampered\n")

    with pytest.raises(RuntimeError, match="invalid evolved rubric"):
        evolver.evolve(**arguments)


def test_resume_rejects_candidate_score_that_differs_from_judge_artifacts(
    tmp_path: Path,
) -> None:
    arguments = _arguments(tmp_path)
    event_text = _event_text(arguments)
    evolver = _evolver(
        run_auditor=lambda **_: _auditor_output(event_text),
        run_proposer=lambda **_: _proposer_output(),
    )
    evolver.evolve(**arguments)
    metadata_path = tmp_path / "rubrics" / "r0001.proposer.json"
    metadata_path.chmod(0o644)
    metadata = json.loads(metadata_path.read_text())
    metadata["candidate_cross_score"]["candidate_score"] = 44
    metadata_path.write_text(json.dumps(metadata) + "\n")

    with pytest.raises(RuntimeError, match="invalid evolved rubric"):
        evolver.evolve(**arguments)


def test_resume_rejects_tampered_auditor_packet(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    event_text = _event_text(arguments)
    evolver = _evolver(
        run_auditor=lambda **_: _auditor_output(event_text),
        run_proposer=lambda **_: _proposer_output(),
    )
    evolver.evolve(**arguments)
    packet_path = tmp_path / "rubrics" / "r0001.auditor.json"
    packet_path.chmod(0o644)
    packet = json.loads(packet_path.read_text())
    packet["findings"][0]["evidence"][0]["text"] = "hallucinated"
    packet_path.write_text(json.dumps(packet) + "\n")

    with pytest.raises(RuntimeError, match="invalid evolved rubric"):
        evolver.evolve(**arguments)


def test_speculative_auditor_concern_can_have_no_citation(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    event_text = _event_text(arguments)
    packet = json.loads(_packet(event_text))
    finding = packet["findings"][0]
    finding["kind"] = "potential_concern"
    finding["hypothesis"] = "The result may depend on an untested assumption."
    finding["basis"] = "The task requires a robust scientific conclusion."
    finding["evidence"] = []
    finding["uncertainty"] = "The bounded trace does not establish the assumption."
    finding["verification_question"] = "Does the result survive assumption checks?"

    result = _evolver(
        run_auditor=lambda **_: _auditor_output(
            event_text,
            packet_text=json.dumps(packet),
        ),
        run_proposer=lambda **_: _proposer_output(),
    ).evolve(**arguments)

    sealed = json.loads(
        (tmp_path / "rubrics" / "r0001.auditor.json").read_text()
    )
    assert sealed["findings"][0]["kind"] == "potential_concern"
    assert sealed["findings"][0]["evidence"] == []
    assert result.changed is True


def test_saturated_score_requires_at_least_one_frontier_finding(
    tmp_path: Path,
) -> None:
    arguments = _arguments(tmp_path, saturated=True)
    event_text = _event_text(arguments)
    empty_packet = _packet(event_text, status="no_supported_problem")

    with pytest.raises(ValueError, match="invalid findings"):
        _evolver(
            run_auditor=lambda **_: _auditor_output(
                event_text,
                packet_text=empty_packet,
            ),
            run_proposer=lambda **_: _proposer_output(),
        ).evolve(**arguments)


def test_structured_proposal_accepts_more_than_26_criteria() -> None:
    proposal = _revised_proposal()
    criteria: list[dict[str, object]] = []
    for index in range(1, 71):
        maximum = 2 if index <= 30 else 1
        criteria.append({
            "title": f"Quality dimension {index}",
            "description": f"Observable task quality dimension {index}.",
            "levels": [
                {
                    "label": "A",
                    "points": maximum,
                    "description": "The outcome is fully established.",
                },
                {
                    "label": "B",
                    "points": maximum - 1,
                    "description": "The outcome is established with a boundary.",
                },
                {
                    "label": "C",
                    "points": maximum - 2,
                    "description": "The outcome is not established.",
                },
            ],
        })
    proposal["criteria"] = criteria
    proposal["challenge_changes"][0]["criterion_title"] = (  # type: ignore[index]
        "Quality dimension 1"
    )

    validated, _ = evolution_module._validated_structured_proposal(
        json.dumps(proposal),
        current_rubric=_current_rubric(),
        packet_text='{"schema_version":3,"inspected":"x","findings":['
        '{"finding_id":"F1"}]}',
        saturated=False,
    )

    assert len(validated["criteria"]) == 70


def test_saturated_score_rejects_retained_rubric(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path, saturated=True)
    event_text = _event_text(arguments)

    with pytest.raises(RuntimeError, match="saturated score requires"):
        _evolver(
            max_retries=0,
            run_auditor=lambda **_: _auditor_output(event_text),
            run_proposer=lambda **_: _proposer_output(_retain_proposal()),
        ).evolve(**arguments)


def test_saturated_score_rejects_candidate_that_stays_at_ceiling(
    tmp_path: Path,
) -> None:
    arguments = _arguments(tmp_path, saturated=True)
    event_text = _event_text(arguments)

    def saturated_gate(text: str, _attempt: int) -> dict[str, object]:
        return {
            "parent_score": 100,
            "candidate_score": 100,
            "raw_score": 100,
            "selected_levels": {"criterion_1": "A", "criterion_2": "A"},
            "criterion_scores": {"criterion_1": 75, "criterion_2": 25},
            "rubric_sha256": sha256_text(text),
            "attempt_id": "b" * 32,
        }

    arguments["candidate_gate"] = saturated_gate
    with pytest.raises(
        RuntimeError,
        match=(
            "did not move the saturated submission below its frontier: "
            "parent score 100, candidate score 100, and 2/2 criteria selected level A"
        ),
    ):
        _evolver(
            max_retries=0,
            run_auditor=lambda **_: _auditor_output(event_text),
            run_proposer=lambda **_: _proposer_output(),
        ).evolve(**arguments)


def test_saturated_cross_score_retry_receives_frontier_failure(
    tmp_path: Path,
) -> None:
    arguments = _arguments(tmp_path, saturated=True)
    event_text = _event_text(arguments)
    proposer_calls: list[dict[str, object]] = []

    def candidate_gate(text: str, attempt: int) -> dict[str, object]:
        levels = parse_rubric_levels_strict(text)
        selected = "A" if attempt < 3 else "B"
        selected_levels = {key: selected for key in levels}
        criterion_scores = {
            key: criterion[selected] for key, criterion in levels.items()
        }
        raw_score = sum(criterion_scores.values())
        return {
            "parent_score": 100,
            "candidate_score": raw_score,
            "raw_score": raw_score,
            "selected_levels": selected_levels,
            "criterion_scores": criterion_scores,
            "rubric_sha256": sha256_text(text),
            "attempt_id": f"{attempt:032x}",
        }

    proposals = iter((
        _revised_proposal(),
        _replacement_proposal(),
        _revised_proposal(),
    ))
    arguments["candidate_gate"] = candidate_gate
    arguments["candidate_validator"] = (
        lambda text, attempt_id: candidate_gate(text, int(attempt_id, 16))
    )
    evolver = _evolver(
        run_auditor=lambda **_: _auditor_output(event_text),
        run_proposer=lambda **kwargs: proposer_calls.append(kwargs)
        or _proposer_output(next(proposals)),
    )
    result = evolver.evolve(**arguments)

    assert result.text == _rendered(_revised_proposal())
    assert len(proposer_calls) == 3
    assert proposer_calls[0]["repair_error"] is None
    assert proposer_calls[0]["rejected_attempts"] == ()
    assert (
        "parent score 100, candidate score 100, and 2/2 criteria selected level A"
        in str(proposer_calls[1]["repair_error"])
    )
    first_rejected = proposer_calls[1]["rejected_attempts"]
    assert isinstance(first_rejected, tuple) and len(first_rejected) == 1
    assert first_rejected[0]["structured_proposal"] == json.dumps(
        _revised_proposal()
    )
    rejected_history = proposer_calls[2]["rejected_attempts"]
    assert isinstance(rejected_history, tuple) and len(rejected_history) == 2
    assert [attempt["structured_proposal"] for attempt in rejected_history] == [
        json.dumps(_revised_proposal()),
        json.dumps(_replacement_proposal()),
    ]
    assert "2/2 criteria selected level A" in rejected_history[0][
        "validation_error"
    ]
    assert "1/1 criteria selected level A" in rejected_history[1][
        "validation_error"
    ]
    proposer_identity = result.metadata["proposer"]
    assert isinstance(proposer_identity, dict)
    assert proposer_identity["rejected_attempts"] == list(rejected_history)
    assert evolver.evolve(**arguments) == result


def test_auditor_packet_rejects_duplicate_evidence_and_counterevidence(
    tmp_path: Path,
) -> None:
    arguments = _arguments(tmp_path)
    event_text = _event_text(arguments)
    packet = json.loads(_packet(event_text))
    packet["findings"][0]["counterevidence"] = [
        dict(packet["findings"][0]["evidence"][0])
    ]

    with pytest.raises(ValueError, match="repeats a snippet"):
        _evolver(
            run_auditor=lambda **_: _auditor_output(
                event_text,
                packet_text=json.dumps(packet),
            ),
            run_proposer=lambda **_: _proposer_output(),
        ).evolve(**arguments)
