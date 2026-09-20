"""Rearm only exhausted Opus RH outputs that contain no complete JSON verdict.

The saved provider responses and failure metadata are moved to an immutable
recovery-evidence directory.  Native ``detect --resume`` then issues the same
semantic request again while retaining every completed judgment.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic


MODEL = "claude-opus-5"
EXPECTED_FAILURES = 16
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918")
ERROR = "direct request exhausted 3 attempts: model response contains no JSON object"


def read_object(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"recovery input is not a regular file: {path}")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError(f"recovery input is not an object: {path}")
    return value


def plan(root: Path, archive: Path, *, expected: int = EXPECTED_FAILURES) -> list[dict[str, object]]:
    actions: list[dict[str, object]] = []
    seen: set[Path] = set()
    for summary_path in sorted(root.glob("**/direct_*/evaluations/*/summary.json")):
        summary = read_object(summary_path)
        for record in summary.get("records", ()):
            if record.get("model") != MODEL or record.get("status") != "failed":
                continue
            if (
                record.get("failure_category") != "structural"
                or record.get("error") != ERROR
                or record.get("max_attempts") != 3
            ):
                raise RuntimeError(f"unsupported Opus RH failure in {summary_path}: {record}")
            case_id = record.get("case_id")
            if type(case_id) is not str or not case_id:
                raise RuntimeError(f"invalid failed Opus RH case in {summary_path}")
            model_root = summary_path.parent / "cases" / case_id / MODEL
            if model_root in seen:
                raise RuntimeError(f"duplicate failed Opus RH case: {model_root}")
            if model_root.is_symlink() or not model_root.is_dir():
                raise RuntimeError(f"failed Opus RH directory is unavailable: {model_root}")
            score = model_root / "score.json"
            if score.exists():
                raise RuntimeError(f"refusing to rearm a completed Opus RH judgment: {score}")
            attempts = sorted(model_root.glob("chunk-*/attempt-*.json"))
            if len(attempts) != 3:
                raise RuntimeError(f"expected three exhausted Opus attempts: {model_root}")
            response_ids: list[str] = []
            for number, attempt in enumerate(attempts, start=1):
                state = read_object(attempt)
                generation = state.get("generation")
                if (
                    state.get("attempt") != number
                    or state.get("error") != "model response contains no JSON object"
                    or not isinstance(generation, dict)
                    or generation.get("requested_model") != MODEL
                    or state.get("remote_completion") != "confirmed"
                ):
                    raise RuntimeError(f"attempt is not the reviewed exhausted Opus case: {attempt}")
                response_id = generation.get("response_id")
                if type(response_id) is not str or not response_id:
                    raise RuntimeError(f"Opus attempt lacks a response id: {attempt}")
                response_ids.append(response_id)
            relative = model_root.relative_to(root)
            destination = archive / relative
            if destination.exists():
                raise RuntimeError(f"recovery archive already exists: {destination}")
            actions.append({
                "kind": "direct_rh_judgment",
                "window": summary.get("source", {}).get("window"),
                "case_id": case_id,
                "model": MODEL,
                "source": str(model_root),
                "archive": str(destination),
                "saved_attempts": 3,
                "response_ids": response_ids,
            })
            seen.add(model_root)
    if len(actions) != expected:
        raise RuntimeError(f"expected {expected} exhausted Opus RH judgments, found {len(actions)}")
    return actions


def run(root: Path, receipt: Path, *, expected: int = EXPECTED_FAILURES) -> dict[str, object]:
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"Opus audit root is unavailable: {root}")
    if receipt.exists():
        raise RuntimeError(f"Opus recovery receipt already exists: {receipt}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = root / "recovery-evidence" / f"opus-rh-json-rearm-{stamp}"
    actions = plan(root, archive, expected=expected)
    for action in actions:
        source = Path(str(action["source"]))
        destination = Path(str(action["archive"]))
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
    result = {
        "kind": "results40-opus-rh-json-rearm",
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
        raise RuntimeError("Opus RH recovery must run through Slurm")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = RUN / f"opus-rh-json-rearm-{stamp}.json"
    result = run(RUN / "audit", receipt)
    print(json.dumps({
        "rearmed_judgments": result["rearmed_judgments"],
        "receipt": str(receipt),
    }))


if __name__ == "__main__":
    main()
