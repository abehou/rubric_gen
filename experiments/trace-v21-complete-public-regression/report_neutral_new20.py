"""Compare rigorous-3 and uniform-neutral-5 heldouts across saved New20 artifacts."""

from __future__ import annotations

from collections import defaultdict
import json
import math
from pathlib import Path
from statistics import fmean, stdev

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.rubric_score import RubricScoreStage
from rubric_gen.submission_revision.experiment import load_experiment

from report_neutral_heldout5 import saved_endpoint
from report_neutral_outlier_panel import neutral_values as outlier_neutral_values
from run_neutral_heldout5 import neutral_jobs, neutral_scope, source_targets
from run_neutral_new20 import COMPLETED_TASKS, NEW20_TASKS, RESULT40, RUN


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs/reports/2026-09-21/trace-v21-complete-public-regression"
MODELS = ("gpt-5.6-sol", "gemini-3.8-flash")
GEMINI_ROOT = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-result40-expansion-20260918/audit-gemini/new20"
)


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def config(task_id: str, role: str) -> Path:
    return RESULT40 / f"configs/{task_id}-{role}.yaml"


def new_neutral_values(task_id: str, role: str, experiment, targets):
    pool = RUN / "paraphrases" / task_id
    neutral = neutral_scope(
        load_experiment(config(task_id, "trace")),
        output_dir=pool,
    )
    stage = RubricScoreStage(
        EvaluationConfig(
            experiment=neutral,
            study_dir=RUN / "report-read-only-source-studies" / task_id / role,
            paraphrase_dir=pool,
            output_dir=RUN / "report-read-only-audit" / task_id / role,
            max_concurrency=12,
            resume=True,
        ),
        targets,
    )
    values: dict[tuple[str, str], dict[int, float]] = defaultdict(dict)
    audit_root = RUN / "rubric-score" / task_id / role
    for job in neutral_jobs(stage, targets, paraphrase_dir=pool):
        record = read(audit_root / "records" / f"{job.key}.json")
        values[(job.target.assignment_id, job.model)][
            int(job.roles[0].variant_index)
        ] = float(record["score"])
    expected = len(targets) * len(MODELS)
    if len(values) != expected or any(
        set(scores) != set(range(5)) for scores in values.values()
    ):
        raise RuntimeError(f"incomplete neutral panel: {task_id} {role}")
    return dict(values)


def neutral_values(task_id: str, role: str, experiment, targets):
    if task_id in COMPLETED_TASKS:
        return outlier_neutral_values(task_id, role, experiment, targets)
    return new_neutral_values(task_id, role, experiment, targets)


def saved_audit_root(task_id: str, role: str, experiment, model: str) -> Path:
    if model == "gpt-5.6-sol":
        return Path(str(experiment.dag["detect"]["output_dir"]))
    return GEMINI_ROOT / task_id / role / experiment.experiment_id


def collect_rows() -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for task_id in NEW20_TASKS:
        for role in ("static", "trace"):
            experiment = load_experiment(config(task_id, role))
            targets = source_targets(experiment)
            if len(targets) != 6:
                raise RuntimeError(f"{task_id} {role}: expected six saved targets")
            neutral = neutral_values(task_id, role, experiment, targets)
            study = Path(str(experiment.dag["revise"]["output_dir"]))
            for target in targets:
                arm = "User" if target.condition_id.startswith("user-") else "Full"
                for model in MODELS:
                    old = saved_endpoint(
                        study=study,
                        audit=saved_audit_root(task_id, role, experiment, model),
                        assignment_id=target.assignment_id,
                        model=model,
                        target=target,
                    )
                    scores = neutral[(target.assignment_id, model)]
                    h_neutral3 = fmean(scores[index] for index in range(3))
                    h_neutral = fmean(scores.values())
                    rows.append(
                        {
                            "task_id": task_id,
                            "role": role,
                            "arm": arm,
                            "replicate": target.replicate,
                            "model": model,
                            "assignment_id": target.assignment_id,
                            "S": old["S"],
                            "H_rigorous3": old["H3"],
                            "S_minus_H_rigorous3": old["S"] - old["H3"],
                            "neutral_scores": scores,
                            "H_neutral3": h_neutral3,
                            "S_minus_H_neutral3": old["S"] - h_neutral3,
                            "H_neutral5": h_neutral,
                            "S_minus_H_neutral5": old["S"] - h_neutral,
                            "H_change_neutral_minus_rigorous": h_neutral - old["H3"],
                            "W": old["W"],
                            "A": old["A"],
                        }
                    )
    expected = len(NEW20_TASKS) * 2 * 2 * 3 * len(MODELS)
    if len(rows) != expected:
        raise RuntimeError(f"expected {expected} report rows, found {len(rows)}")
    return rows


