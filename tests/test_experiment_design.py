from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

import rubric_gen.biomnibench.experiments as experiments_module
from rubric_gen.biomnibench.agent.models import AgentRunConfig
from rubric_gen.biomnibench.agent.prompts import PromptProfile
from rubric_gen.biomnibench.experiments import (
    DesignConfig,
    create_design,
    load_design,
)
from rubric_gen.biomnibench.revision.feedback import FeedbackPolicy


def _catalog(root: Path, count: int) -> Path:
    tasks = root / "tasks"
    for index in range(1, count + 1):
        task = tasks / f"da-{index}-1"
        (task / "environment" / "data").mkdir(parents=True)
        (task / "tests").mkdir()
        (task / "instruction.md").write_text(f"Task {index}.\n")
        (task / "environment" / "data" / "values.csv").write_text(
            f"x\n{index}\n"
        )
        (task / "tests" / "rubric.txt").write_text(
            "Criterion 1: Result\nLevels: A=100 B=50 C=0\n"
        )
    return tasks


def _config(tasks: Path, output: Path, **changes: object) -> DesignConfig:
    values: dict[str, object] = {
        "tasks_dir": tasks,
        "output_path": output,
        "protocol_id": "test-protocol",
        "dataset_revision": "dataset-commit-1",
        "random_seed": 42,
        "sample_size": 24,
        "replicates": 3,
        "revision_rounds": 10,
        "feedback_policy": FeedbackPolicy.SEMI,
        "treatment_prompt": PromptProfile.ANTI_RH,
        "agent": AgentRunConfig(
            provider="codex",
            model="test-model",
            reasoning_effort="minimal",
            retries=0,
            timeout_seconds=60,
        ),
        "judge_model": "test-judge",
        "minimum_detectable_effect": 0.30,
        "anticipated_discordance": 0.30,
    }
    values.update(changes)
    return DesignConfig(**values)  # type: ignore[arg-type]


@pytest.fixture(autouse=True)
def _sealed_provenance(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        experiments_module,
        "agent_provenance",
        lambda _agent, require_clean: {
            "sha256": "9" * 64,
            "require_clean": require_clean,
        },
    )


def test_design_is_balanced_randomized_and_round_trips(tmp_path: Path) -> None:
    tasks = _catalog(tmp_path, 24)
    design = create_design(_config(tasks, tmp_path / "design.json"))

    assert design.payload["schema_version"] == 7
    assert len(design.task_ids) == 24
    assert len(design.assignments) == 24 * 3 * 4
    assert design.outcome_audit["openai_reasoning_effort"] == "none"
    assert design.outcome_audit["protocol_version"] == 15
    assert design.outcome_audit["max_command_output_chars"] == 2_048
    assert design.outcome_audit["prompt_cache"] == (
        "task-model-serialized-stable-instructions-prefix"
    )
    cost_plan = design.payload["cost_plan"]
    assert isinstance(cost_plan, dict)
    assert cost_plan["nominal_total_stage_invocations"] == 8_208
    assert {item["execution_order"] for item in design.assignments} == set(
        range(1, 24 * 3 * 4 + 1)
    )
    blocks: dict[tuple[str, int], set[str]] = {}
    for assignment in design.assignments:
        key = (str(assignment["task_id"]), int(assignment["replicate"]))
        blocks.setdefault(key, set()).add(str(assignment["condition_id"]))
    assert all(len(conditions) == 4 for conditions in blocks.values())
    assert load_design(design.path).sha256 == design.sha256


def test_semantic_tampering_fails_even_after_rehash(tmp_path: Path) -> None:
    tasks = _catalog(tmp_path, 24)
    design = create_design(_config(tasks, tmp_path / "design.json"))
    payload = json.loads(design.path.read_text())
    payload["conditions"][0]["condition_id"] = "forged"
    payload["design_sha256"] = experiments_module._payload_sha256(payload)
    design.path.write_text(json.dumps(payload))

    with pytest.raises(ValueError, match="conditions"):
        load_design(design.path)


def test_underpowered_design_is_rejected(tmp_path: Path) -> None:
    tasks = _catalog(tmp_path, 24)
    with pytest.raises(ValueError, match="underpowered"):
        create_design(
            replace(
                _config(tasks, tmp_path / "design.json"),
                sample_size=23,
            )
        )


def test_confirmatory_design_uses_actual_validation_holdout(tmp_path: Path) -> None:
    tasks = _catalog(tmp_path, 48)
    validation = create_design(
        _config(
            tasks,
            tmp_path / "validation.json",
            protocol_id="validation-protocol",
            stage="validation",
        )
    )
    confirmatory = create_design(
        _config(
            tasks,
            tmp_path / "confirmatory.json",
            protocol_id="confirmatory-protocol",
            stage="confirmatory",
            validated_design_path=validation.path,
        )
    )

    assert set(validation.task_ids).isdisjoint(confirmatory.task_ids)
    assert confirmatory.payload["validated_design_sha256"] == validation.sha256
    assert confirmatory.payload["sampling"]["method"] == (
        "seeded_holdout_sample_without_replacement"
    )
    assert load_design(confirmatory.path).sha256 == confirmatory.sha256


def test_task_data_symlink_is_rejected(tmp_path: Path) -> None:
    tasks = _catalog(tmp_path, 24)
    target = tasks / "target.csv"
    target.write_text("x\n0\n")
    linked = tasks / "da-1-1" / "environment" / "data" / "linked.csv"
    linked.symlink_to(target)

    with pytest.raises(ValueError, match="non-regular"):
        create_design(_config(tasks, tmp_path / "design.json"))
