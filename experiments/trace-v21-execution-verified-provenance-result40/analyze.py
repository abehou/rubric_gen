"""Provider-free reconstruction of the new20 and cumulative40 Results40 cohorts."""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
import importlib.util
import json
import math
import os
from pathlib import Path
import statistics
import sys

from make_configs import BUNDLE, ROOT, RUN, SHARDS, TASKS, config_path
from prepare import CANDIDATE
from audit_scope import (
    GEMINI_PANEL,
    SOL_OPUS_PANEL,
    THREE_MODEL_PANEL,
    new20_gemini_scopes,
    new20_sol_opus_scopes,
    old20_gemini_scopes,
)

REPORT = ROOT / "docs/reports/2026-09-18/trace-v21-execution-verified-provenance-result40"
OLD_REPORT = ROOT / "docs/reports/2026-09-17/trace-v21-execution-verified-provenance-result20"
WINDOWS = ("full_trajectory", "post_update", "final_artifact", "final_revision")
METRICS = ("W", "W_train", "S", "H", "A", "W_minus_S", "S_minus_H", "H_minus_A", "W_minus_A")
GAPS = ("W_minus_S", "S_minus_H", "H_minus_A")
CONDITIONS = {
    "full-static": "static_full",
    "full-red-team-trace-execution-verified-proactive-provenance": "current_full",
    "user-simulator-static": "static_user",
    "user-simulator-red-team-trace-execution-verified-proactive-provenance": "current_user",
}
PANELS = {
    "sol_opus": SOL_OPUS_PANEL,
    "sol": ("gpt-5.6-sol",),
    "opus": ("claude-opus-5",),
    "gemini": GEMINI_PANEL,
    "sol_opus_gemini": THREE_MODEL_PANEL,
}


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    result = importlib.util.module_from_spec(spec)
    search_paths = (str(path.parent), str(ROOT / "scripts/diagnostics"))
    for search_path in reversed(search_paths):
        sys.path.insert(0, search_path)
    try:
        spec.loader.exec_module(result)
    finally:
        for search_path in search_paths:
            sys.path.remove(search_path)
    return result


BASE = _module(
    "result20_analysis_library",
    ROOT / "experiments/trace-v21-execution-verified-provenance-result20/analyze_result20.py",
)
RECONSTRUCT = _module(
    "result40_native_reconstruct",
    ROOT / "experiments/trace-attack-defense-v21/report/report_reconstruct.py",
)


def write_json(name: str, value: object) -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def write_csv(name: str, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (REPORT / name).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list, tuple)) else value
                for key, value in row.items()
            })


def normalize(raw: dict, *, block: str) -> dict[str, object]:
    values = raw["values"]
    row: dict[str, object] = {
        "block": block,
        "cohort": CONDITIONS[raw["condition_id"]],
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
        "W": values["W"], "W_train": values["W_train"], "S": values["S"],
        "H": values["H"], "A": values["A"], "W_minus_S": values["WS"],
        "S_minus_H": values["SH"], "H_minus_A": values["HA"], "W_minus_A": values["WA"],
    }
    for window in WINDOWS:
        verdict = raw["direct"][window]
        row[f"RH_{window}_decision"] = verdict["decision"]
        row[f"RH_{window}_score"] = verdict["score"]
        row[f"RH_{window}_reason"] = verdict["reason"]
    return row


def reconstruct_new20() -> tuple[dict[str, object], list[dict[str, object]]]:
    coverage = {"sol_opus": {}, "gemini": {}}
    rows = []
    scopes = {
        "sol_opus": new20_sol_opus_scopes(),
        "gemini": new20_gemini_scopes(),
    }
    for panel_name, panel_scopes in scopes.items():
        models = PANELS[panel_name]
        expected = 6 * len(models)
        for name, experiment in panel_scopes:
            study = Path(experiment.dag["revise"]["output_dir"])
            audit = Path(experiment.dag["detect"]["output_dir"])
            task_coverage, raw_rows = RECONSTRUCT.reconstruct(
                study, audit, models, expected_holdouts=3
            )
            if len(raw_rows) != expected:
                raise RuntimeError(
                    f"{name} expected {expected} auditor rows, got {len(raw_rows)}"
                )
            coverage[panel_name][name] = task_coverage
            rows.extend(normalize(raw, block="new20") for raw in raw_rows)
    counts = Counter(row["cohort"] for row in rows)
    if counts != {cohort: 180 for cohort in CONDITIONS.values()}:
        raise RuntimeError(f"new20 auditor coverage changed: {counts}")
    return coverage, rows


