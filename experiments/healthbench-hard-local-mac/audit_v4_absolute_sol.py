"""All-case, absolute-only Sol sensitivity audit of the completed v4 answers."""

from concurrent.futures import as_completed
from dataclasses import replace
from datetime import datetime, timezone
import os
from pathlib import Path
import json
import subprocess

from dotenv import dotenv_values

from rubric_gen.runtime.process_environment import install_controlled_process_environment

install_controlled_process_environment()

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.runtime.audit_execution import AuditExecutor, audit_owner
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.source_resolution import resolve_study_sources
from rubric_gen.submission_revision.evaluation import absolute_score
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.targets import load_evaluation_targets
from rubric_gen.submission_revision.evaluation.runner import RubricFreeScoreRunner
from rubric_gen.submission_revision.evaluation.resume import prepare_stage_output


def main():
    here = Path(__file__).resolve().parent
    root = here.parents[1]
    key = dotenv_values(root / ".env.local").get("OPENAI_API_KEY")
    if not key or not key.endswith("IfoA") or key.startswith("sk-ant-"):
        raise RuntimeError("Expected confirmed OpenAI credential is unavailable")
    for name in list(os.environ):
        if "API_KEY" in name or name in {
            "CODEX_ACCESS_TOKEN", "OPENAI_BASE_URL", "OPENAI_API_BASE",
            "OPENAI_ORG_ID", "OPENAI_PROJECT_ID",
        }:
            os.environ.pop(name)
    os.environ.update(
        OPENAI_API_KEY=key,
        OPENAI_BASE_URL="https://api.openai.com/v1",
        RUBRIC_GEN_OPENAI_REASONING_EFFORT="high",
        RUBRIC_GEN_RUNTIME_CONFIG=str(here / "runtime.json"),
    )
    experiment = load_experiment(here / "dev3-v4.yaml")
    run = Path(experiment.dag["seed"]["output_dir"]).parent
    config = EvaluationConfig(
        experiment=experiment,
        study_dir=run / "studies" / experiment.experiment_id,
        paraphrase_dir=run / "paraphrases",
        output_dir=run / "absolute-sol",
        max_concurrency=12,
        resume=True,
    )
    with audit_owner(config.output_dir):
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        invocation = config.output_dir / "invocations" / stamp
        invocation.mkdir(parents=True, exist_ok=False)
        (invocation / "source.diff").write_bytes(subprocess.check_output(
            ["git", "diff", "--binary", "HEAD"], cwd=root,
        ))
        (invocation / "experiment.yaml").write_text(experiment.path.read_text())
        (invocation / "launcher.py").write_text(Path(__file__).read_text())
        receipt = {
            "source_commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=root, text=True,
            ).strip(),
            "experiment_id": experiment.experiment_id,
            "pid": os.getpid(), "started_utc": stamp, "status": "running",
            "model": "gpt-6-sol", "reasoning_effort": "high",
            "key_suffix": "IfoA", "outer_queues": 1, "assignment_workers": 0,
            "aggregate_concurrency": 12, "internal_fanout": 1,
            "audit_concurrency": 12, "host_cpu_count": os.cpu_count(),
            "host_memory_gib": 24, "expected_wall_minutes": [1, 5],
            "resource_reservation": "local process, no scheduler reservation",
            "output_dir": str(config.output_dir),
        }
        (invocation / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        sources = resolve_study_sources(config.study_dir, experiment)
        targets = load_evaluation_targets(config, sources)
        stage = RubricFreeScoreRunner(config, targets)
        stage.preflight()
        original = stage._prepared
        jobs = tuple(replace(job, model="gpt-6-sol") for job in original.absolute_jobs)
        unique = tuple({job.key: job for job in jobs}.values())
        prepared = replace(
            original, models=("gpt-6-sol",), absolute_jobs=jobs,
            unique_absolute_jobs=unique, pairwise_jobs=(), unique_pairwise_jobs=(),
            predispatch_plan=stage._predispatch_plan(unique, ()),
        )
        stage._prepared = prepared
        manifest = stage._manifests(prepared)["absolute"]
        manifest["supplemental_audit"] = {
            "scope": "all initial and final answers, absolute score only",
            "reason": "near-identical answers received a nine-point Luna A discrepancy",
            "model_override": "gpt-6-sol", "reasoning_effort": "high",
            "primary_experiment_unchanged": True,
        }
        prepare_stage_output(stage.absolute_output, manifest, True)
        print(f"Auditing {len(unique)} unique answers / {len(jobs)} references", flush=True)
        judgments = {}
        with AuditExecutor(12, prepared.models) as executor:
            futures = {executor.submit(stage._run_absolute_job, job): job for job in unique}
            for future in as_completed(futures):
                job = futures[future]
                judgments[job.key] = future.result()
                print(f"Completed {len(judgments)}/{len(unique)}", flush=True)
        records = [absolute_score.assignment_reference(job, judgments[job.key]) for job in jobs]
        summary = {
            **manifest, "status": "completed", "missing_models": [],
            "completed_utc": datetime.now(timezone.utc).isoformat(),
            "planned_semantic_judgment_count": len(unique),
            "successful_semantic_judgment_count": len(judgments),
            "used_semantic_judgment_count": len(judgments),
            "failed_semantic_judgment_count": 0, "judge_failures": [],
            "assignment_reference_count": len(records), "records": records,
            "completed_record_sha256s": {
                key: sha256_file(stage.absolute_output.regular_file("records", f"{key}.json"))
                for key in sorted(judgments)
            },
            "assignments": absolute_score.summarize(targets, records, prepared.models),
        }
        stage.absolute_output.write_json(("summary.json",), summary)
        receipt.update(status="completed", completed_utc=summary["completed_utc"],
                       completed_unique_judgments=len(judgments))
        (invocation / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(stage.absolute_output.root / "summary.json", flush=True)


if __name__ == "__main__":
    main()
