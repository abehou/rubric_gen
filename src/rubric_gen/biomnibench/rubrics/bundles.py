"""Strict, read-only resolution of sealed task-rubric bundles."""

from __future__ import annotations

import json
import math
import re
from dataclasses import asdict, dataclass
from pathlib import Path

from rubric_gen.biomnibench.rubrics.prompts import (
    TaskRubricRequest,
    build_task_rubric_prompt,
)
from rubric_gen.biomnibench.rubrics.schema import (
    canonical_json,
    load_json_strict,
    parse_task_process_rubric,
    render_task_process_rubric,
    sha256_text,
    validate_rendered_task_process_rubric,
)


TASK_RUBRIC_BUNDLE_SCHEMA_VERSION = 1
TASK_RUBRIC_COMPILER_CONFIG_SCHEMA_VERSION = 1
TASK_RUBRIC_REWRITER_PROVENANCE_SCHEMA_VERSION = 1
TASK_RUBRIC_RESPONSE_METADATA_SCHEMA_VERSION = 1
TASK_RUBRIC_PROMPT_VERSION = "task-process-rubric-v1"
TASK_RUBRIC_PROVIDER = "google-gemini"

SAFE_TASK_ID_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
GENERATION_CODE_KEYS = {
    "gemini_client.py",
    "rubric_bundles.py",
    "rubric_scoring.py",
    "task_rubric_compiler.py",
    "task_rubric_prompts.py",
    "task_rubrics.py",
    "task_snapshots.py",
}
_PRE_BUNDLE_GENERATION_CODE_KEYS = {
    "gemini_client.py",
    "rubric_scoring.py",
    "task_rubric_compiler.py",
    "task_rubric_prompts.py",
    "task_rubrics.py",
    "task_snapshots.py",
}
_PRE_SNAPSHOT_GENERATION_CODE_KEYS = {
    "gemini_client.py",
    "rubric_scoring.py",
    "task_rubric_compiler.py",
    "task_rubric_prompts.py",
    "task_rubrics.py",
}
_PRE_PROMPT_GENERATION_CODE_KEYS = {
    "gemini_client.py",
    "rubric_scoring.py",
    "task_rubric_compiler.py",
    "task_rubrics.py",
}
_HISTORICAL_GENERATION_CODE_KEYS = {
    "perturbations.py",
    "rubric_scoring.py",
    "task_rubric_compiler.py",
    "task_rubrics.py",
}
_COMPILER_CONFIG_KEYS = {
    "api_key_env",
    "bundle_schema_version",
    "max_concurrency",
    "max_retries",
    "model",
    "prompt_version",
    "rewriter_provenance_sha256",
    "schema_version",
    "seed",
    "task_ids",
    "tasks_dir",
    "temperature",
}
_REWRITER_PROVENANCE_KEYS = {
    "schema_version",
    "provider",
    "model",
    "implementation_id",
    "implementation_sha256",
}
_RESPONSE_METADATA_KEYS = {
    "raw_response_sha256",
    "response_id",
    "schema_version",
    "served_model_version",
}


class RubricBundleError(ValueError):
    """Raised when a sealed rubric bundle cannot be trusted."""


@dataclass(frozen=True)
class ResolvedRubricBundle:
    task_id: str
    rubric_set_id: str
    rubric_id: str
    rubric_sha256: str
    rubric_json_path: Path
    rubric_json_text: str
    rendered_path: Path
    rendered_text: str
    task_manifest_path: Path
    task_manifest_sha256: str


def is_safe_task_id(task_id: object) -> bool:
    return isinstance(task_id, str) and bool(SAFE_TASK_ID_PATTERN.fullmatch(task_id))


def compilation_payload(
    config_sha256: str,
    generation_code_sha256: str,
    rewriter_provenance_sha256: str,
    tasks: dict[str, dict[str, str]],
) -> dict[str, object]:
    return {
        "compiler_config_sha256": config_sha256,
        "generation_code_sha256": generation_code_sha256,
        "rewriter_provenance_sha256": rewriter_provenance_sha256,
        "tasks": tasks,
    }


def _object(value: object, context: str) -> dict[str, object]:
    if type(value) is not dict:
        raise RubricBundleError(f"{context} must be an object")
    return value


def _string(value: object, context: str) -> str:
    if not isinstance(value, str):
        raise RubricBundleError(f"{context} must be a string")
    return value


def _hash(value: object, context: str) -> str:
    digest = _string(value, context)
    if not SHA256_PATTERN.fullmatch(digest):
        raise RubricBundleError(f"{context} must be a lowercase SHA-256 digest")
    return digest


