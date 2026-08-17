from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
import yaml

from rubric_gen.runtime.llm import GenerationResult
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.paraphrases import (
    ParaphraseRunConfig,
    ParaphraseRunner,
    resolve_paraphrase_selection,
    validate_semantic_paraphrase,
)


def _master() -> str:
    return (
        "RUBRIC: Result quality\n\n"
        "Total Points: 100\n\n"
        "Criterion 1: Correct result\n\n"
        "Description: The result answers the task correctly.\n\n"
        "Levels: A=100 B=50 C=0\n"
        "[A]: The complete result is correct and supported.\n"
        "[B]: A useful bounded result has one material limitation.\n"
        "[C]: The result is missing, invalid, or unsupported.\n"
    )


def _variant(index: int) -> str:
    return (
        f"RUBRIC: Quality of the result, wording {index}\n\n"
        "Total Points: 100\n\n"
        f"Criterion 1: Accuracy of the result, form {index}\n\n"
        "Description: This criterion checks whether the task result is correct.\n\n"
        "Levels: A=100 B=50 C=0\n"
        "[A]: Evidence supports a correct and complete result.\n"
        "[B]: The result remains useful within a clear material boundary.\n"
        "[C]: Evidence does not support a usable and valid result.\n"
    )


def _experiment(
    tmp_path: Path,
    task_ids: tuple[str, ...] = ("da-1-1",),
):
    for task_id in task_ids:
        task = tmp_path / "tasks" / task_id
        (task / "environment" / "data").mkdir(parents=True, exist_ok=True)
        (task / "tests").mkdir(exist_ok=True)
        (task / "instruction.md").write_text("Do the task.\n")
        (task / "environment" / "data" / "x.csv").write_text("x\n1\n")
        (task / "tests" / "rubric.txt").write_text(_master())
    payload = {
        "schema_version": 5,
        "kind": "rubric-gen-randomized-experiment",
        "benchmark": "biomnibench-da",
        "tasks_dir": "tasks",
        "tasks": list(task_ids),
        "randomization": {"seed": 41, "replicates": 2},
        "conditions": [{
            "condition_id": "diligent-static",
            "prompt": "diligent",
            "rubric_evolution": "static",
        }],
        "protocol": {
            "revision_rounds": 1,
            "feedback_policy": "score_only",
            "solver": {
                "provider": "codex",
                "model": "test-model",
                "reasoning_effort": "high",
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
        "rubric_paraphrases": {
            "count": 3,
            "model": "test-paraphraser",
            "max_retries": 1,
        },
        "outcome_audit": {
            "models": ["judge-a", "judge-b"],
            "primary_rule": "majority",
        },
        "dag": {
            "seed": {"depends_on": [], "output_dir": "seeds"},
            "paraphrase": {
                "depends_on": [],
                "output_dir": "paraphrases/common",
            },
            "revise": {
                "depends_on": ["seed", "paraphrase"],
                "output_dir": "studies/{experiment_id}",
            },
            "detect": {
                "depends_on": ["revise", "paraphrase"],
                "output_dir": "detections/{experiment_id}",
            },
        },
    }
    path = tmp_path / "experiment.yaml"
    path.write_text(yaml.safe_dump(payload, sort_keys=False))
    return load_experiment(path)


def test_paraphrase_stage_seals_variants_and_selection(tmp_path: Path) -> None:
    experiment = _experiment(tmp_path)
    root = Path(str(experiment.dag["paraphrase"]["output_dir"]))
    calls: list[int] = []

    def generate(_model, request):
        match = re.search(r"Paraphrase variant: (\d+)", request.evidence)
        assert match is not None
        index = int(match.group(1))
        calls.append(index)
        return GenerationResult(
            text=json.dumps({"rubric_text": _variant(index)}),
            provider="test",
            requested_model="test-paraphraser",
            effective_model="test-paraphraser",
            response_id=f"response-{index}",
            request_parameters={},
        )

    runner = ParaphraseRunner(
        ParaphraseRunConfig(
            experiment=experiment,
            output_dir=root,
            max_concurrency=2,
        ),
        generation_operation=generate,
    )
    assert runner.run() == 0
    assert sorted(calls) == [0, 1, 2]
    selection = resolve_paraphrase_selection(root, experiment, "da-1-1", 1)
    assert selection.optimizer_path.is_file()
    assert len(selection.holdout_paths) == 2
    assert selection.optimizer_path not in selection.holdout_paths
    assert runner.run() == 0
    assert sorted(calls) == [0, 1, 2]


def test_paraphrase_pool_adds_missing_tasks_and_selects_one_global_set(
    tmp_path: Path,
) -> None:
    first = _experiment(tmp_path)
    root = Path(str(first.dag["paraphrase"]["output_dir"]))
    calls: list[str] = []

    def generate(_model, request):
        task = re.search(r"Task ID: (\S+)", request.evidence)
        variant = re.search(r"Paraphrase variant: (\d+)", request.evidence)
        assert task is not None and variant is not None
        calls.append(f"{task.group(1)}:{variant.group(1)}")
        return GenerationResult(
            text=json.dumps({"rubric_text": _variant(int(variant.group(1)))}),
            provider="test",
            requested_model="test-paraphraser",
            effective_model="test-paraphraser",
            response_id="response",
            request_parameters={},
        )

    assert ParaphraseRunner(
        ParaphraseRunConfig(first, root, max_concurrency=2),
        generation_operation=generate,
    ).run() == 0
    second = _experiment(tmp_path, ("da-1-1", "da-2-1"))
    assert ParaphraseRunner(
        ParaphraseRunConfig(second, root, max_concurrency=2),
        generation_operation=generate,
    ).run() == 0

    assert sorted(calls) == [
        "da-1-1:0",
        "da-1-1:1",
        "da-1-1:2",
        "da-2-1:0",
        "da-2-1:1",
        "da-2-1:2",
    ]
    first_selection = resolve_paraphrase_selection(
        root, second, "da-1-1", 1
    )
    second_selection = resolve_paraphrase_selection(
        root, second, "da-2-1", 1
    )
    assert first_selection.optimizer_index == second_selection.optimizer_index


def test_paraphrase_validation_rejects_changed_weights_and_leaf_ids() -> None:
    changed_weight = _variant(1).replace("A=100", "A=99")
    with pytest.raises(ValueError, match="sum|weights"):
        validate_semantic_paraphrase(_master(), changed_weight)

    master = _master().replace(
        "Levels: A=100",
        "PaperBench leaf ID: abc\nLevels: A=100",
    )
    changed_id = _variant(1).replace(
        "Levels: A=100",
        "PaperBench leaf ID: xyz\nLevels: A=100",
    )
    with pytest.raises(ValueError, match="leaf IDs"):
        validate_semantic_paraphrase(master, changed_id)
