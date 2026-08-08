from __future__ import annotations

import json
import os
from pathlib import Path

import pytest
import yaml

import rubric_gen.biomnibench.study as study_module
from rubric_gen.biomnibench.experiment import load_experiment
from rubric_gen.biomnibench.revision.seeds import SeedSetConfig, SeedSetRunner
from rubric_gen.biomnibench.study import (
    StudyRunConfig,
    StudyRunner,
    _exclusive_study_lease,
)


def _task(root: Path, task_id: str) -> None:
    task = root / "tasks" / task_id
    (task / "environment" / "data").mkdir(parents=True)
    (task / "tests").mkdir()
    (task / "instruction.md").write_text("Task.\n")
    (task / "environment" / "data" / "x.csv").write_text("x\n1\n")
    (task / "tests" / "rubric.txt").write_text(
        "Criterion 1: Result\nLevels: A=100 B=50 C=0\n"
    )


def _payload(root: Path) -> dict[str, object]:
    return {
        "schema_version": 1,
        "kind": "rubric-gen-randomized-experiment",
        "experiment_id": "test-experiment",
        "tasks_dir": "tasks",
        "tasks": ["da-1-1", "da-2-1"],
        "randomization": {"seed": 42, "replicates": 3},
        "conditions": [
            {"condition_id": "base-static", "prompt": "base", "rubric_evolution": "static"},
            {"condition_id": "diligent-prospective", "prompt": "diligent", "rubric_evolution": "prospective"},
        ],
        "protocol": {
            "revision_rounds": 10, "feedback_policy": "semi",
            "solver": {"provider": "codex", "model": "test-model", "reasoning_effort": "minimal", "service_tier": None, "executable": None, "retries": 1, "timeout_seconds": 60},
            "judge_model": "test-judge", "judge_max_retries": 1,
            "rubric_name": "rubric.txt", "review": "trace", "max_review_chars": None,
            "rubric_proposer_model": "test-proposer", "rubric_proposer_step_limit": 2,
            "rubric_proposer_max_retries": 1,
        },
        "outcome_audit": {
            "models": ["judge-a", "judge-b"],
            "primary_rule": "majority",
        },
        "dag": {
            "seed": {"depends_on": [], "output_dir": "runs/seeds"},
            "revise": {"depends_on": ["seed"], "output_dir": "runs/revisions"},
            "detect": {"depends_on": ["revise"], "output_dir": "runs/detections"},
        },
    }


def test_yaml_experiment_randomizes_balanced_assignments_without_hashes(tmp_path: Path) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(_payload(tmp_path), sort_keys=False))
    first = load_experiment(path)
    second = load_experiment(path)
    assert first.assignments == second.assignments
    assert len(first.assignments) == 2 * 3 * 2
    assert all("design_sha256" not in item for item in first.assignments)
    assert {item["execution_order"] for item in first.assignments} == set(range(1, 13))


def test_yaml_experiment_rejects_broken_dag(tmp_path: Path) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["dag"]["detect"]["depends_on"] = []  # type: ignore[index]
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    with pytest.raises(ValueError, match="invalid dependencies"):
        load_experiment(path)


def test_vllm_solver_requires_and_uses_matching_endpoint(tmp_path: Path) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["protocol"]["solver"].update({  # type: ignore[index,union-attr]
        "provider": "vllm",
        "model": "Qwen/Qwen3.6-27B",
        "reasoning_effort": None,
    })
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    experiment = load_experiment(path)

    with pytest.raises(ValueError, match="matching --vllm endpoint"):
        experiment.agent_config()
    config = experiment.agent_config(vllm_endpoints={
        "Qwen/Qwen3.6-27B": "http://qwen27:43117/v1",
    })
    assert config.provider == "vllm"
    assert config.model == "Qwen/Qwen3.6-27B"
    assert config.base_url == "http://qwen27:43117/v1"


def test_experiment_workflow_suppresses_solver_event_streams(tmp_path: Path) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(_payload(tmp_path), sort_keys=False))
    experiment = load_experiment(path)

    seed = SeedSetRunner(SeedSetConfig(
        experiment=experiment,
        output_dir=tmp_path / "seeds",
        max_concurrency=1,
    ))
    study = StudyRunner(StudyRunConfig(
        experiment=experiment,
        seed_run_dir=tmp_path / "seeds",
        output_dir=tmp_path / "study",
        max_concurrency=1,
    ))
    assignment = min(
        experiment.assignments,
        key=lambda item: int(item["execution_order"]),
    )

    assert seed.agent.quiet is True
    assert study._revision_config(assignment, resume=False).agent.quiet is True


def test_study_resume_reclaims_interrupted_running_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["tasks"] = ["da-1-1"]
    payload["randomization"] = {"seed": 42, "replicates": 1}
    payload["conditions"] = [payload["conditions"][0]]  # type: ignore[index]
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    experiment = load_experiment(path)
    output = tmp_path / "runs" / "revisions"
    output.mkdir(parents=True)
    runner = StudyRunner(
        StudyRunConfig(
            experiment=experiment,
            seed_run_dir=tmp_path / "runs" / "seeds",
            output_dir=output,
            max_concurrency=1,
            resume=True,
        )
    )
    assignments = sorted(
        experiment.assignments,
        key=lambda item: int(item["execution_order"]),
    )
    manifest = runner._new_manifest(assignments)
    record = manifest["records"][0]  # type: ignore[index]
    record.update({
        "status": "running",
        "hostname": "dead-host",
        "pid": 999999,
        "attempt_count": 4,
        "started_at": "2026-08-07T00:00:00-07:00",
    })
    runner._write_manifest(manifest)
    revisions: list[object] = []
    monkeypatch.setattr(
        study_module,
        "run_submission_revision",
        lambda revision: revisions.append(revision),
    )
    monkeypatch.setattr(
        study_module,
        "validate_completed_revision",
        lambda *args, **kwargs: None,
    )

    assert runner.run() == 0

    finished = json.loads((output / "study.json").read_text())
    recovered = finished["records"][0]
    assert finished["status"] == "completed"
    assert recovered["status"] == "completed"
    assert recovered["attempt_count"] == 5
    assert recovered["pid"] == os.getpid()
    assert len(revisions) == 1


def test_study_lease_rejects_a_concurrent_invocation(tmp_path: Path) -> None:
    root = tmp_path / "study"
    root.mkdir()

    with _exclusive_study_lease(root):
        owner = json.loads((root / ".study.lock").read_text())
        assert owner["pid"] == os.getpid()
        with pytest.raises(RuntimeError, match="active invocation"):
            with _exclusive_study_lease(root):
                pass

    with _exclusive_study_lease(root):
        pass
