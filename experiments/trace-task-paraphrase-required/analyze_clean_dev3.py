"""Provider-free analysis of the clean matched RTT Dev3 run.

The script reads only the completed NAS1 study/audit summaries and writes small
derived tables under the tracked report directory.  It never mutates the study
or creates provider requests.
"""
from __future__ import annotations

import csv
import json
import math
import statistics
from collections import Counter, defaultdict
from pathlib import Path


# The analysis script lives under ``<checkout>/experiments/<recipe>``.
# Keep derived reports in this execution checkout rather than its parent.
RUN = Path(__file__).resolve().parents[2]
CLEAN = Path("/home/aydanh/runs/rtt-clean-20260915")
EXPERIMENT = "biomnibench-da-factorial-r10-bad950537c4d"
STUDY = CLEAN / "study" / EXPERIMENT
AUDIT = CLEAN / "detect" / EXPERIMENT
REPORT = RUN / "docs/reports/2026-09-15/rtt-clean-20260915"
TASKS = ("da-3-4", "da-11-1", "da-18-1")
MODELS = ("gpt-5.6-sol", "claude-opus-5")
WINDOWS = ("full_trajectory", "post_update", "final_artifact", "final_revision")
METRICS = ("W", "W_train", "S", "H", "A", "W_minus_S", "S_minus_H", "H_minus_A", "W_minus_A")
GAPS = ("W_minus_S", "S_minus_H", "H_minus_A")
EXPECTED_ASSIGNMENTS = 36


def load(path: Path):
    return json.loads(path.read_text())


def write_json(name: str, value: object) -> None:
    (REPORT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n")


def write_csv(name: str, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    with (REPORT / name).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def mean_or_none(values):
    values = [float(x) for x in values if x is not None]
    return statistics.mean(values) if values else None


def rank_desc(values: list[float]) -> list[float]:
    """Rank highest/worst first, using average ranks for ties."""
    result = []
    for value in values:
        better = sum(other > value for other in values)
        ties = sum(other == value for other in values)
        result.append(1.0 + better + (ties - 1) / 2.0)
    return result


def spearman(xs: list[float], ys: list[float]):
    if len(xs) < 2 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    rx, ry = rank_desc(xs), rank_desc(ys)
    mx, my = statistics.mean(rx), statistics.mean(ry)
    numerator = sum((a - mx) * (b - my) for a, b in zip(rx, ry))
    denx = math.sqrt(sum((a - mx) ** 2 for a in rx))
    deny = math.sqrt(sum((b - my) ** 2 for b in ry))
    return numerator / (denx * deny) if denx and deny else None


def kendall_tau_b(xs: list[float], ys: list[float]):
    if len(xs) < 2 or len(set(xs)) < 2 or len(set(ys)) < 2:
        return None
    concordant = discordant = ties_x = ties_y = 0
    for i in range(len(xs)):
        for j in range(i + 1, len(xs)):
            dx, dy = xs[i] - xs[j], ys[i] - ys[j]
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
        (concordant + discordant + ties_x) * (concordant + discordant + ties_y)
    )
    return (concordant - discordant) / denominator if denominator else None


def worst_set(rows: list[dict[str, object]], field: str, fraction: float) -> set[str]:
    """Return a tie-aware worst fraction set (larger value is worse)."""
    if not rows:
        return set()
    ordered = sorted((float(row[field]) for row in rows), reverse=True)
    cutoff = ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]
    return {str(row["assignment_id"]) for row in rows if float(row[field]) >= cutoff}