def _closed_keys(value: dict[str, object], expected: set[str], context: str) -> None:
    if set(value) != expected:
        raise RubricBundleError(f"{context} has missing or unexpected fields")


def _validated_compiler_config(value: object) -> dict[str, object]:
    config = _object(value, "compiler config")
    _closed_keys(config, _COMPILER_CONFIG_KEYS, "compiler config")
    if (
        type(config["schema_version"]) is not int
        or config["schema_version"] != TASK_RUBRIC_COMPILER_CONFIG_SCHEMA_VERSION
    ):
        raise RubricBundleError("unsupported compiler config schema version")
    if (
        type(config["bundle_schema_version"]) is not int
        or config["bundle_schema_version"] != TASK_RUBRIC_BUNDLE_SCHEMA_VERSION
    ):
        raise RubricBundleError("compiler config bundle schema version mismatch")
    if config["prompt_version"] != TASK_RUBRIC_PROMPT_VERSION:
        raise RubricBundleError("compiler config prompt version mismatch")
    _hash(
        config["rewriter_provenance_sha256"],
        "compiler config rewriter provenance sha256",
    )
    for field_name in ("api_key_env", "model", "tasks_dir"):
        if type(config[field_name]) is not str or not config[field_name]:
            raise RubricBundleError(f"compiler config {field_name} must be a string")
    task_ids = config["task_ids"]
    if (
        type(task_ids) is not list
        or not task_ids
        or any(not is_safe_task_id(task_id) for task_id in task_ids)
        or len(set(task_ids)) != len(task_ids)
    ):
        raise RubricBundleError("compiler config task_ids is invalid")
    if type(config["max_retries"]) is not int or config["max_retries"] < 0:
        raise RubricBundleError("compiler config max_retries is invalid")
    if type(config["max_concurrency"]) is not int or config["max_concurrency"] < 1:
        raise RubricBundleError("compiler config max_concurrency is invalid")
    if type(config["seed"]) is not int:
        raise RubricBundleError("compiler config seed is invalid")
    temperature = config["temperature"]
    if (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float))
        or not math.isfinite(temperature)
    ):
        raise RubricBundleError("compiler config temperature is invalid")
    return config


def _validated_rewriter_provenance(value: object) -> dict[str, object]:
    raw = _object(value, "rewriter provenance")
    _closed_keys(raw, _REWRITER_PROVENANCE_KEYS, "rewriter provenance")
    if (
        type(raw["schema_version"]) is not int
        or raw["schema_version"] != TASK_RUBRIC_REWRITER_PROVENANCE_SCHEMA_VERSION
    ):
        raise RubricBundleError("unsupported rewriter provenance schema version")
    for field_name in ("provider", "model", "implementation_id"):
        field_value = raw[field_name]
        if type(field_value) is not str or not field_value.strip():
            raise RubricBundleError(
                f"rewriter provenance {field_name} must be non-empty"
            )
    _hash(
        raw["implementation_sha256"],
        "rewriter provenance implementation_sha256",
    )
    return raw


def _validated_response_metadata(value: object) -> dict[str, object]:
    metadata = _object(value, "response metadata")
    _closed_keys(metadata, _RESPONSE_METADATA_KEYS, "response metadata")
    if (
        type(metadata["schema_version"]) is not int
        or metadata["schema_version"] != TASK_RUBRIC_RESPONSE_METADATA_SCHEMA_VERSION
    ):
        raise RubricBundleError("unsupported response metadata schema version")
    _hash(metadata["raw_response_sha256"], "response metadata raw-response hash")
    for field_name in ("served_model_version", "response_id"):
        field_value = metadata[field_name]
        if field_value is not None and (
            type(field_value) is not str or not field_value.strip()
        ):
            raise RubricBundleError(
                f"response metadata {field_name} must be null or a non-empty string"
            )
    return metadata


def _validated_generation_code_sha256s(value: object) -> dict[str, str]:
    raw_hashes = _object(value, "generation code hashes")
    key_set = set(raw_hashes)
    if key_set not in (
        GENERATION_CODE_KEYS,
        _PRE_BUNDLE_GENERATION_CODE_KEYS,
        _PRE_SNAPSHOT_GENERATION_CODE_KEYS,
        _PRE_PROMPT_GENERATION_CODE_KEYS,
        _HISTORICAL_GENERATION_CODE_KEYS,
    ):
        raise RubricBundleError(
            "generation code hashes has missing or unexpected fields"
        )
    return {
        module_name: _hash(raw_hashes[module_name], f"generation code {module_name}")
        for module_name in sorted(key_set)
    }


