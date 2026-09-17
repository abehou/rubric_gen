"""Deterministic execution witness and delivery selection for the enforced RTT."""

from __future__ import annotations

import json
import re
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic

from .artifacts import read_json_object
from .evolution_serialization import canonical_json
from .rubric_generation_store import rubric_generation_directory
from .task_required_enforced_schema import EnforcementContract, enforcement_schema
from .trace_defense_evidence_v2 import PublicDocument, source_manifest


VERSION = "attack_defense_v2.1_task_paraphrase_required_enforced"
REQUIREMENT_ONLY_VERSION = "attack_defense_v2.1_task_paraphrase_required_enforced_requirement_only"
SOURCE_BOUND_VERSION = (
    "attack_defense_v2.1_task_paraphrase_required_enforced_"
    "requirement_only_source_bound"
)
WITNESS_FROZEN_VERSION = (
    "attack_defense_v2.1_task_paraphrase_required_enforced_"
    "requirement_only_witness_frozen"
)
DURABLE_VERSION = (
    "attack_defense_v2.1_task_paraphrase_required_enforced_"
    "requirement_only_durable"
)
DURABLE_DELIVERY_VERSION = (
    "attack_defense_v2.1_task_paraphrase_required_enforced_"
    "requirement_only_durable_delivery"
)
EXECUTION_VERIFIED_VERSION = "attack_defense_v2.1_execution_verified"
EXECUTION_VERIFIED_PROACTIVE_VERSION = (
    "attack_defense_v2.1_execution_verified_proactive"
)
EXECUTION_VERIFIED_VERSIONS = {
    EXECUTION_VERIFIED_VERSION,
    EXECUTION_VERIFIED_PROACTIVE_VERSION,
}
VERSIONS = {
    VERSION, REQUIREMENT_ONLY_VERSION, SOURCE_BOUND_VERSION,
    WITNESS_FROZEN_VERSION, DURABLE_VERSION, DURABLE_DELIVERY_VERSION,
    *EXECUTION_VERIFIED_VERSIONS,
}
_MAX_COMMAND_CHARS = 1_800
_MAX_WITNESS_CHARS = 60_000
_ERROR_LINE = re.compile(
    r"traceback|\berror\b|exception|failed|failure|not found|no such file|nan|warning",
    re.IGNORECASE,
)


def _shorten(text: str, maximum: int) -> tuple[str, bool]:
    if len(text) <= maximum:
        return text, False
    head = maximum // 2
    tail = maximum - head
    return text[:head] + "\n...[host truncation]...\n" + text[-tail:], True


def _command_items(value):
    if isinstance(value, dict):
        if value.get("type") == "command_execution" and value.get("status") == "completed":
            yield value
        for child in value.values():
            yield from _command_items(child)
    elif isinstance(value, list):
        for child in value:
            yield from _command_items(child)


def _execution_items(trajectory_path: Path):
    records, seen, parse_errors = [], set(), 0
    for line in trajectory_path.read_text(encoding="utf-8").splitlines():
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            parse_errors += 1
            continue
        for item in _command_items(event):
            identity = (
                item.get("id"), item.get("command"), item.get("exit_code"),
                item.get("aggregated_output", ""),
            )
            if identity in seen:
                continue
            seen.add(identity)
            records.append(item)
    return records, parse_errors


