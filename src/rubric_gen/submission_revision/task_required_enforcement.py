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
VERSIONS = {
    VERSION, REQUIREMENT_ONLY_VERSION, SOURCE_BOUND_VERSION,
    WITNESS_FROZEN_VERSION, DURABLE_VERSION, DURABLE_DELIVERY_VERSION,
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


def _execution_text(trajectory_path: Path):
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
                        freeze_witness=False):
    witness, witness_record = (
        frozen_execution_witness(output_dir, source_checkpoint)
        if freeze_witness else build_execution_witness(output_dir, source_checkpoint)
    )
    texts = {
        "task": instruction,
        "selected_rubric": original_rubric.content,
        "development_rubric": development_rubric.content,
        "artifact": artifact.content,
        "execution_witness": witness,
    }
    documents = {name: PublicDocument(name, text) for name, text in texts.items()}
    native_ids = {
        "task": "task-instruction",
        "selected_rubric": original_rubric.content_sha256,
        "development_rubric": development_rubric.content_sha256,
        "artifact": artifact.artifact_id,
        "execution_witness": witness_record["execution_witness_sha256"],
    }
    evidence = {
        "review_scope": "one_explicit_task_required_obligation",
        "public_sources": {name: document.model_record() for name, document in documents.items()},
        "source_manifest": source_manifest(documents, native_ids),
    }
    validator = EnforcementContract(
        "enforcement", enforcement_schema(documents), documents, native_ids
    )
    return evidence, validator, witness_record


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
