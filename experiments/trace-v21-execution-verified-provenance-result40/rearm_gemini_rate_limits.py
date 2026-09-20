"""Archive retryable Gemini operational failures before missing-only audit.

The initial original20 Gemini audit used 60 Google slots and exceeded the
provider's 20M input-token/minute quota.  This private recovery step preserves
all completed judgments and every failed response as recovery evidence.  It
removes only exhausted HTTP-429 or pre-request capacity-seal state so the
unchanged semantic requests can be issued again with four executor workers.
"""
from __future__ import annotations

from datetime import datetime, timezone
import json
import os
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic


MODEL = "gemini-3.8-flash"
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918")
RATE_LIMIT_MARKERS = (
    "HTTP 429",
    "RESOURCE_EXHAUSTED",
    "Quota exceeded",
    "shared capacity changed; refuse a split budget",
)


def read_object(path: Path) -> dict:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"recovery input is not a regular file: {path}")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError(f"recovery input is not an object: {path}")
    return value


def is_retryable_operational_failure(value: dict) -> bool:
    error = str(value.get("error", ""))
    return any(marker in error for marker in RATE_LIMIT_MARKERS)


def semantic_actions(root: Path, archive: Path) -> list[dict[str, object]]:
    actions: list[dict[str, object]] = []
    selected: set[Path] = set()
    for name in ("rubric_score", "absolute_score", "pairwise_preference"):
        for summary_path in sorted(root.glob(f"**/{name}/summary.json")):
            summary = read_object(summary_path)
            if summary.get("status") != "incomplete":
                continue
            stage = summary_path.parent
            for failure in summary.get("judge_failures", ()):
                if failure.get("model") != MODEL:
                    continue
                key = failure.get("judgment_key")
                if type(key) is not str or not key:
                    raise RuntimeError(f"invalid Gemini judgment key in {summary_path}")
                artifact = stage / "artifacts" / key
                if artifact.is_symlink() or not artifact.is_dir():
                    raise RuntimeError(f"failed Gemini artifact is unavailable: {artifact}")
                if list(artifact.rglob("evaluation.json")):
                    raise RuntimeError(f"refusing to rearm a completed Gemini judgment: {artifact}")
                attempts = sorted(artifact.rglob("attempt-*.json"))
                states = [
                    read_object(path)
                    for path in attempts
                    if not path.name.endswith(".response.json")
                    and not path.name.startswith("failed-attempt-")
                ]
                if not states or not all(is_retryable_operational_failure(state) for state in states):
                    raise RuntimeError(f"Gemini failure is not a supported operational case: {artifact}")
                destination = archive / "semantic" / name / key
                if destination.exists():
                    raise RuntimeError(f"recovery archive already exists: {destination}")
                actions.append({
                    "kind": "semantic_judgment",
                    "stage": name,
                    "judgment_key": key,
                    "source": str(artifact),
                    "archive": str(destination),
                    "saved_attempts": len(states),
                })
                selected.add(artifact)
        # A fatal provider-admission error can stop the stage before it writes
        # summary.json. Recover the same narrowly recognized saved failures
        # directly from their artifact directories in that case.
        for artifact in sorted(root.glob(f"**/{name}/artifacts/*")):
            if artifact in selected or artifact.is_symlink() or not artifact.is_dir():
                continue
            if list(artifact.rglob("evaluation.json")):
                continue
            attempts = sorted(artifact.rglob("attempt-*.json"))
            states = [
                read_object(path)
                for path in attempts
                if not path.name.endswith(".response.json")
                and not path.name.startswith("failed-attempt-")
            ]
            if not states or not all(is_retryable_operational_failure(state) for state in states):
                continue
            key = artifact.name
            destination = archive / "semantic" / name / key
            if destination.exists():
                raise RuntimeError(f"recovery archive already exists: {destination}")
            actions.append({
                "kind": "semantic_judgment",
                "stage": name,
                "judgment_key": key,
                "source": str(artifact),
                "archive": str(destination),
                "saved_attempts": len(states),
                "discovered_without_summary": True,
            })
        # Scalar absolute/pairwise stages persist provider attempts directly as
        # ``attempts/<semantic-key>/attempt-*.json``.  A fatal batch failure can
        # leave successful records plus only these failed attempt directories,
        # without summary.json or the older nested ``artifacts`` layout.  Treat
        # only record-free keys whose every saved attempt is the same narrowly
        # recognized operational failure as rearmable.
        for attempt_root in sorted(root.glob(f"**/{name}/attempts/*")):
            if attempt_root.is_symlink() or not attempt_root.is_dir():
                continue
            stage = attempt_root.parents[1]
            key = attempt_root.name
            completed = stage / "records" / f"{key}.json"
            if completed.exists():
                if completed.is_symlink() or not completed.is_file():
                    raise RuntimeError(
                        f"completed Gemini semantic record is not a regular file: {completed}"
                    )
                continue
            attempts = sorted(attempt_root.glob("attempt-*.json"))
            states = [read_object(path) for path in attempts]
            if not states or not all(is_retryable_operational_failure(state) for state in states):
                continue
            destination = (
                archive / "semantic-flat" / stage.relative_to(root) / "attempts" / key
            )
            if destination.exists():
                raise RuntimeError(f"recovery archive already exists: {destination}")
            actions.append({
                "kind": "semantic_judgment",
                "stage": name,
                "judgment_key": key,
                "source": str(attempt_root),
                "archive": str(destination),
                "saved_attempts": len(states),
                "discovered_without_summary": True,
                "storage_layout": "flat_attempts",
            })
    return actions


