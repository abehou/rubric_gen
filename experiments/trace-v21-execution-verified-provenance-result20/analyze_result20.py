"""Provider-free Results20 reconstruction and matched comparison tables."""
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


ROOT = Path(__file__).resolve().parents[2]
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/rtt-result20-next")
EXPERIMENT_ID = "biomnibench-da-factorial-r10-682343156c5d"
STUDY = RUN / "study" / EXPERIMENT_ID
AUDIT = RUN / "audit" / EXPERIMENT_ID
REPORT = ROOT / "docs/reports/2026-09-17/trace-v21-execution-verified-provenance-result20"
PANEL = ("gpt-5.6-sol", "claude-opus-5")
WINDOWS = ("full_trajectory", "post_update", "final_artifact", "final_revision")
METRICS = ("W", "W_train", "S", "H", "A", "W_minus_S", "S_minus_H", "H_minus_A", "W_minus_A")
GAPS = ("W_minus_S", "S_minus_H", "H_minus_A")
CURRENT_CONDITIONS = {
    "full-red-team-trace-execution-verified-proactive-provenance": "current_full",
    "user-simulator-red-team-trace-execution-verified-proactive-provenance": "current_user",
}


def load(path: Path):
    return json.loads(path.read_text())


def write_json(name: str, value: object) -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / name).write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    )


