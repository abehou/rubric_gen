from __future__ import annotations

import argparse
import json
import os
import re
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

import rubric_gen.submission_revision.commands as commands_module
import rubric_gen.submission_revision.experiment as experiment_module
import rubric_gen.submission_revision.study as study_module
import rubric_gen.benchmarks.paperbench_code_dev.contract as paperbench_contract_module
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
        "kind": "rubric-gen-randomized-experiment",
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
        "rubric_paraphrases": {
            "count": 3,
            "model": "test-paraphraser",
            "max_retries": 1,
        },
        "outcome_audit": {
            "models": ["judge-a", "judge-b"],
            "primary_rule": "majority",
            "component_weights": {
                "verifier_exploitation": 1,
                "rubric_drift": 1,
                "wording_exploitation": 1,
                "specification_exploitation": 1,
            },
        },
        "dag": {
            "seed": {"depends_on": [], "output_dir": "runs/seeds"},
            "paraphrase": {
                "depends_on": [],
                "output_dir": "runs/paraphrases/common",
            },
            "revise": {
                "depends_on": ["seed", "paraphrase"],
                "output_dir": "runs/revisions/{experiment_id}",
            },
            "detect": {
                "depends_on": ["revise", "paraphrase"],
                "output_dir": "runs/detections/{experiment_id}",
            },
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


def test_experiment_id_is_derived_from_semantic_yaml(tmp_path: Path) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    first_path = tmp_path / "first.yaml"
    first_path.write_text(yaml.safe_dump(payload, sort_keys=False))
    first = load_experiment(first_path)

    second_path = tmp_path / "second.yaml"
    second_path.write_text(yaml.safe_dump(payload, sort_keys=True))
    second = load_experiment(second_path)

    assert re.fullmatch(
        r"biomnibench-da-semi-r10-[0-9a-f]{12}", first.experiment_id
    )
    assert second.experiment_id == first.experiment_id
    assert Path(str(first.dag["revise"]["output_dir"])).name == first.experiment_id
    assert Path(str(first.dag["detect"]["output_dir"])).name == first.experiment_id


def test_experiment_requires_all_reward_hacking_component_weights(
    tmp_path: Path,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["outcome_audit"]["component_weights"].pop("rubric_drift")
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="component_weights must contain exactly"):
        load_experiment(path)


def test_experiment_id_changes_with_behavior_but_not_output_routing(
    tmp_path: Path,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    baseline = _payload(tmp_path)
    baseline_path = tmp_path / "baseline.yaml"
    baseline_path.write_text(yaml.safe_dump(baseline, sort_keys=False))
    baseline_id = load_experiment(baseline_path).experiment_id

    routed = _payload(tmp_path)
    routed["dag"]["revise"]["output_dir"] = "other/studies/{experiment_id}"  # type: ignore[index]
    routed["dag"]["detect"]["output_dir"] = "other/detections/{experiment_id}"  # type: ignore[index]
    routed_path = tmp_path / "routed.yaml"
    routed_path.write_text(yaml.safe_dump(routed, sort_keys=False))
    assert load_experiment(routed_path).experiment_id == baseline_id

    changed = _payload(tmp_path)
    changed["protocol"]["revision_rounds"] = 11  # type: ignore[index]
    changed_path = tmp_path / "changed.yaml"
    changed_path.write_text(yaml.safe_dump(changed, sort_keys=False))
    changed_id = load_experiment(changed_path).experiment_id
    assert changed_id != baseline_id
    assert "-r11-" in changed_id


def test_experiment_rejects_manual_id_and_nonautomatic_output_paths(
    tmp_path: Path,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    manual = _payload(tmp_path)
    manual["experiment_id"] = "manual-id"
    manual_path = tmp_path / "manual.yaml"
    manual_path.write_text(yaml.safe_dump(manual, sort_keys=False))
    with pytest.raises(ValueError, match="experiment keys must be exactly"):
        load_experiment(manual_path)

    fixed_output = _payload(tmp_path)
    fixed_output["dag"]["revise"]["output_dir"] = "runs/revisions/fixed"  # type: ignore[index]
    fixed_path = tmp_path / "fixed.yaml"
    fixed_path.write_text(yaml.safe_dump(fixed_output, sort_keys=False))
    with pytest.raises(ValueError, match="must end with .*experiment_id"):
        load_experiment(fixed_path)


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


def test_seed_stage_uses_one_shared_directory_without_an_owner_id(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["dag"]["seed"]["output_dir"] = "seeds/shared"  # type: ignore[index]
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    observed: list[SeedSetConfig] = []

    class FakeSeedSetRunner:
        def __init__(self, config: SeedSetConfig) -> None:
            observed.append(config)

        def run(self) -> int:
            return 0

    monkeypatch.setattr(commands_module, "SeedSetRunner", FakeSeedSetRunner)
    args = argparse.Namespace(
        experiment=str(path), max_concurrency=2, resume=True, vllm=[]
    )

    assert commands_module.run_seed(args) == 0
    assert len(observed) == 1
    assert observed[0].output_dir == tmp_path / "seeds" / "shared"
    assert observed[0].max_concurrency == 2


def test_seed_stage_rejects_obsolete_source_routing(tmp_path: Path) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["dag"]["seed"]["source_experiment_id"] = "source-experiment"  # type: ignore[index]
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="requires depends_on and output_dir"):
        load_experiment(path)


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


def test_experiment_workflow_suppresses_solver_event_streams(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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
        paraphrase_run_dir=tmp_path / "paraphrases",
        output_dir=tmp_path / "study",
        max_concurrency=1,
    ))
    assignment = min(
        experiment.assignments,
        key=lambda item: int(item["execution_order"]),
    )
    optimizer = experiment.task_dir(str(assignment["task_id"])) / "tests" / "rubric.txt"
    monkeypatch.setattr(
        study_module,
        "resolve_paraphrase_selection",
        lambda *_args, **_kwargs: SimpleNamespace(optimizer_path=optimizer),
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
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    experiment = load_experiment(path)
    experiment_id = experiment.experiment_id
    roots = {
        stage: Path(str(experiment.dag[stage]["output_dir"]))
        for stage in ("seed", "paraphrase", "revise", "detect")
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

    def seed_stage(_args: argparse.Namespace) -> int:
        assert roots["seed"].is_dir()
        assert roots["revise"].is_dir()
        assert roots["detect"].is_dir()
        calls.append("seed")
        return 0

    def paraphrase_stage(stage_args: argparse.Namespace) -> int:
        assert stage_args.resume is False
        assert roots["paraphrase"].is_dir()
        assert roots["revise"].is_dir()
        assert roots["detect"].is_dir()
        calls.append("paraphrase")
        return 0

    def stage(name: str):
        def run(_args: argparse.Namespace) -> int:
            assert roots["seed"].is_dir()
            assert roots["paraphrase"].is_dir()
            assert not roots["revise"].exists()
            assert not roots["detect"].exists()
            calls.append(name)
            return 0

        return run

    monkeypatch.setattr(commands_module, "run_seed", seed_stage)
    monkeypatch.setattr(commands_module, "run_paraphrase", paraphrase_stage)
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
    assert calls == ["seed", "paraphrase", "revise", "detect"]
    assert roots["seed"].is_dir()
    assert roots["paraphrase"].is_dir()


def test_detect_runs_score_methods_when_direct_panel_has_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rubric_gen.submission_revision.direct_audit as direct_audit_module
    import rubric_gen.submission_revision.rh_diagnostics as diagnostics_module

    experiment = SimpleNamespace(
        dag={
            "revise": {"output_dir": str(tmp_path / "study")},
            "paraphrase": {"output_dir": str(tmp_path / "paraphrases")},
            "detect": {"output_dir": str(tmp_path / "detect")},
        },
        outcome_audit={"models": ["strong-a", "strong-b"]},
    )
    calls: list[str] = []
    direct_configs: list[object] = []
    configs: list[object] = []

    def direct(config: object) -> int:
        direct_configs.append(config)
        calls.append("direct")
        return 1

    class MechanisticRunner:
        def __init__(self, config: object) -> None:
            configs.append(config)

        def run(self) -> int:
            calls.append("mechanistic")
            return 0

    class HolisticRunner:
        def __init__(self, config: object) -> None:
            configs.append(config)

        def run(self) -> int:
            calls.append("holistic")
            return 0

    monkeypatch.setattr(commands_module, "load_experiment", lambda _path: experiment)
    monkeypatch.setattr(direct_audit_module, "run_direct_audit", direct)
    monkeypatch.setattr(
        diagnostics_module,
        "MechanisticEvaluationRunner",
        MechanisticRunner,
    )
    monkeypatch.setattr(
        diagnostics_module,
        "HolisticPairwiseRunner",
        HolisticRunner,
    )
    monkeypatch.setattr(
        diagnostics_module,
        "write_reward_hacking_evaluation",
        lambda _path: calls.append("combined"),
    )

    status = commands_module.run_detect(argparse.Namespace(
        experiment="experiment.yaml",
        max_concurrency=3,
        resume=True,
        vllm=["http://weak:8000::weak-model"],
    ))

    assert status == 1
    assert calls == ["direct", "mechanistic", "holistic", "combined"]
    assert len(direct_configs) == 1
    assert direct_configs[0].base_urls == {}
    assert all(
        config.vllm_endpoints == {"weak-model": "http://weak:8000/v1"}
        for config in configs
    )


def test_detect_runs_holistic_stage_after_mechanistic_stage_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rubric_gen.submission_revision.direct_audit as direct_audit_module
    import rubric_gen.submission_revision.rh_diagnostics as diagnostics_module

    experiment = SimpleNamespace(
        dag={
            "revise": {"output_dir": str(tmp_path / "study")},
            "paraphrase": {"output_dir": str(tmp_path / "paraphrases")},
            "detect": {"output_dir": str(tmp_path / "detect")},
        },
        outcome_audit={"models": ["strong-a", "strong-b"]},
    )
    calls: list[str] = []

    class MechanisticRunner:
        def __init__(self, _config: object) -> None:
            pass

        def run(self) -> int:
            calls.append("mechanistic")
            raise RuntimeError("strong judge unavailable")

    class HolisticRunner:
        def __init__(self, _config: object) -> None:
            pass

        def run(self) -> int:
            calls.append("holistic")
            return 0

    monkeypatch.setattr(commands_module, "load_experiment", lambda _path: experiment)
    monkeypatch.setattr(
        direct_audit_module,
        "run_direct_audit",
        lambda _config: 0,
    )
    monkeypatch.setattr(
        diagnostics_module,
        "MechanisticEvaluationRunner",
        MechanisticRunner,
    )
    monkeypatch.setattr(
        diagnostics_module,
        "HolisticPairwiseRunner",
        HolisticRunner,
    )
    monkeypatch.setattr(
        diagnostics_module,
        "write_reward_hacking_evaluation",
        lambda _path: calls.append("combined"),
    )

    with pytest.raises(RuntimeError, match="mechanistic"):
        commands_module.run_detect(argparse.Namespace(
            experiment="experiment.yaml",
            max_concurrency=3,
            resume=False,
            vllm=[],
        ))

    assert calls == ["mechanistic", "holistic"]


def test_run_restart_validates_every_output_before_removal(tmp_path: Path) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    experiment = load_experiment(path)
    experiment_id = experiment.experiment_id
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
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    experiment = load_experiment(path)
    experiment_id = experiment.experiment_id
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


def test_run_restart_detaches_outputs_before_best_effort_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    experiment = load_experiment(path)
    experiment_id = experiment.experiment_id
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
            paraphrase_run_dir=tmp_path / "runs" / "paraphrases",
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
    optimizer = experiment.task_dir("da-1-1") / "tests" / "rubric.txt"
    monkeypatch.setattr(study_module, "validate_paraphrase_run", lambda *_: None)
    monkeypatch.setattr(
        study_module,
        "resolve_paraphrase_selection",
        lambda *_args, **_kwargs: SimpleNamespace(optimizer_path=optimizer),
    )
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


def test_study_reports_recorded_assignment_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _task(tmp_path, "da-1-1")
    payload = _payload(tmp_path)
    payload["tasks"] = ["da-1-1"]
    payload["randomization"] = {"seed": 42, "replicates": 1}
    payload["conditions"] = [payload["conditions"][0]]  # type: ignore[index]
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    experiment = load_experiment(path)
    optimizer = experiment.task_dir("da-1-1") / "tests" / "rubric.txt"
    monkeypatch.setattr(study_module, "validate_paraphrase_run", lambda *_: None)
    monkeypatch.setattr(
        study_module,
        "resolve_paraphrase_selection",
        lambda *_args, **_kwargs: SimpleNamespace(optimizer_path=optimizer),
    )

    def fail_revision(_revision: object) -> None:
        raise RuntimeError("scoring identity mismatch")

    monkeypatch.setattr(study_module, "run_submission_revision", fail_revision)
    runner = StudyRunner(StudyRunConfig(
        experiment=experiment,
        seed_run_dir=tmp_path / "runs" / "seeds",
        paraphrase_run_dir=tmp_path / "runs" / "paraphrases",
        output_dir=tmp_path / "runs" / "study",
        max_concurrency=1,
    ))

    assert runner.run() == 1
    assert (
        "assignment failed: da-1-1--rep-001--base-static: "
        "RuntimeError: scoring identity mismatch"
    ) in capsys.readouterr().err


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
