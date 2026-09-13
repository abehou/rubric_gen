"""Remove only the two explicitly obsolete runtime environments.

The prior cleanup reached the targets but failed at rmdir after leaving a
permission-protected residual.  Make each exact allowlisted tree owner-writable
and remove it; the active trace-repair environment is never touched.
"""
from __future__ import annotations

import json
import os
import shutil
import stat
from pathlib import Path

ROOT = Path("/data/user_data/aydanh/rubric_gen/cache/environments")
ACTIVE = ROOT / "trace-repair-10381602"
TARGETS = (
    ROOT / "a5f86d3f89f6256c-be8151e15cce-10380168",
    ROOT / "a5f86d3f89f6256c-d61735ca9b4a-10380169",
)
RECEIPT = Path(__file__).resolve().parent / "exact-cache-cleanup-receipt.json"


def make_writable(root: Path) -> None:
    for path in sorted(root.rglob("*"), key=lambda p: len(p.parts), reverse=True) + [root]:
        mode = stat.S_IRUSR | stat.S_IWUSR | (stat.S_IXUSR if path.is_dir() else 0)
        try:
            os.chmod(path, mode)
        except PermissionError as exc:
            raise RuntimeError(f"cannot make allowlisted cache writable: {path}") from exc


def main() -> int:
    removed, absent = [], []
    for target in TARGETS:
        if target == ACTIVE:
            raise RuntimeError("refusing active runtime environment")
        if not target.exists():
            absent.append(str(target))
            continue
        if target.is_symlink() or not target.is_dir():
            raise RuntimeError(f"refusing non-directory cache target: {target}")
        make_writable(target)
        shutil.rmtree(target)
        if target.exists():
            raise RuntimeError(f"allowlisted cache target remains: {target}")
        removed.append(str(target))
    receipt = {"removed": removed, "already_absent": absent, "active_preserved": str(ACTIVE), "allowlist": [str(p) for p in TARGETS]}
    RECEIPT.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(receipt, sort_keys=True), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
