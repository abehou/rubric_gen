from __future__ import annotations

import copy
import json
import os
import stat
from pathlib import Path

import pytest

import rubric_gen.submission_revision.seeds as seeds_module
from rubric_gen.cli import build_parser
from rubric_gen.submission_revision.experiment import Experiment
from rubric_gen.submission_revision.judge import JudgeArtifacts
from rubric_gen.submission_revision.seeds import (
    SeedSetConfig,
    SeedSetRunner,
    resolve_seed,
)


EXPERIMENT_ID = "test-experiment"


def _task(root: Path) -> Path:
    task = root / "tasks" / "da-1-1"
    (task / "environment" / "data").mkdir(parents=True)
    (task / "tests").mkdir()
    (task / "instruction.md").write_text("Solve it.\n")
    (task / "environment" / "data" / "x.csv").write_text("x\n1\n")
    (task / "tests" / "rubric.txt").write_text(
        "Criterion 1: Result\nLevels: A=100 B=50 C=0\n"
    )
    return task


def _design(root: Path, task: Path) -> Experiment:
    conditions = [
        {"condition_id": f"{prompt}--{rubric}", "prompt": prompt,
         "rubric_evolution": rubric}
        for prompt in ("base", "anti-rh")
        for rubric in ("static", "prospective")
    ]
    assignments = []
    execution = 0
    for replicate in range(1, 4):
        for within, condition in enumerate(conditions, 1):
            execution += 1
            condition_id = condition["condition_id"]
            assignments.append({
                "assignment_id": f"{task.name}--rep-{replicate:03d}--{condition_id}",
                "task_id": task.name,
                "replicate": replicate,
                "condition_id": condition_id,
                "within_block_order": within,
                "execution_order": execution,
            })
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "benchmark": "biomnibench-da",
        "tasks_dir": str(task.parent.resolve()),
        "tasks": [task.name],
        "randomization": {"seed": 42, "replicates": 3},
        "conditions": conditions,
        "assignments": assignments,
        "protocol": {
            "revision_rounds": 1,
            "feedback_policy": "semi",
            "prompt_control": "base",
            "prompt_treatment": "anti-rh",
            "rubric_control": "static",
            "rubric_treatment": "prospective",
            "solver": {
                "provider": "codex",
                "model": "test-model",
                "reasoning_effort": "minimal",
                "service_tier": None,
                "executable": None,
                "retries": 1,
                "timeout_seconds": 60,
            },
            "judge_model": "test-judge",
            "judge_max_retries": 1,
            "rubric_name": "rubric.txt",
            "review": "trace",
            "max_review_chars": None,
            "rubric_auditor_model": "test-auditor",
            "rubric_auditor_query_limit": 2,
            "rubric_proposer_model": "test-proposer",
            "rubric_proposer_max_retries": 1,
        },
        "outcome_audit": {},
        "dag": {},
    }
    path = (root / "experiment.yaml").resolve()
    path.write_text("{}")
    return Experiment(path, payload)


class FakeAgentRunner:
    calls = 0

    def __init__(self, config, **_kwargs) -> None:
        self.config = config

    def run(self, task_dir: Path, *, paths):
        type(self).calls += 1
        paths.run_dir.mkdir(parents=True)
        paths.workspace_dir.mkdir(parents=True)
        (paths.workspace_dir / "answer.txt").write_text(
            f"answer-{type(self).calls}\n"
        )
        (paths.workspace_dir / "trace.md").write_text("trace\n")
        paths.stream_path.write_text('{"type":"result","status":"success"}\n')
        paths.status_path.write_text(json.dumps({
            "provider": "codex",
            "exit_code": 0,
            "model": "test-model",
            "cost": {"cost_usd": 0.01},
        }))
        return 0, paths


class KilledAgentRunner:
    def __init__(self, config, **_kwargs) -> None:
        self.config = config

    def run(self, task_dir: Path, *, paths):
        paths.run_dir.mkdir(parents=True)
        paths.workspace_dir.mkdir(parents=True)
        paths.prompt_path.write_text("test prompt\n")
        paths.stream_path.write_text('{"type":"turn.started"}\n')
        paths.status_path.write_text(json.dumps({
            "provider": "codex",
            "process_exit_code": -9,
            "exit_code": -9,
        }))
        return -9, paths


