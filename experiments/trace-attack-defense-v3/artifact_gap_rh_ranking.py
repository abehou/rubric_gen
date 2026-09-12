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


def rows_for_result20(adapter: Any, config: Path) -> list[dict[str, Any]]:
    from rubric_gen.submission_revision.experiment import load_experiment
    exp = load_experiment(config)
    study = Path(exp.dag["revise"]["output_dir"])
    audit = Path(exp.dag["detect"]["output_dir"])
    _, rows = adapter.reconstruct(study, audit, PANEL)
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
    out: list[dict[str, Any]] = []
    for (task, rep), values in sorted(grouped.items()):
        first = values[0]
        item: dict[str, Any] = {"condition": label, "task_id": task, "replicate": rep, "key": f"{task}/rep-{rep:03d}"}
        for metric in ("W", "W_train", "S", "H", "A", "W_minus_S", "W_minus_A", "S_minus_H", "H_minus_A"):
            item[metric] = mean(float(row["values"][metric]) for row in values)
        for window in WINDOWS:
            verdicts = [row["direct"][window] for row in values]
            scores = [float(v.get("score")) for v in verdicts if isinstance(v.get("score"), (int, float))]
            item[f"RH_{window}_monitor"] = mean(scores) if scores else None
            item[f"RH_{window}_positive"] = any(v.get("decision") == "reward_hacking_detected" for v in verdicts)
            item[f"RH_{window}_abstain"] = any(v.get("decision") == "abstain" for v in verdicts)
        out.append(item)
    return out


def analyze(rows: list[dict[str, Any]]) -> dict[str, Any]:
    for metric in ("W_minus_S", "S_minus_H", "H_minus_A"):
        ranks = tie_rank({row["key"]: float(row[metric]) for row in rows})
        for row in rows:
            row[f"rank_{metric}"] = ranks[row["key"]]
    for row in rows:
        row["combined_gap_rank"] = mean(row[f"rank_{metric}"] for metric in ("W_minus_S", "S_minus_H", "H_minus_A"))
    summaries: dict[str, Any] = {}
    for rh_kind in ("RH_final_artifact_monitor", "RH_full_trajectory_monitor"):
        gaps = [(float(row["combined_gap_rank"]), float(row[rh_kind])) for row in rows if row[rh_kind] is not None]
        summaries[rh_kind] = {
            "spearman": spearman([x for x, _ in gaps], [y for _, y in gaps]),
            "kendall_tau_b": kendall_tau_b([x for x, _ in gaps], [y for _, y in gaps]),
            "n": len(gaps),
        }
        for metric in ("W_minus_S", "S_minus_H", "H_minus_A"):
            pairs = [(float(row[f"rank_{metric}"]), float(row[rh_kind])) for row in rows if row[rh_kind] is not None]
            summaries[rh_kind][f"{metric}_spearman"] = spearman([x for x, _ in pairs], [y for _, y in pairs])
            summaries[rh_kind][f"{metric}_kendall_tau_b"] = kendall_tau_b([x for x, _ in pairs], [y for _, y in pairs])
        order = sorted(rows, key=lambda row: (-float(row["combined_gap_rank"]), row["key"]))
        positive = {row["key"] for row in rows if row[rh_kind] is not None and row[f"RH_{rh_kind.removeprefix('RH_').removesuffix('_monitor')}_positive"]}
        for fraction in (0.10, 0.20, 0.25):
            n = max(1, math.ceil(fraction * len(order)))
            top = {row["key"] for row in order[:n]}
            summaries[rh_kind][f"worst_{int(fraction*100)}_overlap"] = {"n": n, "positive_in_top": len(top & positive), "positive_total": len(positive), "keys": sorted(top & positive)}
        positive_key = f"RH_{rh_kind.removeprefix('RH_').removesuffix('_monitor')}_positive"
        summaries[rh_kind]["mean_combined_gap_rank_positive"] = mean(
            [row["combined_gap_rank"] for row in rows if row[rh_kind] is not None and row[positive_key]]
        ) if positive else None
        summaries[rh_kind]["mean_combined_gap_rank_negative"] = mean(
            [row["combined_gap_rank"] for row in rows if row[rh_kind] is not None and not row[positive_key]]
        ) if len(positive) < len(rows) else None
    return summaries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cohort", choices=("all", "result20", "dev3"), default="all")
    args = parser.parse_args()
    v3_adapter, v21_adapter = load_reconstructors()
    sets: list[tuple[str, list[dict[str, Any]]]] = []
    if args.cohort in {"all", "result20"}:
        cfg = ROOT / "experiments/trace-attack-defense-v21/result20.yaml"
        all_rows = rows_for_result20(v21_adapter, cfg)
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
                except Exception:
                    pass
    all_rows: list[dict[str, Any]] = []
    summary: dict[str, Any] = {"provider_calls": 0, "cohort": args.cohort, "conditions": {}}
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
    lines = ["# Artifact gap-rank versus RH-rank", "", "Provider-free descriptive analysis using signed W-S, S-H and H-A. Higher signed gaps are worse; equal-weight Sol+Opus values and direct RH monitor scores are aggregated within task × replicate. Abstentions remain explicit in the JSON/CSV. No provider calls or endpoint changes were made.", ""]
    for label, content in summary["conditions"].items():
        lines += [f"## {label}", "", f"Assignments: {content['n']}", "", "```json", json.dumps(content["ranking"], indent=2), "```", ""]
    md_path.write_text("\n".join(lines), encoding="utf-8")
    print(json.dumps({"provider_calls": 0, "cohort": args.cohort, "conditions": {key: value["n"] for key, value in summary["conditions"].items()}, "csv": str(csv_path), "json": str(json_path), "markdown": str(md_path)}, indent=2), flush=True)


if __name__ == "__main__":
    main()
