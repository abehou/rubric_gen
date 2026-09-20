"""Provider-free final Results20 analysis for all four feedback policies."""
from __future__ import annotations

from collections import Counter
import csv
import importlib.util
import json
import os
from pathlib import Path
import statistics
import sys

from rubric_gen.submission_revision.experiment import load_experiment

from prepare import CONFIG, ROOT, RUN
from run import GEMINI, SOL_OPUS, scoped_experiment


REPORT = ROOT / "docs/reports/2026-09-20/trace-v21-execution-verified-provenance-result20-feedback"
RESULT40 = ROOT / "docs/reports/2026-09-18/trace-v21-execution-verified-provenance-result40"
WINDOWS = ("full_trajectory", "post_update", "final_artifact", "final_revision")
METRICS = ("W", "W_train", "S", "H", "A", "W_minus_S", "S_minus_H", "H_minus_A", "W_minus_A")
GAPS = ("W_minus_S", "S_minus_H", "H_minus_A", "W_minus_A")
CONDITIONS = {
    "semi-static-execution-provenance-high-proposer": "static_semi",
    "semi-red-team-trace-execution-provenance-high-proposer": "current_semi",
    "score-only-static-execution-provenance-high-proposer": "static_score_only",
    "score-only-red-team-trace-execution-provenance-high-proposer": "current_score_only",
}
COHORTS = (
    "static_full", "current_full", "static_user", "current_user",
    "static_semi", "current_semi", "static_score_only", "current_score_only",
)
PANELS = {
    "sol_opus": SOL_OPUS,
    "sol": ("gpt-5.6-sol",),
    "opus": ("claude-opus-5",),
    "gemini": GEMINI,
    "sol_opus_gemini": (*SOL_OPUS, *GEMINI),
}
POLICIES = {
    "full": ("static_full", "current_full"),
    "user": ("static_user", "current_user"),
    "semi": ("static_semi", "current_semi"),
    "score_only": ("static_score_only", "current_score_only"),
}


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    search = (str(path.parent), str(ROOT / "scripts/diagnostics"))
    for item in reversed(search):
        sys.path.insert(0, item)
    try:
        spec.loader.exec_module(module)
    finally:
        for item in search:
            sys.path.remove(item)
    return module


R40 = _module(
    "feedback_result40_analysis",
    ROOT / "experiments/trace-v21-execution-verified-provenance-result40/analyze.py",
)
RECONSTRUCT = R40.RECONSTRUCT


def write_json(name: str, value: object) -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / name).write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    )


def write_csv(name: str, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing to write empty {name}")
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (REPORT / name).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: json.dumps(value, ensure_ascii=False)
                if isinstance(value, (dict, list, tuple)) else value
                for key, value in row.items()
            })


def normalize(raw: dict[str, object]) -> dict[str, object]:
    values = raw["values"]
    condition = str(raw["condition_id"])
    if condition not in CONDITIONS:
        raise RuntimeError(f"unexpected feedback condition: {condition}")
    row: dict[str, object] = {
        "cohort": CONDITIONS[condition],
        "task_id": raw["task_id"],
        "replicate": int(raw["replicate"]),
        "model": raw["model"],
        "assignment_id": raw["assignment_id"],
        "artifact_id": f"{raw['task_id']}--rep-{int(raw['replicate']):03d}",
        "submission_id": raw["submission_id"],
        "submission_sha256": raw["submission_sha256"],
        "initial_submission_sha256": raw["initial_submission_sha256"],
        "selected_rubric_sha256": raw["selected_rubric_sha256"],
        "state_path": raw["state_path"],
        "retained_revisions": raw["retained_revisions"],
        "attempted_turns": raw["attempted_turns"],
        "stop_reason": raw["stop_reason"],
        "W": values["W"], "W_train": values["W_train"],
        "S": values["S"], "H": values["H"], "A": values["A"],
        "W_minus_S": values["WS"], "S_minus_H": values["SH"],
        "H_minus_A": values["HA"], "W_minus_A": values["WA"],
    }
    for window in WINDOWS:
        verdict = raw["direct"][window]
        row[f"RH_{window}_decision"] = verdict["decision"]
        row[f"RH_{window}_score"] = verdict["score"]
        row[f"RH_{window}_reason"] = verdict["reason"]
    return row


def existing_full_user_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    allowed = {"static_full", "current_full", "static_user", "current_user"}
    with (RESULT40 / "candidate-auditor-rows.csv").open(newline="") as handle:
        for raw in csv.DictReader(handle):
            if raw.get("block") != "old20" or raw.get("cohort") not in allowed:
                continue
            row: dict[str, object] = dict(raw)
            row["replicate"] = int(raw["replicate"])
            for metric in METRICS:
                row[metric] = float(raw[metric])
            for window in WINDOWS:
                value = raw[f"RH_{window}_score"]
                row[f"RH_{window}_score"] = None if value == "" else float(value)
            rows.append(row)
    counts = Counter((str(row["cohort"]), str(row["model"])) for row in rows)
    expected = {(cohort, model): 60 for cohort in allowed for model in PANELS["sol_opus_gemini"]}
    if counts != expected:
        raise RuntimeError(f"published Full/User Results20 coverage changed: {counts}")
    return rows


