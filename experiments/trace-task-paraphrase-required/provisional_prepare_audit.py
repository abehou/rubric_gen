"""Prepare a read-only scoped view for auditing the 16 completed Dev3 records.

The historical candidate study ledger is deliberately left untouched.  This
script creates hard-link views and a local NAS1 mirror of the already validated
task/paraphrase inputs so the audit can run without reading the stalled NAS8
mount.  It makes no provider calls.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path


BASE = Path("/home/aydanh/runs/trace-task-paraphrase-required-20260914")
CANONICAL = BASE / "canonical"
PROVISIONAL = BASE / "provisional-audit"
MIRROR = PROVISIONAL / "input-mirror"
TASK_SOURCE = Path("/home/aydanh/repos/rubric_gen/data/biomnibench-da")
PARAPHRASE_SOURCE = {
    "da-3-4": Path(
        "/home/aydanh/repos/rubric_gen/runs/autonomous-dev3-20260907/"
        "isolation-readers-smoke/paraphrases/tasks/da-3-4"
    ),
    "da-11-1": Path(
        "/home/aydanh/repos/rubric_gen/runs/autonomous-dev3-20260907/"
        "baseline-da11/paraphrases/tasks/da-11-1"
    ),
    "da-18-1": Path(
        "/home/aydanh/repos/rubric_gen/runs/babel-dev3-da18-inputs-20260908/"
        "paraphrase/tasks/da-18-1"
    ),
}
TASKS = ("da-3-4", "da-11-1", "da-18-1")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def copy_tree(src: Path, dst: Path, *, hardlink: bool = False) -> None:
    if not src.is_dir() or src.is_symlink():
        raise RuntimeError(f"expected regular source directory: {src}")
    if dst.exists() or dst.is_symlink():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(src, dst, copy_function=os.link if hardlink else shutil.copy2)


def copy_file(src: Path, dst: Path) -> None:
    if not src.is_file() or src.is_symlink():
        raise RuntimeError(f"expected regular source file: {src}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    if dst.exists():
        if digest(dst) != digest(src):
            raise RuntimeError(f"existing mirror differs: {dst}")
        return
    shutil.copy2(src, dst)


def validate_no_symlinks(root: Path) -> None:
    bad = [p for p in root.rglob("*") if p.is_symlink()]
    if bad:
        raise RuntimeError(f"mirror/view contains symlinks: {bad[:3]}")


def prepare_task_inputs(task: str, receipt: dict) -> None:
    task_src = TASK_SOURCE / task
    task_dst = MIRROR / "inputs" / "tasks" / task
    copy_tree(task_src, task_dst)
    pool_src = PARAPHRASE_SOURCE[task]
    if not pool_src.is_dir():
        raise RuntimeError(f"paraphrase pool is missing: {pool_src}")
    pool_dst = MIRROR / "inputs" / task / "paraphrase" / "tasks" / task
    pool_dst.mkdir(parents=True, exist_ok=True)
    hashes = []
    for index in range(5):
        for suffix in ("txt", "json"):
            src = pool_src / f"variant-{index:03d}.{suffix}"
            dst = pool_dst / src.name
            copy_file(src, dst)
        hashes.append(digest(pool_dst / f"variant-{index:03d}.txt"))
    # The native loader only needs the variant files for this audit, but retain
    # the producer manifest as an input provenance receipt when available.
    for candidate in (pool_src.parent.parent / "manifest.json", pool_src.parent / "manifest.json"):
        if candidate.is_file():
            copy_file(candidate, MIRROR / "inputs" / task / "paraphrase" / "manifest.json")
            break
    receipt[task] = {
        "task_source": str(task_src),
        "task_master_sha256": digest(task_src / "tests" / "rubric.txt"),
        "task_tree_destination": str(task_dst),
        "paraphrase_source": str(pool_src),
        "paraphrase_destination": str(pool_dst),
        "paraphrase_txt_sha256": hashes,
    }


def prepare_view(task: str, receipt: dict) -> None:
    source_root = next((CANONICAL / task / "study").glob("*"))
    source_ledger = json.loads((source_root / "study.json").read_text())
    records = source_ledger["records"]
    completed = [r for r in records if r.get("status") == "completed"]
    expected = 6 if task != "da-11-1" else 4
    if len(completed) != expected:
        raise RuntimeError(f"unexpected completed count for {task}: {len(completed)}")
    # The two Full da-11-1 rows are intentionally excluded by assignment ID;
    # they remain in the source ledger and are never changed.
    selected_ids = [r["assignment_id"] for r in completed]
    view = PROVISIONAL / "views" / task
    view.mkdir(parents=True, exist_ok=True)
    for name in ("shared-judgments", "pretreatment-rubrics"):
        copy_tree(source_root / name, view / name, hardlink=True)
    for record in records:
        if record["assignment_id"] not in selected_ids:
            continue
        src = source_root / record["experiment_dir"]
        copy_tree(src, view / record["experiment_dir"], hardlink=True)
    # Assignment status files are hard-linked above for compactness, but their
    # recorded workspaces point at the original study root.  Break only these
    # small view metadata links and bind each status to the copied workspace;
    # scientific manifests, state, and source study files remain untouched.
    for record in records:
        if record["assignment_id"] not in selected_ids:
            continue
        run_dir = view / record["experiment_dir"]
        for status_path in run_dir.glob("submissions/*/status.json"):
            status = json.loads(status_path.read_text())
            workspace = status.get("workspace_dir")
            expected = status_path.parent.parent / "workspace"
            if workspace != str(expected):
                status["workspace_dir"] = str(expected)
                temporary = status_path.with_suffix(".view-tmp")
                temporary.write_text(json.dumps(status, indent=2) + "\n")
                os.replace(temporary, status_path)
    view_ledger = dict(source_ledger)
    view_ledger["status"] = "completed_scope"
    view_ledger["execution_assignment_ids"] = selected_ids
    # This is a scoped consumer view: native source resolution binds the
    # pretreatment rubric root to the view itself, while all other source
    # identities remain those of the original experiment.
    view_ledger["pretreatment_rubric_root"] = str(view / "pretreatment-rubrics")
    view_ledger["finished_at"] = view_ledger.get("finished_at") or "provisional-audit"
    # Keep all original rows, identities and recorded paths.  Only the scoped
    # consumer root and terminal selection differ in this audit view.
    (view / "study.json").write_text(json.dumps(view_ledger, indent=2) + "\n")
    validate_no_symlinks(view)
    receipt[task]["source_study"] = str(source_root)
    receipt[task]["view_study"] = str(view)
    receipt[task]["selected_assignment_ids"] = selected_ids
    receipt[task]["selected_count"] = len(selected_ids)


def main() -> None:
    PROVISIONAL.mkdir(parents=True, exist_ok=True)
    receipt: dict = {
        "kind": "provisional-16-assignment-audit-input-view",
        "candidate": "attack_defense_v2.1_task_paraphrase_required",
        "tasks": list(TASKS),
        "provider_calls": 0,
        "source_ledger_unchanged": True,
    }
    for task in TASKS:
        prepare_task_inputs(task, receipt)
    for task in TASKS:
        prepare_view(task, receipt)
    validate_no_symlinks(MIRROR)
    receipt["mirror_root"] = str(MIRROR)
    receipt["view_root"] = str(PROVISIONAL / "views")
    receipt["mount_targets"] = {
        "tasks": "/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910/dev3/inputs/tasks",
        **{
            task: f"/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910/dev3/inputs/{task}/paraphrase"
            for task in TASKS
        },
    }
    out = PROVISIONAL / "input-view-receipt.json"
    out.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps({"stage": "provisional_audit_view_ready", "tasks": list(TASKS), "selected": 16, "receipt": str(out)}), flush=True)


if __name__ == "__main__":
    main()
