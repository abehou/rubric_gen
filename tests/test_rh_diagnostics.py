from pathlib import Path

from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.paraphrases import ParaphraseSelection
from rubric_gen.submission_revision.rh_diagnostics import (
    DiagnosticTarget,
    _gap_aggregates,
    _summarize_meta_scores,
    _summarize_rubric_scores,
)


def _target(tmp_path: Path) -> DiagnosticTarget:
    selection = ParaphraseSelection(
        task_id="da-1-1",
        replicate=1,
        optimizer_index=1,
        optimizer_path=tmp_path / "variant-001.txt",
        optimizer_sha256="1" * 64,
        holdout_paths=(tmp_path / "variant-000.txt", tmp_path / "variant-002.txt"),
        holdout_sha256s=("0" * 64, "2" * 64),
        master_path=tmp_path / "master.txt",
        master_sha256="f" * 64,
    )
    return DiagnosticTarget(
        assignment_id="assignment-1",
        task_id="da-1-1",
        replicate=1,
        condition_id="diligent-prospective",
        benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,
        experiment_dir=tmp_path,
        task_dir=tmp_path,
        review="trace",
        max_review_chars=None,
        weak_model="weak",
        weak_initial_score=80,
        weak_final_score=95,
        initial_submission=tmp_path / "s000",
        final_submission=tmp_path / "s006",
        final_rubric_path=tmp_path / "r0006.txt",
        selection=selection,
    )


def test_score_diagnostic_summaries_keep_distinct_gap_definitions(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    records = []
    for index, initial, final, role in (
        (0, 50, 70, "holdout-paraphrase"),
        (1, 50, 90, "optimizer-paraphrase"),
        (2, 60, 75, "holdout-paraphrase"),
    ):
        for boundary, score in (("initial", initial), ("final", final)):
            records.append({
                "assignment_id": target.assignment_id,
                "rubric_role": role,
                "rubric_index": index,
                "boundary": boundary,
                "score": score,
            })
    for score in (80, 84, 88):
        records.append({
            "assignment_id": target.assignment_id,
            "rubric_role": "final-optimizer-rubric",
            "rubric_index": None,
            "boundary": "final",
            "score": score,
        })

    summary = _summarize_rubric_scores((target,), records)[0]
    assert summary["paraphrase_contrast"]["final_gap"] == 17.5
    assert summary["paraphrase_contrast"]["gain_gap"] == 22.5
    assert summary["strong_judge_gap"]["strong_mean_final_score"] == 84
    assert summary["strong_judge_gap"]["final_gap"] == 11

    meta = _summarize_meta_scores((target,), [
        {"assignment_id": target.assignment_id, "boundary": "initial", "score": 60},
        {"assignment_id": target.assignment_id, "boundary": "final", "score": 75},
    ])[0]["rubric_free_gap"]
    assert meta["final_gap"] == 20
    assert meta["gain_gap"] == 0


def test_gap_aggregates_keep_signals_and_conditions_separate() -> None:
    assignments = [{
        "condition_id": "diligent-prospective",
        "paraphrase_contrast": {"final_gap": 10.0, "gain_gap": 4.0},
        "rubric_free_gap": {"final_gap": -2.0, "gain_gap": 3.0},
        "strong_judge_gap": {"final_gap": 6.0},
    }, {
        "condition_id": "diligent-static",
        "paraphrase_contrast": {"final_gap": -4.0, "gain_gap": 0.0},
        "rubric_free_gap": {"final_gap": 8.0, "gain_gap": -1.0},
        "strong_judge_gap": {"final_gap": 2.0},
    }]

    result = _gap_aggregates(assignments)

    assert result["overall"]["paraphrase_final_gap"]["mean"] == 3
    assert result["overall"]["paraphrase_final_gap"]["positive_fraction"] == 0.5
    assert result["diligent-prospective"]["strong_judge_final_gap"]["mean"] == 6
