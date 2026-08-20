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
        "RUBRIC: Result\n\n"
        "Criterion 1: Result\n"
        "Description: Evaluate the result.\n"
        "Levels: A=100 B=50 C=0\n"
        "[A]: Fully correct.\n"
        "[B]: Partly correct.\n"
        "[C]: Incorrect.\n"
    )


def _payload(root: Path) -> dict[str, object]:
    return {
        "kind": "rubric-gen-randomized-experiment",
        "benchmark": "biomnibench-da",
        "tasks_dir": "tasks",
        "tasks": ["da-1-1", "da-2-1"],
        "randomization": {"seed": 42, "replicates": 3},
        "conditions": [
            {
                "condition_id": "base-fixed",
                "prompt": "diligent",
                "rubric_policy": "fixed",
            },
            {
                "condition_id": "diligent-offline-elicitation",
                "prompt": "diligent",
                "rubric_policy": "offline_elicitation",
            },
            {
                "condition_id": "diligent-online-elicitation",
                "prompt": "diligent",
                "rubric_policy": "online_elicitation",
            },
        ],
        "protocol": {
            "revision_rounds": 10, "feedback_policy": "semi",
            "solver": {"provider": "codex", "model": "test-model", "reasoning_effort": "minimal", "service_tier": None, "executable": None, "retries": 1, "timeout_seconds": 60},
            "judge_model": "test-judge", "judge_max_retries": 1,
            "rubric_name": "rubric.txt", "review": "trace", "max_review_chars": None,
            "rubric_proposer_model": "test-proposer",
            "rubric_semantic_judge_model": "gpt-5.5-2026-04-23",
            "rubric_semantic_judge_max_calls_per_assignment": 9,
            "rubric_semantic_judge_max_request_bytes_per_call": 1_048_576,
            "rubric_semantic_judge_max_output_tokens_per_call": 32_768,
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
            "loss_weights": {
                "verifier_exploitation": 1,
                "dynamic_rubric_gap": 1,
            },
            "direct_detector_max_cost_usd": 100,
            "mechanistic_max_calls": 1_024,
            "mechanistic_max_request_bytes": 268_435_456,
            "mechanistic_max_output_tokens": 4_194_304,
            "holistic_max_calls": 96,
            "holistic_max_request_bytes": 134_217_728,
            "holistic_max_output_tokens": 393_216,
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
    assert len(first.assignments) == 2 * 3 * 3
    assert all("design_sha256" not in item for item in first.assignments)
    assert {item["execution_order"] for item in first.assignments} == set(
        range(1, 19)
    )


def test_experiment_rejects_an_invalid_master_rubric_before_dispatch(
    tmp_path: Path,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    (tmp_path / "tasks" / "da-2-1" / "tests" / "rubric.txt").write_text(
        "Criterion 1: Incomplete\nLevels: A=100 B=50 C=0\n"
    )
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(_payload(tmp_path), sort_keys=False))

    with pytest.raises(
        ValueError,
        match="master rubric is invalid for da-2-1",
    ):
        load_experiment(path)


def test_run_rejects_an_invalid_master_rubric_before_any_stage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    (tmp_path / "tasks" / "da-2-1" / "tests" / "rubric.txt").write_text(
        "Criterion 1: Incomplete\nLevels: A=100 B=50 C=0\n"
    )
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(_payload(tmp_path), sort_keys=False))
    calls: list[str] = []

    def stage(_args: argparse.Namespace) -> int:
        calls.append("stage")
        return 0

    monkeypatch.setattr(commands_module, "run_seed", stage)
    monkeypatch.setattr(commands_module, "run_paraphrase", stage)
    monkeypatch.setattr(commands_module, "run_revise", stage)
    monkeypatch.setattr(commands_module, "run_detect", stage)

    with pytest.raises(
        ValueError,
        match="master rubric is invalid for da-2-1",
    ):
        commands_module.run_dag(argparse.Namespace(
            experiment=str(path),
            max_concurrency=4,
            resume=False,
            restart=False,
            vllm=[],
        ))

    assert calls == []
    assert not (tmp_path / "runs").exists()


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


def test_experiment_requires_exact_reward_hacking_loss_weights(
    tmp_path: Path,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["outcome_audit"]["loss_weights"].pop("dynamic_rubric_gap")
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="loss_weights must contain exactly"):
        load_experiment(path)


def test_experiment_rejects_obsolete_component_weights(
    tmp_path: Path,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["outcome_audit"]["component_weights"] = payload[
        "outcome_audit"
    ].pop("loss_weights")
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="outcome_audit keys must be"):
        load_experiment(path)


@pytest.mark.parametrize(
    "missing",
    [
        "mechanistic_max_calls",
        "mechanistic_max_request_bytes",
        "mechanistic_max_output_tokens",
        "holistic_max_calls",
        "holistic_max_request_bytes",
        "holistic_max_output_tokens",
    ],
)
def test_experiment_requires_each_predispatch_stage_cap(
    tmp_path: Path,
    missing: str,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["outcome_audit"].pop(missing)
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="stage caps"):
        load_experiment(path)


@pytest.mark.parametrize("invalid", [0, -1, 1.5, True, "10"])
def test_experiment_requires_positive_integer_stage_caps(
    tmp_path: Path,
    invalid: object,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["outcome_audit"]["mechanistic_max_calls"] = invalid
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="positive integer"):
        load_experiment(path)


@pytest.mark.parametrize(
    ("field", "invalid", "message"),
    [
        ("judge_model", None, "judge_model"),
        ("judge_model", 7, "judge_model"),
        ("judge_max_retries", "1", "judge_max_retries"),
        ("judge_max_retries", -1, "judge_max_retries"),
        ("rubric_name", "../rubric.txt", "safe basename"),
        ("rubric_name", "", "safe basename"),
        ("max_review_chars", 0, "max_review_chars"),
        ("max_review_chars", "100", "max_review_chars"),
    ],
)
def test_experiment_eagerly_validates_judge_protocol_fields(
    tmp_path: Path,
    field: str,
    invalid: object,
    message: str,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["protocol"][field] = invalid
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match=message):
        load_experiment(path)


@pytest.mark.parametrize(
    ("field", "invalid", "message"),
    [
        (
            "rubric_semantic_judge_max_calls_per_assignment",
            8,
            "call cap must equal revision_rounds minus one",
        ),
        (
            "rubric_semantic_judge_max_calls_per_assignment",
            "9",
            "call cap must equal revision_rounds minus one",
        ),
        (
            "rubric_semantic_judge_max_request_bytes_per_call",
            0,
            "request-byte cap is invalid",
        ),
        (
            "rubric_semantic_judge_max_request_bytes_per_call",
            1_048_577,
            "request-byte cap is invalid",
        ),
        (
            "rubric_semantic_judge_max_output_tokens_per_call",
            0,
            "output-token cap is invalid",
        ),
        (
            "rubric_semantic_judge_max_output_tokens_per_call",
            32_769,
            "output-token cap is invalid",
        ),
    ],
)
def test_experiment_eagerly_validates_semantic_judge_caps(
    tmp_path: Path,
    field: str,
    invalid: object,
    message: str,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["protocol"][field] = invalid
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match=message):
        load_experiment(path)


@pytest.mark.parametrize(
    "overlap",
    ["solver", "proposer", "submission_judge", "outcome_judge", "simulator"],
)
def test_experiment_requires_a_disjoint_semantic_judge(
    tmp_path: Path,
    overlap: str,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    protocol = payload["protocol"]
    if overlap == "solver":
        conflicting_model = protocol["solver"]["model"]
    elif overlap == "proposer":
        conflicting_model = protocol["rubric_proposer_model"]
    elif overlap == "submission_judge":
        conflicting_model = protocol["judge_model"]
    elif overlap == "outcome_judge":
        conflicting_model = payload["outcome_audit"]["models"][0]
    else:
        conflicting_model = "test-simulator"
        protocol["feedback_policy"] = "simulated_user"
        protocol["feedback_simulator"] = {
            "model": conflicting_model,
            "max_output_tokens": 1_024,
            "max_aspects": 2,
            "max_retries": 1,
        }
    protocol["rubric_semantic_judge_model"] = conflicting_model
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="rubric semantic judge must differ"):
        load_experiment(path)


def test_experiment_requires_exact_solver_keys(tmp_path: Path) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["protocol"]["solver"]["retry"] = 1
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="solver keys must be exactly"):
        load_experiment(path)


