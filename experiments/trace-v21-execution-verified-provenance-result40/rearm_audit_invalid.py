"""Archive exhausted Opus cardinality failures before native missing-only audit.

This private recovery operation never changes a scientific request.  It moves
only the complete failed-attempt evidence for rubric judgments that are absent
from an incomplete native summary after all three saved provider responses
failed the same criterion-line cardinality contract.  Native ``detect --resume``
then issues the unchanged missing judgment again while retaining every completed
record.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import sys

from rubric_gen.artifacts.serialization import write_json_atomic

MODEL = "claude-opus-5"
ERROR_FRAGMENT = "rubric criteria_text must contain exactly"
ATTEMPTS = (1, 2, 3)
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918")


def read_object(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"recovery input is not a regular file: {path}")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError(f"recovery input is not an object: {path}")
    return value


def plan_stage(stage: Path, archive: Path) -> list[dict[str, object]]:
    summary = read_object(stage / "summary.json")
    failures = summary.get("judge_failures")
    if summary.get("status") != "incomplete" or not isinstance(failures, list):
        return []
    actions = []
    for failure in failures:
        if (
            failure.get("model") != MODEL
            or failure.get("reason") != "judge-failed"
            or failure.get("error_type") != "RuntimeError"
        ):
            continue
        key = failure.get("judgment_key")
        if type(key) is not str or len(key) != 32:
            raise RuntimeError(f"invalid failed judgment key in {stage}")
        artifact = stage / "artifacts" / key
        if artifact.is_symlink() or not artifact.is_dir():
            raise RuntimeError(f"failed judgment artifact is unavailable: {artifact}")
        if list(artifact.rglob("evaluation.json")):
            raise RuntimeError(f"refusing to rearm a completed judgment: {artifact}")
        attempt_dirs = list(artifact.rglob("*.attempts"))
        failed_receipts = sorted(artifact.rglob("failed-attempt-*.json"))
        if len(attempt_dirs) != 1 or len(failed_receipts) != len(ATTEMPTS):
            raise RuntimeError(f"failed judgment attempt evidence is incomplete: {artifact}")
        attempt_dir = attempt_dirs[0]
        errors = []
        for number in ATTEMPTS:
            state = read_object(attempt_dir / f"attempt-{number:03d}.json")
            response = attempt_dir / f"attempt-{number:03d}.response.json"
            receipt = read_object(attempt_dir.parent / f"failed-attempt-{number:03d}.json")
            if (
                state.get("attempt") != number
                or state.get("failure_category") != "invalid_response"
                or ERROR_FRAGMENT not in str(state.get("error"))
                or receipt.get("attempt") != number
                or receipt.get("error_type") != "FullRubricJudgeError"
                or ERROR_FRAGMENT not in str(receipt.get("error"))
                or response.is_symlink()
                or not response.is_file()
            ):
                raise RuntimeError(f"failed judgment is not the reviewed cardinality case: {artifact}")
            errors.append(str(receipt["error"]))
        destination = archive / key
        if destination.exists():
            raise RuntimeError(f"recovery archive already exists: {destination}")
        actions.append({
            "judgment_key": key,
            "model": MODEL,
            "live_artifact": str(artifact),
            "archive": str(destination),
            "saved_attempts": len(ATTEMPTS),
            "errors": errors,
        })
    return actions


def run(root: Path, receipt: Path) -> dict[str, object]:
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"audit root is unavailable: {root}")
    if receipt.exists():
        raise RuntimeError(f"audit recovery receipt already exists: {receipt}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    actions = []
    for summary in sorted(root.glob("**/rubric_score/summary.json")):
        stage = summary.parent
        archive = stage / "recovery-evidence" / f"invalid-response-rearm-{stamp}"
        actions.extend(plan_stage(stage, archive))
    if not actions:
        raise RuntimeError("no exhausted Opus cardinality failures require rearm")
    for action in actions:
        source = Path(str(action["live_artifact"]))
        destination = Path(str(action["archive"]))
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
    result = {
        "kind": "results40-audit-invalid-response-rearm",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": os.environ.get("RESULT40_SOURCE_COMMIT"),
        "provider_calls": 0,
        "request_semantics_changed": False,
        "model": MODEL,
        "actions": actions,
        "rearmed_judgments": len(actions),
    }
    write_json_atomic(receipt, result)
    return result


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("audit recovery must run through Slurm")
    root = RUN / "audit"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = RUN / f"audit-invalid-response-rearm-{stamp}.json"
    result = run(root, receipt)
    print(json.dumps({"rearmed_judgments": result["rearmed_judgments"], "receipt": str(receipt)}))


if __name__ == "__main__":
    main()