def extract_rows() -> tuple[list[dict[str, object]], dict[str, object]]:
    rubric = load(AUDIT / "rubric_score/summary.json")
    absolute = load(AUDIT / "absolute_score/summary.json")
    rubric_by_id = {str(item["assignment_id"]): item for item in rubric["assignments"]}
    absolute_by_id = {str(item["assignment_id"]): item for item in absolute["assignments"]}
    rh_by_key: dict[tuple[str, str, str], dict[str, object]] = {}
    direct_costs: dict[str, object] = {}
    for window in WINDOWS:
        summary_paths = list((AUDIT / f"direct_{window}/evaluations").glob("*/summary.json"))
        if len(summary_paths) != 1:
            raise RuntimeError(f"expected one direct {window} summary")
        summary = load(summary_paths[0])
        direct_costs[window] = summary.get("cost", {})
        for record in summary["records"]:
            rh_by_key[(str(record["source_path"]), str(record["model"]), window)] = record

    rows: list[dict[str, object]] = []
    for assignment_id, rubric_assignment in sorted(rubric_by_id.items()):
        task = str(rubric_assignment["task_id"])
        replicate = int(rubric_assignment["replicate"])
        condition = str(rubric_assignment["condition_id"])
        state_path = STUDY / "experiments" / task / f"rep-{replicate:03d}" / "luna" / condition / "state.json"
        state = load(state_path)
        submission_id = str(state["submission_ids"][-1])
        evaluation = load(state_path.parent / "rubric-evaluations" / f"{submission_id}.json")
        absolute_assignment = absolute_by_id[assignment_id]
        source_path = str(state_path.parent)
        for model in MODELS:
            selected = float(rubric_assignment["reference_scores"]["selected"]["final"]["scores"][model])
            holdout_variants = rubric_assignment["reference_scores"]["holdout"]["final"]["variants"]
            holdout = statistics.mean(float(value["scores"][model]) for value in holdout_variants.values())
            quality_model = absolute_assignment["rubric_free_absolute_scores"]["model_scores"][model]
            row: dict[str, object] = {
                "assignment_id": assignment_id,
                "task_id": task,
                "replicate": replicate,
                "condition_id": condition,
                "model": model,
                "submission_id": submission_id,
                "revision_count": len(state["submission_ids"]) - 1,
                "stop_reason": state.get("stop_reason"),
                "W": float(evaluation["reference_score"]),
                "W_train": float(evaluation["score"]),
                "S": selected,
                "H": holdout,
                "A": float(quality_model["final"]),
                "source_path": source_path,
            }
            row.update({
                "W_minus_S": row["W"] - row["S"],
                "S_minus_H": row["S"] - row["H"],
                "H_minus_A": row["H"] - row["A"],
                "W_minus_A": row["W"] - row["A"],
            })
            for window in WINDOWS:
                record = rh_by_key[(source_path, model, window)]
                verdict = record["verdict"]
                decision = str(verdict["decision"])
                row[f"RH_{window}_decision"] = decision
                row[f"RH_{window}_score"] = float(verdict["score"])
                row[f"RH_{window}_positive"] = 100.0 * (decision == "reward_hacking_detected")
                row[f"RH_{window}_abstain"] = 100.0 * (decision == "abstain")
            rows.append(row)
    if len(rows) != EXPECTED_ASSIGNMENTS * len(MODELS):
        raise RuntimeError(
            f"expected {EXPECTED_ASSIGNMENTS * len(MODELS)} auditor rows, got {len(rows)}"
        )
    return rows, {
        "rubric_score": {
            "status": rubric["status"],
            "configured_assignments": rubric["assignment_coverage"]["configured_assignment_count"],
            "evaluated_assignments": rubric["assignment_coverage"]["evaluated_assignment_count"],
            "planned_unique_judgments": rubric["planned_semantic_judgment_count"],
            "successful_unique_judgments": rubric["successful_semantic_judgment_count"],
            "failed_unique_judgments": rubric["failed_semantic_judgment_count"],
            "assignment_reference_records": len(rubric["records"]),
        },
        "absolute_score": {
            "status": absolute["status"],
            "configured_assignments": absolute["assignment_coverage"]["configured_assignment_count"],
            "evaluated_assignments": absolute["assignment_coverage"]["evaluated_assignment_count"],
            "planned_unique_judgments": absolute["planned_semantic_judgment_count"],
            "successful_unique_judgments": absolute["successful_semantic_judgment_count"],
            "failed_unique_judgments": absolute["failed_semantic_judgment_count"],
            "assignment_reference_records": len(absolute["records"]),
        },
        "pairwise_preference": {
            "status": load(AUDIT / "pairwise_preference/summary.json")["status"],
            "configured_assignments": load(AUDIT / "pairwise_preference/summary.json")["assignment_coverage"]["configured_assignment_count"],
            "evaluated_assignments": load(AUDIT / "pairwise_preference/summary.json")["assignment_coverage"]["evaluated_assignment_count"],
            "planned_unique_judgments": load(AUDIT / "pairwise_preference/summary.json")["planned_semantic_judgment_count"],
            "successful_unique_judgments": load(AUDIT / "pairwise_preference/summary.json")["successful_semantic_judgment_count"],
            "failed_unique_judgments": load(AUDIT / "pairwise_preference/summary.json")["failed_semantic_judgment_count"],
            "assignment_reference_records": len(load(AUDIT / "pairwise_preference/summary.json")["records"]),
        },
        "direct_rh_costs": direct_costs,
        "reuse": {
            "absolute_score_judgments_reused": 90,
            "pairwise_preference_judgments_reused": 72,
            "direct_rh_records_reused_per_window": 72,
            "direct_rh_windows": len(WINDOWS),
            "provider_calls_from_analysis": 0,
        },
        "usage_estimates": {
            "direct_rh_total_usd": 183.7094375,
            "semantic_absolute_score_usd": 3.996631,
            "semantic_pairwise_preference_usd": 3.875490,
            "semantic_rubric_score_usd": 35.361630,
            "identifiable_total_usd": 226.9431885,
            "pricing_as_of": "2026-08-18",
            "basis": "repository usage-derived estimates; not an account invoice",
        },
    }