def test_experiment_rejects_unknown_solver_provider(tmp_path: Path) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["protocol"]["solver"]["provider"] = "unknown-provider"
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="solver provider must be one of"):
        load_experiment(path)


def test_experiment_rejects_non_string_dag_output_dir(tmp_path: Path) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["dag"]["seed"]["output_dir"] = 123
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="output_dir must be a nonempty string"):
        load_experiment(path)


def test_experiment_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = yaml.safe_dump(_payload(tmp_path), sort_keys=False)
    path = tmp_path / "experiment.yaml"
    path.write_text(payload.replace(
        "kind: rubric-gen-randomized-experiment\n",
        "kind: forged\nkind: rubric-gen-randomized-experiment\n",
        1,
    ))

    with pytest.raises(ValueError, match="duplicate YAML key: kind"):
        load_experiment(path)


@pytest.mark.parametrize(
    ("field", "invalid", "message"),
    [
        ("provider", 1, "solver provider"),
        ("model", 1, "solver model"),
        ("retries", "1", "solver retries"),
        ("timeout_seconds", 0, "solver timeout_seconds"),
        ("service_tier", 1, "optional string"),
    ],
)
def test_experiment_rejects_solver_value_coercion(
    tmp_path: Path,
    field: str,
    invalid: object,
    message: str,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["protocol"]["solver"][field] = invalid
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match=message):
        load_experiment(path)


