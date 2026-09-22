"""Semi/Score-only Results40 revision and missing-only Sol/Gemini audit."""
from __future__ import annotations

import argparse
from collections import Counter
from contextlib import redirect_stderr, redirect_stdout
from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading

from dotenv import dotenv_values

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.targets import load_evaluation_targets
from rubric_gen.submission_revision.execution_scope import terminal_records
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.source_resolution import resolve_study_sources

from make_configs import BUNDLE, CONDITIONS, ROOT, RUN, SHARDS, TASKS, config_path
from prepare import PANEL, sha
UV = Path("/home/aydanh/tools/uv/uv")
PYTHON = Path("/home/aydanh/repos/rubric_gen/.venv/bin/python")
SOL_PANEL = ("gpt-5.6-sol",)
GEMINI_PANEL = ("gemini-3.8-flash",)
OPUS_PANEL = ("claude-opus-5",)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def credential_keys(mode: str) -> tuple[str, ...]:
    if mode == "execute":
        # Semi/score-only revision uses the unchanged optimizer judge through
        # the OpenAI Responses route even though solver/RTT turns use Codex.
        return ("OPENAI_API_KEY",)
    if mode == "audit":
        return ("OPENAI_API_KEY", "GEMINI_API_KEY")
    if mode == "audit-opus-complete":
        return ("ANTHROPIC_API_KEY",)
    raise ValueError(f"unsupported credential mode: {mode}")


def credentials(mode: str) -> None:
    values = dotenv_values("/home/aydanh/repos/rubric_gen/.env.local")
    for key in credential_keys(mode):
        if not values.get(key):
            raise RuntimeError(f"configured credential unavailable: {key}")
        os.environ[key] = str(values[key])


def runtime_write_probe() -> None:
    """Fail before provider work when the shared runtime journal is unwritable."""

    root = Path(policy()["coordination_dir"])
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"write-probe-{os.environ['SLURM_JOB_ID']}-{os.getpid()}"
    path.write_text("ok\n")
    path.unlink()


def clean_commit() -> str:
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=ROOT, text=True).strip()
    dirty = subprocess.check_output(["git", "status", "--porcelain"], cwd=ROOT, text=True)
    if dirty.strip():
        raise RuntimeError("frozen Results40 worktree is not clean")
    return commit


def config(task: str, kind: str) -> Path:
    return config_path(task, kind)


def experiment(task: str, kind: str):
    return load_experiment(config(task, kind))


def runtime(mode: str) -> dict:
    value = policy()
    if value["aggregate_concurrency"] != 60 or value["audit_studies"] != 3:
        raise RuntimeError("Results40 runtime owner capacity changed")
    expected_audit = {"openai": 60, "anthropic": 60, "google": 60}
    if value.get("audit_provider_concurrency") != expected_audit:
        raise RuntimeError("Results40 Sol/Opus/Gemini provider partitions changed")
    return {
        **value,
        "stage_workers": revision_shard_workers() * revision_assignment_workers() if mode == "execute" else 63,
        "revision_shard_workers": revision_shard_workers() if mode == "execute" else None,
        "revision_assignment_workers": revision_assignment_workers() if mode == "execute" else None,
    }


def revision_shard_workers() -> int:
    workers = int(os.environ.get("RESULT40_SHARD_WORKERS", "4"))
    if not 1 <= workers <= 10:
        raise RuntimeError("RESULT40_SHARD_WORKERS must be between 1 and 10")
    return workers


def revision_assignment_workers() -> int:
    workers = int(os.environ.get("RESULT40_ASSIGNMENT_WORKERS", "6"))
    if not 1 <= workers <= 6:
        raise RuntimeError("RESULT40_ASSIGNMENT_WORKERS must be between 1 and 6")
    return workers


def revision_recovery_passes() -> int:
    passes = int(os.environ.get("RESULT40_RECOVERY_PASSES", "3"))
    if not 1 <= passes <= 3:
        raise RuntimeError("RESULT40_RECOVERY_PASSES must be between 1 and 3")
    return passes


def scoped_experiment(source: Path, models: tuple[str, ...], output_dir: Path):
    original = load_experiment(source)
    payload = deepcopy(original.payload)
    payload["execution_audit_models"] = list(models)
    payload["dag"]["detect"]["output_dir"] = str(output_dir)
    scoped = replace(original, payload=payload)
    if scoped.experiment_id != original.experiment_id:
        raise RuntimeError("audit scope changed revision experiment identity")
    if tuple(scoped.outcome_audit["models"]) != models:
        raise RuntimeError("audit scope did not select requested provider")
    return scoped


