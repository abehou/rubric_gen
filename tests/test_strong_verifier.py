from __future__ import annotations

import json

import pytest

from rubric_gen.biomnibench.judging.models import JudgeRunConfig
from rubric_gen.biomnibench.judging.ensemble import (
    STRONG_VERIFIER_MODELS,
    StrongVerifierRunner,
    calculate_exploitation,
)


def panel(**criteria: tuple[str, str, str]) -> dict[str, dict[str, str]]:
    return {
        model: {
            criterion: levels[index]
            for criterion, levels in criteria.items()
        }
        for index, model in enumerate(STRONG_VERIFIER_MODELS)
    }


def test_exploitation_reports_binary_and_ordinal_transitions() -> None:
    rubric = {
        "criterion_1": {"A": 20, "B": 10, "C": 0},
        "criterion_2": {"A": 0, "B": -5, "C": -10},
    }
    weak = [
        {"criterion_1": "C", "criterion_2": "C"},
        {"criterion_1": "B", "criterion_2": "A"},
        {"criterion_1": "A", "criterion_2": "A"},
    ]
    strong = [
        panel(criterion_1=("C", "C", "C"), criterion_2=("C", "C", "C")),
        panel(criterion_1=("C", "C", "C"), criterion_2=("B", "B", "B")),
        panel(criterion_1=("B", "B", "B"), criterion_2=("A", "A", "A")),
    ]

    result = calculate_exploitation(rubric, weak, strong)

    assert result["binary_newly_credited_weight"] == 30
    assert result["binary_exploited_weight"] == 30
    assert result["binary_exploitation_rate"] == 1.0
    assert result["ordinal_gained_points"] == 30
    assert result["ordinal_exploited_points"] == 30
    assert result["ordinal_exploitation_rate"] == 1.0
    assert result["transitions"][0]["binary_exploited_criteria"] == ["criterion_2"]
    assert result["transitions"][1]["binary_exploited_criteria"] == ["criterion_1"]


def test_exploitation_uses_null_when_there_are_no_new_credits() -> None:
    rubric = {"criterion_1": {"A": 10, "B": 0}}
    weak = [{"criterion_1": "A"}, {"criterion_1": "A"}]
    strong = [
        panel(criterion_1=("A", "A", "A")),
        panel(criterion_1=("A", "A", "A")),
    ]

    result = calculate_exploitation(rubric, weak, strong)

    assert result["binary_exploitation_rate"] is None
    assert result["ordinal_exploitation_rate"] is None


def test_exploitation_rejects_tied_best_levels() -> None:
    with pytest.raises(ValueError, match="one best"):
        calculate_exploitation(
            {"criterion_1": {"A": 10, "B": 10}},
            [{"criterion_1": "A"}],
            [panel(criterion_1=("A", "A", "A"))],
        )


def test_ensemble_rejects_dry_run(tmp_path) -> None:
    with pytest.raises(ValueError, match="does not support --dry-run"):
        JudgeRunConfig(
            run_dir=tmp_path,
            tasks_dir=tmp_path,
            ensemble=True,
            dry_run=True,
        )


def test_ensemble_expands_revision_batch_root(tmp_path, monkeypatch) -> None:
    batch = tmp_path / "batch"
    batch.mkdir()
    (batch / "batch.json").write_text(
        '{"kind":"rubric-gen-submission-revision-batch",'
        '"experiment_dirs":["da-1-1","da-1-2"]}'
    )
    observed = []
    runner = StrongVerifierRunner(
        JudgeRunConfig(run_dir=batch, tasks_dir=tmp_path, ensemble=True)
    )
    monkeypatch.setattr(
        runner,
        "_run_experiment",
        lambda path: observed.append(path) or 0,
    )

    assert runner.run() == 0
    assert observed == [batch / "da-1-1", batch / "da-1-2"]


def test_ensemble_skips_revision_without_weak_judgments(tmp_path, capsys) -> None:
    experiment = tmp_path / "da-1-1"
    experiment.mkdir()
    (experiment / "manifest.json").write_text(
        json.dumps(
            {
                "kind": "rubric-gen-submission-revision-experiment",
                "task_id": "da-1-1",
                "task_dir": str(tmp_path / "tasks" / "da-1-1"),
            }
        )
    )
    (experiment / "state.json").write_text(
        json.dumps(
            {
                "submission_ids": ["s000"],
                "scores": [],
                "judge_attempts": {},
            }
        )
    )
    runner = StrongVerifierRunner(
        JudgeRunConfig(run_dir=experiment, tasks_dir=tmp_path, ensemble=True)
    )

    assert runner.run() == 0
    output = capsys.readouterr().out
    assert "Skipping da-1-1: no weak-judged submissions" in output
    assert str(experiment) in output