_ROOT_TASK_ENTRY_KEYS = {
    "input_sha256",
    "response_metadata_sha256",
    "rubric_id",
    "rubric_sha256",
    "snapshot_sha256",
    "task_manifest_path",
    "task_manifest_sha256",
}


def _validated_root_task_entries(
    tasks: dict[str, object],
) -> tuple[
    dict[str, dict[str, object]],
    dict[str, dict[str, str]],
    dict[str, dict[str, str]],
]:
    entries: dict[str, dict[str, object]] = {}
    compilation_tasks: dict[str, dict[str, str]] = {}
    identity_tasks: dict[str, dict[str, str]] = {}
    for member_id, raw_entry in sorted(tasks.items()):
        if not is_safe_task_id(member_id):
            raise RubricBundleError(f"unsafe root task ID: {member_id!r}")
        entry = _object(raw_entry, f"root task entry {member_id}")
        _closed_keys(entry, _ROOT_TASK_ENTRY_KEYS, f"root task entry {member_id}")
        input_sha256 = _hash(entry["input_sha256"], f"root input hash {member_id}")
        response_metadata_sha256 = _hash(
            entry["response_metadata_sha256"],
            f"root response metadata hash {member_id}",
        )
        rubric_id = _hash(entry["rubric_id"], f"root rubric ID {member_id}")
        rubric_sha256 = _hash(
            entry["rubric_sha256"],
            f"root rubric hash {member_id}",
        )
        if rubric_id != rubric_sha256:
            raise RubricBundleError(f"root rubric ID mismatch for {member_id}")
        snapshot_sha256 = _hash(
            entry["snapshot_sha256"],
            f"root snapshot hash {member_id}",
        )
        expected_manifest_path = f"tasks/{member_id}/manifest.json"
        if entry["task_manifest_path"] != expected_manifest_path:
            raise RubricBundleError("task manifest path is not canonical")
        _hash(
            entry["task_manifest_sha256"],
            f"root task manifest hash {member_id}",
        )
        entries[member_id] = entry
        compilation_tasks[member_id] = {
            "input_sha256": input_sha256,
            "snapshot_sha256": snapshot_sha256,
        }
        identity_tasks[member_id] = {
            "input_sha256": input_sha256,
            "response_metadata_sha256": response_metadata_sha256,
            "rubric_id": rubric_id,
            "snapshot_sha256": snapshot_sha256,
        }
    return entries, compilation_tasks, identity_tasks


def _read_json_object(path: Path, context: str) -> dict[str, object]:
    return _read_json_object_bytes(_read_regular_bytes(path, context), context)


def read_bundle_json_object(path: Path, context: str) -> dict[str, object]:
    """Read one strict, nonsymlink JSON object from a bundle."""
    return _read_json_object(path, context)


def _read_regular_bytes(path: Path, context: str) -> bytes:
    if path.is_symlink() or not path.is_file():
        raise RubricBundleError(f"missing regular {context}: {path}")
    try:
        return path.read_bytes()
    except OSError as exc:
        raise RubricBundleError(f"invalid {context}: {exc}") from exc


def _decode_json_bytes(raw: bytes, context: str) -> object:
    try:
        return load_json_strict(raw.decode("utf-8"))
    except (UnicodeError, ValueError) as exc:
        raise RubricBundleError(f"invalid {context}: {exc}") from exc


def _read_json_object_bytes(raw: bytes, context: str) -> dict[str, object]:
    value = _decode_json_bytes(raw, context)
    return _object(value, context)


def _read_json_string_list(path: Path, context: str) -> list[str]:
    return _read_json_string_list_bytes(_read_regular_bytes(path, context), context)


def _read_json_string_list_bytes(raw: bytes, context: str) -> list[str]:
    value = _decode_json_bytes(raw, context)
    if type(value) is not list or any(not isinstance(item, str) for item in value):
        raise RubricBundleError(f"{context} must be an array of strings")
    return value


def _sha256_bytes(raw: bytes) -> str:
    import hashlib

    return hashlib.sha256(raw).hexdigest()


