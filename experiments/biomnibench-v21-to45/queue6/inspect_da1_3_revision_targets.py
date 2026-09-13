"""Read-only census of the four q6 failed revision targets."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "biomnibench-v21-to45-20260912/results30/da-1-3/study/"
    "biomnibench-da-factorial-r10-81712ed5ed7c/experiments/da-1-3"
)
TARGETS = (
    "rep-001/luna/full-static",
    "rep-001/luna/full-red-team-trace",
    "rep-002/luna/full-red-team-trace",
    "rep-003/luna/full-red-team-trace",
)
OUT = Path(__file__).resolve().parent / "da1-3-revision-target-inspection.json"


def main() -> int:
    rows = []
    for relative in TARGETS:
        path = ROOT / relative
        row = {"path": relative, "exists": path.exists(), "files": []}
        if path.exists():
            state = path / "state.json"
            if state.is_file():
                try:
                    row["state"] = json.loads(state.read_text(encoding="utf-8"))
                except Exception as exc:
                    row["state_error"] = f"{type(exc).__name__}: {exc}"
            for child in sorted(path.rglob("*")):
                if child.is_file():
                    item = {"relative": str(child.relative_to(path)), "size": child.stat().st_size}
                    if child.name == "manifest.json":
                        try:
                            item["json_valid"] = True
                            item["json"] = json.loads(child.read_text(encoding="utf-8"))
                        except Exception as exc:  # diagnostic only
                            item["json_valid"] = False
                            item["error"] = f"{type(exc).__name__}: {exc}"
                    row["files"].append(item)
        rows.append(row)
    result = {"root": str(ROOT), "provider_calls": 0, "targets": rows}
    OUT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(OUT), "targets": len(rows), "files": [len(r["files"]) for r in rows]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
