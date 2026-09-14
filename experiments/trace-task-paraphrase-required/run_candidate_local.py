"""Run the canonical task-required RTT candidate through a local Mac adapter."""
from __future__ import annotations

import argparse
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
import platform
from pathlib import Path
import socket
import subprocess
import threading
import time
import uuid

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.execution_scope import terminal_records
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.study import (
    StudyRunConfig,
    StudyRunner,
    _exclusive_study_lease,
)
from rubric_gen.submission_revision.study_validation import validate_completed_revision


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
TASKS = ("da-3-4", "da-11-1", "da-18-1")
VERSION = "attack_defense_v2.1_task_paraphrase_required"
INPUT_RECEIPT = ROOT / "experiments/trace-attack-defense-v2/dev3-inputs.json"
CONTROL_RECEIPT = ROOT / "experiments/trace-attack-defense-v3/canonical-v3-config-finalization.json"


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-root", type=Path, required=True)
    parser.add_argument("--path-map", type=Path, required=True)
    parser.add_argument("--aggregate-concurrency", type=int, default=6)
    parser.add_argument("--task-workers", type=int, default=2)
    parser.add_argument("--assignment-workers", type=int, default=2)
    return parser.parse_args()


def _regular_absolute(path: Path, label: str) -> Path:
    if not path.is_absolute() or path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} must be a regular absolute file: {path}")
    return path.resolve()


def _write_runtime_config(run_root: Path, aggregate: int) -> Path:
    if type(aggregate) is not int or not 1 <= aggregate <= 8:
        raise ValueError("first local run aggregate concurrency must be between 1 and 8")
    path = run_root / "runtime/runtime.json"
    write_json_atomic(path, {
        "version": 1,
        "aggregate_concurrency": aggregate,
        "audit_studies": 1,
        "coordination_dir": str((run_root / "runtime/coordination").resolve()),
    })
    return path.resolve()


def _config_receipt(path: Path):
    experiment = load_experiment(path)
    task = experiment.task_ids[0]
    expected = {
        (task, replicate, condition)
        for replicate in range(1, 4)
        for condition in (
            "full-red-team-trace",
            "user-simulator-red-team-trace",
        )
    }
    actual = {
        (assignment.task_id, assignment.replicate, assignment.condition_id)
        for assignment in experiment.execution_assignments
    }
    if actual != expected or len(experiment.execution_assignments) != 6:
        raise RuntimeError(f"candidate scope differs: {sorted(actual)}")
    if experiment.protocol.get("red_team_trace_version") != VERSION:
        raise RuntimeError("candidate config has the wrong trace recipe")
    if experiment.payload["randomization"] != {"seed": 20260806, "replicates": 3}:
        raise RuntimeError("canonical Dev3 randomization changed")
    if (experiment.protocol["min_revisions"] != 5
            or experiment.protocol["max_revisions"] != 10):
        raise RuntimeError("revision boundary changed")
    if experiment.payload.get("execution_audit_models") != ["gemini-3.8-flash"]:
        raise RuntimeError("local candidate audit scope must be Gemini-only")
    return experiment


def _task_tree_receipt(root: Path) -> dict[str, object]:
    digest = hashlib.sha256()
    count = 0
    size = 0
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.is_symlink():
            raise RuntimeError(f"task tree contains a symlink: {path}")
        relative = str(path.relative_to(root))
        file_digest = sha256_file(path)
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(file_digest.encode("ascii"))
        digest.update(b"\0")
        count += 1
        size += path.stat().st_size
    return {"files": count, "bytes": size, "tree_sha256": digest.hexdigest()}


