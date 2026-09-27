"""Approved candidate Dev3 using native workflow and the existing $3 budget relay."""
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

CONFIG = HERE / "dev3-v6.yaml"
RUNTIME = HERE / "runtime.json"
OUTPUT = ROOT / "runs/healthbench-hard-rh-dev3-20260926-v6"
BUDGET_USD = 3.0


def stage_command(stage, experiment):
    command = [sys.executable, "-m", "rubric_gen.cli", stage,
               "--experiment", str(CONFIG), "--max-concurrency",
               "12" if stage in ("revise", "detect") else "6"]
    if stage in ("revise", "detect"):
        command.append("--resume")
    if stage == "revise":
        command += ["--assignment-workers", "6"]
    if stage == "detect":
        command += ["--study-dir", experiment.dag["revise"]["output_dir"]]
    return command


def worker_environment(worker_key):
    env = controlled_process_environment()
    for name in list(env):
        if any(s in name for s in ("API_KEY", "ACCESS_TOKEN")) or name in (
            "OPENAI_BASE_URL", "OPENAI_API_BASE", "OPENAI_ORG_ID", "OPENAI_PROJECT_ID",
            "RUBRIC_GEN_AUDIT_OUTPUT_RECOVERY",
        ):
            env.pop(name)
    env.update(OPENAI_API_KEY=worker_key, CODEX_API_KEY=worker_key,
               OPENAI_BASE_URL="http://127.0.0.1:18765/v1",
               RUBRIC_GEN_OPENAI_BUDGET_URL="http://127.0.0.1:18765/v1",
               RUBRIC_GEN_RUNTIME_CONFIG=str(RUNTIME), PYTHONPATH=str(ROOT / "src"))
    return env


def rearm_budget_denials(study_path, invocation):
    """Rearm only local-relay denials after explicit budget authorization.

    Caller holds the run owner lock. Preserve the entire prior manifest before
    changing operational retry flags; never alter answers, scores or identities.
    """
    original = study_path.read_bytes()
    state = json.loads(original)
    affected = []
    for record in state.get("records", []):
        if (record.get("status") == "failed"
                and record.get("automatic_recovery_exhausted")
                and record.get("error_type") == "RubricProposerProviderError"
                and "Budget relay stopped request: RuntimeError" in record.get("traceback", "")):
            record.update(automatic_recovery_exhausted=False, automatic_attempt_count=0,
                          next_automatic_action="explicit resume after authorized local budget extension")
            affected.append(record["assignment_id"])
    if affected:
        (invocation / "prior-budget-denial-study.json").write_bytes(original)
        from rubric_gen.artifacts.serialization import write_json_atomic
        write_json_atomic(study_path, state)
    return affected


def main(*, complete_remaining=False):
    experiment = load_experiment(CONFIG)
    assert len(experiment.assignments) == 36
    assert experiment.outcome_audit["models"] == ["gpt-6-luna"]
    assert not experiment.outcome_audit.get("rubric_free_models")
    assert Path(experiment.dag["seed"]["output_dir"]).parent == OUTPUT
    OUTPUT.mkdir(parents=True, exist_ok=True)
    with (OUTPUT / ".run.lock").open("a") as owner:
        # Authorized completion waits for the original owner to drain naturally;
        # never kill its in-flight calls or start a second provider queue.
        fcntl.flock(owner, fcntl.LOCK_EX | (0 if complete_remaining else fcntl.LOCK_NB))
        if complete_remaining and not (Path(experiment.dag["revise"]["output_dir"]) / "study.json").exists():
            raise RuntimeError("Completion recovery requires an existing study")
        key = dotenv_values(ROOT / ".env.local").get("OPENAI_API_KEY")
        if not key or key.startswith("sk-ant-") or not key.endswith("IfoA"):
            raise RuntimeError("Confirmed local OpenAI credential unavailable")
        ledger = Ledger(OUTPUT / "budget.json", BUDGET_USD, allow_overrun=complete_remaining)
        if complete_remaining:
            # User has explicitly lifted the dollar stop for this same cohort.
            # The original invocation/error and all recorded spending remain.
            ledger.state["stopped"] = False
            ledger.save()
        worker_key = "sk-local-budget-" + secrets.token_hex(24)
        env = worker_environment(worker_key)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        invocation = OUTPUT / "invocations" / stamp
        invocation.mkdir(parents=True, exist_ok=False)
        rearmed = rearm_budget_denials(
            Path(experiment.dag["revise"]["output_dir"]) / "study.json", invocation
        ) if complete_remaining else []
        head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, env=env, text=True).strip()
        (invocation / "source.diff").write_bytes(subprocess.check_output(
            ["git", "diff", "--binary", "HEAD"], cwd=ROOT, env=env))
        # Include new untracked implementation files without archiving credentials.
        with tarfile.open(invocation / "source.tar.gz", "w:gz") as archive:
            paths = [*sorted((ROOT / "src").rglob("*.py")), CONFIG, RUNTIME,
                     Path(__file__).resolve(), HERE.parent / "healthbench-hard-result20/budget_proxy.py"]
            paths.extend(p for p in Path(experiment.payload["tasks_dir"]).rglob("*") if p.is_file())
            for path in paths:
                archive.add(path, arcname=str(path.relative_to(ROOT)), recursive=False)
        receipt = dict(status="running", pid=os.getpid(), started_utc=stamp,
                       source_commit=head, experiment_id=experiment.experiment_id,
                       config=str(CONFIG), assignments=36,
                       budget_usd=None if complete_remaining else BUDGET_USD,
                       original_budget_usd=BUDGET_USD, allow_overrun=complete_remaining,
                       rearmed_budget_denials=rearmed,
                       scope="remaining revision and audit only" if complete_remaining else "full workflow",
                       key_suffix="IfoA", host="local Mac", outer_queues=1,
                       assignment_workers=6, provider_concurrency=12,
                       internal_fanout=4, audit_concurrency=12, cpu=os.cpu_count(),
                       memory_gib=24, resource_reservation="none; local process",
                       expected_wall_minutes=[30, 60], stages=[])
        def save():
            (invocation / "receipt.json").write_text(json.dumps(receipt, indent=2) + "\n")
        save()
        print(f"invocation={invocation} pid={os.getpid()} study={experiment.experiment_id}", flush=True)
        server = None
        try:
            server = start_proxy(key, ledger, worker_key)
            stages = ("revise", "detect") if complete_remaining else ("seed", "paraphrase", "revise", "detect")
            for stage in stages:
                command = stage_command(stage, experiment)
                effort = "high" if stage == "detect" else "low"
                record = dict(stage=stage, command=command, reasoning_effort=effort, status="running")
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