def owner(mode: str, commit: str, capacity: dict) -> Path:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    root = RUN / "owners" / f"{mode}-{os.environ['SLURM_JOB_ID']}-{stamp}"
    root.mkdir(parents=True, exist_ok=False)
    write_json_atomic(root / "launch.json", {
        "mode": mode,
        "source_commit": commit,
        "job_id": os.environ["SLURM_JOB_ID"],
        "host": socket.gethostname(),
        "started_at": stamp,
        "tasks": list(TASKS),
        "conditions": list(CONDITIONS),
        "assignment_count": 240,
        "cpus": int(os.environ["SLURM_CPUS_PER_TASK"]),
        "memory_mb": int(os.environ["SLURM_MEM_PER_NODE"]),
        "runtime": capacity,
        "internal_fanout": 4,
        "command": sys.argv,
    })
    return root


def environment() -> dict:
    result = dict(os.environ)
    result.update({
        "PYTHONPATH": str(ROOT / "src"),
        "UV_PROJECT_ENVIRONMENT": str(PYTHON.parent.parent),
    })
    return result


def uv_stage(task: str, kind: str, stage: str, workers: int, log: Path) -> dict:
    command = [
        str(UV), "run", "--no-sync", "rubric-gen", stage,
        "--experiment", str(config(task, kind)),
        "--max-concurrency", str(workers), "--resume",
    ]
    started = now()
    with log.open("a") as output:
        completed = subprocess.run(command, cwd=ROOT, env=environment(), stdout=output, stderr=subprocess.STDOUT)
    return {"task_id": task, "shard": kind, "stage": stage, "exit_code": completed.returncode, "started_at": started, "finished_at": now(), "log": str(log)}


def audit_stage(name: str, exp, workers: int, log: Path) -> dict:
    """Run the native detect implementation for one in-memory audit scope."""

    from rubric_gen.runtime.audit_execution import audit_output_owner
    from rubric_gen.submission_revision.commands import _run_detect_owned

    started = now()
    output_dir = Path(exp.dag["detect"]["output_dir"])
    args = argparse.Namespace(max_concurrency=workers, resume=True)
    exit_code = 1
    error = None
    category = None
    try:
        with log.open("a") as output, redirect_stdout(output), redirect_stderr(output):
            with audit_output_owner(output_dir):
                exit_code = _run_detect_owned(
                    args,
                    exp,
                    Path(exp.dag["revise"]["output_dir"]),
                    Path(exp.dag["paraphrase"]["output_dir"]),
                    output_dir,
                )
    except Exception as exc:
        from rubric_gen.runtime.failures import failure_category

        error = f"{type(exc).__name__}: {exc}"
        category = failure_category(exc)
    return {
        "scope": name,
        "stage": "detect",
        "models": list(exp.outcome_audit["models"]),
        "experiment_id": exp.experiment_id,
        "study_dir": str(exp.dag["revise"]["output_dir"]),
        "audit_dir": str(output_dir),
        "exit_code": int(exit_code),
        "error": error,
        "failure_category": category,
        "started_at": started,
        "finished_at": now(),
        "log": str(log),
    }


def complete_shard(task: str, kind: str) -> list[dict]:
    exp = experiment(task, kind)
    study = Path(exp.dag["revise"]["output_dir"])
    ledger = json.loads((study / "study.json").read_text())
    rows = terminal_records(exp, ledger)
    if len(rows) != 6 or any(row["status"] != "completed" for row in rows):
        raise RuntimeError(f"{task}/{kind} is not 6/6 complete")
    # StudyRunner performs full artifact/hash validation before it changes an
    # assignment record to completed.  Repeating that scan here re-read large
    # immutable workspaces and exhausted several recovery wall-time limits.
    # Reopen the exact sources through the audit target loader instead: this
    # rechecks study/producer identity, terminal state, rubric generations and
    # the concrete initial/final targets without duplicating workspace hashing.
    sources = resolve_study_sources(study, exp)
    targets = load_evaluation_targets(EvaluationConfig(
        experiment=exp,
        study_dir=study,
        paraphrase_dir=Path(exp.dag["paraphrase"]["output_dir"]),
        output_dir=Path(exp.dag["detect"]["output_dir"]),
        max_concurrency=6,
        resume=True,
    ), sources)
    expected = {row["assignment_id"] for row in rows}
    if len(targets) != 6 or {target.assignment_id for target in targets} != expected:
        raise RuntimeError(f"{task}/{kind} audit target scope differs from completed assignments")
    return rows


