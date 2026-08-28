"""Validate paraphrase candidates, sealed pools, and deterministic selections."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.experiment import Experiment
from rubric_gen.submission_revision.judging.scoring import parse_rubric_levels_strict
from rubric_gen.submission_revision.paraphrase_protocol import (
    CRITERION_HEADER_PATTERN,
    LEAF_ID_PATTERN,
    PARAPHRASE_PROTOCOL,
    PARAPHRASE_RUN_KIND,
    PARAPHRASE_VARIANT_KIND,
    validate_wording_value,
    wording_template,
)


@dataclass(frozen=True)
class ParaphraseSelection:
    task_id: str
    replicate: int
    optimizer_index: int
    optimizer_path: Path
    optimizer_sha256: str
    holdout_paths: tuple[Path, ...]
    holdout_sha256s: tuple[str, ...]
    master_path: Path
    master_sha256: str


def validate_semantic_paraphrase(master: str, candidate: str) -> str:
    if type(candidate) is not str or not candidate.strip():
        raise ValueError("paraphrase must be a non-empty string")
    if "```" in candidate:
        raise ValueError("paraphrase must not contain Markdown code fences")
    if sha256_text(candidate) == sha256_text(master):
        raise ValueError("paraphraser returned the unchanged master rubric")
    master_levels = parse_rubric_levels_strict(master)
    candidate_levels = parse_rubric_levels_strict(candidate)
    if candidate_levels != master_levels:
        raise ValueError("paraphrase changed criterion order or level values")
    if LEAF_ID_PATTERN.findall(candidate) != LEAF_ID_PATTERN.findall(master):
        raise ValueError("paraphrase changed PaperBench leaf IDs")
    master_template = wording_template(master)
    candidate_template = wording_template(candidate)
    if tuple(slot.key for slot in master_template.slots) != tuple(
        slot.key for slot in candidate_template.slots
    ):
        raise ValueError("paraphrase changed its wording-field layout")
    if candidate_template.fixed_fragments != master_template.fixed_fragments:
        raise ValueError("paraphrase changed immutable rubric structure")
    titles = [
        " ".join(match.group("text").lower().split())
        for match in CRITERION_HEADER_PATTERN.finditer(candidate)
    ]
    if len(set(titles)) != len(titles):
        raise ValueError("paraphrase contains duplicate criterion titles")
    for master_slot, candidate_slot in zip(
        master_template.slots,
        candidate_template.slots,
    ):
        validate_wording_value(master_slot, candidate_slot.text)
    return candidate


def resolve_paraphrase_selection(
    root: Path,
    experiment: Experiment,
    task_id: str,
    replicate: int,
) -> ParaphraseSelection:
    """Resolve one selection from a separately validated paraphrase pool."""

    if task_id not in experiment.task_ids:
        raise ValueError(f"task is not in experiment: {task_id}")
    if not 1 <= replicate <= experiment.replicates:
        raise ValueError("replicate is outside the experiment")
    count = int(experiment.rubric_paraphrases["count"])
    optimizer_index = _selected_index(
        int(experiment.payload["randomization"]["seed"]),
        replicate,
        count,
    )
    task_root = root.resolve() / "tasks" / task_id
    paths = tuple(task_root / f"variant-{index:03d}.txt" for index in range(count))
    master_path = (
        experiment.task_dir(task_id)
        / "tests"
        / str(experiment.protocol["rubric_name"])
    )
    return ParaphraseSelection(
        task_id=task_id,
        replicate=replicate,
        optimizer_index=optimizer_index,
        optimizer_path=paths[optimizer_index],
        optimizer_sha256=sha256_file(paths[optimizer_index]),
        holdout_paths=tuple(
            path for index, path in enumerate(paths) if index != optimizer_index
        ),
        holdout_sha256s=tuple(
            sha256_file(path)
            for index, path in enumerate(paths)
            if index != optimizer_index
        ),
        master_path=master_path,
        master_sha256=sha256_file(master_path),
    )


def validate_paraphrase_run(root: Path, experiment: Experiment) -> None:
    resolved = root.resolve()
    if root.is_symlink() or not resolved.is_dir():
        raise RuntimeError(f"paraphrase run is not a regular directory: {root}")
    manifest = read_json_object(resolved / "manifest.json", "rubric paraphrase manifest")
    records = manifest.get("tasks")
    if not _valid_manifest(manifest, records, experiment):
        raise RuntimeError("rubric paraphrase pool is incompatible")
    assert isinstance(records, list)
    by_task = {
        record.get("task_id"): record
        for record in records
        if isinstance(record, dict)
    }
    if len(by_task) != len(records) or not set(experiment.task_ids) <= set(by_task):
        raise RuntimeError("rubric paraphrase pool lacks required tasks")
    count = int(experiment.rubric_paraphrases["count"])
    model = str(experiment.rubric_paraphrases["model"])
    for task_id in experiment.task_ids:
        record = by_task[task_id]
        assert isinstance(record, dict)
        validate_task_record(resolved, experiment, task_id, record, count, model)


def _valid_manifest(
    manifest: dict[str, object],
    records: object,
    experiment: Experiment,
) -> bool:
    return (
        set(manifest)
        == {
            "kind",
            "benchmark",
            "tasks_dir",
            "protocol",
            "model",
            "count",
            "tasks",
            "created_at",
            "updated_at",
        }
        and manifest.get("kind") == PARAPHRASE_RUN_KIND
        and manifest.get("benchmark") == experiment.benchmark.value
        and manifest.get("tasks_dir") == str(experiment.tasks_dir.resolve())
        and manifest.get("protocol") == PARAPHRASE_PROTOCOL
        and manifest.get("model") == experiment.rubric_paraphrases["model"]
        and manifest.get("count") == experiment.rubric_paraphrases["count"]
        and isinstance(records, list)
        and all(
            isinstance(record, dict)
            and set(record) == {"task_id", "master_path", "master_sha256"}
            for record in records
        )
        and type(manifest.get("created_at")) is str
        and type(manifest.get("updated_at")) is str
    )


def validate_task_record(
    root: Path,
    experiment: Experiment,
    task_id: str,
    record: dict[str, object],
    count: int,
    model: str,
) -> None:
    master_path = (
        experiment.task_dir(task_id)
        / "tests"
        / str(experiment.protocol["rubric_name"])
    )
    if (
        set(record) != {"task_id", "master_path", "master_sha256"}
        or record.get("task_id") != task_id
        or record.get("master_path") != str(master_path)
        or record.get("master_sha256") != sha256_file(master_path)
    ):
        raise RuntimeError(f"rubric paraphrase task identity changed: {task_id}")
    master = master_path.read_text(encoding="utf-8")
    seen: set[str] = set()
    for variant_index in range(count):
        rubric_path = root / "tasks" / task_id / f"variant-{variant_index:03d}.txt"
        metadata_path = root / "tasks" / task_id / f"variant-{variant_index:03d}.json"
        validate_variant_files(
            rubric_path,
            metadata_path,
            master,
            master_path,
            task_id,
            variant_index,
            model,
        )
        digest = sha256_file(rubric_path)
        if digest in seen:
            raise RuntimeError(f"duplicate rubric paraphrase for {task_id}")
        seen.add(digest)


def validate_variant_files(
    rubric_path: Path,
    metadata_path: Path,
    master: str,
    master_path: Path,
    task_id: str,
    variant_index: int,
    model: str,
) -> None:
    if (
        rubric_path.is_symlink()
        or metadata_path.is_symlink()
        or not rubric_path.is_file()
        or not metadata_path.is_file()
    ):
        raise RuntimeError(f"rubric paraphrase artifact is incomplete: {rubric_path}")
    text = rubric_path.read_text(encoding="utf-8")
    try:
        expected = validate_semantic_paraphrase(master, text)
    except ValueError as exc:
        raise RuntimeError(f"rubric paraphrase is invalid: {rubric_path}") from exc
    metadata = read_json_object(metadata_path, "rubric paraphrase metadata")
    if not _valid_variant_metadata(
        metadata,
        master,
        master_path,
        task_id,
        variant_index,
        model,
        expected,
    ):
        raise RuntimeError(f"rubric paraphrase metadata is invalid: {metadata_path}")


def _valid_variant_metadata(
    metadata: dict[str, object],
    master: str,
    master_path: Path,
    task_id: str,
    variant_index: int,
    model: str,
    expected: str,
) -> bool:
    return (
        set(metadata)
        == {
            "kind",
            "protocol",
            "task_id",
            "variant_index",
            "model",
            "attempt_count",
            "master_path",
            "master_sha256",
            "rubric_sha256",
            "prompt_sha256",
            "generation",
        }
        and metadata.get("kind") == PARAPHRASE_VARIANT_KIND
        and metadata.get("protocol") == PARAPHRASE_PROTOCOL
        and metadata.get("task_id") == task_id
        and metadata.get("variant_index") == variant_index
        and metadata.get("model") == model
        and metadata.get("master_path") == str(master_path)
        and metadata.get("master_sha256") == sha256_text(master)
        and metadata.get("rubric_sha256") == sha256_text(expected)
        and type(metadata.get("attempt_count")) is int
        and metadata["attempt_count"] >= 1
        and isinstance(metadata.get("generation"), dict)
        and type(metadata.get("prompt_sha256")) is str
    )


def _selected_index(seed: int, replicate: int, count: int) -> int:
    digest = hashlib.sha256(
        f"{seed}\0{replicate}\0rubric-paraphrase-set".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big") % count
