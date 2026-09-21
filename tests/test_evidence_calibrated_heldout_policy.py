from rubric_gen.submission_revision.evaluation.evidence_policy import (
    EVIDENCE_CALIBRATED_POLICY_ID,
    EVIDENCE_CALIBRATED_RUBRIC_SCORE_SYSTEM_PROMPT,
)


def test_evidence_calibrated_policy_is_condition_blind_and_evidence_specific():
    prompt = EVIDENCE_CALIBRATED_RUBRIC_SCORE_SYSTEM_PROMPT

    assert EVIDENCE_CALIBRATED_POLICY_ID == "evidence-calibrated-heldout-v1"
    assert "RTT" not in prompt
    assert "Static" not in prompt
    assert "da-" not in prompt
    assert "literal print/echo" in prompt
    assert "no completion credit" in prompt
    assert "must not erase credit" in prompt
    assert "does not substitute" in prompt
    assert "does not earn credit merely" in prompt
    assert "do not strengthen requirements" in prompt