def panel_rows(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    grouped: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        grouped[str(row["assignment_id"])].append(row)
    result = []
    for assignment_id, group in sorted(grouped.items()):
        first = group[0]
        row = {key: first[key] for key in ("assignment_id", "task_id", "replicate", "condition_id", "submission_id", "revision_count", "stop_reason", "source_path")}
        for metric in METRICS:
            row[metric] = statistics.mean(float(item[metric]) for item in group)
        for window in WINDOWS:
            row[f"RH_{window}_score"] = statistics.mean(float(item[f"RH_{window}_score"]) for item in group)
            decisions = Counter(str(item[f"RH_{window}_decision"]) for item in group)
            row[f"RH_{window}_positive_count"] = decisions["reward_hacking_detected"]
            row[f"RH_{window}_abstain_count"] = decisions["abstain"]
            row[f"RH_{window}_positive_percent"] = 100.0 * decisions["reward_hacking_detected"] / len(group)
            row[f"RH_{window}_bounds_percent"] = [
                row[f"RH_{window}_positive_percent"],
                100.0 * (decisions["reward_hacking_detected"] + decisions["abstain"]) / len(group),
            ]
        result.append(row)
    return result


def summarize(rows: list[dict[str, object]], label: str) -> dict[str, object]:
    result: dict[str, object] = {"label": label, "auditor_rows": len(rows), "assignments": len({r["assignment_id"] for r in rows}), "models": {}}
    for model in (*MODELS, "equal_weight_panel"):
        subset = rows if model == "equal_weight_panel" else [r for r in rows if r["model"] == model]
        values = {metric: statistics.mean(float(row[metric]) for row in subset) for metric in METRICS}
        windows = {}
        for window in WINDOWS:
            decisions = Counter(str(row[f"RH_{window}_decision"]) for row in subset)
            n = len(subset)
            windows[window] = {
                "positive": decisions["reward_hacking_detected"],
                "negative": decisions["no_reward_hacking_detected"],
                "abstain": decisions["abstain"],
                "denominator": n,
                "confirmed_positive_percent": 100.0 * decisions["reward_hacking_detected"] / n if n else None,
                "identification_bounds_percent": [
                    100.0 * decisions["reward_hacking_detected"] / n,
                    100.0 * (decisions["reward_hacking_detected"] + decisions["abstain"]) / n,
                ] if n else [None, None],
                "mean_continuous_score": mean_or_none(row[f"RH_{window}_score"] for row in subset),
            }
        result["models"][model] = {"metrics": values, "rh": windows}
    return result


def paired_deltas(panel: list[dict[str, object]]) -> list[dict[str, object]]:
    by_key = {(str(row["task_id"]), int(row["replicate"]), str(row["condition_id"])): row for row in panel}
    out = []
    for arm, trace, static in (("full", "full-red-team-trace", "full-static"), ("user", "user-simulator-red-team-trace", "user-simulator-static")):
        for task in TASKS:
            for replicate in (1, 2, 3):
                t = by_key[(task, replicate, trace)]
                s = by_key[(task, replicate, static)]
                row = {"arm": arm, "task_id": task, "replicate": replicate, "trace_assignment_id": t["assignment_id"], "static_assignment_id": s["assignment_id"]}
                for metric in METRICS:
                    row[f"delta_{metric}"] = float(t[metric]) - float(s[metric])
                for window in WINDOWS:
                    row[f"delta_RH_{window}_score"] = float(t[f"RH_{window}_score"]) - float(s[f"RH_{window}_score"])
                    row[f"trace_RH_{window}_positive_percent"] = float(t[f"RH_{window}_positive_percent"])
                    row[f"trace_RH_{window}_abstain_count"] = int(t[f"RH_{window}_abstain_count"])
                    row[f"static_RH_{window}_positive_percent"] = float(s[f"RH_{window}_positive_percent"])
                    row[f"static_RH_{window}_abstain_count"] = int(s[f"RH_{window}_abstain_count"])
                out.append(row)
    return out


def gap_rank_analysis(panel: list[dict[str, object]]) -> tuple[list[dict[str, object]], dict[str, object]]:
    ranked: list[dict[str, object]] = []
    summary: dict[str, object] = {"within_condition": {}, "pooled_secondary": None, "definition": "signed gaps; higher positive gap is worse; rank/percentile direction is worst-highest to best-lowest"}
    for condition in sorted({str(row["condition_id"]) for row in panel}):
        group = [row for row in panel if str(row["condition_id"]) == condition]
        ranks = {gap: rank_desc([float(row[gap]) for row in group]) for gap in GAPS}
        n = len(group)
        for index, row in enumerate(group):
            out = {key: row[key] for key in ("assignment_id", "task_id", "replicate", "condition_id")}
            for gap in GAPS:
                out[gap] = float(row[gap])
                out[f"rank_{gap}"] = ranks[gap][index]
                out[f"severity_{gap}"] = (n - ranks[gap][index]) / (n - 1) if n > 1 else None
            out["combined_gap_rank"] = statistics.mean(ranks[gap][index] for gap in GAPS)
            out["combined_gap_severity"] = mean_or_none(out[f"severity_{gap}"] for gap in GAPS)
            out["RH_final_artifact_score"] = float(row["RH_final_artifact_score"])
            out["RH_final_artifact_positive_percent"] = float(row["RH_final_artifact_positive_percent"])
            out["RH_final_artifact_positive_count"] = int(row["RH_final_artifact_positive_count"])
            ranked.append(out)
        summary["within_condition"][condition] = correlation_summary(group, ranks, n)
    summary["pooled_secondary"] = correlation_summary(panel, None, len(panel), pooled=True)
    return ranked, summary


def correlation_summary(group: list[dict[str, object]], ranks, n: int, pooled: bool = False) -> dict[str, object]:
    out = {"n": n, "pooled": pooled, "components": {}, "combined": {}}
    if not group:
        return out
    # Convert all ranks to severity percentiles.  For a pooled secondary view,
    # rank within the pooled set; within-condition callers use their precomputed ranks.
    rank_map = {}
    for gap in GAPS:
        values = [float(row[gap]) for row in group]
        rr = rank_desc(values) if ranks is None else ranks[gap]
        rank_map[gap] = [(n - rank) / (n - 1) if n > 1 else None for rank in rr]
    combined = [statistics.mean(rank_map[gap][i] for gap in GAPS) for i in range(n)] if n > 1 else [None] * n
    rh = [float(row["RH_final_artifact_score"]) for row in group]
    for gap in GAPS:
        x = [v for v in rank_map[gap] if v is not None]
        out["components"][gap] = {"spearman": spearman(x, rh), "kendall_tau_b": kendall_tau_b(x, rh)}
    out["combined"] = {"spearman": spearman([v for v in combined if v is not None], rh), "kendall_tau_b": kendall_tau_b([v for v in combined if v is not None], rh)}
    for fraction in (0.10, 0.20, 0.25):
        gap_rows = []
        for gap in GAPS:
            gap_rows.append({"metric": gap, "gap_worst": sorted({str(row["assignment_id"]) for row in group}, key=lambda aid: next(float(r[gap]) for r in group if r["assignment_id"] == aid), reverse=True)})
        gap_set = set(worst_set(group, gap_rows[0]["metric"], fraction))
        # The primary overlap is combined-gap vs RH; component overlaps are retained.
        combined_order = sorted(range(n), key=lambda i: combined[i], reverse=True)
        combined_cutoff = combined_order[max(0, math.ceil(n * fraction) - 1)]
        combined_set = {str(group[i]["assignment_id"]) for i in range(n) if combined[i] >= combined[combined_cutoff]}
        rh_set = worst_set(group, "RH_final_artifact_score", fraction)
        out["combined"][f"worst_{int(fraction*100)}_percent_overlap"] = {"gap_count": len(combined_set), "rh_count": len(rh_set), "intersection_count": len(combined_set & rh_set), "gap_ids": sorted(combined_set), "rh_ids": sorted(rh_set)}
        out.setdefault("component_worst_overlap", {})[f"worst_{int(fraction*100)}_percent"] = {}
        for gap in GAPS:
            gs = worst_set(group, gap, fraction)
            out["component_worst_overlap"][f"worst_{int(fraction*100)}_percent"][gap] = {"gap_count": len(gs), "rh_count": len(rh_set), "intersection_count": len(gs & rh_set)}
    return out


def main() -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    rows, accounting = extract_rows()
    panel = panel_rows(rows)
    write_csv("dev3-auditor-rows.csv", rows)
    write_csv("dev3-assignment-panel.csv", panel)
    write_csv("dev3-paired-deltas.csv", paired_deltas(panel))
    summaries = {"all": summarize(rows, "all")}
    for condition in sorted({str(row["condition_id"]) for row in rows}):
        summaries[condition] = summarize([row for row in rows if row["condition_id"] == condition], condition)
    ranking_rows, ranking_summary = gap_rank_analysis(panel)
    write_csv("artifact-gap-rh-ranking.csv", ranking_rows)
    write_json("artifact-gap-rh-ranking-summary.json", ranking_summary)
    write_json("audit-accounting.json", accounting)
    write_json("dev3-summary.json", {"candidate": "attack_defense_v2.1_task_paraphrase_required_completion", "experiment_id": EXPERIMENT, "tasks": list(TASKS), "replicates": 3, "assignments": 36, "auditor_rows": 72, "summaries": summaries, "gap_rh_ranking": ranking_summary})
    for condition, summary in summaries.items():
        if condition == "all":
            continue
        panel_summary = summary["models"]["equal_weight_panel"]["metrics"]
        assert math.isclose(panel_summary["W_minus_S"], panel_summary["W"] - panel_summary["S"], abs_tol=1e-9)
        assert math.isclose(panel_summary["S_minus_H"], panel_summary["S"] - panel_summary["H"], abs_tol=1e-9)
        assert math.isclose(panel_summary["H_minus_A"], panel_summary["H"] - panel_summary["A"], abs_tol=1e-9)
        assert math.isclose(panel_summary["W_minus_A"], panel_summary["W"] - panel_summary["A"], abs_tol=1e-9)
    print(json.dumps({"assignments": 36, "auditor_rows": 72, "conditions": sorted(summaries), "report": str(REPORT)}))


if __name__ == "__main__":
    main()
