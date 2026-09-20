"""Report rigorous-3 versus neutral-5 heldout scores for four saved artifacts."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from statistics import fmean

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.rubric_score import RubricScoreStage
from rubric_gen.submission_revision.experiment import load_experiment

from report_heldout5 import _assignment_ids, _audit_roots, endpoint
from run_neutral_heldout5 import (
    AUDIT_ROOT,
    NEUTRAL_POOL,
    ORIGINAL_CONFIG,
    REPAIRED_CONFIG,
    load_four_source_targets,
    neutral_jobs,
    neutral_scope,
)


ROOT = Path(__file__).resolve().parents[2]
BASE_RUN = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-complete-public-regression-20260921"
)
NEUTRAL_RUN = BASE_RUN / "neutral-heldout5"
REPORT = ROOT / "docs/reports/2026-09-21/trace-v21-complete-public-regression"
MODELS = ("gpt-5.6-sol", "gemini-3.8-flash")


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def neutral_scores() -> dict[tuple[str, str], dict[int, float]]:
    summary = read(NEUTRAL_RUN / "rubric-score/summary.json")
    if summary.get("status") != "completed" or summary.get(
        "successful_judgments"
    ) != 40:
        raise RuntimeError("neutral-heldout score panel is incomplete")
    original = load_experiment(ORIGINAL_CONFIG)
    repaired = load_experiment(REPAIRED_CONFIG)
    experiment = neutral_scope(repaired)
    targets = load_four_source_targets(original, repaired)
    stage = RubricScoreStage(
        EvaluationConfig(
            experiment=experiment,
            study_dir=NEUTRAL_RUN / "four-read-only-source-studies",
            paraphrase_dir=NEUTRAL_POOL,
            output_dir=AUDIT_ROOT,
            max_concurrency=12,
            resume=True,
        ),
        targets,
    )
    jobs = neutral_jobs(stage, targets)
    values: dict[tuple[str, str], dict[int, float]] = defaultdict(dict)
    for job in jobs:
        row = read(AUDIT_ROOT / "records" / f"{job.key}.json")
        role = job.roles[0]
        if role.name != "holdout" or role.variant_index is None:
            raise RuntimeError("neutral score has a non-heldout role")
        variant = int(role.variant_index)
        key = (job.target.assignment_id, job.model)
        if variant in values[key]:
            raise RuntimeError(f"duplicate neutral score: {key} {variant}")
        values[key][variant] = float(row["score"])
    if len(values) != 8 or any(set(scores) != set(range(5)) for scores in values.values()):
        raise RuntimeError("neutral scores do not cover four artifacts x two models")
    return dict(values)


def analyze() -> dict[str, object]:
    roots = _audit_roots()
    assignment_ids = _assignment_ids()
    neutral = neutral_scores()
    rows: list[dict[str, object]] = []
    for version in ("original", "repaired"):
        for arm in ("Full", "User"):
            assignment_id = assignment_ids[version][arm]
            for model in MODELS:
                old = endpoint(
                    study=roots[version]["study"],
                    audit=roots[version][model],
                    assignment_id=assignment_id,
                    model=model,
                )
                scores = neutral[(assignment_id, model)]
                h_neutral = fmean(scores.values())
                rows.append({
                    "version": version,
                    "arm": arm,
                    "model": model,
                    "assignment_id": assignment_id,
                    "S": old["S"],
                    "H_rigorous3": old["H3"],
                    "S_minus_H_rigorous3": float(old["S"]) - float(old["H3"]),
                    "neutral_scores": scores,
                    "H_neutral5": h_neutral,
                    "S_minus_H_neutral5": float(old["S"]) - h_neutral,
                    "H_change_neutral_minus_rigorous": h_neutral - float(old["H3"]),
                    "W": old["W"],
                    "A": old["A"],
                    "RH": old["RH"],
                })

    combined = []
    for version in ("original", "repaired"):
        for arm in ("Full", "User"):
            group = [
                row for row in rows
                if row["version"] == version and row["arm"] == arm
            ]
            combined.append({
                "version": version,
                "arm": arm,
                "models": list(MODELS),
                **{
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
                },
            })
    return {
        "kind": "neutral-heldout5-da-26-4-rep002-report",
        "rows": rows,
        "combined": combined,
    }


def markdown(report: dict[str, object]) -> str:
    lines = [
        "# Neutral heldout policy sensitivity",
        "",
        "All trajectories, final artifacts, selected rubrics, S, A, and RH are reused.",
        "Only H is recomputed using five fresh `uniform_neutral` heldouts.",
        "",
        "## Sol + Gemini equal-weight mean",
        "",
        "| Arm | Artifact | S | H rigorous-3 | S-H rigorous-3 | H neutral-5 | S-H neutral-5 | H change |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in report["combined"]:
        label = "saved Result40" if row["version"] == "original" else "complete-public repair"
        lines.append(
            f"| {row['arm']} | {label} | {row['S']:.2f} | "
            f"{row['H_rigorous3']:.2f} | {row['S_minus_H_rigorous3']:.2f} | "
            f"{row['H_neutral5']:.2f} | {row['S_minus_H_neutral5']:.2f} | "
            f"{row['H_change_neutral_minus_rigorous']:+.2f} |"
        )
    lines.extend([
        "",
        "## Per-model paired values",
        "",
        "| Model | Arm | Artifact | S | H rigorous-3 | S-H rigorous-3 | H neutral-5 | S-H neutral-5 | H change |",
        "| --- | --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    for row in report["rows"]:
        label = "saved Result40" if row["version"] == "original" else "complete-public repair"
        lines.append(
            f"| {row['model']} | {row['arm']} | {label} | {row['S']:.2f} | "
            f"{row['H_rigorous3']:.2f} | {row['S_minus_H_rigorous3']:.2f} | "
            f"{row['H_neutral5']:.2f} | {row['S_minus_H_neutral5']:.2f} | "
            f"{row['H_change_neutral_minus_rigorous']:+.2f} |"
        )
    return "\n".join(lines) + "\n"


def main() -> int:
    report = analyze()
    REPORT.mkdir(parents=True, exist_ok=True)
    write_json_atomic(REPORT / "neutral-heldout5.json", report)
    output = markdown(report)
    (REPORT / "neutral-heldout5.md").write_text(output, encoding="utf-8")
    print(output, flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
