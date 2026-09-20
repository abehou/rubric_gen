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
from rubric_gen.submission_revision.evaluation.jobs import (
    EvaluationConfig,
    EvaluationTarget,
    RubricRole,
    RubricScoreJob,
)
from rubric_gen.submission_revision.evaluation.rubric_score import RubricScoreStage
from rubric_gen.submission_revision.experiment import Experiment, load_experiment
from rubric_gen.submission_revision.judge import SCORING_IDENTITY_KEYS
from rubric_gen.submission_revision.paraphrases import (
    ParaphraseRunConfig,
    ParaphraseRunner,
)
from rubric_gen.submission_revision.paraphrase_protocol import UNIFORM_NEUTRAL
from rubric_gen.submission_revision.paraphrase_validation import (
    resolve_paraphrase_selection,
    validate_paraphrase_run,
)
from rubric_gen.submission_revision.rubric_generation import RubricPolicy
from rubric_gen.submission_revision.rubric_generation_store import (
    load_rubric_generation,
    rubric_generation_directory,
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
    sources = resolve_study_sources(study_dir, producer)
    selected_sources = tuple(
        source
        for source in sources.revisions
        if replicate is None or source.assignment.replicate == replicate
    )
    targets = []
    for source in selected_sources:
        assignment = source.assignment
        source_experiment = source.producer
        state = source.state
        submission_ids = state.get("submission_ids")
        scores = state.get("scores")
        fixed_scores = state.get("fixed_original_scores")
        if (
            state.get("phase") != "completed"
            or not isinstance(submission_ids, list)
            or not submission_ids
            or not isinstance(scores, list)
            or not isinstance(fixed_scores, list)
            or len(scores) != len(submission_ids)
            or len(fixed_scores) != len(submission_ids)
        ):
            raise RuntimeError(f"saved source state is incomplete: {source.directory}")
        final_submission = (
            source.directory / "submissions" / str(submission_ids[-1])
        ).resolve()
        initial_submission = (
            source.directory / "submissions" / str(submission_ids[0])
        ).resolve()
        if not final_submission.is_dir() or not initial_submission.is_dir():
            raise RuntimeError(f"saved source submission is missing: {source.directory}")
        rubric_policy = RubricPolicy(
            str(source_experiment.condition(assignment.condition_id)["rubric_policy"])
        )
        generation = load_rubric_generation(
            source.directory,
            0,
            expected_policy=rubric_policy,
        )
        generation_manifest = (
            rubric_generation_directory(source.directory, 0) / "manifest.json"
        ).resolve()
        selection = resolve_paraphrase_selection(
            Path(str(source_experiment.dag["paraphrase"]["output_dir"])),
            source_experiment,
            assignment.task_id,
        )
        targets.append(EvaluationTarget(
            study_experiment_id=sources.experiment.experiment_id,
            assignment_id=assignment.assignment_id,
            task_id=assignment.task_id,
            replicate=assignment.replicate,
            solver_id=assignment.solver_id,
            condition_id=assignment.condition_id,
            rubric_policy=rubric_policy,
            benchmark=source_experiment.benchmark,
            experiment_dir=source.directory.resolve(),
            task_dir=source_experiment.task_dir(assignment.task_id).resolve(),
            review=str(source_experiment.protocol["review"]),
            max_review_chars=source_experiment.protocol["max_review_chars"],
            initial_submission=initial_submission,
            final_submission=final_submission,
            submission_ids=tuple(str(value) for value in submission_ids),
            active_scores=tuple(float(value) for value in scores),
            fixed_original_scores=tuple(float(value) for value in fixed_scores),
            initial_generation=generation,
            final_generation=generation,
            initial_manifest_path=generation_manifest,
            final_manifest_path=generation_manifest,
            initial_manifest_sha256=sha256_file(generation_manifest),
            final_manifest_sha256=sha256_file(generation_manifest),
            selection=selection,
        ))
    return tuple(targets)


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


def neutral_jobs(
    stage: RubricScoreStage,
    targets: tuple[evaluation_jobs.EvaluationTarget, ...],
) -> tuple[evaluation_jobs.RubricScoreJob, ...]:
    implementation = rubric_score._evaluation_implementation_sha256()
    paths = tuple(
        NEUTRAL_POOL / "tasks/da-26-4" / f"variant-{index:03d}.txt"
        for index in range(5)
    )
    jobs_list: list[RubricScoreJob] = []
    for target in targets:
        for variant_index, path in enumerate(paths):
            for model in MODELS:
                judge = stage._new_judge(
                    target=target,
                    model=model,
                    rubric_path=path,
                    artifact_key="predispatch-identity",
                )
                grading_identity = judge.scoring_identity()
                if set(grading_identity) != set(SCORING_IDENTITY_KEYS):
                    raise RuntimeError("neutral-heldout grading identity changed")
                review_sha256, answer_sha256 = stage._request_hashes(
                    judge,
                    target.final_submission,
                )
                jobs_list.append(RubricScoreJob(
                    target=target,
                    model=model,
                    artifact="final",
                    rubric_path=path,
                    roles=(RubricRole("holdout", variant_index),),
                    generation_bindings=(),
                    grading_identity=grading_identity,
                    review_input_sha256=review_sha256,
                    answer_input_sha256=answer_sha256,
                    evaluation_implementation_sha256=implementation,
                ))
    jobs = tuple(jobs_list)
    expected = len(targets) * 5 * len(MODELS)
    if len(jobs) != expected:
        raise RuntimeError(
            f"expected {expected} neutral-heldout judgments, found {len(jobs)}"
        )
    if any(
        len(job.roles) != 1
        or job.roles[0].name != "holdout"
        or job.roles[0].variant_index not in range(5)
        or job.artifact != "final"
        for job in jobs
    ):
        raise RuntimeError("neutral-heldout job scope contains another rubric or artifact")
    if len({job.key for job in jobs}) != expected:
        raise RuntimeError("neutral-heldout jobs are not unique")
    return jobs


def run_scores(
    experiment: Experiment,
    targets: tuple[evaluation_jobs.EvaluationTarget, ...],
    *,
    audit_root: Path = AUDIT_ROOT,
    run_kind: str = "neutral-heldout5-final-rubric-score-only",
) -> dict[str, object]:
    config = EvaluationConfig(
        experiment=experiment,
        study_dir=RUN / "four-read-only-source-studies",
        paraphrase_dir=NEUTRAL_POOL,
        output_dir=audit_root,
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
        "kind": run_kind,
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
    audit_root.mkdir(parents=True, exist_ok=True)
    write_json_atomic(audit_root / "launch.json", launch)
    records: dict[str, dict[str, object]] = {}
    errors: list[BaseException] = []
    with audit_output_owner(audit_root), reservation("audit"), AuditExecutor(
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
        "status": (
            "completed" if not errors and len(records) == len(jobs) else "incomplete"
        ),
        "successful_judgments": len(records),
        "errors": [f"{type(error).__name__}: {error}" for error in errors],
        "records": [records[key] for key in sorted(records)],
    }
    write_json_atomic(audit_root / "summary.json", summary)
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
    summary = run_scores(neutral, source_targets)
    completion = {
        "kind": "neutral-heldout5-da-26-4-rep002-completion",
        "finished_at": datetime.now(timezone.utc).isoformat(),
        "pool": pool,
        "target_assignment_ids": [target.assignment_id for target in source_targets],
        "audit_status": summary["status"],
        "successful_judgments": summary["successful_judgments"],
    }
    write_json_atomic(RUN / "completion.json", completion)
    print(json.dumps(completion, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
