"""Regression coverage for predicate polarity and contradictory feedback summaries."""

import hashlib
import json

import pytest

from rubric_gen.benchmarks.answer_only.dataset import render_rubric
from rubric_gen.submission_revision.evaluation.rubric_judge import rubric_score_output_schema
from rubric_gen.submission_revision.feedback import _project_full_payload
from rubric_gen.submission_revision.judging.full_rubric_protocol import structured_output_schema
from rubric_gen.submission_revision.judging.scoring import parse_rubric_levels_strict
from rubric_gen.submission_revision.paraphrase_protocol import wording_template


@pytest.mark.parametrize("predicate", [
    "Fails to provide helpful advice.",
    "Recommends seeking documentation assistance from a specialist.",
    "Fracasa en dar recomendaciones generales para manejar los síntomas.",
])
def test_healthbench_preserves_predicate_and_explicit_penalty_direction(predicate):
    rubric = render_rubric({"rubrics": [
        {"criterion": "Provides a relevant answer.", "points": 5},
        {"criterion": predicate, "points": -7},
    ]}, "healthbench-hard")
    assert parse_rubric_levels_strict(rubric) == {
        "criterion_1": {"A": 5, "B": 0},
        "criterion_2": {"A": 0, "B": -7},
    }
    wording_template(rubric)  # The same representation must reach heldout paraphrases.
    penalty = rubric.split("Criterion 2:")[1]
    quoted = json.dumps(predicate, ensure_ascii=False)
    assert f"[A]: Penalty avoided (zero deduction): this statement is FALSE of the answer: {quoted}" in penalty
    assert f"[B]: Penalty incurred: this statement is TRUE of the answer: {quoted}" in penalty
    assert "criterion is not met" not in rubric


@pytest.mark.parametrize("penalty_level,penalty_points", [("A", 0), ("B", -7)])
def test_feedback_overview_comes_from_scores_not_contradictory_model_summary(
    tmp_path, penalty_level, penalty_points,
):
    rubric = render_rubric({"rubrics": [
        {"criterion": "Provides a relevant answer.", "points": 5},
        {"criterion": "Recommends seeking documentation assistance from a specialist.", "points": -7},
    ]}, "healthbench-hard")
    evaluation = tmp_path / "evaluation.json"
    evaluation.write_text(json.dumps({
        "criteria": {
            "criterion_1": {"reason": "The answer is relevant."},
            "criterion_2": {"reason": "Concrete item-level evidence."},
        },
        "reasoning": "The answer omits required documentation guidance. Add it.",
    }))
    original = evaluation.read_bytes()
    feedback = _project_full_payload(
        validation={"evaluation_sha256": hashlib.sha256(original).hexdigest()},
        evaluation_path=evaluation, rubric_text=rubric, score=100 + 20 * penalty_points,
        criterion_levels={"criterion_1": "A", "criterion_2": penalty_level},
        criterion_scores={"criterion_1": 5, "criterion_2": penalty_points},
        max_reason_chars=2000,
    )
    assert "omits required documentation guidance" not in json.dumps(feedback)
    assert feedback["criteria"]["criterion_2"]["points"] == penalty_points
    assert feedback["criteria"]["criterion_2"]["level"] == penalty_level
    assert "Concrete item-level evidence." in feedback["criteria"]["criterion_2"]["judge_reason"]
    if penalty_points == 0:
        assert "Penalty avoided; zero is full credit" in feedback["criteria"]["criterion_2"]["judge_reason"]
        assert "At maximum points: criterion_1, criterion_2." in feedback["overall_reasoning"]
        assert "Below maximum points: none." in feedback["overall_reasoning"]
    else:
        assert "Penalty incurred" in feedback["criteria"]["criterion_2"]["judge_reason"]
        assert "Below maximum points: criterion_2." in feedback["overall_reasoning"]
    assert evaluation.read_bytes() == original  # Preserve the raw evidence, including errors.


def test_both_structured_judges_request_evidence_before_level_selection():
    online = structured_output_schema({"criterion_1": {"A": 0, "B": -7}})
    independent = rubric_score_output_schema(1, 2)
    assert list(online["properties"]["criteria"]["properties"]["criterion_1"]["properties"]) == ["reason", "level"]
    assert list(independent["properties"]["criteria"]["items"]["properties"]) == ["reason", "level_index"]
