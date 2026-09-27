"""Run the revised HealthBench Hard Dev3 after explicit budget approval."""

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import subprocess
import sys

from dotenv import dotenv_values

ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path(__file__).with_name("dev3-v3.yaml")
RUNTIME = Path(__file__).with_name("runtime.json")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--expected-key-suffix", required=True)
    parser.add_argument("--experiment", type=Path, default=CONFIG)
    args = parser.parse_args()
    key = dotenv_values(ROOT / ".env.local").get("OPENAI_API_KEY")
    if not key or key.startswith("sk-ant-") or not key.endswith(args.expected_key_suffix):
        raise SystemExit("OPENAI_API_KEY is missing, belongs to Anthropic, or does not match the confirmed suffix.")

    sys.path.insert(0, str(ROOT / "src"))
    from rubric_gen.runtime.process_environment import controlled_process_environment
    from rubric_gen.submission_revision.experiment import load_experiment

    config = args.experiment.resolve()
    experiment = load_experiment(config)
    output = Path(experiment.payload["dag"]["seed"]["output_dir"]).parent
    env = controlled_process_environment()
    for name in list(env):
        if "API_KEY" in name or name in {
            "CODEX_ACCESS_TOKEN", "OPENAI_BASE_URL", "OPENAI_API_BASE",
            "OPENAI_ORG_ID", "OPENAI_PROJECT_ID",
        }:
            env.pop(name)
    env.update(
        OPENAI_API_KEY=key,
        CODEX_API_KEY=key,
        OPENAI_BASE_URL="https://api.openai.com/v1",
        PYTHONPATH=str(ROOT / "src"),
        RUBRIC_GEN_RUNTIME_CONFIG=str(RUNTIME),
    )
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    invocation = output / "invocations" / stamp
    invocation.mkdir(parents=True, exist_ok=False)
    (invocation / "source.diff").write_bytes(subprocess.check_output(
        ["git", "diff", "--binary", "HEAD"], cwd=ROOT, env=env
    ))
    (invocation / "experiment.yaml").write_text(config.read_text())
    (invocation / "launcher.py").write_text(Path(__file__).read_text())
    receipt = {
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, env=env, text=True
        ).strip(),
        "source_status": subprocess.check_output(
            ["git", "status", "--short"], cwd=ROOT, env=env, text=True
        ).splitlines(),
        "experiment_id": experiment.experiment_id,
        "config": str(config),
        "pid": os.getpid(),
        "started_utc": stamp,
        "key_suffix": args.expected_key_suffix,
        "assignment_count": len(experiment.assignments),
        "assignment_workers": 6,
        "outer_queues": 1,
        "aggregate_concurrency": 12,
        "internal_fanout": 4,
        "audit_concurrency": 12,
        "host_cpu_count": os.cpu_count(),
        "host_memory_gib": 24,
        "resource_reservation": "local process, no scheduler reservation",
        "expected_wall_minutes": [20, 40],
        "stages": [],
    }
    for stage, extra, workers, effort in [
        ("seed", [], 6, "low"),
        ("paraphrase", [], 6, "low"),
        ("revise", ["--assignment-workers", "6"], 12, "low"),
        ("detect", ["--study-dir", str(output / "studies" / experiment.experiment_id)], 12, "high"),
    ]:
        command = [
            sys.executable, "-m", "rubric_gen.cli", stage,
            "--experiment", str(config), "--max-concurrency", str(workers),
            *extra,
        ]
        if stage in {"revise", "detect"}:
            command.append("--resume")
        record = {"stage": stage, "command": command, "reasoning_effort": effort, "status": "running"}
        receipt["stages"].append(record)
        (invocation / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        print(f"{stage}: {invocation / (stage + '.log')}", flush=True)
        with (invocation / f"{stage}.log").open("w") as log:
            result = subprocess.run(
                command,
                cwd=ROOT,
                env={**env, "RUBRIC_GEN_OPENAI_REASONING_EFFORT": effort},
                stdout=log,
                stderr=subprocess.STDOUT,
            )
        record.update(status="completed" if result.returncode == 0 else "failed", exit_code=result.returncode)
        (invocation / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        if result.returncode:
            raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