def validate_task_match(task: str) -> None:
    by_replicate = {}
    conditions = set()
    for kind in ("static", "trace"):
        exp = experiment(task, kind)
        study = Path(exp.dag["revise"]["output_dir"])
        ledger = json.loads((study / "study.json").read_text())
        assignments = {a.assignment_id: a for a in exp.execution_assignments}
        for row in terminal_records(exp, ledger):
            assignment = assignments[row["assignment_id"]]
            manifest = json.loads((study / row["experiment_dir"] / "manifest.json").read_text())
            by_replicate.setdefault(assignment.replicate, set()).add(manifest["seed_sha256"])
            conditions.add(assignment.condition_id)
    if conditions != set(CONDITIONS) or set(by_replicate) != {1, 2, 3} or any(len(value) != 1 for value in by_replicate.values()):
        raise RuntimeError(f"{task} four conditions do not share matched initial submissions")


def incomplete_shards() -> tuple[tuple[str, str], ...]:
    pending = []
    for task, kind in SHARDS:
        exp = experiment(task, kind)
        study = Path(exp.dag["revise"]["output_dir"])
        if not (study / "study.json").exists():
            pending.append((task, kind))
            continue
        ledger = json.loads((study / "study.json").read_text())
        rows = terminal_records(exp, ledger)
        if len(rows) != 6 or any(row.get("status") != "completed" for row in rows):
            pending.append((task, kind))
    return tuple(pending)


def reconcile_incomplete_shards(shards: tuple[tuple[str, str], ...], pass_index: int) -> list[dict]:
    """Rearm only exact response-free startup residue between bounded passes."""

    from reconcile_runtime_failures import reconcile_study

    stamp = datetime.now(timezone.utc).strftime(f"%Y%m%dT%H%M%SZ-pass{pass_index}")
    results = []
    for task, kind in shards:
        exp = experiment(task, kind)
        results.append(reconcile_study(
            Path(exp.dag["revise"]["output_dir"]),
            stamp=stamp,
            apply=True,
        ))
    return results


def execute(path: Path) -> None:
    status_path = RUN / "revision-status.json"
    if status_path.exists():
        shutil.copyfile(status_path, path / "previous-revision-status.json")
    workers = revision_shard_workers()
    assignment_workers = revision_assignment_workers()
    state = {
        "job_id": os.environ["SLURM_JOB_ID"],
        "started_at": now(),
        "shard_workers": workers,
        "maximum_assignment_workers": workers * assignment_workers,
        "maximum_recovery_passes": revision_recovery_passes(),
        "tasks": {},
        "passes": [],
    }
    state_lock = threading.Lock()
    write_json_atomic(status_path, state)
    def one(shard: tuple[str, str], pass_index: int) -> dict:
        task, kind = shard
        result = uv_stage(
            task,
            kind,
            "revise",
            assignment_workers,
            path / f"revise-pass-{pass_index}-{task}-{kind}.log",
        )
        result["pass"] = pass_index
        if result["exit_code"] == 0:
            try:
                result["completed_assignments"] = len(complete_shard(task, kind))
            except Exception as error:
                result["validation_error"] = f"{type(error).__name__}: {error}"
        with state_lock:
            state["tasks"][f"{task}-{kind}"] = result
            write_json_atomic(status_path, state)
        return result

    for pass_index in range(1, revision_recovery_passes() + 1):
        pending = incomplete_shards()
        if not pending:
            break
        reconciliation = reconcile_incomplete_shards(pending, pass_index)
        pass_record = {
            "pass": pass_index,
            "started_at": now(),
            "shards": [f"{task}-{kind}" for task, kind in pending],
            "rearmed": sum(len(row["rearmed"]) for row in reconciliation),
            "runtime_actions": sum(len(row["actions"]) for row in reconciliation),
        }
        state["passes"].append(pass_record)
        write_json_atomic(status_path, state)
        with ThreadPoolExecutor(max_workers=workers) as pool:
            futures = {pool.submit(one, shard, pass_index): shard for shard in pending}
            for future in as_completed(futures):
                result = future.result()
                print(json.dumps(result), flush=True)
        pass_record["finished_at"] = now()
        pass_record["remaining_shards"] = [
            f"{task}-{kind}" for task, kind in incomplete_shards()
        ]
        write_json_atomic(status_path, state)

    failures = incomplete_shards()
    state["finished_at"] = now()
    state["complete"] = not failures
    write_json_atomic(status_path, state)
    if failures:
        raise RuntimeError(f"Results40 revision retained incomplete shards: {list(failures)}")
    for task in TASKS:
        validate_task_match(task)
    write_json_atomic(RUN / "revision-completion.json", {
        "success": True,
        "job_id": os.environ["SLURM_JOB_ID"],
        "source_commit": clean_commit(),
        "assignment_count": 240,
        "tasks": list(TASKS),
        "configs": {f"{task}-{kind}": {"experiment_id": experiment(task, kind).experiment_id, "sha256": sha(config(task, kind))} for task, kind in SHARDS},
        "finished_at": now(),
    })


