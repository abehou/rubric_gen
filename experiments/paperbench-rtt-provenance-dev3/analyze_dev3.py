"""Extract and compare complete single-auditor PaperBench Dev3 outcomes.

This is a read-only report adapter.  It never publishes evaluation summaries or
makes provider requests.  A model is accepted only when all rubric, absolute,
and direct-window evidence required for every assignment is present.
"""

from __future__ import annotations

import argparse
from collections import Counter
import json
import math
from pathlib import Path
from statistics import fmean, stdev
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from rubric_gen.artifacts.serialization import write_json_atomic  # noqa: E402
from rubric_gen.submission_revision.evaluation import rubric_score  # noqa: E402
from rubric_gen.submission_revision.evaluation.jobs import (  # noqa: E402
    EvaluationConfig,
)
from rubric_gen.submission_revision.evaluation.rubric_score import (  # noqa: E402
    RubricScoreStage,
    _rubric_score_job_identity,
)
from rubric_gen.submission_revision.evaluation.runner import (  # noqa: E402
    _summarize_rubric_scores,
)
from rubric_gen.submission_revision.evaluation.targets import (  # noqa: E402
    load_evaluation_targets,
)
from rubric_gen.submission_revision.experiment import load_experiment  # noqa: E402
from rubric_gen.submission_revision.source_resolution import (  # noqa: E402
    resolve_study_sources,
)
from rubric_gen.submission_revision.store import same_scoring_semantics  # noqa: E402


WINDOWS = (
    "full_trajectory",
    "post_update",
    "final_artifact",
    "final_revision",
)
VALUE_KEYS = ("W", "W_train", "S", "H", "A", "WS", "SH", "HA", "WA")


