"""Recover only missing matched Sol/Opus rubric-score semantic judgments."""
from __future__ import annotations

import argparse
import copy
from concurrent.futures import as_completed
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil

from dotenv import dotenv_values

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.audit_execution import AuditExecutor, audit_output_owner
from rubric_gen.runtime.capacity import policy, reservation
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.rubric_judge import (
    FullRubricJudgeError,
    SavedRubricResponse,
)
from rubric_gen.submission_revision.evaluation.rubric_score import (
    _rubric_score_attempt_id,
)
from rubric_gen.submission_revision.evaluation.runner import RubricScoreRunner
from rubric_gen.submission_revision.evaluation.targets import load_evaluation_targets
from rubric_gen.submission_revision.experiment import Experiment, load_experiment
from rubric_gen.submission_revision.source_resolution import resolve_study_sources


ROOT = Path(__file__).resolve().parents[2]
PANEL = ("gpt-5.6-sol", "claude-opus-5")


def _read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _import_successes(output_root: Path, original_audit: Path,
                      successes: list[dict]) -> list[dict]:
    """Add only recovered missing records; preserve every prior attempt."""
    source = output_root / "rubric_score"
    destination = original_audit / "rubric_score"
    imported = []
    for success in successes:
        key = success["key"]
        source_record = source / "records" / f"{key}.json"
        destination_record = destination / "records" / f"{key}.json"
        if destination_record.exists():
            raise RuntimeError(f"recovery would overwrite rubric record {key}")
        source_artifacts = source / "artifacts" / key
        destination_artifacts = destination / "artifacts" / key
        for path in sorted(source_artifacts.glob("**/*")):
            if not path.is_file():
                continue
            target = destination_artifacts / path.relative_to(source_artifacts)
            if target.exists():
                if target.read_bytes() != path.read_bytes():
                    relative = path.relative_to(source_artifacts)
                    is_attempt_evidence = (
                        any(part.endswith(".attempts") for part in relative.parts)
                        or path.name.startswith("failed-attempt-")
                    )
                    if not is_attempt_evidence:
                        raise RuntimeError(
                            f"recovery artifact collision differs for {target}"
                        )
                    # The original and isolated recovery roots each preserve
                    # their own numbered provider attempts.  A recovered
                    # attempt can reuse attempt-001 without overwriting the
                    # original failed attempt at that name; only the validated
                    # canonical evaluation is imported below.
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        record = _read(source_record)
        source_prefix = str(source)
        destination_prefix = str(destination)
        for field in ("evaluation_path", "validation_path"):
            value = record[field]
            if not value.startswith(source_prefix + os.sep):
                raise RuntimeError(f"recovery {field} escaped isolated root")
            record[field] = destination_prefix + value[len(source_prefix):]
            if not Path(record[field]).is_file():
                raise RuntimeError(f"imported recovery {field} is absent")
        write_json_atomic(destination_record, record)
        imported.append({
            "key": key,
            "model": success["model"],
            "score": success["score"],
            "record": str(destination_record),
        })
    return imported


