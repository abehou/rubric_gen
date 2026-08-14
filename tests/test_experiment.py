from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import pytest
import yaml

import rubric_gen.submission_revision.commands as commands_module
import rubric_gen.submission_revision.experiment as experiment_module
import rubric_gen.submission_revision.study as study_module
import rubric_gen.benchmarks.paperbench_code_dev as paperbench_contract_module
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.seeds import (
    SEED_SET_KIND,
    SeedSetConfig,
    SeedSetRunner,
)
from rubric_gen.submission_revision.study import (
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
        "schema_version": 3,
        "kind": "rubric-gen-randomized-experiment",
        "experiment_id": "test-experiment",
        "benchmark": "biomnibench-da",
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
            "rubric_auditor_model": "test-auditor",
            "rubric_auditor_query_limit": 2,
            "rubric_proposer_model": "test-proposer",
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


def test_paperbench_experiment_accepts_a_pinned_dev_subset(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = "semantic-self-consistency"
    _task(tmp_path, task_id)
    task = tmp_path / "tasks" / task_id
    (task / "environment" / "data" / "paper.md").write_text("# Paper\n")
    (task / "tests" / "paperbench.json").write_text("{}\n")
    payload = _payload(tmp_path)
    payload["benchmark"] = "paperbench-code-dev"
    payload["tasks"] = [task_id]
    payload["protocol"]["review"] = "workspace"  # type: ignore[index]
    path = tmp_path / "paperbench.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    monkeypatch.setattr(
        paperbench_contract_module,
        "validate_paperbench_code_dev_dataset",
        lambda _path: None,
    )

    experiment = load_experiment(path)

    assert experiment.task_ids == (task_id,)


def test_dag_validates_and_reuses_an_explicit_seed_source(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["dag"]["seed"]["source_experiment_id"] = "source-experiment"  # type: ignore[index]
    payload["dag"]["seed"]["output_dir"] = "runs/seeds/source-experiment"  # type: ignore[index]
    payload["dag"]["revise"]["output_dir"] = "runs/revisions/test-experiment"  # type: ignore[index]
    payload["dag"]["detect"]["output_dir"] = "runs/detections/test-experiment"  # type: ignore[index]
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    calls: list[tuple[str, int, str]] = []

    def resolve(seed_root, task_dir, replicate, *, experiment_id, **_kwargs):
        calls.append((task_dir.name, replicate, experiment_id))

    monkeypatch.setattr(commands_module, "resolve_seed", resolve)
    args = argparse.Namespace(
        experiment=str(path), max_concurrency=2, resume=True, vllm=[]
    )

    experiment = load_experiment(path)
    assert experiment.seed_experiment_id == "source-experiment"
    assert commands_module.run_seed(args) == 0
    assert calls == [
        (task_id, replicate, "source-experiment")
        for task_id in ("da-1-1", "da-2-1")
        for replicate in range(1, 4)
    ]
    calls.clear()
    commands_module._validate_existing_seed_set(
        experiment,
        vllm_endpoints={},
    )
    assert calls == [
        (task_id, replicate, "source-experiment")
        for task_id in ("da-1-1", "da-2-1")
        for replicate in range(1, 4)
    ]
    commands_module._validate_restart_roots(
        experiment,
        {
            stage: Path(str(experiment.dag[stage]["output_dir"])).resolve()
            for stage in ("seed", "revise", "detect")
        },
    )


def test_simulated_user_feedback_requires_and_loads_model_config(
    tmp_path: Path,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["protocol"]["feedback_policy"] = "simulated_user"  # type: ignore[index]
    payload["protocol"]["feedback_simulator"] = {  # type: ignore[index]
        "model": "gpt-simulated-user",
        "max_output_tokens": 1_024,
        "max_aspects": 2,
        "max_retries": 1,
    }
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    experiment = load_experiment(path)
    config = experiment.feedback_simulator_config()

    assert config is not None
    assert config.model == "gpt-simulated-user"
    assert config.max_output_tokens == 1_024
    assert config.max_aspects == 2


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


def test_run_restart_reuses_seeds_and_replaces_downstream_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    experiment_id = str(payload["experiment_id"])
    dag = payload["dag"]
    assert isinstance(dag, dict)
    for stage, parent in (
        ("seed", "seeds"),
        ("revise", "studies"),
        ("detect", "detections"),
    ):
        dag[stage]["output_dir"] = f"runs/{parent}/{experiment_id}"  # type: ignore[index]
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    experiment = load_experiment(path)
    roots = {
        stage: Path(str(experiment.dag[stage]["output_dir"]))
        for stage in ("seed", "revise", "detect")
    }
    for root in roots.values():
        nested = root / "nested"
        nested.mkdir(parents=True)
        (nested / "artifact.txt").write_text("old\n")
        nested.chmod(0o555)
    (roots["seed"] / "manifest.json").write_text(json.dumps({
        "kind": SEED_SET_KIND,
        "experiment_id": experiment_id,
    }))
    (roots["revise"] / "study.json").write_text(json.dumps({
        "kind": "rubric-gen-randomized-revision-study",
        "experiment_id": experiment_id,
    }))
    calls: list[str] = []

    def validate_seeds(*_args, **_kwargs) -> None:
        assert roots["seed"].is_dir()
        calls.append("validate-seeds")

    def stage(name: str):
        def run(_args: argparse.Namespace) -> int:
            assert roots["seed"].is_dir()
            assert not roots["revise"].exists()
            assert not roots["detect"].exists()
            calls.append(name)
            return 0

        return run

    monkeypatch.setattr(
        commands_module,
        "_validate_existing_seed_set",
        validate_seeds,
    )
    monkeypatch.setattr(
        commands_module,
        "run_seed",
        lambda _args: pytest.fail("restart must not run seed generation"),
    )
    monkeypatch.setattr(commands_module, "run_revise", stage("revise"))
    monkeypatch.setattr(commands_module, "run_detect", stage("detect"))

    result = commands_module.run_dag(argparse.Namespace(
        experiment=str(path),
        max_concurrency=4,
        resume=False,
        restart=True,
        vllm=[],
    ))

    assert result == 0
    assert calls == ["validate-seeds", "revise", "detect"]
    assert roots["seed"].is_dir()


def test_run_restart_validates_every_output_before_removal(tmp_path: Path) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    experiment_id = str(payload["experiment_id"])
    dag = payload["dag"]
    assert isinstance(dag, dict)
    for stage, parent in (
        ("seed", "seeds"),
        ("revise", "studies"),
        ("detect", "detections"),
    ):
        dag[stage]["output_dir"] = f"runs/{parent}/{experiment_id}"  # type: ignore[index]
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    experiment = load_experiment(path)
    seed_root = Path(str(experiment.dag["seed"]["output_dir"]))
    seed_root.mkdir(parents=True)
    (seed_root / "manifest.json").write_text(json.dumps({
        "kind": SEED_SET_KIND,
        "experiment_id": experiment_id,
    }))
    revise_root = Path(str(experiment.dag["revise"]["output_dir"]))
    revise_root.parent.mkdir(parents=True)
    revise_root.write_text("not a directory\n")

    with pytest.raises(RuntimeError, match="not a regular directory"):
        commands_module._restart_experiment_outputs(experiment)

    assert seed_root.is_dir()
    assert (seed_root / "manifest.json").is_file()


def test_run_restart_rejects_an_active_study(tmp_path: Path) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    experiment_id = str(payload["experiment_id"])
    dag = payload["dag"]
    assert isinstance(dag, dict)
    for stage, parent in (
        ("seed", "seeds"),
        ("revise", "studies"),
        ("detect", "detections"),
    ):
        dag[stage]["output_dir"] = f"runs/{parent}/{experiment_id}"  # type: ignore[index]
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    experiment = load_experiment(path)
    roots = {
        stage: Path(str(experiment.dag[stage]["output_dir"]))
        for stage in ("seed", "revise", "detect")
    }
    for root in roots.values():
        root.mkdir(parents=True)
    (roots["seed"] / "manifest.json").write_text(json.dumps({
        "kind": SEED_SET_KIND,
        "experiment_id": experiment_id,
    }))
    (roots["revise"] / "study.json").write_text(json.dumps({
        "kind": "rubric-gen-randomized-revision-study",
        "experiment_id": experiment_id,
    }))

    with _exclusive_study_lease(roots["revise"]):
        with pytest.raises(RuntimeError, match="active invocation"):
            commands_module._restart_experiment_outputs(experiment)

    assert all(root.is_dir() for root in roots.values())


def test_run_restart_requires_an_existing_complete_seed_set(tmp_path: Path) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    experiment_id = str(payload["experiment_id"])
    dag = payload["dag"]
    assert isinstance(dag, dict)
    for stage, parent in (
        ("seed", "seeds"),
        ("revise", "studies"),
        ("detect", "detections"),
    ):
        dag[stage]["output_dir"] = f"runs/{parent}/{experiment_id}"  # type: ignore[index]
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    experiment = load_experiment(path)

    with pytest.raises(RuntimeError, match="completed seed set"):
        commands_module._validate_existing_seed_set(
            experiment,
            vllm_endpoints={},
        )


def test_run_restart_detaches_outputs_before_best_effort_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    experiment_id = str(payload["experiment_id"])
    dag = payload["dag"]
    assert isinstance(dag, dict)
    for stage, parent in (
        ("seed", "seeds"),
        ("revise", "studies"),
        ("detect", "detections"),
    ):
        dag[stage]["output_dir"] = f"runs/{parent}/{experiment_id}"  # type: ignore[index]
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    experiment = load_experiment(path)
    roots = {
        stage: Path(str(experiment.dag[stage]["output_dir"]))
        for stage in ("seed", "revise", "detect")
    }
    for root in roots.values():
        root.mkdir(parents=True)
    (roots["seed"] / "manifest.json").write_text(json.dumps({
        "kind": SEED_SET_KIND,
        "experiment_id": experiment_id,
    }))
    (roots["revise"] / "study.json").write_text(json.dumps({
        "kind": "rubric-gen-randomized-revision-study",
        "experiment_id": experiment_id,
    }))
    unlocked_study_cleanup: list[bool] = []

    def fail_cleanup(root: Path) -> None:
        if (root / "study.json").is_file():
            with _exclusive_study_lease(root):
                unlocked_study_cleanup.append(True)
        raise OSError(39, "Directory not empty")

    monkeypatch.setattr(
        commands_module,
        "_force_remove_directory",
        fail_cleanup,
    )

    commands_module._restart_experiment_outputs(experiment)

    assert roots["seed"].is_dir()
    assert not roots["revise"].exists()
    assert not roots["detect"].exists()
    assert len(list(roots["revise"].parent.glob(
        f".{experiment_id}.restart-*"
    ))) == 1
    assert len(list(roots["detect"].parent.glob(
        f".{experiment_id}.restart-*"
    ))) == 1
    assert unlocked_study_cleanup == [True]
    assert "detached restart output remains" in capsys.readouterr().err


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
