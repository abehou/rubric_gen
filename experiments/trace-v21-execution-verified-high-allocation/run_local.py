"""Run the matched 18-assignment Luna-high stage-allocation Dev3 on this Mac."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import importlib.util
import json
import os
from pathlib import Path
import socket
import threading
import time
import uuid

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.execution_scope import terminal_records
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.study import StudyRunConfig, StudyRunner
from rubric_gen.submission_revision.study_validation import validate_completed_revision
from rubric_gen.submission_revision.task_paraphrase_required import (
    INTERNAL_STAGE_FANOUT,
)


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
CONFIG = BUNDLE / "dev3.yaml"
RUN_ROOT = ROOT / "runs/trace-v21-execution-verified-high-allocation-local-mac"
TASKS = ("da-3-4", "da-11-1", "da-18-1")
CONDITIONS = (
    "full-red-team-trace-execution-verified-high-attack-pair-diagnosis",
    "user-simulator-red-team-trace-execution-verified-high-attack-pair-diagnosis",
)
PANEL = ("gpt-5.6-sol", "claude-opus-5")
TRACE_VERSION = "attack_defense_v2.1_execution_verified"
RED_TEAM_REASONING_EFFORT = "high"
PROPOSER_REASONING_BY_STAGE = {"quality": "high", "diagnosis": "high"}
RUN_KIND = "execution-verified-high-allocation-local-dev3"
COMPLETION_STAGE = "execution_verified_high_allocation_dev3_complete"
SAVED_CASE_VALIDATOR = None
EXPECTED_ASSIGNMENTS = 18
EXPECTED_DROPOUT_RATES = None


def _configure_local_module_path() -> str:
    """Give workspace-launched app-server children an absolute package path."""

    source = str((ROOT / "src").resolve())
    existing = [
        item for item in os.environ.get("PYTHONPATH", "").split(os.pathsep)
        if item
    ]
    os.environ["PYTHONPATH"] = os.pathsep.join(
        [source, *(item for item in existing if Path(item).resolve() != Path(source))]
    )
    return source


def _base_runner():
    path = ROOT / "experiments/trace-v21-execution-verified-dropout/run_local.py"
    spec = importlib.util.spec_from_file_location("execution_verified_base_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the validated Mac runner helpers")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-concurrency", type=int, default=18)
    parser.add_argument("--aggregate-concurrency", type=int, default=18)
    return parser.parse_args()


def _validate_experiment():
    experiment = load_experiment(CONFIG)
    if len(experiment.execution_assignments) != EXPECTED_ASSIGNMENTS:
        raise RuntimeError(
            f"Dev3 must contain exactly {EXPECTED_ASSIGNMENTS} assignments"
        )
    if tuple(experiment.task_ids) != TASKS:
        raise RuntimeError("high-allocation Dev3 task membership changed")
    if tuple(experiment.payload["execution_conditions"]) != CONDITIONS:
        raise RuntimeError("high-allocation condition membership changed")
    if experiment.payload["randomization"] != {"seed": 20260806, "replicates": 3}:
        raise RuntimeError("high-allocation seed or replicate count changed")
    if experiment.protocol.get("red_team_trace_version") != TRACE_VERSION:
        raise RuntimeError("execution-verified RTT recipe changed")
    if experiment.protocol.get(
        "rubric_proposer_reasoning_effort_by_stage"
    ) != PROPOSER_REASONING_BY_STAGE:
        raise RuntimeError("stage-specific proposer allocation changed")
    if experiment.seed_agent_config().reasoning_effort != "low":
        raise RuntimeError("seed generator reasoning changed")
    if (
        experiment.red_team_agent_config().reasoning_effort
        != RED_TEAM_REASONING_EFFORT
    ):
        raise RuntimeError("attack reasoning effort changed")
    if any(
        experiment.solver_config(item.solver_id).reasoning_effort != "low"
        for item in experiment.execution_assignments
    ):
        raise RuntimeError("solver reasoning must remain low")
    if tuple(experiment.payload["execution_audit_models"]) != PANEL:
        raise RuntimeError("Sol+Opus audit panel changed")
    if EXPECTED_DROPOUT_RATES is not None:
        rates = {
            float(experiment.condition(item.condition_id)["rubric_dropout_rate"])
            for item in experiment.execution_assignments
        }
        if rates != set(EXPECTED_DROPOUT_RATES):
            raise RuntimeError("Dev3 dropout rates changed")
    return experiment


def _status(study: Path, invocation: str) -> dict[str, object]:
    records = []
    try:
        records = json.loads((study / "study.json").read_text())["records"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {
        "invocation": invocation,
        "expected": EXPECTED_ASSIGNMENTS,
        "statuses": dict(Counter(row["status"] for row in records)),
        "time": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    args = _arguments()
    if not 1 <= args.max_concurrency <= 18:
        raise ValueError("local stage concurrency must be between 1 and 18")
    if not 1 <= args.aggregate_concurrency <= 18:
        raise ValueError("local aggregate provider concurrency must be between 1 and 18")
    if os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("local Dev3 must not run with a Slurm job identity")
    local_module_path = _configure_local_module_path()

    experiment = _validate_experiment()
    base = _base_runner()
    saved_case_validation = (
        SAVED_CASE_VALIDATOR() if SAVED_CASE_VALIDATOR is not None else None
    )
    credential_source = base._load_proposer_credential()
    input_manifest = base._input_manifest(experiment, config=CONFIG)
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(
        RUN_ROOT / ".dev3-run.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600,
    )
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        os.close(lock_fd)
        raise RuntimeError("another high-allocation Dev3 owner is active") from error

    runtime_path = RUN_ROOT / "runtime/dev3-runtime.json"
    runtime_path.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(runtime_path, {
        "version": 1,
        "aggregate_concurrency": args.aggregate_concurrency,
        "audit_studies": 1,
        "coordination_dir": str((RUN_ROOT / "runtime/dev3-coordination").resolve()),
    })
    os.environ["RUBRIC_GEN_RUNTIME_CONFIG"] = str(runtime_path.resolve())
    invocation = (
        "execution-verified-high-allocation-dev3-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
        + uuid.uuid4().hex[:8]
    )
    os.environ["RUBRIC_GEN_INVOCATION_ID"] = invocation
    owner = RUN_ROOT / "dev3/owners" / invocation
    owner.mkdir(parents=True, exist_ok=False)
    source = base._git_source(owner, bundle=BUNDLE, config=CONFIG)
    write_json_atomic(RUN_ROOT / "dev3/input-manifest.json", input_manifest)
    study = Path(experiment.dag["revise"]["output_dir"])
    module_path_recovery = base._recover_local_module_path_failures(
        study, invocation,
    )
    write_json_atomic(
        owner / "local-module-path-recovery.json", module_path_recovery,
    )
    launch = {
        "kind": RUN_KIND + "-launch-v1",
        "invocation": invocation,
        "pid": os.getpid(),
        "uid": os.getuid(),
        "host": socket.gethostname(),
        "source": source,
        "hardware": base._hardware(),
        "runtime": policy(),
        "runtime_config": {"path": str(runtime_path), "sha256": sha256_file(runtime_path)},
        "experiment": str(CONFIG),
        "experiment_id": experiment.experiment_id,
        "config_sha256": sha256_file(CONFIG),
        "study": str(study),
        "stage_max_concurrency": args.max_concurrency,
        "aggregate_provider_concurrency": args.aggregate_concurrency,
        "internal_stage_fanout": INTERNAL_STAGE_FANOUT,
        "expected_assignments": EXPECTED_ASSIGNMENTS,
        "tasks": list(TASKS),
        "conditions": list(CONDITIONS),
        "seed": 20260806,
        "resume": study.exists(),
        "local_module_path": local_module_path,
        "local_module_path_recovery": {
            "recovered_assignments": module_path_recovery[
                "recovered_assignments"
            ],
            "receipt": str(
                (owner / "local-module-path-recovery.json").resolve()
            ),
            "receipt_sha256": sha256_file(
                owner / "local-module-path-recovery.json"
            ),
        },
        "rubric_proposer_provider": "openai",
        "rubric_proposer_credential_source": credential_source,
        "stage_reasoning": {
            "attack": RED_TEAM_REASONING_EFFORT,
            "quality": PROPOSER_REASONING_BY_STAGE.get("quality", "low"),
            "diagnosis": PROPOSER_REASONING_BY_STAGE.get("diagnosis", "low"),
            "rubric_view": "low", "compilation": "low", "semantic": "low",
            "application": "low", "enforcement": "low", "solver": "low",
        },
        "saved_case_validation": saved_case_validation,
        "input_manifest_sha256": sha256_file(RUN_ROOT / "dev3/input-manifest.json"),
        "slurm_job_id": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json_atomic(owner / "launch.json", launch)
    write_json_atomic(RUN_ROOT / "dev3/latest-launch.json", launch)

    runner = StudyRunner(StudyRunConfig(
        experiment=experiment,
        seed_run_dir=Path(experiment.dag["seed"]["output_dir"]),
        paraphrase_run_dir=Path(experiment.dag["paraphrase"]["output_dir"]),
        output_dir=study,
        max_concurrency=args.max_concurrency,
        resume=study.exists(),
    ))
    stop = threading.Event()

    def monitor() -> None:
        while not stop.is_set():
            write_json_atomic(RUN_ROOT / "dev3/status.json", _status(study, invocation))
            stop.wait(30)

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()
    started = time.monotonic()
    try:
        exit_code = runner.run()
    finally:
        stop.set()
        monitor_thread.join(5)
        write_json_atomic(RUN_ROOT / "dev3/status.json", _status(study, invocation))
    write_json_atomic(owner / "revision-exit.json", {
        "exit_code": exit_code,
        "wall_seconds": time.monotonic() - started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    })
    if exit_code:
        raise RuntimeError("high-allocation Dev3 has incomplete assignments")

    ledger = json.loads((study / "study.json").read_text())
    completed = terminal_records(experiment, ledger)
    if (len(completed) != EXPECTED_ASSIGNMENTS
            or any(row["status"] != "completed" for row in completed)):
        raise RuntimeError(
            "Dev3 completion scope does not contain exactly "
            f"{EXPECTED_ASSIGNMENTS} successful assignments"
        )
    assignments = {item.assignment_id: item for item in experiment.assignments}
    rows = []
    for record in completed:
        path = study / record["experiment_dir"]
        validate_completed_revision(
            path, assignments[record["assignment_id"]], experiment,
            runner.seed_root, runner.paraphrase_root,
        )
        rows.append({"assignment_id": record["assignment_id"], "root": str(path)})
    completion = {
        "kind": RUN_KIND + "-completion-v1",
        "invocation": invocation,
        "experiment_id": experiment.experiment_id,
        "expected": EXPECTED_ASSIGNMENTS,
        "completed": len(rows),
        "assignments": rows,
        "source": source,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json_atomic(owner / "completion.json", completion)
    write_json_atomic(RUN_ROOT / "dev3/completion.json", completion)
    print(json.dumps({
        "stage": COMPLETION_STAGE,
        "completed": len(rows),
        "experiment_id": experiment.experiment_id,
    }), flush=True)


if __name__ == "__main__":
    main()
