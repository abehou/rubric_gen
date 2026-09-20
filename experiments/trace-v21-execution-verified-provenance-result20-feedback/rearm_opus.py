"""Archive only reviewed missing Opus failure state before native resume."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.runner import RubricScoreRunner
from rubric_gen.submission_revision.evaluation.targets import load_evaluation_targets
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.source_resolution import resolve_study_sources

from prepare import CONFIG, RUN
from run import SOL_OPUS, check_revision_receipt, install_reuse, scoped_experiment


MODEL = "claude-opus-5"
CREDIT = "credit balance is too low"
CARDINALITY = "rubric criteria_text must contain exactly"
INCOMPLETE = "Anthropic response stopped before a complete answer"
EXHAUSTED_DIRECT = {
    "model response contains no JSON object",
    "Anthropic returned an empty response",
}


def read_object(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"recovery input is not a regular file: {path}")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError(f"recovery input is not an object: {path}")
    return value


def allowed_rubric_failure(state: dict[str, object]) -> bool:
    error = str(state.get("error", ""))
    category = state.get("failure_category")
    return (
        (category == "invalid_response" and CARDINALITY in error)
        or (category in {"configuration", "structural"} and CREDIT in error)
        or (category == "transient_connection" and INCOMPLETE in error)
    )


def rubric_actions(runner: RubricScoreRunner, archive: Path) -> list[dict[str, object]]:
    prepared = runner._prepared
    if prepared is None:
        raise RuntimeError("Opus rearm preflight produced no native plan")
    if runner._saved_response_replays:
        raise RuntimeError("recoverable saved Opus responses must be published before rearm")
    pending = [
        job for job in prepared.unique_jobs
        if job.key not in runner._reused_records
    ]
    if not pending or any(job.model != MODEL for job in pending):
        raise RuntimeError("native pending rubric scope is not exclusively missing Opus work")
    actions: list[dict[str, object]] = []
    for job in pending:
        artifact = runner.output.path("artifacts", job.key)
        if not artifact.exists():
            continue
        if artifact.is_symlink() or not artifact.is_dir():
            raise RuntimeError(f"missing Opus artifact is unsafe: {artifact}")
        if list(artifact.rglob("evaluation.json")):
            raise RuntimeError(f"refusing to rearm a completed Opus rubric judgment: {artifact}")
        states = [
            read_object(path) for path in sorted(artifact.rglob("attempt-*.json"))
            if not path.name.endswith(".response.json")
            and not path.name.startswith("failed-attempt-")
        ]
        if not states:
            continue
        if not all(allowed_rubric_failure(state) for state in states):
            raise RuntimeError(f"unsupported missing Opus rubric failure: {artifact}")
        destination = archive / "rubric_score" / job.key
        if destination.exists():
            raise RuntimeError(f"Opus recovery archive already exists: {destination}")
        actions.append({
            "kind": "rubric_score",
            "judgment_key": job.key,
            "source": str(artifact),
            "archive": str(destination),
            "saved_attempts": len(states),
            "failure_categories": sorted({str(state.get("failure_category")) for state in states}),
        })
    return actions


def direct_actions(root: Path, archive: Path) -> list[dict[str, object]]:
    actions: list[dict[str, object]] = []
    for summary_path in sorted(root.glob("direct_*/evaluations/*/summary.json")):
        summary = read_object(summary_path)
        stage = summary_path.parents[2].name
        for record in summary.get("records", []):
            if record.get("model") != MODEL or record.get("status") != "failed":
                continue
            case_id = record.get("case_id")
            if not isinstance(case_id, str) or not case_id:
                raise RuntimeError(f"invalid missing Opus direct case: {summary_path}")
            model_root = summary_path.parent / "cases" / case_id / MODEL
            if (model_root / "score.json").exists():
                # A later missing-only pass may have completed a row while the
                # enclosing summary remained stale after another stage failed.
                # Native resume will validate the score and rebuild the summary.
                continue
            for attempt in sorted(model_root.glob("chunk-*/attempt-*.json")):
                state = read_object(attempt)
                error = str(state.get("error", ""))
                if not error:
                    continue
                if CREDIT not in error and error not in EXHAUSTED_DIRECT:
                    raise RuntimeError(f"unsupported missing Opus RH failure: {attempt}")
                destination = archive / stage / case_id / attempt.relative_to(model_root)
                if destination.exists():
                    raise RuntimeError(f"Opus recovery archive already exists: {destination}")
                actions.append({
                    "kind": "direct_rh_attempt",
                    "stage": stage,
                    "case_id": case_id,
                    "source": str(attempt),
                    "archive": str(destination),
                    "error_type": str(state.get("error_type") or error.split(":", 1)[0]),
                })
    return actions


def plan() -> tuple[Path, list[dict[str, object]], dict[str, int]]:
    experiment = load_experiment(CONFIG)
    check_revision_receipt(experiment)
    output = Path(experiment.dag["detect"]["output_dir"])
    scoped = scoped_experiment(experiment, SOL_OPUS, output)
    install_reuse()
    study = Path(scoped.dag["revise"]["output_dir"])
    config = EvaluationConfig(
        experiment=scoped,
        study_dir=study,
        paraphrase_dir=Path(scoped.dag["paraphrase"]["output_dir"]),
        output_dir=output / "rubric_score",
        max_concurrency=1,
        resume=True,
    )
    sources = resolve_study_sources(study, scoped)
    runner = RubricScoreRunner(config, load_evaluation_targets(config, sources))
    runner.preflight()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = output / "recovery-evidence" / f"opus-missing-rearm-{stamp}"
    actions = rubric_actions(runner, archive) + direct_actions(output, archive)
    counts: dict[str, int] = {}
    for action in actions:
        kind = str(action["kind"])
        counts[kind] = counts.get(kind, 0) + 1
    return archive, actions, counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply"))
    args = parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Opus audit recovery must run through Slurm")
    archive, actions, counts = plan()
    if not actions:
        raise RuntimeError("no reviewed missing Opus failure state requires rearm")
    if args.mode == "apply":
        for action in actions:
            source = Path(str(action["source"]))
            destination = Path(str(action["archive"]))
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)
        receipt = RUN / f"opus-missing-rearm-{archive.name.rsplit('-', 1)[-1]}.json"
        write_json_atomic(receipt, {
            "kind": "result20-feedback-opus-missing-rearm",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_commit": os.environ.get("RESULT20_FEEDBACK_SOURCE_COMMIT"),
            "provider_calls": 0,
            "request_semantics_changed": False,
            "model": MODEL,
            "counts": counts,
            "actions": actions,
        })
        print(json.dumps({"applied": True, "counts": counts, "receipt": str(receipt)}))
    else:
        print(json.dumps({"applied": False, "counts": counts, "actions": len(actions)}))


if __name__ == "__main__":
    main()
