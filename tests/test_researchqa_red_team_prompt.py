from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.red_team import red_team_prompt


def test_researchqa_sidecar_targets_scholarly_answer_quality():
    prompt = red_team_prompt("Criterion 1: cite the relevant finding", benchmark=SubmissionBenchmarkId.RESEARCHQA)
    assert "scholarly-answer" in prompt
    assert "misattributed study" in prompt
    assert "answer.txt" in prompt
    assert "computation or results" not in prompt
    assert "trace.md" not in prompt
