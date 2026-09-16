"""Provider-free checks for absolute task-required enforcement."""

import json
from types import SimpleNamespace

import pytest

from rubric_gen.submission_revision import task_paraphrase_required_prompts as prior_prompts
from rubric_gen.submission_revision import task_required_enforced_prompts as prompts
from rubric_gen.submission_revision.rubric_generation import RubricGeneration
from rubric_gen.submission_revision.task_paraphrase_required_stage import TraceStagesV2
from rubric_gen.submission_revision.task_required_enforced_schema import (
    EnforcementContract,
    enforcement_schema,
)
from rubric_gen.submission_revision.task_required_enforcement import (
    DURABLE_DELIVERY_VERSION,
    DURABLE_VERSION,
    REQUIREMENT_ONLY_VERSION,
    SOURCE_BOUND_VERSION,
    WITNESS_FROZEN_VERSION,
    VERSION,
    build_execution_witness,
    current_submission_artifact,
    frozen_execution_witness,
    select_enforcement,
)
from rubric_gen.submission_revision.trace_defense_delivery import (
    numeric_literals,
    select_reminder,
)
from rubric_gen.submission_revision.trace_defense_evidence_v2 import PublicDocument
from rubric_gen.submission_revision.trace_defense_registry import SOURCE_SCHEDULE, prompt_hashes, recipe
from rubric_gen.submission_revision.task_paraphrase_required import (
    _encode_supported_compiled_criterion,
)
from test_rubric_evolution import _rubric


def _proposer():
    contract = SimpleNamespace(record=lambda: {"model": "stub"})
    return SimpleNamespace(red_team_trace_version=VERSION, max_retries=0,
                           proposer_contract=contract)


def test_recipe_adds_only_enforcement_prompt_to_prior_scientific_stages(tmp_path):
    assert recipe(VERSION).learning_module == "task_paraphrase_required"
    for name in prior_prompts.STAGES:
        assert prompt_hashes(VERSION)[name] == prompt_hashes(prior_prompts.PROMPT_VERSION)[name]
    assert set(prompt_hashes(VERSION)) == set(prompt_hashes(prior_prompts.PROMPT_VERSION)) | {"enforcement"}
    docs = {"task": PublicDocument("task", "Do the analysis.\n")}
    validator = EnforcementContract("enforcement", enforcement_schema(docs), docs, {"task": "task"})
    request = TraceStagesV2(_proposer(), tmp_path).request("enforcement", {"scope": "x"}, validator)
    assert request["prompt_version"] == VERSION
    assert request["prompt"] == prompts.ENFORCEMENT_V1


def test_contract_requires_explicit_obligation_and_current_failure_references():
    docs = {
        "task": PublicDocument("task", "Report the requested table.\n"),
        "artifact": PublicDocument("artifact", "No table is reported.\n"),
        "execution_witness": PublicDocument("execution_witness", "No output file exists.\n"),
    }
    contract = EnforcementContract("enforcement", enforcement_schema(docs), docs,
                                   {name: name for name in docs})
    response = {
        "decision": "correct",
        "requirement": "Include the explicitly requested table.",
        "corrective_action": "Generate the table from the supplied data and report it.",
        "preserve_supported_work": "Keep the supported narrative findings.",
        "evidence_refs": [
            {"source_id": "task", "start_line": 1, "end_line": 1},
            {"source_id": "execution_witness", "start_line": 1, "end_line": 1},
        ],
        "reason": "The task requires a table, but the execution witness contains no output file.",
    }
    assert set(contract.validate(response)) == {"evidence_refs"}
    response["evidence_refs"] = response["evidence_refs"][:1]
    with pytest.raises(ValueError, match="missing_current_failure_source"):
        contract.validate(response)


def test_execution_witness_keeps_failed_output_even_when_exit_is_zero(tmp_path):
    submission = tmp_path / "submissions" / "s000"
    workspace = submission / "workspace"
    workspace.mkdir(parents=True)
    event = {
        "type": "item.completed",
        "item": {
            "id": "exec-1", "type": "command_execution", "status": "completed",
            "command": "python analysis.py", "exit_code": 0,
            "aggregated_output": "Traceback (most recent call last):\nValueError: empty input\n",
        },
    }
    (submission / "trajectory.stream.jsonl").write_text(json.dumps(event) + "\n")
    (workspace / "answer.txt").write_text("answer")
    (workspace / "instruction.md").write_text("source")
    (workspace / "data").mkdir()
    (workspace / "data" / "large.csv").write_text("source data")
    witness, record = build_execution_witness(tmp_path, 0)
    assert "exit_code=0" in witness and "Traceback" in witness and "ValueError" in witness
    assert [item["path"] for item in record["generated_files"]] == ["answer.txt"]
    assert record["completed_command_count"] == 1


