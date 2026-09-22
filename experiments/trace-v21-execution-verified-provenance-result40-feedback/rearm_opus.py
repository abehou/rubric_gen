"""Archive only reviewed failed Opus state before missing-only resume."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic

from make_configs import RUN, SHARDS
from run import OPUS_PANEL, experiment


MODEL = OPUS_PANEL[0]
CARDINALITY = "rubric criteria_text must contain exactly"
INCOMPLETE = "Anthropic response stopped before a complete answer"
CREDIT = "credit balance is too low"
DIRECT_ERRORS = {
    "model response contains no JSON object",
    "Anthropic returned an empty response",
}


def read_object(path: Path) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"recovery input is not a regular file: {path}")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError(f"recovery input is not an object: {path}")
    return value


def allowed_rubric_failure(state: dict[str, object]) -> bool:
    error = str(state.get("error", ""))
    category = state.get("failure_category")
    return (
        (category == "invalid_response" and CARDINALITY in error)
        or (category in {"configuration", "structural"} and CREDIT in error)
        or (category == "transient_connection" and INCOMPLETE in error)
    )


def rubric_actions(root: Path, archive: Path) -> list[dict[str, object]]:
    actions = []
    artifacts = root / "rubric_score/artifacts"
    records = root / "rubric_score/records"
    if not artifacts.is_dir():
        return actions
    for artifact in sorted(artifacts.iterdir()):
        if artifact.is_symlink() or not artifact.is_dir():
            raise RuntimeError(f"unsafe Opus rubric artifact: {artifact}")
        key = artifact.name
        if (records / f"{key}.json").is_file() or list(artifact.rglob("evaluation.json")):
            continue
        states = [
            read_object(path) for path in sorted(artifact.rglob("attempt-*.json"))
            if not path.name.endswith(".response.json")
            and not path.name.startswith("failed-attempt-")
        ]
        if not states:
            continue
        if not all(allowed_rubric_failure(state) for state in states):
            raise RuntimeError(f"unsupported missing Opus rubric failure: {artifact}")
        destination = archive / "rubric_score" / key
        if destination.exists():
            raise RuntimeError(f"Opus recovery archive already exists: {destination}")
        actions.append({
            "kind": "rubric_score",
            "source": str(artifact),
            "archive": str(destination),
            "saved_attempts": len(states),
        })
    return actions


def direct_actions(root: Path, archive: Path) -> list[dict[str, object]]:
    actions = []
    for summary_path in sorted(root.glob("direct_*/evaluations/*/summary.json")):
        summary = read_object(summary_path)
        stage = summary_path.parents[2].name
        for record in summary.get("records", []):
            if record.get("model") != MODEL or record.get("status") != "failed":
                continue
            case_id = record.get("case_id")
            if not isinstance(case_id, str) or not case_id:
                raise RuntimeError(f"invalid missing Opus direct case: {summary_path}")
            model_root = summary_path.parent / "cases" / case_id / MODEL
            if (model_root / "score.json").is_file():
                continue
            for attempt in sorted(model_root.glob("chunk-*/attempt-*.json")):
                state = read_object(attempt)
                error = str(state.get("error", ""))
                if not error:
                    continue
                if CREDIT not in error and error not in DIRECT_ERRORS:
                    raise RuntimeError(f"unsupported missing Opus RH failure: {attempt}")
                destination = archive / stage / case_id / attempt.relative_to(model_root)
                if destination.exists():
                    raise RuntimeError(f"Opus recovery archive already exists: {destination}")
                actions.append({
                    "kind": "direct_rh_attempt",
                    "source": str(attempt),
                    "archive": str(destination),
                })
    return actions


def plan() -> tuple[list[dict[str, object]], dict[str, int]]:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    expected = {(task, kind) for task, kind in SHARDS}
    actions = []
    for root in sorted((RUN / "audit-opus").glob("*/*/*")):
        task, kind, experiment_id = root.parts[-3:]
        if (task, kind) not in expected or experiment(task, kind).experiment_id != experiment_id:
            raise RuntimeError(f"unexpected partial Opus output root: {root}")
        archive = root / "recovery-evidence" / f"opus-missing-rearm-{stamp}"
        actions.extend(rubric_actions(root, archive))
        actions.extend(direct_actions(root, archive))
    counts: dict[str, int] = {}
    for action in actions:
        kind = str(action["kind"])
        counts[kind] = counts.get(kind, 0) + 1
    return actions, counts


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("plan", "apply"))
    args = parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Results40 Opus recovery must run through Slurm")
    actions, counts = plan()
    if not actions:
        raise RuntimeError("no reviewed partial Opus failure state requires rearm")
    if args.mode == "apply":
        for action in actions:
            source = Path(str(action["source"]))
            destination = Path(str(action["archive"]))
            destination.parent.mkdir(parents=True, exist_ok=True)
            source.rename(destination)
        receipt = RUN / f"opus-partial-rearm-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        write_json_atomic(receipt, {
            "provider_calls": 0,
            "request_semantics_changed": False,
            "model": MODEL,
            "counts": counts,
            "actions": actions,
        })
        print(json.dumps({"applied": True, "counts": counts, "receipt": str(receipt)}))
    else:
        print(json.dumps({"applied": False, "counts": counts, "actions": len(actions)}))


if __name__ == "__main__":
    main()
