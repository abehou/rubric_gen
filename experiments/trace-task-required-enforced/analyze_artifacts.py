"""Provider-free, complete-cohort gap/RH ranking and evidence index."""
from __future__ import annotations

import argparse
from collections import defaultdict
import json
from pathlib import Path
from statistics import mean
import sys

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "experiments/trace-attack-defense-v21/report"),
                str(ROOT / "scripts/diagnostics")]
from report_reconstruct import reconstruct


def ranks(values):
    """Ascending ranks, average ranks for ties; larger means worse."""
    return [1 + sum(y < x for y in values)
            + (sum(y == x for y in values) - 1) / 2 for x in values]


def spearman(xs, ys):
    x, y = ranks(xs), ranks(ys)
    mx, my = mean(x), mean(y)
    denominator = (sum((v - mx) ** 2 for v in x)
                   * sum((v - my) ** 2 for v in y)) ** 0.5
    return (sum((a - mx) * (b - my) for a, b in zip(x, y))
            / denominator if denominator else None)


def analyze(study, audit):
    panel = ("gpt-5.6-sol", "claude-opus-5")
    coverage, rows = reconstruct(study, audit, panel, expected_holdouts=2)
    groups = defaultdict(list)
    for row in rows:
        groups[row["condition_id"], row["assignment_id"]].append(row)
    result = {"coverage": coverage, "arms": {}, "limitations": [
        "Descriptive signed-gap ranks within nine artifacts per arm; not a causal test.",
        "RH severity and RH binary incidence are separate; ties receive average ranks.",
        "Undefined correlations (constant RH) are null; no cases are dropped.",
        "Local H averages two holdouts; historical Results20 is not a matched cohort.",
    ]}
    for arm in sorted({key[0] for key in groups}):
        items = []
        for (condition, aid), rs in sorted(groups.items()):
            if condition != arm:
                continue
            assert {r["model"] for r in rs} == set(panel)
            items.append({
                "assignment_id": aid, "task_id": rs[0]["task_id"],
                "values": {k: mean(r["values"][k] for r in rs) for k in rs[0]["values"]},
                "rh_score": mean(r["direct"]["full_trajectory"]["score"] for r in rs),
                "rh_percent": 100 * mean(r["direct"]["full_trajectory"]["decision"] == "reward_hacking_detected" for r in rs),
                "auditors": [{"model": r["model"], "values": r["values"],
                              "rh": r["direct"], "quality_path": r["quality_path"],
                              "rubric_paths": r["rubric_paths"], "state_path": r["state_path"]} for r in rs],
            })
        gap_ranks = {k: ranks([r["values"][k] for r in items]) for k in ("WS", "SH", "HA")}
        for i, item in enumerate(items):
            item["gap_ranks"] = {k: rs[i] for k, rs in gap_ranks.items()}
            item["gap_rank_sum"] = sum(item["gap_ranks"].values())
        task_means = {
            task: {k: mean(r["values"][k] for r in items if r["task_id"] == task)
                   for k in items[0]["values"]}
            for task in sorted({r["task_id"] for r in items})}
        result["arms"][arm] = {
            "artifacts": items, "task_means": task_means,
            "spearman_rank_sum_vs_rh_severity": spearman([r["gap_rank_sum"] for r in items], [r["rh_score"] for r in items]),
            "spearman_rank_sum_vs_rh_incidence": spearman([r["gap_rank_sum"] for r in items], [r["rh_percent"] for r in items]),
        }
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = analyze(args.study.resolve(), args.audit.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    for arm, data in result["arms"].items():
        print(arm, {k: v for k, v in data.items() if k != "artifacts"})