def _execution_text(trajectory_path: Path):
    records, parse_errors = _execution_items(trajectory_path)
    blocks, command_truncations = [], 0
    for index, item in enumerate(records, 1):
        command, command_cut = _shorten(str(item.get("command", "")), _MAX_COMMAND_CHARS // 2)
        output = str(item.get("aggregated_output", ""))
        if len(output) > _MAX_COMMAND_CHARS:
            notable = "\n".join(line for line in output.splitlines() if _ERROR_LINE.search(line))
            excerpt, output_cut = _shorten(output, _MAX_COMMAND_CHARS)
            if notable:
                notable, _ = _shorten(notable, _MAX_COMMAND_CHARS // 2)
                excerpt += "\n[host-selected diagnostic lines]\n" + notable
        else:
            excerpt, output_cut = output, False
        command_truncations += int(command_cut or output_cut)
        blocks.append(
            f"COMMAND {index} status=completed exit_code={item.get('exit_code')!r}\n"
            f"$ {command}\nOUTPUT:\n{excerpt or '[no captured output]'}"
        )
    text = "\n\n".join(blocks) if blocks else "No completed command executions were captured."
    text, witness_truncated = _shorten(text, _MAX_WITNESS_CHARS)
    return text, {
        "completed_command_count": len(records),
        "trajectory_parse_error_count": parse_errors,
        "command_excerpt_truncation_count": command_truncations,
        "witness_truncated": witness_truncated,
    }


def _command_records(trajectory_path: Path):
    records, parse_errors = _execution_items(trajectory_path)
    commands = []
    for ordinal, item in enumerate(records, 1):
        command = str(item.get("command", ""))
        output = str(item.get("aggregated_output", ""))
        excerpt, truncated = _shorten(output, _MAX_COMMAND_CHARS)
        body = {
            "ordinal": ordinal,
            "provider_item_id": item.get("id"),
            "command": command,
            "command_sha256": sha256_text(command),
            "exit_code": item.get("exit_code"),
            "output_sha256": sha256_text(output),
            "output_bytes": len(output.encode("utf-8")),
            "output_excerpt": excerpt,
            "output_excerpt_truncated": truncated,
        }
        body["record_sha256"] = sha256_text(canonical_json(body))
        commands.append(body)
    return commands, parse_errors


def _generated_manifest(workspace: Path):
    entries = []
    if workspace.is_dir() and not workspace.is_symlink():
        for path in sorted(workspace.rglob("*")):
            relative = path.relative_to(workspace)
            if not relative.parts or relative.parts[0] in {"data", ".agent-tmp"}:
                continue
            if relative.as_posix() == "instruction.md" or path.is_symlink() or not path.is_file():
                continue
            entries.append({
                "path": relative.as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })
    return entries


def build_execution_witness(output_dir: Path, source_checkpoint: int):
    submission_id = f"s{source_checkpoint:03d}"
    submission = output_dir / "submissions" / submission_id
    trajectory_path = submission / "trajectory.stream.jsonl"
    workspace = submission / "workspace"
    if trajectory_path.is_symlink() or not trajectory_path.is_file():
        raise RuntimeError(f"task-required enforcement lacks trajectory: {trajectory_path}")
    execution_text, accounting = _execution_text(trajectory_path)
    generated = _generated_manifest(workspace)
    manifest_text = canonical_json({"generated_files": generated})
    witness_text = execution_text + "\n\nGENERATED FILE MANIFEST\n" + manifest_text + "\n"
    return witness_text, {
        "submission_id": submission_id,
        "trajectory_path": str(trajectory_path),
        "trajectory_sha256": sha256_file(trajectory_path),
        "execution_witness_sha256": sha256_text(witness_text),
        "generated_files": generated,
        **accounting,
    }


def frozen_execution_witness(output_dir: Path, source_checkpoint: int):
    """Persist the pre-cleanup witness and replay it during final validation."""
    submission_id = f"s{source_checkpoint:03d}"
    submission = output_dir / "submissions" / submission_id
    snapshot_path = submission / "snapshot.json"
    snapshot = read_json_object(snapshot_path, "submission snapshot")
    workspace_sha256 = snapshot.get("workspace_sha256")
    if (snapshot.get("submission_id") != submission_id
            or not isinstance(workspace_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", workspace_sha256)):
        raise RuntimeError("task-required enforcement snapshot binding is invalid")
    path = output_dir / "task-required-enforcement-witnesses" / f"{submission_id}.json"
    if path.is_file() and not path.is_symlink():
        payload = read_json_object(path, "frozen task-required execution witness")
        if set(payload) != {"kind", "source_checkpoint", "witness", "record"}:
            raise RuntimeError("frozen task-required witness fields changed")
        witness, record = payload["witness"], payload["record"]
    elif path.exists() or path.is_symlink():
        raise RuntimeError("frozen task-required witness path is invalid")
    else:
        witness, record = build_execution_witness(output_dir, source_checkpoint)
        record.update({
            "snapshot_path": str(snapshot_path),
            "snapshot_sha256": sha256_file(snapshot_path),
            "snapshot_workspace_sha256": workspace_sha256,
            "frozen_witness_path": str(path),
        })
        payload = {
            "kind": "task-required-execution-witness-v1",
            "source_checkpoint": source_checkpoint,
            "witness": witness,
            "record": record,
        }
        write_json_atomic(path, payload)
    trajectory_path = submission / "trajectory.stream.jsonl"
    if payload.get("kind") != "task-required-execution-witness-v1":
        raise RuntimeError("frozen task-required witness kind changed")
    if (not isinstance(witness, str)
            or not isinstance(record, dict)
            or payload.get("source_checkpoint") != source_checkpoint
            or record.get("submission_id") != submission_id
            or record.get("trajectory_sha256") != sha256_file(trajectory_path)
            or record.get("execution_witness_sha256") != sha256_text(witness)
            or not isinstance(record.get("snapshot_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", record["snapshot_sha256"])
            or not isinstance(record.get("snapshot_workspace_sha256"), str)
            or not re.fullmatch(r"[0-9a-f]{64}", record["snapshot_workspace_sha256"])
            or record.get("frozen_witness_path") != str(path)):
        raise RuntimeError("frozen task-required witness binding changed")
    return witness, record


def execution_verified_witness(output_dir: Path, source_checkpoint: int):
    """Freeze an ordered witness whose command/file hashes support delta checks."""

    submission_id = f"s{source_checkpoint:03d}"
    submission = output_dir / "submissions" / submission_id
    trajectory_path = submission / "trajectory.stream.jsonl"
    snapshot_path = submission / "snapshot.json"
    snapshot = read_json_object(snapshot_path, "submission snapshot")
    workspace_sha256 = snapshot.get("workspace_sha256")
    if (snapshot.get("submission_id") != submission_id
            or not isinstance(workspace_sha256, str)
            or not re.fullmatch(r"[0-9a-f]{64}", workspace_sha256)):
        raise RuntimeError("execution-verified snapshot binding is invalid")
    path = output_dir / "execution-verified-witnesses" / f"{submission_id}.json"
    if path.is_file() and not path.is_symlink():
        payload = read_json_object(path, "execution-verified witness")
    elif path.exists() or path.is_symlink():
        raise RuntimeError("execution-verified witness path is invalid")
    else:
        witness, base = build_execution_witness(output_dir, source_checkpoint)
        commands, parse_errors = _command_records(trajectory_path)
        record = {
            **base,
            "command_records": commands,
            "structured_trajectory_parse_error_count": parse_errors,
            "snapshot_path": str(snapshot_path),
            "snapshot_sha256": sha256_file(snapshot_path),
            "snapshot_workspace_sha256": workspace_sha256,
            "frozen_witness_path": str(path),
            "source_checkpoint": source_checkpoint,
        }
        record["structured_evidence_sha256"] = sha256_text(canonical_json({
            "command_records": commands,
            "generated_files": record["generated_files"],
            "snapshot_workspace_sha256": workspace_sha256,
            "source_checkpoint": source_checkpoint,
        }))
        payload = {
            "kind": "execution-verified-witness-v1",
            "source_checkpoint": source_checkpoint,
            "witness": witness,
            "record": record,
        }
        write_json_atomic(path, payload)
    if set(payload) != {"kind", "source_checkpoint", "witness", "record"}:
        raise RuntimeError("execution-verified witness fields changed")
    witness, record = payload["witness"], payload["record"]
    if (payload["kind"] != "execution-verified-witness-v1"
            or payload["source_checkpoint"] != source_checkpoint
            or not isinstance(witness, str)
            or record.get("submission_id") != submission_id
            or record.get("source_checkpoint") != source_checkpoint
            or record.get("trajectory_sha256") != sha256_file(trajectory_path)
            or record.get("execution_witness_sha256") != sha256_text(witness)
            or record.get("frozen_witness_path") != str(path)
            or not isinstance(record.get("command_records"), list)
            or record.get("structured_evidence_sha256") != sha256_text(canonical_json({
                "command_records": record.get("command_records"),
                "generated_files": record.get("generated_files"),
                "snapshot_workspace_sha256": record.get("snapshot_workspace_sha256"),
                "source_checkpoint": source_checkpoint,
            }))):
        raise RuntimeError("execution-verified witness binding changed")
    return witness, record


def _active_prior_issue(output_dir: Path, source_checkpoint: int):
    if source_checkpoint < 1:
        return None
    path = output_dir / "execution-truthfulness-issues" / f"s{source_checkpoint - 1:03d}.json"
    if not path.is_file() or path.is_symlink():
        return None
    record = read_json_object(path, "prior execution-truthfulness issue")
    issue = record.get("issue")
    if record.get("kind") != "execution-truthfulness-issue-v1" or not isinstance(issue, dict):
        raise RuntimeError("prior execution-truthfulness issue is malformed")
    return issue if issue.get("status") == "active" else None


def active_execution_issue(output_dir: Path, submission_id: str) -> bool:
    path = output_dir / "execution-truthfulness-issues" / f"{submission_id}.json"
    if not path.is_file() or path.is_symlink():
        return False
    record = read_json_object(path, "execution-truthfulness issue")
    issue = record.get("issue")
    if record.get("kind") != "execution-truthfulness-issue-v1" or not isinstance(issue, dict):
        raise RuntimeError("execution-truthfulness issue is malformed")
    return issue.get("status") == "active"


def _execution_delta(output_dir: Path, source_checkpoint: int, current_record, prior_issue):
    prior_checkpoint = (
        None if prior_issue is None else prior_issue.get("last_checked_checkpoint")
    )
    prior_commands = set()
    prior_files = {}
    if isinstance(prior_checkpoint, int):
        _, prior_record = execution_verified_witness(output_dir, prior_checkpoint)
        prior_commands = {
            item["record_sha256"] for item in prior_record["command_records"]
        }
        prior_files = {
            item["path"]: item["sha256"] for item in prior_record["generated_files"]
        }
    new_commands = [
        item for item in current_record["command_records"]
        if item["record_sha256"] not in prior_commands
    ]
    current_files = {
        item["path"]: item for item in current_record["generated_files"]
    }
    changed_files = [
        {**item, "prior_sha256": prior_files.get(path)}
        for path, item in sorted(current_files.items())
        if prior_files.get(path) != item["sha256"]
    ]
    removed_files = sorted(set(prior_files) - set(current_files))
    body = {
        "kind": "execution-evidence-delta-v1",
        "feedback_source_checkpoint": prior_checkpoint,
        "current_source_checkpoint": source_checkpoint,
        "order_contract": (
            "new_commands are host-observed after the feedback attached to "
            "feedback_source_checkpoint and before the current submission snapshot"
        ),
        "new_command_count": len(new_commands),
        "new_commands": new_commands,
        "changed_generated_files": changed_files,
        "removed_generated_files": removed_files,
        "current_snapshot_workspace_sha256": current_record["snapshot_workspace_sha256"],
    }
    text, truncated = _shorten(canonical_json(body), _MAX_WITNESS_CHARS)
    return text, {
        "execution_delta_sha256": sha256_text(text),
        "new_command_count": len(new_commands),
        "changed_generated_file_count": len(changed_files),
        "removed_generated_file_count": len(removed_files),
        "delta_truncated": truncated,
        "feedback_source_checkpoint": prior_checkpoint,
    }


def current_submission_artifact(*, history, output_dir: Path, source_checkpoint: int):
    """Resolve the reviewed artifact from the attack's bound source hash.

    An attack is allowed to produce no distinct sidecar.  The red-team
    manifest still binds that checkpoint to the exact public submission, so
    enforcement must not depend on an included adversarial witness.
    """
    manifest_path = (
        output_dir / "red-team" / f"checkpoint-{source_checkpoint:04d}" /
        "manifest.json"
    )
    manifest = read_json_object(manifest_path, "red-team checkpoint manifest")
    digest = manifest.get("source_artifact_sha256")
    if manifest.get("checkpoint") != source_checkpoint:
        raise RuntimeError("task-required enforcement checkpoint binding changed")
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise RuntimeError("task-required enforcement source hash is invalid")
    matches = [item for item in history.artifacts if item.content_sha256 == digest]
    if len(matches) != 1:
        raise RuntimeError(
            "task-required enforcement requires exactly one source-bound artifact"
        )
    return matches[0], {
        "red_team_manifest_path": str(manifest_path),
        "red_team_manifest_sha256": sha256_file(manifest_path),
        "source_artifact_sha256": digest,
        "sidecar_included": manifest.get("included"),
    }


def enforcement_request(*, instruction, original_rubric, development_rubric,
                        artifact, output_dir, source_checkpoint,
                        freeze_witness=False, execution_verified=False):
    if execution_verified:
        witness, witness_record = execution_verified_witness(output_dir, source_checkpoint)
    else:
        witness, witness_record = (
            frozen_execution_witness(output_dir, source_checkpoint)
            if freeze_witness else build_execution_witness(output_dir, source_checkpoint)
        )
    prior_issue = _active_prior_issue(output_dir, source_checkpoint) if execution_verified else None
    delta_text, delta_record = (
        _execution_delta(output_dir, source_checkpoint, witness_record, prior_issue)
        if execution_verified else (None, None)
    )
    texts = {
        "task": instruction,
        "selected_rubric": original_rubric.content,
        "development_rubric": development_rubric.content,
        "artifact": artifact.content,
        "execution_witness": witness,
    }
    if execution_verified:
        texts["execution_delta"] = delta_text
        if prior_issue is not None:
            texts["prior_issue"] = canonical_json(prior_issue)
    documents = {name: PublicDocument(name, text) for name, text in texts.items()}
    native_ids = {
        "task": "task-instruction",
        "selected_rubric": original_rubric.content_sha256,
        "development_rubric": development_rubric.content_sha256,
        "artifact": artifact.artifact_id,
        "execution_witness": witness_record["execution_witness_sha256"],
    }
    if execution_verified:
        native_ids["execution_delta"] = delta_record["execution_delta_sha256"]
        if prior_issue is not None:
            native_ids["prior_issue"] = prior_issue["issue_id"]
    evidence = {
        "review_scope": (
            "one_execution_truthfulness_issue"
            if execution_verified else "one_explicit_task_required_obligation"
        ),
        "public_sources": {name: document.model_record() for name, document in documents.items()},
        "source_manifest": source_manifest(documents, native_ids),
    }
    validator = EnforcementContract(
        "enforcement", enforcement_schema(documents, execution_verified=execution_verified),
        documents, native_ids, execution_verified=execution_verified,
        prior_issue=prior_issue,
    )
    if execution_verified:
        witness_record["execution_delta"] = delta_record
        witness_record["prior_issue_id"] = (
            prior_issue["issue_id"] if prior_issue is not None else None
        )
    return evidence, validator, witness_record


def select_execution_verified(*, generation, root: Path):
    """Select and persist the one protected execution issue for this feedback."""

    if generation.red_team_trace_version not in EXECUTION_VERIFIED_VERSIONS:
        raise ValueError("execution-verified selection used for another recipe")
    path = rubric_generation_directory(root, generation.generation_round) / "evolution.json"
    evolution = read_json_object(path, "execution-verified generation")
    enforcement = evolution.get("task_required_enforcement")
    if not isinstance(enforcement, dict) or enforcement.get("status") != "valid_result":
        return None, [{"criterion_id": "execution_issue", "reason": "contract_exhausted",
                       "absent_numeric_literals": []}], None
    response = enforcement.get("response")
    if not isinstance(response, dict):
        raise RuntimeError("execution-verified enforcement response is missing")
    checkpoint = generation.source_checkpoint
    if not isinstance(checkpoint, int):
        raise RuntimeError("execution-verified generation lacks a source checkpoint")
    prior_issue = _active_prior_issue(root, checkpoint)
    status = response["prior_issue_status"]
    witness = enforcement["witness"]
    if response["decision"] == "correct":
        stable = {
            key: response[key] for key in (
                "requirement", "defect", "corrective_action",
                "preserve_supported_work", "if_execution_unavailable",
            )
        }
        issue_id = (
            prior_issue["issue_id"] if prior_issue is not None
            else "execution_" + sha256_text(canonical_json(stable))[:16]
        )
        issue = {
            "issue_id": issue_id,
            "status": "active",
            "source_checkpoint": (
                prior_issue["source_checkpoint"] if prior_issue is not None else checkpoint
            ),
            "last_checked_checkpoint": checkpoint,
            **stable,
            "public_evidence": response["public_evidence"],
            "enforcement_reason": response["reason"],
            "source_artifact_id": enforcement["source_artifact_id"],
            "source_artifact_sha256": witness["source_binding"]["source_artifact_sha256"],
            "source_witness_sha256": witness["execution_witness_sha256"],
            "execution_delta_sha256": witness["execution_delta"]["execution_delta_sha256"],
        }
        selection = {
            "criterion_id": issue_id,
            "source_generation": generation.generation_round,
            "category": 0,
            "points": -1,
            "previously_reminded": prior_issue is not None,
            "corrective": True,
            "protected_execution_issue": True,
            **{key: issue[key] for key in (
                "requirement", "defect", "public_evidence", "corrective_action",
                "preserve_supported_work", "if_execution_unavailable",
            )},
            "enforcement_decision": "correct",
            "prior_issue_status": status,
        }
        return selection, [], issue
    if prior_issue is not None:
        issue = {
            **prior_issue,
            "status": status,
            "resolved_checkpoint": checkpoint,
            "last_checked_checkpoint": checkpoint,
            "resolution_reason": response["reason"],
            "resolution_evidence_refs": enforcement["resolved_evidence"]["evidence_refs"],
            "source_artifact_id": enforcement["source_artifact_id"],
            "source_artifact_sha256": witness["source_binding"]["source_artifact_sha256"],
            "source_witness_sha256": witness["execution_witness_sha256"],
            "execution_delta_sha256": witness["execution_delta"]["execution_delta_sha256"],
        }
        return None, [], issue
    return None, [], None


def select_enforcement(*, generation, root: Path, instruction: str, numeric_literals):
    if generation.red_team_trace_version not in VERSIONS or generation.generation_round < 2:
        return None, []
    path = rubric_generation_directory(root, generation.generation_round) / "evolution.json"
    evolution = read_json_object(path, "task-required enforcement generation")
    record = evolution.get("task_required_enforcement")
    if not isinstance(record, dict) or record.get("status") != "valid_result":
        return None, []
    response = record.get("response")
    if not isinstance(response, dict) or response.get("decision") != "correct":
        return None, []
    requirement = response["requirement"]
    if generation.red_team_trace_version == VERSION:
        requirement += " Corrective action: " + response["corrective_action"]
    skipped = []
    if len(requirement) > 650:
        skipped.append({"criterion_id": "required_unselected", "reason": "requirement_exceeds_delivery_limit",
                        "absent_numeric_literals": []})
        return None, skipped
    extra = sorted(numeric_literals(requirement) - numeric_literals(instruction))
    if extra:
        skipped.append({"criterion_id": "required_unselected", "reason": "numeric_literal_absent_from_public_task",
                        "absent_numeric_literals": extra})
        return None, skipped
    identity = "required_" + sha256_text(requirement)[:16]
    return {
        "criterion_id": identity,
        "source_generation": generation.generation_round,
        "category": 0,
        "points": -1,
        "previously_reminded": False,
        "corrective": True,
        "requirement": requirement,
        "enforcement_decision": "correct",
    }, skipped
