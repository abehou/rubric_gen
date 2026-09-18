"""Run the promoted provenance RTT on the corrected PaperBench Dev3 inputs."""

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
from rubric_gen.submission_revision.task_paraphrase_required import INTERNAL_STAGE_FANOUT


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
CONFIG = BUNDLE / "dev3.yaml"
RUN_ROOT = ROOT / "runs/paperbench-rtt-provenance-local-mac"
TASKS = (
    "semantic-self-consistency",
    "self-expansion",
    "self-composing-policies",
)
CONDITIONS = (
    "full-red-team-trace-execution-verified-proactive-provenance",
    "user-simulator-red-team-trace-execution-verified-proactive-provenance",
)
PANEL = ("gpt-5.6-sol", "claude-opus-5")
TRACE_VERSION = "attack_defense_v2.1_execution_verified_proactive_provenance"


def _base_runner():
    path = ROOT / "experiments/trace-v21-execution-verified-dropout/run_local.py"
    spec = importlib.util.spec_from_file_location("paperbench_rtt_base_runner", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load the validated local runner helpers")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("largest-smoke", "full"), required=True)
    parser.add_argument("--max-concurrency", type=int, default=4)
    parser.add_argument("--aggregate-concurrency", type=int, default=6)
    return parser.parse_args()


def _validate_experiment():
    experiment = load_experiment(CONFIG)
    if len(experiment.execution_assignments) != 18:
        raise RuntimeError("PaperBench RTT Dev3 must contain exactly 18 assignments")
    if tuple(experiment.task_ids) != TASKS:
        raise RuntimeError("PaperBench RTT Dev3 task membership changed")
    if tuple(experiment.execution_conditions or ()) != CONDITIONS:
        raise RuntimeError("PaperBench RTT condition membership changed")
    if experiment.payload["randomization"] != {"seed": 20260812, "replicates": 3}:
        raise RuntimeError("PaperBench corrected Dev3 seed or replicates changed")
    if experiment.protocol.get("review") != "workspace":
        raise RuntimeError("PaperBench must retain benchmark-native workspace review")
    if experiment.protocol.get("red_team_trace_version") != TRACE_VERSION:
        raise RuntimeError("promoted RTT implementation changed")
    if experiment.protocol.get("rubric_proposer_reasoning_effort_by_stage") != {
        "diagnosis": "high"
    }:
        raise RuntimeError("promoted diagnosis-only high allocation changed")
    if experiment.seed_agent_config().reasoning_effort != "low":
        raise RuntimeError("seed reasoning changed")
    if experiment.red_team_agent_config().reasoning_effort != "low":
        raise RuntimeError("attack reasoning changed")
    if any(
        experiment.solver_config(item.solver_id).reasoning_effort != "low"
        for item in experiment.execution_assignments
    ):
        raise RuntimeError("solver reasoning changed")
    paraphrases = experiment.payload["rubric_paraphrases"]
    if (
        paraphrases.get("prompt_policy") != "selected_neutral_heldout_rigorous"
        or paraphrases.get("count") != 5
    ):
        raise RuntimeError("corrected PaperBench rubric role policy changed")
    if tuple(experiment.payload["execution_audit_models"]) != PANEL:
        raise RuntimeError("Sol+Opus audit panel changed")
    return experiment


def _scope_ids(experiment, scope: str) -> tuple[str, ...]:
    if scope == "full":
        return tuple(item.assignment_id for item in experiment.execution_assignments)
    selected = tuple(
        item.assignment_id
        for item in experiment.execution_assignments
        if item.task_id == "self-composing-policies" and item.replicate == 1
    )
    selected_conditions = {
        item.condition_id
        for item in experiment.execution_assignments
        if item.assignment_id in selected
    }
    if len(selected) != 2 or selected_conditions != set(CONDITIONS):
        raise RuntimeError("largest-task smoke is not one matched Full/User pair")
    return selected


def _status(study: Path, invocation: str, expected: int) -> dict[str, object]:
    records = []
    try:
        records = json.loads((study / "study.json").read_text())["records"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    return {
        "invocation": invocation,
        "expected": expected,
        "statuses": dict(Counter(row["status"] for row in records)),
        "time": datetime.now(timezone.utc).isoformat(),
    }


def _input_manifest(experiment, base) -> dict[str, object]:
    roots = {
        "seeds": Path(experiment.dag["seed"]["output_dir"]),
        "paraphrases": Path(experiment.dag["paraphrase"]["output_dir"]),
        "dataset": Path(experiment.tasks_dir),
    }
    return {
        "config": {"path": str(CONFIG), "sha256": sha256_file(CONFIG)},
        "roots": {name: base._tree_manifest(root) for name, root in roots.items()},
    }


def main() -> None:
    args = _arguments()
    if not 1 <= args.max_concurrency <= 18:
        raise ValueError("local stage concurrency must be between 1 and 18")
    if not 1 <= args.aggregate_concurrency <= 18:
        raise ValueError("local aggregate provider concurrency must be between 1 and 18")
    if os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("local PaperBench Dev3 must not run with a Slurm identity")

    experiment = _validate_experiment()
    selected = _scope_ids(experiment, args.scope)
    expected = len(selected)
    base = _base_runner()
    credential_source = base._load_proposer_credential()
    input_manifest = _input_manifest(experiment, base)
    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(
        RUN_ROOT / ".dev3-run.lock",
        os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW,
        0o600,
    )
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        os.close(lock_fd)
        raise RuntimeError("another PaperBench RTT Dev3 owner is active") from error

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
        f"paperbench-rtt-{args.scope}-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
        + uuid.uuid4().hex[:8]
    )
    os.environ["RUBRIC_GEN_INVOCATION_ID"] = invocation
    owner = RUN_ROOT / "dev3/owners" / invocation
    owner.mkdir(parents=True, exist_ok=False)
    source = base._git_source(owner, bundle=BUNDLE, config=CONFIG)
    write_json_atomic(RUN_ROOT / "dev3/input-manifest.json", input_manifest)
    study = Path(experiment.dag["revise"]["output_dir"])
    launch = {
        "kind": "paperbench-rtt-provenance-local-dev3-launch-v1",
        "scope": args.scope,
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
        "expected_assignments": expected,
        "assignment_ids": list(selected),
        "tasks": list(TASKS),
        "conditions": list(CONDITIONS),
        "seed": 20260812,
        "resume": study.exists(),
        "rubric_proposer_provider": "openai",
        "rubric_proposer_credential_source": credential_source,
        "stage_reasoning": {
            "attack": "low",
            "quality": "low",
            "diagnosis": "high",
            "rubric_view": "low",
            "compilation": "low",
            "semantic": "low",
            "application": "low",
            "enforcement": "low",
            "solver": "low",
        },
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
        assignment_ids=selected,
    ))
    stop = threading.Event()

    def monitor() -> None:
        while not stop.is_set():
            write_json_atomic(
                RUN_ROOT / "dev3/status.json",
                _status(study, invocation, expected),
            )
            stop.wait(30)

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()
    started = time.monotonic()
    try:
        exit_code = runner.run()
    finally:
        stop.set()
        monitor_thread.join(5)
        write_json_atomic(
            RUN_ROOT / "dev3/status.json",
            _status(study, invocation, expected),
        )
    write_json_atomic(owner / "revision-exit.json", {
        "exit_code": exit_code,
        "wall_seconds": time.monotonic() - started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    })
    if exit_code:
        raise RuntimeError("PaperBench RTT Dev3 scope has incomplete assignments")

    ledger = json.loads((study / "study.json").read_text())
    completed = terminal_records(experiment, ledger)
    if (
        {row["assignment_id"] for row in completed} != set(selected)
        or any(row["status"] != "completed" for row in completed)
    ):
        raise RuntimeError("PaperBench RTT Dev3 completion scope is incomplete")
    assignments = {item.assignment_id: item for item in experiment.assignments}
    rows = []
    for record in completed:
        path = study / record["experiment_dir"]
        validate_completed_revision(
            path,
            assignments[record["assignment_id"]],
            experiment,
            runner.seed_root,
            runner.paraphrase_root,
        )
        rows.append({"assignment_id": record["assignment_id"], "root": str(path)})
    completion = {
        "kind": "paperbench-rtt-provenance-local-dev3-completion-v1",
        "scope": args.scope,
        "invocation": invocation,
        "experiment_id": experiment.experiment_id,
        "expected": expected,
        "completed": len(rows),
        "assignments": rows,
        "source": source,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    name = "smoke-completion.json" if args.scope == "largest-smoke" else "completion.json"
    write_json_atomic(owner / "completion.json", completion)
    write_json_atomic(RUN_ROOT / "dev3" / name, completion)
    print(json.dumps({
        "stage": f"paperbench_rtt_{args.scope}_complete",
        "completed": len(rows),
        "experiment_id": experiment.experiment_id,
    }), flush=True)


if __name__ == "__main__":
    main()