def check_revision_receipt() -> None:
    receipt = json.loads((RUN / "revision-completion.json").read_text())
    if (
        receipt.get("success") is not True
        or receipt.get("assignment_count") != 240
        or tuple(receipt.get("tasks", ())) != TASKS
    ):
        raise RuntimeError("Results40 revision completion receipt is unavailable")
    for task, kind in SHARDS:
        exp = experiment(task, kind)
        expected = {"experiment_id": exp.experiment_id, "sha256": sha(config(task, kind))}
        if receipt.get("configs", {}).get(f"{task}-{kind}") != expected:
            raise RuntimeError(f"Results40 completed config differs for {task}/{kind}")
        study = Path(exp.dag["revise"]["output_dir"])
        ledger = json.loads((study / "study.json").read_text())
        rows = terminal_records(exp, ledger)
        if len(rows) != 6 or any(row["status"] != "completed" for row in rows):
            raise RuntimeError(f"Results40 completed ledger differs for {task}/{kind}")


def audit(path: Path) -> None:
    check_revision_receipt()
    status_path = RUN / "audit-status.json"
    status = {
        "job_id": os.environ["SLURM_JOB_ID"],
        "started_at": now(),
        "panels": {
            "sol": list(SOL_PANEL),
            "gemini": list(GEMINI_PANEL),
            "sol_gemini": [*SOL_PANEL, *GEMINI_PANEL],
        },
        "scopes": {},
    }
    write_json_atomic(status_path, status)
    status_lock = threading.Lock()

    def provider_scopes(
        provider: str, models: tuple[str, ...]
    ) -> tuple[tuple[str, object], ...]:
        return tuple(
            (
                f"new20-{task}-{kind}-{provider}",
                scoped_experiment(
                    config(task, kind),
                    models,
                    RUN / f"audit-{provider}" / task / kind /
                    experiment(task, kind).experiment_id,
                ),
            )
            for task, kind in SHARDS
        )

    tracks = {
        "sol": (provider_scopes("sol", SOL_PANEL), 60),
        "gemini": (provider_scopes("gemini", GEMINI_PANEL), 3),
    }

    def one_track(provider: str) -> list[str]:
        scopes, workers = tracks[provider]
        failed = []
        for name, exp in scopes:
            result = audit_stage(name, exp, workers, path / f"detect-{name}.log")
            with status_lock:
                status["scopes"][name] = result
                write_json_atomic(status_path, status)
            print(json.dumps(result), flush=True)
            if result["exit_code"]:
                failed.append(name)
                break
        return failed

    failures = []
    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = {pool.submit(one_track, provider): provider for provider in tracks}
        for future in as_completed(futures):
            failures.extend(future.result())
    status["finished_at"] = now()
    status["complete"] = not failures
    write_json_atomic(status_path, status)
    if failures:
        raise RuntimeError(f"Results40 audit retained incomplete tasks: {failures}")
    sys.path.insert(0, str(ROOT / "scripts/diagnostics"))
    from check_audit_coverage import check
    coverage = {}
    for scopes, _workers in tracks.values():
        for name, exp in scopes:
            coverage[name] = check(
                Path(exp.dag["revise"]["output_dir"]),
                Path(exp.dag["detect"]["output_dir"]),
                expected_models=tuple(exp.outcome_audit["models"]),
            )
            if coverage[name].get("assignment_count") != 6:
                raise RuntimeError(f"{name} audit assignment coverage differs from 6")
    write_json_atomic(RUN / "audit-completion.json", {
        "success": True,
        "job_id": os.environ["SLURM_JOB_ID"],
        "source_commit": clean_commit(),
        "panels": status["panels"],
        "coverage": coverage,
        "finished_at": now(),
    })


