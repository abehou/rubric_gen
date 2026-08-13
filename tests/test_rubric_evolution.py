from __future__ import annotations

import errno
import json
import subprocess
import sys
import types
from pathlib import Path

import pytest

from rubric_gen.biomnibench.agent.models import AgentRunConfig
from rubric_gen.biomnibench.agent.workspaces import TaskWorkspace
from rubric_gen.biomnibench.forensics.evidence_index import (
    build_evidence_index,
    indexable_event_contents,
    write_query_tool,
)
import rubric_gen.biomnibench.revision.evolution as evolution_module
from rubric_gen.biomnibench.revision.evolution import (
    AuditorOutput,
    ProposerOutput,
    RubricEvolver,
)
from rubric_gen.biomnibench.utils.hashing import sha256_text


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
    problems = []
    if status == "supported_problem":
        problems = [{
            "hypothesis": "The trajectory contains an unsupported result.",
            "evidence": [{
                "event_id": 1,
                "start_offset": start,
                "end_offset": start + len(snippet_text),
                "text": snippet_text,
            }],
        }]
    return json.dumps({
        "schema_version": 1,
        "status": status,
        "inspected": "Inspected the result claim and its stated support.",
        "problems": problems,
        "counterevidence": [],
        "uncertainty": None,
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


def _proposer_output(rubric_text: str | None = None) -> ProposerOutput:
    return ProposerOutput(
        rubric_text=rubric_text or _revised_rubric(),
        cost=_cost(),
        generation=_generation(),
    )


def _arguments(tmp_path: Path) -> dict[str, object]:
    trajectory = tmp_path / "trajectory.stream.jsonl"
    trajectory.write_text('{"type":"message","content":"evidence"}\n')
    return {
        "instruction": "TASK",
        "current_rubric": _current_rubric(),
        "current_submission": "SUBMISSION",
        "trajectory_path": trajectory,
        "version": 1,
        "source_submission_id": "s000",
        "output_dir": tmp_path / "rubrics",
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


def test_codex_auditor_emits_only_a_structured_packet(
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
        assert "Prompt contract: trajectory-evidence-auditor-v1" in prompt
        assert "Do not force a problem" in prompt
        assert "Never propose criterion wording, weights, edits" in prompt
        assert "judge reasoning" in prompt
        assert "reward-hacking detector" in prompt
        assert "<current_rubric>" not in prompt
        assert paths.output_schema_path is not None
        schema = json.loads(paths.output_schema_path.read_text())
        assert schema["properties"]["status"]["enum"] == [
            "no_supported_problem",
            "supported_problem",
        ]
        TaskWorkspace(task_dir, paths.workspace_dir).create()
        artifacts = paths.workspace_dir / "artifacts"
        artifacts.mkdir()
        (artifacts / "query-count.txt").write_text("1")
        (artifacts / "query-audit.jsonl").write_text('{"event_ids":[1]}\n')
        assert paths.output_last_message_path is not None
        paths.output_last_message_path.write_text(_packet(event_text))
        paths.stream_path.parent.mkdir(parents=True, exist_ok=True)
        paths.stream_path.write_text("")
        return 0, paths

    monkeypatch.setattr(evolution_module.AgentRunner, "run", fake_run)
    output = _evolver()._run_trajectory_auditor(trajectory_path=trajectory)

    assert json.loads(output.packet_text)["status"] == "supported_problem"
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
        _evolver()._run_trajectory_auditor(trajectory_path=trajectory)


def test_proposer_prompt_preserves_recursive_cycle_and_has_only_four_inputs() -> None:
    instructions = evolution_module._proposer_instructions(
        current_rubric=(
            "Criterion 1: Result\nLevels: A=100 B=50 C=0\n"
            "[A]: complete\n[B]: partial\n[C]: missing\n"
        ),
        repair_error=None,
    )
    packet = '{"schema_version":1,"status":"no_supported_problem"}\n'
    evidence = evolution_module._proposer_evidence(
        instruction="TASK",
        current_rubric="RUBRIC",
        current_submission="SUBMISSION",
        auditor_packet=packet,
    )

    assert "Prompt contract: audited-complete-rubric-v2" in instructions
    assert "recursive decompose-filter cycle" in instructions
    assert "informative, comprehensive, and non-redundant" in instructions
    assert "Do not reward effort" in instructions
    assert "independently useful but bounded outcome" in instructions
    assert "longer or busier trajectory" in instructions
    assert "Return only the complete rubric" in instructions
    assert "trace.md" not in instructions
    assert "query tool" not in instructions
    assert evidence.count("<task_instruction>") == 1
    assert evidence.count("<current_submission>") == 1
    assert evidence.count("<current_complete_rubric>") == 1
    assert evidence.count("<verified_auditor_packet>") == 1
    assert "trajectory_path" not in evidence


def test_direct_proposer_makes_one_model_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    def generate(**kwargs):
        calls.append(kwargs)
        return _proposer_output()

    monkeypatch.setattr(evolution_module, "_generate_complete_rubric", generate)
    output = _evolver()._run_direct_proposer(
        instruction="TASK",
        current_rubric=_current_rubric(),
        current_submission="SUBMISSION",
        auditor_packet='{"schema_version":1}\n',
        repair_error=None,
    )

    assert output.rubric_text == _revised_rubric()
    assert len(calls) == 1
    assert "trajectory" not in calls[0]
    assert "trace" not in calls[0]


def test_openai_proposer_call_returns_plain_complete_rubric(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class Responses:
        def create(self, **kwargs):
            calls.append(kwargs)
            return types.SimpleNamespace(
                status="completed",
                output_text=_revised_rubric(),
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

    output = evolution_module._generate_complete_rubric(
        model="gpt-proposer",
        base_url=None,
        service_tier=None,
        instructions="INSTRUCTIONS",
        evidence="EVIDENCE",
    )

    assert output.rubric_text == _revised_rubric()
    assert len(calls) == 1
    assert "response_format" not in calls[0]
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

    assert auditor_calls == [{"trajectory_path": arguments["trajectory_path"]}]
    assert len(proposer_calls) == 1
    assert set(proposer_calls[0]) == {
        "instruction",
        "current_rubric",
        "current_submission",
        "auditor_packet",
        "repair_error",
    }
    assert "trajectory_path" not in proposer_calls[0]
    output_dir = arguments["output_dir"]
    assert isinstance(output_dir, Path)
    paths = (
        output_dir / "r0001.txt",
        output_dir / "r0001.proposer.json",
        output_dir / "r0001.auditor.json",
        output_dir / "r0001.diff",
    )
    assert all(path.is_file() and not path.stat().st_mode & 0o222 for path in paths)
    assert not (output_dir / "r0001.proposer.trace.md").exists()
    metadata = json.loads((output_dir / "r0001.proposer.json").read_text())
    packet_text = (output_dir / "r0001.auditor.json").read_text()
    assert metadata["mode"] == "prospective"
    assert metadata["schema_version"] == 4
    assert metadata["kind"] == "audited-complete-rubric-generation"
    assert metadata["auditor"]["model"] == "auditor-model"
    assert metadata["auditor"]["prompt_version"] == (
        "trajectory-evidence-auditor-v1"
    )
    assert metadata["auditor"]["query_count"] == 2
    assert metadata["auditor"]["retrieved_event_ids"] == [1]
    assert metadata["auditor_packet_sha256"] == sha256_text(packet_text)
    assert metadata["proposer"]["model"] == "proposer-model"
    assert metadata["proposer"]["prompt_version"] == (
        "audited-complete-rubric-v2"
    )
    assert metadata["attempt_count"] == 1
    assert metadata["proposer_attempts"][0]["cost"][
        "estimated_cost_usd"
    ] == 0.01
    assert metadata["source_submission_id"] == "s000"
    assert metadata["parent_criterion_count"] == 1
    assert metadata["criterion_count"] == 2
    assert metadata["rubric_changed"] is True
    assert metadata["rubric_sha256"] == result.sha256
    assert result.text == _revised_rubric()
    assert json.loads(packet_text)["problems"][0]["evidence"][0]["text"] == (
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
        run_proposer=lambda **_: _proposer_output(_replacement_rubric()),
    ).evolve(**arguments)

    assert result.text == _replacement_rubric()
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
        "Criterion 1: Result\nLevels: A=100 B=50 C=0\n"
    )["provider"] == "vllm"


def test_evolver_reuses_packet_when_retrying_invalid_rubric(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    event_text = _event_text(arguments)
    malformed = _revised_rubric().replace(
        "Levels: A=75 B=35 C=0",
        "Levels: A=75 B=35 C=35",
    )
    responses = iter((malformed, _revised_rubric()))
    auditor_calls = 0
    proposer_calls: list[dict[str, object]] = []

    def audit(**_kwargs):
        nonlocal auditor_calls
        auditor_calls += 1
        return _auditor_output(event_text)

    result = _evolver(
        run_auditor=audit,
        run_proposer=lambda **kwargs: proposer_calls.append(kwargs)
        or _proposer_output(next(responses)),
    ).evolve(**arguments)

    assert result.text == _revised_rubric()
    assert auditor_calls == 1
    assert len(proposer_calls) == 2
    assert proposer_calls[0]["auditor_packet"] == proposer_calls[1][
        "auditor_packet"
    ]
    assert "strictly descend" in str(proposer_calls[1]["repair_error"])
    failure_dir = tmp_path / "rubrics" / "r0001.proposer-failures"
    failure = json.loads((failure_dir / "attempt-0001.json").read_text())
    assert failure["evolve_attempt"] == 1
    assert failure["auditor_packet_sha256"] == result.metadata[
        "auditor_packet_sha256"
    ]
    assert (failure_dir / "attempt-0001.txt").read_text() == malformed
    assert not (failure_dir / "attempt-0001.trace.md").exists()


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
        run_proposer=lambda **_: _proposer_output(current_rubric),
    ).evolve(**arguments)

    assert result.text == current_rubric
    assert result.changed is False
    assert result.metadata["rubric_changed"] is False
    assert json.loads(
        (tmp_path / "rubrics" / "r0001.auditor.json").read_text()
    )["status"] == "no_supported_problem"
    assert (tmp_path / "rubrics" / "r0001.diff").read_text() == ""


@pytest.mark.parametrize(
    ("mutate", "message"),
    (
        (
            lambda packet: packet["problems"][0]["evidence"][0].update(
                {"text": "hallucinated"}
            ),
            "verbatim event slice",
        ),
        (
            lambda packet: packet["problems"][0]["evidence"][0].update(
                {"event_id": 2}
            ),
            "verbatim event slice",
        ),
        (
            lambda packet: packet["problems"][0]["evidence"][0].update(
                {"start_offset": 0}
            ),
            "verbatim event slice",
        ),
    ),
)
def test_evolver_deterministically_rejects_unverified_snippets(
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
    event_text = _event_text(arguments)
    evolver = _evolver(
        run_auditor=lambda **_: _auditor_output(
            event_text, events=(2,)
        ),
        run_proposer=lambda **_: _proposer_output(),
    )

    with pytest.raises(ValueError, match="retrieval metadata"):
        evolver.evolve(**arguments)


@pytest.mark.parametrize(
    ("rubric", "message"),
    (
        (
            _revised_rubric().replace("Criterion 2:", "Criterion 3:"),
            "criterion numbers must be contiguous",
        ),
        (
            _revised_rubric().replace(
                "Criterion 2: Independent result validation",
                "Criterion 2: Data preparation integrity",
            ),
            "duplicate criterion titles",
        ),
        (
            _revised_rubric().replace(
                "[B]: The central result remains useful",
                "[D]: The central result remains useful",
            ),
            "one nonempty description for each level",
        ),
        (
            _revised_rubric().replace(
                "Levels: A=25 B=10 C=0", "Levels: A=24 B=10 C=0"
            ),
            "A-level points must sum to 100",
        ),
        (
            "```text\n" + _revised_rubric() + "```\n",
            "must not contain Markdown code fences",
        ),
    ),
)
def test_evolver_rejects_invalid_complete_rubric_structure(
    tmp_path: Path,
    rubric: str,
    message: str,
) -> None:
    arguments = _arguments(tmp_path)
    event_text = _event_text(arguments)
    evolver = _evolver(
        max_retries=0,
        run_auditor=lambda **_: _auditor_output(event_text),
        run_proposer=lambda **_: _proposer_output(rubric),
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
    packet["problems"][0]["evidence"][0]["text"] = "hallucinated"
    packet_path.write_text(json.dumps(packet) + "\n")

    with pytest.raises(RuntimeError, match="invalid evolved rubric"):
        evolver.evolve(**arguments)
