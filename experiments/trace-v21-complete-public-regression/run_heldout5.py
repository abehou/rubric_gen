"""Extend da-26-4 to five heldouts and score only the two new rubrics.

This is an audit-only sensitivity check.  Variants 0--4 and all four saved
final artifacts are reused byte-for-byte.  The only provider work here is the
generation of variants 5/6 and their Sol/Gemini rubric-score judgments.
"""

from __future__ import annotations

from concurrent.futures import as_completed
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import subprocess

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.audit_execution import AuditExecutor, audit_output_owner
from rubric_gen.runtime.capacity import reservation
from rubric_gen.submission_revision.evaluation import jobs as evaluation_jobs
from rubric_gen.submission_revision.evaluation import rubric_score
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.rubric_score import RubricScoreStage
from rubric_gen.submission_revision.evaluation.targets import load_evaluation_targets
from rubric_gen.submission_revision.experiment import Experiment, load_experiment
from rubric_gen.submission_revision.paraphrases import (
    ParaphraseRunConfig,
    ParaphraseRunner,
)
from rubric_gen.submission_revision.paraphrase_validation import (
    resolve_paraphrase_selection,
    validate_paraphrase_run,
    validate_request_policy,
)
from rubric_gen.submission_revision.source_resolution import resolve_study_sources


ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "experiments/trace-v21-complete-public-regression"
RESULT40 = ROOT / "experiments/trace-v21-execution-verified-provenance-result40"
ORIGINAL_CONFIG = RESULT40 / "configs/da-26-4-trace.yaml"
REPAIRED_CONFIG = BUNDLE / "configs/da-26-4-rep002.yaml"
RUN = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-complete-public-regression-20260921/heldout5"
)
EXTENDED_POOL = RUN / "paraphrases"
AUDIT_ROOT = RUN / "rubric-score"
MODELS = ("gpt-5.6-sol", "gemini-3.8-flash")
NEW_VARIANTS = {5, 6}
WORKERS = 12


def heldout5_scope(original: Experiment) -> Experiment:
    """Change only the measurement panel from three to five heldouts."""

    payload = deepcopy(original.payload)
    payload["rubric_paraphrases"]["count"] = 7
    payload["outcome_audit"]["models"] = list(MODELS)
    payload["execution_audit_models"] = list(MODELS)
    payload["dag"]["paraphrase"]["output_dir"] = str(EXTENDED_POOL)
    scoped = replace(original, payload=payload)
    if scoped.rubric_paraphrases["selected_variant"] != 0:
        raise RuntimeError("heldout-5 scope changed the selected rubric")
    if scoped.rubric_paraphrases["development_variant"] != 1:
        raise RuntimeError("heldout-5 scope changed the development rubric")
    if scoped.rubric_paraphrases["count"] != 7:
        raise RuntimeError("heldout-5 scope must contain seven total variants")
    return scoped


