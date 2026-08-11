from __future__ import annotations

import errno
import json
import subprocess
import sys
from pathlib import Path

import pytest

from rubric_gen.biomnibench.agent.models import AgentRunConfig
from rubric_gen.biomnibench.agent.workspaces import TaskWorkspace
from rubric_gen.biomnibench.forensics.evidence_index import (
    build_evidence_index,
    write_query_tool,
)
import rubric_gen.biomnibench.revision.evolution as evolution_module
from rubric_gen.biomnibench.revision.evolution import ProposerOutput, RubricEvolver


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
        "[B]: The main transformation is executed, but one material choice is weakly "
        "justified or incompletely traceable.\n"
        "[C]: A central transformation is missing, contradicted, or only asserted.\n\n"
        "Criterion 2: Independent result validation\n"
        "Levels: A=25 B=10 C=0\n"
        "[A]: An independent check reproduces the central result and any discrepancy "
        "is resolved in the conclusion.\n"
        "[B]: A relevant check is executed but incomplete or leaves a material "
        "discrepancy unresolved.\n"
        "[C]: No relevant check is executed, or the claimed check lacks supporting "
        "evidence.\n"
    )


def _replacement_rubric() -> str:
    return (
        "Criterion 1: Reproducible task completion\n"
        "Levels: A=100 B=40 C=0\n"
        "[A]: The required analysis is executed and independently reproducible from "
        "the task data and persisted artifacts.\n"
        "[B]: The central analysis is executed but has a material reproducibility gap.\n"
        "[C]: The central analysis is missing, invalid, or supported only by prose.\n"
    )


def _agent(*, retries: int = 1) -> AgentRunConfig:
    return AgentRunConfig(provider="codex", model="proposer-model", retries=retries)


def _output(
    rubric_text: str | None = None,
    *,
    trace: str = "Investigated trajectory:event-1 and audited the complete set.\n",
    queries: int = 2,
    events: tuple[int, ...] = (1,),
) -> ProposerOutput:
    return ProposerOutput(
        rubric_text=rubric_text or _revised_rubric(),
        trace=trace,
        query_count=queries,
        retrieved_event_ids=events,
        cost={
            "cost_usd": None,
            "estimated_cost_usd": 0.01,
            "cost_source": "test-estimate",
        },
    )


def _arguments(tmp_path: Path) -> dict[str, object]:
    trajectory = tmp_path / "trajectory.stream.jsonl"
    trajectory.write_text('{"type":"message","content":"evidence"}\n')
    return {
        "instruction": "TASK",
        "current_rubric": _current_rubric(),
        "answer": "ANSWER",
        "trace": "TRACE-EVIDENCE",
        "trajectory_path": trajectory,
        "evaluation": {"score": 1},
        "version": 1,
        "source_submission_id": "s000",
        "output_dir": tmp_path / "rubrics",
    }


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
    assert not (relocated_data / counter.name).exists()
    assert not (relocated_data / audit.name).exists()


def test_codex_proposer_uses_unstructured_complete_rubric_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trajectory = tmp_path / "trajectory.stream.jsonl"
    trajectory.write_text('{"type":"message","content":"evidence"}\n')

    def fake_run(self, task_dir, runs_dir=None, *, paths=None):
        assert paths is not None
        assert not paths.workspace_dir.exists()
        prompt = (task_dir / "instruction.md").read_text()
        assert "complete optimizer rubric" in prompt
        assert "Prompt contract: complete-rubric-rrd-v1" in prompt
        assert "recursive decompose-filter cycle" in prompt
        assert "informative, comprehensive, and non-redundant" in prompt
        assert "Emphasize process evidence" in prompt
        assert "strong executed solution" in prompt
        TaskWorkspace(task_dir, paths.workspace_dir).create()
        assert paths.output_schema_path is None
        assert paths.output_last_message_path == paths.workspace_dir / "answer.txt"
        artifacts = paths.workspace_dir / "artifacts"
        artifacts.mkdir()
        (artifacts / "query-count.txt").write_text("1")
        (artifacts / "query-audit.jsonl").write_text('{"event_ids":[1]}\n')
        (paths.workspace_dir / "answer.txt").write_text(_revised_rubric())
        (paths.workspace_dir / "trace.md").write_text(
            "Audited trajectory:event-1 and decomposed one coarse criterion.\n"
        )
        paths.stream_path.parent.mkdir(parents=True, exist_ok=True)
        paths.stream_path.write_text("")
        return 0, paths

    monkeypatch.setattr(evolution_module.AgentRunner, "run", fake_run)
    output = RubricEvolver(agent=_agent(), query_limit=3)._run_codex_proposer(
        instruction="TASK",
        current_rubric=_current_rubric(),
        answer="ANSWER",
        trace="TRACE",
        trajectory_path=trajectory,
        evaluation={"score": 0},
        repair_error=None,
    )

    assert output.rubric_text == _revised_rubric()
    assert output.query_count == 1
    assert output.retrieved_event_ids == (1,)