def test_source_bound_artifact_survives_an_unincluded_sidecar(tmp_path):
    checkpoint = tmp_path / "red-team" / "checkpoint-0002"
    checkpoint.mkdir(parents=True)
    digest = "a" * 64
    (checkpoint / "manifest.json").write_text(json.dumps({
        "checkpoint": 2,
        "included": False,
        "source_artifact_sha256": digest,
    }))
    expected = SimpleNamespace(artifact_id="artifact-current", content_sha256=digest)
    history = SimpleNamespace(artifacts=(
        SimpleNamespace(artifact_id="artifact-old", content_sha256="b" * 64),
        expected,
    ))
    artifact, binding = current_submission_artifact(
        history=history, output_dir=tmp_path, source_checkpoint=2,
    )
    assert artifact is expected
    assert binding["sidecar_included"] is False
    assert binding["source_artifact_sha256"] == digest


def test_frozen_witness_replays_after_historical_workspace_cleanup(tmp_path):
    submission = tmp_path / "submissions" / "s000"
    workspace = submission / "workspace"
    workspace.mkdir(parents=True)
    (submission / "trajectory.stream.jsonl").write_text('{"type":"noop"}\n')
    (submission / "snapshot.json").write_text(json.dumps({
        "submission_id": "s000", "workspace_sha256": "c" * 64,
    }))
    script = workspace / "analysis.py"
    script.write_text("print('analysis')\n")
    first = frozen_execution_witness(tmp_path, 0)
    script.unlink()
    (submission / "snapshot.json").write_text(json.dumps({
        "submission_id": "s000", "workspace_sha256": "d" * 64,
    }))
    second = frozen_execution_witness(tmp_path, 0)
    assert second == first
    assert "analysis.py" in second[0]


def test_overlong_task_required_proposal_is_rejected_without_failing_update():
    assert _encode_supported_compiled_criterion(
        {"requirement": "x" * 650}, "task_required"
    ) is None
    encoded = _encode_supported_compiled_criterion(
        {"requirement": "short"}, "task_required"
    )
    assert encoded["requirement"].endswith("short")


def test_correct_enforcement_preempts_learned_reminder(tmp_path):
    generation = RubricGeneration(
        2, 0, _rubric(), (), 5, SOURCE_SCHEDULE, VERSION
    )
    root = tmp_path / "rubric-generations" / "generation-0002"
    root.mkdir(parents=True)
    response = {
        "decision": "correct",
        "requirement": "Report the requested table.",
        "corrective_action": "Create the table from supplied data.",
    }
    (root / "evolution.json").write_text(json.dumps({
        "task_required_enforcement": {"status": "valid_result", "response": response}
    }))
    selection, skipped = select_enforcement(
        generation=generation, root=tmp_path, instruction="Report the requested table.",
        numeric_literals=numeric_literals,
    )
    assert skipped == []
    assert selection["category"] == 0 and selection["corrective"] is True
    assert "Corrective action" in selection["requirement"]


def test_delivery_does_not_expose_new_numeric_literal(tmp_path):
    generation = RubricGeneration(2, 0, _rubric(), (), 5, SOURCE_SCHEDULE, VERSION)
    root = tmp_path / "rubric-generations" / "generation-0002"
    root.mkdir(parents=True)
    (root / "evolution.json").write_text(json.dumps({
        "task_required_enforcement": {
            "status": "valid_result",
            "response": {
                "decision": "correct", "requirement": "Report exactly 42 rows.",
                "corrective_action": "Add all 42 rows.",
            },
        }
    }))
    selection, skipped = select_enforcement(
        generation=generation, root=tmp_path, instruction="Report the requested rows.",
        numeric_literals=numeric_literals,
    )
    assert selection is None
    assert skipped[0]["reason"] == "numeric_literal_absent_from_public_task"


