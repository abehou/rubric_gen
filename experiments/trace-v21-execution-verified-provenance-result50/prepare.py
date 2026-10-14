"""Prepare only missing Result50 inputs and validate the frozen extension."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess

from huggingface_hub import snapshot_download

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run
from rubric_gen.submission_revision.pretreatment_reuse import source_pool
from rubric_gen.submission_revision.seeds import resolve_seed
from rubric_gen.submission_revision.task_paraphrase_required import INTERNAL_STAGE_FANOUT

from make_configs import (
    BUNDLE, CANDIDATE, CONDITIONS, EXECUTION_BUNDLE, GENERATED_INPUT_TASKS,
    PANEL, ROOT, RUN, SHARDS, SUPPLEMENT_DATA, TASKS, config_path,
    input_roots, main as make_configs, task_root,
)


REVISION = "e1c8ca5e11a620087bc48d97888eb69176a1f235"
UV = Path("/home/aydanh/tools/uv/uv")
PYTHON = Path("/home/aydanh/repos/rubric_gen/.venv/bin/python")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _environment() -> dict[str, str]:
    value = dict(os.environ)
    value.update({
        "PYTHONPATH": str(ROOT / "src"),
        "UV_PROJECT_ENVIRONMENT": str(PYTHON.parent.parent),
    })
    return value


def _download_supplement() -> None:
    token = os.environ.get("HF_TOKEN")
    if not token:
        raise RuntimeError("Hugging Face token is unavailable")
    SUPPLEMENT_DATA.mkdir(parents=True, exist_ok=True)
    snapshot_download(
        repo_id="phylobio/BiomniBench-DA",
        repo_type="dataset",
        revision=REVISION,
        local_dir=SUPPLEMENT_DATA,
        allow_patterns=[f"{task}/**" for task in GENERATED_INPUT_TASKS],
        token=token,
    )
    for task in GENERATED_INPUT_TASKS:
        for relative in ("instruction.md", "tests/rubric.txt", "environment/data"):
            path = SUPPLEMENT_DATA / task / relative
            if not path.exists() or path.is_symlink():
                raise RuntimeError(f"downloaded Result50 task input is missing: {path}")


def _stage(task: str, stage: str) -> None:
    command = [
        str(UV), "run", "--no-sync", "rubric-gen", stage,
        "--experiment", str(config_path(task, "static")),
        "--max-concurrency", "12",
    ]
    completed = subprocess.run(command, cwd=ROOT, env=_environment())
    if completed.returncode:
        raise RuntimeError(f"{task} {stage} failed with {completed.returncode}")


def _prepare_task(task: str) -> None:
    _stage(task, "seed")
    _stage(task, "paraphrase")


def _validate(task: str, kind: str) -> dict[str, object]:
    config = config_path(task, kind)
    experiment = load_experiment(config)
    expected_conditions = (
        ("full-static", "user-simulator-static")
        if kind == "static"
        else (
            "full-red-team-trace-execution-verified-proactive-provenance",
            "user-simulator-red-team-trace-execution-verified-proactive-provenance",
        )
    )
    if experiment.task_ids != (task,) or tuple(experiment.execution_conditions) != expected_conditions:
        raise RuntimeError(f"Result50 scope mismatch: {task}/{kind}")
    if len(experiment.execution_assignments) != 6:
        raise RuntimeError(f"Result50 assignment count mismatch: {task}/{kind}")
    if tuple(experiment.outcome_audit["models"]) != PANEL:
        raise RuntimeError(f"Result50 audit panel mismatch: {task}/{kind}")
    if experiment.payload["randomization"] != {"seed": 20260820, "replicates": 3}:
        raise RuntimeError(f"Result50 randomization mismatch: {task}/{kind}")
    if experiment.payload["rubric_paraphrases"]["count"] != 5:
        raise RuntimeError(f"Result50 paraphrase count mismatch: {task}/{kind}")
    if kind == "trace":
        if experiment.protocol["red_team_trace_version"] != CANDIDATE:
            raise RuntimeError(f"Result50 RTT identity mismatch: {task}")
        if experiment.protocol["rubric_proposer_reasoning_effort_by_stage"] != {"diagnosis": "high"}:
            raise RuntimeError(f"Result50 proposer allocation mismatch: {task}")
    seed_root, paraphrase_root = input_roots(task)
    validate_paraphrase_run(paraphrase_root, experiment)
    seeds = [
        resolve_seed(
            seed_root,
            experiment.task_dir(task),
            replicate,
            seed_generator=experiment.seed_agent_config(),
            prompt_profile=experiment.protocol["prompt"],
            benchmark=experiment.benchmark,
        ).sha256
        for replicate in range(1, 4)
    ]
    pool = source_pool(experiment)
    return {
        "task": task,
        "kind": kind,
        "config": str(config),
        "config_sha256": sha(config),
        "experiment_id": experiment.experiment_id,
        "task_root": str(task_root(task)),
        "seed_root": str(seed_root),
        "seed_sha256": seeds,
        "paraphrase_root": str(paraphrase_root),
        "pretreatment_source": str(pool) if pool else None,
    }


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Result50 setup must run on a Babel compute node")
    if not os.environ.get("HF_TOKEN"):
        token = Path("/home/aydanh/.cache/huggingface/token")
        if token.is_file():
            os.environ["HF_TOKEN"] = token.read_text().strip()
    _download_supplement()
    make_configs()
    with ThreadPoolExecutor(max_workers=5) as workers:
        list(workers.map(_prepare_task, GENERATED_INPUT_TASKS))
    rows = [_validate(task, kind) for task, kind in SHARDS]
    runtime = policy()
    if runtime["aggregate_concurrency"] != 60 or INTERNAL_STAGE_FANOUT != 4:
        raise RuntimeError("Result50 runtime profile mismatch")
    receipt = {
        "success": True,
        "provider_calls": "missing seed/paraphrase inputs only",
        "job_id": os.environ["SLURM_JOB_ID"],
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "upstream_dataset_revision": REVISION,
        "tasks": list(TASKS),
        "conditions": list(CONDITIONS),
        "assignment_count": 120,
        "heldout_generation": "selected/development neutral; heldouts rigorous-V2",
        "input_rows": rows,
        "runtime": runtime,
    }
    write_json_atomic(EXECUTION_BUNDLE / "input-validation.json", receipt)
    write_json_atomic(RUN / "input-validation.json", receipt)
    print(json.dumps({"success": True, "tasks": 10, "assignments": 120}))


if __name__ == "__main__":
    main()