def test_codex_proposer_rejects_missing_query_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trajectory = tmp_path / "trajectory.stream.jsonl"
    trajectory.write_text('{"type":"message","content":"evidence"}\n')

    def fake_run(self, task_dir, runs_dir=None, *, paths=None):
        assert paths is not None
        TaskWorkspace(task_dir, paths.workspace_dir).create()
        (paths.workspace_dir / "artifacts").mkdir()
        (paths.workspace_dir / "answer.txt").write_text(_revised_rubric())
        (paths.workspace_dir / "trace.md").write_text(
            "Claimed retrieval of trajectory:event-1.\n"
        )
        paths.stream_path.parent.mkdir(parents=True, exist_ok=True)
        paths.stream_path.write_text("")
        return 0, paths

    monkeypatch.setattr(evolution_module.AgentRunner, "run", fake_run)
    with pytest.raises(RuntimeError, match="trajectory query audit is missing"):
        RubricEvolver(agent=_agent(), query_limit=3)._run_codex_proposer(
            instruction="TASK",
            current_rubric=_current_rubric(),
            answer="ANSWER",
            trace="TRACE",
            trajectory_path=trajectory,
            evaluation={"score": 0},
            repair_error=None,
        )


def test_evolver_seals_complete_rubric_and_derived_diff(tmp_path: Path) -> None:
    calls: list[dict[str, object]] = []
    evolver = RubricEvolver(
        agent=_agent(),
        query_limit=7,
        run_proposer=lambda **kwargs: calls.append(kwargs) or _output(),
    )
    arguments = _arguments(tmp_path)

    result = evolver.evolve(**arguments)

    assert len(calls) == 1
    assert calls[0]["trajectory_path"] == arguments["trajectory_path"]
    output_dir = arguments["output_dir"]
    assert isinstance(output_dir, Path)
    paths = (
        output_dir / "r0001.txt",
        output_dir / "r0001.proposer.json",
        output_dir / "r0001.proposer.trace.md",
        output_dir / "r0001.diff",
    )
    assert all(path.is_file() and not path.stat().st_mode & 0o222 for path in paths)
    assert not (output_dir / "r0001.proposal.json").exists()
    metadata = json.loads((output_dir / "r0001.proposer.json").read_text())
    assert metadata["mode"] == "prospective"
    assert metadata["schema_version"] == 1
    assert metadata["kind"] == "complete-rubric-generation"
    assert metadata["proposer_attempt_costs"][0]["estimated_cost_usd"] == 0.01
    assert metadata["source_submission_id"] == "s000"
    assert metadata["provider"] == "codex"
    assert metadata["model"] == "proposer-model"
    assert metadata["prompt_version"] == "complete-rubric-rrd-v1"
    assert metadata["query_limit"] == 7
    assert metadata["trajectory_query_count"] == 2
    assert metadata["available_trajectory_events"] == 1
    assert metadata["retrieved_trajectory_events"] == [1]
    assert metadata["parent_criterion_count"] == 1
    assert metadata["criterion_count"] == 2
    assert metadata["rubric_changed"] is True
    assert metadata["rubric_sha256"] == result.sha256
    assert result.text == _revised_rubric()
    assert result.changed is True
    assert result.metadata == metadata
    diff = (output_dir / "r0001.diff").read_text()
    assert "-Criterion 1: Scientific validity" in diff
    assert "+Criterion 1: Data preparation integrity" in diff
    assert evolver.evolve(**arguments) == result
    assert len(calls) == 1


def test_evolver_accepts_full_replacement_rubric(tmp_path: Path) -> None:
    result = RubricEvolver(
        agent=_agent(),
        query_limit=3,
        run_proposer=lambda **_: _output(_replacement_rubric()),
    ).evolve(**_arguments(tmp_path))

    assert result.text == _replacement_rubric()
    assert "Scientific validity" not in result.text
    assert result.metadata["criterion_count"] == 1


def test_evolver_rejects_unsupported_proposer() -> None:
    with pytest.raises(ValueError, match="Codex or vLLM"):
        RubricEvolver(
            agent=AgentRunConfig(provider="gemini", model="gemini-model"),
            query_limit=2,
        )


def test_evolver_accepts_vllm_proposer() -> None:
    evolver = RubricEvolver(
        agent=AgentRunConfig(
            provider="vllm",
            model="Qwen/Qwen3.6-27B",
            base_url="http://qwen27:43117/v1",
        ),
        query_limit=2,
        run_proposer=lambda **_: _output(),
    )
    assert evolver.agent.provider == "vllm"