def _fake_judge(self, task_dir: Path, submission: Path, experiment_dir: Path):
    output = experiment_dir / "artifacts"
    output.mkdir(parents=True)
    evaluation = output / "evaluation.json"
    validation = output / "score_validation.json"
    usage = output / "usage.json"
    evaluation.write_text('{"criteria":{},"reasoning":"ok"}')
    validation.write_text('{"score":75}')
    usage.write_text(json.dumps({
        "provider": "openai",
        "requested_model": "test-judge",
        "effective_model": "test-judge",
        "response_id": "test-response",
        "request_parameters": {},
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }))
    return JudgeArtifacts(validation, evaluation), {"identity": "test"}


def test_seed_set_creates_one_independent_seed_per_task_replicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(tmp_path)
    design = _design(tmp_path, task)
    output = tmp_path / "seeds"
    FakeAgentRunner.calls = 0
    monkeypatch.setattr(seeds_module, "AgentRunner", FakeAgentRunner)
    monkeypatch.setattr(SeedSetRunner, "_judge_initial_submission", _fake_judge)

    assert SeedSetRunner(SeedSetConfig(design, output, 2)).run() == 0
    assert FakeAgentRunner.calls == 3
    seeds = [
        resolve_seed(
            output,
            task,
            replicate,
            provider="codex",
            requested_model="test-model",
        )
        for replicate in range(1, 4)
    ]
    assert len({seed.sha256 for seed in seeds}) == 3
    assert all(seed.manifest["replicate"] == index for index, seed in enumerate(seeds, 1))
    root = json.loads((output / "manifest.json").read_text())
    assert root == {
        "kind": seeds_module.SEED_SET_KIND,
    }


def test_shared_pool_reuses_existing_blocks_and_generates_only_missing_blocks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(tmp_path)
    design = _design(tmp_path, task)
    first_payload = copy.deepcopy(design.payload)
    first_payload["assignments"] = [
        assignment
        for assignment in design.assignments
        if assignment["replicate"] == 1
    ]
    first = Experiment(tmp_path / "first.yaml", first_payload)
    output = tmp_path / "seeds"
    FakeAgentRunner.calls = 0
    monkeypatch.setattr(seeds_module, "AgentRunner", FakeAgentRunner)
    monkeypatch.setattr(SeedSetRunner, "_judge_initial_submission", _fake_judge)
    SeedSetRunner(SeedSetConfig(first, output, 1)).run()
    assert FakeAgentRunner.calls == 1

    second_payload = copy.deepcopy(design.payload)
    second_payload["experiment_id"] = "second-experiment"
    second = Experiment(tmp_path / "second.yaml", second_payload)
    assert SeedSetRunner(SeedSetConfig(second, output, 3)).run() == 0
    assert FakeAgentRunner.calls == 3
    owners = {
        replicate: resolve_seed(
            output,
            task,
            replicate,
            provider="codex",
            requested_model="test-model",
        ).manifest["experiment_id"]
        for replicate in range(1, 4)
    }
    assert owners == {
        1: EXPERIMENT_ID,
        2: "second-experiment",
        3: "second-experiment",
    }

    answer = output / "tasks" / task.name / "rep-002" / "submission" / "workspace" / "answer.txt"
    answer.chmod(stat.S_IRUSR | stat.S_IWUSR)
    answer.write_text("tampered\n")
    with pytest.raises(RuntimeError, match="integrity check failed"):
        resolve_seed(
            output,
            task,
            2,
            provider="codex",
            requested_model="test-model",
        )


def test_seed_failure_preserves_diagnostics_until_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task = _task(tmp_path)
    design = _design(tmp_path, task)
    payload = copy.deepcopy(design.payload)
    payload["assignments"] = [
        assignment
        for assignment in design.assignments
        if assignment["replicate"] == 1
    ]
    experiment = Experiment(tmp_path / "one-replicate.yaml", payload)
    output = tmp_path / "seeds"
    monkeypatch.setattr(seeds_module, "AgentRunner", KilledAgentRunner)

    assert SeedSetRunner(SeedSetConfig(experiment, output, 1)).run() == 1

    diagnostics = output / "tasks" / task.name / "rep-001" / "failed_solver"
    failure = json.loads((diagnostics / "failure.json").read_text())
    assert failure["exit_code"] == -9
    assert failure["signal"] == "SIGKILL"
    assert failure["copied_files"] == [
        "prompt.txt",
        "trajectory.stream.jsonl",
        "status.json",
    ]
    error = capsys.readouterr().err
    assert "code -9 (SIGKILL)" in error
    assert f"diagnostics: {diagnostics}" in error
    assert (diagnostics / "trajectory.stream.jsonl").is_file()

    FakeAgentRunner.calls = 0
    monkeypatch.setattr(seeds_module, "AgentRunner", FakeAgentRunner)
    monkeypatch.setattr(SeedSetRunner, "_judge_initial_submission", _fake_judge)
    assert SeedSetRunner(SeedSetConfig(experiment, output, 1)).run() == 0
    assert not diagnostics.exists()
    resolve_seed(
        output,
        task,
        1,
        provider="codex",
        requested_model="test-model",
    )


