"""Provider-free validation for the frozen five-task improvement pilot."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import subprocess

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run
from rubric_gen.submission_revision.pretreatment_reuse import source_pool
from rubric_gen.submission_revision.seeds import resolve_seed
from rubric_gen.submission_revision.task_paraphrase_required import INTERNAL_STAGE_FANOUT

from make_configs import (
    BUNDLE, CANDIDATE, CONDITIONS, PANEL, ROOT, RUN, STAGE_EFFORTS,
    TASKS, config_path,
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def validate_task(task: str) -> dict[str, object]:
    path = config_path(task)
    experiment = load_experiment(path)
    if experiment.task_ids != (task,) or experiment.replicates != 3:
        raise RuntimeError(f"task/replicate scope changed: {task}")
    if tuple(experiment.execution_conditions) != CONDITIONS:
        raise RuntimeError(f"condition scope changed: {task}")
    if len(experiment.execution_assignments) != 6:
        raise RuntimeError(f"assignment scope changed: {task}")
    if tuple(experiment.outcome_audit["models"]) != PANEL:
        raise RuntimeError(f"audit panel changed: {task}")
    if tuple(experiment.payload["execution_audit_models"]) != PANEL:
        raise RuntimeError(f"execution audit panel changed: {task}")
    protocol = experiment.protocol
    if protocol["red_team_trace_version"] != CANDIDATE:
        raise RuntimeError(f"candidate recipe changed: {task}")
    if protocol["rubric_proposer_reasoning_effort_by_stage"] != STAGE_EFFORTS:
        raise RuntimeError(f"stage reasoning allocation changed: {task}")
    if protocol["min_revisions"] != 5 or protocol["max_revisions"] != 10:
        raise RuntimeError(f"revision budget changed: {task}")
    if (
        experiment.red_team_agent_config().reasoning_effort != "low"
        or any(
            experiment.solver_config(solver).reasoning_effort != "low"
            for solver in experiment.solver_ids
        )
    ):
        raise RuntimeError(f"solver/red-team control changed: {task}")
    seed_root = Path(experiment.dag["seed"]["output_dir"])
    paraphrase_root = Path(experiment.dag["paraphrase"]["output_dir"])
    validate_paraphrase_run(paraphrase_root, experiment)
    seeds = []
    for replicate in range(1, 4):
        seed = resolve_seed(
            seed_root,
            experiment.task_dir(task),
            replicate,
            seed_generator=experiment.seed_agent_config(),
            prompt_profile=protocol["prompt"],
            benchmark=experiment.benchmark,
        )
        seeds.append({"replicate": replicate, "sha256": seed.sha256})
    pool = source_pool(experiment)
    if pool is None:
        raise RuntimeError(f"pretreatment source was not reused: {task}")
    return {
        "task_id": task,
        "config": str(path),
        "config_sha256": sha(path),
        "experiment_id": experiment.experiment_id,
        "seed_root": str(seed_root),
        "seeds": seeds,
        "paraphrase_root": str(paraphrase_root),
        "pretreatment_pool": str(pool),
        "pretreatment_files": sum(1 for item in pool.rglob("*") if item.is_file()),
    }


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("pilot preflight requires a Slurm compute node")
    dirty = subprocess.check_output(
        ["git", "status", "--porcelain"], cwd=ROOT, text=True
    )
    if dirty.strip():
        raise RuntimeError("pilot source must be a clean commit")
    runtime = policy()
    if runtime["aggregate_concurrency"] != 60 or runtime["audit_studies"] != 3:
        raise RuntimeError("shared runtime policy changed")
    if INTERNAL_STAGE_FANOUT != 4:
        raise RuntimeError("internal stage fanout changed")
    with ThreadPoolExecutor(max_workers=5) as executor:
        rows = list(executor.map(validate_task, TASKS))
    if sum(len(load_experiment(config_path(task)).execution_assignments) for task in TASKS) != 30:
        raise RuntimeError("pilot assignment scope is not 30")
    for root in (
        RUN,
        Path("/data/user_data/aydanh/rubric_gen/live/rtt-result40-gap-improvement-pilot-20260921"),
        Path("/data/user_data/aydanh/rubric_gen/cache/rtt-result40-gap-improvement-pilot-20260921"),
    ):
        root.mkdir(parents=True, exist_ok=True)
        probe = root / f".write-probe-{os.environ['SLURM_JOB_ID']}"
        probe.write_text("ok\n")
        probe.unlink()
    receipt = {
        "success": True,
        "provider_calls": 0,
        "job_id": os.environ["SLURM_JOB_ID"],
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "tasks": list(TASKS),
        "conditions": list(CONDITIONS),
        "assignments": 30,
        "solver_reasoning_effort": "low",
        "red_team_reasoning_effort": "low",
        "rubric_learning_high_stages": sorted(STAGE_EFFORTS),
        "panel": list(PANEL),
        "rows": rows,
        "runtime": runtime,
    }
    (BUNDLE / "receipts").mkdir(exist_ok=True)
    write_json_atomic(BUNDLE / "receipts/input-validation.json", receipt)
    write_json_atomic(RUN / "input-validation.json", receipt)
    print(json.dumps(receipt, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