def feedback_rows() -> tuple[list[dict[str, object]], dict[str, object]]:
    experiment = load_experiment(CONFIG)
    study = Path(experiment.dag["revise"]["output_dir"])
    scopes = {
        "sol_opus": scoped_experiment(
            experiment, SOL_OPUS, Path(experiment.dag["detect"]["output_dir"])
        ),
        "gemini": scoped_experiment(
            experiment, GEMINI, RUN / "audit-gemini" / experiment.experiment_id
        ),
    }
    rows: list[dict[str, object]] = []
    coverage: dict[str, object] = {}
    for panel, scoped in scopes.items():
        audit = Path(scoped.dag["detect"]["output_dir"])
        panel_coverage, raw = RECONSTRUCT.reconstruct(
            study, audit, tuple(scoped.outcome_audit["models"]), expected_holdouts=3
        )
        expected = 240 * len(scoped.outcome_audit["models"])
        if len(raw) != expected:
            raise RuntimeError(f"{panel} expected {expected} auditor rows, found {len(raw)}")
        coverage[panel] = panel_coverage
        rows.extend(normalize(item) for item in raw)
    counts = Counter((str(row["cohort"]), str(row["model"])) for row in rows)
    expected_counts = {
        (cohort, model): 60
        for cohort in ("static_semi", "current_semi", "static_score_only", "current_score_only")
        for model in PANELS["sol_opus_gemini"]
    }
    if counts != expected_counts:
        raise RuntimeError(f"Semi/Score-only auditor coverage changed: {counts}")
    return rows, coverage


def table_markdown(analysis: dict[str, object]) -> str:
    labels = {
        "sol_opus": "GPT-5.6 Sol + Claude Opus 5",
        "sol": "GPT-5.6 Sol",
        "opus": "Claude Opus 5",
        "gemini": "Gemini 3.8 Flash",
        "sol_opus_gemini": "GPT-5.6 Sol + Claude Opus 5 + Gemini 3.8 Flash",
    }
    lines = [
        "# Results20 feedback-policy gap and RH tables",
        "",
        "Gap cells are score points. RH cells are confirmed-positive auditor-row percentages; abstentions remain in denominators. Delta is promoted RTT minus matched static.",
        "",
    ]
    for panel, label in labels.items():
        lines.extend([
            f"## {label}", "",
            "| Policy | Condition | W−S | S−H | H−A | W−A | RH full | RH post | RH artifact | RH revision |",
            "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
        ])
        summaries = analysis["cohorts"][panel]
        comparisons = analysis["paired_comparisons"][panel]
        for policy, (static, current) in POLICIES.items():
            for condition, cohort in (("Static", static), ("Promoted RTT", current)):
                summary = summaries[cohort]
                values = [summary["metrics"][metric]["mean"] for metric in GAPS]
                rhs = [summary["rh"][window]["confirmed_positive_percent"] for window in WINDOWS]
                lines.append(
                    f"| {policy.replace('_', '-').title()} | {condition} | "
                    + " | ".join(f"{value:.2f}" for value in (*values, *rhs)) + " |"
                )
            delta = comparisons[policy]
            values = [delta["metrics"][metric]["mean"] for metric in GAPS]
            rhs = [delta["rh"][window]["mean"] for window in WINDOWS]
            lines.append(
                f"| {policy.replace('_', '-').title()} | RTT − static | "
                + " | ".join(f"{value:.2f}" for value in (*values, *rhs)) + " |"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Results20 feedback analysis must run through Slurm")
    existing = existing_full_user_rows()
    feedback, coverage = feedback_rows()
    rows = existing + feedback
    summaries: dict[str, object] = {}
    comparisons: dict[str, object] = {}
    paired_rows: list[dict[str, object]] = []
    panels: list[dict[str, object]] = []
    task_means: list[dict[str, object]] = []
    rank_rows: list[dict[str, object]] = []
    rank_summaries: dict[str, object] = {}
    for panel_name, models in PANELS.items():
        summaries[panel_name] = {
            cohort: R40.summarize_panel(rows, cohort, models) for cohort in COHORTS
        }
        panel = R40.panel_artifacts(rows, models, panel_name)
        panels.extend(panel)
        task_means.extend(R40.BASE.task_means(panel))
        ranks, rank_summary = R40.BASE.ranking(panel)
        for row in ranks:
            row["panel"] = panel_name
        rank_rows.extend(ranks)
        rank_summaries[panel_name] = rank_summary
        comparisons[panel_name] = {}
        for policy, (static, current) in POLICIES.items():
            summary, deltas = R40.paired(
                [row for row in rows if row["cohort"] == current],
                [row for row in rows if row["cohort"] == static],
                f"current_{policy}_minus_static_{policy}",
                models,
                panel_name,
            )
            comparisons[panel_name][policy] = summary
            paired_rows.extend(deltas)
    analysis = {
        "complete": True,
        "experiment_id": load_experiment(CONFIG).experiment_id,
        "assignment_count": 240,
        "conditions": list(CONDITIONS),
        "coverage": coverage,
        "cohorts": summaries,
        "paired_comparisons": comparisons,
        "rank_analysis": rank_summaries,
        "definitions": {
            "full_user": "read-only original20 rows from the completed Results40 report",
            "semi_score_only": "new matched Results20 assignments audited by all three models",
            "panels": {name: list(models) for name, models in PANELS.items()},
        },
    }
    write_csv("candidate-auditor-rows.csv", rows)
    write_csv("artifact-values.csv", panels)
    write_csv("paired-deltas.csv", paired_rows)
    write_csv("task-means.csv", task_means)
    write_csv("artifact-gap-rh-ranking.csv", rank_rows)
    write_json("artifact-gap-rh-ranking-summary.json", rank_summaries)
    write_json("analysis.json", analysis)
    (REPORT / "comparison-tables.md").write_text(table_markdown(analysis) + "\n")
    print(json.dumps({"complete": True, "auditor_rows": len(rows)}))


if __name__ == "__main__":
    main()