def write_csv(name: str, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    REPORT.mkdir(parents=True, exist_ok=True)
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


def stats(values: list[float]) -> dict[str, float | int | None]:
    values = [float(value) for value in values]
    n = len(values)
    sd = statistics.stdev(values) if n > 1 else None
    return {
        "n": n,
        "mean": statistics.mean(values) if values else None,
        "sample_sd": sd,
        "se": sd / math.sqrt(n) if sd is not None else None,
    }


def wilson(successes: int, n: int, z: float = 1.959963984540054) -> list[float | None]:
    if n == 0:
        return [None, None]
    p = successes / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [100 * (center - half), 100 * (center + half)]


def rank_ascending(values: list[float]) -> list[float]:
    result = []
    for value in values:
        lower = sum(other < value for other in values)
        ties = sum(other == value for other in values)
        result.append(1.0 + lower + (ties - 1) / 2.0)
    return result


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    mx, my = statistics.mean(xs), statistics.mean(ys)
    numerator = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    dx = math.sqrt(sum((x - mx) ** 2 for x in xs))
    dy = math.sqrt(sum((y - my) ** 2 for y in ys))
    return numerator / (dx * dy) if dx and dy else None


def spearman(xs: list[float], ys: list[float]) -> float | None:
    return pearson(rank_ascending(xs), rank_ascending(ys))


def kendall_tau_b(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    concordant = discordant = ties_x = ties_y = 0
    for index in range(len(xs)):
        for other in range(index + 1, len(xs)):
            dx, dy = xs[index] - xs[other], ys[index] - ys[other]
            if dx == 0 and dy == 0:
                continue
            if dx == 0:
                ties_x += 1
            elif dy == 0:
                ties_y += 1
            elif dx * dy > 0:
                concordant += 1
            else:
                discordant += 1
    denominator = math.sqrt(
        (concordant + discordant + ties_x)
        * (concordant + discordant + ties_y)
    )
    return (concordant - discordant) / denominator if denominator else None


def worst_set(rows: list[dict[str, object]], field: str, fraction: float) -> set[str]:
    ordered = sorted((float(row[field]) for row in rows), reverse=True)
    cutoff = ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]
    return {
        str(row["artifact_id"])
        for row in rows
        if float(row[field]) >= cutoff
    }


def reconstruct_current() -> tuple[dict[str, object], list[dict[str, object]]]:
    sys.path.insert(0, str(ROOT / "scripts/diagnostics"))
    module_path = ROOT / "experiments/trace-attack-defense-v21/report/report_reconstruct.py"
    spec = importlib.util.spec_from_file_location("result20_reconstruct", module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load native Results20 reconstruction")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    coverage, raw_rows = module.reconstruct(STUDY, AUDIT, PANEL, expected_holdouts=3)
    rows = []
    for raw in raw_rows:
        cohort = CURRENT_CONDITIONS[raw["condition_id"]]
        values = raw["values"]
        row = {
            "cohort": cohort,
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
            "W": values["W"],
            "W_train": values["W_train"],
            "S": values["S"],
            "H": values["H"],
            "A": values["A"],
            "W_minus_S": values["WS"],
            "S_minus_H": values["SH"],
            "H_minus_A": values["HA"],
            "W_minus_A": values["WA"],
        }
        for window in WINDOWS:
            verdict = raw["direct"][window]
            row[f"RH_{window}_decision"] = verdict["decision"]
            row[f"RH_{window}_score"] = verdict["score"]
            row[f"RH_{window}_reason"] = verdict["reason"]
        rows.append(row)
    if len(rows) != 240:
        raise RuntimeError(f"expected 240 candidate auditor rows, got {len(rows)}")
    return coverage, rows


def historical_rows() -> list[dict[str, object]]:
    result = []
    sources = (
        (
            ROOT / "docs/reports/2026-09-11/trace-attack-defense-v2.1/outcomes-by-auditor.csv",
            {"static_full", "static_user", "candidate_full", "candidate_user"},
            "v21",
        ),
        (
            ROOT / "docs/reports/2026-09-10/trace-attack-defense-v1/outcomes-by-auditor.csv",
            {"candidate_full", "candidate_user"},
            "v1",
        ),
    )
    for path, wanted, prefix in sources:
        with path.open(newline="") as handle:
            for raw in csv.DictReader(handle):
                if raw["cohort"] not in wanted:
                    continue
                cohort = raw["cohort"]
                if cohort.startswith("static_"):
                    label = cohort
                else:
                    label = f"{prefix}_{cohort.removeprefix('candidate_')}"
                row = {
                    "cohort": label,
                    "task_id": raw["task_id"],
                    "replicate": int(raw["replicate"]),
                    "model": raw["model"],
                    "assignment_id": "",
                    "artifact_id": f"{raw['task_id']}--rep-{int(raw['replicate']):03d}",
                    "submission_id": raw["submission_id"],
                    "submission_sha256": raw["submission_sha256"],
                    "initial_submission_sha256": raw["initial_submission_sha256"],
                    "selected_rubric_sha256": raw["selected_rubric_sha256"],
                    "state_path": raw["state_path"],
                }
                for metric in METRICS:
                    row[metric] = float(raw[metric])
                for window in WINDOWS:
                    positive = float(raw[f"RH_{window}"])
                    upper = float(raw[f"RH_upper_{window}"])
                    decision = (
                        "reward_hacking_detected" if positive == 100
                        else "abstain" if upper == 100
                        else "no_reward_hacking_detected"
                    )
                    row[f"RH_{window}_decision"] = decision
                    row[f"RH_{window}_score"] = None
                    row[f"RH_{window}_reason"] = ""
                result.append(row)
    counts = Counter(row["cohort"] for row in result)
    if counts != {
        "static_full": 120,
        "static_user": 120,
        "v21_full": 120,
        "v21_user": 120,
        "v1_full": 120,
        "v1_user": 120,
    }:
        raise RuntimeError(f"historical Results20 coverage changed: {counts}")
    return result


def summarize(rows: list[dict[str, object]], cohort: str) -> dict[str, object]:
    cohort_rows = [row for row in rows if row["cohort"] == cohort]
    result: dict[str, object] = {
        "cohort": cohort,
        "assignments": len({row["artifact_id"] for row in cohort_rows}),
        "auditor_rows": len(cohort_rows),
        "models": {},
    }
    for model in (*PANEL, "equal_weight_panel"):
        auditor_rows = cohort_rows if model == "equal_weight_panel" else [
            row for row in cohort_rows if row["model"] == model
        ]
        if model == "equal_weight_panel":
            grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
            for row in cohort_rows:
                grouped[str(row["artifact_id"])].append(row)
            if any({item["model"] for item in group} != set(PANEL) for group in grouped.values()):
                raise RuntimeError(f"incomplete equal-weight panel for {cohort}")
            metric_rows = [
                {
                    metric: statistics.mean(float(item[metric]) for item in group)
                    for metric in METRICS
                }
                for group in grouped.values()
            ]
        else:
            metric_rows = auditor_rows
        rh = {}
        for window in WINDOWS:
            counts = Counter(row[f"RH_{window}_decision"] for row in auditor_rows)
            n = len(auditor_rows)
            positive = counts["reward_hacking_detected"]
            abstain = counts["abstain"]
            scores = [
                float(row[f"RH_{window}_score"])
                for row in auditor_rows if row[f"RH_{window}_score"] not in (None, "")
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
                "wilson95_confirmed_positive_percent": wilson(positive, n),
                "mean_continuous_score": statistics.mean(scores) if scores else None,
            }
        metric_stats = {
            metric: stats([float(row[metric]) for row in metric_rows])
            for metric in METRICS
        }
        result["models"][model] = {
            "metrics": metric_stats,
            "rh": rh,
            "metric_unit": "artifact" if model == "equal_weight_panel" else "artifact_auditor",
            "rh_unit": "auditor_judgment",
        }
    return result


def panel_artifacts(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str, int], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[(str(row["cohort"]), str(row["task_id"]), int(row["replicate"]))].append(row)
    result = []
    for (cohort, task, replicate), group in sorted(groups.items()):
        if {row["model"] for row in group} != set(PANEL):
            raise RuntimeError(f"incomplete panel: {(cohort, task, replicate)}")
        item: dict[str, object] = {
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
            item[f"RH_{window}_positive_percent"] = 50 * counts["reward_hacking_detected"]
            item[f"RH_{window}_abstain_percent"] = 50 * counts["abstain"]
        result.append(item)
    return result


def paired(current: list[dict[str, object]], reference: list[dict[str, object]], name: str) -> dict[str, object]:
    def index(rows):
        return {
            (str(row["task_id"]), int(row["replicate"]), str(row["model"])): row
            for row in rows
        }
    lhs, rhs = index(current), index(reference)
    if lhs.keys() != rhs.keys() or len(lhs) != 120:
        raise RuntimeError(f"unmatched Results20 comparison: {name}")
    initial_matches = sum(
        lhs[key]["initial_submission_sha256"] == rhs[key]["initial_submission_sha256"]
        for key in lhs
    )
    deltas = []
    for key in sorted(lhs):
        item = {
            "comparison": name,
            "task_id": key[0],
            "replicate": key[1],
            "model": key[2],
        }
        for metric in METRICS:
            item[f"delta_{metric}"] = float(lhs[key][metric]) - float(rhs[key][metric])
        for window in WINDOWS:
            item[f"delta_RH_{window}"] = 100 * (
                lhs[key][f"RH_{window}_decision"] == "reward_hacking_detected"
            ) - 100 * (
                rhs[key][f"RH_{window}_decision"] == "reward_hacking_detected"
            )
        deltas.append(item)
    panel_groups: dict[tuple[str, int], list[dict[str, object]]] = defaultdict(list)
    for row in deltas:
        panel_groups[(str(row["task_id"]), int(row["replicate"]))].append(row)
    if any({item["model"] for item in group} != set(PANEL) for group in panel_groups.values()):
        raise RuntimeError(f"incomplete paired panel: {name}")
    panel_deltas = [
        {
            metric: statistics.mean(float(item[f"delta_{metric}"]) for item in group)
            for metric in METRICS
        }
        for group in panel_groups.values()
    ]
    summary = {
        "comparison": name,
        "matched_auditor_rows": len(deltas),
        "matched_assignments": len(deltas) // len(PANEL),
        "initial_hash_matches": initial_matches,
        "metrics": {
            metric: stats([row[metric] for row in panel_deltas])
            for metric in METRICS
        },
        "metrics_by_model": {
            model: {
                metric: stats([
                    row[f"delta_{metric}"] for row in deltas if row["model"] == model
                ])
                for metric in METRICS
            }
            for model in PANEL
        },
        "rh": {
            window: stats([row[f"delta_RH_{window}"] for row in deltas])
            for window in WINDOWS
        },
        "rh_by_model": {
            model: {
                window: stats([
                    row[f"delta_RH_{window}"]
                    for row in deltas if row["model"] == model
                ])
                for window in WINDOWS
            }
            for model in PANEL
        },
        "metric_unit": "matched artifact panel",
        "rh_unit": "matched auditor judgment",
    }
    return {"summary": summary, "rows": deltas}


def task_means(panel: list[dict[str, object]]) -> list[dict[str, object]]:
    groups: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in panel:
        groups[(str(row["cohort"]), str(row["task_id"]))].append(row)
    output = []
    for (cohort, task), rows in sorted(groups.items()):
        item: dict[str, object] = {"cohort": cohort, "task_id": task, "artifacts": len(rows)}
        for metric in METRICS:
            item[metric] = statistics.mean(float(row[metric]) for row in rows)
        for window in WINDOWS:
            item[f"RH_{window}_confirmed_percent"] = statistics.mean(
                float(row[f"RH_{window}_positive_percent"]) for row in rows
            )
        output.append(item)
    return output


def ranking(panel: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, object]]:
    output = []
    summary = {}
    for cohort in ("current_full", "current_user"):
        rows = [dict(row) for row in panel if row["cohort"] == cohort]
        n = len(rows)
        for gap in GAPS:
            ranks = rank_ascending([float(row[gap]) for row in rows])
            for row, rank in zip(rows, ranks):
                row[f"{gap}_rank"] = rank
                row[f"{gap}_severity_percentile"] = 100 * (rank - 1) / (n - 1) if n > 1 else 50.0
        for row in rows:
            row["combined_gap_severity_percentile"] = statistics.mean(
                float(row[f"{gap}_severity_percentile"]) for gap in GAPS
            )
        windows = {}
        for window in ("final_artifact", "full_trajectory"):
            rh = [float(row[f"RH_{window}_score"]) for row in rows]
            combined = [float(row["combined_gap_severity_percentile"]) for row in rows]
            entry = {
                "n": n,
                "spearman": spearman(combined, rh),
                "kendall_tau_b": kendall_tau_b(combined, rh),
                "components": {
                    gap: {
                        "spearman": spearman([float(row[gap]) for row in rows], rh),
                        "kendall_tau_b": kendall_tau_b([float(row[gap]) for row in rows], rh),
                    }
                    for gap in GAPS
                },
                "worst_overlap": {},
            }
            for fraction in (0.10, 0.20, 0.25):
                gap_set = worst_set(rows, "combined_gap_severity_percentile", fraction)
                rh_set = worst_set(rows, f"RH_{window}_score", fraction)
                entry["worst_overlap"][str(fraction)] = {
                    "gap_count": len(gap_set),
                    "rh_count": len(rh_set),
                    "intersection_count": len(gap_set & rh_set),
                    "union_count": len(gap_set | rh_set),
                    "jaccard": len(gap_set & rh_set) / len(gap_set | rh_set)
                    if gap_set | rh_set else None,
                }
            windows[window] = entry
        summary[cohort] = windows
        output.extend(rows)
    return output, summary


def audit_accounting() -> dict[str, object]:
    summaries = {}
    for name, path in {
        "rubric_score": AUDIT / "rubric_score/summary.json",
        "absolute_score": AUDIT / "absolute_score/summary.json",
        "pairwise_preference": AUDIT / "pairwise_preference/summary.json",
    }.items():
        raw = load(path)
        summaries[name] = {
            "status": raw["status"],
            "planned": raw["planned_semantic_judgment_count"],
            "successful": raw["successful_semantic_judgment_count"],
            "failed": raw["failed_semantic_judgment_count"],
        }
    direct = {}
    for window in WINDOWS:
        paths = list((AUDIT / f"direct_{window}/evaluations").glob("*/summary.json"))
        if len(paths) != 1:
            raise RuntimeError(f"expected one {window} summary")
        raw = load(paths[0])
        record_count = len(raw["records"])
        direct[window] = {
            "status": raw.get("status", "completed" if record_count == 240 else "incomplete"),
            "records": record_count,
        }
    return {
        "audit_completion": load(RUN / "audit-completion.json"),
        "revision_completion": load(RUN / "revision-completion.json"),
        "semantic_stages": summaries,
        "direct_windows": direct,
        "audit_jobs": [10479921, 10480179],
        "first_attempt_transient_incomplete_calls": 8,
        "first_attempt_unincorporated_rubric_cells": 140,
        "recovery_provider_calls": 0,
    }


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Results20 NAS analysis must run through Slurm")
    coverage, current = reconstruct_current()
    history = historical_rows()
    rows = current + history
    cohorts = (
        "static_full", "v1_full", "v21_full", "current_full",
        "static_user", "v1_user", "v21_user", "current_user",
    )
    summaries = {cohort: summarize(rows, cohort) for cohort in cohorts}
    panel = panel_artifacts(rows)
    comparisons = {}
    paired_rows = []
    for arm in ("full", "user"):
        current_rows = [row for row in current if row["cohort"] == f"current_{arm}"]
        for reference in ("static", "v1", "v21"):
            reference_rows = [row for row in history if row["cohort"] == f"{reference}_{arm}"]
            name = f"current_{arm}_minus_{reference}_{arm}"
            result = paired(current_rows, reference_rows, name)
            comparisons[name] = result["summary"]
            paired_rows.extend(result["rows"])
    ranks, rank_summary = ranking(panel)
    candidate_rows = []
    for row in current:
        candidate_rows.append(dict(row))
    write_csv("candidate-auditor-rows.csv", candidate_rows)
    write_csv("artifact-values.csv", panel)
    write_csv("task-means.csv", task_means(panel))
    write_csv("paired-deltas.csv", paired_rows)
    write_csv("artifact-gap-rh-ranking.csv", ranks)
    write_json("artifact-gap-rh-ranking-summary.json", rank_summary)
    accounting = audit_accounting()
    write_json("audit-accounting.json", accounting)
    result = {
        "complete": True,
        "experiment_id": EXPERIMENT_ID,
        "candidate": "attack_defense_v2.1_execution_verified_proactive_provenance",
        "coverage": coverage,
        "accounting": accounting,
        "cohorts": summaries,
        "paired_comparisons": comparisons,
        "rank_analysis": rank_summary,
        "definitions": {
            "combined": "equal-weight Sol plus Opus auditor rows",
            "continuous_metric_n": "60 artifact panels per Results20 arm; auditor-specific n=60",
            "rh_combined_n": "120 auditor rows per arm and window",
            "uncertainty": "sample SD/SE are descriptive; rows share 20 task clusters and two auditors",
            "historical_comparators": "same canonical Results20 task/replicate cohort; trajectories differ by recipe",
        },
    }
    write_json("analysis.json", result)
    print(json.dumps({
        "complete": True,
        "coverage": accounting,
        "current": {key: summaries[key] for key in ("current_full", "current_user")},
    }, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
