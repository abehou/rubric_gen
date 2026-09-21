"""Reconcile exact response-free runtime residue before Results40 resume."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import shutil

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.study import _exclusive_study_lease

from make_configs import RUN, SHARDS, config_path
from rubric_gen.submission_revision.experiment import load_experiment


LIVE = Path(
    "/data/user_data/aydanh/rubric_gen/live/"
    "rtt-result40-feedback-policies-20260920"
)
STARTUP_PREFIX = "Codex app-server start failed after 2 attempts:"
TMP_ERROR = "Codex tmp requires terminal-owner reconciliation: "
RESTORE_ERROR = "stale workspace restore path exists: "


def _read(path: Path) -> dict:
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def _within(path: Path, root: Path) -> bool:
    absolute = path.absolute()
    return absolute == root.absolute() or root.absolute() in absolute.parents


def _response_free_startup_failure(record: dict) -> bool:
    return (
        record.get("status") == "failed"
        and record.get("automatic_recovery_exhausted") is True
        and record.get("error_type") == "CodexProviderHealthError"
        and str(record.get("error", "")).startswith(STARTUP_PREFIX)
    )


def _workspace(experiment_dir: Path, live_root: Path) -> Path:
    manifest = _read(experiment_dir / "manifest.json")
    value = manifest.get("live_workspace_dir")
    if not isinstance(value, str):
        raise RuntimeError(f"revision manifest has no live workspace: {experiment_dir}")
    workspace = Path(value)
    if (
        not workspace.is_absolute()
        or workspace.name != "workspace"
        or not _within(workspace, live_root)
    ):
        raise RuntimeError(f"revision workspace is outside the owned live root: {workspace}")
    return workspace


def _reconcile_cli_tmp(
    assignment_id: str,
    workspace: Path,
    *,
    apply: bool,
) -> dict | None:
    temporary = workspace.parent / ".agent-state/codex/tmp"
    if not os.path.lexists(temporary):
        return None
    if not temporary.is_symlink():
        if temporary.is_dir():
            return None
        raise RuntimeError(f"Codex temporary path is neither a directory nor symlink: {temporary}")
    raw_target = temporary.readlink()
    target = raw_target if raw_target.is_absolute() else temporary.parent / raw_target
    if target.exists():
        raise RuntimeError(f"Codex temporary link still has a live target: {temporary} -> {raw_target}")
    backups = sorted(temporary.parent.glob(".tmp-preserved-*"))
    if len(backups) > 1 or any(path.is_symlink() or not path.is_dir() for path in backups):
        raise RuntimeError(f"ambiguous Codex temporary backups for {temporary}: {backups}")
    action = {
        "assignment_id": assignment_id,
        "kind": "codex_cli_tmp",
        "path": str(temporary),
        "stale_target": str(raw_target),
        "backup": str(backups[0]) if backups else None,
        "action": "restore_backup" if backups else "unlink_stale_runtime_link",
    }
    if apply:
        temporary.unlink()
        if backups:
            backups[0].rename(temporary)
    return action


def _archive_stale_restore(
    record: dict,
    experiment_dir: Path,
    workspace: Path,
    stamp: str,
    *,
    apply: bool,
) -> dict | None:
    error = str(record.get("error", ""))
    if record.get("error_type") != "RuntimeError" or not error.startswith(RESTORE_ERROR):
        return None
    restored = Path(error.removeprefix(RESTORE_ERROR))
    expected = workspace.parent / "workspace-restore"
    if restored != expected or not _within(restored, LIVE):
        raise RuntimeError(f"stale restore path differs from owned workspace: {restored}")
    action = {
        "assignment_id": record["assignment_id"],
        "kind": "workspace_restore",
        "path": str(restored),
        "action": "already_absent",
        "archive": None,
    }
    if not os.path.lexists(restored):
        return action
    if restored.is_symlink() or not restored.is_dir():
        raise RuntimeError(f"stale restore path is not a regular directory: {restored}")
    archive = experiment_dir / "runtime-recovery" / f"workspace-restore-{stamp}"
    if os.path.lexists(archive):
        raise RuntimeError(f"runtime recovery archive already exists: {archive}")
    action.update(action="archive_reconstructible_restore", archive=str(archive))
    if apply:
        archive.parent.mkdir(exist_ok=True)
        shutil.move(str(restored), str(archive))
    return action


def reconcile_study(study: Path, *, stamp: str, apply: bool) -> dict:
    result = {"study": str(study), "failed": [], "actions": [], "rearmed": []}
    if not study.is_dir():
        return result
    with _exclusive_study_lease(study):
        ledger_path = study / "study.json"
        ledger = _read(ledger_path)
        changed = False
        for record in ledger.get("records", []):
            if record.get("status") == "completed":
                continue
            result["failed"].append({
                key: record.get(key)
                for key in (
                    "assignment_id",
                    "status",
                    "error_type",
                    "error",
                    "failure_category",
                    "automatic_recovery_exhausted",
                )
            })
            experiment_dir = study / str(record["experiment_dir"])
            workspace = _workspace(experiment_dir, LIVE)
            if _response_free_startup_failure(record):
                action = _reconcile_cli_tmp(
                    str(record["assignment_id"]), workspace, apply=apply
                )
                if action is not None:
                    result["actions"].append(action)
                result["rearmed"].append(str(record["assignment_id"]))
                if apply:
                    record.update(
                        automatic_recovery_exhausted=False,
                        automatic_attempt_count=0,
                        next_automatic_action=(
                            "explicit missing-only resume after response-free "
                            "Codex app-server startup failure"
                        ),
                    )
                    changed = True
            restore = _archive_stale_restore(
                record, experiment_dir, workspace, stamp, apply=apply
            )
            if restore is not None:
                result["actions"].append(restore)
        if apply and changed:
            write_json_atomic(ledger_path, ledger)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Results40 reconciliation requires a Slurm compute node")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    studies = []
    for task, kind in SHARDS:
        experiment = load_experiment(config_path(task, kind))
        studies.append(
            reconcile_study(
                Path(experiment.dag["revise"]["output_dir"]),
                stamp=stamp,
                apply=args.apply,
            )
        )
    receipt = {
        "kind": "rtt-result40-feedback-response-free-runtime-reconciliation-v1",
        "applied": args.apply,
        "job_id": os.environ["SLURM_JOB_ID"],
        "time": datetime.now(timezone.utc).isoformat(),
        "failed_assignment_count": sum(len(row["failed"]) for row in studies),
        "action_count": sum(len(row["actions"]) for row in studies),
        "rearmed_count": sum(len(row["rearmed"]) for row in studies),
        "studies": [row for row in studies if row["failed"]],
    }
    owner = RUN / "owners" / f"reconcile-{os.environ['SLURM_JOB_ID']}"
    owner.mkdir(parents=True, exist_ok=False)
    write_json_atomic(owner / "receipt.json", receipt)
    print(json.dumps(receipt, indent=2), flush=True)


if __name__ == "__main__":
    main()
