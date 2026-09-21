"""Report the matched four-task neutral-heldout outlier panel."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from statistics import fmean

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.rubric_score import RubricScoreStage
from rubric_gen.submission_revision.experiment import load_experiment

from report_neutral_heldout5 import saved_endpoint
from run_neutral_heldout5 import neutral_jobs, neutral_scope, source_targets
from run_neutral_outlier_panel import EXISTING_DA264_POOL, RUN, TASKS, configs


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs/reports/2026-09-21/trace-v21-complete-public-regression"
MODELS = ("gpt-5.6-sol", "gemini-3.8-flash")
EXISTING_DA264_TRACE = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-complete-public-regression-20260921/neutral-heldout5/rubric-score"
)
EXISTING_DA264_STATIC = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-complete-public-regression-20260921/neutral-heldout5-static/rubric-score"
)


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def pool_for(task_id: str) -> Path:
    return (
        EXISTING_DA264_POOL
        if task_id == "da-26-4"
        else RUN / "paraphrases" / task_id
    )


def panel_root(task_id: str, role: str, replicate: int) -> Path:
    if task_id == "da-26-4" and replicate == 2:
        return EXISTING_DA264_TRACE if role == "trace" else EXISTING_DA264_STATIC
    return RUN / "rubric-score" / task_id / role


def neutral_values(task_id: str, role: str, experiment, targets):
    pool = pool_for(task_id)
    neutral = neutral_scope(
        load_experiment(configs(task_id)[1]),
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
    for job in neutral_jobs(stage, targets, paraphrase_dir=pool):
        root = panel_root(task_id, role, job.target.replicate)
        record = read(root / "records" / f"{job.key}.json")
        values[(job.target.assignment_id, job.model)][
            int(job.roles[0].variant_index)
        ] = float(record["score"])
    expected = len(targets) * len(MODELS)
    if len(values) != expected or any(
        set(scores) != set(range(5)) for scores in values.values()
    ):
        raise RuntimeError(f"incomplete neutral panel: {task_id} {role}")
    return dict(values)


def saved_audit_root(task_id: str, role: str, experiment, model: str) -> Path:
    if model == "gpt-5.6-sol":
        return Path(str(experiment.dag["detect"]["output_dir"]))
    return (
        Path(
            "/data/user_data/aydanh/rubric_gen/runs/"
            f"rtt-result40-expansion-20260918/audit-gemini/new20/{task_id}/{role}"
        )
        / experiment.experiment_id
    )


def collect_rows() -> list[dict[str, object]]:
    rows = []
    for task_id in TASKS:
        for role, config_path in zip(("static", "trace"), configs(task_id), strict=True):
            experiment = load_experiment(config_path)
            targets = source_targets(experiment)
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
                            "H_neutral5": h_neutral,
                            "S_minus_H_neutral5": old["S"] - h_neutral,
                            "H_change_neutral_minus_rigorous": h_neutral - old["H3"],
                            "W": old["W"],
                            "A": old["A"],
                        }
                    )
    if len(rows) != len(TASKS) * 2 * 2 * 3 * len(MODELS):
        raise RuntimeError(f"unexpected report row count: {len(rows)}")
    return rows


def metric_mean(rows, field: str) -> float:
    return fmean(float(row[field]) for row in rows)


def contrasts(rows, *, tasks: tuple[str, ...]) -> list[dict[str, object]]:
    result = []
    for task_id in tasks:
        for arm in ("Full", "User"):
            by_role = {
                role: [
                    row
                    for row in rows
                    if row["task_id"] == task_id
                    and row["arm"] == arm
                    and row["role"] == role
                ]
                for role in ("static", "trace")
            }
            if any(len(group) != 6 for group in by_role.values()):
                raise RuntimeError(f"incomplete task contrast: {task_id} {arm}")
            rigorous = {
                role: metric_mean(group, "S_minus_H_rigorous3")
                for role, group in by_role.items()
            }
            neutral = {
                role: metric_mean(group, "S_minus_H_neutral5")
                for role, group in by_role.items()
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
                    "static_S_minus_H_neutral5": neutral["static"],
                    "trace_S_minus_H_neutral5": neutral["trace"],
                    "RTT_minus_static_neutral5": neutral_contrast,
                    "contrast_change_neutral_minus_rigorous": (
                        neutral_contrast - rigorous_contrast
                    ),
                }
            )
    return result


def analyze() -> dict[str, object]:
    rows = collect_rows()
    task_contrasts = contrasts(rows, tasks=TASKS)
    aggregate = []
    for arm in ("Full", "User"):
        arm_rows = [row for row in rows if row["arm"] == arm]
        by_role = {
            role: [row for row in arm_rows if row["role"] == role]
            for role in ("static", "trace")
        }
        rigorous = {
            role: metric_mean(group, "S_minus_H_rigorous3")
            for role, group in by_role.items()
        }
        neutral = {
            role: metric_mean(group, "S_minus_H_neutral5")
            for role, group in by_role.items()
        }
        rigorous_contrast = rigorous["trace"] - rigorous["static"]
        neutral_contrast = neutral["trace"] - neutral["static"]
        aggregate.append(
            {
                "arm": arm,
                "n_auditor_rows_per_condition": len(by_role["trace"]),
                "static_S_minus_H_rigorous3": rigorous["static"],
                "trace_S_minus_H_rigorous3": rigorous["trace"],
                "RTT_minus_static_rigorous3": rigorous_contrast,
                "static_S_minus_H_neutral5": neutral["static"],
                "trace_S_minus_H_neutral5": neutral["trace"],
                "RTT_minus_static_neutral5": neutral_contrast,
                "contrast_change_neutral_minus_rigorous": (
                    neutral_contrast - rigorous_contrast
                ),
            }
        )
    shifts = [float(row["H_change_neutral_minus_rigorous"]) for row in rows]
    return {
        "kind": "neutral-heldout5-four-outlier-task-report",
        "tasks": list(TASKS),
        "models": list(MODELS),
        "rows": rows,
        "task_contrasts": task_contrasts,
        "aggregate": aggregate,
        "sensitivity": {
            "auditor_rows": len(rows),
            "H_increased": sum(value > 0 for value in shifts),
            "H_decreased": sum(value < 0 for value in shifts),
            "H_unchanged": sum(value == 0 for value in shifts),
            "mean_H_change": fmean(shifts),
        },
    }


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# Four-task neutral-heldout outlier panel",
        "",
        "This is a saved-artifact Sol+Gemini diagnostic. No artifact, trajectory, "
        "selected score, A, or RH value changed.",
        "",
        "## Aggregate across four tasks",
        "",
        "| Arm | Static S-H rigorous | RTT S-H rigorous | RTT-static rigorous | Static S-H neutral | RTT S-H neutral | RTT-static neutral | Contrast change |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["aggregate"]:
        lines.append(
            f"| {row['arm']} | {row['static_S_minus_H_rigorous3']:.2f} | "
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
            "## Task-level contrasts",
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
    write_json_atomic(REPORT / "neutral-outlier-panel.json", report)
    output = markdown(report)
    (REPORT / "neutral-outlier-panel.md").write_text(output, encoding="utf-8")
    print(output, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
