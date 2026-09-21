import json

from rubric_gen.submission_revision.evaluation.evidence_policy import (
    EVIDENCE_CALIBRATED_POLICY_ID,
    EVIDENCE_CALIBRATED_POLICY_V2_ID,
    EVIDENCE_CALIBRATED_RUBRIC_SCORE_SYSTEM_PROMPT,
    EVIDENCE_CALIBRATED_RUBRIC_SCORE_SYSTEM_PROMPT_V2,
    render_sealed_public_evidence,
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


def test_v2_policy_is_obligation_neutral_and_distinguishes_false_completion():
    prompt = EVIDENCE_CALIBRATED_RUBRIC_SCORE_SYSTEM_PROMPT_V2
    normalized = " ".join(prompt.split())

    assert EVIDENCE_CALIBRATED_POLICY_V2_ID == "obligation-neutral-evidence-rigorous-v2"
    assert "RTT" not in prompt
    assert "Static" not in prompt
    assert "da-" not in prompt
    assert "does not mean demanding more work" in prompt
    assert "more serious failure than" in prompt
    assert "Both remain incomplete" in normalized
    assert "Do not invent a new penalty" in prompt
    assert "Do not demand replacement" in prompt


def test_sealed_public_evidence_includes_commands_outputs_and_inventory(tmp_path):
    submission = tmp_path / "submission"
    workspace = submission / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "answer.txt").write_text("final answer", encoding="utf-8")
    (workspace / "trace.md").write_text("trace", encoding="utf-8")
    (workspace / "analysis.py").write_text("print(3)", encoding="utf-8")
    (workspace / "run.log").write_text("computed value = 3", encoding="utf-8")
    (workspace / "results.csv").write_text("metric,value\nx,3\n", encoding="utf-8")
    event = {
        "response": {
            "items": [{
                "type": "command_execution",
                "status": "completed",
                "id": "cmd-1",
                "command": "python analysis.py",
                "exit_code": 0,
                "aggregated_output": "computed value = 3",
            }]
        }
    }
    (submission / "trajectory.stream.jsonl").write_text(
        json.dumps(event) + "\n", encoding="utf-8"
    )

    rendered = render_sealed_public_evidence(submission)

    assert '"path":"analysis.py"' in rendered
    assert '"path":"run.log"' in rendered
    assert "FILE results.csv" in rendered
    assert "$ python analysis.py" in rendered
    assert "computed value = 3" in rendered
    assert "FILE answer.txt" not in rendered
