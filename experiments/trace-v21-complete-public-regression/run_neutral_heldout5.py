"""Score five new neutral heldouts on four saved da-26-4 artifacts.

This is a measurement-only comparison.  The selected rubric and every saved
artifact remain unchanged; only the heldout paraphrase prompt policy changes
from rigorous wording to the same neutral wording-only policy used by selected.
"""

from __future__ import annotations

from concurrent.futures import as_completed
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
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
from rubric_gen.submission_revision.paraphrase_protocol import UNIFORM_NEUTRAL
from rubric_gen.submission_revision.paraphrase_validation import (
    ParaphraseSelection,
    validate_paraphrase_run,
)
from rubric_gen.submission_revision.source_resolution import resolve_study_sources


ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "experiments/trace-v21-complete-public-regression"
RESULT40 = ROOT / "experiments/trace-v21-execution-verified-provenance-result40"
ORIGINAL_CONFIG = RESULT40 / "configs/da-26-4-trace.yaml"
REPAIRED_CONFIG = BUNDLE / "configs/da-26-4-rep002.yaml"
RUN = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-complete-public-regression-20260921/neutral-heldout5"
)
NEUTRAL_POOL = RUN / "paraphrases"
AUDIT_ROOT = RUN / "rubric-score"
MODELS = ("gpt-5.6-sol", "gemini-3.8-flash")
WORKERS = 12


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def neutral_scope(original: Experiment) -> Experiment:
    """Create a five-paraphrase pool with one prompt policy for every variant."""

    payload = deepcopy(original.payload)
    payload["rubric_paraphrases"] = {
        **payload["rubric_paraphrases"],
        "count": 5,
        "selected_variant": 0,
        "development_variant": 1,
        "prompt_policy": UNIFORM_NEUTRAL,
    }
    payload["outcome_audit"]["models"] = list(MODELS)
    payload["execution_audit_models"] = list(MODELS)
    payload["dag"]["paraphrase"]["output_dir"] = str(NEUTRAL_POOL)
    return replace(original, payload=payload)


def prepare_neutral_pool(experiment: Experiment) -> dict[str, object]:
    runner = ParaphraseRunner(
        ParaphraseRunConfig(
            experiment=experiment,
            output_dir=NEUTRAL_POOL,
            max_concurrency=2,
        )
    )
    if runner.run() != 0:
        raise RuntimeError("neutral heldout paraphrase generation failed")
    validate_paraphrase_run(NEUTRAL_POOL, experiment)

    task_root = NEUTRAL_POOL / "tasks/da-26-4"
    paths = tuple(task_root / f"variant-{index:03d}.txt" for index in range(5))
    hashes = tuple(sha256_file(path) for path in paths)
    master = experiment.task_dir("da-26-4") / "tests" / str(
        experiment.protocol["rubric_name"]
    )
    if len(set(hashes) | {sha256_file(master)}) != 6:
        raise RuntimeError("neutral heldout pool contains a duplicate rubric")
    return {
        "prompt_policy": UNIFORM_NEUTRAL,
        "pool": str(NEUTRAL_POOL),
        "variant_sha256s": {
            str(index): digest for index, digest in enumerate(hashes)
        },
    }


def recorded_experiment(study_dir: Path) -> Experiment:
    """Load the experiment identity recorded by a completed read-only study."""

    ledger = read(study_dir / "study.json")
    experiment = load_experiment(Path(str(ledger["experiment_path"])))
    if experiment.experiment_id != ledger["experiment_id"]:
        experiment = Experiment(
            path=experiment.path,
            payload={**experiment.payload, "experiment_id": ledger["experiment_id"]},
        )
    return experiment


def source_targets(
    configured: Experiment,
    *,
    replicate: int | None = None,
) -> tuple[evaluation_jobs.EvaluationTarget, ...]:
    study_dir = Path(str(configured.dag["revise"]["output_dir"]))
    producer = recorded_experiment(study_dir)
    config = EvaluationConfig(
        experiment=producer,
        study_dir=study_dir,
        paraphrase_dir=Path(str(producer.dag["paraphrase"]["output_dir"])),
        output_dir=RUN / "target-loading-unused",
        max_concurrency=4,
        resume=True,
    )
    sources = resolve_study_sources(study_dir, producer)
    if replicate is not None:
        sources = replace(
            sources,
            revisions=tuple(
                source
                for source in sources.revisions
                if source.assignment.replicate == replicate
            ),
        )
    return load_evaluation_targets(
        config,
        sources,
    )


