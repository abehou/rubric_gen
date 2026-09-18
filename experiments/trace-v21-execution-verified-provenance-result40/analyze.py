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
from prepare import CANDIDATE, PANEL

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


def _module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load {path}")
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
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
    coverage = {}
    rows = []
    for task, kind in SHARDS:
        from rubric_gen.submission_revision.experiment import load_experiment
        experiment = load_experiment(config_path(task, kind))
        study = Path(experiment.dag["revise"]["output_dir"])
        audit = Path(experiment.dag["detect"]["output_dir"])
        task_coverage, raw_rows = RECONSTRUCT.reconstruct(study, audit, PANEL, expected_holdouts=3)
        if len(raw_rows) != 12:
            raise RuntimeError(f"{task}/{kind} expected 12 auditor rows, got {len(raw_rows)}")
        coverage[f"{task}-{kind}"] = task_coverage
        rows.extend(normalize(raw, block="new20") for raw in raw_rows)
    counts = Counter(row["cohort"] for row in rows)
    if counts != {cohort: 120 for cohort in CONDITIONS.values()}:
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
    counts = Counter(row["cohort"] for row in rows)
    if counts != {cohort: 120 for cohort in CONDITIONS.values()}:
        raise RuntimeError(f"old20 published auditor coverage changed: {counts}")
    if len({row["task_id"] for row in rows}) != 20 or {row["task_id"] for row in rows} & set(TASKS):
        raise RuntimeError("old20 and new20 memberships are not disjoint 20-task blocks")
    return rows


def paired(lhs_rows: list[dict[str, object]], rhs_rows: list[dict[str, object]], name: str) -> tuple[dict, list[dict]]:
    def index(rows):
        return {(str(row["task_id"]), int(row["replicate"]), str(row["model"])): row for row in rows}
    lhs, rhs = index(lhs_rows), index(rhs_rows)
    if lhs.keys() != rhs.keys() or not lhs:
        raise RuntimeError(f"unmatched comparison {name}")
    deltas = []
    for key in sorted(lhs):
        item = {"comparison": name, "task_id": key[0], "replicate": key[1], "model": key[2]}
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
    if any({row["model"] for row in group} != set(PANEL) for group in groups.values()):
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
            for model in PANEL
        },
        "rh": {window: BASE.stats([row[f"delta_RH_{window}"] for row in deltas]) for window in WINDOWS},
        "rh_by_model": {
            model: {window: BASE.stats([row[f"delta_RH_{window}"] for row in deltas if row["model"] == model]) for window in WINDOWS}
            for model in PANEL
        },
    }
    return summary, deltas


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
    for task, kind in SHARDS:
        from rubric_gen.submission_revision.experiment import load_experiment
        experiment = load_experiment(config_path(task, kind))
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
                raise RuntimeError(f"{task}/{kind} has ambiguous {window} direct summary")
            raw = json.loads(paths[0].read_text())
            count = len(raw["records"])
            if count != 12:
                raise RuntimeError(f"{task}/{kind} {window} has {count}, expected 12")
            direct[window] += count
            item["direct"][window] = count
        tasks[f"{task}-{kind}"] = item
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
        summaries[population] = {cohort: BASE.summarize(rows, cohort) for cohort in cohorts}
        panel = BASE.panel_artifacts(rows)
        for row in panel:
            row["population"] = population
        panels.extend(panel)
        for row in BASE.task_means(panel):
            row["population"] = population
            task_means.append(row)
        population_rank_rows, population_rank_summary = BASE.ranking(panel)
        for row in population_rank_rows:
            row["population"] = population
        rank_rows.extend(population_rank_rows)
        rank_summaries[population] = population_rank_summary
        heterogeneity[population] = {}
        for arm in ("full", "user"):
            name = f"{population}_current_{arm}_minus_static_{arm}"
            summary, deltas = paired(
                [row for row in rows if row["cohort"] == f"current_{arm}"],
                [row for row in rows if row["cohort"] == f"static_{arm}"],
                name,
            )
            comparisons[name] = summary
            paired_rows.extend(deltas)
            heterogeneity[population][arm] = task_heterogeneity(panel, f"current_{arm}", f"static_{arm}")
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
            "combined": "equal-weight Sol plus Opus artifact panel",
            "uncertainty": "sample SD/SE are descriptive; artifacts are clustered within tasks and share auditors",
        },
    }
    write_json("analysis.json", result)
    print(json.dumps({"complete": True, "new_rows": len(new), "old_rows": len(old), "accounting": accounting["direct_windows"]}), flush=True)


if __name__ == "__main__":
    main()
