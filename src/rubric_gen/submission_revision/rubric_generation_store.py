"""Atomic storage for self-contained rubric generations."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.submission_revision.rubric_generation import (
    CompleteRubric,
    RubricGeneration,
    RubricPolicy,
    parse_elicited_criterion,
    require_nonnegative_int,
    require_sha256,
)


_BASE_FILES = frozenset({"manifest.json", "rubric.txt", "criteria.json"})
_EVOLUTION_FILES = frozenset({
    "artifact-history.json",
    "pairwise-assessment-rubric-free.json",
    "pairwise-assessment-active-rubric.json",
    "pairwise-assessment-development-rubric.json",
    "pairwise-comparisons.json",
    "criterion-proposal.json",
    "criterion-validation.json",
    "aggregate-margins.json",
    "evolution.json",
})
_MANIFEST_KEYS = frozenset({
    "policy",
    "generation_round",
    "source_checkpoint",
    "proposer_call_budget",
    "generation_sha256",
    "rubric_sha256",
    "file_sha256s",
})


def rubric_generation_directory(root: Path, generation_round: int) -> Path:
    """Return the canonical directory for one complete rubric generation."""

    require_nonnegative_int(generation_round, "generation_round")
    return root / "rubric-generations" / f"generation-{generation_round:04d}"


def persist_rubric_generation(
    root: Path,
    generation: RubricGeneration,
    policy: RubricPolicy,
    *,
    evolution_files: dict[str, str] | None = None,
) -> Path:
    """Publish one complete generation or validate its exact existing copy."""

    if not isinstance(generation, RubricGeneration):
        raise ValueError("generation must be a RubricGeneration")
    if not isinstance(policy, RubricPolicy):
        raise ValueError("policy must be a RubricPolicy")
    _validate_policy_generation(policy, generation)
    trace = _validated_evolution_files(generation, evolution_files)
    files = _generation_files(generation, policy, trace)
    generation_dir = rubric_generation_directory(root, generation.generation_round)
    manifest_path = generation_dir / "manifest.json"
    if os.path.lexists(generation_dir):
        loaded = load_rubric_generation(
            root,
            generation.generation_round,
            expected_policy=policy,
        )
        if loaded != generation:
            raise RuntimeError("persisted rubric generation changed")
        _validate_directory_contents(generation_dir, files)
        return manifest_path

    parent = generation_dir.parent
    parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(
        prefix=f".generation-{generation.generation_round:04d}.",
        dir=parent,
    ))
    try:
        for name, content in files.items():
            (stage / name).write_text(content, encoding="utf-8")
        _validate_directory_contents(stage, files)
        for path in stage.iterdir():
            with path.open("rb") as stream:
                os.fsync(stream.fileno())
        _fsync_directory(stage)
        os.rename(stage, generation_dir)
        _fsync_directory(parent)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    return manifest_path


def load_rubric_generation(
    root: Path,
    generation_round: int,
    *,
    expected_policy: RubricPolicy | None = None,
) -> RubricGeneration:
    """Load one generation from its current artifact format."""

    generation_dir = rubric_generation_directory(root, generation_round)
    if generation_dir.is_symlink() or not generation_dir.is_dir():
        raise RuntimeError(f"rubric generation directory is missing: {generation_dir}")
    manifest_path = generation_dir / "manifest.json"
    manifest = _read_json_object(manifest_path, "rubric generation manifest")
    if set(manifest) != _MANIFEST_KEYS:
        raise RuntimeError("rubric generation manifest has invalid fields")
    try:
        policy = RubricPolicy(manifest["policy"])
    except (TypeError, ValueError) as exc:
        raise RuntimeError("rubric generation manifest has an invalid policy") from exc
    if expected_policy is not None and policy is not expected_policy:
        raise RuntimeError("rubric generation manifest has the wrong policy")
    if manifest["generation_round"] != generation_round:
        raise RuntimeError("rubric generation manifest has the wrong round")

    file_sha256s = manifest["file_sha256s"]
    expected_names = _BASE_FILES | (_EVOLUTION_FILES if generation_round > 0 else set())
    expected_payload_names = expected_names - {"manifest.json"}
    if (
        not isinstance(file_sha256s, dict)
        or set(file_sha256s) != expected_payload_names
    ):
        raise RuntimeError("rubric generation manifest has invalid file hashes")
    observed_names = {path.name for path in generation_dir.iterdir()}
    if observed_names != expected_names:
        raise RuntimeError("rubric generation directory has invalid files")
    contents: dict[str, str] = {}
    for name in sorted(expected_payload_names):
        path = generation_dir / name
        content = _read_text(path, f"rubric generation {name}")
        if sha256_text(content) != require_sha256(file_sha256s[name], name):
            raise RuntimeError(f"rubric generation file hash changed: {name}")
        contents[name] = content

    criteria_value = _load_json(contents["criteria.json"], "rubric criteria")
    if not isinstance(criteria_value, list):
        raise RuntimeError("rubric criteria must be an array")
    try:
        generation = RubricGeneration(
            generation_round=generation_round,
            source_checkpoint=manifest["source_checkpoint"],
            rubric=CompleteRubric.from_content(contents["rubric.txt"]),
            elicited_criteria=tuple(
                parse_elicited_criterion(value) for value in criteria_value
            ),
            proposer_call_budget=manifest["proposer_call_budget"],
        )
        _validate_policy_generation(policy, generation)
    except (TypeError, ValueError) as exc:
        raise RuntimeError("rubric generation manifest has invalid values") from exc
    if manifest["rubric_sha256"] != generation.rubric.content_sha256:
        raise RuntimeError("rubric generation manifest has the wrong rubric hash")
    if manifest["generation_sha256"] != generation.generation_sha256:
        raise RuntimeError("rubric generation manifest has the wrong generation hash")
    return generation


def _generation_files(
    generation: RubricGeneration,
    policy: RubricPolicy,
    evolution_files: dict[str, str],
) -> dict[str, str]:
    criteria_text = _json_text([
        criterion.as_dict() for criterion in generation.elicited_criteria
    ])
    payload = {
        "rubric.txt": generation.rubric.content,
        "criteria.json": criteria_text,
        **evolution_files,
    }
    manifest = {
        "policy": policy.value,
        "generation_round": generation.generation_round,
        "source_checkpoint": generation.source_checkpoint,
        "proposer_call_budget": generation.proposer_call_budget,
        "generation_sha256": generation.generation_sha256,
        "rubric_sha256": generation.rubric.content_sha256,
        "file_sha256s": {
            name: sha256_text(content) for name, content in sorted(payload.items())
        },
    }
    return {"manifest.json": _json_text(manifest), **payload}


def _validated_evolution_files(
    generation: RubricGeneration,
    value: dict[str, str] | None,
) -> dict[str, str]:
    if generation.generation_round == 0:
        if value not in (None, {}):
            raise ValueError("the initial rubric cannot have evolution files")
        return {}
    if not isinstance(value, dict) or set(value) != _EVOLUTION_FILES:
        raise ValueError("an evolved rubric requires complete evolution files")
    if any(type(content) is not str for content in value.values()):
        raise ValueError("rubric evolution files must contain text")
    return value


def _validate_policy_generation(
    policy: RubricPolicy,
    generation: RubricGeneration,
) -> None:
    if policy is RubricPolicy.FIXED:
        if generation.generation_round != 0 or generation.source_checkpoint is not None:
            raise ValueError("fixed policy permits only the initial rubric")
        return
    if policy is RubricPolicy.OFFLINE_ELICITATION:
        if generation.generation_round > 1 or generation.source_checkpoint is not None:
            raise ValueError("offline elicitation permits one pre-treatment generation")
        return
    if generation.generation_round <= 1:
        if generation.source_checkpoint is not None:
            raise ValueError(
                "initial and pre-treatment online rubrics cannot use live evidence"
            )
    elif generation.source_checkpoint != generation.generation_round - 1:
        raise ValueError("online generation requires its preceding checkpoint")


def _validate_directory_contents(root: Path, expected: dict[str, str]) -> None:
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError("rubric generation directory is invalid")
    entries = list(root.iterdir())
    if {path.name for path in entries} != set(expected):
        raise RuntimeError("rubric generation directory has invalid files")
    for path in entries:
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("rubric generation contains a non-regular file")
        if _read_text(path, path.name) != expected[path.name]:
            raise RuntimeError(f"rubric generation file changed: {path.name}")


def _read_json_object(path: Path, context: str) -> dict[str, object]:
    value = _load_json(_read_text(path, context), context)
    if not isinstance(value, dict):
        raise RuntimeError(f"{context} must be an object")
    return value


def _load_json(text: str, context: str) -> object:
    try:
        return json.loads(text, object_pairs_hook=_unique_json_object)
    except (json.JSONDecodeError, ValueError) as exc:
        raise RuntimeError(f"{context} is invalid JSON") from exc


def _read_text(path: Path, context: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError(f"{context} is not a regular file")
    try:
        return path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError(f"{context} is unreadable") from exc


def _json_text(value: object) -> str:
    return json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def _unique_json_object(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, child in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = child
    return value


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
