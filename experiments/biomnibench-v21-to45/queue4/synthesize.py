"""Provider-free synthesis of completed development evidence; no live-run mutation."""
from __future__ import annotations

import csv
import json
import math
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[3]
HISTORY = ROOT / "docs/reports/2026-09-11/trace-attack-defense-v3"
OUT = ROOT / "docs/reports/2026-09-12/biomnibench-v21-to45/queue4"
METRICS = ("W", "W_train", "S", "H", "A", "W_minus_S", "S_minus_H", "H_minus_A", "W_minus_A")
WINDOWS = ("full_trajectory", "post_update", "final_artifact", "final_revision")
INTERVENTIONS = {
    "v2.1": "Legacy User simulator plus separate admitted-rule reminder",
    "v3": "Budgeted User delivery, ranked base deficits and task-preserving simulator policy",
    "v3.1": "v3 plus proactive-only decision guard; guard did not fire in this cohort",
    "v3.2": "v3.1 plus stronger output-preservation instruction",
}


def load(path):
    return json.loads(path.read_text())


def write_json(name, value):
    (OUT / name).write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")


def write_csv(name, rows):
    with (OUT / name).open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def check_algebra(row):
    for gap, left, right in (("W_minus_S", "W", "S"), ("S_minus_H", "S", "H"),
                             ("H_minus_A", "H", "A"), ("W_minus_A", "W", "A")):
        assert math.isclose(row[gap], row[left] - row[right], abs_tol=1e-9), (gap, row)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    variants, paired, cases, by_auditor, windows = [], [], [], [], []
    for variant, directory in (("v3", "stress-outcomes"), ("v3.1", "stress-outcomes-v31"),
                               ("v3.2", "stress-outcomes-v32")):
        path = HISTORY / directory / "outcomes.json"
        packet = load(path)
        arms = [(variant, "v3")]
        if variant == "v3":
            arms.insert(0, ("v2.1", "v21"))
        for name, arm in arms:
            summary = packet[arm]
            assert summary["assignments"] == 9 and summary["auditor_rows"] == 18
            check_algebra(summary["means"])
            row = dict(cohort="historical_stress", variant=name, intervention=INTERVENTIONS[name],
                       assignments=9, judgments=sum(v["semantic_judgments"] for k, v in
                       packet["coverage"].items() if k.startswith(arm + ":")),
                       **{m: summary["means"][m] for m in METRICS},
                       **{"RH_" + w: summary["means"]["RH_" + w] for w in WINDOWS},
                       source=str(path.relative_to(ROOT)))
            variants.append(row)
            windows.append(dict(cohort="historical_stress", variant=name, windows=summary["windows"]))
        source = HISTORY / directory / "paired-v3-minus-v21.csv"
        with source.open() as f:
            raw = list(csv.DictReader(f))
        assert len(raw) == 18
        assert len({(r["task_id"], r["replicate"], r["model"]) for r in raw}) == 18
        for r in raw:
            values = {k: float(v) for k, v in r.items() if k not in ("task_id", "replicate", "model")}
            check_algebra(values)
            paired.append(dict(variant=variant, comparator="v2.1", cohort="historical_stress",
                               task_id=r["task_id"], replicate=int(r["replicate"]), model=r["model"],
                               **values, source=str(source.relative_to(ROOT))))
        current = [r for r in paired if r["variant"] == variant]
        keys = [m for m in current[0] if m in METRICS or m.startswith("RH_")]
        for task, rep in sorted({(r["task_id"], r["replicate"]) for r in current}):
            group = [r for r in current if (r["task_id"], r["replicate"]) == (task, rep)]
            assert {r["model"] for r in group} == {"gpt-5.6-sol", "claude-opus-5"}
            row = dict(variant=variant, task_id=task, replicate=rep,
                       **{m: mean(r[m] for r in group) for m in keys}, source=str(source.relative_to(ROOT)))
            check_algebra(row)
            cases.append(row)
        for auditor in sorted({r["model"] for r in current}):
            group = [r for r in current if r["model"] == auditor]
            row = dict(variant=variant, auditor=auditor, paired_rows=len(group),
                       **{m: mean(r[m] for r in group) for m in keys})
            check_algebra(row)
            by_auditor.append(row)
        for m in keys:
            expected = packet["v3"]["means"][m] - packet["v21"]["means"][m]
            assert math.isclose(mean(r[m] for r in current), expected, abs_tol=1e-9)

    control_path = ROOT / "docs/reports/2026-09-12/biomnibench-v21-to45/queue3/user_simulator-trace.json"
    control = load(control_path)
    assert control["complete"] and control["completed_audited_assignments"] == 9
    summary = control["summary"]
    variants.append(dict(cohort="canonical_dev3", variant="R0/v2.1", intervention=INTERVENTIONS["v2.1"],
                         assignments=9, judgments=sum(r["coverage"]["semantic_judgments"] for r in control["coverage"]),
                         **{m: summary["means"][m] for m in METRICS},
                         **{"RH_" + w: summary["means"]["RH_" + w] for w in WINDOWS},
                         source=str(control_path.relative_to(ROOT))))
    assert variants[-1]["judgments"] == 336
    windows.append(dict(cohort="canonical_dev3", variant="R0/v2.1", windows=summary["windows"],
                        native_panel_union=control["native_panel_union"]))

    extremes = {}
    for variant in ("v3", "v3.1", "v3.2"):
        rows = [r for r in cases if r["variant"] == variant]
        extremes[variant] = {}
        for metric in METRICS:
            lo, hi = min(r[metric] for r in rows), max(r[metric] for r in rows)
            extremes[variant][metric] = {
                "smallest_delta": [r for r in rows if r[metric] == lo],
                "largest_delta": [r for r in rows if r[metric] == hi],
            }
    write_csv("completed-variants.csv", variants)
    write_csv("historical-paired-auditor-deltas.csv", paired)
    write_csv("historical-paired-case-deltas.csv", cases)
    write_csv("historical-auditor-mean-deltas.csv", by_auditor)
    write_json("synthesis.json", dict(provider_calls=0, new_recipes=0, incumbent="attack_defense_v2.1",
               decision="Wait for complete current R1/R2 and within-policy comparisons; no further refinement dispatched",
               completed_variants=variants, all_windows=windows, historical_auditor_means=by_auditor,
               extremes=extremes, algebra_checked_rows=len(paired), historical_case_count=len(cases),
               limitations=["Historical stress and canonical dev3 are separate cohorts, not paired with each other",
                            "Historical stress static starts differ; these are trace-versus-trace deltas",
                            "Three clusters and fresh continuations do not isolate causal mechanisms",
                            "No partial R1/R2 or policy-cell outcome means are used"]))
    lines = ["# Completed development evidence", "", "Generated from saved reports; no provider calls. RH columns are equal-weight confirmed-positive percentages, not native union rates.", "",
             "| Cohort / variant | Assignments / judgments | W / W_train | S | H | A | W−S | S−H | H−A | W−A | RH full / post / final artifact / final revision |",
             "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for r in variants:
        lines.append(f"| {r['cohort']} / {r['variant']} | {r['assignments']}/9; {r['judgments']}/{r['judgments']} | "
                     + f"{r['W']:.2f} / {r['W_train']:.2f} | "
                     + " | ".join(f"{r[m]:.2f}" for m in METRICS[2:]) + " | "
                     + " / ".join(f"{r['RH_' + w]:.2f}" for w in WINDOWS) + " |")
    lines.extend(["", "## All historical paired cases", "", "Candidate minus its own matched stress v2.1 trace control; both auditors averaged. These are not comparisons with a static baseline.", "",
                  "| Variant / task / replicate | ΔW | ΔS | ΔH | ΔA | Δ(W−S) | Δ(S−H) | Δ(H−A) | Δ(W−A) |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for r in cases:
        lines.append(f"| {r['variant']} / {r['task_id']} / {r['replicate']} | "
                     + " | ".join(f"{r[m]:+.2f}" for m in METRICS if m != "W_train") + " |")
    lines.extend(["", "## Auditor mean differences", "", "| Variant / auditor | ΔW | ΔS | ΔH | ΔA | Δ(W−S) | Δ(S−H) | Δ(H−A) | Δ(W−A) |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|"])
    for r in by_auditor:
        lines.append(f"| {r['variant']} / {r['auditor']} | "
                     + " | ".join(f"{r[m]:+.2f}" for m in METRICS if m != "W_train") + " |")
    (OUT / "tables.md").write_text("\n".join(lines) + "\n")
    print(json.dumps(dict(completed_variant_rows=len(variants), paired_auditor_rows=len(paired),
                          paired_cases=len(cases), auditor_aggregates=len(by_auditor), provider_calls=0)))


if __name__ == "__main__":
    main()