def _inspect_frozen_files(experiments) -> tuple[list[dict[str, object]], list[str]]:
    receipt = json.loads(INPUT_RECEIPT.read_text(encoding="utf-8"))
    expected_by_task = {row["task"]: row for row in receipt["per_task"]}
    rows: list[dict[str, object]] = []
    errors: list[str] = []
    for experiment in experiments:
        task = experiment.task_ids[0]
        expected = expected_by_task[task]
        roots = {
            "seed": Path(experiment.dag["seed"]["output_dir"]),
            "paraphrase": Path(experiment.dag["paraphrase"]["output_dir"]),
        }
        validated: dict[str, object] = {"task": task}
        for kind, root in roots.items():
            if root.is_symlink() or not root.is_dir():
                message = f"missing regular frozen {kind} root for {task}: {root}"
                errors.append(message)
                validated[kind] = {"root": str(root), "status": "missing"}
                continue
            files = expected[kind]["files"]
            failures = []
            for relative, digest in files.items():
                path = root / relative
                if path.is_symlink() or not path.is_file() or sha256_file(path) != digest:
                    failures.append(str(path))
            if failures:
                errors.extend(
                    f"frozen {kind} mismatch for {task}: {path}" for path in failures
                )
            validated[kind] = {
                "root": str(root),
                "validated_files": len(files),
                "receipt_sha256": sha256_file(INPUT_RECEIPT),
                "status": "mismatch" if failures else "verified",
            }
        instruction = experiment.task_dir(task) / "instruction.md"
        rubric = experiment.task_dir(task) / "tests/rubric.txt"
        validated["task_files"] = {
            "instruction.md": sha256_file(instruction),
            "tests/rubric.txt": sha256_file(rubric),
            **_task_tree_receipt(experiment.task_dir(task)),
        }
        rows.append(validated)
    return rows, errors


def _validate_control_configs(experiments) -> list[dict[str, str]]:
    receipt = json.loads(CONTROL_RECEIPT.read_text(encoding="utf-8"))
    expected = {row["task"]: row for row in receipt["tasks"]}
    rows = []
    for experiment in experiments:
        task = experiment.task_ids[0]
        source = experiment.pretreatment_source
        assert source is not None
        config = Path(source["experiment"])
        row = expected[task]
        if source["experiment_id"] != row["producer_id"]:
            raise RuntimeError(f"control experiment identity changed for {task}")
        if sha256_file(config) != row["producer_config_sha256"]:
            raise RuntimeError(f"control config bytes changed for {task}")
        rows.append({
            "task": task,
            "experiment_id": source["experiment_id"],
            "config": str(config),
            "config_sha256": sha256_file(config),
            "study": source["study_dir"],
        })
    return rows


def _inspect_control_studies(experiments) -> tuple[list[dict[str, object]], list[str]]:
    rows: list[dict[str, object]] = []
    errors: list[str] = []
    for experiment in experiments:
        task = experiment.task_ids[0]
        source = experiment.pretreatment_source
        assert source is not None
        root = Path(source["study_dir"])
        row: dict[str, object] = {
            "task": task,
            "experiment_id": source["experiment_id"],
            "root": str(root),
        }
        if root.is_symlink() or not root.is_dir():
            row["status"] = "missing"
            errors.append(f"missing compatible control study for {task}: {root}")
        else:
            ledger_path = root / "study.json"
            pool = root / "pretreatment-rubrics"
            if ledger_path.is_symlink() or not ledger_path.is_file():
                errors.append(f"missing compatible control ledger for {task}: {ledger_path}")
            if pool.is_symlink() or not pool.is_dir():
                errors.append(f"missing compatible control g1 pool for {task}: {pool}")
            row.update({
                "status": "present",
                "study_json_sha256": (
                    sha256_file(ledger_path) if ledger_path.is_file() else None
                ),
                "pretreatment_pool": str(pool),
            })
        rows.append(row)
    return rows, errors


def _hardware() -> dict[str, object]:
    def sysctl(name: str) -> str | None:
        try:
            return subprocess.check_output(["sysctl", "-n", name], text=True).strip()
        except (FileNotFoundError, subprocess.CalledProcessError):
            return None

    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "processor": platform.processor(),
        "hostname": socket.gethostname(),
        "hw_memsize": sysctl("hw.memsize"),
        "hw_ncpu": sysctl("hw.ncpu"),
        "hw_physicalcpu": sysctl("hw.physicalcpu"),
    }


