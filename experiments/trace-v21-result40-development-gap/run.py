"""Score Result40 final artifacts with the frozen development rubric only.

This is an evaluation-only diagnostic.  It neither revises artifacts nor changes
the completed Result40 audit.  Each final artifact receives one score per model
under rubric variant 1, allowing S-H = (S-D) + (D-H) to be measured directly.
"""
from __future__ import annotations

import argparse
from concurrent.futures import as_completed
from contextlib import nullcontext
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

from dotenv import dotenv_values


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
RESULT40_BUNDLE = ROOT / "experiments/trace-v21-execution-verified-provenance-result40"
sys.path.insert(0, str(RESULT40_BUNDLE))

from audit_scope import config_path, scoped_experiment  # noqa: E402

from rubric_gen.artifacts.hashing import sha256_file  # noqa: E402
from rubric_gen.artifacts.serialization import write_json_atomic  # noqa: E402
from rubric_gen.runtime.audit_execution import (  # noqa: E402
    AuditExecutor,
    audit_output_owner,
)
from rubric_gen.runtime.capacity import policy, reservation  # noqa: E402
from rubric_gen.submission_revision.evaluation import (  # noqa: E402
    jobs as evaluation_jobs,
    rubric_score,
)
from rubric_gen.submission_revision.evaluation.jobs import (  # noqa: E402
    EvaluationConfig,
    RubricRole,
)
from rubric_gen.submission_revision.evaluation.rubric_score import (  # noqa: E402
    RubricScoreStage,
    _GroupedRubrics,
)
from rubric_gen.submission_revision.evaluation.resume import (  # noqa: E402
    prepare_stage_output,
)
from rubric_gen.submission_revision.evaluation.runner import (  # noqa: E402
    PANEL_POLICY,
    _failure_record,
    _is_judge_failure,
)
from rubric_gen.submission_revision.evaluation.targets import (  # noqa: E402
    load_evaluation_targets,
)
from rubric_gen.submission_revision.source_resolution import (  # noqa: E402
    resolve_study_sources,
)


TASKS = ("da-26-4", "da-26-2", "da-17-1", "da-17-5", "da-20-4")
KINDS = ("static", "trace")
MODELS = ("gpt-5.6-sol", "gemini-3.8-flash")
CONDITIONS = {
    "static": (
        "full-static",
        "user-simulator-static",
    ),
    "trace": (
        "full-red-team-trace-execution-verified-proactive-provenance",
        "user-simulator-red-team-trace-execution-verified-proactive-provenance",
    ),
}
RUN = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-result40-development-score-pilot-20260921"
)
MAX_CONCURRENCY = 12


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def credentials() -> None:
    values = dotenv_values("/home/aydanh/repos/rubric_gen/.env.local")
    for key in ("OPENAI_API_KEY", "GEMINI_API_KEY"):
        value = values.get(key)
        if not value:
            raise RuntimeError(f"configured credential unavailable: {key}")
        os.environ[key] = str(value)


def clean_commit() -> str:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    )
    if dirty.strip():
        raise RuntimeError("development-score diagnostic worktree is not clean")
    return commit