def read(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def arm(condition_id: str) -> str:
    if condition_id.startswith("full"):
        return "full"
    if condition_id.startswith("user-simulator"):
        return "user"
    raise RuntimeError(f"unexpected PaperBench Dev3 condition: {condition_id}")


def stats(values: list[float]) -> dict[str, float | int]:
    if not values:
        raise RuntimeError("cannot summarize an empty value list")
    sample_sd = stdev(values) if len(values) > 1 else 0.0
    return {
        "n": len(values),
        "mean": fmean(values),
        "sample_sd": sample_sd,
        "se": sample_sd / math.sqrt(len(values)),
    }


def _rubric_assignments(
    study: Path,
    audit: Path,
    model: str,
) -> tuple[list[dict], dict[str, object]]:
    summary_path = audit / "rubric_score" / "summary.json"
    if summary_path.is_file():
        summary = read(summary_path)
        assert isinstance(summary, dict)
        assignments = summary.get("assignments")
        if isinstance(assignments, list) and assignments:
            for assignment in assignments:
                for artifact in ("initial", "final"):
                    selected = assignment["reference_scores"]["selected"][artifact]
                    if model not in selected["scores"]:
                        raise RuntimeError(
                            f"rubric summary does not contain complete {model} scores"
                        )
            model_records = [
                record
                for record in summary["records"]
                if record["model"] == model
            ]
            return assignments, {
                "source": "native-complete-summary",
                "assignment_references": len(model_records),
                "semantic_records": len({
                    record["judgment_key"] for record in model_records
                }),
            }

    ledger = read(study / "study.json")
    assert isinstance(ledger, dict)
    experiment_path = Path(str(ledger["experiment_path"]))
    experiment = load_experiment(experiment_path)
    config = EvaluationConfig(
        experiment=experiment,
        study_dir=study,
        paraphrase_dir=Path(str(ledger["paraphrase_run_dir"])),
        output_dir=audit / "rubric_score",
        max_concurrency=4,
        resume=True,
    )
    sources = resolve_study_sources(study, experiment)
    targets = load_evaluation_targets(config, sources)
    stage = RubricScoreStage(config, targets)
    jobs = tuple(job for job in stage._jobs(targets) if job.model == model)
    if not jobs:
        raise RuntimeError(f"no rubric jobs were planned for {model}")

    records = []
    semantic_keys = set()
    for job in jobs:
        path = audit / "rubric_score" / "records" / f"{job.key}.json"
        if not path.is_file():
            raise RuntimeError(f"missing {model} rubric record: {job.key}")
        raw = read(path)
        assert isinstance(raw, dict)
        identity = _rubric_score_job_identity(job)
        for field in (
            "model",
            "task_id",
            "submission_content_sha256",
            "rubric_sha256",
            "review_input_sha256",
            "answer_input_sha256",
        ):
            if raw.get(field) != identity[field]:
                raise RuntimeError(f"rubric record identity mismatch: {job.key} {field}")
        if not same_scoring_semantics(raw["grading_identity"], identity["grading_identity"]):
            raise RuntimeError(f"rubric scoring semantics mismatch: {job.key}")
        score = raw.get("score")
        if not isinstance(score, (int, float)) or isinstance(score, bool):
            raise RuntimeError(f"rubric record has invalid score: {job.key}")
        records.append(
            {
                **identity,
                "judgment_key": job.key,
                "score": float(score),
                "attempt_id": raw["attempt_id"],
                "validation_path": raw["validation_path"],
                "evaluation_path": raw["evaluation_path"],
            }
        )
        semantic_keys.add(job.key)
    assignments = _summarize_rubric_scores(targets, records, (model,))
    return assignments, {
        "source": "read-only-complete-model-reconstruction",
        "assignment_references": len(records),
        "semantic_records": len(semantic_keys),
    }


def _absolute_records(audit: Path, model: str) -> dict[tuple[str, str], dict]:
    summary = read(audit / "absolute_score" / "summary.json")
    assert isinstance(summary, dict)
    records = {}
    for record in summary["records"]:
        if record["model"] != model:
            continue
        key = (record["assignment_id"], record["artifact"])
        if key in records:
            raise RuntimeError(f"duplicate absolute-score reference: {key}")
        raw_path = audit / "absolute_score" / "records" / f'{record["judgment_key"]}.json'
        raw = read(raw_path)
        assert isinstance(raw, dict)
        if (
            raw.get("model") != model
            or raw.get("verdict") != record.get("verdict")
            or raw.get("submission_content_sha256")
            != record.get("submission_content_sha256")
        ):
            raise RuntimeError(f"absolute-score evidence mismatch: {key}")
        records[key] = record
    return records


def _direct_records(
    study: Path,
    audit: Path,
    model: str,
    assignment_by_source: dict[str, str],
) -> dict[str, dict[str, dict]]:
    result: dict[str, dict[str, dict]] = {}
    for window in WINDOWS:
        paths = list((audit / f"direct_{window}" / "evaluations").glob("*/summary.json"))
        if len(paths) != 1:
            raise RuntimeError(f"missing or ambiguous direct summary: {window}")
        summary_path = paths[0]
        summary = read(summary_path)
        assert isinstance(summary, dict)
        records = {}
        for record in summary["records"]:
            if record["model"] != model:
                continue
            if record["status"] not in {"completed", "skipped"}:
                raise RuntimeError(
                    f"incomplete {model} direct record: {window} {record['case_id']}"
                )
            source = str(Path(record["source_path"]).resolve())
            assignment_id = assignment_by_source.get(source)
            if assignment_id is None:
                raise RuntimeError(f"direct source is outside the study: {source}")
            score_path = summary_path.parent / "cases" / record["case_id"] / model / "score.json"
            saved = read(score_path)
            assert isinstance(saved, dict)
            if saved != {**record, "status": "completed"}:
                raise RuntimeError(f"direct score evidence mismatch: {window} {assignment_id}")
            if assignment_id in records:
                raise RuntimeError(f"duplicate direct record: {window} {assignment_id}")
            records[assignment_id] = record["verdict"]
        result[window] = records
    return result


def extract(study: Path, audit: Path, model: str) -> dict[str, object]:
    study = study.resolve()
    audit = audit.resolve()
    ledger = read(study / "study.json")
    assert isinstance(ledger, dict)
    completed = [record for record in ledger["records"] if record["status"] == "completed"]
    assignment_by_source = {
        str((study / record["experiment_dir"]).resolve()): record["assignment_id"]
        for record in completed
    }
    if len(assignment_by_source) != 18:
        raise RuntimeError("PaperBench Dev3 extraction requires exactly 18 assignments")

    rubric_assignments, rubric_coverage = _rubric_assignments(study, audit, model)
    rubric_by_assignment = {
        assignment["assignment_id"]: assignment for assignment in rubric_assignments
    }
    absolute = _absolute_records(audit, model)
    direct = _direct_records(study, audit, model, assignment_by_source)
    ids = set(assignment_by_source.values())
    if set(rubric_by_assignment) != ids:
        raise RuntimeError("rubric assignment coverage is incomplete")
    expected_absolute = {
        (assignment_id, artifact)
        for assignment_id in ids
        for artifact in ("initial", "final")
    }
    if set(absolute) != expected_absolute:
        raise RuntimeError("absolute-score assignment coverage is incomplete")
    for window in WINDOWS:
        if set(direct[window]) != ids:
            raise RuntimeError(f"direct assignment coverage is incomplete: {window}")

    rows = []
    for assignment_id in sorted(ids):
        assignment = rubric_by_assignment[assignment_id]
        references = assignment["reference_scores"]
        selected = float(references["selected"]["final"]["scores"][model])
        heldout = [
            float(variant["scores"][model])
            for variant in references["holdout"]["final"]["variants"].values()
        ]
        if len(heldout) != 3:
            raise RuntimeError(f"expected three held-out rubrics: {assignment_id}")
        original = float(assignment["weak_original_rubric_scores"]["final"])
        trained = float(assignment["active_local_scores"]["final"]["weak_score"])
        absolute_final = absolute[assignment_id, "final"]
        quality = float(absolute_final["verdict"]["score"])
        values = {
            "W": original,
            "W_train": trained,
            "S": selected,
            "H": fmean(heldout),
            "A": quality,
        }
        values.update(
            WS=values["W"] - values["S"],
            SH=values["S"] - values["H"],
            HA=values["H"] - values["A"],
            WA=values["W"] - values["A"],
        )
        if abs(values["WA"] - values["WS"] - values["SH"] - values["HA"]) > 1e-8:
            raise RuntimeError(f"score decomposition does not close: {assignment_id}")
        rows.append(
            {
                "assignment_id": assignment_id,
                "condition_id": assignment["condition_id"],
                "arm": arm(assignment["condition_id"]),
                "task_id": assignment["task_id"],
                "replicate": assignment["replicate"],
                "model": model,
                "initial_submission_sha256": absolute[assignment_id, "initial"][
                    "submission_content_sha256"
                ],
                "final_submission_sha256": absolute_final["submission_content_sha256"],
                "values": values,
                "direct": {window: direct[window][assignment_id] for window in WINDOWS},
            }
        )

    summaries = {}
    for arm_name in ("full", "user"):
        selected_rows = [row for row in rows if row["arm"] == arm_name]
        if len(selected_rows) != 9:
            raise RuntimeError(f"expected nine {arm_name} assignments")
        summaries[arm_name] = {
            "values": {
                key: stats([float(row["values"][key]) for row in selected_rows])
                for key in VALUE_KEYS
            },
            "direct": {
                window: dict(
                    Counter(row["direct"][window]["decision"] for row in selected_rows)
                )
                for window in WINDOWS
            },
        }
    return {
        "kind": "paperbench-rtt-dev3-single-auditor-extraction-v1",
        "study": str(study),
        "audit": str(audit),
        "experiment_id": ledger["experiment_id"],
        "model": model,
        "assignment_count": len(rows),
        "coverage": {
            "rubric_score": rubric_coverage,
            "absolute_score_assignment_references": len(absolute),
            "direct_assignment_references": {
                window: len(direct[window]) for window in WINDOWS
            },
        },
        "summaries": summaries,
        "rows": rows,
    }


def compare(baseline: dict, candidate: dict) -> dict[str, object]:
    if baseline["model"] != candidate["model"]:
        raise RuntimeError("baseline and candidate auditors differ")
    baseline_rows = {
        (row["arm"], row["task_id"], row["replicate"], row["model"]): row
        for row in baseline["rows"]
    }
    candidate_rows = {
        (row["arm"], row["task_id"], row["replicate"], row["model"]): row
        for row in candidate["rows"]
    }
    if baseline_rows.keys() != candidate_rows.keys() or len(baseline_rows) != 18:
        raise RuntimeError("baseline and candidate Dev3 cells are not matched")
    deltas = []
    for key in sorted(baseline_rows):
        left = baseline_rows[key]
        right = candidate_rows[key]
        if left["initial_submission_sha256"] != right["initial_submission_sha256"]:
            raise RuntimeError(f"matched Dev3 seed artifact differs: {key}")
        deltas.append(
            {
                "arm": key[0],
                "task_id": key[1],
                "replicate": key[2],
                "model": key[3],
                "candidate_minus_baseline": {
                    value: float(right["values"][value]) - float(left["values"][value])
                    for value in VALUE_KEYS
                },
            }
        )
    summaries = {
        arm_name: {
            value: stats(
                [
                    float(row["candidate_minus_baseline"][value])
                    for row in deltas
                    if row["arm"] == arm_name
                ]
            )
            for value in VALUE_KEYS
        }
        for arm_name in ("full", "user")
    }
    return {
        "kind": "paperbench-rtt-vs-static-matched-dev3-v1",
        "model": baseline["model"],
        "baseline_experiment_id": baseline["experiment_id"],
        "candidate_experiment_id": candidate["experiment_id"],
        "matched_cell_count": len(deltas),
        "initial_submission_identity": "exact-sha256-match-per-arm-task-replicate",
        "baseline": baseline["summaries"],
        "candidate": candidate["summaries"],
        "candidate_minus_baseline": summaries,
        "deltas": deltas,
    }


def absolute(path: str) -> Path:
    value = Path(path)
    if not value.is_absolute() or value.is_symlink():
        raise argparse.ArgumentTypeError("path must be absolute and non-symlinked")
    return value


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    extract_parser = subparsers.add_parser("extract")
    extract_parser.add_argument("--study", type=absolute, required=True)
    extract_parser.add_argument("--audit", type=absolute, required=True)
    extract_parser.add_argument("--model", required=True)
    extract_parser.add_argument("--output", type=absolute, required=True)
    compare_parser = subparsers.add_parser("compare")
    compare_parser.add_argument("--baseline", type=absolute, required=True)
    compare_parser.add_argument("--candidate", type=absolute, required=True)
    compare_parser.add_argument("--output", type=absolute, required=True)
    args = parser.parse_args()

    if args.command == "extract":
        output = extract(args.study, args.audit, args.model)
    else:
        baseline = read(args.baseline)
        candidate = read(args.candidate)
        assert isinstance(baseline, dict) and isinstance(candidate, dict)
        output = compare(baseline, candidate)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(args.output, output)
    print(json.dumps({
        "output": str(args.output),
        "kind": output["kind"],
        "model": output["model"],
    }))


if __name__ == "__main__":
    main()
