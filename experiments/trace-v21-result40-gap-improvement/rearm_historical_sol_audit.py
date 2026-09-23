"""Archive response-free Sol audit failures before native missing-only resume.

The interrupted historical Sol+Gemini audit persisted exhausted OpenAI request
budgets for judgments that never produced provider material.  This private
recovery keeps every published judgment and moves only those response-free
operational attempts into immutable recovery evidence.  The unchanged native
recovery entrypoint can then issue only the still-missing Sol judgments.
"""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.audit_execution import audit_output_owner
from rubric_gen.submission_revision.experiment import load_experiment

from audit_inventory import model_coverage, saved_model_counts
from audit_sol_opus import clean_commit, validate_revision
from make_configs import RUN, SMOKE_TASK, TASKS, config_path


MODEL = "gpt-5.6-sol"
STAGES = (
    "rubric_score",
    "absolute_score",
    "pairwise_preference",
    "direct_full_trajectory",
    "direct_post_update",
    "direct_final_artifact",
    "direct_final_revision",
)
RETRYABLE_CATEGORIES = {"billing", "transient_connection", "transient_provider"}
EXACT_CREDIT_MARKERS = ("credit_balance_exhausted", "no credits remaining")
RETRYABLE_ERROR_MARKERS = (
    *EXACT_CREDIT_MARKERS,
    "connection error",
    "connection reset",
    "connection refused",
    "timed out",
    "timeout",
    "temporarily unavailable",
    "service unavailable",
)


def read_object(path: Path, label: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{label} is not a regular file: {path}")
    value = json.loads(path.read_text())
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} is not an object: {path}")
    return value


def _category(value: dict[str, object]) -> object:
    return value.get("failure_category", value.get("category"))


def _has_provider_material(value: dict[str, object]) -> bool:
    return any(value.get(key) is not None for key in (
        "generation", "records", "output", "response", "result"
    ))


def _attempt_model(value: dict[str, object]) -> object:
    identity = value.get("identity")
    if not isinstance(identity, dict):
        return None
    if identity.get("model") is not None:
        return identity.get("model")
    scoring = identity.get("scoring_identity")
    if isinstance(scoring, dict):
        return scoring.get("effective_judge_model")
    return None


def response_free_operational_attempt(path: Path) -> dict[str, object]:
    value = read_object(path, "Sol audit attempt")
    category = _category(value)
    error = str(value.get("error", ""))
    error_lower = error.lower()
    category_allowed = category in RETRYABLE_CATEGORIES or (
        category == "structural"
        and any(marker in error_lower for marker in EXACT_CREDIT_MARKERS)
    )
    if (
        _attempt_model(value) != MODEL
        or not category_allowed
        or not error
        or not any(marker in error_lower for marker in RETRYABLE_ERROR_MARKERS)
        or _has_provider_material(value)
    ):
        raise RuntimeError(f"attempt is not a reviewed response-free operational failure: {path}")
    return {
        "path": str(path),
        "sha256": sha256_file(path),
        "attempt": value.get("attempt"),
        "category": category,
        "error_type": value.get("error_type"),
        "error": error,
        "provider_material": False,
    }


def _nested_semantic_actions(root: Path, archive: Path) -> list[dict[str, object]]:
    actions = []
    stage = root / "rubric_score"
    for artifact in sorted((stage / "artifacts").glob("*")):
        if artifact.is_symlink() or not artifact.is_dir():
            continue
        key = artifact.name
        record = stage / "records" / f"{key}.json"
        if record.exists():
            continue
        if list(artifact.rglob("evaluation.json")):
            raise RuntimeError(f"refusing to rearm a completed Sol rubric judgment: {artifact}")
        if list(artifact.rglob("*.response.json")):
            raise RuntimeError(f"refusing to archive Sol rubric provider material: {artifact}")
        attempts = sorted(
            path for path in artifact.rglob("attempt-*.json")
            if not path.name.startswith("failed-attempt-")
        )
        if not attempts:
            continue
        if _attempt_model(read_object(attempts[0], "Sol audit attempt")) != MODEL:
            continue
        evidence = [response_free_operational_attempt(path) for path in attempts]
        destination = archive / "rubric_score" / key
        actions.append({
            "stage": "rubric_score",
            "judgment_key": key,
            "sources": [str(artifact)],
            "archive": str(destination),
            "attempts": evidence,
            "saved_attempts": len(evidence),
        })
    return actions


def _flat_semantic_actions(root: Path, archive: Path) -> list[dict[str, object]]:
    actions = []
    for stage_name in ("absolute_score", "pairwise_preference"):
        stage = root / stage_name
        for attempt_root in sorted((stage / "attempts").glob("*")):
            if attempt_root.is_symlink() or not attempt_root.is_dir():
                continue
            key = attempt_root.name
            record = stage / "records" / f"{key}.json"
            if record.exists():
                continue
            attempts = sorted(attempt_root.glob("attempt-*.json"))
            if not attempts:
                continue
            if _attempt_model(read_object(attempts[0], "Sol audit attempt")) != MODEL:
                continue
            states = [read_object(path, "Sol audit attempt") for path in attempts]
            failed = [
                path for path, value in zip(attempts, states, strict=True)
                if not _has_provider_material(value)
            ]
            if not failed:
                raise RuntimeError(
                    f"missing Sol judgment has provider material but no "
                    f"response-free failure: {attempt_root}"
                )
            evidence = [response_free_operational_attempt(path) for path in failed]
            destination = archive / stage_name / key
            actions.append({
                "stage": stage_name,
                "judgment_key": key,
                "source_root": str(attempt_root),
                "sources": [str(path) for path in failed],
                "archive": str(destination),
                "attempts": evidence,
                "saved_attempts": len(evidence),
                "preserved_provider_attempts": len(attempts) - len(failed),
            })
    return actions


