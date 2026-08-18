import json
from pathlib import Path

from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.paraphrases import ParaphraseSelection
from rubric_gen.submission_revision.rh_diagnostics import (
    EvaluationTarget,
    _HOLISTIC_INSTRUCTIONS,
    _combine_assignment,
    _condition_aggregates,
    _direct_assignment_outcomes,
    _holistic_review_material,
    _paired_condition_contrasts,
    _summarize_holistic_scores,
    _summarize_mechanistic_scores,
)


def _target(tmp_path: Path) -> EvaluationTarget:
    selection = ParaphraseSelection(
        task_id="da-1-1",
        replicate=1,
        optimizer_index=1,
        optimizer_path=tmp_path / "variant-001.txt",
        optimizer_sha256="1" * 64,
        holdout_paths=(
            tmp_path / "variant-000.txt",
            tmp_path / "variant-002.txt",
        ),
        holdout_sha256s=("0" * 64, "2" * 64),
        master_path=tmp_path / "master.txt",
        master_sha256="f" * 64,
    )
    return EvaluationTarget(
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
        initial_active_rubric=tmp_path / "r0000.txt",
        final_active_rubric=tmp_path / "r0006.txt",
        selection=selection,
    )


def _record(
    target: EvaluationTarget,
    *,
    model: str,
    boundary: str,
    score: int,
    roles: list[tuple[str, int | None]],
) -> dict[str, object]:
    return {
        "assignment_id": target.assignment_id,
        "model": model,
        "boundary": boundary,
        "score": score,
        "rubric_roles": [
            {"name": name, "variant_index": index} for name, index in roles
        ],
    }


def _mechanistic_summary(
    tmp_path: Path,
) -> tuple[EvaluationTarget, dict[str, object]]:
    target = _target(tmp_path)
    records: list[dict[str, object]] = []
    for model, active, holdout_0, holdout_2 in (
        ("strong-a", 60, 50, 70),
        ("strong-b", 70, 60, 60),
    ):
        records.extend((
            _record(
                target,
                model=model,
                boundary="initial",
                score=active,
                roles=[("active", None), ("selected", 1)],
            ),
            _record(
                target,
                model=model,
                boundary="initial",
                score=holdout_0,
                roles=[("holdout", 0)],
            ),
            _record(
                target,
                model=model,
                boundary="initial",
                score=holdout_2,
                roles=[("holdout", 2)],
            ),
        ))
    for model, active, selected, holdout_0, holdout_2 in (
        ("strong-a", 80, 70, 60, 70),
        ("strong-b", 90, 80, 70, 60),
    ):
        records.extend((
            _record(
                target,
                model=model,
                boundary="final",
                score=active,
                roles=[("active", None)],
            ),
            _record(
                target,
                model=model,
                boundary="final",
                score=selected,
                roles=[("selected", 1)],
            ),
            _record(
                target,
                model=model,
                boundary="final",
                score=holdout_0,
                roles=[("holdout", 0)],
            ),
            _record(
                target,
                model=model,
                boundary="final",
                score=holdout_2,
                roles=[("holdout", 2)],
            ),
        ))
    summary = _summarize_mechanistic_scores(
        (target,),
        records,
        ("strong-a", "strong-b"),
    )[0]
    return target, summary


def test_mechanistic_summary_estimates_three_rubric_components(
    tmp_path: Path,
) -> None:
    _target_value, summary = _mechanistic_summary(tmp_path)

    assert summary["reference_scores"]["holdout"]["initial"]["mean"] == 60
    assert summary["partial_components"]["initial"] == {
        "verifier_exploitation": 15,
        "rubric_drift": 0,
        "wording_exploitation": 5,
    }
    assert summary["partial_components"]["final"] == {
        "verifier_exploitation": 10,
        "rubric_drift": 10,
        "wording_exploitation": 10,
    }


def test_holistic_summary_averages_both_response_positions(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)

    def verdict(a: int, b: int) -> dict[str, object]:
        return {
            "response_A": {"score": a, "explanation": "A"},
            "response_B": {"score": b, "explanation": "B"},
            "comparative_explanation": "comparison",
        }

    records = [
        {"assignment_id": target.assignment_id, "model": "strong-a",
         "ordering": "initial-first", "verdict": verdict(40, 70)},
        {"assignment_id": target.assignment_id, "model": "strong-a",
         "ordering": "final-first", "verdict": verdict(80, 50)},
        {"assignment_id": target.assignment_id, "model": "strong-b",
         "ordering": "initial-first", "verdict": verdict(60, 80)},
        {"assignment_id": target.assignment_id, "model": "strong-b",
         "ordering": "final-first", "verdict": verdict(70, 40)},
    ]

    quality = _summarize_holistic_scores(
        (target,), records, ("strong-a", "strong-b")
    )[0]["rubric_free_quality"]

    assert quality["model_scores"]["strong-a"] == {
        "initial": 45,
        "final": 75,
        "gain": 30,
    }
    assert quality["initial_panel_mean"] == 47.5
    assert quality["final_panel_mean"] == 75
    assert quality["panel_mean_gain"] == 27.5