class DevelopmentScoreStage(RubricScoreStage):
    """Use the native scoring request, restricted to final × development."""

    @staticmethod
    def _grouped_rubrics(target, artifact, models):
        if artifact != "final":
            raise ValueError("development diagnostic only scores final artifacts")
        selection = target.selection
        if (
            selection.development_index != 1
            or selection.development_path.stem != "variant-001"
        ):
            raise RuntimeError("development diagnostic requires rubric variant 1")
        if sha256_file(selection.development_path) != selection.development_sha256:
            raise RuntimeError("evaluation development rubric changed")
        grouped = _GroupedRubrics()
        role = RubricRole("development", selection.development_index)
        for model in models:
            grouped.include(selection.development_path, model, role=role)
        return grouped

    def _jobs(self, targets):
        models = tuple(
            str(model) for model in self.config.experiment.outcome_audit["models"]
        )
        implementation_sha256 = evaluation_jobs._evaluation_implementation_sha256()
        request_hashes = {}
        return tuple(
            job
            for target in targets
            for job in self._artifact_jobs(
                target,
                "final",
                models,
                implementation_sha256,
                request_hashes,
            )
        )

    def run_prepared(self, executor: AuditExecutor) -> int:
        prepared = self._prepared
        if prepared is None:
            raise RuntimeError("development score preflight did not produce a plan")
        models = tuple(
            str(model) for model in self.config.experiment.outcome_audit["models"]
        )
        manifest = {
            "kind": "rubric-gen-development-score-evaluation",
            "experiment_id": self.config.experiment.experiment_id,
            "study_experiment_id": prepared.targets[0].study_experiment_id,
            "study_dir": str(self.config.study_dir.resolve()),
            "paraphrase_dir": str(self.config.paraphrase_dir.resolve()),
            "models": list(models),
            "artifact": "final",
            "rubric_role": "development",
            "assignment_count": len(prepared.targets),
            "planned_semantic_judgment_count": len(prepared.unique_jobs),
            "implementation_identity": (
                evaluation_jobs._rubric_score_implementation_identity(
                    prepared.unique_jobs
                )
            ),
            "assignment_reference_identity_sha256": (
                rubric_score._rubric_score_assignment_reference_sha256(
                    prepared.jobs
                )
            ),
            "predispatch_plan": prepared.predispatch_plan,
        }
        prepare_stage_output(
            self.output,
            manifest,
            self.config.resume,
            prepared.jobs,
        )
        prior_timings = {}
        prior_summary_path = self.output.path("summary.json")
        if self.config.resume and prior_summary_path.exists():
            prior_summary = read_json_object(
                prior_summary_path, "saved development-score summary"
            )
            prior_timings = {
                str(row["judgment_key"]): row
                for row in prior_summary.get("timings", ())
                if isinstance(row, dict) and row.get("judgment_key")
            }
        judgments = {}
        failures = {}
        fatal = []
        timings = {}

        def timed_job(job):
            started = time.monotonic()
            reused = job.key in getattr(self, "_reused_records", {})
            result = self._run_job(job)
            return result, time.monotonic() - started, reused

        futures = {
            executor.submit(timed_job, job, model=job.model): job
            for job in prepared.unique_jobs
        }
        for future in as_completed(futures):
            job = futures[future]
            try:
                judgment, elapsed, reused = future.result()
                judgments[job.key] = judgment
                timings[job.key] = (
                    prior_timings[job.key]
                    if reused and job.key in prior_timings
                    else {
                        "judgment_key": job.key,
                        "model": job.model,
                        "elapsed_seconds": elapsed,
                        "reused_before_dispatch": reused,
                    }
                )
            except Exception as error:
                if _is_judge_failure(
                    error, "rubric-score rubric judge failed after "
                ):
                    failures[job.key] = _failure_record(
                        key=job.key, model=job.model, error=error
                    )
                else:
                    fatal.append(error)
        if fatal:
            raise RuntimeError("development score non-panel job failed") from fatal[0]

        missing_models = tuple(
            model
            for model in models
            if any(
                job.key not in judgments
                for job in prepared.unique_jobs
                if job.model == model
            )
        )
        records = [
            {
                **rubric_score._rubric_score_job_identity(job),
                "judgment_key": job.key,
                "score": judgments[job.key]["score"],
                "attempt_id": judgments[job.key]["attempt_id"],
                "validation_path": judgments[job.key]["validation_path"],
                "evaluation_path": judgments[job.key]["evaluation_path"],
            }
            for job in prepared.jobs
            if job.key in judgments
        ]
        records.sort(
            key=lambda row: (
                str(row["task_id"]),
                int(row["replicate"]),
                str(row["condition_id"]),
                str(row["model"]),
            )
        )
        by_assignment = {}
        for row in records:
            by_assignment.setdefault(str(row["assignment_id"]), {})[
                str(row["model"])
            ] = float(row["score"])
        assignments = []
        for target in prepared.targets:
            scores = by_assignment.get(target.assignment_id, {})
            assignments.append({
                "assignment_id": target.assignment_id,
                "task_id": target.task_id,
                "replicate": target.replicate,
                "solver_id": target.solver_id,
                "condition_id": target.condition_id,
                "scores": scores,
                "mean": (
                    sum(scores.values()) / len(models)
                    if set(scores) == set(models)
                    else None
                ),
            })
        summary = {
            **manifest,
            "status": "incomplete" if missing_models else "completed",
            "panel_policy": PANEL_POLICY,
            "missing_models": list(missing_models),
            "successful_semantic_judgment_count": len(judgments),
            "failed_semantic_judgment_count": len(failures),
            "used_semantic_judgment_count": len(judgments),
            "assignment_reference_count": len(records),
            "judge_failures": sorted(
                failures.values(), key=lambda row: (row["model"], row["judgment_key"])
            ),
            "timings": sorted(
                timings.values(), key=lambda row: (row["model"], row["judgment_key"])
            ),
            "records": records,
            "assignments": assignments,
        }
        self.output.write_json(("summary.json",), summary)
        return 1 if missing_models else 0