def _direct_actions(root: Path, archive: Path) -> list[dict[str, object]]:
    actions = []
    for stage_name in STAGES[3:]:
        stage = root / stage_name
        for model_root in sorted((stage / "evaluations").glob(f"*/cases/*/{MODEL}")):
            if model_root.is_symlink() or not model_root.is_dir():
                continue
            score = model_root / "score.json"
            if score.exists():
                continue
            attempts = sorted(model_root.glob("*/attempt-*.json"))
            if not attempts:
                continue
            states = [read_object(path, "Sol audit attempt") for path in attempts]
            failed = [
                path for path, value in zip(attempts, states, strict=True)
                if not _has_provider_material(value)
            ]
            if not failed:
                raise RuntimeError(
                    f"missing Sol direct judgment has provider material but no "
                    f"response-free failure: {model_root}"
                )
            evidence = [response_free_operational_attempt(path) for path in failed]
            case_id = model_root.parent.name
            sources = [str(path) for path in failed]
            actions.append({
                "stage": stage_name,
                "judgment_key": case_id,
                "source_root": str(model_root),
                "sources": sources,
                "archive": str(archive / stage_name / case_id / MODEL),
                "attempts": evidence,
                "saved_attempts": len(evidence),
                "preserved_provider_attempts": len(attempts) - len(failed),
            })
    return actions


def plan(
    root: Path,
    archive: Path,
) -> tuple[list[dict[str, object]], dict[str, int], dict[str, int]]:
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"historical audit root is unavailable: {root}")
    coverage = model_coverage(saved_model_counts(root), MODEL)
    missing = {
        stage: int(row["missing"])
        for stage, row in coverage["stages"].items()
    }
    actions = (
        _nested_semantic_actions(root, archive)
        + _flat_semantic_actions(root, archive)
        + _direct_actions(root, archive)
    )
    observed = Counter(str(action["stage"]) for action in actions)
    expected = Counter({stage: count for stage, count in missing.items() if count})
    if any(observed[stage] > count for stage, count in expected.items()) or any(
        stage not in expected for stage in observed
    ):
        raise RuntimeError(
            f"response-free rearm scope differs from missing Sol inventory: "
            f"actions={dict(observed)}, missing={dict(expected)}"
        )
    untouched = {
        stage: count - observed[stage]
        for stage, count in expected.items()
        if count - observed[stage]
    }
    return actions, missing, untouched


def inspect_task(task: str, stamp: str) -> dict[str, object]:
    experiment = load_experiment(config_path(task))
    root = Path(experiment.dag["detect"]["output_dir"])
    archive = root / "recovery-evidence" / f"sol-audit-rearm-{stamp}"
    actions, missing, untouched = plan(root, archive)
    return {
        "task_id": task,
        "audit_root": str(root),
        "config_sha256": sha256_file(config_path(task)),
        "missing_by_stage": missing,
        "untouched_missing_by_stage": untouched,
        "rearm_judgments": len(actions),
        "saved_attempts": sum(int(action["saved_attempts"]) for action in actions),
        "archived_provider_material": 0,
        "preserved_provider_attempts": sum(
            int(action.get("preserved_provider_attempts", 0))
            for action in actions
        ),
        "actions": actions,
    }


def rearm_task(task: str, stamp: str) -> dict[str, object]:
    inspected = inspect_task(task, stamp)
    root = Path(str(inspected["audit_root"]))
    with audit_output_owner(root):
        inspected = inspect_task(task, stamp)
        for action in inspected["actions"]:
            destination = Path(str(action["archive"]))
            sources = [Path(str(source)) for source in action["sources"]]
            if len(sources) == 1 and sources[0].is_dir():
                destination.parent.mkdir(parents=True, exist_ok=True)
                sources[0].rename(destination)
                continue
            for source in sources:
                relative = source.relative_to(Path(str(action["source_root"])))
                target = destination / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                source.rename(target)
    return inspected


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("mode", choices=("inspect", "rearm"))
    parser.add_argument("--task", choices=TASKS, required=True)
    args = parser.parse_args()
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("historical Sol audit rearm must run through Slurm")
    if args.task == SMOKE_TASK:
        raise RuntimeError("smoke-task historical Sol audit is already complete")
    commit = clean_commit()
    validate_revision(args.task)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    if args.mode == "inspect":
        result = inspect_task(args.task, stamp)
        print(json.dumps({"source_commit": commit, "provider_calls": 0, **result}), flush=True)
        return
    if os.environ.get("RESULT40_OPENAI_CREDITS_CONFIRMED") != "1":
        raise RuntimeError("OpenAI credits must be explicitly confirmed before rearm")
    result = rearm_task(args.task, stamp)
    receipt = RUN / f"historical-sol-audit-rearm-{args.task}-{stamp}.json"
    payload = {
        "kind": "result40-gap-historical-sol-audit-rearm-v1",
        "source_commit": commit,
        "provider_calls": 0,
        "request_semantics_changed": False,
        "created_at": datetime.now(timezone.utc).isoformat(),
        **result,
    }
    write_json_atomic(receipt, payload)
    print(json.dumps({"receipt": str(receipt), **payload}), flush=True)


if __name__ == "__main__":
    main()