def _copy_file_exact(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.read_bytes() != source.read_bytes():
            raise RuntimeError(f"extended pool differs from frozen source: {destination}")
        return
    with destination.open("xb") as handle:
        handle.write(source.read_bytes())


def prepare_extended_pool(
    source_pool: Path,
    experiment: Experiment,
) -> dict[str, object]:
    """Copy variants 0--4 exactly, then natively generate only 5 and 6."""

    runner = ParaphraseRunner(
        ParaphraseRunConfig(
            experiment=experiment,
            output_dir=EXTENDED_POOL,
            max_concurrency=2,
        )
    )
    EXTENDED_POOL.mkdir(parents=True, exist_ok=True)
    manifest_path = EXTENDED_POOL / "manifest.json"
    if not manifest_path.exists():
        unexpected = list(EXTENDED_POOL.iterdir())
        if unexpected:
            raise RuntimeError("unowned files exist in new heldout-5 pool")
        write_json_atomic(manifest_path, runner._new_manifest())

    task_id = "da-26-4"
    source_task = source_pool / "tasks" / task_id
    destination_task = EXTENDED_POOL / "tasks" / task_id
    copied_hashes: dict[str, str] = {}
    for variant in range(5):
        stem = f"variant-{variant:03d}"
        for suffix in (".txt", ".json"):
            source = source_task / f"{stem}{suffix}"
            destination = destination_task / f"{stem}{suffix}"
            _copy_file_exact(source, destination)
            copied_hashes[f"{stem}{suffix}"] = sha256_file(destination)
        source_failures = source_task / f"{stem}.failures"
        destination_failures = destination_task / f"{stem}.failures"
        if source_failures.exists():
            if destination_failures.exists():
                for source in source_failures.rglob("*"):
                    if source.is_file():
                        _copy_file_exact(
                            source,
                            destination_failures / source.relative_to(source_failures),
                        )
            else:
                shutil.copytree(source_failures, destination_failures)

    if runner.run() != 0:
        raise RuntimeError("heldout-5 paraphrase generation failed")
    validate_paraphrase_run(EXTENDED_POOL, experiment)
    master = (
        experiment.task_dir(task_id)
        / "tests"
        / str(experiment.protocol["rubric_name"])
    ).read_text(encoding="utf-8")
    for variant in NEW_VARIANTS:
        validate_request_policy(
            destination_task / f"variant-{variant:03d}.json",
            master,
            experiment.rubric_paraphrases,
        )
    for variant in range(5):
        stem = f"variant-{variant:03d}"
        for suffix in (".txt", ".json"):
            if sha256_file(destination_task / f"{stem}{suffix}") != copied_hashes[
                f"{stem}{suffix}"
            ]:
                raise RuntimeError(f"frozen paraphrase changed: {stem}{suffix}")
    return {
        "source_pool": str(source_pool),
        "extended_pool": str(EXTENDED_POOL),
        "preserved_variants": list(range(5)),
        "generated_variants": sorted(NEW_VARIANTS),
        "variant_sha256s": {
            str(variant): sha256_file(
                destination_task / f"variant-{variant:03d}.txt"
            )
            for variant in range(7)
        },
    }


def _source_targets(experiment: Experiment) -> tuple[evaluation_jobs.EvaluationTarget, ...]:
    study_dir = Path(str(experiment.dag["revise"]["output_dir"]))
    config = EvaluationConfig(
        experiment=experiment,
        study_dir=study_dir,
        paraphrase_dir=Path(str(experiment.dag["paraphrase"]["output_dir"])),
        output_dir=RUN / "target-loading-unused",
        max_concurrency=4,
        resume=True,
    )
    return load_evaluation_targets(
        config,
        resolve_study_sources(study_dir, experiment),
    )


def load_four_targets(
    original: Experiment,
    repaired: Experiment,
    extended: Experiment,
) -> tuple[evaluation_jobs.EvaluationTarget, ...]:
    selection = resolve_paraphrase_selection(EXTENDED_POOL, extended, "da-26-4")
    original_targets = tuple(
        target
        for target in _source_targets(original)
        if target.replicate == 2
    )
    repaired_targets = _source_targets(repaired)
    targets = (*original_targets, *repaired_targets)
    if len(targets) != 4:
        raise RuntimeError(f"expected four original/repaired targets, found {len(targets)}")
    arms = [
        "user" if target.condition_id.startswith("user-") else "full"
        for target in targets
    ]
    if arms.count("full") != 2 or arms.count("user") != 2:
        raise RuntimeError("heldout-5 comparison does not contain two targets per arm")
    return tuple(replace(target, selection=selection) for target in targets)


def _new_holdout_jobs(
    stage: RubricScoreStage,
    targets: tuple[evaluation_jobs.EvaluationTarget, ...],
) -> tuple[evaluation_jobs.RubricScoreJob, ...]:
    implementation = rubric_score._evaluation_implementation_sha256()
    request_hashes: dict[tuple[str, str], tuple[str, str]] = {}
    jobs = tuple(
        job
        for target in targets
        for job in stage._artifact_jobs(
            target,
            "final",
            MODELS,
            implementation,
            request_hashes,
        )
        if any(
            role.name == "holdout" and role.variant_index in NEW_VARIANTS
            for role in job.roles
        )
    )
    if len(jobs) != 16:
        raise RuntimeError(f"expected 16 new heldout judgments, found {len(jobs)}")
    if any(
        len(job.roles) != 1
        or job.roles[0].name != "holdout"
        or job.roles[0].variant_index not in NEW_VARIANTS
        or job.artifact != "final"
        for job in jobs
    ):
        raise RuntimeError("heldout-5 job scope contains a non-new or non-final rubric")
    return jobs


def run_new_holdout_scores(
    experiment: Experiment,
    targets: tuple[evaluation_jobs.EvaluationTarget, ...],
) -> dict[str, object]:
    config = EvaluationConfig(
        experiment=experiment,
        study_dir=RUN / "four-read-only-source-studies",
        paraphrase_dir=EXTENDED_POOL,
        output_dir=AUDIT_ROOT,
        max_concurrency=WORKERS,
        resume=True,
    )
    stage = RubricScoreStage(config, targets)
    jobs = _new_holdout_jobs(stage, targets)
    unique_jobs_by_key: dict[str, evaluation_jobs.RubricScoreJob] = {}
    for job in jobs:
        unique_jobs_by_key.setdefault(job.key, job)
    unique_jobs = tuple(unique_jobs_by_key.values())
    plan = stage._predispatch_plan(unique_jobs)
    stage._prepared = evaluation_jobs.PreparedRubricScoreEvaluation(
        targets=targets,
        jobs=jobs,
        unique_jobs=unique_jobs,
        predispatch_plan=plan,
    )
    launch = {
        "kind": "heldout5-new-rubric-score-only",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "job_id": os.environ.get("SLURM_JOB_ID"),
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "models": list(MODELS),
        "variants": sorted(NEW_VARIANTS),
        "artifact": "final",
        "target_count": len(targets),
        "judgment_count": len(unique_jobs),
        "max_concurrency": WORKERS,
        "aggregate_concurrency": 6,
    }
    AUDIT_ROOT.mkdir(parents=True, exist_ok=True)
    write_json_atomic(AUDIT_ROOT / "launch.json", launch)
    records: dict[str, dict[str, object]] = {}
    errors: list[BaseException] = []
    with audit_output_owner(AUDIT_ROOT), reservation("audit"), AuditExecutor(
        WORKERS, MODELS
    ) as executor:
        futures = {
            executor.submit(stage._run_job, job, model=job.model): job
            for job in unique_jobs
        }
        for future in as_completed(futures):
            job = futures[future]
            try:
                records[job.key] = future.result()
            except BaseException as exc:
                errors.append(exc)
    summary = {
        **launch,
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "status": "completed" if not errors and len(records) == 16 else "incomplete",
        "successful_judgments": len(records),
        "errors": [f"{type(error).__name__}: {error}" for error in errors],
        "records": [records[key] for key in sorted(records)],
    }
    write_json_atomic(AUDIT_ROOT / "summary.json", summary)
    if summary["status"] != "completed":
        raise RuntimeError("heldout-5 rubric scoring is incomplete")
    return summary


def main() -> int:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("heldout-5 audit must run on a Babel compute node")
    original = load_experiment(ORIGINAL_CONFIG)
    repaired = load_experiment(REPAIRED_CONFIG)
    source_pool = Path(str(original.dag["paraphrase"]["output_dir"]))
    if source_pool != Path(str(repaired.dag["paraphrase"]["output_dir"])):
        raise RuntimeError("original and repaired studies do not share the frozen pool")
    extended = heldout5_scope(repaired)
    pool_receipt = prepare_extended_pool(source_pool, extended)
    targets = load_four_targets(original, repaired, extended)
    summary = run_new_holdout_scores(extended, targets)
    completion = {
        "kind": "heldout5-da-26-4-rep002-completion",
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "pool": pool_receipt,
        "target_assignment_ids": [target.assignment_id for target in targets],
        "audit_status": summary["status"],
        "successful_judgments": summary["successful_judgments"],
    }
    write_json_atomic(RUN / "completion.json", completion)
    print(json.dumps(completion, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
