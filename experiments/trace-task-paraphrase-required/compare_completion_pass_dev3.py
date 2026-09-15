"""Join completion-pass results to the published fixed and parent cells.

The join is task/replicate/feedback exact.  It labels the historical completion
trace as the parent and never calls it a v2.1 RTT control.
"""
from __future__ import annotations

import csv
import json
from pathlib import Path


RUN = Path(__file__).resolve().parents[2]
OLD = RUN / "docs/reports/2026-09-15/rtt-clean-20260915"
NEW = RUN / "docs/reports/2026-09-15/rtt-task-required-pass-boundary"
METRICS = (
    "W", "W_train", "S", "H", "A", "W_minus_S", "S_minus_H",
    "H_minus_A", "W_minus_A",
)
WINDOWS = ("full_trajectory", "post_update", "final_artifact", "final_revision")
MODELS = ("gpt-5.6-sol", "claude-opus-5", "equal_weight_panel")
ARMS = {
    "full": ("full-static", "full-red-team-trace"),
    "user": ("user-simulator-static", "user-simulator-red-team-trace"),
}


def load(path: Path):
    return json.loads(path.read_text())


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="") as stream:
        return list(csv.DictReader(stream))


def delta_model(candidate: dict, reference: dict) -> dict:
    return {
        "metrics": {
            metric: candidate["metrics"][metric] - reference["metrics"][metric]
            for metric in METRICS
        },
        "rh": {
            window: {
                "confirmed_positive_percentage_points": (
                    candidate["rh"][window]["confirmed_positive_percent"]
                    - reference["rh"][window]["confirmed_positive_percent"]
                ),
                "mean_continuous_score": (
                    candidate["rh"][window]["mean_continuous_score"]
                    - reference["rh"][window]["mean_continuous_score"]
                ),
                "candidate_abstain": candidate["rh"][window]["abstain"],
                "reference_abstain": reference["rh"][window]["abstain"],
            }
            for window in WINDOWS
        },
    }


def main() -> None:
    old = load(OLD / "dev3-summary.json")
    new = load(NEW / "completion-pass-dev3-summary.json")
    comparison: dict[str, object] = {
        "candidate": new["candidate"],
        "candidate_experiment_id": new["experiment_id"],
        "comparison_semantics": (
            "matched static and completion-parent cells are reused from the clean "
            "bad950537c4d cohort; no matched v2.1 RTT cell exists"
        ),
        "arms": {},
    }
    for arm, (fixed_id, trace_id) in ARMS.items():
        fixed = old["summaries"][fixed_id]
        parent = old["summaries"][trace_id]
        candidate = new["summaries"][trace_id]
        arm_result = {
            "matched_fixed": fixed,
            "completion_parent": parent,
            "completion_pass": candidate,
            "candidate_minus_fixed": {},
            "candidate_minus_parent": {},
        }
        for model in MODELS:
            arm_result["candidate_minus_fixed"][model] = delta_model(
                candidate["models"][model], fixed["models"][model]
            )
            arm_result["candidate_minus_parent"][model] = delta_model(
                candidate["models"][model], parent["models"][model]
            )
        comparison["arms"][arm] = arm_result
    (NEW / "completion-pass-comparison.json").write_text(
        json.dumps(comparison, indent=2, ensure_ascii=False, allow_nan=False) + "\n"
    )

    old_panel = read_csv(OLD / "dev3-assignment-panel.csv")
    new_panel = read_csv(NEW / "completion-pass-dev3-assignment-panel.csv")
    old_by_key = {
        (row["task_id"], int(row["replicate"]), row["condition_id"]): row
        for row in old_panel
    }
    paired = []
    for row in new_panel:
        condition = row["condition_id"]
        arm = "full" if condition == "full-red-team-trace" else "user"
        fixed_id, parent_id = ARMS[arm]
        key = (row["task_id"], int(row["replicate"]))
        fixed = old_by_key[(*key, fixed_id)]
        parent = old_by_key[(*key, parent_id)]
        out: dict[str, object] = {
            "arm": arm,
            "task_id": row["task_id"],
            "replicate": int(row["replicate"]),
            "candidate_assignment_id": row["assignment_id"],
            "fixed_assignment_id": fixed["assignment_id"],
            "parent_assignment_id": parent["assignment_id"],
        }
        for metric in METRICS:
            value = float(row[metric])
            out[f"candidate_{metric}"] = value
            out[f"delta_vs_fixed_{metric}"] = value - float(fixed[metric])
            out[f"delta_vs_parent_{metric}"] = value - float(parent[metric])
        for window in WINDOWS:
            field = f"RH_{window}_score"
            value = float(row[field])
            out[f"candidate_{field}"] = value
            out[f"delta_vs_fixed_{field}"] = value - float(fixed[field])
            out[f"delta_vs_parent_{field}"] = value - float(parent[field])
        paired.append(out)
    if len(paired) != 18:
        raise RuntimeError(f"expected 18 paired candidate rows, got {len(paired)}")
    with (NEW / "completion-pass-paired-deltas.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(paired[0]), lineterminator="\n")
        writer.writeheader()
        writer.writerows(paired)
    print(json.dumps({"arms": sorted(ARMS), "paired_rows": len(paired)}, sort_keys=True))


if __name__ == "__main__":
    main()