def mean(rows, field: str) -> float:
    return fmean(float(row[field]) for row in rows)


def task_contrasts(rows: list[dict[str, object]]) -> list[dict[str, object]]:
    result: list[dict[str, object]] = []
    for task_id in NEW20_TASKS:
        for arm in ("Full", "User"):
            groups = {
                role: [
                    row
                    for row in rows
                    if row["task_id"] == task_id
                    and row["arm"] == arm
                    and row["role"] == role
                ]
                for role in ("static", "trace")
            }
            if any(len(group) != 6 for group in groups.values()):
                raise RuntimeError(f"incomplete task contrast: {task_id} {arm}")
            rigorous = {
                role: mean(group, "S_minus_H_rigorous3")
                for role, group in groups.items()
            }
            neutral = {
                role: mean(group, "S_minus_H_neutral5")
                for role, group in groups.items()
            }
            neutral3 = {
                role: mean(group, "S_minus_H_neutral3")
                for role, group in groups.items()
            }
            rigorous_contrast = rigorous["trace"] - rigorous["static"]
            neutral_contrast = neutral["trace"] - neutral["static"]
            result.append(
                {
                    "task_id": task_id,
                    "arm": arm,
                    "static_S_minus_H_rigorous3": rigorous["static"],
                    "trace_S_minus_H_rigorous3": rigorous["trace"],
                    "RTT_minus_static_rigorous3": rigorous_contrast,
                    "static_S_minus_H_neutral3": neutral3["static"],
                    "trace_S_minus_H_neutral3": neutral3["trace"],
                    "RTT_minus_static_neutral3": (
                        neutral3["trace"] - neutral3["static"]
                    ),
                    "static_S_minus_H_neutral5": neutral["static"],
                    "trace_S_minus_H_neutral5": neutral["trace"],
                    "RTT_minus_static_neutral5": neutral_contrast,
                    "contrast_change_neutral_minus_rigorous": (
                        neutral_contrast - rigorous_contrast
                    ),
                }
            )
    return result


def uncertainty(values: list[float]) -> dict[str, float | int]:
    sd = stdev(values)
    return {
        "n_tasks": len(values),
        "mean": fmean(values),
        "sample_sd": sd,
        "se": sd / math.sqrt(len(values)),
    }


