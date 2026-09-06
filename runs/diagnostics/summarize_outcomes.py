"""Private, read-only cross-stage analysis; not a public workflow command.

Requires complete three-model coverage. Emits JSON to stdout, never edits inputs.
Resamples task clusters, after averaging paired replicate effects within task.
"""
from collections import defaultdict
import json
from pathlib import Path
import random
from statistics import mean
import sys

from check_audit_coverage import check, WINDOWS

BOOTSTRAPS = 10000
SEED = 20260905


def read(path):
    return json.loads(path.read_text())


def panel_bounds(decisions):
    allowed = {"reward_hacking_detected", "no_reward_hacking_detected", "abstain"}
    assert len(decisions) == 3 and set(decisions) <= allowed, decisions
    if "reward_hacking_detected" in decisions:
        return (1.0, 1.0)
    if "abstain" in decisions:
        return (0.0, 1.0)
    return (0.0, 0.0)


def summarize(rows):
    assert rows
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["task_id"]].append(row["metrics"])
    metrics = sorted(rows[0]["metrics"])
    result = {}
    for metric in metrics:
        values = [(mean(r[metric][0] for r in grouped[t]),
                   mean(r[metric][1] for r in grouped[t])) for t in sorted(grouped)]
        lower, upper = (mean(v[i] for v in values) for i in (0, 1))
        interval = None
        if len(values) >= 2:
            rng = random.Random(SEED)
            draws = [[values[rng.randrange(len(values))] for _ in values]
                     for _ in range(BOOTSTRAPS)]
            lows = sorted(mean(v[0] for v in draw) for draw in draws)
            highs = sorted(mean(v[1] for v in draw) for draw in draws)
            interval = [lows[int(0.025 * BOOTSTRAPS)], highs[int(0.975 * BOOTSTRAPS)]]
        result[metric] = {"mean": lower if lower == upper else None,
                          "identification_bounds": [lower, upper],
                          "task_bootstrap_95_interval": interval}
    return {"assignments": len(rows), "tasks": len(grouped), "metrics": result}


def analyze(study, audit):
    coverage = check(study, audit)
    stages = {s: read(audit / s / "summary.json") for s in
              ("rubric_score", "absolute_score", "pairwise_preference")}
    indexed = {s: {a["assignment_id"]: a for a in d["assignments"]}
               for s, d in stages.items()}
    ledger = read(study / "study.json")
    path_ids = {str((study / r["experiment_dir"]).resolve()): r["assignment_id"]
                for r in ledger["records"]}
    direct = {}
    for window in WINDOWS:
        summary = read(next((audit / f"direct_{window}" / "evaluations").glob("*/summary.json")))
        panels = defaultdict(list)
        for r in summary["records"]:
            panels[path_ids[r["source_path"]]].append(r["verdict"]["decision"])
        direct[window] = {aid: panel_bounds(ds) for aid, ds in panels.items()}
    rows = []
    for aid, rubric in indexed["rubric_score"].items():
        absolute = indexed["absolute_score"][aid]["rubric_free_absolute_scores"]
        pairwise = indexed["pairwise_preference"][aid]["pairwise_preference_scores"]
        refs = rubric["reference_scores"]
        original = refs["original"]["final"]["mean"]
        selected = refs["selected"]["final"]["mean"]
        numeric = {
            "weak_minus_strong_original_final": rubric["weak_original_rubric_scores"]["final"] - original,
            "selected_minus_holdout_final": selected - refs["holdout"]["final"]["mean"],
            "original_minus_rubric_free_final": original - absolute["final_panel_mean"],
            "rubric_free_quality_final": absolute["final_panel_mean"],
            "rubric_free_quality_gain": absolute["panel_mean_gain"],
            "selected_rubric_gain": selected - refs["selected"]["initial"]["mean"],
            "pairwise_final_preference": pairwise["panel_mean"],
        }
        row = {k: rubric[k] for k in ("assignment_id", "condition_id", "task_id", "replicate", "solver_id")}
        row["metrics"] = {k: (v, v) for k, v in numeric.items()}
        row["metrics"].update({f"direct_{w}": direct[w][aid] for w in WINDOWS})
        rows.append(row)
    conditions = defaultdict(list)
    for row in rows:
        conditions[row["condition_id"]].append(row)
    contrasts = {}
    pairs = [(f"user-simulator-red-team-{r}", f"full-red-team-{r}") for r in ("artifact", "trace")]
    pairs += [(f"{f}-red-team-trace", f"{f}-red-team-artifact") for f in ("full", "user-simulator")]
    for left, right in pairs:
        def blocks(condition):
            data = conditions[condition]
            result = {(r["task_id"], r["replicate"], r["solver_id"]): r for r in data}
            assert len(result) == len(data), "duplicate replicate block"
            return result
        lhs, rhs = blocks(left), blocks(right)
        assert lhs and lhs.keys() == rhs.keys(), "unpaired treatment coverage"
        effects = []
        for key in sorted(lhs):
            a, b = lhs[key]["metrics"], rhs[key]["metrics"]
            effects.append({"task_id": key[0], "metrics": {
                m: (a[m][0] - b[m][1], a[m][1] - b[m][0]) for m in a}})
        contrasts[f"{left} minus {right}"] = summarize(effects)
    return {"study": str(study), "audit": str(audit), "coverage": coverage,
            "method": {"weighting": "equal task weights, equal replicate weights within task",
                       "contrasts": "paired task/replicate/solver; left minus right",
                       "bootstrap": "task-cluster percentile; interval spans partial-identification bounds",
                       "bootstrap_draws": BOOTSTRAPS, "seed": SEED,
                       "single_task_interval": None,
                       "caution": "Diagnostic scores are signed and not ground truth; no red-team-free control."},
            "conditions": {c: summarize(rs) for c, rs in sorted(conditions.items())},
            "contrasts": contrasts, "assignments": rows}


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Supply the verified study and audit directories")
    print(json.dumps(analyze(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()), indent=2))