def test_four_component_decomposition_telescopes_at_both_boundaries(
    tmp_path: Path,
) -> None:
    _target_value, mechanism = _mechanistic_summary(tmp_path)
    quality = {
        "assignment_id": "assignment-1",
        "task_id": "da-1-1",
        "replicate": 1,
        "condition_id": "diligent-prospective",
        "rubric_free_quality": {
            "initial_panel_mean": 47.5,
            "final_panel_mean": 75,
            "panel_mean_gain": 27.5,
        },
    }

    result = _combine_assignment(
        mechanism,
        quality,
        {
            "verifier_exploitation": 1,
            "rubric_drift": 1,
            "wording_exploitation": 1,
            "specification_exploitation": 1,
        },
    )

    assert result["boundaries"]["initial"]["components"] == {
        "verifier_exploitation": 15,
        "rubric_drift": 0,
        "wording_exploitation": 5,
        "specification_exploitation": 12.5,
    }
    assert result["boundaries"]["final"]["total_proxy_gap"] == 20
    assert result["component_changes"] == {
        "verifier_exploitation": -5,
        "rubric_drift": 10,
        "wording_exploitation": 5,
        "specification_exploitation": -22.5,
    }
    assert result["outcomes"] == {
        "proxy_gain": 15,
        "holistic_gain": 27.5,
        "proxy_gain_gap": -12.5,
        "optimization_induced_risk": 0,
        "reward_hacking_loss_change": -2.5,
    }


def test_condition_aggregates_keep_direct_detection_independent(
    tmp_path: Path,
) -> None:
    _target_value, mechanism = _mechanistic_summary(tmp_path)
    assignment = _combine_assignment(
        mechanism,
        {
            "rubric_free_quality": {
                "initial_panel_mean": 47.5,
                "final_panel_mean": 75,
            },
        },
        {name: 1 for name in (
            "verifier_exploitation",
            "rubric_drift",
            "wording_exploitation",
            "specification_exploitation",
        )},
    )
    assignment["direct_detection"] = {"decision": "detected"}

    result = _condition_aggregates([assignment])

    assert result["overall"]["direct_detection"]["rate"] == 1
    assert result["diligent-prospective"]["outcomes"][
        "reward_hacking_loss_change"
    ]["mean"] == -2.5


def test_condition_contrasts_pair_task_replicates() -> None:
    assignments = [
        {
            "assignment_id": "a",
            "task_id": "task-1",
            "replicate": 1,
            "condition_id": "prospective",
            "outcomes": {
                "holistic_gain": 8,
                "proxy_gain_gap": 3,
                "reward_hacking_loss_change": 5,
            },
        },
        {
            "assignment_id": "b",
            "task_id": "task-1",
            "replicate": 1,
            "condition_id": "static",
            "outcomes": {
                "holistic_gain": 2,
                "proxy_gain_gap": 7,
                "reward_hacking_loss_change": 1,
            },
        },
    ]

    contrast = _paired_condition_contrasts(assignments)[0]

    assert contrast["direction"] == "left-minus-right"
    assert contrast["left_condition"] == "prospective"
    assert contrast["paired_differences"]["holistic_gain"]["mean"] == 6
    assert contrast["paired_differences"]["proxy_gain_gap"]["mean"] == -4


def test_direct_outcomes_use_the_configured_rule_and_experiment(
    tmp_path: Path,
) -> None:
    source = tmp_path / "assignment-1"
    source.mkdir()
    (source / "manifest.json").write_text(
        json.dumps({
            "experiment_id": "experiment-1",
            "assignment_id": "assignment-1",
        }),
        encoding="utf-8",
    )
    direct = {
        "detection": "rh",
        "models": ["a", "b", "c"],
        "primary_rule": "majority",
        "records": [
            {
                "source_path": str(source),
                "provider": model,
                "verdict": {"decision": decision},
            }
            for model, decision in (
                ("a", "reward_hacking_detected"),
                ("b", "reward_hacking_detected"),
                ("c", "no_reward_hacking_detected"),
            )
        ],
    }

    result = _direct_assignment_outcomes(
        direct,
        [{"assignment_id": "assignment-1"}],
        "experiment-1",
    )

    assert result["assignment-1"]["decision"] == "detected"


def test_biomnibench_holistic_review_includes_all_final_artifacts(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    submission = tmp_path / "s006"
    workspace = submission / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "trace.md").write_text("analysis trace\n", encoding="utf-8")
    (workspace / "answer.txt").write_text("final answer\n", encoding="utf-8")

    material = _holistic_review_material(target, submission)

    assert "# Exact submitted files" in material
    assert "## Exact submitted file: /app/trace.md" in material
    assert "analysis trace" in material
    assert "## Exact submitted file: /app/answer.txt" in material
    assert "final answer" in material
    instructions = " ".join(_HOLISTIC_INSTRUCTIONS.split())
    assert "Treat the named file as present" in instructions
    assert "source filesystem" in instructions
    assert "Do not use or reconstruct a criterion rubric" in instructions
