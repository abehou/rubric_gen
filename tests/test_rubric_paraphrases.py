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
    wording = _wording(index)
    return (
        "RUBRIC: Result quality\n\n"
        "Total Points: 100\n\n"
        f"Criterion 1: {wording['criterion_1_title']}\n\n"
        f"Description: {wording['criterion_1_description']}\n\n"
        "Levels: A=100 B=50 C=0\n"
        f"[A]: {wording['criterion_1_level_A']}\n"
        f"[B]: {wording['criterion_1_level_B']}\n"
        f"[C]: {wording['criterion_1_level_C']}\n"
    )


def _wording(index: int) -> dict[str, str]:
    titles = (
        "Accurate task result",
        "Correct task outcome",
        "Validity of the result",
    )
    return {
        "criterion_1_title": titles[index],
        "criterion_1_description": (
            "This criterion checks whether the task result is correct."
        ),
        "criterion_1_level_A": (
            "Evidence supports a result that is both complete and correct."
        ),
        "criterion_1_level_B": (
            "The result stays useful despite one clear material limitation."
        ),
        "criterion_1_level_C": (
            "The evidence does not support a valid and usable result."
        ),
    }


def _wording_response(index: int) -> dict[str, object]:
    return {
        "wording": [
            {"field": field, "text": text}
            for field, text in _wording(index).items()
        ]
    }


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
        "kind": "rubric-gen-randomized-experiment",
        "benchmark": "biomnibench-da",
        "tasks_dir": "tasks",
        "tasks": list(task_ids),
        "randomization": {"seed": 41, "replicates": 2},
        "conditions": [{
            "condition_id": "diligent-fixed",
            "prompt": "diligent",
            "rubric_policy": "fixed",
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
    schemas: list[dict[str, object]] = []

    def generate(_model, request):
        match = re.search(r"Paraphrase variant: (\d+)", request.evidence)
        assert match is not None
        index = int(match.group(1))
        calls.append(index)
        schemas.append(request.schema)
        return GenerationResult(
            text=json.dumps(_wording_response(index)),
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
    assert selection.optimizer_path.read_text().startswith("RUBRIC: Result quality\n")
    assert len(selection.holdout_paths) == 2
    assert selection.optimizer_path not in selection.holdout_paths
    assert all("rubric_text" not in json.dumps(schema) for schema in schemas)
    assert all(
        set(schema["properties"]) == {"wording"}  # type: ignore[index]
        for schema in schemas
    )
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
            text=json.dumps(_wording_response(int(variant.group(1)))),
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
    with pytest.raises(ValueError, match="level values"):
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


def test_wording_only_paraphrase_keeps_penalty_points_and_rejects_number_drift(
    tmp_path: Path,
) -> None:
    experiment = _experiment(tmp_path)
    master_path = experiment.task_dir("da-1-1") / "tests" / "rubric.txt"
    master = _master() + (
        "\nCriterion 2: Source reliability\n\n"
        "Description: Check all 21 cited values against their sources.\n\n"
        "Levels: A=0 B=-5 C=-10\n"
        "[A]: Every one of the 21 values is traceable.\n"
        "[B]: Most of the 21 values are traceable.\n"
        "[C]: The 21 values include unsupported claims.\n"
    )
    master_path.write_text(master)
    root = Path(str(experiment.dag["paraphrase"]["output_dir"]))

    def generate(_model, request):
        match = re.search(r"Paraphrase variant: (\d+)", request.evidence)
        assert match is not None
        variant_index = int(match.group(1))
        source = json.loads(
            request.evidence.split("<wording_fields_json>\n", 1)[1].split(
                "\n</wording_fields_json>", 1
            )[0]
        )
        wording = {
            item["field"]: item["text"].replace("correct", "valid")
            for item in source
        }
        wording["criterion_2_title"] = (
            "Reliability of sources",
            "Source evidence quality",
            "Traceability of sources",
        )[variant_index]
        wording["criterion_2_description"] = (
            "Verify all 21 cited values by using their sources."
        )
        wording["criterion_2_level_A"] = "Each of the 21 values is traceable."
        wording["criterion_2_level_B"] = "The majority of the 21 values is traceable."
        wording["criterion_2_level_C"] = (
            "Unsupported claims occur among the 21 values."
        )
        return GenerationResult(
            text=json.dumps({
                "wording": [
                    {"field": item["field"], "text": wording[item["field"]]}
                    for item in source
                ]
            }),
            provider="test",
            requested_model="test-paraphraser",
            effective_model="test-paraphraser",
            response_id="response",
            request_parameters={},
        )

    assert ParaphraseRunner(
        ParaphraseRunConfig(experiment, root, max_concurrency=2),
        generation_operation=generate,
    ).run() == 0
    variant = (root / "tasks" / "da-1-1" / "variant-000.txt").read_text()
    assert "Levels: A=0 B=-5 C=-10" in variant
    assert "Levels: A=100 B=50 C=0" in variant

    changed_number = variant.replace("all 21 cited values", "all 22 cited values")
    with pytest.raises(ValueError, match="changed its numbers"):
        validate_semantic_paraphrase(master, changed_number)
