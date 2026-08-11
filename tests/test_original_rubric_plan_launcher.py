from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import threading

import pytest
import yaml

from rubric_gen.malt.model_judge import STRONG_JUDGE_MODELS
from scripts import run_original_rubric_ensemble_plan as launcher
from scripts.run_original_rubric_ensemble_plan import (
    JudgmentPlan,
    PlannedTarget,
    _assignment_summaries,
)


PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLAN_CASES = (
    (
        "luna-top30-semi-r10-original-rubric.yaml",
        "runs/biomnibench-studies/luna-top30-semi-r10",
    ),
    (
        "luna-top30-full-r10-original-rubric.yaml",
        "runs/biomnibench-studies/luna-top30-full-r10",
    ),
)


@pytest.mark.parametrize(("filename", "study_dir"), PLAN_CASES)
def test_checked_plan_has_exact_deduplicated_coverage(
    filename: str,
    study_dir: str,
) -> None:
    path = PROJECT_ROOT / "judgment_plans" / filename
    plan = yaml.safe_load(path.read_text(encoding="utf-8"))
    targets = plan["targets"]
    initial = [target for target in targets if target["boundary"] == "initial"]
    final = [target for target in targets if target["boundary"] == "final"]

    assert plan["models"] == list(STRONG_JUDGE_MODELS)
    assert plan["study_dir"] == study_dir
    assert plan["expected"] == {
        "assignments": 360,
        "initial_targets": 90,
        "final_targets": 360,
        "score_targets": 450,
        "hosted_calls": 1_350,
    }
    assert len(targets) == len({target["target_id"] for target in targets}) == 450
    assert Counter(len(target["assignment_ids"]) for target in initial) == {4: 90}
    assert all(target["submission_id"] == "s000" for target in initial)
    assert all(
        len(target["assignment_ids"]) == 1 and target["submission_id"] == "s010"
        for target in final
    )

    initial_assignments = [
        assignment_id
        for target in initial
        for assignment_id in target["assignment_ids"]
    ]
    final_assignments = [target["assignment_ids"][0] for target in final]
    assert len(initial_assignments) == len(set(initial_assignments)) == 360
    assert set(initial_assignments) == set(final_assignments)


def test_assignment_summary_reuses_one_shared_initial_score(tmp_path: Path) -> None:
    assignments = {
        "task--rep-001--base-static": {
            "task_id": "task",
            "replicate": 1,
            "condition_id": "base-static",
        },
        "task--rep-001--diligent-static": {
            "task_id": "task",
            "replicate": 1,
            "condition_id": "diligent-static",
        },
    }
    assignment_ids = tuple(assignments)
    initial = PlannedTarget(
        target_id="task--rep-001--initial",
        boundary="initial",
        task_id="task",
        replicate=1,
        source_assignment_id=assignment_ids[0],
        assignment_ids=assignment_ids,
        submission_id="s000",
        submission_dir=tmp_path / "s000",
        task_dir=tmp_path / "task",
        rubric_sha256="0" * 64,
    )
    finals = tuple(
        PlannedTarget(
            target_id=f"{assignment_id}--final",
            boundary="final",
            task_id="task",
            replicate=1,
            source_assignment_id=assignment_id,
            assignment_ids=(assignment_id,),
            submission_id="s010",
            submission_dir=tmp_path / assignment_id / "s010",
            task_dir=tmp_path / "task",
            rubric_sha256="0" * 64,
        )
        for assignment_id in assignment_ids
    )
    plan = JudgmentPlan(
        path=tmp_path / "plan.yaml",
        sha256="1" * 64,
        plan_id="test-plan",
        study_dir=tmp_path / "study",
        output_dir=tmp_path / "output",
        experiment_id="test-experiment",
        tasks_dir=tmp_path / "tasks",
        review="trace",
        rubric_name="rubric.txt",
        max_review_chars=None,
        models=tuple(STRONG_JUDGE_MODELS),
        max_retries=1,
        expected={
            "assignments": 2,
            "initial_targets": 1,
            "final_targets": 2,
            "score_targets": 3,
            "hosted_calls": 9,
        },
        targets=(initial, *finals),
        assignments=assignments,
    )
    records = []
    for model_index, model in enumerate(STRONG_JUDGE_MODELS):
        records.append({
            "target_id": initial.target_id,
            "model": model,
            "status": "completed",
            "score": 10 + model_index,
        })
        for final_index, target in enumerate(finals):
            records.append({
                "target_id": target.target_id,
                "model": model,
                "status": "completed",
                "score": 20 + final_index + model_index,
            })

    summaries = _assignment_summaries(plan, records)

    for model_index, model in enumerate(STRONG_JUDGE_MODELS):
        assert {
            summaries[assignment_id]["judges"][model]["initial_score"]
            for assignment_id in assignment_ids
        } == {10.0 + model_index}
    assert summaries[assignment_ids[0]]["ensemble"]["mean_delta"] == 10.0
    assert summaries[assignment_ids[1]]["ensemble"]["mean_delta"] == 11.0


def test_runner_executes_each_planned_target_model_pair(
    tmp_path: Path,
    monkeypatch,
) -> None:
    assignments = {
        "task--rep-001--base-static": {
            "task_id": "task",
            "replicate": 1,
            "condition_id": "base-static",
        }
    }
    assignment_id = next(iter(assignments))
    targets = tuple(
        PlannedTarget(
            target_id=f"target-{boundary}",
            boundary=boundary,
            task_id="task",
            replicate=1,
            source_assignment_id=assignment_id,
            assignment_ids=(assignment_id,),
            submission_id=submission_id,
            submission_dir=tmp_path / submission_id,
            task_dir=tmp_path / "task",
            rubric_sha256="0" * 64,
        )
        for boundary, submission_id in (("initial", "s000"), ("final", "s010"))
    )
    plan = JudgmentPlan(
        path=tmp_path / "plan.yaml",
        sha256="1" * 64,
        plan_id="test-plan",
        study_dir=tmp_path / "study",
        output_dir=tmp_path / "output",
        experiment_id="test-experiment",
        tasks_dir=tmp_path / "tasks",
        review="trace",
        rubric_name="rubric.txt",
        max_review_chars=None,
        models=tuple(STRONG_JUDGE_MODELS),
        max_retries=1,
        expected={
            "assignments": 1,
            "initial_targets": 1,
            "final_targets": 1,
            "score_targets": 2,
            "hosted_calls": 6,
        },
        targets=targets,
        assignments=assignments,
    )
    calls: list[tuple[str, str]] = []
    calls_lock = threading.Lock()

    def fake_evaluate(
        _plan: JudgmentPlan,
        target: PlannedTarget,
        model: str,
    ) -> dict[str, object]:
        with calls_lock:
            calls.append((target.target_id, model))
        return {
            "target_id": target.target_id,
            "model": model,
            "status": "completed",
            "score": 10 if target.boundary == "initial" else 20,
        }

    monkeypatch.setattr(launcher, "_evaluate", fake_evaluate)

    assert launcher.run_plan(plan, max_concurrency=2, resume=True) == 0
    assert set(calls) == {
        (target.target_id, model)
        for target in targets
        for model in STRONG_JUDGE_MODELS
    }
    summary = json.loads((plan.output_dir / "summary.json").read_text())
    assert summary["status"] == "completed"
    assert summary["totals"] == {
        "jobs": 6,
        "completed": 6,
        "failed": 0,
        "pending": 0,
    }