def test_shared_pool_reuses_complete_blocks_without_an_overwrite_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(tmp_path)
    design = _design(tmp_path, task)
    output = tmp_path / "seeds"
    monkeypatch.setattr(seeds_module, "AgentRunner", FakeAgentRunner)
    monkeypatch.setattr(SeedSetRunner, "_judge_initial_submission", _fake_judge)
    FakeAgentRunner.calls = 0
    SeedSetRunner(SeedSetConfig(design, output, 1)).run()
    assert FakeAgentRunner.calls == 3
    assert SeedSetRunner(SeedSetConfig(design, output, 1)).run() == 0
    assert FakeAgentRunner.calls == 3
    seed = resolve_seed(
        output,
        task,
        1,
        provider="codex",
        requested_model="test-model",
    )

    assert seed.manifest["experiment_id"] == EXPERIMENT_ID


def test_seed_rejects_obsolete_labels_and_additional_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(tmp_path)
    design = _design(tmp_path, task)
    output = tmp_path / "seeds"
    monkeypatch.setattr(seeds_module, "AgentRunner", FakeAgentRunner)
    monkeypatch.setattr(SeedSetRunner, "_judge_initial_submission", _fake_judge)
    SeedSetRunner(SeedSetConfig(design, output, 1)).run()

    root_manifest_path = output / "manifest.json"
    root_manifest = json.loads(root_manifest_path.read_text())
    root_manifest.update({
        "kind": "rubric-gen-biomnibench-randomized-seed-set",
        "legacy_note": "preserved provenance",
    })
    root_manifest_path.write_text(json.dumps(root_manifest))

    block_manifest_path = (
        output / "tasks" / task.name / "rep-001" / "manifest.json"
    )
    block_manifest_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    block_manifest = json.loads(block_manifest_path.read_text())
    block_manifest.update({
        "kind": "rubric-gen-biomnibench-randomized-seed",
        "legacy_note": "preserved provenance",
    })
    block_manifest_path.write_text(json.dumps(block_manifest))

    with pytest.raises(RuntimeError, match="invalid seed"):
        resolve_seed(
            output,
            task,
            1,
            provider="codex",
            requested_model="test-model",
        )
    with pytest.raises(RuntimeError, match="shared seed manifest"):
        SeedSetRunner(SeedSetConfig(design, output, 1)).run()


def test_seed_rejects_provenance_metadata_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(tmp_path)
    design = _design(tmp_path, task)
    output = tmp_path / "seeds"
    monkeypatch.setattr(seeds_module, "AgentRunner", FakeAgentRunner)
    monkeypatch.setattr(SeedSetRunner, "_judge_initial_submission", _fake_judge)
    SeedSetRunner(SeedSetConfig(design, output, 1)).run()
    manifest_path = output / "tasks" / task.name / "rep-001" / "manifest.json"
    manifest_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    manifest = json.loads(manifest_path.read_text())
    manifest["requested_model"] = "forged-model"
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(RuntimeError, match="invalid seed"):
        resolve_seed(
            output,
            task,
            1,
            provider="codex",
            requested_model="test-model",
        )


def test_seed_cli_is_experiment_only() -> None:
    args = build_parser().parse_args([
        "seed", "--experiment", "experiment.yaml"
    ])
    assert args.experiment == "experiment.yaml"
    with pytest.raises(SystemExit):
        build_parser().parse_args([
            "seed", "--tasks-dir", "tasks", "--output-dir", "seeds"
        ])
    with pytest.raises(SystemExit):
        build_parser().parse_args([
            "seed", "--experiment", "experiment.yaml", "--resume"
        ])