def _artifact_path(task_dir: Path, relative: str) -> Path:
    candidate = Path(relative)
    if (
        candidate.is_absolute()
        or ".." in candidate.parts
        or candidate.as_posix() != relative
    ):
        raise RubricBundleError(f"invalid artifact path: {relative!r}")
    path = task_dir.joinpath(*candidate.parts)
    try:
        if path.resolve(strict=True).is_relative_to(task_dir.resolve(strict=True)):
            return path
    except (OSError, RuntimeError):
        pass
    raise RubricBundleError(f"artifact leaves task bundle: {relative!r}")


def _validate_snapshot_attestation(
    task_id: str,
    task_manifest: dict[str, object],
    artifact_bytes: dict[str, bytes],
) -> None:
    snapshot_record = _object(task_manifest["snapshot"], "snapshot record")
    _closed_keys(
        snapshot_record, {"input_hashes", "input_sha256", "sha256"}, "snapshot record"
    )
    input_hashes = snapshot_record["input_hashes"]
    if type(input_hashes) is not list:
        raise RubricBundleError("snapshot input_hashes must be an array")
    input_sha256 = _hash(snapshot_record["input_sha256"], "snapshot input_sha256")
    if sha256_text(canonical_json(input_hashes)) != input_sha256:
        raise RubricBundleError("snapshot input hash mismatch")
    snapshot_sha256 = _hash(snapshot_record["sha256"], "snapshot sha256")

    expected_files = {
        "request.json",
        "response.txt",
        "response_metadata.json",
        "errors.json",
    }
    attempt_files: dict[int, set[str]] = {}
    for relative in artifact_bytes:
        if not relative.startswith("attempts/"):
            continue
        match = re.fullmatch(
            r"attempts/attempt-([1-9][0-9]*)/"
            r"(request\.json|response\.txt|response_metadata\.json|errors\.json)",
            relative,
        )
        if match is None:
            raise RubricBundleError("attempt artifacts are not canonical")
        attempt_number = int(match.group(1))
        attempt_files.setdefault(attempt_number, set()).add(match.group(2))
    if not attempt_files:
        raise RubricBundleError("task bundle has no generation attempts")
    attempt_numbers = sorted(attempt_files)
    if attempt_numbers != list(range(1, len(attempt_numbers) + 1)):
        raise RubricBundleError("attempt directories must be contiguous")
    if any(files != expected_files for files in attempt_files.values()):
        raise RubricBundleError(
            "generation attempts do not contain exactly the required files"
        )

    snapshot: dict[str, object] | None = None
    flattened_errors: list[str] = []
    successful_request: dict[str, object] | None = None
    successful_attempt_number: int | None = None
    for attempt_number in attempt_numbers:
        context = f"attempt-{attempt_number} request"
        attempt_prefix = f"attempts/attempt-{attempt_number}"
        request = _read_json_object_bytes(
            artifact_bytes[f"{attempt_prefix}/request.json"],
            context,
        )
        _closed_keys(
            request,
            {"schema_version", "prompt_version", "task_snapshot", "previous_errors"},
            context,
        )
        if (
            type(request["schema_version"]) is not int
            or request["schema_version"] != TASK_RUBRIC_BUNDLE_SCHEMA_VERSION
        ):
            raise RubricBundleError(f"{context} schema version mismatch")
        if request["prompt_version"] != TASK_RUBRIC_PROMPT_VERSION:
            raise RubricBundleError(f"{context} prompt version mismatch")
        request_snapshot = _object(request["task_snapshot"], f"{context} snapshot")
        if snapshot is None:
            snapshot = request_snapshot
            if snapshot.get("task_id") != task_id:
                raise RubricBundleError("request task ID mismatch")
            if snapshot.get("snapshot_sha256") != snapshot_sha256:
                raise RubricBundleError("request snapshot hash mismatch")
            if snapshot.get("input_hashes") != input_hashes:
                raise RubricBundleError("request immutable input hashes mismatch")
            snapshot_payload = dict(snapshot)
            snapshot_payload.pop("snapshot_sha256", None)
            if sha256_text(canonical_json(snapshot_payload)) != snapshot_sha256:
                raise RubricBundleError("snapshot content hash mismatch")
        elif request_snapshot != snapshot:
            raise RubricBundleError(f"{context} snapshot mismatch")
        previous_errors = request["previous_errors"]
        if type(previous_errors) is not list or any(
            not isinstance(error, str) for error in previous_errors
        ):
            raise RubricBundleError(f"{context} previous_errors must be strings")
        if previous_errors != flattened_errors:
            raise RubricBundleError(f"{context} previous-error chain mismatch")
        response_bytes = artifact_bytes[f"{attempt_prefix}/response.txt"]
        response_metadata_bytes = artifact_bytes[
            f"{attempt_prefix}/response_metadata.json"
        ]
        response_metadata = _validated_response_metadata(
            _read_json_object_bytes(
                response_metadata_bytes,
                f"attempt-{attempt_number} response metadata",
            )
        )
        if response_metadata_bytes != (canonical_json(response_metadata) + "\n").encode(
            "utf-8"
        ):
            raise RubricBundleError(
                f"attempt-{attempt_number} response metadata is not canonical JSON"
            )
        if response_metadata["raw_response_sha256"] != _sha256_bytes(response_bytes):
            raise RubricBundleError(
                f"attempt-{attempt_number} response metadata hash mismatch"
            )
        errors = _read_json_string_list_bytes(
            artifact_bytes[f"{attempt_prefix}/errors.json"],
            f"attempt-{attempt_number} errors",
        )
        is_final = attempt_number == attempt_numbers[-1]
        if is_final:
            if errors:
                raise RubricBundleError("final generation attempt was not successful")
            successful_request = request
            successful_attempt_number = attempt_number
        elif not errors:
            raise RubricBundleError("intermediate generation attempt has no errors")
        flattened_errors.extend(errors)

    if (
        snapshot is None
        or successful_request is None
        or successful_attempt_number is None
    ):
        raise RubricBundleError("task bundle has no successful generation attempt")
    prompt_request = TaskRubricRequest(
        schema_version=successful_request["schema_version"],  # type: ignore[arg-type]
        prompt_version=successful_request["prompt_version"],  # type: ignore[arg-type]
        task_snapshot=snapshot,
        previous_errors=tuple(successful_request["previous_errors"]),  # type: ignore[arg-type]
    )
    hashes = _object(task_manifest["hashes"], "task hashes")
    prompt_sha256 = _hash(hashes["prompt_sha256"], "prompt sha256")
    if sha256_text(build_task_rubric_prompt(prompt_request)) != prompt_sha256:
        raise RubricBundleError("prompt hash mismatch")
    successful_response = artifact_bytes[
        f"attempts/attempt-{successful_attempt_number}/response.txt"
    ]
    if _sha256_bytes(successful_response) != hashes["raw_response_sha256"]:
        raise RubricBundleError("successful response does not match raw response")
    successful_response_metadata = artifact_bytes[
        f"attempts/attempt-{successful_attempt_number}/response_metadata.json"
    ]
    if successful_response_metadata != artifact_bytes["response_metadata.json"]:
        raise RubricBundleError(
            "successful attempt response metadata does not match final metadata"
        )