def test_evolver_retries_invalid_complete_rubric(tmp_path: Path) -> None:
    malformed = _revised_rubric().replace(
        "Levels: A=75 B=35 C=0",
        "Levels: A=75 B=35 C=35",
    )
    responses = iter((malformed, _revised_rubric()))
    calls: list[dict[str, object]] = []
    evolver = RubricEvolver(
        agent=_agent(),
        query_limit=3,
        max_retries=2,
        run_proposer=lambda **kwargs: calls.append(kwargs) or _output(next(responses)),
    )

    result = evolver.evolve(**_arguments(tmp_path))

    assert result.text == _revised_rubric()
    assert len(calls) == 2
    assert "strictly descend" in str(calls[1]["repair_error"])
    stored = json.loads(
        (tmp_path / "rubrics" / "r0001.proposer.json").read_text()
    )
    assert stored["attempt_count"] == 2
    failure_dir = tmp_path / "rubrics" / "r0001.proposer-failures"
    failure = json.loads((failure_dir / "attempt-0001.json").read_text())
    assert failure["evolve_attempt"] == 1
    assert "strictly descend" in failure["error"]
    assert (failure_dir / "attempt-0001.answer.txt").read_text() == malformed
    assert (failure_dir / "attempt-0001.trace.md").is_file()


def test_resume_rejects_different_proposer_identity(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    RubricEvolver(
        agent=_agent(), query_limit=3, run_proposer=lambda **_: _output()
    ).evolve(**arguments)

    with pytest.raises(RuntimeError, match="invalid evolved rubric"):
        RubricEvolver(
            agent=AgentRunConfig(provider="codex", model="different"),
            query_limit=3,
            run_proposer=lambda **_: _output(),
        ).evolve(**arguments)


def test_evolver_derives_unchanged_rubric_without_action(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    current_rubric = str(arguments["current_rubric"])
    result = RubricEvolver(
        agent=_agent(),
        query_limit=3,
        run_proposer=lambda **_: _output(current_rubric),
    ).evolve(**arguments)

    assert result.text == current_rubric
    assert result.changed is False
    assert result.metadata["rubric_changed"] is False
    assert "action" not in result.metadata
    assert (tmp_path / "rubrics" / "r0001.diff").read_text() == ""


def test_evolver_retries_unchanged_rubric_without_trajectory_evidence(
    tmp_path: Path,
) -> None:
    arguments = _arguments(tmp_path)
    current_rubric = str(arguments["current_rubric"])
    outputs = iter((
        _output(current_rubric, queries=0, events=()),
        _output(current_rubric),
    ))
    calls: list[dict[str, object]] = []
    result = RubricEvolver(
        agent=_agent(),
        query_limit=3,
        run_proposer=lambda **kwargs: calls.append(kwargs) or next(outputs),
    ).evolve(**arguments)

    assert result.changed is False
    assert len(calls) == 2
    assert "must retrieve at least one trajectory event" in str(
        calls[1]["repair_error"]
    )


def test_evolver_rejects_unavailable_trajectory_reference(tmp_path: Path) -> None:
    evolver = RubricEvolver(
        agent=_agent(retries=0),
        query_limit=3,
        max_retries=0,
        run_proposer=lambda **_: _output(
            trace="Relied on trajectory:event-999.\n",
        ),
    )

    with pytest.raises(RuntimeError, match="unavailable trajectory event"):
        evolver.evolve(**_arguments(tmp_path))


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
            _revised_rubric().replace("[B]: A relevant check", "[D]: A relevant check"),
            "one nonempty description for each level",
        ),
        (
            _revised_rubric().replace("Levels: A=25 B=10 C=0", "Levels: A=24 B=10 C=0"),
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
    evolver = RubricEvolver(
        agent=_agent(retries=0),
        query_limit=3,
        max_retries=0,
        run_proposer=lambda **_: _output(rubric),
    )

    with pytest.raises(RuntimeError, match=message):
        evolver.evolve(**_arguments(tmp_path))


def test_resume_rejects_tampered_rubric_diff(tmp_path: Path) -> None:
    arguments = _arguments(tmp_path)
    RubricEvolver(
        agent=_agent(), query_limit=3, run_proposer=lambda **_: _output()
    ).evolve(**arguments)
    diff_path = tmp_path / "rubrics" / "r0001.diff"
    diff_path.chmod(0o644)
    diff_path.write_text("tampered\n")

    with pytest.raises(RuntimeError, match="invalid evolved rubric"):
        RubricEvolver(
            agent=_agent(), query_limit=3, run_proposer=lambda **_: _output()
        ).evolve(**arguments)
