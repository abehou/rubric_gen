"""Report matched static versus RTT neutral-heldout sensitivity."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from statistics import fmean

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.rubric_score import RubricScoreStage
from rubric_gen.submission_revision.experiment import load_experiment

from report_neutral_heldout5 import analyze as analyze_rtt
from report_neutral_heldout5 import saved_endpoint
from run_neutral_heldout5 import NEUTRAL_POOL, REPAIRED_CONFIG, neutral_jobs, neutral_scope
from run_neutral_static import AUDIT_ROOT, STATIC_CONFIG, source_targets


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "docs/reports/2026-09-21/trace-v21-complete-public-regression"
MODELS = ("gpt-5.6-sol", "gemini-3.8-flash")


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def static_neutral_scores(targets) -> dict[tuple[str, str], dict[int, float]]:
    summary = read(AUDIT_ROOT / "summary.json")
    if summary.get("status") != "completed" or summary.get(
        "successful_judgments"
    ) != 20:
        raise RuntimeError("matched static neutral-heldout panel is incomplete")
    experiment = neutral_scope(load_experiment(REPAIRED_CONFIG))
    stage = RubricScoreStage(
        EvaluationConfig(
            experiment=experiment,
            study_dir=AUDIT_ROOT.parent / "read-only-static-source-study",
            paraphrase_dir=NEUTRAL_POOL,
            output_dir=AUDIT_ROOT,
            max_concurrency=12,
            resume=True,
        ),
        targets,
    )
    values: dict[tuple[str, str], dict[int, float]] = defaultdict(dict)
    for job in neutral_jobs(stage, targets):
        row = read(AUDIT_ROOT / "records" / f"{job.key}.json")
        role = job.roles[0]
        key = (job.target.assignment_id, job.model)
        values[key][int(role.variant_index)] = float(row["score"])
    if len(values) != 4 or any(
        set(scores) != set(range(5)) for scores in values.values()
    ):
        raise RuntimeError("static neutral scores do not cover two artifacts x two models")
    return dict(values)


def static_rows() -> list[dict[str, object]]:
    experiment = load_experiment(STATIC_CONFIG)
    study = Path(str(experiment.dag["revise"]["output_dir"]))
    sol_audit = Path(str(experiment.dag["detect"]["output_dir"]))
    gemini_audit = (
        Path(
            "/data/user_data/aydanh/rubric_gen/runs/"
            "rtt-result40-expansion-20260918/audit-gemini/new20/da-26-4/static"
        )
        / experiment.experiment_id
    )
    targets = source_targets(experiment, replicate=2)
    neutral = static_neutral_scores(targets)
    rows = []
    for target in targets:
        arm = "User" if target.condition_id.startswith("user-") else "Full"
        for model, audit in ((MODELS[0], sol_audit), (MODELS[1], gemini_audit)):
            old = saved_endpoint(
                study=study,
                audit=audit,
                assignment_id=target.assignment_id,
                model=model,
                target=target,
            )
            h_neutral = fmean(neutral[(target.assignment_id, model)].values())
            rows.append(
                {
                    "arm": arm,
                    "model": model,
                    "assignment_id": target.assignment_id,
                    "S": old["S"],
                    "H_rigorous3": old["H3"],
                    "S_minus_H_rigorous3": old["S"] - old["H3"],
                    "neutral_scores": neutral[(target.assignment_id, model)],
                    "H_neutral5": h_neutral,
                    "S_minus_H_neutral5": old["S"] - h_neutral,
                    "H_change_neutral_minus_rigorous": h_neutral - old["H3"],
                    "W": old["W"],
                    "A": old["A"],
                }
            )
    return rows


def mean_rows(rows, *, arm: str) -> dict[str, float]:
    group = [row for row in rows if row["arm"] == arm]
    if {row["model"] for row in group} != set(MODELS):
        raise RuntimeError(f"incomplete Sol/Gemini rows for {arm}")
    return {
        field: fmean(float(row[field]) for row in group)
        for field in (
            "S",
            "H_rigorous3",
            "S_minus_H_rigorous3",
            "H_neutral5",
            "S_minus_H_neutral5",
            "H_change_neutral_minus_rigorous",
            "W",
            "A",
        )
    }


def analyze() -> dict[str, object]:
    static = static_rows()
    rtt = analyze_rtt()
    comparisons = []
    for arm in ("Full", "User"):
        static_mean = mean_rows(static, arm=arm)
        for version in ("original", "repaired"):
            rtt_mean = next(
                row
                for row in rtt["combined"]
                if row["arm"] == arm and row["version"] == version
            )
            rigorous_contrast = (
                float(rtt_mean["S_minus_H_rigorous3"])
                - static_mean["S_minus_H_rigorous3"]
            )
            neutral_contrast = (
                float(rtt_mean["S_minus_H_neutral5"])
                - static_mean["S_minus_H_neutral5"]
            )
            comparisons.append(
                {
                    "arm": arm,
                    "rtt_version": version,
                    "static": static_mean,
                    "rtt": rtt_mean,
                    "RTT_minus_static_S_minus_H_rigorous3": rigorous_contrast,
                    "RTT_minus_static_S_minus_H_neutral5": neutral_contrast,
                    "contrast_change_neutral_minus_rigorous": (
                        neutral_contrast - rigorous_contrast
                    ),
                }
            )
    return {
        "kind": "neutral-heldout5-da-26-4-rep002-matched-static-report",
        "models": list(MODELS),
        "static_rows": static,
        "rtt_rows": rtt["rows"],
        "comparisons": comparisons,
    }


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# Matched static versus RTT neutral-heldout sensitivity",
        "",
        "All artifacts, trajectories, selected rubrics, S, A, and RH are unchanged. "
        "Only H is recomputed from the same five `uniform_neutral` rubrics.",
        "",
        "| Arm | RTT artifact | Static S-H rigorous | RTT S-H rigorous | RTT-static rigorous | Static S-H neutral | RTT S-H neutral | RTT-static neutral | Contrast change |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["comparisons"]:
        label = (
            "saved Result40 RTT"
            if row["rtt_version"] == "original"
            else "complete-public repair RTT"
        )
        lines.append(
            f"| {row['arm']} | {label} | "
            f"{row['static']['S_minus_H_rigorous3']:.2f} | "
            f"{row['rtt']['S_minus_H_rigorous3']:.2f} | "
            f"{row['RTT_minus_static_S_minus_H_rigorous3']:+.2f} | "
            f"{row['static']['S_minus_H_neutral5']:.2f} | "
            f"{row['rtt']['S_minus_H_neutral5']:.2f} | "
            f"{row['RTT_minus_static_S_minus_H_neutral5']:+.2f} | "
            f"{row['contrast_change_neutral_minus_rigorous']:+.2f} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    report = analyze()
    REPORT.mkdir(parents=True, exist_ok=True)
    write_json_atomic(REPORT / "neutral-heldout5-matched-static.json", report)
    output = markdown(report)
    (REPORT / "neutral-heldout5-matched-static.md").write_text(
        output, encoding="utf-8"
    )
    print(output, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