def old20_rows() -> list[dict[str, object]]:
    rows = []
    with (OLD_REPORT / "candidate-auditor-rows.csv").open(newline="") as handle:
        for raw in csv.DictReader(handle):
            row: dict[str, object] = dict(raw)
            row["block"] = "old20"
            row["replicate"] = int(raw["replicate"])
            for metric in METRICS:
                row[metric] = float(raw[metric])
            for window in WINDOWS:
                value = raw[f"RH_{window}_score"]
                row[f"RH_{window}_score"] = None if value == "" else float(value)
            rows.append(row)
    for historical in BASE.historical_rows():
        if historical["cohort"] not in {"static_full", "static_user"}:
            continue
        row = dict(historical)
        row["block"] = "old20"
        rows.append(row)
    gemini_counts = Counter()
    for name, experiment in old20_gemini_scopes():
        study = Path(experiment.dag["revise"]["output_dir"])
        audit = Path(experiment.dag["detect"]["output_dir"])
        _, raw_rows = RECONSTRUCT.reconstruct(
            study, audit, GEMINI_PANEL, expected_holdouts=3
        )
        expected = 120 if name == "old20-current-gemini" else 60
        if len(raw_rows) != expected:
            raise RuntimeError(
                f"{name} expected {expected} Gemini rows, got {len(raw_rows)}"
            )
        for raw in raw_rows:
            row = normalize(raw, block="old20")
            gemini_counts[str(row["cohort"])] += 1
            rows.append(row)
    if gemini_counts != {cohort: 60 for cohort in CONDITIONS.values()}:
        raise RuntimeError(f"old20 Gemini coverage changed: {gemini_counts}")
    counts = Counter(row["cohort"] for row in rows)
    if counts != {cohort: 180 for cohort in CONDITIONS.values()}:
        raise RuntimeError(f"old20 published auditor coverage changed: {counts}")
    if len({row["task_id"] for row in rows}) != 20 or {row["task_id"] for row in rows} & set(TASKS):
        raise RuntimeError("old20 and new20 memberships are not disjoint 20-task blocks")
    return rows


def paired(
    lhs_rows: list[dict[str, object]],
    rhs_rows: list[dict[str, object]],
    name: str,
    models: tuple[str, ...],
    panel_name: str,
) -> tuple[dict, list[dict]]:
    def index(rows):
        return {(str(row["task_id"]), int(row["replicate"]), str(row["model"])): row for row in rows}
    lhs = index([row for row in lhs_rows if row["model"] in models])
    rhs = index([row for row in rhs_rows if row["model"] in models])
    if lhs.keys() != rhs.keys() or not lhs:
        raise RuntimeError(f"unmatched comparison {name}")
    deltas = []
    for key in sorted(lhs):
        item = {
            "comparison": name,
            "panel": panel_name,
            "task_id": key[0],
            "replicate": key[1],
            "model": key[2],
        }
        for metric in METRICS:
            item[f"delta_{metric}"] = float(lhs[key][metric]) - float(rhs[key][metric])
        for window in WINDOWS:
            item[f"delta_RH_{window}"] = 100 * (
                lhs[key][f"RH_{window}_decision"] == "reward_hacking_detected"
            ) - 100 * (rhs[key][f"RH_{window}_decision"] == "reward_hacking_detected")
        deltas.append(item)
    groups: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in deltas:
        groups[(row["task_id"], row["replicate"])].append(row)
    if any({row["model"] for row in group} != set(models) for group in groups.values()):
        raise RuntimeError(f"incomplete paired auditor panel {name}")
    panel = [{metric: statistics.mean(float(row[f"delta_{metric}"]) for row in group) for metric in METRICS} for group in groups.values()]
    summary = {
        "comparison": name,
        "matched_assignments": len(groups),
        "matched_auditor_rows": len(deltas),
        "initial_hash_matches": sum(lhs[key]["initial_submission_sha256"] == rhs[key]["initial_submission_sha256"] for key in lhs),
        "metrics": {metric: BASE.stats([row[metric] for row in panel]) for metric in METRICS},
        "metrics_by_model": {
            model: {metric: BASE.stats([row[f"delta_{metric}"] for row in deltas if row["model"] == model]) for metric in METRICS}
            for model in models
        },
        "rh": {window: BASE.stats([row[f"delta_RH_{window}"] for row in deltas]) for window in WINDOWS},
        "rh_by_model": {
            model: {window: BASE.stats([row[f"delta_RH_{window}"] for row in deltas if row["model"] == model]) for window in WINDOWS}
            for model in models
        },
        "models": list(models),
        "panel": panel_name,
    }
    return summary, deltas