def neutral_selection(
    source: ParaphraseSelection,
) -> ParaphraseSelection:
    paths = tuple(
        NEUTRAL_POOL / "tasks/da-26-4" / f"variant-{index:03d}.txt"
        for index in range(5)
    )
    return replace(
        source,
        holdout_paths=paths,
        holdout_sha256s=tuple(sha256_file(path) for path in paths),
    )


def load_four_source_targets(
    original: Experiment,
    repaired: Experiment,
) -> tuple[evaluation_jobs.EvaluationTarget, ...]:
    original_targets = source_targets(original, replicate=2)
    repaired_targets = source_targets(repaired)
    targets = (*original_targets, *repaired_targets)
    if len(targets) != 4:
        raise RuntimeError(f"expected four saved targets, found {len(targets)}")
    arms = [
        "user" if target.condition_id.startswith("user-") else "full"
        for target in targets
    ]
    if arms.count("full") != 2 or arms.count("user") != 2:
        raise RuntimeError("neutral-heldout comparison requires two targets per arm")
    return targets


def attach_neutral_selection(
    targets: tuple[evaluation_jobs.EvaluationTarget, ...],
) -> tuple[evaluation_jobs.EvaluationTarget, ...]:
    return tuple(
        replace(target, selection=neutral_selection(target.selection))
        for target in targets
    )


def neutral_jobs(
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
        if any(role.name == "holdout" for role in job.roles)
    )
    if len(jobs) != 40:
        raise RuntimeError(f"expected 40 neutral-heldout judgments, found {len(jobs)}")
    if any(
        len(job.roles) != 1
        or job.roles[0].name != "holdout"
        or job.roles[0].variant_index not in range(5)
        or job.artifact != "final"
        for job in jobs
    ):
        raise RuntimeError("neutral-heldout job scope contains another rubric or artifact")
    if len({job.key for job in jobs}) != 40:
        raise RuntimeError("neutral-heldout jobs are not unique")
    return jobs


def run_scores(
    experiment: Experiment,
    targets: tuple[evaluation_jobs.EvaluationTarget, ...],
) -> dict[str, object]:
    config = EvaluationConfig(
        experiment=experiment,
        study_dir=RUN / "four-read-only-source-studies",
        paraphrase_dir=NEUTRAL_POOL,
        output_dir=AUDIT_ROOT,
        max_concurrency=WORKERS,
        resume=True,
    )
    stage = RubricScoreStage(config, targets)
    jobs = neutral_jobs(stage, targets)
    plan = stage._predispatch_plan(jobs)
    stage._prepared = evaluation_jobs.PreparedRubricScoreEvaluation(
        targets=targets,
        jobs=jobs,
        unique_jobs=jobs,
        predispatch_plan=plan,
    )
    launch = {
        "kind": "neutral-heldout5-final-rubric-score-only",
        "started_at": datetime.now(timezone.utc).isoformat(),
        "job_id": os.environ.get("SLURM_JOB_ID"),
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "prompt_policy": UNIFORM_NEUTRAL,
        "models": list(MODELS),
        "artifact": "final",
        "target_count": len(targets),
        "judgment_count": len(jobs),
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
            for job in jobs
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
        "status": "completed" if not errors and len(records) == 40 else "incomplete",
        "successful_judgments": len(records),
        "errors": [f"{type(error).__name__}: {error}" for error in errors],
        "records": [records[key] for key in sorted(records)],
    }
    write_json_atomic(AUDIT_ROOT / "summary.json", summary)
    if summary["status"] != "completed":
        raise RuntimeError("neutral-heldout rubric scoring is incomplete")
    return summary


def main() -> int:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("neutral-heldout audit must run on a Babel compute node")
    original = load_experiment(ORIGINAL_CONFIG)
    repaired = load_experiment(REPAIRED_CONFIG)
    neutral = neutral_scope(repaired)
    source_targets = load_four_source_targets(original, repaired)
    pool = prepare_neutral_pool(neutral)
    targets = attach_neutral_selection(source_targets)
    summary = run_scores(neutral, targets)
    completion = {
        "kind": "neutral-heldout5-da-26-4-rep002-completion",
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "pool": pool,
        "target_assignment_ids": [target.assignment_id for target in targets],
        "audit_status": summary["status"],
        "successful_judgments": summary["successful_judgments"],
    }
    write_json_atomic(RUN / "completion.json", completion)
    print(json.dumps(completion, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
