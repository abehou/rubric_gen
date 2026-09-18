"""Recover only the genuinely missing da-17-1 rep-003 native seed block."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from dotenv import dotenv_values

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.seeds import resolve_seed

from make_configs import BUNDLE, ROOT, RUN


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("seed recovery must run on a Slurm compute node")
    config = ROOT / "experiments/biomnibench-v21-to45/queue7/configs/da-17-1.yaml"
    experiment = load_experiment(config)
    seed_root = Path(experiment.dag["seed"]["output_dir"])
    valid_before = []
    missing_before = []
    for replicate in range(1, 4):
        try:
            resolve_seed(
                seed_root, experiment.task_dir("da-17-1"), replicate,
                seed_generator=experiment.seed_agent_config(),
                prompt_profile=experiment.protocol["prompt"], benchmark=experiment.benchmark,
            )
            valid_before.append(replicate)
        except Exception as error:
            missing_before.append({"replicate": replicate, "error": f"{type(error).__name__}: {error}"})
    if valid_before != [1, 2] or [row["replicate"] for row in missing_before] != [3]:
        raise RuntimeError(f"unexpected da-17-1 seed state: valid={valid_before}, missing={missing_before}")
    values = dotenv_values("/home/aydanh/repos/rubric_gen/.env.local")
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        if values.get(key):
            os.environ[key] = str(values[key])
    command = [
        "/home/aydanh/repos/rubric_gen/.venv/bin/python", "-m", "rubric_gen.cli",
        "seed", "--experiment", str(config), "--max-concurrency", "1",
    ]
    completed = subprocess.run(command, cwd=ROOT, env=os.environ.copy())
    if completed.returncode:
        raise RuntimeError(f"native da-17-1 missing-only seed recovery exited {completed.returncode}")
    rows = []
    for replicate in range(1, 4):
        seed = resolve_seed(
            seed_root, experiment.task_dir("da-17-1"), replicate,
            seed_generator=experiment.seed_agent_config(),
            prompt_profile=experiment.protocol["prompt"], benchmark=experiment.benchmark,
        )
        rows.append({"replicate": replicate, "sha256": seed.sha256})
    receipt = {
        "success": True,
        "job_id": os.environ["SLURM_JOB_ID"],
        "source_commit": subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip(),
        "task_id": "da-17-1",
        "preserved_valid_replicates": valid_before,
        "generated_replicates": [3],
        "seeds": rows,
    }
    write_json_atomic(BUNDLE / "receipts/da17-seed-recovery.json", receipt)
    RUN.mkdir(parents=True, exist_ok=True)
    write_json_atomic(RUN / "da17-seed-recovery.json", receipt)
    print(json.dumps(receipt), flush=True)


if __name__ == "__main__":
    main()
