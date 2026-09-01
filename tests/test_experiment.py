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
import rubric_gen.submission_revision.study as study_module
import rubric_gen.submission_revision.study_validation as study_validation_module
import rubric_gen.submission_revision.paraphrase_validation as paraphrase_validation_module
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


def _factorial_conditions() -> list[dict[str, str]]:
    feedback_policies = {
        "full": "full",
        "semi": "semi",
        "score-only": "score_only",
        "user-simulator": "user_simulator",
    }
    rubric_policies = {
        "static": "fixed",
        "offline-rubric": "offline_elicitation",
        "online-rubric": "online_elicitation",
    }
    return [
        {
            "condition_id": f"{feedback_slug}-{rubric_slug}",
            "feedback_policy": feedback_policy,
            "rubric_policy": rubric_policy,
        }
        for feedback_slug, feedback_policy in feedback_policies.items()
        for rubric_slug, rubric_policy in rubric_policies.items()
    ]


def _payload(root: Path) -> dict[str, object]:
    return {
        "kind": "rubric-gen-randomized-experiment",
        "benchmark": "biomnibench-da",
        "tasks_dir": "tasks",
        "tasks": ["da-1-1", "da-2-1"],
        "randomization": {"seed": 42, "replicates": 3},
        "seed_generator": {
            "provider": "codex", "model": "seed-model",
            "reasoning_effort": "low", "service_tier": None,
            "executable": None, "retries": 1, "timeout_seconds": 60,
        },
        "solvers": [{
            "solver_id": "test-solver", "provider": "codex",
            "model": "test-model", "reasoning_effort": "low",
            "service_tier": None, "executable": None,
            "retries": 1, "timeout_seconds": 60,
        }],
        "assignment_selection": "all",
        "conditions": _factorial_conditions(),
        "protocol": {
            "max_revisions": 10,
            "min_revisions": 5,
            "prompt": "base",
            "feedback_simulator": {
                "model": "test-simulator",
                "max_output_tokens": 1_024,
                "max_concerns": 2,
                "max_history_bytes": 131_072,
                "max_request_bytes": 1_048_576,
                "max_retries": 1,
            },
            "judge_model": "test-judge",
            "rubric_name": "rubric.txt", "review": "trace", "max_review_chars": None,
            "rubric_proposer_model": "test-proposer",
            "rubric_proposer_max_retries": 1,
        },
        "rubric_paraphrases": {
            "count": 3,
            "selected_variant": 0,
            "model": "test-paraphraser",
            "max_retries": 1,
        },
        "outcome_audit": {
            "models": ["judge-a", "judge-b"],
            "primary_rule": "any_detect",
            "loss_weights": {
                "verifier_exploitation": 1,
                "original_rubric_gap": 1,
            },
            "rubric_score_max_calls": 1_024,
            "rubric_score_max_request_bytes": 268_435_456,
            "rubric_score_max_output_tokens": 4_194_304,
            "rubric_free_evaluation_max_calls": 96,
            "rubric_free_evaluation_max_request_bytes": 134_217_728,
            "rubric_free_evaluation_max_output_tokens": 393_216,
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
    assert len(first.assignments) == 2 * 3 * 12
    assert all(not hasattr(item, "design_sha256") for item in first.assignments)
    assert {item.execution_order for item in first.assignments} == set(
        range(1, 73)
    )


def test_experiment_crosses_solver_with_each_randomized_condition(
    tmp_path: Path,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["solvers"].append({
        "solver_id": "other-solver",
        "provider": "codex",
        "model": "other-model",
        "reasoning_effort": "medium",
        "service_tier": None,
        "executable": None,
        "retries": 2,
        "timeout_seconds": 120,
    })
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    experiment = load_experiment(path)

    assert len(experiment.assignments) == 2 * 3 * 2 * 12
    assert experiment.solver_ids == ("test-solver", "other-solver")
    assert experiment.seed_agent_config().model == "seed-model"
    assert experiment.solver_config("other-solver").model == "other-model"
    assert {
        solver_id: sum(
            assignment.solver_id == solver_id
            for assignment in experiment.assignments
        )
        for solver_id in experiment.solver_ids
    } == {"test-solver": 72, "other-solver": 72}


def test_experiment_selects_exact_assignments_after_randomization(
    tmp_path: Path,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    selected = [
        "da-1-1--rep-001--solver-test-solver--full-static",
        "da-2-1--rep-003--solver-test-solver--user-simulator-online-rubric",
    ]
    payload = _payload(tmp_path)
    payload["assignment_selection"] = selected
    path = tmp_path / "selected.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    experiment = load_experiment(path)

    assert {item.assignment_id for item in experiment.assignments} == set(
        selected
    )
    assert [item.execution_order for item in experiment.assignments] == [1, 2]

    payload["assignment_selection"] = ["unknown-assignment"]
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    with pytest.raises(ValueError, match="unknown assignment IDs"):
        load_experiment(path)


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
        r"biomnibench-da-factorial-r10-[0-9a-f]{12}", first.experiment_id
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
    payload["outcome_audit"]["loss_weights"].pop("original_rubric_gap")
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
        "rubric_score_max_calls",
        "rubric_score_max_request_bytes",
        "rubric_score_max_output_tokens",
        "rubric_free_evaluation_max_calls",
        "rubric_free_evaluation_max_request_bytes",
        "rubric_free_evaluation_max_output_tokens",
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
    payload["outcome_audit"]["rubric_score_max_calls"] = invalid
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="positive integer"):
        load_experiment(path)


@pytest.mark.parametrize(
    ("field", "invalid", "message"),
    [
        ("prompt", 7, "protocol prompt"),
        ("judge_model", None, "judge_model"),
        ("judge_model", 7, "judge_model"),
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


def test_experiment_requires_exact_solver_keys(tmp_path: Path) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["solvers"][0]["retry"] = 1
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="solver test-solver keys must be exactly"):
        load_experiment(path)


def test_experiment_rejects_unknown_solver_provider(tmp_path: Path) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["solvers"][0]["provider"] = "unknown-provider"
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="solver test-solver provider must be one of"):
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
        ("provider", 1, "solver test-solver provider"),
        ("model", 1, "solver test-solver model"),
        ("retries", "1", "solver test-solver retries"),
        ("timeout_seconds", 0, "solver test-solver timeout_seconds"),
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
    payload["solvers"][0][field] = invalid
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match=message):
        load_experiment(path)


@pytest.mark.parametrize(
    ("field", "invalid", "message"),
    [
        ("condition_id", 123, "condition_id"),
        ("feedback_policy", 123, "condition feedback_policy"),
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


def test_experiment_accepts_a_complete_selected_feedback_by_rubric_factorial(
    tmp_path: Path,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["conditions"] = [
        condition
        for condition in payload["conditions"]
        if condition["feedback_policy"] in {"full", "user_simulator"}
    ]
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    experiment = load_experiment(path)

    assert len(experiment.payload["conditions"]) == 6
    assert len(experiment.assignments) == 36


def test_experiment_rejects_an_incomplete_selected_factorial(
    tmp_path: Path,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["conditions"].pop()
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="each selected"):
        load_experiment(path)


def test_experiment_rejects_a_mislabeled_factorial_cell(tmp_path: Path) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["conditions"][0]["condition_id"] = "wrong-label"
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="condition_id must be 'full-static'"):
        load_experiment(path)


def test_experiment_rejects_obsolete_condition_level_prompts(
    tmp_path: Path,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["conditions"][1]["prompt"] = "base"
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="each condition requires"):
        load_experiment(path)


def test_experiment_rejects_obsolete_protocol_level_feedback_policy(
    tmp_path: Path,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["protocol"]["feedback_policy"] = "full"
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="protocol keys must be exactly"):
        load_experiment(path)


@pytest.mark.parametrize(("minimum", "maximum"), ((1, 10), (2, 2)))
def test_experiment_requires_a_reachable_post_update_window(
    tmp_path: Path,
    minimum: int,
    maximum: int,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["protocol"]["min_revisions"] = minimum
    payload["protocol"]["max_revisions"] = maximum
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="post-update detection window"):
        load_experiment(path)


@pytest.mark.parametrize(
    ("field", "invalid", "message"),
    [
        ("models", ["judge-a", 3], "list of strings"),
        ("primary_rule", 1, "primary_rule must be a string"),
        ("max_input_tokens", "250000", "max input tokens"),
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


def test_experiment_rejects_the_removed_any_detects_rule(tmp_path: Path) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["outcome_audit"]["primary_rule"] = "any_detects"
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="primary detection rule is invalid"):
        load_experiment(path)


@pytest.mark.parametrize("selected_variant", [-1, 3, "0", True])
def test_experiment_rejects_invalid_selected_paraphrase_variant(
    tmp_path: Path,
    selected_variant: object,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["rubric_paraphrases"]["selected_variant"] = selected_variant
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="selected rubric paraphrase variant"):
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
    changed["protocol"]["max_revisions"] = 11  # type: ignore[index]
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


def test_paperbench_experiment_accepts_the_exact_pinned_dev_split(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_ids = (
        "semantic-self-consistency",
        "self-expansion",
        "self-composing-policies",
    )
    for task_id in task_ids:
        _task(tmp_path, task_id)
        task = tmp_path / "tasks" / task_id
        (task / "environment" / "data" / "paper.md").write_text("# Paper\n")
        (task / "tests" / "paperbench.json").write_text("{}\n")
    payload = _payload(tmp_path)
    payload["benchmark"] = "paperbench-code-dev"
    payload["tasks"] = list(task_ids)
    payload["protocol"]["review"] = "workspace"  # type: ignore[index]
    path = tmp_path / "paperbench.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    monkeypatch.setattr(
        paperbench_contract_module,
        "validate_paperbench_code_dataset",
        lambda _path, *, source_split: None,
    )

    experiment = load_experiment(path)

    assert experiment.task_ids == task_ids


def test_paperbench_experiment_rejects_a_partial_official_split(
    tmp_path: Path,
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

    with pytest.raises(ValueError, match="official 3-paper dev split"):
        load_experiment(path)


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
        experiment=str(path), max_concurrency=2, resume=True
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
    payload["protocol"]["feedback_simulator"] = {  # type: ignore[index]
        "model": "gpt-simulated-user",
        "max_output_tokens": 1_024,
        "max_concerns": 2,
        "max_history_bytes": 131_072,
        "max_request_bytes": 1_048_576,
        "max_retries": 1,
    }
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    experiment = load_experiment(path)
    config = experiment.feedback_simulator_config("user_simulator")

    assert config is not None
    assert config.model == "gpt-simulated-user"
    assert config.max_output_tokens == 1_024
    assert config.max_concerns == 2
    assert config.max_history_bytes == 131_072
    assert config.max_request_bytes == 1_048_576
    assert experiment.feedback_simulator_config("full") is None


def test_experiment_rejects_the_removed_simulated_user_policy_name(
    tmp_path: Path,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["conditions"][0]["feedback_policy"] = "simulated_user"  # type: ignore[index]
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))

    with pytest.raises(ValueError, match="simulated_user"):
        load_experiment(path)


def test_yaml_experiment_rejects_broken_dag(tmp_path: Path) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    payload = _payload(tmp_path)
    payload["dag"]["detect"]["depends_on"] = []  # type: ignore[index]
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    with pytest.raises(ValueError, match="invalid dependencies"):
        load_experiment(path)


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
        key=lambda item: item.execution_order,
    )
    optimizer = experiment.task_dir(assignment.task_id) / "tests" / "rubric.txt"
    monkeypatch.setattr(
        paraphrase_validation_module,
        "resolve_paraphrase_selection",
        lambda *_args, **_kwargs: SimpleNamespace(optimizer_path=optimizer),
    )

    assert seed.agent.quiet is True
    assert study._revision_config(assignment, resume=False).agent.quiet is True


def test_study_shares_one_pretreatment_rubric_across_elicitation_arms(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-2-1")
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(_payload(tmp_path), sort_keys=False))
    experiment = load_experiment(path)
    study = StudyRunner(StudyRunConfig(
        experiment=experiment,
        seed_run_dir=tmp_path / "seeds",
        paraphrase_run_dir=tmp_path / "paraphrases",
        output_dir=tmp_path / "study",
        max_concurrency=1,
    ))
    task_id = "da-1-1"
    optimizer = experiment.task_dir(task_id) / "tests" / "rubric.txt"
    monkeypatch.setattr(
        paraphrase_validation_module,
        "resolve_paraphrase_selection",
        lambda *_args, **_kwargs: SimpleNamespace(optimizer_path=optimizer),
    )
    assignments = [
        assignment
        for assignment in experiment.assignments
        if assignment.task_id == task_id
        and experiment.condition(assignment.condition_id)[
            "rubric_policy"
        ] in {"offline_elicitation", "online_elicitation"}
    ]
    roots = {
        study._revision_config(assignment, resume=False).pretreatment_rubric_dir
        for assignment in assignments
    }

    assert len(roots) == 1
    assert next(iter(roots)).parent == study.pretreatment_root / task_id


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
    ))

    assert result == 0
    assert calls == ["seed", "paraphrase", "revise", "detect"]
    assert roots["seed"].is_dir()
    assert roots["paraphrase"].is_dir()


def test_detect_runs_score_methods_when_direct_panel_has_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rubric_gen.submission_revision.evaluation.direct as direct_audit_module
    import rubric_gen.submission_revision.evaluation.targets as targets_module
    import rubric_gen.submission_revision.evaluation.report as report_module
    import rubric_gen.submission_revision.evaluation.runner as outcome_panel_module

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
    targets = (object(),)

    def direct(config: object) -> int:
        direct_configs.append(config)
        calls.append("direct")
        return 1

    class RubricScoreRunnerStub:
        def __init__(
            self,
            config: object,
            loaded_targets: object,
        ) -> None:
            configs.append(config)
            assert loaded_targets is targets

        def preflight(self) -> None:
            calls.append("rubric_score-preflight")

        def run(self) -> int:
            calls.append("rubric_score")
            return 0

    class RubricFreeRunnerStub:
        def __init__(
            self,
            config: object,
            loaded_targets: object,
        ) -> None:
            configs.append(config)
            assert loaded_targets is targets

        def preflight(self) -> None:
            calls.append("rubric_free_score-preflight")

        def run(self) -> int:
            calls.append("rubric_free_score")
            return 0

    monkeypatch.setattr(commands_module, "load_experiment", lambda _path: experiment)
    monkeypatch.setattr(
        targets_module,
        "load_evaluation_targets",
        lambda _config: calls.append("target-loading") or targets,
    )
    monkeypatch.setattr(direct_audit_module, "run_direct_detection", direct)
    monkeypatch.setattr(
        outcome_panel_module,
        "RubricScoreRunner",
        RubricScoreRunnerStub,
    )
    monkeypatch.setattr(
        outcome_panel_module,
        "RubricFreeScoreRunner",
        RubricFreeRunnerStub,
    )
    monkeypatch.setattr(
        report_module,
        "write_evaluation_report",
        lambda _path: calls.append("combined"),
    )

    status = commands_module.run_detect(argparse.Namespace(
        experiment="experiment.yaml",
        max_concurrency=3,
        resume=True,
    ))

    assert status == 1
    assert calls == [
        "target-loading",
        "rubric_score-preflight",
        "rubric_free_score-preflight",
        "direct",
        "direct",
        "direct",
        "direct",
        "rubric_score",
        "rubric_free_score",
        "combined",
    ]
    assert len(direct_configs) == 4
    assert {config.window.value for config in direct_configs} == {
        "full_trajectory",
        "post_update",
        "final_artifact",
        "final_revision",
    }
    assert all(not hasattr(config, "vllm_endpoints") for config in configs)


def test_detect_does_not_combine_an_incomplete_score_panel(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rubric_gen.submission_revision.evaluation.direct as direct_audit_module
    import rubric_gen.submission_revision.evaluation.targets as targets_module
    import rubric_gen.submission_revision.evaluation.report as report_module
    import rubric_gen.submission_revision.evaluation.runner as outcome_panel_module

    experiment = SimpleNamespace(
        dag={
            "revise": {"output_dir": str(tmp_path / "study")},
            "paraphrase": {"output_dir": str(tmp_path / "paraphrases")},
            "detect": {"output_dir": str(tmp_path / "detect")},
        },
        outcome_audit={"models": ["strong-a", "strong-b"]},
    )
    calls: list[str] = []

    class RunnerStub:
        def __init__(self, _config: object, _targets: object) -> None:
            pass

        def preflight(self) -> None:
            pass

        def run(self) -> int:
            return 1

    monkeypatch.setattr(commands_module, "load_experiment", lambda _path: experiment)
    monkeypatch.setattr(
        targets_module,
        "load_evaluation_targets",
        lambda _config: (object(),),
    )
    monkeypatch.setattr(direct_audit_module, "run_direct_detection", lambda _config: 0)
    monkeypatch.setattr(outcome_panel_module, "RubricScoreRunner", RunnerStub)
    monkeypatch.setattr(outcome_panel_module, "RubricFreeScoreRunner", RunnerStub)
    monkeypatch.setattr(
        report_module,
        "write_evaluation_report",
        lambda _path: calls.append("combined"),
    )

    assert commands_module.run_detect(argparse.Namespace(
        experiment="experiment.yaml",
        max_concurrency=3,
        resume=True,
    )) == 1
    assert calls == []


def test_detect_runs_rubric_free_stage_after_rubric_score_exception(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rubric_gen.submission_revision.evaluation.direct as direct_audit_module
    import rubric_gen.submission_revision.evaluation.targets as targets_module
    import rubric_gen.submission_revision.evaluation.report as report_module
    import rubric_gen.submission_revision.evaluation.runner as outcome_panel_module

    experiment = SimpleNamespace(
        dag={
            "revise": {"output_dir": str(tmp_path / "study")},
            "paraphrase": {"output_dir": str(tmp_path / "paraphrases")},
            "detect": {"output_dir": str(tmp_path / "detect")},
        },
        outcome_audit={"models": ["strong-a", "strong-b"]},
    )
    calls: list[str] = []

    class RubricScoreRunnerStub:
        def __init__(
            self,
            _config: object,
            _targets: object,
        ) -> None:
            pass

        def preflight(self) -> None:
            calls.append("rubric_score-preflight")

        def run(self) -> int:
            calls.append("rubric_score")
            raise RuntimeError("strong judge unavailable")

    class RubricFreeRunnerStub:
        def __init__(
            self,
            _config: object,
            _targets: object,
        ) -> None:
            pass

        def preflight(self) -> None:
            calls.append("rubric_free_score-preflight")

        def run(self) -> int:
            calls.append("rubric_free_score")
            return 0

    monkeypatch.setattr(commands_module, "load_experiment", lambda _path: experiment)
    monkeypatch.setattr(
        targets_module,
        "load_evaluation_targets",
        lambda _config: (object(),),
    )
    monkeypatch.setattr(
        direct_audit_module,
        "run_direct_detection",
        lambda _config: 0,
    )
    monkeypatch.setattr(
        outcome_panel_module,
        "RubricScoreRunner",
        RubricScoreRunnerStub,
    )
    monkeypatch.setattr(
        outcome_panel_module,
        "RubricFreeScoreRunner",
        RubricFreeRunnerStub,
    )
    monkeypatch.setattr(
        report_module,
        "write_evaluation_report",
        lambda _path: calls.append("combined"),
    )

    with pytest.raises(RuntimeError, match="rubric_score"):
        commands_module.run_detect(argparse.Namespace(
            experiment="experiment.yaml",
            max_concurrency=3,
            resume=False,
        ))

    assert calls == [
        "rubric_score-preflight",
        "rubric_free_score-preflight",
        "rubric_score",
        "rubric_free_score",
    ]


def test_detect_stops_before_provider_work_when_stage_preflight_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import rubric_gen.submission_revision.evaluation.direct as direct_audit_module
    import rubric_gen.submission_revision.evaluation.targets as targets_module
    import rubric_gen.submission_revision.evaluation.report as report_module
    import rubric_gen.submission_revision.evaluation.runner as outcome_panel_module

    experiment = SimpleNamespace(
        dag={
            "revise": {"output_dir": str(tmp_path / "study")},
            "paraphrase": {"output_dir": str(tmp_path / "paraphrases")},
            "detect": {"output_dir": str(tmp_path / "detect")},
        },
        outcome_audit={"models": ["strong-a"]},
    )
    calls: list[str] = []

    class RubricScoreRunnerStub:
        def __init__(
            self,
            _config: object,
            _targets: object,
        ) -> None:
            pass

        def preflight(self) -> None:
            calls.append("rubric_score-preflight")

        def run(self) -> int:
            calls.append("rubric_score-provider")
            return 0

    class RubricFreeRunnerStub:
        def __init__(
            self,
            _config: object,
            _targets: object,
        ) -> None:
            pass

        def preflight(self) -> None:
            calls.append("rubric_free_score-preflight")
            raise RuntimeError("rubric_free_evaluation calls exceeds its hard cap")

        def run(self) -> int:
            calls.append("rubric_free_score-provider")
            return 0

    monkeypatch.setattr(commands_module, "load_experiment", lambda _path: experiment)
    monkeypatch.setattr(
        targets_module,
        "load_evaluation_targets",
        lambda _config: (object(),),
    )
    monkeypatch.setattr(
        direct_audit_module,
        "run_direct_detection",
        lambda _config: calls.append("direct-provider") or 0,
    )
    monkeypatch.setattr(
        outcome_panel_module,
        "RubricScoreRunner",
        RubricScoreRunnerStub,
    )
    monkeypatch.setattr(
        outcome_panel_module,
        "RubricFreeScoreRunner",
        RubricFreeRunnerStub,
    )
    monkeypatch.setattr(
        report_module,
        "write_evaluation_report",
        lambda _path: calls.append("combined"),
    )

    with pytest.raises(RuntimeError, match="calls exceeds its hard cap"):
        commands_module.run_detect(argparse.Namespace(
            experiment="experiment.yaml",
            max_concurrency=3,
            resume=False,
        ))

    assert calls == ["rubric_score-preflight", "rubric_free_score-preflight"]


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
        key=lambda item: item.execution_order,
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
    monkeypatch.setattr(
        paraphrase_validation_module,
        "validate_paraphrase_run",
        lambda *_: None,
    )
    monkeypatch.setattr(
        paraphrase_validation_module,
        "resolve_paraphrase_selection",
        lambda *_args, **_kwargs: SimpleNamespace(optimizer_path=optimizer),
    )
    monkeypatch.setattr(
        study_module,
        "run_submission_revision",
        lambda revision, **_kwargs: revisions.append(revision),
    )
    monkeypatch.setattr(
        study_validation_module,
        "validate_completed_revision",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        runner,
        "_prepare_pretreatment_rubrics",
        lambda *_assignments: None,
    )

    assert runner.run() == 0

    finished = json.loads((output / "study.json").read_text())
    recovered = finished["records"][0]
    assert finished["status"] == "completed"
    assert recovered["status"] == "completed"
    assert recovered["attempt_count"] == 5
    assert recovered["pid"] == os.getpid()
    assert len(revisions) == 36


def test_study_resume_trusts_completed_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _task(tmp_path, "da-1-1")
    payload = _payload(tmp_path)
    payload["tasks"] = ["da-1-1"]
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    experiment = load_experiment(path)
    output = tmp_path / "runs" / "revisions"
    output.mkdir(parents=True)
    runner = StudyRunner(StudyRunConfig(
        experiment=experiment,
        seed_run_dir=tmp_path / "runs" / "seeds",
        paraphrase_run_dir=tmp_path / "runs" / "paraphrases",
        output_dir=output,
        max_concurrency=1,
        resume=True,
    ))
    assignments = sorted(
        experiment.assignments,
        key=lambda item: item.execution_order,
    )
    manifest = runner._new_manifest(assignments)
    for record in manifest["records"]:  # type: ignore[union-attr]
        record["status"] = "completed"
    runner._write_manifest(manifest)

    def unexpected(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("resume revalidated a completed record")

    monkeypatch.setattr(
        paraphrase_validation_module,
        "validate_paraphrase_run",
        lambda *_: None,
    )
    monkeypatch.setattr(
        study_validation_module,
        "validate_completed_revision",
        unexpected,
    )
    monkeypatch.setattr(study_module, "run_submission_revision", unexpected)

    assert runner.run() == 0
    finished = json.loads((output / "study.json").read_text())
    assert finished["status"] == "completed"
    assert {record["status"] for record in finished["records"]} == {"completed"}


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
    monkeypatch.setattr(
        paraphrase_validation_module,
        "validate_paraphrase_run",
        lambda *_: None,
    )
    monkeypatch.setattr(
        paraphrase_validation_module,
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
    monkeypatch.setattr(
        runner,
        "_prepare_pretreatment_rubrics",
        lambda *_assignments: None,
    )

    assert runner.run() == 1
    error = capsys.readouterr().err
    assert "assignment failed: da-1-1--rep-" in error
    assert "RuntimeError: scoring identity mismatch" in error


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
