"""Recover provider-free Opus responses or run the independent Gemini audit."""
from __future__ import annotations

import argparse
from collections import Counter
import json
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.audit_execution import audit_output_owner
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.resume import prepare_stage_output
from rubric_gen.submission_revision.evaluation.runner import RubricScoreRunner
from rubric_gen.submission_revision.evaluation.targets import load_evaluation_targets
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.source_resolution import resolve_study_sources

from prepare import CONFIG, RUN
from run import (
    GEMINI,
    SOL_OPUS,
    audit_stage,
    check_revision_receipt,
    clean_commit,
    credentials,
    install_reuse,
    now,
    scoped_experiment,
)


def publish_saved_opus() -> None:
    """Publish only native-validated saved responses; make no provider calls."""
    experiment = load_experiment(CONFIG)
    check_revision_receipt(experiment)
    scoped = scoped_experiment(
        experiment,
        SOL_OPUS,
        Path(experiment.dag["detect"]["output_dir"]),
    )
    install_reuse()
    study = Path(scoped.dag["revise"]["output_dir"])
    output = Path(scoped.dag["detect"]["output_dir"])
    sources = resolve_study_sources(study, scoped)
    config = EvaluationConfig(
        experiment=scoped,
        study_dir=study,
        paraphrase_dir=Path(scoped.dag["paraphrase"]["output_dir"]),
        output_dir=output / "rubric_score",
        max_concurrency=1,
        resume=True,
    )
    targets = load_evaluation_targets(config, sources)
    runner = RubricScoreRunner(config, targets)
    runner.preflight()
    prepared = runner._prepared
    if prepared is None:
        raise RuntimeError("rubric-score replay preflight produced no plan")
    replay_keys = set(runner._saved_response_replays)
    jobs = [job for job in prepared.unique_jobs if job.key in replay_keys]
    if len(jobs) != len(replay_keys):
        raise RuntimeError("saved replay keys are not unique in the prepared plan")
    receipt = RUN / "provider-free-opus-replay.json"
    with audit_output_owner(output):
        prepare_stage_output(
            runner.output,
            runner._manifest(prepared, SOL_OPUS),
            True,
            prepared.jobs,
        )
        completed = []
        for job in jobs:
            record = runner._run_job(job)
            if record.get("judgment_key") != job.key:
                raise RuntimeError("published replay record key changed")
            completed.append(job.key)
        write_json_atomic(receipt, {
            "provider_calls": 0,
            "planned_replays": len(jobs),
            "published_replays": len(completed),
            "judgment_keys": sorted(completed),
        })
    print(json.dumps({
        "published_replays": len(completed),
        "receipt": str(receipt),
    }), flush=True)


def inspect_status() -> None:
    """Print bounded stage coverage from the persistent audit roots."""
    experiment = load_experiment(CONFIG)
    roots = {
        "sol-opus": Path(experiment.dag["detect"]["output_dir"]),
        "gemini": RUN / "audit-gemini" / experiment.experiment_id,
    }
    result = {}
    for panel, root in roots.items():
        stages = {}
        for name in ("rubric_score", "absolute_score", "pairwise_preference"):
            summary_path = root / name / "summary.json"
            records = root / name / "records"
            value = {
                "record_files": len(list(records.glob("*.json"))) if records.is_dir() else 0,
                "summary_exists": summary_path.is_file(),
            }
            if summary_path.is_file():
                summary = json.loads(summary_path.read_text())
                for field in (
                    "status",
                    "planned_semantic_judgment_count",
                    "successful_semantic_judgment_count",
                    "failed_semantic_judgment_count",
                    "missing_models",
                ):
                    value[field] = summary.get(field)
            stages[name] = value
        for window in (
            "full_trajectory",
            "post_update",
            "final_artifact",
            "final_revision",
        ):
            summaries = list(
                (root / f"direct_{window}" / "evaluations").glob("*/summary.json")
            )
            value = {"summary_count": len(summaries)}
            if len(summaries) == 1:
                summary = json.loads(summaries[0].read_text())
                rows = summary.get("records", [])
                value.update({
                    "record_count": len(rows),
                    "statuses": dict(Counter(str(row.get("status")) for row in rows)),
                    "decisions": dict(Counter(
                        str(row.get("verdict", {}).get("decision")) for row in rows
                        if isinstance(row.get("verdict"), dict)
                    )),
                })
            stages[f"direct_{window}"] = value
        result[panel] = {"root": str(root), "stages": stages}
    print(json.dumps(result, indent=2, sort_keys=True))


def run_gemini() -> None:
    """Finish the independent Gemini panel without waiting on Opus."""
    clean_commit()
    credentials("audit")
    experiment = load_experiment(CONFIG)
    check_revision_receipt(experiment)
    sources = install_reuse()
    output = RUN / "audit-gemini" / experiment.experiment_id
    scoped = scoped_experiment(experiment, GEMINI, output)
    receipt = RUN / "audit-gemini-status.json"
    write_json_atomic(receipt, {
        "started_at": now(),
        "models": list(GEMINI),
        "workers": 60,
        "reuse_sources": sources,
    })
    result = audit_stage(
        "gemini",
        scoped,
        60,
        RUN / "detect-gemini.log",
    )
    write_json_atomic(receipt, {**result, "reuse_sources": sources})
    print(json.dumps(result), flush=True)
    if result["exit_code"]:
        raise RuntimeError("Gemini audit incomplete; saved judgments retained")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("publish-saved-opus", "gemini", "status"))
    args = parser.parse_args()
    if args.mode == "publish-saved-opus":
        publish_saved_opus()
    elif args.mode == "gemini":
        run_gemini()
    else:
        inspect_status()


if __name__ == "__main__":
    main()