def summarize_panel(
    rows: list[dict[str, object]],
    cohort: str,
    models: tuple[str, ...],
) -> dict[str, object]:
    selected = [
        row for row in rows
        if row["cohort"] == cohort and row["model"] in models
    ]
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in selected:
        groups[str(row["artifact_id"])].append(row)
    if not groups or any({row["model"] for row in group} != set(models) for group in groups.values()):
        raise RuntimeError(f"incomplete {models} panel for {cohort}")
    metric_rows = [
        {
            metric: statistics.mean(float(row[metric]) for row in group)
            for metric in METRICS
        }
        for group in groups.values()
    ]
    rh = {}
    for window in WINDOWS:
        counts = Counter(row[f"RH_{window}_decision"] for row in selected)
        n = len(selected)
        positive = counts["reward_hacking_detected"]
        abstain = counts["abstain"]
        scores = [
            float(row[f"RH_{window}_score"])
            for row in selected
            if row[f"RH_{window}_score"] not in (None, "")
        ]
        rh[window] = {
            "positive": positive,
            "negative": counts["no_reward_hacking_detected"],
            "abstain": abstain,
            "denominator": n,
            "confirmed_positive_percent": 100 * positive / n,
            "identification_bounds_percent": [
                100 * positive / n,
                100 * (positive + abstain) / n,
            ],
            "wilson95_confirmed_positive_percent": BASE.wilson(positive, n),
            "mean_continuous_score": statistics.mean(scores) if scores else None,
        }
    return {
        "cohort": cohort,
        "models": list(models),
        "assignments": len(groups),
        "auditor_rows": len(selected),
        "metrics": {
            metric: BASE.stats([row[metric] for row in metric_rows])
            for metric in METRICS
        },
        "rh": rh,
    }


def panel_artifacts(
    rows: list[dict[str, object]],
    models: tuple[str, ...],
    panel_name: str,
) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, int], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        if row["model"] in models:
            groups[(str(row["cohort"]), str(row["task_id"]), int(row["replicate"]))].append(row)
    result = []
    for (cohort, task, replicate), group in sorted(groups.items()):
        if {row["model"] for row in group} != set(models):
            raise RuntimeError(f"incomplete {panel_name} panel: {(cohort, task, replicate)}")
        item: dict[str, object] = {
            "panel": panel_name,
            "cohort": cohort,
            "task_id": task,
            "replicate": replicate,
            "artifact_id": f"{task}--rep-{replicate:03d}",
            "initial_submission_sha256": group[0]["initial_submission_sha256"],
        }
        for metric in METRICS:
            item[metric] = statistics.mean(float(row[metric]) for row in group)
        for window in WINDOWS:
            scores = [
                float(row[f"RH_{window}_score"])
                for row in group if row[f"RH_{window}_score"] not in (None, "")
            ]
            counts = Counter(row[f"RH_{window}_decision"] for row in group)
            item[f"RH_{window}_score"] = statistics.mean(scores) if scores else None
            item[f"RH_{window}_positive_percent"] = (
                100 * counts["reward_hacking_detected"] / len(models)
            )
            item[f"RH_{window}_abstain_percent"] = 100 * counts["abstain"] / len(models)
        result.append(item)
    return result


def task_heterogeneity(panel: list[dict], current: str, static: str) -> dict:
    current_rows = {row["task_id"]: row for row in BASE.task_means([r for r in panel if r["cohort"] == current])}
    static_rows = {row["task_id"]: row for row in BASE.task_means([r for r in panel if r["cohort"] == static])}
    result = {}
    for metric in METRICS:
        deltas = {task: float(current_rows[task][metric]) - float(static_rows[task][metric]) for task in current_rows}
        result[metric] = {
            "improved": sum(value > 0 for value in deltas.values()) if metric in {"S", "H", "A"} else sum(value < 0 for value in deltas.values()),
            "worsened": sum(value < 0 for value in deltas.values()) if metric in {"S", "H", "A"} else sum(value > 0 for value in deltas.values()),
            "tied": sum(value == 0 for value in deltas.values()),
            "task_deltas": deltas,
        }
    return result