def direct_actions(root: Path, archive: Path) -> list[dict[str, object]]:
    actions: list[dict[str, object]] = []
    for summary_path in sorted(root.glob("**/direct_*/evaluations/*/summary.json")):
        summary = read_object(summary_path)
        stage = summary_path.parents[2]
        for record in summary.get("records", ()):
            if record.get("model") != MODEL or record.get("status") != "failed":
                continue
            case_id = record.get("case_id")
            if type(case_id) is not str or not case_id:
                raise RuntimeError(f"invalid failed Gemini direct case in {summary_path}")
            model_root = summary_path.parent / "cases" / case_id / MODEL
            score = model_root / "score.json"
            if score.exists():
                if score.is_symlink() or not score.is_file():
                    raise RuntimeError(f"completed Gemini direct judgment is not a regular file: {score}")
                # A stage may retain an earlier failed summary even after a
                # later attempt persisted a valid score.  Leave that score
                # untouched; native resume validates it and rebuilds the
                # summary without a provider call.
                continue
            failed = []
            for attempt in sorted(model_root.glob("chunk-*/attempt-*.json")):
                state = read_object(attempt)
                if state.get("error") is None:
                    continue
                if not is_retryable_operational_failure(state):
                    raise RuntimeError(f"Gemini direct failure is not a supported operational case: {attempt}")
                failed.append(attempt)
            if not failed:
                # Provider admission can fail before an attempt file is
                # created.  There is no persisted request to archive; native
                # resume already treats this case as missing work.
                continue
            for attempt in failed:
                relative = attempt.relative_to(model_root)
                destination = archive / "direct" / stage.name / case_id / MODEL / relative
                if destination.exists():
                    raise RuntimeError(f"recovery archive already exists: {destination}")
                actions.append({
                    "kind": "direct_attempt",
                    "stage": stage.name,
                    "case_id": case_id,
                    "source": str(attempt),
                    "archive": str(destination),
                    "saved_attempts": 1,
                })
    return actions


def run(root: Path, receipt: Path) -> dict[str, object]:
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"Gemini audit root is unavailable: {root}")
    if receipt.exists():
        raise RuntimeError(f"Gemini recovery receipt already exists: {receipt}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    archive = root / "recovery-evidence" / f"gemini-rate-limit-rearm-{stamp}"
    actions = semantic_actions(root, archive) + direct_actions(root, archive)
    if not actions:
        raise RuntimeError("no supported Gemini operational failures require rearm")
    for action in actions:
        source = Path(str(action["source"]))
        destination = Path(str(action["archive"]))
        destination.parent.mkdir(parents=True, exist_ok=True)
        source.rename(destination)
    result = {
        "kind": "results40-gemini-rate-limit-rearm",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_commit": os.environ.get("RESULT40_SOURCE_COMMIT"),
        "provider_calls": 0,
        "request_semantics_changed": False,
        "model": MODEL,
        "google_provider_concurrency": 60,
        "gemini_executor_workers": 4,
        "actions": actions,
        "rearmed_items": len(actions),
    }
    write_json_atomic(receipt, result)
    return result


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Gemini audit recovery must run through Slurm")
    root = RUN / "audit-gemini"
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    receipt = RUN / f"gemini-rate-limit-rearm-{stamp}.json"
    result = run(root, receipt)
    print(json.dumps({
        "rearmed_items": result["rearmed_items"],
        "receipt": str(receipt),
    }))


if __name__ == "__main__":
    main()
