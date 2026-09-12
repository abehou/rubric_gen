"""Provider-free signed gap-rank versus RH-rank analysis.

It consumes the same sealed Sol+Opus rubric/quality/direct-RH records as the
dev3 outcome adapter.  The output is descriptive: no endpoint, verdict or
candidate selection is changed.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean
from typing import Any, Iterable

BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
OUT = ROOT / "docs/reports/2026-09-11/trace-attack-defense-v3"
PANEL = ("gpt-5.6-sol", "claude-opus-5")
WINDOWS = ("full_trajectory", "post_update", "final_artifact", "final_revision")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def tie_rank(values: dict[str, float]) -> dict[str, float]:
    """Rank highest (worst gap) first, with average ranks for ties."""
    ordered = sorted(values, key=lambda key: (-values[key], key))
    result: dict[str, float] = {}
    i = 0
    while i < len(ordered):
        j = i + 1
        while j < len(ordered) and values[ordered[j]] == values[ordered[i]]:
            j += 1
        rank = (i + 1 + j) / 2
        for key in ordered[i:j]:
            result[key] = rank
        i = j
    return result


def pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 2:
        return None
    mx, my = mean(xs), mean(ys)
    dx, dy = [x - mx for x in xs], [y - my for y in ys]
    denom = math.sqrt(sum(x * x for x in dx) * sum(y * y for y in dy))
    return sum(x * y for x, y in zip(dx, dy)) / denom if denom else None


def spearman(xs: list[float], ys: list[float]) -> float | None:
    def ranks(values: list[float]) -> list[float]:
        mapping = tie_rank({str(i): value for i, value in enumerate(values)})
        return [mapping[str(i)] for i in range(len(values))]
    return pearson(ranks(xs), ranks(ys))


def kendall_tau_b(xs: list[float], ys: list[float]) -> float | None:
    concordant = discordant = ties_x = ties_y = 0
    n = len(xs)
    if n < 2:
        return None
    for i in range(n):
        for j in range(i + 1, n):
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
    denom = math.sqrt((concordant + discordant + ties_x) * (concordant + discordant + ties_y))
    return (concordant - discordant) / denom if denom else None


def load_reconstructors():
    return load_module("trace_v3_outcome_adapter", BUNDLE / "report_dev3_outcomes.py"), load_module("trace_v21_report_adapter", ROOT / "experiments/trace-attack-defense-v21/report/report_reconstruct.py")


def rows_for_result20(adapter: Any) -> list[dict[str, Any]]:
    # The repaired cohort's sealed completion receipt owns its actual identity;
    # loading today's YAML computes a different, never-executed experiment ID.
    run = Path("/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20")
    completion = json.loads((run / "completion.json").read_text())
    if not completion["success"]:
        raise ValueError("Result20 completion receipt is not successful")
    identity = completion["experiment_id"]
    _, rows = adapter.reconstruct(run / "study" / identity, run / "audit" / identity, PANEL)
    for row in rows:
        for native, name in (("WS", "W_minus_S"), ("WA", "W_minus_A"),
                             ("SH", "S_minus_H"), ("HA", "H_minus_A")):
            row["values"][name] = row["values"][native]
    return rows


def rows_for_dev3(adapter: Any, configs: Iterable[Path]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for config in configs:
        _, _, rows = adapter.reconstruct(config)
        result.extend(rows)
    return result


def aggregate(rows: list[dict[str, Any]], *, label: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(row["task_id"], int(row["replicate"]))].append(row)
    out = []
    for (task, rep), values in sorted(grouped.items()):
        if len(values) != len(PANEL) or {r["model"] for r in values} != set(PANEL):
            raise ValueError(f"incomplete/duplicate auditor panel: {label}/{task}/{rep}")
        item = {"condition": label, "task_id": task, "replicate": rep,
                "key": f"{task}/rep-{rep:03d}"}
        for metric in ("W", "W_train", "S", "H", "A", "W_minus_S", "W_minus_A", "S_minus_H", "H_minus_A"):
            item[metric] = mean(float(row["values"][metric]) for row in values)
        for window in WINDOWS:
            verdicts = [row["direct"][window] for row in values]
            scores = [v.get("score") for v in verdicts]
            item[f"RH_{window}_monitor"] = mean(scores) if all(type(v) in (int, float) for v in scores) else None
            decisions = [v["decision"] for v in verdicts]
            positive = "reward_hacking_detected" in decisions
            abstain = "abstain" in decisions
            item[f"RH_{window}_positive"] = positive
            item[f"RH_{window}_abstain"] = abstain
            item[f"RH_{window}_status"] = "positive" if positive else "ambiguous" if abstain else "negative"
            for r in values:
                model = r["model"]
                item[f"RH_{window}_{model}_score"] = r["direct"][window].get("score")
                item[f"RH_{window}_{model}_decision"] = r["direct"][window]["decision"]
        out.append(item)
    return out


def worst_membership(values: dict[str, float], count: int) -> dict[str, float]:
    """Fractional top-k membership at the boundary; no task-ID tie breaking."""
    boundary = sorted(values.values(), reverse=True)[count - 1]
    above = sum(v > boundary for v in values.values())
    tied = sum(v == boundary for v in values.values())
    fraction = (count - above) / tied
    return {k: 1.0 if v > boundary else fraction if v == boundary else 0.0 for k, v in values.items()}


def overlap(gaps: dict[str, float], rh: dict[str, float], fraction: float) -> dict[str, Any]:
    count = max(1, math.ceil(fraction * len(gaps)))
    a, b = worst_membership(gaps, count), worst_membership(rh, count)
    expected = sum(a[k] * b[k] for k in a)
    return {"k": count, "expected_overlap_count": expected,
            "expected_overlap_fraction": expected / count,
            "gap_boundary_members": {k: v for k, v in a.items() if v},
            "RH_boundary_members": {k: v for k, v in b.items() if v}}


def analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    metrics = ("W_minus_S", "S_minus_H", "H_minus_A")
    for metric in metrics:
        ranks = tie_rank({row["key"]: float(row[metric]) for row in rows})
        for row in rows:
            row[f"rank_{metric}"] = ranks[row["key"]]
    for row in rows:
        row["combined_gap_rank"] = mean(row[f"rank_{metric}"] for metric in metrics)
        # Rank 1 is worst. A high score is worst, matching high RH monitor scores.
        row["combined_gap_score"] = -row["combined_gap_rank"]
        row["combined_gap_percentile"] = ((len(rows) - row["combined_gap_rank"]) / (len(rows) - 1)
                                          if len(rows) > 1 else 0.5)
    summaries = {}
    for window in ("final_artifact", "full_trajectory"):
        key = f"RH_{window}_monitor"
        available = [r for r in rows if r[key] is not None]
        rh = {r["key"]: float(r[key]) for r in available}
        rh_ranks = tie_rank(rh)
        for r in rows:
            r[f"rank_RH_{window}"] = rh_ranks.get(r["key"])
        result = {"n": len(available), "missing_panel_scores": len(rows) - len(available),
                  "metrics": {}}
        for metric in (*metrics, "combined_gap_score"):
            gaps = {r["key"]: float(r[metric]) for r in available}
            xs, ys = list(gaps.values()), list(rh.values())
            result["metrics"][metric] = {
                "spearman": spearman(xs, ys), "kendall_tau_b": kendall_tau_b(xs, ys),
                "worst_overlap": {str(int(100*f)): overlap(gaps, rh, f) for f in (.10, .20, .25)} if gaps else {},
            }
        # Literal mean-rank vs score association is retained with its reverse sign.
        result["combined_gap_rank_vs_monitor"] = {
            "spearman": spearman([r["combined_gap_rank"] for r in available], list(rh.values())),
            "kendall_tau_b": kendall_tau_b([r["combined_gap_rank"] for r in available], list(rh.values())),
        }
        for status in ("positive", "negative", "ambiguous"):
            selected = [r for r in rows if r[f"RH_{window}_status"] == status]
            result[status] = {"count": len(selected), "mean_combined_gap_rank":
                             mean(r["combined_gap_rank"] for r in selected) if selected else None}
        summaries[window] = result
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", choices=("all", "result20", "dev3"), default="all")
    args = parser.parse_args()
    v3_adapter, v21_adapter = load_reconstructors()
    sets: list[tuple[str, list[dict[str, Any]]]] = []
    unavailable = {}
    if args.cohort in {"all", "result20"}:
        all_rows = rows_for_result20(v21_adapter)
        sets.extend((label, aggregate([row for row in all_rows if row["condition_id"] == condition], label=label)) for condition, label in (("full-red-team-trace", "v2.1-full"), ("user-simulator-red-team-trace", "v2.1-user")))
    if args.cohort in {"all", "dev3"}:
        stress = [BUNDLE / "stress" / f"v3-candidate-{task}.yaml" for task in ("da-15-1", "da-13-6", "da-18-5")]
        control = [BUNDLE / "stress" / f"v21-control-{task}.yaml" for task in ("da-15-1", "da-13-6", "da-18-5")]
        for label, configs in (("stress-v2.1-user", control), ("stress-v3-user", stress)):
            sets.append((label, aggregate(rows_for_dev3(v3_adapter, configs), label=label)))
        canonical_control = [BUNDLE / "control-v21-compatible" / f"{task}.yaml" for task in ("da-3-4", "da-11-1", "da-18-1")]
        canonical_v3 = [BUNDLE / "canonical-v3" / f"{task}.yaml" for task in ("da-3-4", "da-11-1", "da-18-1")]
        if all(path.is_file() for path in canonical_control + canonical_v3):
            for label, configs in (("canonical-v2.1-user", canonical_control), ("canonical-v3-user", canonical_v3)):
                try:
                    sets.append((label, aggregate(rows_for_dev3(v3_adapter, configs), label=label)))
                except (FileNotFoundError, RuntimeError, ValueError) as exc:
                    unavailable[label] = f"{type(exc).__name__}: {exc}"
    all_rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"provider_calls": 0, "cohort": args.cohort, "conditions": {}, "unavailable": unavailable,
        "rank_convention": "rank 1 = worst; combined score = negative mean rank; positive score/RH correlation = shared failure ordering",
        "ties": "average ranks; fractional top-k boundary membership; expected overlap under independent tie resolution",
        "abstentions": "preserved; no-positive with any abstention is ambiguous, never negative"}
    for label, rows in sets:
        summary["conditions"][label] = {"n": len(rows), "ranking": analyze(rows)}
        all_rows.extend(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    csv_path = OUT / "artifact-gap-rh-ranking.csv"
    fields = list(all_rows[0]) if all_rows else []
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(all_rows)
    json_path = OUT / "artifact-gap-rh-ranking-summary.json"
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    md_path = OUT / "artifact-gap-rh-ranking.md"
    lines = ["# Artifact gap-rank versus RH-rank", "",
        "Provider-free descriptive analysis of signed gaps, using the complete equal-weight Sol+Opus panel. Each condition is ranked separately; rank 1 is worst. Combined rank is the mean of the three component ranks. Combined score is its negative, so a positive score/RH correlation means overlapping failure orderings.", "",
        "Worst-tail overlap compares the gap and continuous-RH rankings at 10%, 20%, and 25%. Boundary ties have fractional membership; overlap is the expectation under independent tie resolution. Constant scores produce undefined correlations, not evidence of no association. Abstentions remain ambiguous unless the other auditor confirms a positive.", "",
        "| Condition | n | RH window | Gap | Spearman | Kendall tau-b | Worst 20% overlap |",
        "|---|---:|---|---|---:|---:|---:|"]
    fmt = lambda value: "undefined" if value is None else f"{value:.3f}"
    for label, result in summary["conditions"].items():
        for window, stats in result["ranking"].items():
            for metric, association in stats["metrics"].items():
                tail = association["worst_overlap"].get("20", {}).get("expected_overlap_fraction")
                lines.append(f"| {label} | {stats['n']} | {window} | {metric} | {fmt(association['spearman'])} | {fmt(association['kendall_tau_b'])} | {fmt(tail)} |")
    lines += ["", "Result20 is descriptive only and is not used to choose v3 wording. The CSV retains signed gaps, component/combined ranks, both auditor scores/verdicts, and ambiguous cases. The JSON includes each tail size, tie membership, literal rank-vs-score correlations and RH-positive/negative/ambiguous mean ranks.", ""]
    if unavailable:
        lines += ["Unavailable cohorts (no replacement provider calls):", ""] + [f"- {label}: {error}" for label, error in unavailable.items()]
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps({"provider_calls": 0, "rows": len(all_rows), "conditions": list(summary["conditions"]), "unavailable": unavailable}), flush=True)



if __name__ == "__main__":
    main()