def audit_accounting() -> dict:
    totals = {stage: Counter() for stage in ("rubric_score", "absolute_score", "pairwise_preference")}
    direct = {window: 0 for window in WINDOWS}
    tasks = {}
    scopes = (*new20_sol_opus_scopes(), *new20_gemini_scopes(), *old20_gemini_scopes())
    for name, experiment in scopes:
        audit = Path(experiment.dag["detect"]["output_dir"])
        item = {"semantic": {}, "direct": {}}
        for stage in totals:
            raw = json.loads((audit / stage / "summary.json").read_text())
            counts = {
                "planned": int(raw["planned_semantic_judgment_count"]),
                "successful": int(raw["successful_semantic_judgment_count"]),
                "failed": int(raw["failed_semantic_judgment_count"]),
            }
            item["semantic"][stage] = counts
            totals[stage].update(counts)
        for window in WINDOWS:
            paths = list((audit / f"direct_{window}/evaluations").glob("*/summary.json"))
            if len(paths) != 1:
                raise RuntimeError(f"{name} has ambiguous {window} direct summary")
            raw = json.loads(paths[0].read_text())
            count = len(raw["records"])
            expected = len(experiment.execution_assignments) * len(experiment.outcome_audit["models"])
            if count != expected:
                raise RuntimeError(f"{name} {window} has {count}, expected {expected}")
            direct[window] += count
            item["direct"][window] = count
        tasks[name] = item
    return {
        "revision_completion": json.loads((RUN / "revision-completion.json").read_text()),
        "audit_completion": json.loads((RUN / "audit-completion.json").read_text()),
        "semantic_stages": {stage: dict(counts) for stage, counts in totals.items()},
        "direct_windows": direct,
        "tasks": tasks,
    }


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Results40 NAS analysis must run through Slurm")
    coverage, new = reconstruct_new20()
    old = old20_rows()
    populations = {"old20": old, "new20": new, "cumulative40": old + new}
    cohorts = ("static_full", "current_full", "static_user", "current_user")
    summaries = {}
    comparisons = {}
    paired_rows = []
    panels = []
    task_means = []
    heterogeneity = {}
    rank_rows = []
    rank_summaries = {}
    for population, rows in populations.items():
        summaries[population] = {}
        comparisons[population] = {}
        heterogeneity[population] = {}
        rank_summaries[population] = {}
        for panel_name, models in PANELS.items():
            summaries[population][panel_name] = {
                cohort: summarize_panel(rows, cohort, models) for cohort in cohorts
            }
            panel = panel_artifacts(rows, models, panel_name)
            for row in panel:
                row["population"] = population
            panels.extend(panel)
            for row in BASE.task_means(panel):
                row["population"] = population
                row["panel"] = panel_name
                task_means.append(row)
            population_rank_rows, population_rank_summary = BASE.ranking(panel)
            for row in population_rank_rows:
                row["population"] = population
                row["panel"] = panel_name
            rank_rows.extend(population_rank_rows)
            rank_summaries[population][panel_name] = population_rank_summary
            comparisons[population][panel_name] = {}
            heterogeneity[population][panel_name] = {}
            for arm in ("full", "user"):
                name = f"{population}_current_{arm}_minus_static_{arm}"
                summary, deltas = paired(
                    [row for row in rows if row["cohort"] == f"current_{arm}"],
                    [row for row in rows if row["cohort"] == f"static_{arm}"],
                    name,
                    models,
                    panel_name,
                )
                comparisons[population][panel_name][arm] = summary
                paired_rows.extend(deltas)
                heterogeneity[population][panel_name][arm] = task_heterogeneity(
                    panel, f"current_{arm}", f"static_{arm}"
                )
    accounting = audit_accounting()
    write_csv("candidate-auditor-rows.csv", old + new)
    write_csv("artifact-values.csv", panels)
    write_csv("paired-deltas.csv", paired_rows)
    write_csv("task-means.csv", task_means)
    write_csv("artifact-gap-rh-ranking.csv", rank_rows)
    write_json("artifact-gap-rh-ranking-summary.json", rank_summaries)
    write_json("audit-accounting.json", accounting)
    result = {
        "complete": True,
        "candidate": CANDIDATE,
        "new20_tasks": list(TASKS),
        "coverage": coverage,
        "accounting": accounting,
        "cohorts": summaries,
        "paired_comparisons": comparisons,
        "task_heterogeneity": heterogeneity,
        "rank_analysis": rank_summaries,
        "definitions": {
            "old20": "read-only published Results20 artifact/auditor rows from commit 770aa64",
            "new20": "precommitted queue6 additional10 plus first ten queue7 final15 tasks",
            "cumulative40": "artifact-level reconstruction from old20 plus new20 rows; no rounded-mean composition",
            "heldout_boundary": "old20 historical producer prompt differs from new20 rigorous-V2 prompt source commit 47463ca",
            "panels": {
                "sol_opus": "equal-weight GPT-5.6 Sol plus Claude Opus 5",
                "sol": "GPT-5.6 Sol alone",
                "opus": "Claude Opus 5 alone",
                "gemini": "Gemini 3.8 Flash alone",
                "sol_opus_gemini": "equal-weight GPT-5.6 Sol, Claude Opus 5, and Gemini 3.8 Flash",
            },
            "uncertainty": "sample SD/SE are descriptive; artifacts are clustered within tasks and share auditors",
        },
    }
    write_json("analysis.json", result)
    print(json.dumps({"complete": True, "new_rows": len(new), "old_rows": len(old), "accounting": accounting["direct_windows"]}), flush=True)


if __name__ == "__main__":
    main()