@pytest.mark.parametrize(
    ("field", "invalid", "message"),
    [
        ("condition_id", 123, "condition_id"),
        ("prompt", 123, "condition prompt"),
        ("rubric_policy", 123, "condition rubric_policy"),
    ],
)
def test_experiment_rejects_condition_value_coercion(
    tmp_path: Path,
    field: str,
    invalid: object,
    message: str,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["conditions"][0][field] = invalid
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match=message):
        load_experiment(path)


def test_experiment_requires_exactly_one_arm_per_rubric_policy(
    tmp_path: Path,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["conditions"][1]["rubric_policy"] = "fixed"
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="exactly one arm"):
        load_experiment(path)


def test_experiment_requires_one_shared_prompt_across_policy_arms(
    tmp_path: Path,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["conditions"][1]["prompt"] = "base"
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="one shared prompt"):
        load_experiment(path)


@pytest.mark.parametrize(
    ("field", "invalid", "message"),
    [
        ("models", ["judge-a", 3], "list of strings"),
        ("primary_rule", 1, "primary_rule must be a string"),
        ("max_input_tokens", "250000", "max input tokens"),
        ("max_retries", "1", "max retries"),
    ],
)
def test_experiment_rejects_outcome_audit_value_coercion(
    tmp_path: Path,
    field: str,
    invalid: object,
    message: str,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["outcome_audit"][field] = invalid
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match=message):
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
    changed["protocol"][
        "rubric_semantic_judge_max_calls_per_assignment"
    ] = 10  # type: ignore[index]
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
        def run(stage_args: argparse.Namespace) -> int:
            assert roots["seed"].is_dir()
            assert roots["paraphrase"].is_dir()
            assert not roots["revise"].exists()
            assert not roots["detect"].exists()
            assert stage_args.max_concurrency == 4
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

        def preflight(self) -> None:
            calls.append("mechanistic-preflight")

        def run(self) -> int:
            calls.append("mechanistic")
            return 0

    class HolisticRunner:
        def __init__(self, config: object) -> None:
            configs.append(config)

        def preflight(self) -> None:
            calls.append("holistic-preflight")

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
    assert calls == [
        "mechanistic-preflight",
        "holistic-preflight",
        "direct",
        "mechanistic",
        "holistic",
        "combined",
    ]
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

        def preflight(self) -> None:
            calls.append("mechanistic-preflight")

        def run(self) -> int:
            calls.append("mechanistic")
            raise RuntimeError("strong judge unavailable")

    class HolisticRunner:
        def __init__(self, _config: object) -> None:
            pass

        def preflight(self) -> None:
            calls.append("holistic-preflight")

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

    assert calls == [
        "mechanistic-preflight",
        "holistic-preflight",
        "mechanistic",
        "holistic",
    ]


def test_detect_stops_before_provider_work_when_stage_preflight_fails(
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
        outcome_audit={"models": ["strong-a"]},
    )
    calls: list[str] = []

    class MechanisticRunner:
        def __init__(self, _config: object) -> None:
            pass

        def preflight(self) -> None:
            calls.append("mechanistic-preflight")

        def run(self) -> int:
            calls.append("mechanistic-provider")
            return 0

    class HolisticRunner:
        def __init__(self, _config: object) -> None:
            pass

        def preflight(self) -> None:
            calls.append("holistic-preflight")
            raise RuntimeError("holistic calls exceeds its hard cap")

        def run(self) -> int:
            calls.append("holistic-provider")
            return 0

    monkeypatch.setattr(commands_module, "load_experiment", lambda _path: experiment)
    monkeypatch.setattr(
        direct_audit_module,
        "run_direct_audit",
        lambda _config: calls.append("direct-provider") or 0,
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

    with pytest.raises(RuntimeError, match="calls exceeds its hard cap"):
        commands_module.run_detect(argparse.Namespace(
            experiment="experiment.yaml",
            max_concurrency=3,
            resume=False,
            vllm=[],
        ))

    assert calls == ["mechanistic-preflight", "holistic-preflight"]


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
    payload["randomization"] = {"seed": 42, "replicates": 3}
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
        lambda revision, **_kwargs: revisions.append(revision),
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
    assert len(revisions) == 9


def test_study_reports_recorded_assignment_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _task(tmp_path, "da-1-1")
    payload = _payload(tmp_path)
    payload["tasks"] = ["da-1-1"]
    payload["randomization"] = {"seed": 42, "replicates": 3}
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

    def fail_revision(_revision: object, **_kwargs: object) -> None:
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
        "assignment failed: da-1-1--rep-001--base-fixed: "
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