def _prepare(runner: StudyRunner) -> None:
    existed = runner.root.exists()
    runner.root.mkdir(parents=True, exist_ok=True)
    with _exclusive_study_lease(runner.root):
        runner._start_manifest(
            sorted(runner.experiment.assignments, key=lambda item: item.execution_order),
            existed,
        )
        runner._prepare_pretreatment_rubric(runner.experiment.task_ids[0])


def _status(runners: list[StudyRunner], invocation: str) -> dict[str, object]:
    rows = []
    by_task: dict[str, dict[str, int]] = {}
    for runner in runners:
        task_rows = []
        try:
            task_rows = json.loads((runner.root / "study.json").read_text())["records"]
        except (OSError, ValueError, KeyError, TypeError):
            pass
        rows.extend(task_rows)
        by_task[runner.experiment.task_ids[0]] = dict(
            Counter(row["status"] for row in task_rows)
        )
    return {
        "invocation": invocation,
        "method": VERSION,
        "statuses": dict(Counter(row["status"] for row in rows)),
        "by_task": by_task,
        "time": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    args = _arguments()
    run_root = args.run_root.expanduser()
    if not run_root.is_absolute() or run_root.is_symlink():
        raise RuntimeError("--run-root must be an absolute non-symlink path")
    if not 1 <= args.task_workers <= 2:
        raise ValueError("first local run supports at most two concurrent task runners")
    if not 1 <= args.assignment_workers <= 2:
        raise ValueError("first local run supports at most two assignment workers per task")
    path_map = _regular_absolute(args.path_map.expanduser(), "--path-map")
    run_root.mkdir(parents=True, exist_ok=True)
    run_lock = os.open(run_root / ".local-run.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        fcntl.flock(run_lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as exc:
        os.close(run_lock)
        raise RuntimeError("another local candidate runner owns this run root") from exc

    runtime_config = _write_runtime_config(run_root, args.aggregate_concurrency)
    os.environ["RUBRIC_GEN_PATH_MAP_FILE"] = str(path_map)
    os.environ["RUBRIC_GEN_RUNTIME_CONFIG"] = str(runtime_config)
    invocation = "local-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:8]
    os.environ["RUBRIC_GEN_INVOCATION_ID"] = invocation
    runtime = policy()
    experiments = [
        _config_receipt(BUNDLE / "canonical" / f"{task}.yaml") for task in TASKS
    ]
    for experiment in experiments:
        output = Path(experiment.dag["revise"]["output_dir"])
        if not output.is_relative_to(run_root):
            raise RuntimeError(f"candidate output escaped --run-root: {output}")
    controls = _validate_control_configs(experiments)
    frozen_inputs, frozen_errors = _inspect_frozen_files(experiments)
    control_studies, control_errors = _inspect_control_studies(experiments)
    input_errors = frozen_errors + control_errors
    write_json_atomic(run_root / "input-validation.json", {
        "kind": "trace-task-paraphrase-required-local-input-validation",
        "time": datetime.now(timezone.utc).isoformat(),
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "path_map": {"path": str(path_map), "sha256": sha256_file(path_map)},
        "frozen_inputs": frozen_inputs,
        "pretreatment_sources": controls,
        "control_studies": control_studies,
        "errors": input_errors,
        "ready": not input_errors,
        "provider_calls": 0,
    })
    if input_errors:
        raise RuntimeError("local input validation failed:\n- " + "\n- ".join(input_errors))

    runners = [
        StudyRunner(StudyRunConfig(
            experiment,
            Path(experiment.dag["seed"]["output_dir"]),
            Path(experiment.dag["paraphrase"]["output_dir"]),
            Path(experiment.dag["revise"]["output_dir"]),
            args.assignment_workers,
            resume=Path(experiment.dag["revise"]["output_dir"]).exists(),
        ))
        for experiment in experiments
    ]
    owner = run_root / "owners" / invocation
    owner.mkdir(parents=True, exist_ok=False)
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
    ).strip()
    write_json_atomic(owner / "launch.json", {
        "method": VERSION,
        "dev3_control": False,
        "invocation": invocation,
        "pid": os.getpid(),
        "uid": os.getuid(),
        "host": socket.gethostname(),
        "commit": commit,
        "runtime": runtime,
        "runtime_config": {"path": str(runtime_config), "sha256": sha256_file(runtime_config)},
        "path_map": {"path": str(path_map), "sha256": sha256_file(path_map)},
        "hardware": _hardware(),
        "task_workers": args.task_workers,
        "assignment_workers_per_task": args.assignment_workers,
        "candidate_internal_learning_threads": 4,
        "tasks": list(TASKS),
        "expected_assignments": 18,
        "configs": {str(experiment.path): sha256_file(experiment.path) for experiment in experiments},
        "frozen_inputs": frozen_inputs,
        "pretreatment_sources": controls,
        "control_studies": control_studies,
        "time": datetime.now(timezone.utc).isoformat(),
        "outcome_audits": False,
        "slurm_job_id": os.environ.get("SLURM_JOB_ID"),
        "openai_api_key_imported_by_adapter": False,
    })

    try:
        with ThreadPoolExecutor(max_workers=args.task_workers) as pool:
            list(pool.map(_prepare, runners))
        runners = [
            StudyRunner(StudyRunConfig(
                runner.experiment,
                runner.seed_root,
                runner.paraphrase_root,
                runner.root,
                args.assignment_workers,
                resume=True,
            ))
            for runner in runners
        ]
        frozen_g1 = []
        for runner in runners:
            manifests = list(runner.pretreatment_root.glob("**/generation-0001/manifest.json"))
            if len(manifests) != 1:
                raise RuntimeError(
                    f"expected one reused g1 manifest for {runner.experiment.task_ids[0]}, "
                    f"found {len(manifests)}"
                )
            path = manifests[0]
            data = json.loads(path.read_text(encoding="utf-8"))
            frozen_g1.append({
                "task": runner.experiment.task_ids[0],
                "manifest": str(path),
                "manifest_sha256": sha256_file(path),
                "generation_sha256": data["generation_sha256"],
            })
        write_json_atomic(run_root / "frozen-g1.json", frozen_g1)

        stop = threading.Event()

        def monitor() -> None:
            while not stop.is_set():
                write_json_atomic(run_root / "candidate-status.json", _status(runners, invocation))
                stop.wait(30)

        thread = threading.Thread(target=monitor, daemon=True)
        thread.start()
        started = time.monotonic()
        try:
            with ThreadPoolExecutor(max_workers=args.task_workers) as pool:
                exits = list(pool.map(lambda runner: runner.run(), runners))
        finally:
            stop.set()
            thread.join(5)
            write_json_atomic(run_root / "candidate-status.json", _status(runners, invocation))
        write_json_atomic(owner / "revision-exits.json", {
            "exits": exits,
            "wall_seconds": time.monotonic() - started,
        })
        if any(exits):
            raise RuntimeError("candidate has incomplete assignments; successful outputs retained")

        rows = []
        for runner in runners:
            ledger = json.loads((runner.root / "study.json").read_text(encoding="utf-8"))
            completed = terminal_records(runner.experiment, ledger)
            if len(completed) != 6 or any(row["status"] != "completed" for row in completed):
                raise RuntimeError("task study scope incomplete")
            assignments = {item.assignment_id: item for item in runner.experiment.assignments}
            for record in completed:
                path = runner.root / record["experiment_dir"]
                validate_completed_revision(
                    path,
                    assignments[record["assignment_id"]],
                    runner.experiment,
                    runner.seed_root,
                    runner.paraphrase_root,
                )
                rows.append({
                    "assignment_id": record["assignment_id"],
                    "root": str(path),
                    "experiment_id": runner.experiment.experiment_id,
                })
        write_json_atomic(run_root / "completion.json", {
            "method": VERSION,
            "dev3_control": False,
            "invocation": invocation,
            "expected": 18,
            "completed": len(rows),
            "assignments": rows,
            "frozen_g1": frozen_g1,
            "audits_launched": 0,
        })
        print(json.dumps({
            "stage": "candidate_dev3_complete",
            "assignments": len(rows),
            "outcome_audits": 0,
        }), flush=True)
    finally:
        os.close(run_lock)


if __name__ == "__main__":
    main()
