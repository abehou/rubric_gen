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
)
from rubric_gen.submission_revision.paraphrase_validation import (
    resolve_paraphrase_selection,
    validate_semantic_paraphrase,
)
from rubric_gen.submission_revision.paraphrase_protocol import wording_template


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
    return {"wording": _wording(index)}


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
        "randomization": {"seed": 41, "replicates": 3},
        "assignment_selection": "all",
        "conditions": [
            {
                "condition_id": f"{feedback_slug}-{rubric_slug}",
                "feedback_policy": feedback_policy,
                "rubric_policy": rubric_policy,
            }
            for feedback_slug, feedback_policy in (
                ("full", "full"),
                ("semi", "semi"),
                ("score-only", "score_only"),
                ("user-simulator", "user_simulator"),
            )
            for rubric_slug, rubric_policy in (
                ("static", "fixed"),
                ("offline-rubric", "offline_elicitation"),
                ("online-rubric", "online_elicitation"),
            )
        ],
        "protocol": {
            "revision_rounds": 1,
            "prompt": "diligent",
            "feedback_simulator": {
                "model": "test-simulator",
                "max_output_tokens": 1_024,
                "max_aspects": 2,
                "max_retries": 1,
            },
            "solver": {
                "provider": "codex",
                "model": "test-model",
                "reasoning_effort": "low",
                "service_tier": None,
                "executable": None,
                "retries": 1,
                "timeout_seconds": 60,
            },
            "judge_model": "test-judge",
            "rubric_name": "rubric.txt",
            "review": "trace",
            "max_review_chars": None,
            "rubric_proposer_model": "test-proposer",
            "rubric_proposer_max_retries": 1,
            "rubric_semantic_judge_model": "test-semantic-reviewer",
            "rubric_semantic_judge_max_calls_per_assignment": 1,
            "rubric_semantic_judge_max_request_bytes_per_call": 1_048_576,
            "rubric_semantic_judge_max_output_tokens_per_call": 32_768,
        },
        "rubric_paraphrases": {
            "count": 3,
            "model": "test-paraphraser",
            "max_retries": 1,
        },
        "outcome_audit": {
            "models": ["judge-a", "judge-b"],
            "primary_rule": "any_detect",
            "loss_weights": {
                "verifier_exploitation": 1,
                "dynamic_rubric_gap": 1,
            },
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
    assert all(
        schema["properties"]["wording"]["type"] == "object"  # type: ignore[index]
        for schema in schemas
    )
    metadata = json.loads(
        (root / "tasks/da-1-1/variant-000.json").read_text()
    )
    assert metadata["attempt_count"] == 1
    assert metadata["generation"]["strategy"] == "criterion-wise"
    assert [
        request["group_id"]
        for request in metadata["generation"]["requests"]
    ] == ["criterion-001"]
    assert runner.run() == 0
    assert sorted(calls) == [0, 1, 2]


def test_paraphrase_requests_keep_each_criterion_atomic() -> None:
    master = _master() + (
        "\nCriterion 2: Supported conclusion\n\n"
        "Description: The conclusion follows from the evidence.\n\n"
        "Levels: A=100 B=50 C=0\n"
        "[A]: The complete result is correct and supported.\n"
        "[B]: A useful bounded result has one material limitation.\n"
        "[C]: The result is missing, invalid, or unsupported.\n"
    )
    template = wording_template(master)

    assert len(template.slots) == 10
    assert [group.group_id for group in template.groups] == [
        "criterion-001",
        "criterion-002",
    ]
    first, second = template.groups
    assert set(first.fields) == {
        "criterion_1_title",
        "criterion_1_description",
        "criterion_1_level_A",
        "criterion_1_level_B",
        "criterion_1_level_C",
    }
    assert set(second.fields) == {
        "criterion_2_title",
        "criterion_2_description",
        "criterion_2_level_A",
        "criterion_2_level_B",
        "criterion_2_level_C",
    }

    first_wording = dict(first.fields)
    first_wording["criterion_1_title"] = "Accurate task outcome"
    first_wording["criterion_1_level_A"] = (
        "The complete outcome is accurate and has supporting evidence."
    )
    second_wording = dict(second.fields)
    second_wording["criterion_2_title"] = "Conclusion supported by evidence"
    second_wording["criterion_2_level_A"] = (
        "All evidence supports the complete and correct result."
    )
    rendered = template.render(
        first.expand(first_wording) | second.expand(second_wording)
    )

    assert first_wording["criterion_1_level_A"] in rendered
    assert second_wording["criterion_2_level_A"] in rendered
    for group in template.groups:
        schema = group.response_schema()["properties"]["wording"]
        assert schema["required"] == list(group.fields)
        assert set(schema["properties"]) == set(group.fields)


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


def test_incomplete_paraphrase_restarts_all_criteria(
    tmp_path: Path,
) -> None:
    experiment = _experiment(tmp_path)
    master_path = experiment.task_dir("da-1-1") / "tests" / "rubric.txt"
    master_path.write_text(
        _master()
        + "\nCriterion 2: Supported conclusion\n\n"
        + "Description: The conclusion follows from the evidence.\n\n"
        + "Levels: A=100 B=50 C=0\n"
        + "[A]: The complete conclusion is correct and supported.\n"
        + "[B]: A useful conclusion has one material limitation.\n"
        + "[C]: The conclusion is missing, invalid, or unsupported.\n"
    )
    root = Path(str(experiment.dag["paraphrase"]["output_dir"]))
    calls: list[tuple[int, str]] = []
    fail_target = True

    def generate(_model, request):
        nonlocal fail_target
        variant = re.search(r"Paraphrase variant: (\d+)", request.evidence)
        unit = re.search(r"Paraphrase unit: (\S+)", request.evidence)
        assert variant is not None and unit is not None
        index = int(variant.group(1))
        group_id = unit.group(1)
        calls.append((index, group_id))
        if fail_target and (index, group_id) == (0, "criterion-002"):
            text = "{"
        elif group_id == "criterion-001":
            text = json.dumps(_wording_response(index))
        else:
            source = json.loads(
                request.evidence.split("<wording_fields_json>\n", 1)[1].split(
                    "\n</wording_fields_json>", 1
                )[0]
            )
            source["criterion_2_title"] = (
                "Conclusion with evidence",
                "Evidence-supported conclusion",
                "Support for the conclusion",
            )[index]
            source["criterion_2_description"] = (
                "This criterion checks whether evidence supports the conclusion."
            )
            source["criterion_2_level_A"] = (
                "Evidence supports the complete and correct conclusion."
            )
            source["criterion_2_level_B"] = (
                "The conclusion remains useful despite one material limitation."
            )
            source["criterion_2_level_C"] = (
                "Evidence does not support a valid conclusion."
            )
            text = json.dumps({"wording": source})
        return GenerationResult(
            text=text,
            provider="test",
            requested_model="test-paraphraser",
            effective_model="test-paraphraser",
            response_id=f"response-{index}-{group_id}",
            request_parameters={},
        )

    config = ParaphraseRunConfig(experiment, root, max_concurrency=2)
    with pytest.raises(RuntimeError, match="criterion-002"):
        ParaphraseRunner(config, generation_operation=generate).run()
    assert calls.count((0, "criterion-002")) == 2
    assert all(
        calls.count((index, group_id)) == 1
        for index in range(3)
        for group_id in ("criterion-001", "criterion-002")
        if (index, group_id) != (0, "criterion-002")
    )
    assert not (root / "tasks/da-1-1/variant-000.txt").exists()

    calls.clear()
    fail_target = False
    assert ParaphraseRunner(config, generation_operation=generate).run() == 0
    assert sorted(calls) == [(0, "criterion-001"), (0, "criterion-002")]
    metadata = json.loads(
        (root / "tasks/da-1-1/variant-000.json").read_text()
    )
    assert metadata["attempt_count"] == 2
    assert [
        request["attempt_count"]
        for request in metadata["generation"]["requests"]
    ] == [1, 1]


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


def test_paraphrase_validation_rejects_duplicate_criterion_titles() -> None:
    second_master = (
        "\nCriterion 2: Evidence quality\n\n"
        "Description: The evidence supports the result.\n\n"
        "Levels: A=40 B=20 C=0\n"
        "[A]: The evidence is complete.\n"
        "[B]: The evidence is partial.\n"
        "[C]: The evidence is absent.\n"
    )
    second_candidate = second_master.replace(
        "Criterion 2: Evidence quality",
        "Criterion 2: Accurate task result",
    )

    with pytest.raises(ValueError, match="duplicate criterion titles"):
        validate_semantic_paraphrase(
            _master() + second_master,
            _variant(0) + second_candidate,
        )


def test_paraphrase_runner_repairs_only_the_colliding_title(
    tmp_path: Path,
) -> None:
    experiment = _experiment(tmp_path)
    master_path = experiment.task_dir("da-1-1") / "tests" / "rubric.txt"
    master_path.write_text(
        _master()
        + "\nCriterion 2: Evidence quality\n\n"
        + "Description: The evidence supports the result.\n\n"
        + "Levels: A=40 B=20 C=0\n"
        + "[A]: The evidence is complete.\n"
        + "[B]: The evidence is partial.\n"
        + "[C]: The evidence is absent.\n"
    )
    root = Path(str(experiment.dag["paraphrase"]["output_dir"]))
    calls: list[tuple[int, str, bool]] = []

    def generate(_model, request):
        variant = re.search(r"Paraphrase variant: (\d+)", request.evidence)
        unit = re.search(r"Paraphrase unit: (\S+)", request.evidence)
        assert variant is not None and unit is not None
        index = int(variant.group(1))
        group_id = unit.group(1)
        is_repair = "duplicates criterion_1_title" in request.evidence
        calls.append((index, group_id, is_repair))
        if group_id == "criterion-001":
            wording = _wording(index)
        else:
            wording = json.loads(
                request.evidence.split("<wording_fields_json>\n", 1)[1].split(
                    "\n</wording_fields_json>", 1
                )[0]
            )
            wording["criterion_2_title"] = (
                "Independent evidence conclusion"
                if is_repair
                else (
                    "Accurate task result",
                    "Evidence-supported conclusion",
                    "Support for the conclusion",
                )[index]
            )
            wording["criterion_2_description"] = (
                "This criterion checks whether evidence supports the result."
            )
            wording["criterion_2_level_A"] = (
                "Complete evidence supports the result."
            )
            wording["criterion_2_level_B"] = (
                "Partial evidence supports the result."
            )
            wording["criterion_2_level_C"] = (
                "No evidence supports the result."
            )
        return GenerationResult(
            text=json.dumps({"wording": wording}),
            provider="test",
            requested_model="test-paraphraser",
            effective_model="test-paraphraser",
            response_id=f"response-{index}-{group_id}-{is_repair}",
            request_parameters={},
        )

    assert ParaphraseRunner(
        ParaphraseRunConfig(experiment, root, max_concurrency=2),
        generation_operation=generate,
    ).run() == 0
    assert calls.count((0, "criterion-001", False)) == 1
    assert calls.count((0, "criterion-002", False)) == 1
    assert calls.count((0, "criterion-002", True)) == 1
    variant = (root / "tasks/da-1-1/variant-000.txt").read_text()
    assert "Criterion 2: Independent evidence conclusion" in variant
    metadata = json.loads(
        (root / "tasks/da-1-1/variant-000.json").read_text()
    )
    assert metadata["attempt_count"] == 3
    assert [
        request["attempt_count"]
        for request in metadata["generation"]["requests"]
    ] == [1, 2]


def test_wording_only_paraphrase_keeps_penalty_points_and_rejects_number_drift(
    tmp_path: Path,
) -> None:
    experiment = _experiment(tmp_path)
    master_path = experiment.task_dir("da-1-1") / "tests" / "rubric.txt"
    master = _master() + (
        "\nCriterion 2: Source thresholds 20, 10, and 5.2\n\n"
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
        unit = re.search(r"Paraphrase unit: (\S+)", request.evidence)
        assert match is not None and unit is not None
        variant_index = int(match.group(1))
        source = json.loads(
            request.evidence.split("<wording_fields_json>\n", 1)[1].split(
                "\n</wording_fields_json>", 1
            )[0]
        )
        wording = {
            field: text.replace("correct", "valid")
            for field, text in source.items()
        }
        if unit.group(1) == "criterion-002":
            first, second, third = re.findall(
                r"«NUMBER_[A-Z]+»",
                source["criterion_2_title"],
            )
            wording["criterion_2_title"] = (
                f"Source thresholds {first}, then {second}, then {third}",
                f"Ordered source thresholds: {first}, {second}, and {third}",
                f"Threshold sequence: {first}, {second}, and {third}",
            )[variant_index]
            count = re.findall(
                r"«NUMBER_[A-Z]+»",
                source["criterion_2_description"],
            )[0]
            wording["criterion_2_description"] = (
                f"Verify all {count} cited values by using their sources."
            )
            count = re.findall(
                r"«NUMBER_[A-Z]+»",
                source["criterion_2_level_A"],
            )[0]
            wording["criterion_2_level_A"] = (
                f"Each of the {count} values is traceable."
            )
            wording["criterion_2_level_B"] = (
                f"The majority of the {count} values is traceable."
            )
            wording["criterion_2_level_C"] = (
                f"Unsupported claims occur among the {count} values."
            )
            title_pattern = request.schema["properties"]["wording"][  # type: ignore[index]
                "properties"
            ]["criterion_2_title"]["pattern"]
            assert re.fullmatch(title_pattern, wording["criterion_2_title"])
            assert re.fullmatch(
                title_pattern,
                f"Source thresholds {third}, then {first}, then {second}",
            ) is not None
        return GenerationResult(
            text=json.dumps({"wording": wording}),
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

    numeric_group = wording_template(master).groups[1]
    injected = dict(numeric_group.fields)
    injected["criterion_2_title"] = (
        "৫.২ " + injected["criterion_2_title"]
    )
    with pytest.raises(ValueError, match="changed its numbers"):
        numeric_group.expand(injected)
