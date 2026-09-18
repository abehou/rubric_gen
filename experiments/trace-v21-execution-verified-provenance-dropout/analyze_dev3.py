"""Compare provenance/high-proposer Dev3 at 0%, 30%, and 50% dropout."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import importlib.util
import json
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic


ROOT = Path(__file__).resolve().parents[2]
BASE_PATH = (
    ROOT
    / "experiments/trace-v21-execution-verified-high-allocation"
    / "analyze_matched_dev3.py"
)
COST_PATH = (
    ROOT
    / "experiments/trace-v21-execution-verified-proactive-high-proposer"
    / "analyze_matched_dev3.py"
)
PANEL = ("gpt-5.6-sol", "claude-opus-5")
RATES = ("0", "30", "50")


def _load(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load analysis helpers from {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _rate(row: dict) -> str:
    condition = row["condition_id"]
    if condition.endswith("dropout-30"):
        return "30"
    if condition.endswith("dropout-50"):
        return "50"
    return "0"


def _dropout_summary(rows: list[dict], base) -> dict:
    assignments = base.assignment_dirs(rows)
    per_turn: list[dict] = []
    per_assignment: list[dict] = []
    for assignment_id, directory in sorted(assignments.items()):
        manifest = _read(directory / "manifest.json")
        turn_rows = []
        for path in sorted((directory / "rubric-dropout").glob("s*.json")):
            payload = _read(path)
            retained = set(payload["retained_criterion_ids"])
            dropped = set(payload["dropped_criterion_ids"])
            eligible = set(payload["eligible_criterion_ids"])
            protected = set(payload["protected_ids"])
            row = {
                "assignment_id": assignment_id,
                "arm": base.arm({"condition_id": manifest["condition_id"]}),
                "task_id": manifest["task_id"],
                "replicate": manifest["replicate"],
                "submission_id": path.stem,
                "configured_rate": payload["configured_rate"],
                "deterministic_key": payload["deterministic_key"],
                "eligible_ids": sorted(eligible),
                "protected_ids": sorted(protected),
                "protected_reason": payload["protected_reason"],
                "retained_ids": sorted(retained),
                "dropped_ids": sorted(dropped),
                "retained_learned_ids": payload["retained_learned_criterion_ids"],
                "dropped_learned_ids": payload["dropped_learned_criterion_ids"],
                "realized_fraction": payload["realized_fraction"],
                "solver_visible_masked_score": payload["solver_visible_masked_score"],
                "full_canonical_score": payload["full_canonical_score"],
            }
            if not dropped <= eligible:
                raise RuntimeError(f"dropped criterion outside eligible set: {path}")
            if protected & dropped:
                raise RuntimeError(f"protected criterion was dropped: {path}")
            per_turn.append(row)
            turn_rows.append(row)

        ordinary_universe = set().union(
            *(set(row["eligible_ids"]) for row in turn_rows)
        ) if turn_rows else set()
        learned_universe = set().union(
            *(
                set(row["retained_learned_ids"]) | set(row["dropped_learned_ids"])
                for row in turn_rows
            )
        ) if turn_rows else set()
        ordinary_seen: set[str] = set()
        learned_seen: set[str] = set()
        cumulative = []
        for revision_index, row in enumerate(turn_rows, start=1):
            ordinary_seen.update(row["retained_ids"])
            learned_seen.update(row["retained_learned_ids"])
            cumulative.append({
                "revision_index": revision_index,
                "submission_id": row["submission_id"],
                "ordinary_ever_exposed": len(ordinary_seen & ordinary_universe),
                "ordinary_final_universe": len(ordinary_universe),
                "ordinary_fraction": (
                    len(ordinary_seen & ordinary_universe) / len(ordinary_universe)
                    if ordinary_universe else 1.0
                ),
                "learned_ever_exposed": len(learned_seen & learned_universe),
                "learned_final_universe": len(learned_universe),
                "learned_fraction": (
                    len(learned_seen & learned_universe) / len(learned_universe)
                    if learned_universe else 1.0
                ),
            })
        per_assignment.append({
            "assignment_id": assignment_id,
            "arm": base.arm({"condition_id": manifest["condition_id"]}),
            "task_id": manifest["task_id"],
            "replicate": manifest["replicate"],
            "turn_count": len(turn_rows),
            "ordinary_universe_count": len(ordinary_universe),
            "ordinary_ever_exposed_count": len(ordinary_seen & ordinary_universe),
            "ordinary_complete_reconstruction": ordinary_universe <= ordinary_seen,
            "learned_universe_count": len(learned_universe),
            "learned_ever_exposed_count": len(learned_seen & learned_universe),
            "learned_complete_reconstruction": learned_universe <= learned_seen,
            "cumulative_exposure": cumulative,
        })

    by_arm = {}
    for arm_name in ("full", "user"):
        turns = [row for row in per_turn if row["arm"] == arm_name]
        assignments_for_arm = [
            row for row in per_assignment if row["arm"] == arm_name
        ]
        by_arm[arm_name] = {
            "turns": len(turns),
            "mean_realized_fraction": (
                sum(row["realized_fraction"] for row in turns) / len(turns)
            ),
            "turns_with_learned_eligible": sum(
                bool(row["retained_learned_ids"] or row["dropped_learned_ids"])
                for row in turns
            ),
            "turns_dropping_learned": sum(
                bool(row["dropped_learned_ids"]) for row in turns
            ),
            "learned_drops": sum(
                len(row["dropped_learned_ids"]) for row in turns
            ),
            "turns_with_protected_issue": sum(
                bool(row["protected_ids"]) for row in turns
            ),
            "ordinary_complete_reconstruction_assignments": sum(
                row["ordinary_complete_reconstruction"] for row in assignments_for_arm
            ),
            "learned_complete_reconstruction_assignments": sum(
                row["learned_complete_reconstruction"] for row in assignments_for_arm
            ),
            "assignment_count": len(assignments_for_arm),
        }
    return {
        "turns": per_turn,
        "assignments": per_assignment,
        "by_arm": by_arm,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--control-study", type=Path, required=True)
    parser.add_argument("--control-audit", type=Path, required=True)
    parser.add_argument("--treatment-study", type=Path, required=True)
    parser.add_argument("--treatment-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in vars(args).values():
        if not path.is_absolute() or path.is_symlink():
            raise RuntimeError("all paths must be absolute and non-symlinked")

    base = _load(BASE_PATH, "dropout_base_analysis")
    cost = _load(COST_PATH, "dropout_cost_analysis")
    control_coverage, control_rows = base.reconstruct(
        args.control_study, args.control_audit, PANEL, expected_holdouts=2
    )
    treatment_coverage, treatment_rows = base.reconstruct(
        args.treatment_study, args.treatment_audit, PANEL, expected_holdouts=2
    )
    if control_coverage["assignment_count"] != 18 or len(control_rows) != 36:
        raise RuntimeError("0% control coverage is not complete")
    if treatment_coverage["assignment_count"] != 36 or len(treatment_rows) != 72:
        raise RuntimeError("30%/50% treatment coverage is not complete")

    rows_by_rate = {
        "0": control_rows,
        "30": [row for row in treatment_rows if _rate(row) == "30"],
        "50": [row for row in treatment_rows if _rate(row) == "50"],
    }
    if any(len(rows) != 36 for rows in rows_by_rate.values()):
        raise RuntimeError("one or more dropout conditions lack 18 complete assignments")

    output = {
        "kind": "provenance-high-proposer-dropout-dev3",
        "uncertainty_note": (
            "SD and SE use nine panel-averaged artifacts per arm. Wilson intervals "
            "over 18 auditor rows are descriptive because two auditors share each "
            "artifact and nine artifacts occupy only three task clusters."
        ),
        "coverage": {
            "dropout_0": control_coverage,
            "dropout_30_50": treatment_coverage,
        },
        "conditions": {},
        "paired_differences": {},
        "cost": {
            "treatment_revision": cost._study_costs(args.treatment_study),
            "treatment_audit": base.semantic_costs(args.treatment_audit),
            "control_audit": base.semantic_costs(args.control_audit),
        },
    }
    for rate, rows in rows_by_rate.items():
        output["conditions"][rate] = {
            arm_name: {
                "outcomes": base.outcome_summary([
                    row for row in rows if base.arm(row) == arm_name
                ]),
                "rh": base.rh_summary([
                    row for row in rows if base.arm(row) == arm_name
                ]),
            }
            for arm_name in ("full", "user")
        }
        output["conditions"][rate]["mechanism"] = base.mechanism_summary(rows)
        if rate != "0":
            output["conditions"][rate]["dropout"] = _dropout_summary(rows, base)

    for left, right in (("30", "0"), ("50", "0"), ("50", "30")):
        comparison = f"{left}_minus_{right}"
        output["paired_differences"][comparison] = {}
        for arm_name in ("full", "user"):
            left_rows = [
                row for row in rows_by_rate[left] if base.arm(row) == arm_name
            ]
            right_rows = [
                row for row in rows_by_rate[right] if base.arm(row) == arm_name
            ]
            left_index = base.index_rows(left_rows)
            right_index = base.index_rows(right_rows)
            if left_index.keys() != right_index.keys():
                raise RuntimeError(f"unpaired comparison: {comparison}/{arm_name}")
            for key in left_index:
                if (
                    left_index[key]["initial_submission_sha256"]
                    != right_index[key]["initial_submission_sha256"]
                ):
                    raise RuntimeError(f"initial artifact mismatch: {comparison}/{key}")
                if (
                    left_index[key]["selected_rubric_sha256"]
                    != right_index[key]["selected_rubric_sha256"]
                ):
                    raise RuntimeError(f"selected rubric mismatch: {comparison}/{key}")
            output["paired_differences"][comparison][arm_name] = base.paired_summary(
                left_rows, right_rows
            )

    write_json_atomic(args.output, output)
    print(json.dumps({
        "output": str(args.output),
        "treatment_revision_cost": output["cost"]["treatment_revision"]["usage_based_usd"],
        "treatment_audit_cost": output["cost"]["treatment_audit"]["usage_based_usd"],
    }), flush=True)


if __name__ == "__main__":
    main()