def _replay_complete_saved_response(runner: RubricScoreRunner, job):
    """Publish an exact complete response that used pipe-delimited v8 rows."""

    judge = runner._judge_for_job(job)
    attempt_id = _rubric_score_attempt_id(job)
    root = judge._evaluation_root(job.submission, attempt_id)
    attempts = root.parent / f"{attempt_id}.attempts"
    for attempt in range(1, 4):
        state = attempts / f"attempt-{attempt:03d}.json"
        response = attempts / f"attempt-{attempt:03d}.response.json"
        if not state.is_file() or not response.is_file():
            continue
        candidate = SavedRubricResponse(state, response, _read(state)["identity"])
        try:
            candidate.replay(judge, job.submission)
        except FullRubricJudgeError:
            continue
        runner._saved_response_replays = {job.key: candidate}
        return runner._run_job(job)
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, required=True)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--path-map", type=Path, required=True)
    parser.add_argument("--original-audit", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--max-concurrency", type=int, default=4)
    args = parser.parse_args()
    for path in (args.experiment, args.runtime_config, args.path_map):
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise RuntimeError(f"required input must be an absolute regular file: {path}")
    for path in (args.original_audit, args.output_root):
        if not path.is_absolute() or path.is_symlink():
            raise RuntimeError(f"audit path must be absolute and non-symlinked: {path}")
    if not 1 <= args.max_concurrency <= 12:
        raise ValueError("recovery concurrency must be between one and twelve")

    os.environ["RUBRIC_GEN_PATH_MAP_FILE"] = str(args.path_map)
    os.environ["RUBRIC_GEN_RUNTIME_CONFIG"] = str(args.runtime_config)
    os.environ.pop("RUBRIC_GEN_OPENAI_REASONING_EFFORT", None)
    if policy()["audit_studies"] != 1:
        raise RuntimeError("local audit studies must remain serialized")
    credentials = dotenv_values(ROOT / ".env.local")
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        value = os.environ.get(name) or credentials.get(name)
        if not value:
            raise RuntimeError(f"configured {name} absent")
        os.environ[name] = str(value)

    source = load_experiment(args.experiment)
    payload = copy.deepcopy(source.payload)
    payload["execution_audit_models"] = list(PANEL)
    experiment = Experiment(source.path, payload)
    study = Path(experiment.dag["revise"]["output_dir"])
    paraphrases = Path(experiment.dag["paraphrase"]["output_dir"])
    manifest = _read(args.original_audit / "rubric_score" / "manifest.json")
    planned = {str(job["semantic_key"]) for job in manifest["predispatch_plan"]["jobs"]}
    completed = {path.stem for path in (args.original_audit / "rubric_score" / "records").glob("*.json")}
    missing = planned - completed
    if not missing:
        print(json.dumps({"stage": "no_missing_rubric_scores"}), flush=True)
        return

    config = EvaluationConfig(
        experiment=experiment,
        study_dir=study,
        paraphrase_dir=paraphrases,
        output_dir=args.output_root / "rubric_score",
        max_concurrency=args.max_concurrency,
        resume=True,
    )
    sources = resolve_study_sources(study, experiment)
    runner = RubricScoreRunner(config, load_evaluation_targets(config, sources))
    runner.preflight()
    prepared = runner._prepared
    if prepared is None:
        raise RuntimeError("rubric-score recovery produced no plan")
    jobs = tuple(job for job in prepared.unique_jobs if job.key in missing)
    if {job.key for job in jobs} != missing:
        raise RuntimeError("could not resolve every missing rubric semantic key")

    successes: list[dict] = []
    failures: list[dict] = []
    jobs_by_key = {job.key: job for job in jobs}
    args.output_root.mkdir(parents=True, exist_ok=True)
    write_json_atomic(args.output_root / "recovery-plan.json", {
        "kind": "matched-sol-opus-rubric-score-recovery",
        "original_audit": str(args.original_audit),
        "models": list(PANEL),
        "missing_keys": sorted(missing),
        "jobs_by_model": {model: sum(job.model == model for job in jobs) for model in PANEL},
        "request_identity": "unchanged canonical rubric-score jobs",
        "time": datetime.now(timezone.utc).isoformat(),
    })
    with audit_output_owner(args.output_root), reservation("audit"), AuditExecutor(
        args.max_concurrency, PANEL
    ) as executor:
        futures = {executor.submit(runner._run_job, job): job for job in jobs}
        for future in as_completed(futures):
            job = futures[future]
            try:
                result = future.result()
                successes.append({"key": job.key, "model": job.model, **result})
            except Exception as error:
                failures.append({
                    "key": job.key,
                    "model": job.model,
                    "error_type": type(error).__name__,
                    "error": str(error),
                })
    remaining_failures = []
    for failure in failures:
        job = jobs_by_key[failure["key"]]
        replayed = _replay_complete_saved_response(runner, job)
        if replayed is None:
            remaining_failures.append(failure)
        else:
            successes.append({
                "key": job.key,
                "model": job.model,
                "local_response_replay": True,
                **replayed,
            })
    failures = remaining_failures
    receipt = {
        "kind": "matched-sol-opus-rubric-score-recovery-result",
        "planned": len(jobs),
        "successful": len(successes),
        "failed": len(failures),
        "successes": sorted(successes, key=lambda row: row["key"]),
        "failures": sorted(failures, key=lambda row: row["key"]),
        "time": datetime.now(timezone.utc).isoformat(),
    }
    write_json_atomic(args.output_root / "recovery-result.json", receipt)
    imported = _import_successes(
        args.output_root, args.original_audit, successes
    )
    write_json_atomic(args.output_root / "recovery-import.json", {
        "kind": "matched-sol-opus-rubric-score-recovery-import",
        "original_audit": str(args.original_audit),
        "records": imported,
        "time": datetime.now(timezone.utc).isoformat(),
    })
    print(json.dumps({key: receipt[key] for key in ("planned", "successful", "failed")}), flush=True)
    if failures:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