def make_stage(task: str, kind: str) -> DevelopmentScoreStage:
    output_dir = RUN / "scores" / task / kind
    experiment = scoped_experiment(
        config_path(task, kind),
        models=MODELS,
        output_dir=output_dir,
    )
    config = EvaluationConfig(
        experiment=experiment,
        study_dir=Path(experiment.dag["revise"]["output_dir"]),
        paraphrase_dir=Path(experiment.dag["paraphrase"]["output_dir"]),
        output_dir=output_dir,
        max_concurrency=MAX_CONCURRENCY,
        resume=True,
    )
    sources = resolve_study_sources(config.study_dir, experiment)
    targets = load_evaluation_targets(config, sources)
    stage = DevelopmentScoreStage(config, targets)
    stage.preflight()
    expected_assignments = {
        (task, replicate, condition)
        for replicate in (1, 2, 3)
        for condition in CONDITIONS[kind]
    }
    observed_assignments = {
        (target.task_id, target.replicate, target.condition_id)
        for target in targets
    }
    prepared = stage._prepared
    if (
        tuple(experiment.outcome_audit["models"]) != MODELS
        or observed_assignments != expected_assignments
        or prepared is None
        or len(prepared.unique_jobs) != 12
        or any(job.artifact != "final" for job in prepared.unique_jobs)
        or any(
            [(role.name, role.variant_index) for role in job.roles]
            != [("development", 1)]
            for job in prepared.unique_jobs
        )
    ):
        raise RuntimeError(f"unexpected diagnostic scope for {task}/{kind}")
    return stage


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--preflight-only", action="store_true")
    args = parser.parse_args()
    commit = clean_commit()
    capacity = policy()
    stages = [
        (task, kind, make_stage(task, kind))
        for task in TASKS
        for kind in KINDS
    ]
    saved_before = sum(
        len(getattr(stage, "_reused_records", {}))
        for _, _, stage in stages
    )
    if args.preflight_only:
        print(json.dumps({
            "status": "preflight-completed",
            "source_commit": commit,
            "tasks": list(TASKS),
            "scope_count": len(stages),
            "assignment_count": 60,
            "judgment_count": 120,
            "saved_semantic_judgment_count": saved_before,
            "missing_semantic_judgment_count": 120 - saved_before,
            "models": list(MODELS),
            "revision_calls": 0,
        }, indent=2))
        return 0

    credentials()
    RUN.mkdir(parents=True, exist_ok=True)
    receipt = {
        "status": "running",
        "started_at": now(),
        "source_commit": commit,
        "host": socket.gethostname(),
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "slurm_cpus_per_task": os.environ.get("SLURM_CPUS_PER_TASK"),
        "slurm_mem_per_node": os.environ.get("SLURM_MEM_PER_NODE"),
        "tasks": list(TASKS),
        "kinds": list(KINDS),
        "models": list(MODELS),
        "assignment_count": 60,
        "judgment_count": 120,
        "saved_semantic_judgment_count": saved_before,
        "missing_semantic_judgment_count": 120 - saved_before,
        "max_concurrency": MAX_CONCURRENCY,
        "evaluation_only": True,
        "revision_calls": 0,
        "runtime": deepcopy(capacity),
        "output_root": str(RUN),
    }
    owner = RUN / "owners" / str(
        receipt["slurm_job_id"] or f"manual-{socket.gethostname()}"
    )
    owner.mkdir(parents=True, exist_ok=True)
    write_json_atomic(RUN / "launch.json", receipt)
    write_json_atomic(owner / "launch.json", receipt)
    results = []
    exit_code = 0
    with audit_output_owner(RUN), reservation("audit"):
        with AuditExecutor(MAX_CONCURRENCY, MODELS) as executor:
            for task, kind, stage in stages:
                code = stage.run_prepared(executor)
                results.append({
                    "task_id": task,
                    "kind": kind,
                    "exit_code": code,
                    "output_dir": str(stage.config.output_dir),
                })
                exit_code = max(exit_code, code)
    receipt.update({
        "status": "completed" if exit_code == 0 else "incomplete",
        "finished_at": now(),
        "scopes": results,
    })
    write_json_atomic(RUN / "completion.json", receipt)
    write_json_atomic(owner / "completion.json", receipt)
    print(json.dumps(receipt, indent=2))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
