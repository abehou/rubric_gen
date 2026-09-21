"""Assemble the complete New20 evidence-calibrated heldout reanalysis."""

from __future__ import annotations

from collections import defaultdict
import json
import math
from pathlib import Path
import statistics

from rubric_gen.artifacts.serialization import write_json_atomic


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs/reports/2026-09-21/trace-v21-complete-public-regression"
CONTROL = REPORT / "neutral-new20.json"
OUTLIER4 = (
    ROOT
    / "diagnostics/heldout-judge-failure-analysis"
    / "evidence-calibrated-panel-outlier4-v2.json"
)
COMPLETIONS = (
    ROOT
    / "diagnostics/heldout-judge-failure-analysis"
    / "new20-remaining16-completions"
)
OUTPUT = REPORT / "evidence-calibrated-new20.json"


def read(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def stats(values: list[float]) -> dict[str, float | int]:
    if not values:
        raise RuntimeError("cannot summarize an empty sample")
    sd = statistics.stdev(values) if len(values) > 1 else 0.0
    return {
        "n": len(values),
        "mean": statistics.mean(values),
        "sample_sd": sd,
        "se": sd / math.sqrt(len(values)),
    }


def main() -> int:
    control = read(CONTROL)
    control_rows = control["rows"]
    if len(control_rows) != 480:
        raise RuntimeError(f"expected 480 control rows, got {len(control_rows)}")

    panels = [read(OUTLIER4)]
    completion_paths = sorted(COMPLETIONS.rglob("completion.json"))
    if len(completion_paths) != 26:
        raise RuntimeError(
            f"expected 26 remaining-task completion receipts, got {len(completion_paths)}"
        )
    panels.extend(read(path) for path in completion_paths)
    for panel in panels:
        if panel.get("status") != "completed":
            raise RuntimeError("incomplete panel receipt")
        if panel.get("policy") != "obligation-neutral-evidence-rigorous-v2":
            raise RuntimeError("panel policy changed")
        if panel.get("source_commit") != "6858016cee19d04c46d4662e9f23e606fc574897":
            raise RuntimeError("panel source commit changed")

    evidence_rows = [row for panel in panels for row in panel["rows"]]
    if len(evidence_rows) != 2400:
        raise RuntimeError(
            f"expected 2,400 evidence judgments, got {len(evidence_rows)}"
        )

    grouped_evidence: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in evidence_rows:
        grouped_evidence[(row["assignment_id"], row["model"])].append(row)
    if len(grouped_evidence) != 480:
        raise RuntimeError(
            f"expected 480 artifact-model groups, got {len(grouped_evidence)}"
        )

    enriched = []
    for row in control_rows:
        key = (row["assignment_id"], row["model"])
        heldouts = grouped_evidence.get(key)
        if heldouts is None:
            raise RuntimeError(f"missing evidence judgments for {key}")
        variants = sorted(item["rubric_variant"] for item in heldouts)
        if variants != [0, 1, 2, 3, 4]:
            raise RuntimeError(f"heldout variants changed for {key}: {variants}")
        h_evidence = statistics.mean(
            float(item["evidence_calibrated_score"]) for item in heldouts
        )
        enriched.append(
            {
                **row,
                "H_evidence5": h_evidence,
                "S_minus_H_evidence5": float(row["S"]) - h_evidence,
                "H_evidence5_minus_A": h_evidence - float(row["A"]),
                "W_minus_S": float(row["W"]) - float(row["S"]),
                "W_minus_A": float(row["W"]) - float(row["A"]),
            }
        )

    aggregate: dict[str, dict] = {}
    model_views = {
        "Sol+Gemini": {"gpt-5.6-sol", "gemini-3.8-flash"},
        "gpt-5.6-sol": {"gpt-5.6-sol"},
        "gemini-3.8-flash": {"gemini-3.8-flash"},
    }
    for view, models in model_views.items():
        aggregate[view] = {}
        for arm in ("Full", "User"):
            aggregate[view][arm] = {}
            for role in ("static", "trace"):
                subset = [
                    row
                    for row in enriched
                    if row["model"] in models
                    and row["arm"] == arm
                    and row["role"] == role
                ]
                aggregate[view][arm][role] = {
                    "W": stats([float(row["W"]) for row in subset]),
                    "S": stats([float(row["S"]) for row in subset]),
                    "H_evidence5": stats(
                        [float(row["H_evidence5"]) for row in subset]
                    ),
                    "A": stats([float(row["A"]) for row in subset]),
                    "W_minus_S": stats(
                        [float(row["W_minus_S"]) for row in subset]
                    ),
                    "S_minus_H_neutral5": stats(
                        [float(row["S_minus_H_neutral5"]) for row in subset]
                    ),
                    "S_minus_H_evidence5": stats(
                        [float(row["S_minus_H_evidence5"]) for row in subset]
                    ),
                    "H_evidence5_minus_A": stats(
                        [float(row["H_evidence5_minus_A"]) for row in subset]
                    ),
                    "W_minus_A": stats(
                        [float(row["W_minus_A"]) for row in subset]
                    ),
                }

            paired = []
            pairing: dict[tuple[str, int, str], dict[str, float]] = defaultdict(dict)
            for row in enriched:
                if row["model"] in models and row["arm"] == arm:
                    key = (row["task_id"], int(row["replicate"]), row["model"])
                    pairing[key][row["role"]] = float(row["S_minus_H_evidence5"])
            for key, values in pairing.items():
                if set(values) != {"static", "trace"}:
                    raise RuntimeError(f"incomplete role pair: {key}")
                paired.append(values["trace"] - values["static"])
            aggregate[view][arm]["trace_minus_static_S_minus_H"] = stats(paired)

    task_points = []
    for arm in ("Full", "User"):
        for task_id in sorted({row["task_id"] for row in enriched}):
            role_means = {}
            for role in ("static", "trace"):
                values = [
                    float(row["S_minus_H_evidence5"])
                    for row in enriched
                    if row["arm"] == arm
                    and row["task_id"] == task_id
                    and row["role"] == role
                ]
                role_means[role] = statistics.mean(values)
            task_points.append(
                {
                    "task_id": task_id,
                    "arm": arm,
                    "static_S_minus_H": role_means["static"],
                    "trace_S_minus_H": role_means["trace"],
                    "trace_minus_static": role_means["trace"] - role_means["static"],
                }
            )

    result = {
        "kind": "evidence-calibrated-five-neutral-heldout-New20-report",
        "policy": "obligation-neutral-evidence-rigorous-v2",
        "source_commit": "6858016cee19d04c46d4662e9f23e606fc574897",
        "coverage": {
            "tasks": len({row["task_id"] for row in enriched}),
            "artifact_model_rows": len(enriched),
            "heldout_judgments": len(evidence_rows),
            "rubric_variants": 5,
            "models": ["gpt-5.6-sol", "gemini-3.8-flash"],
        },
        "invariants": {
            "revision_rerun": False,
            "artifact_changed": False,
            "selected_score_changed": False,
            "holistic_score_changed": False,
            "reward_hacking_changed": False,
        },
        "aggregate": aggregate,
        "task_points": task_points,
        "rows": enriched,
    }
    write_json_atomic(OUTPUT, result)

    for arm in ("Full", "User"):
        print(arm)
        for role in ("static", "trace"):
            values = aggregate["Sol+Gemini"][arm][role]
            print(
                role,
                f"W-S={values['W_minus_S']['mean']:.2f}",
                f"S-H={values['S_minus_H_evidence5']['mean']:.2f}",
                f"H-A={values['H_evidence5_minus_A']['mean']:.2f}",
                f"W-A={values['W_minus_A']['mean']:.2f}",
            )
        contrast = aggregate["Sol+Gemini"][arm]["trace_minus_static_S_minus_H"]
        print(
            "trace-static S-H",
            f"{contrast['mean']:+.2f} ± {contrast['sample_sd']:.2f}",
            f"(SE {contrast['se']:.2f}, n={contrast['n']})",
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