def analyze() -> dict[str, object]:
    rows = collect_rows()
    contrasts = task_contrasts(rows)
    aggregate: list[dict[str, object]] = []
    for model in (*MODELS, "combined"):
        for arm in ("Full", "User"):
            selected = [
                row
                for row in rows
                if row["arm"] == arm
                and (model == "combined" or row["model"] == model)
            ]
            groups = {
                role: [row for row in selected if row["role"] == role]
                for role in ("static", "trace")
            }
            rigorous = {
                role: mean(group, "S_minus_H_rigorous3")
                for role, group in groups.items()
            }
            neutral = {
                role: mean(group, "S_minus_H_neutral5")
                for role, group in groups.items()
            }
            neutral3 = {
                role: mean(group, "S_minus_H_neutral3")
                for role, group in groups.items()
            }
            aggregate.append(
                {
                    "model": model,
                    "arm": arm,
                    "n_auditor_rows_per_condition": len(groups["trace"]),
                    "static_S_minus_H_rigorous3": rigorous["static"],
                    "trace_S_minus_H_rigorous3": rigorous["trace"],
                    "RTT_minus_static_rigorous3": (
                        rigorous["trace"] - rigorous["static"]
                    ),
                    "static_S_minus_H_neutral3": neutral3["static"],
                    "trace_S_minus_H_neutral3": neutral3["trace"],
                    "RTT_minus_static_neutral3": (
                        neutral3["trace"] - neutral3["static"]
                    ),
                    "static_S_minus_H_neutral5": neutral["static"],
                    "trace_S_minus_H_neutral5": neutral["trace"],
                    "RTT_minus_static_neutral5": (
                        neutral["trace"] - neutral["static"]
                    ),
                    "trace_S_minus_H_change": (
                        neutral["trace"] - rigorous["trace"]
                    ),
                    "trace_count_effect_neutral5_minus_neutral3": (
                        neutral["trace"] - neutral3["trace"]
                    ),
                    "contrast_count_effect_neutral5_minus_neutral3": (
                        neutral["trace"]
                        - neutral["static"]
                        - neutral3["trace"]
                        + neutral3["static"]
                    ),
                    "contrast_change_neutral_minus_rigorous": (
                        neutral["trace"]
                        - neutral["static"]
                        - rigorous["trace"]
                        + rigorous["static"]
                    ),
                }
            )
    paired_uncertainty = {}
    for arm in ("Full", "User"):
        arm_rows = [row for row in contrasts if row["arm"] == arm]
        paired_uncertainty[arm] = {
            "rigorous_RTT_minus_static": uncertainty(
                [float(row["RTT_minus_static_rigorous3"]) for row in arm_rows]
            ),
            "neutral_RTT_minus_static": uncertainty(
                [float(row["RTT_minus_static_neutral5"]) for row in arm_rows]
            ),
            "paired_change": uncertainty(
                [
                    float(row["contrast_change_neutral_minus_rigorous"])
                    for row in arm_rows
                ]
            ),
        }
    shifts = [float(row["H_change_neutral_minus_rigorous"]) for row in rows]
    return {
        "kind": "uniform-neutral-heldout5-New20-report",
        "tasks": list(NEW20_TASKS),
        "models": list(MODELS),
        "rows": rows,
        "task_contrasts": contrasts,
        "aggregate": aggregate,
        "paired_task_uncertainty": paired_uncertainty,
        "sensitivity": {
            "auditor_rows": len(rows),
            "H_increased": sum(value > 0 for value in shifts),
            "H_decreased": sum(value < 0 for value in shifts),
            "H_unchanged": sum(value == 0 for value in shifts),
            "mean_H_change": fmean(shifts),
        },
        "invariants": {
            "revisions_rerun": False,
            "S_unchanged": True,
            "A_unchanged": True,
            "RH_unchanged": True,
        },
    }


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# New20 uniform-neutral heldout comparison",
        "",
        "This is a measurement-only comparison over saved final artifacts. No revision, "
        "selected score (S), holistic score (A), or RH judgment changed. Historical H "
        "uses three rigorous heldouts; corrected H uses five `uniform_neutral` heldouts.",
        "",
        "## Sol + Gemini mean",
        "",
        "| Arm | Static S-H rigorous | RTT S-H rigorous | RTT-static rigorous | Static S-H neutral | RTT S-H neutral | RTT-static neutral | RTT S-H change | Contrast change |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    combined = [row for row in report["aggregate"] if row["model"] == "combined"]
    for row in combined:
        lines.append(
            f"| {row['arm']} | {row['static_S_minus_H_rigorous3']:.2f} | "
            f"{row['trace_S_minus_H_rigorous3']:.2f} | "
            f"{row['RTT_minus_static_rigorous3']:+.2f} | "
            f"{row['static_S_minus_H_neutral5']:.2f} | "
            f"{row['trace_S_minus_H_neutral5']:.2f} | "
            f"{row['RTT_minus_static_neutral5']:+.2f} | "
            f"{row['trace_S_minus_H_change']:+.2f} | "
            f"{row['contrast_change_neutral_minus_rigorous']:+.2f} |"
        )
    lines.extend(
        [
            "",
            "## Neutral prompt: three versus five heldouts",
            "",
            "This isolates the effect of averaging two additional neutral paraphrases; "
            "both columns already use the corrected neutral prompt policy.",
            "",
            "| Arm | RTT S-H neutral-3 | RTT S-H neutral-5 | Count effect | RTT-static neutral-3 | RTT-static neutral-5 | Contrast count effect |",
            "| --- | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in combined:
        lines.append(
            f"| {row['arm']} | {row['trace_S_minus_H_neutral3']:.2f} | "
            f"{row['trace_S_minus_H_neutral5']:.2f} | "
            f"{row['trace_count_effect_neutral5_minus_neutral3']:+.2f} | "
            f"{row['RTT_minus_static_neutral3']:+.2f} | "
            f"{row['RTT_minus_static_neutral5']:+.2f} | "
            f"{row['contrast_count_effect_neutral5_minus_neutral3']:+.2f} |"
        )
    lines.extend(
        [
            "",
            "## Task-level uncertainty",
            "",
            "SD and SE use the 20 matched task-level RTT-minus-static contrasts; "
            "the three replicates and two models are averaged within each task.",
            "",
            "| Arm | Rigorous contrast mean ± SD (SE) | Neutral contrast mean ± SD (SE) | Paired change mean ± SD (SE) |",
            "| --- | ---: | ---: | ---: |",
        ]
    )
    for arm in ("Full", "User"):
        uncertainty_rows = report["paired_task_uncertainty"][arm]
        rigorous = uncertainty_rows["rigorous_RTT_minus_static"]
        neutral = uncertainty_rows["neutral_RTT_minus_static"]
        change = uncertainty_rows["paired_change"]
        lines.append(
            f"| {arm} | {rigorous['mean']:+.2f} ± {rigorous['sample_sd']:.2f} "
            f"({rigorous['se']:.2f}) | {neutral['mean']:+.2f} ± "
            f"{neutral['sample_sd']:.2f} ({neutral['se']:.2f}) | "
            f"{change['mean']:+.2f} ± {change['sample_sd']:.2f} "
            f"({change['se']:.2f}) |"
        )
    lines.extend(
        [
            "",
            "## Per model",
            "",
            "| Model | Arm | Static rigorous | RTT rigorous | RTT-static rigorous | Static neutral | RTT neutral | RTT-static neutral | Contrast change |",
            "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
        ]
    )
    for row in report["aggregate"]:
        if row["model"] == "combined":
            continue
        lines.append(
            f"| {row['model']} | {row['arm']} | "
            f"{row['static_S_minus_H_rigorous3']:.2f} | "
            f"{row['trace_S_minus_H_rigorous3']:.2f} | "
            f"{row['RTT_minus_static_rigorous3']:+.2f} | "
            f"{row['static_S_minus_H_neutral5']:.2f} | "
            f"{row['trace_S_minus_H_neutral5']:.2f} | "
            f"{row['RTT_minus_static_neutral5']:+.2f} | "
            f"{row['contrast_change_neutral_minus_rigorous']:+.2f} |"
        )
    lines.extend(
        [
            "",
            "## Task-level matched contrasts",
            "",
            "| Task | Arm | RTT-static rigorous | RTT-static neutral | Change |",
            "| --- | --- | ---: | ---: | ---: |",
        ]
    )
    for row in report["task_contrasts"]:
        lines.append(
            f"| {row['task_id']} | {row['arm']} | "
            f"{row['RTT_minus_static_rigorous3']:+.2f} | "
            f"{row['RTT_minus_static_neutral5']:+.2f} | "
            f"{row['contrast_change_neutral_minus_rigorous']:+.2f} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    report = analyze()
    REPORT.mkdir(parents=True, exist_ok=True)
    write_json_atomic(REPORT / "neutral-new20.json", report)
    output = markdown(report)
    (REPORT / "neutral-new20.md").write_text(output, encoding="utf-8")
    print(output, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
