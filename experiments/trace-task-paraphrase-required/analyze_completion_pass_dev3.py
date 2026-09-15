"""Provider-free analysis of the completion-pass RTT Dev3 candidate.

This intentionally emits candidate-only artifacts.  The final report joins them
to the already-published matched static and completion-parent rows explicitly;
it never presents those historical cells as newly executed controls.
"""
from __future__ import annotations

import json
import math
from pathlib import Path

import analyze_clean_dev3 as analysis


RUN = Path(__file__).resolve().parents[2]
ROOT = Path("/home/aydanh/runs/rtt-completion-pass-dev3-20260915")
EXPERIMENT = "biomnibench-da-factorial-r10-a55245afa8c8"
REPORT = RUN / "docs/reports/2026-09-15/rtt-task-required-pass-boundary"
CANDIDATE = "attack_defense_v2.1_task_paraphrase_required_completion_pass"


def main() -> None:
    analysis.CLEAN = ROOT
    analysis.EXPERIMENT = EXPERIMENT
    analysis.STUDY = ROOT / "study" / EXPERIMENT
    analysis.AUDIT = ROOT / "detect" / EXPERIMENT
    analysis.REPORT = REPORT
    analysis.EXPECTED_ASSIGNMENTS = 18

    REPORT.mkdir(parents=True, exist_ok=True)
    rows, accounting = analysis.extract_rows()
    panel = analysis.panel_rows(rows)
    summaries = {"all": analysis.summarize(rows, "all")}
    for condition in sorted({str(row["condition_id"]) for row in rows}):
        subset = [row for row in rows if row["condition_id"] == condition]
        summaries[condition] = analysis.summarize(subset, condition)
    ranking_rows, ranking_summary = analysis.gap_rank_analysis(panel)

    # The reused/cost constants in the historical clean analyzer describe the
    # 36-assignment parent run and must not be copied into this candidate.
    accounting.pop("reuse", None)
    accounting.pop("usage_estimates", None)
    accounting["provider_calls_from_analysis"] = 0
    accounting["cost_status"] = (
        "Stage/model usage and pricing are computed separately from the saved "
        "candidate responses; this coverage file does not infer account billing."
    )

    analysis.write_csv("completion-pass-dev3-auditor-rows.csv", rows)
    analysis.write_csv("completion-pass-dev3-assignment-panel.csv", panel)
    analysis.write_csv("completion-pass-artifact-gap-rh-ranking.csv", ranking_rows)
    analysis.write_json("completion-pass-artifact-gap-rh-ranking-summary.json", ranking_summary)
    analysis.write_json("completion-pass-audit-accounting.json", accounting)
    analysis.write_json(
        "completion-pass-dev3-summary.json",
        {
            "candidate": CANDIDATE,
            "experiment_id": EXPERIMENT,
            "tasks": list(analysis.TASKS),
            "replicates": 3,
            "assignments": 18,
            "auditor_rows": 36,
            "summaries": summaries,
            "gap_rh_ranking": ranking_summary,
        },
    )
    for condition, summary in summaries.items():
        if condition == "all":
            continue
        metrics = summary["models"]["equal_weight_panel"]["metrics"]
        assert math.isclose(metrics["W_minus_S"], metrics["W"] - metrics["S"], abs_tol=1e-9)
        assert math.isclose(metrics["S_minus_H"], metrics["S"] - metrics["H"], abs_tol=1e-9)
        assert math.isclose(metrics["H_minus_A"], metrics["H"] - metrics["A"], abs_tol=1e-9)
        assert math.isclose(metrics["W_minus_A"], metrics["W"] - metrics["A"], abs_tol=1e-9)
    print(
        json.dumps(
            {
                "assignments": 18,
                "auditor_rows": 36,
                "conditions": sorted(summaries),
                "report": str(REPORT),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