def resolve_rubric_bundle(
    rubric_set_dir: Path,
    task_id: str,
) -> ResolvedRubricBundle:
    """Resolve one task from a sealed set after verifying all bundle attestations."""

    if not is_safe_task_id(task_id):
        raise RubricBundleError(f"unsafe task ID: {task_id!r}")
    try:
        root = rubric_set_dir.resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise RubricBundleError(f"rubric set does not exist: {rubric_set_dir}") from exc
    if not root.is_dir():
        raise RubricBundleError(f"rubric set is not a directory: {root}")
    root_children = {path.name for path in root.iterdir()}
    if root_children != {"manifest.json", "tasks"}:
        raise RubricBundleError("rubric set root has unlisted members")

    root_manifest = _read_json_object(root / "manifest.json", "root manifest")
    _closed_keys(
        root_manifest,
        {
            "compilation_sha256",
            "compiler_config",
            "compiler_config_sha256",
            "generated_at",
            "generation_code_sha256",
            "generation_code_sha256s",
            "prompt_version",
            "rewriter_provenance",
            "rewriter_provenance_sha256",
            "rubric_set_id",
            "schema_version",
            "status",
            "tasks",
        },
        "root manifest",
    )
    if (
        type(root_manifest["schema_version"]) is not int
        or root_manifest["schema_version"] != TASK_RUBRIC_BUNDLE_SCHEMA_VERSION
    ):
        raise RubricBundleError("unsupported root manifest schema version")
    if root_manifest["status"] != "sealed":
        raise RubricBundleError("root manifest is not sealed")
    if root_manifest["prompt_version"] != TASK_RUBRIC_PROMPT_VERSION:
        raise RubricBundleError("unsupported prompt version")
    _string(root_manifest["generated_at"], "root generated_at")
    compiler_config = _validated_compiler_config(root_manifest["compiler_config"])
    compiler_config_sha256 = _hash(
        root_manifest["compiler_config_sha256"],
        "compiler config sha256",
    )
    if sha256_text(canonical_json(compiler_config)) != compiler_config_sha256:
        raise RubricBundleError("compiler config hash mismatch")
    generation_code_sha256s = _validated_generation_code_sha256s(
        root_manifest["generation_code_sha256s"]
    )
    generation_code_sha256 = _hash(
        root_manifest["generation_code_sha256"],
        "generation code sha256",
    )
    if sha256_text(canonical_json(generation_code_sha256s)) != generation_code_sha256:
        raise RubricBundleError("generation code hash-map mismatch")
    rewriter_provenance = _validated_rewriter_provenance(
        root_manifest["rewriter_provenance"]
    )
    rewriter_provenance_sha256 = _hash(
        root_manifest["rewriter_provenance_sha256"],
        "rewriter provenance sha256",
    )
    if sha256_text(canonical_json(rewriter_provenance)) != rewriter_provenance_sha256:
        raise RubricBundleError("rewriter provenance hash mismatch")
    if compiler_config["rewriter_provenance_sha256"] != rewriter_provenance_sha256:
        raise RubricBundleError("compiler config rewriter provenance mismatch")
    if compiler_config["model"] != rewriter_provenance["model"]:
        raise RubricBundleError("rewriter provenance model mismatch")
    compilation_sha256 = _hash(
        root_manifest["compilation_sha256"],
        "compilation sha256",
    )
    rubric_set_id = _hash(root_manifest["rubric_set_id"], "rubric set ID")
    tasks = _object(root_manifest["tasks"], "root tasks")
    if task_id not in tasks:
        raise RubricBundleError(f"task is not a member of rubric set: {task_id}")
    task_entries, compilation_tasks, identity_tasks = _validated_root_task_entries(
        tasks
    )
    if set(compiler_config["task_ids"]) != set(task_entries):  # type: ignore[arg-type]
        raise RubricBundleError("compiler config task IDs do not match root tasks")
    expected_compilation_sha256 = sha256_text(
        canonical_json(
            compilation_payload(
                compiler_config_sha256,
                generation_code_sha256,
                rewriter_provenance_sha256,
                compilation_tasks,
            )
        )
    )
    if compilation_sha256 != expected_compilation_sha256:
        raise RubricBundleError("compilation hash mismatch")

    tasks_root = root / "tasks"
    if tasks_root.is_symlink() or not tasks_root.is_dir():
        raise RubricBundleError("tasks root must be a regular directory")
    actual_tasks = {path.name for path in tasks_root.iterdir() if path.is_dir()}
    if actual_tasks != set(tasks) or any(
        not path.is_dir() for path in tasks_root.iterdir()
    ):
        raise RubricBundleError(
            "task directory membership does not match root manifest"
        )

    task_entry = task_entries[task_id]

    task_dir = tasks_root / task_id
    if task_dir.is_symlink() or task_dir.resolve(
        strict=True
    ).parent != tasks_root.resolve(strict=True):
        raise RubricBundleError("task bundle leaves rubric set root")
    task_manifest_path = task_dir / "manifest.json"
    expected_manifest_sha256 = _hash(
        task_entry["task_manifest_sha256"],
        "task manifest sha256",
    )
    task_manifest_bytes = _read_regular_bytes(
        task_manifest_path,
        "task manifest",
    )
    actual_manifest_sha256 = _sha256_bytes(task_manifest_bytes)
    if actual_manifest_sha256 != expected_manifest_sha256:
        raise RubricBundleError("task manifest hash mismatch")
    task_manifest = _read_json_object_bytes(task_manifest_bytes, "task manifest")
    _closed_keys(
        task_manifest,
        {
            "artifacts",
            "compiler",
            "generated_at",
            "hashes",
            "rubric_id",
            "rubric_set_id",
            "rubric_sha256",
            "schema_version",
            "snapshot",
            "status",
            "task_id",
            "validation_errors",
        },
        "task manifest",
    )
    if (
        type(task_manifest["schema_version"]) is not int
        or task_manifest["schema_version"] != TASK_RUBRIC_BUNDLE_SCHEMA_VERSION
    ):
        raise RubricBundleError("unsupported task manifest schema version")
    if task_manifest["status"] != "valid" or task_manifest["validation_errors"] != []:
        raise RubricBundleError("task manifest does not attest a valid rubric")
    if task_manifest["task_id"] != task_id:
        raise RubricBundleError("task manifest task ID mismatch")
    if task_manifest["rubric_set_id"] != rubric_set_id:
        raise RubricBundleError("task manifest rubric-set ID mismatch")

    artifacts = _object(task_manifest["artifacts"], "task artifacts")
    required_artifacts = {
        "raw_response.txt",
        "response_metadata.json",
        "rubric.json",
        "process_rubric.txt",
    }
    if not required_artifacts.issubset(artifacts):
        raise RubricBundleError("task manifest is missing required artifacts")
    actual_artifacts: set[str] = set()
    for path in task_dir.rglob("*"):
        if path.is_symlink():
            raise RubricBundleError(f"bundle member must not be a symlink: {path}")
        if path.is_file() and path != task_manifest_path:
            actual_artifacts.add(path.relative_to(task_dir).as_posix())
    if actual_artifacts != set(artifacts):
        raise RubricBundleError("task artifact membership does not match manifest")
    artifact_bytes: dict[str, bytes] = {}
    for relative, expected in artifacts.items():
        path = _artifact_path(task_dir, relative)
        raw = _read_regular_bytes(path, f"bundle artifact {relative}")
        if _sha256_bytes(raw) != _hash(expected, f"artifact hash {relative}"):
            raise RubricBundleError(f"bundle artifact hash mismatch: {relative}")
        artifact_bytes[relative] = raw

    compiler = _object(task_manifest["compiler"], "compiler record")
    _closed_keys(
        compiler,
        {
            "code_sha256",
            "code_sha256s",
            "compiler_config_sha256",
            "model",
            "prompt_version",
            "provider",
            "rewriter_provenance",
            "rewriter_provenance_sha256",
            "schema_version",
            "seed",
            "temperature",
        },
        "compiler record",
    )
    if _hash(compiler["code_sha256"], "compiler code sha256") != generation_code_sha256:
        raise RubricBundleError("task compiler code hash mismatch")
    if (
        _validated_generation_code_sha256s(compiler["code_sha256s"])
        != generation_code_sha256s
    ):
        raise RubricBundleError("task compiler code map mismatch")
    if (
        _hash(
            compiler["compiler_config_sha256"],
            "task compiler config sha256",
        )
        != compiler_config_sha256
    ):
        raise RubricBundleError("task compiler config hash mismatch")
    task_rewriter_provenance = _validated_rewriter_provenance(
        compiler["rewriter_provenance"]
    )
    if task_rewriter_provenance != rewriter_provenance:
        raise RubricBundleError("task rewriter provenance mismatch")
    if (
        _hash(
            compiler["rewriter_provenance_sha256"],
            "task rewriter provenance sha256",
        )
        != rewriter_provenance_sha256
    ):
        raise RubricBundleError("task rewriter provenance hash mismatch")
    if compiler["provider"] != rewriter_provenance["provider"]:
        raise RubricBundleError("compiler provider mismatch")
    if compiler["prompt_version"] != TASK_RUBRIC_PROMPT_VERSION:
        raise RubricBundleError("compiler prompt version mismatch")
    if (
        type(compiler["schema_version"]) is not int
        or compiler["schema_version"] != TASK_RUBRIC_BUNDLE_SCHEMA_VERSION
    ):
        raise RubricBundleError("compiler schema version mismatch")
    if compiler["model"] != compiler_config["model"]:
        raise RubricBundleError("task compiler model disagrees with root config")
    if compiler["model"] != rewriter_provenance["model"]:
        raise RubricBundleError("task compiler model disagrees with rewriter")
    if type(compiler["seed"]) is not int:
        raise RubricBundleError("task compiler seed is invalid")
    if compiler["seed"] != compiler_config["seed"]:
        raise RubricBundleError("task compiler seed disagrees with root config")
    if canonical_json(compiler["temperature"]) != canonical_json(
        compiler_config["temperature"]
    ):
        raise RubricBundleError("task compiler temperature disagrees with root config")

    hashes = _object(task_manifest["hashes"], "task hashes")
    _closed_keys(
        hashes,
        {
            "input_sha256",
            "model_sha256",
            "prompt_sha256",
            "raw_response_sha256",
            "rendered_rubric_sha256",
            "response_metadata_sha256",
            "seed_sha256",
            "snapshot_sha256",
            "structured_rubric_sha256",
            "temperature_sha256",
        },
        "task hashes",
    )
    for name, digest in hashes.items():
        _hash(digest, name)
    if hashes["model_sha256"] != sha256_text(
        _string(compiler["model"], "compiler model")
    ):
        raise RubricBundleError("model hash mismatch")
    if hashes["temperature_sha256"] != sha256_text(
        canonical_json(compiler["temperature"])
    ):
        raise RubricBundleError("temperature hash mismatch")
    if hashes["seed_sha256"] != sha256_text(canonical_json(compiler["seed"])):
        raise RubricBundleError("seed hash mismatch")
    if hashes["raw_response_sha256"] != artifacts["raw_response.txt"]:
        raise RubricBundleError("raw-response hash mismatch")
    if hashes["response_metadata_sha256"] != artifacts["response_metadata.json"]:
        raise RubricBundleError("response-metadata hash mismatch")
    if hashes["structured_rubric_sha256"] != artifacts["rubric.json"]:
        raise RubricBundleError("structured-rubric hash mismatch")
    if hashes["rendered_rubric_sha256"] != artifacts["process_rubric.txt"]:
        raise RubricBundleError("rendered-rubric hash mismatch")
    if hashes["input_sha256"] != task_entry["input_sha256"]:
        raise RubricBundleError("root input hash mismatch")
    if hashes["snapshot_sha256"] != task_entry["snapshot_sha256"]:
        raise RubricBundleError("root snapshot hash mismatch")
    if hashes["response_metadata_sha256"] != task_entry["response_metadata_sha256"]:
        raise RubricBundleError("root response-metadata hash mismatch")
    response_metadata = _validated_response_metadata(
        _read_json_object_bytes(
            artifact_bytes["response_metadata.json"],
            "response metadata",
        )
    )
    if artifact_bytes["response_metadata.json"] != (
        canonical_json(response_metadata) + "\n"
    ).encode("utf-8"):
        raise RubricBundleError("response metadata is not canonical JSON")
    if response_metadata["raw_response_sha256"] != artifacts["raw_response.txt"]:
        raise RubricBundleError("response metadata raw-response hash mismatch")
    _validate_snapshot_attestation(
        task_id,
        task_manifest,
        artifact_bytes,
    )

    rubric_json_path = task_dir / "rubric.json"
    rubric_sha256 = _hash(task_manifest["rubric_sha256"], "rubric sha256")
    rubric_id = _hash(task_manifest["rubric_id"], "rubric ID")
    if rubric_sha256 != artifacts["rubric.json"] or rubric_id != rubric_sha256:
        raise RubricBundleError("rubric ID or hash mismatch")
    if (
        task_entry["rubric_sha256"] != rubric_sha256
        or task_entry["rubric_id"] != rubric_id
    ):
        raise RubricBundleError("root rubric ID or hash mismatch")
    try:
        rubric_text = artifact_bytes["rubric.json"].decode("utf-8")
        rubric = parse_task_process_rubric(rubric_text)
    except (UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise RubricBundleError(f"invalid structured rubric: {exc}") from exc
    if rubric.task_id != task_id:
        raise RubricBundleError("structured rubric task ID mismatch")
    if rubric_text != canonical_json(asdict(rubric)) + "\n":
        raise RubricBundleError("structured rubric is not canonical JSON")
    rendered_path = task_dir / "process_rubric.txt"
    try:
        rendered_text = artifact_bytes["process_rubric.txt"].decode("utf-8")
    except UnicodeError as exc:
        raise RubricBundleError(f"invalid rendered rubric: {exc}") from exc
    if rendered_text != render_task_process_rubric(rubric):
        raise RubricBundleError("rendered rubric is not derived from structured rubric")
    try:
        validate_rendered_task_process_rubric(rubric, rendered_text)
    except ValueError as exc:
        raise RubricBundleError(str(exc)) from exc

    identity = {
        "compilation_sha256": compilation_sha256,
        "generation_code_sha256": generation_code_sha256,
        "rewriter_provenance_sha256": rewriter_provenance_sha256,
        "schema_version": TASK_RUBRIC_BUNDLE_SCHEMA_VERSION,
        "tasks": identity_tasks,
    }
    if sha256_text(canonical_json(identity)) != rubric_set_id:
        raise RubricBundleError("rubric-set ID mismatch")

    return ResolvedRubricBundle(
        task_id=task_id,
        rubric_set_id=rubric_set_id,
        rubric_id=rubric_id,
        rubric_sha256=rubric_sha256,
        rubric_json_path=rubric_json_path,
        rubric_json_text=rubric_text,
        rendered_path=rendered_path,
        rendered_text=rendered_text,
        task_manifest_path=task_manifest_path,
        task_manifest_sha256=actual_manifest_sha256,
    )
