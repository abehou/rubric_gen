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


def _response() -> str:
    return json.dumps({
        "action": "add_process_criterion",
        "criterion_text": (
            "Criterion 1: Executed-result provenance\n"
            "Levels: A=0 B=-5 C=-10\n"
            "[A]: Every central numerical claim is linked to a successful execution "
            "event and a generated artifact whose contents agree with the answer. "
            "The provenance remains valid under paraphrasing and artifact renaming.\n"
            "[B]: The main analysis ran, but one secondary claim lacks a complete "
            "execution or artifact link.\n"
            "[C]: A central result is unsupported, contradicted by execution, copied "
            "from evaluator feedback, or presented after the producing command failed."
        ),
        "change_summary": "Added an error-sensitive validity criterion.",
        "failure_evidence": ["trajectory:event-1 shows an unsupported claim."],
        "generalization_rationale": "Unsupported claims can occur in any solution.",
        "validation_plan": (
            "Confirm a valid executed solution receives A and inject a failed command "
            "followed by a copied result to confirm it receives C."
        ),
    })


def _agent(*, retries: int = 1) -> AgentRunConfig:
    return AgentRunConfig(provider="codex", model="proposer-model", retries=retries)


def _output(
    answer: str | None = None,
    *,
    queries: int = 2,
    events: tuple[int, ...] = (1,),
) -> ProposerOutput:
    return ProposerOutput(
        answer=answer or _response(),
        trace="Investigated trajectory:event-1 and generalized the failure.\n",
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
        "current_rubric": (
            "Criterion 1: Scientific validity\n"
            "Levels: A=100 B=50 C=0\n"
            "[A]: Fully valid.\n[B]: Partly valid.\n[C]: Invalid.\n"
        ),
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


def test_codex_proposer_leaves_workspace_creation_to_agent_runner(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    trajectory = tmp_path / "trajectory.stream.jsonl"
    trajectory.write_text('{"type":"message","content":"evidence"}\n')

    def fake_run(self, task_dir, runs_dir=None, *, paths=None):
        assert paths is not None
        assert not paths.workspace_dir.exists()
        TaskWorkspace(task_dir, paths.workspace_dir).create()
        assert paths.output_schema_path == (
            paths.workspace_dir / "data" / "proposal.schema.json"
        )
        assert paths.output_last_message_path == paths.workspace_dir / "answer.txt"
        schema = json.loads(paths.output_schema_path.read_text())
        assert schema["properties"]["action"]["enum"] == [
            "add_process_criterion",
            "no_patch",
        ]
        artifacts = paths.workspace_dir / "artifacts"
        artifacts.mkdir()
        (artifacts / "query-count.txt").write_text("1")
        (artifacts / "query-audit.jsonl").write_text('{"event_ids":[1]}\n')
        (paths.workspace_dir / "answer.txt").write_text(_response())
        (paths.workspace_dir / "trace.md").write_text("checked event 1\n")
        paths.stream_path.parent.mkdir(parents=True, exist_ok=True)
        paths.stream_path.write_text("")
        return 0, paths

    monkeypatch.setattr(evolution_module.AgentRunner, "run", fake_run)
    output = RubricEvolver(agent=_agent(), query_limit=3)._run_codex_proposer(
        instruction="TASK",
        current_rubric="RUBRIC",
        answer="ANSWER",
        trace="TRACE",
        trajectory_path=trajectory,
        evaluation={"score": 0},
        repair_error=None,
    )

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
        (paths.workspace_dir / "answer.txt").write_text(_response())
        (paths.workspace_dir / "trace.md").write_text("claimed query\n")
        paths.stream_path.parent.mkdir(parents=True, exist_ok=True)
        paths.stream_path.write_text("")
        return 0, paths

    monkeypatch.setattr(evolution_module.AgentRunner, "run", fake_run)
    with pytest.raises(RuntimeError, match="trajectory query audit is missing"):
        RubricEvolver(agent=_agent(), query_limit=3)._run_codex_proposer(
            instruction="TASK",
            current_rubric="RUBRIC",
            answer="ANSWER",
            trace="TRACE",
            trajectory_path=trajectory,
            evaluation={"score": 0},
            repair_error=None,
        )


def test_evolver_runs_separate_codex_proposer_and_seals_version(tmp_path: Path) -> None:
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
    assert not (output_dir / "r0001.txt").stat().st_mode & 0o222
    proposal = json.loads((output_dir / "r0001.proposal.json").read_text())
    assert proposal["mode"] == "prospective"
    assert proposal["schema_version"] == 6
    assert proposal["proposer_attempt_costs"][0]["estimated_cost_usd"] == 0.01
    assert proposal["source_submission_id"] == "s000"
    assert proposal["kind"] == "optimizer-process-rubric-patch"
    assert proposal["action"] == "add_process_criterion"
    assert proposal["provider"] == "codex"
    assert proposal["model"] == "proposer-model"
    assert proposal["query_limit"] == 7
    assert proposal["trajectory_query_count"] == 2
    assert proposal["available_trajectory_events"] == 1
    assert proposal["retrieved_trajectory_events"] == [1]
    assert (output_dir / "r0001.proposer.trace.md").is_file()
    assert proposal["rubric_sha256"] == result.sha256
    assert "Criterion 1: Scientific validity" in result.text
    assert "Criterion 2: Executed-result provenance" in result.text
    assert evolver.evolve(**arguments) == result
    assert len(calls) == 1


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


def test_evolver_retries_strict_format_failure(tmp_path: Path) -> None:
    malformed = json.loads(_response())
    malformed["criterion_text"] = malformed["criterion_text"].replace(
        "Levels: A=0 B=-5 C=-10", "[A=0]:"
    )
    responses = iter((json.dumps(malformed), _response()))
    calls: list[dict[str, object]] = []
    evolver = RubricEvolver(
        agent=_agent(),
        query_limit=3,
        max_retries=2,
        run_proposer=lambda **kwargs: calls.append(kwargs) or _output(next(responses)),
    )

    result = evolver.evolve(**_arguments(tmp_path))

    assert "Levels: A=0 B=-5 C=-10" in result.text
    assert len(calls) == 2
    assert "must contain exactly one Levels line" in str(calls[1]["repair_error"])
    stored = json.loads(
        (tmp_path / "rubrics" / "r0001.proposal.json").read_text()
    )
    assert stored["attempt_count"] == 2
    failure_dir = tmp_path / "rubrics" / "r0001.proposer-failures"
    failure = json.loads((failure_dir / "attempt-0001.json").read_text())
    assert failure["evolve_attempt"] == 1
    assert "must contain exactly one Levels line" in failure["error"]
    assert (failure_dir / "attempt-0001.answer.txt").is_file()
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


def test_evolver_accepts_grounded_no_patch(tmp_path: Path) -> None:
    response = json.dumps({
        "action": "no_patch",
        "criterion_text": "",
        "change_summary": "No new generalizable process failure was established.",
        "failure_evidence": [],
        "generalization_rationale": "The existing rubric already covers the evidence.",
        "validation_plan": "Retain the current rubric unchanged.",
    })
    arguments = _arguments(tmp_path)
    result = RubricEvolver(
        agent=_agent(), query_limit=3,
        run_proposer=lambda **_: _output(response),
    ).evolve(**arguments)

    assert result.text == arguments["current_rubric"]
    assert result.proposal["action"] == "no_patch"


def test_evolver_retries_no_patch_without_trajectory_evidence(tmp_path: Path) -> None:
    no_patch = json.dumps({
        "action": "no_patch",
        "criterion_text": "",
        "change_summary": "No new generalizable process failure was established.",
        "failure_evidence": [],
        "generalization_rationale": "The existing rubric already covers the evidence.",
        "validation_plan": "Retain the current rubric unchanged.",
    })
    outputs = iter((
        _output(no_patch, queries=0, events=()),
        _output(no_patch),
    ))
    calls: list[dict[str, object]] = []
    arguments = _arguments(tmp_path)
    result = RubricEvolver(
        agent=_agent(),
        query_limit=3,
        run_proposer=lambda **kwargs: calls.append(kwargs) or next(outputs),
    ).evolve(**arguments)

    assert result.proposal["action"] == "no_patch"
    assert len(calls) == 2
    assert "must retrieve at least one trajectory event" in str(
        calls[1]["repair_error"]
    )


def test_evolver_rejects_unavailable_trajectory_reference(tmp_path: Path) -> None:
    proposal = json.loads(_response())
    proposal["failure_evidence"] = ["trajectory:event-999 was not retrieved."]
    evolver = RubricEvolver(
        agent=_agent(retries=0), query_limit=3, max_retries=0,
        run_proposer=lambda **_: _output(json.dumps(proposal)),
    )

    with pytest.raises(RuntimeError, match="unavailable trajectory event"):
        evolver.evolve(**_arguments(tmp_path))


def test_evolver_rejects_proposer_contract_contamination(tmp_path: Path) -> None:
    proposal = json.loads(_response())
    proposal["criterion_text"] = proposal["criterion_text"].replace(
        "Every central numerical claim",
        "The answer must contain rubric_text; every central numerical claim",
    )
    evolver = RubricEvolver(
        agent=_agent(retries=0), query_limit=3, max_retries=0,
        run_proposer=lambda **_: _output(json.dumps(proposal)),
    )

    with pytest.raises(RuntimeError, match="leaks the rubric proposer contract"):
        evolver.evolve(**_arguments(tmp_path))


def test_evolver_rejects_duplicate_criterion_title(tmp_path: Path) -> None:
    proposal = json.loads(_response())
    arguments = _arguments(tmp_path)
    arguments["current_rubric"] = (
        str(arguments["current_rubric"])
        + "\nCriterion 2: Executed-result provenance\n"
        + "Levels: A=0 B=-5 C=-10\n"
        + "[A]: All claims have complete execution provenance.\n"
        + "[B]: A secondary claim has incomplete provenance.\n"
        + "[C]: A central claim has no valid execution provenance.\n"
    )
    evolver = RubricEvolver(
        agent=_agent(retries=0), query_limit=3, max_retries=0,
        run_proposer=lambda **_: _output(json.dumps(proposal)),
    )

    with pytest.raises(RuntimeError, match="duplicates an existing criterion title"):
        evolver.evolve(**arguments)
