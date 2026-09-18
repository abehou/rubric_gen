"""Reconcile only response-free Results40 runtime residue before native resume."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.study import _exclusive_study_lease

from make_configs import RUN, SHARDS, config_path
from rubric_gen.submission_revision.experiment import load_experiment


LIVE = Path("/data/user_data/aydanh/rubric_gen/live/rtt-result40-expansion-20260918")
TRANSPORT_ERROR = "Codex transport closed during an active turn"
TMP_ERROR = "Codex tmp requires terminal-owner reconciliation: "


def _within(path: Path, root: Path) -> bool:
    absolute = path.absolute()
    return absolute == root.absolute() or root.absolute() in absolute.parents


def _tmp_actions(record: dict, study: Path, live_root: Path, *, apply: bool) -> list[dict]:
    manifest_path = study / str(record["experiment_dir"]) / "manifest.json"
    if not manifest_path.is_file():
        return None
    manifest = json.loads(manifest_path.read_text())
    workspace_value = manifest.get("live_workspace_dir")
    candidates = []
    if isinstance(workspace_value, str):
        candidates.append(Path(workspace_value) / ".agent-state/codex/tmp")
    error = record.get("error")
    if isinstance(error, str) and TMP_ERROR in error:
        matches = re.findall(re.escape(TMP_ERROR) + r"([^\n]+)", error)
        if not matches:
            raise RuntimeError("saved Codex temporary reconciliation path is malformed")
        recorded = Path(matches[-1].strip())
        if not recorded.is_absolute():
            raise RuntimeError("saved Codex temporary reconciliation path is not absolute")
        candidates.append(recorded)
    results = []
    for temporary in dict.fromkeys(candidates):
        home = temporary.parent
        if not _within(home, live_root):
            raise RuntimeError(f"failed assignment Codex home is outside the Results40 live root: {home}")
        if not temporary.is_symlink():
            continue
        raw_target = temporary.readlink()
        target = raw_target if raw_target.is_absolute() else temporary.parent / raw_target
        if target.exists():
            raise RuntimeError(f"failed assignment still has a live Codex temporary target: {temporary} -> {raw_target}")
        backups = sorted(home.glob(".tmp-preserved-*"))
        if len(backups) > 1 or any(path.is_symlink() or not path.is_dir() for path in backups):
            raise RuntimeError(f"ambiguous Codex temporary backups for {temporary}: {backups}")
        results.append({
            "assignment_id": record["assignment_id"],
            "tmp": str(temporary),
            "stale_target": str(raw_target),
            "backup": str(backups[0]) if backups else None,
            "action": "restore_backup" if backups else "unlink_stale_runtime_link",
        })
        if apply:
            temporary.unlink()
            if backups:
                backups[0].rename(temporary)
    return results


def reconcile_study(study: Path, live_root: Path, *, apply: bool) -> dict:
    result = {"study": str(study), "failed": [], "tmp_actions": [], "rearmed": []}
    if not study.is_dir():
        return result
    with _exclusive_study_lease(study):
        ledger_path = study / "study.json"
        ledger = json.loads(ledger_path.read_text())
        changed = False
        for record in ledger["records"]:
            if record.get("status") == "completed":
                continue
            result["failed"].append({
                "assignment_id": record.get("assignment_id"),
                "status": record.get("status"),
                "error_type": record.get("error_type"),
                "error": record.get("error"),
                "failure_category": record.get("failure_category"),
                "automatic_recovery_exhausted": record.get("automatic_recovery_exhausted"),
            })
            actions = _tmp_actions(record, study, live_root, apply=apply)
            result["tmp_actions"].extend(actions)
            transport_closed = record.get("error") == TRANSPORT_ERROR
            startup_tmp_interrupted = (
                isinstance(record.get("error"), str)
                and str(record["error"]).startswith("Codex app-server start failed after 2 attempts:")
                and TMP_ERROR in str(record["error"])
                and bool(actions)
            )
            if (
                record.get("status") == "failed"
                and record.get("automatic_recovery_exhausted") is True
                and record.get("error_type") == "CodexProviderHealthError"
                and (transport_closed or startup_tmp_interrupted)
            ):
                result["rearmed"].append(record["assignment_id"])
                if apply:
                    record.update(
                        automatic_recovery_exhausted=False,
                        automatic_attempt_count=0,
                        next_automatic_action="explicit missing-only resume after response-free Codex transport closure",
                    )
                    changed = True
        if apply and changed:
            write_json_atomic(ledger_path, ledger)
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Results40 runtime reconciliation requires a Slurm compute node")
    studies = []
    for task, kind in SHARDS:
        experiment = load_experiment(config_path(task, kind))
        studies.append(reconcile_study(Path(experiment.dag["revise"]["output_dir"]), LIVE, apply=args.apply))
    receipt = {
        "kind": "rtt-result40-response-free-runtime-reconciliation-v1",
        "applied": args.apply,
        "job_id": os.environ["SLURM_JOB_ID"],
        "time": datetime.now(timezone.utc).isoformat(),
        "failed_assignment_count": sum(len(row["failed"]) for row in studies),
        "tmp_action_count": sum(len(row["tmp_actions"]) for row in studies),
        "rearmed_count": sum(len(row["rearmed"]) for row in studies),
        "studies": [row for row in studies if row["failed"]],
    }
    owner = RUN / "owners" / f"reconcile-{os.environ['SLURM_JOB_ID']}"
    owner.mkdir(parents=True, exist_ok=False)
    write_json_atomic(owner / "receipt.json", receipt)
    print(json.dumps(receipt, indent=2), flush=True)


if __name__ == "__main__":
    main()
