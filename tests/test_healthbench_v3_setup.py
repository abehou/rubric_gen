"""Offline checks for the revised HealthBench allocation."""

import json
from pathlib import Path

import pytest

from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision import evolution
from rubric_gen.submission_revision.evaluation import rubric_judge
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.judging import full_rubric_judge, full_rubric_protocol


RUBRIC = """Score normalization maximum: 1

Criterion 1: Give an answer.
Levels: A=1 B=0
[A]: Met.
[B]: Not met.
"""


@pytest.mark.parametrize("version", ["v3", "v4", "v5"])
def test_healthbench_v3_stage_allocation(monkeypatch, version) -> None:
    config = Path(__file__).resolve().parents[1] / f"experiments/healthbench-hard-local-mac/dev3-{version}.yaml"
    experiment = load_experiment(config)
    assert len(experiment.assignments) == 36
    assert experiment.payload["rubric_paraphrases"]["count"] == 5
    assert experiment.payload["outcome_audit"]["models"] == ["gpt-6-luna"]
    manifest = json.loads((Path(experiment.payload["tasks_dir"]) / "manifest.json").read_text())
    result20 = json.loads((config.parents[2] / "data/healthbench-hard/result20/manifest.json").read_text())
    source_ids = [task["source_id"] for task in manifest["tasks"]]
    assert source_ids == [
        "b947fc6f-1d50-4e3f-b679-8484529b787b",
        "1ca222ed-cc79-4e78-9ca3-3547e7b37e3a",
        "d546badf-e07b-44a1-bb32-373f263d7458",
    ]
    assert set(source_ids).isdisjoint(task["source_id"] for task in result20["tasks"])
    efforts = experiment.payload["protocol"]["rubric_proposer_reasoning_effort_by_stage"]
    proposer = evolution.RubricProposer(
        benchmark=SubmissionBenchmarkId.HEALTHBENCH_HARD,
        model="gpt-5.6-luna",
        reasoning_effort_by_stage=efforts,
    )
    for stage in (
        "assessment_rubric_free", "assessment_active_rubric",
        "assessment_development_rubric", "induction",
    ):
        assert proposer.contract_for_stage(stage).reasoning_effort == "high"
    assert proposer.contract_for_stage("validation").reasoning_effort == (
        "high" if version == "v5" else "low"
    )

    seen = {}

    def capture_stage(**kwargs):
        seen["contract"] = kwargs["contract"]
        return None

    monkeypatch.setattr(evolution, "run_stage", capture_stage)
    proposer._stage(stage="induction")
    assert seen["contract"].reasoning_effort == "high"
    proposer._stage(stage="validation")
    assert seen["contract"].reasoning_effort == ("high" if version == "v5" else "low")


@pytest.mark.parametrize("judge", [full_rubric_judge, rubric_judge])
def test_gpt6_high_judge_request_omits_temperature(monkeypatch, judge) -> None:
    assert full_rubric_protocol.provider_and_model("gpt-6-luna") == (
        "openai", "openai/responses/gpt-6-luna"
    )
    captured = {}

    def intercept(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("captured offline")

    monkeypatch.setenv("OPENAI_API_KEY", "unused-test-key")
    monkeypatch.setenv("RUBRIC_GEN_OPENAI_REASONING_EFFORT", "high")
    monkeypatch.setattr(judge.provider_streams, "openai_response", intercept)
    if judge is full_rubric_judge:
        spec = full_rubric_protocol.build_full_rubric_run_spec(
            rubric_text=RUBRIC, review_text="", answer_text="answer",
            requested_model="gpt-6-luna", seed=1,
        )
        payload = full_rubric_protocol.full_rubric_payload(RUBRIC, "", "answer")
        schema = full_rubric_protocol.structured_output_schema({"criterion_1": {"A": 1, "B": 0}})
    else:
        spec = rubric_judge.build_rubric_score_run_spec(
            rubric_text=RUBRIC, review_text="", answer_text="answer",
            requested_model="gpt-6-luna", seed=1,
        )
        payload = rubric_judge.rubric_score_payload(RUBRIC, "", "answer")
        schema = rubric_judge.rubric_score_output_schema(1, 2)
    with pytest.raises(RuntimeError, match="captured offline"):
        judge._generate_response(spec, payload=payload, schema=schema)
    assert captured["model"] == "gpt-6-luna"
    assert captured["reasoning"] == {"effort": "high"}
    assert "temperature" not in captured
