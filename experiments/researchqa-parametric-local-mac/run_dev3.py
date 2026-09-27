"""Run the ResearchQA four-condition Dev3 through the existing local budget relay."""
from datetime import datetime, timezone
import fcntl
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import tarfile

from dotenv import dotenv_values
from rubric_gen.runtime.process_environment import controlled_process_environment
from rubric_gen.submission_revision.experiment import load_experiment

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
sys.path.insert(0, str(HERE.parent / "healthbench-hard-result20"))
from budget_proxy import Ledger, start_proxy

CONFIG = HERE / "dev3-factorial.yaml"
RUNTIME = HERE / "runtime.json"
OUTPUT = ROOT / "runs/researchqa-parametric-dev3-20260927"
BUDGET_USD = 8.0
PORT = 18766


def main() -> None:
    experiment = load_experiment(CONFIG)
    if len(experiment.assignments) != 36 or experiment.outcome_audit["models"] != ["gpt-6-luna"]:
        raise RuntimeError("ResearchQA Dev3 scope changed; review the launcher")
    if Path(experiment.dag["seed"]["output_dir"]).parent != OUTPUT:
        raise RuntimeError("ResearchQA output root changed; review the launcher")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with (OUTPUT / ".run.lock").open("a") as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        key = dotenv_values(ROOT / ".env.local").get("OPENAI_API_KEY")
        if not key or key.startswith("sk-ant-") or not key.endswith("IfoA"):
            raise RuntimeError("Confirmed local OpenAI credential unavailable")
        ledger = Ledger(OUTPUT / "budget.json", BUDGET_USD)
        worker_key = "sk-local-budget-" + secrets.token_hex(24)
        env = controlled_process_environment()
        for name in list(env):
            if any(term in name for term in ("API_KEY", "ACCESS_TOKEN")) or name in (
                "OPENAI_BASE_URL", "OPENAI_API_BASE", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID",
                "RUBRIC_GEN_AUDIT_OUTPUT_RECOVERY",
            ):
                env.pop(name)
        relay_url = f"http://127.0.0.1:{PORT}/v1"
        env.update(OPENAI_API_KEY=worker_key, CODEX_API_KEY=worker_key,
                   OPENAI_BASE_URL=relay_url, RUBRIC_GEN_OPENAI_BUDGET_URL=relay_url,
                   RUBRIC_GEN_RUNTIME_CONFIG=str(RUNTIME), PYTHONPATH=str(ROOT / "src"))
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        invocation = OUTPUT / "invocations" / stamp
        invocation.mkdir(parents=True, exist_ok=False)
        source_commit = subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, env=env, text=True).strip()
        (invocation / "source.diff").write_bytes(subprocess.check_output(
            ["git", "diff", "--binary", "HEAD"], cwd=ROOT, env=env))
        with tarfile.open(invocation / "source.tar.gz", "w:gz") as archive:
            paths = [*sorted((ROOT / "src").rglob("*.py")), CONFIG, RUNTIME,
                     Path(__file__).resolve(),
                     HERE.parent / "healthbench-hard-result20/budget_proxy.py"]
            paths.extend(p for p in experiment.tasks_dir.rglob("*") if p.is_file())
            for path in paths:
                archive.add(path, arcname=str(path.relative_to(ROOT)), recursive=False)
        receipt = dict(status="running", pid=os.getpid(), started_utc=stamp,
                       source_commit=source_commit, experiment_id=experiment.experiment_id,
                       config=str(CONFIG), assignments=36, budget_usd=BUDGET_USD,
                       host="local Mac", outer_shards=1, assignment_workers=6,
                       aggregate_provider_concurrency=12, internal_fanout=4,
                       audit_concurrency=12, requested_cpus=12, requested_memory_gib=24,
                       expected_wall_minutes=[30, 90], stages=[])

        def save() -> None:
            (invocation / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")

        save()
        print(f"invocation={invocation} pid={os.getpid()} study={experiment.experiment_id}", flush=True)
        server = None
        try:
            server = start_proxy(key, ledger, worker_key, port=PORT)
            for stage in ("seed", "paraphrase", "revise", "detect"):
                concurrency = 6 if stage in ("seed", "paraphrase") else 12
                command = [sys.executable, "-m", "rubric_gen.cli", stage,
                           "--experiment", str(CONFIG), "--max-concurrency", str(concurrency)]
                if stage == "revise":
                    command += ["--assignment-workers", "6", "--resume"]
                if stage == "detect":
                    command += ["--study-dir", experiment.dag["revise"]["output_dir"], "--resume"]
                effort = "high" if stage == "detect" else "low"
                record = dict(stage=stage, command=command, reasoning_effort=effort,
                              status="running")
                receipt["stages"].append(record)
                save()
                print(f"{stage}: {invocation / (stage + '.log')}", flush=True)
                with (invocation / f"{stage}.log").open("w") as log:
                    result = subprocess.run(command, cwd=ROOT,
                        env={**env, "RUBRIC_GEN_OPENAI_REASONING_EFFORT": effort},
                        stdout=log, stderr=subprocess.STDOUT)
                record.update(exit_code=result.returncode,
                              status="completed" if result.returncode == 0 else "failed")
                save()
                if result.returncode:
                    raise RuntimeError(f"{stage} incomplete; native outputs preserved")
            receipt["status"] = "completed"
        except BaseException:
            receipt["status"] = "failed"
            raise
        finally:
            if server is not None:
                server.shutdown()
                server.server_close()
            receipt.update(ended_utc=datetime.now(timezone.utc).isoformat(),
                           budget=json.loads((OUTPUT / "budget.json").read_text()))
            save()


if __name__ == "__main__":
    main()