def test_requirement_only_delivery_drops_unsafe_action_numbers(tmp_path):
    generation = RubricGeneration(
        2, 0, _rubric(), (), 5, SOURCE_SCHEDULE, REQUIREMENT_ONLY_VERSION
    )
    root = tmp_path / "rubric-generations" / "generation-0002"
    root.mkdir(parents=True)
    (root / "evolution.json").write_text(json.dumps({
        "task_required_enforcement": {
            "status": "valid_result",
            "response": {
                "decision": "correct",
                "requirement": "Report the required interquartile ranges.",
                "corrective_action": "Compute the 25th and 75th percentiles.",
            },
        }
    }))
    selection, skipped = select_enforcement(
        generation=generation, root=tmp_path,
        instruction="Report medians and interquartile ranges.",
        numeric_literals=numeric_literals,
    )
    assert skipped == []
    assert selection["requirement"] == "Report the required interquartile ranges."
    assert "25" not in selection["requirement"] and "75" not in selection["requirement"]


def test_source_bound_version_remains_requirement_only(tmp_path):
    generation = RubricGeneration(
        2, 0, _rubric(), (), 5, SOURCE_SCHEDULE, SOURCE_BOUND_VERSION
    )
    root = tmp_path / "rubric-generations" / "generation-0002"
    root.mkdir(parents=True)
    (root / "evolution.json").write_text(json.dumps({
        "task_required_enforcement": {
            "status": "valid_result",
            "response": {
                "decision": "correct",
                "requirement": "Report the required interquartile ranges.",
                "corrective_action": "Compute the 25th and 75th percentiles.",
            },
        }
    }))
    selection, skipped = select_enforcement(
        generation=generation, root=tmp_path,
        instruction="Report medians and interquartile ranges.",
        numeric_literals=numeric_literals,
    )
    assert skipped == []
    assert selection["requirement"] == "Report the required interquartile ranges."


def test_witness_frozen_version_remains_requirement_only(tmp_path):
    generation = RubricGeneration(
        2, 0, _rubric(), (), 5, SOURCE_SCHEDULE, WITNESS_FROZEN_VERSION
    )
    root = tmp_path / "rubric-generations" / "generation-0002"
    root.mkdir(parents=True)
    (root / "evolution.json").write_text(json.dumps({
        "task_required_enforcement": {
            "status": "valid_result",
            "response": {
                "decision": "correct", "requirement": "Report the required ranges.",
                "corrective_action": "Compute the 25th and 75th percentiles.",
            },
        }
    }))
    selection, skipped = select_enforcement(
        generation=generation, root=tmp_path,
        instruction="Report the required ranges.", numeric_literals=numeric_literals,
    )
    assert skipped == [] and selection["requirement"] == "Report the required ranges."


def test_durable_delivery_version_preempts_with_requirement_only_enforcement(tmp_path):
    generation = RubricGeneration(
        2, 0, _rubric(), (), 5, SOURCE_SCHEDULE, DURABLE_DELIVERY_VERSION
    )
    root = tmp_path / "rubric-generations" / "generation-0002"
    root.mkdir(parents=True)
    (root / "evolution.json").write_text(json.dumps({
        "task_required_enforcement": {
            "status": "valid_result",
            "response": {
                "decision": "correct",
                "requirement": "Report the required ranges.",
                "corrective_action": "Compute the 25th and 75th percentiles.",
            },
        }
    }))
    selection, skipped = select_reminder(
        generation=generation,
        score_validation_path=tmp_path / "unused.json",
        root=tmp_path,
        submission_id="s000",
        instruction="Report the required ranges.",
    )
    assert skipped == []
    assert selection["category"] == 0
    assert selection["criterion_id"].startswith("required_")
    assert selection["requirement"] == "Report the required ranges."
    assert "25" not in selection["requirement"]


def test_durable_historical_version_does_not_change_delivery_dispatch(tmp_path):
    generation = RubricGeneration(
        2, 0, _rubric(), (), 5, SOURCE_SCHEDULE, DURABLE_VERSION
    )
    root = tmp_path / "rubric-generations" / "generation-0002"
    root.mkdir(parents=True)
    (root / "evolution.json").write_text(json.dumps({
        "task_required_enforcement": {
            "status": "valid_result",
            "response": {
                "decision": "correct",
                "requirement": "Report the required ranges.",
                "corrective_action": "Compute the ranges.",
            },
        }
    }))
    with pytest.raises(RuntimeError, match="score validation is not valid JSON"):
        select_reminder(
            generation=generation,
            score_validation_path=tmp_path / "unused.json",
            root=tmp_path,
            submission_id="s000",
            instruction="Report the required ranges.",
        )