def audit_opus_complete(path: Path) -> None:
    """Audit only native-complete shards while revision recovery is blocked."""

    completed = []
    skipped = []
    for task, kind in SHARDS:
        exp = experiment(task, kind)
        study = Path(exp.dag["revise"]["output_dir"])
        if not (study / "study.json").is_file():
            skipped.append((task, kind))
            continue
        ledger = json.loads((study / "study.json").read_text())
        rows = terminal_records(exp, ledger)
        if len(rows) != 6 or any(row.get("status") != "completed" for row in rows):
            skipped.append((task, kind))
            continue
        complete_shard(task, kind)
        completed.append((task, kind))
    if not completed:
        raise RuntimeError("no native-complete Results40 feedback shard is available for Opus audit")

    status_path = RUN / "audit-opus-partial-status.json"
    status = {
        "job_id": os.environ["SLURM_JOB_ID"],
        "started_at": now(),
        "model": OPUS_PANEL[0],
        "completed_revision_shards": [f"{task}-{kind}" for task, kind in completed],
        "skipped_incomplete_shards": [f"{task}-{kind}" for task, kind in skipped],
        "assignment_count": len(completed) * 6,
        "scopes": {},
    }
    write_json_atomic(status_path, status)
    failures = []
    coverage = {}
    for task, kind in completed:
        source = config(task, kind)
        exp = scoped_experiment(
            source,
            OPUS_PANEL,
            RUN / "audit-opus" / task / kind / experiment(task, kind).experiment_id,
        )
        name = f"new20-{task}-{kind}-opus"
        result = audit_stage(name, exp, 60, path / f"detect-{name}.log")
        status["scopes"][name] = result
        write_json_atomic(status_path, status)
        print(json.dumps(result), flush=True)
        if result["exit_code"]:
            failures.append(name)
            break
        sys.path.insert(0, str(ROOT / "scripts/diagnostics"))
        from check_audit_coverage import check
        coverage[name] = check(
            Path(exp.dag["revise"]["output_dir"]),
            Path(exp.dag["detect"]["output_dir"]),
            expected_models=OPUS_PANEL,
        )
        if coverage[name].get("assignment_count") != 6:
            raise RuntimeError(f"{name} Opus audit assignment coverage differs from 6")
    status["finished_at"] = now()
    status["complete_for_native_complete_shards"] = not failures
    write_json_atomic(status_path, status)
    if failures:
        raise RuntimeError(f"Results40 partial Opus audit retained incomplete scopes: {failures}")
    write_json_atomic(RUN / "audit-opus-partial-completion.json", {
        "success": True,
        "job_id": os.environ["SLURM_JOB_ID"],
        "source_commit": clean_commit(),
        "model": OPUS_PANEL[0],
        "completed_revision_shards": [f"{task}-{kind}" for task, kind in completed],
        "skipped_incomplete_shards": [f"{task}-{kind}" for task, kind in skipped],
        "assignment_count": len(completed) * 6,
        "coverage": coverage,
        "finished_at": now(),
    })


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("execute", "audit", "audit-opus-complete"))
    args = parser.parse_args()
    expected_cpus = int(os.environ.get("RESULT40_EXPECTED_CPUS", "32"))
    if not os.environ.get("SLURM_JOB_ID") or int(os.environ.get("SLURM_CPUS_PER_TASK", "0")) != expected_cpus:
        raise RuntimeError(f"Results40 production requires one {expected_cpus}-CPU Slurm allocation")
    commit = clean_commit()
    capacity = runtime("execute" if args.mode == "execute" else "audit")
    runtime_write_probe()
    for task, kind in SHARDS:
        exp = experiment(task, kind)
        if len(exp.execution_assignments) != 6 or tuple(exp.outcome_audit["models"]) != PANEL:
            raise RuntimeError(f"frozen Results40 task shard changed: {task}/{kind}")
    credentials(args.mode)
    path = owner(args.mode, commit, capacity)
    if args.mode == "execute":
        execute(path)
    elif args.mode == "audit":
        audit(path)
    else:
        audit_opus_complete(path)
    write_json_atomic(path / "completed.json", {"success": True, "finished_at": now()})


if __name__ == "__main__":
    main()
