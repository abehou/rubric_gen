"""Generate sealed rubric paraphrases for optimizer and holdout evaluation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import threading
import fcntl
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.llm import (
    GenerationResult,
    StructuredRequest,
    generate_structured,
    generate_structured_vllm,
)
from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.submission_revision.artifacts import make_read_only, read_json_object
from rubric_gen.submission_revision.evolution import _validated_complete_rubric
from rubric_gen.submission_revision.experiment import Experiment
from rubric_gen.submission_revision.judging.scoring import (
    parse_rubric_levels_strict,
)


PARAPHRASE_RUN_SCHEMA_VERSION = 2
PARAPHRASE_RUN_KIND = "rubric-gen-shared-rubric-paraphrase-pool"
PARAPHRASE_PROTOCOL_VERSION = "semantic-rubric-paraphrase-v1"
PARAPHRASE_MAX_OUTPUT_TOKENS = 32_768
_LEAF_ID = re.compile(r"^PaperBench leaf ID:\s*(\S+)\s*$", re.MULTILINE)
_RESPONSE_SCHEMA: dict[str, object] = {
    "type": "object",
    "additionalProperties": False,
    "required": ["rubric_text"],
    "properties": {
        "rubric_text": {"type": "string", "minLength": 1},
    },
}

_INSTRUCTIONS = f"""Prompt contract: {PARAPHRASE_PROTOCOL_VERSION}

Rewrite the complete rubric with different surface wording only.

Preserve all semantics. Preserve every requirement, exception, factual anchor,
number, filename, command, identifier, example, and scoring direction. Preserve
the criterion count, criterion order, level labels, point values, scoring
protocol, and normalization maximum exactly. Preserve every PaperBench leaf ID
exactly. Do not add, remove, merge, split, weaken, strengthen, clarify, or repair
criteria. Do not adapt the rubric to a submission. Do not turn examples into
requirements or requirements into examples.

Change enough wording that the result is a real paraphrase. Return the complete
rubric in `rubric_text`. Do not use Markdown code fences.
"""


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


@dataclass(frozen=True)
class ParaphraseRunConfig:
    experiment: Experiment
    output_dir: Path
    max_concurrency: int
    vllm_endpoints: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if type(self.max_concurrency) is not int or self.max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")


GenerationOperation = Callable[[str, StructuredRequest], GenerationResult]


class ParaphraseRunner:
    def __init__(
        self,
        config: ParaphraseRunConfig,
        *,
        generation_operation: GenerationOperation | None = None,
    ) -> None:
        self.config = config
        self.experiment = config.experiment
        self.root = config.output_dir.resolve()
        self.spec = self.experiment.rubric_paraphrases
        self.model = str(self.spec["model"])
        self.count = int(self.spec["count"])
        self.max_retries = int(self.spec["max_retries"])
        self._generation_operation = generation_operation
        self._failure_lock = threading.Lock()
        self._commit_lock = threading.Lock()

    def run(self) -> int:
        self.root.mkdir(parents=True, exist_ok=True)
        if self.root.is_symlink() or not self.root.is_dir():
            raise RuntimeError(
                f"paraphrase output is not a regular directory: {self.root}"
            )
        with _pool_lease(self.root):
            return self._run_locked()

    def _run_locked(self) -> int:
        manifest_path = self.root / "manifest.json"
        if manifest_path.is_file():
            manifest = read_json_object(
                manifest_path, "rubric paraphrase manifest"
            )
            self._validate_manifest_identity(manifest)
        else:
            unexpected = [
                path for path in self.root.iterdir()
                if path.name != ".paraphrase.lock"
            ]
            if unexpected:
                raise RuntimeError(
                    f"unowned files exist in rubric paraphrase pool: {self.root}"
                )
            manifest = self._new_manifest()
            write_json_atomic(manifest_path, manifest)

        records = manifest.get("tasks")
        assert isinstance(records, list)
        by_task = {
            str(record["task_id"]): record
            for record in records
            if isinstance(record, dict)
        }
        for task_id in self.experiment.task_ids:
            if task_id in by_task:
                _validate_task_record(
                    self.root,
                    self.experiment,
                    task_id,
                    by_task[task_id],
                    self.count,
                    self.model,
                )
        missing_tasks = [
            task_id for task_id in self.experiment.task_ids
            if task_id not in by_task
        ]

        jobs = [
            (task_id, variant_index)
            for task_id in missing_tasks
            for variant_index in range(self.count)
        ]
        errors: list[BaseException] = []
        with TerminalProgress(
            total=len(jobs),
            description="rubric paraphrases",
            unit="variant",
        ) as progress:
            with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as pool:
                futures = [
                    pool.submit(self._generate_variant, task_id, variant_index)
                    for task_id, variant_index in jobs
                ]
                for future in as_completed(futures):
                    try:
                        future.result()
                    except BaseException as exc:
                        errors.append(exc)
                    progress.update()
        if errors:
            raise RuntimeError(
                f"{len(errors)} rubric paraphrase jobs failed; first error: {errors[0]}"
            ) from errors[0]
        for task_id in missing_tasks:
            record = self._task_record(task_id)
            _validate_task_record(
                self.root,
                self.experiment,
                task_id,
                record,
                self.count,
                self.model,
            )
            records.append(record)
        if missing_tasks:
            records.sort(key=lambda record: str(record["task_id"]))
            manifest["updated_at"] = _now()
            write_json_atomic(manifest_path, manifest)
        validate_paraphrase_run(self.root, self.experiment)
        return 0

    def _new_manifest(self) -> dict[str, object]:
        return {
            "schema_version": PARAPHRASE_RUN_SCHEMA_VERSION,
            "kind": PARAPHRASE_RUN_KIND,
            "benchmark": self.experiment.benchmark.value,
            "tasks_dir": str(self.experiment.tasks_dir.resolve()),
            "protocol_version": PARAPHRASE_PROTOCOL_VERSION,
            "model": self.model,
            "count": self.count,
            "tasks": [],
            "created_at": _now(),
            "updated_at": _now(),
        }

    def _task_record(self, task_id: str) -> dict[str, object]:
        master_path = self._master_path(task_id)
        return {
            "task_id": task_id,
            "master_path": str(master_path),
            "master_sha256": sha256_file(master_path),
        }

    def _validate_manifest_identity(self, manifest: dict[str, object]) -> None:
        keys = {
            "schema_version",
            "kind",
            "benchmark",
            "tasks_dir",
            "protocol_version",
            "model",
            "count",
            "tasks",
            "created_at",
            "updated_at",
        }
        records = manifest.get("tasks")
        if (
            set(manifest) != keys
            or manifest.get("schema_version") != PARAPHRASE_RUN_SCHEMA_VERSION
            or manifest.get("kind") != PARAPHRASE_RUN_KIND
            or manifest.get("benchmark") != self.experiment.benchmark.value
            or manifest.get("tasks_dir")
            != str(self.experiment.tasks_dir.resolve())
            or manifest.get("protocol_version") != PARAPHRASE_PROTOCOL_VERSION
            or manifest.get("model") != self.model
            or manifest.get("count") != self.count
            or not isinstance(records, list)
            or any(
                not isinstance(record, dict)
                or set(record) != {"task_id", "master_path", "master_sha256"}
                for record in records
            )
            or len({str(record["task_id"]) for record in records}) != len(records)
            or type(manifest.get("created_at")) is not str
            or type(manifest.get("updated_at")) is not str
        ):
            raise RuntimeError("rubric paraphrase pool identity changed")

    def _master_path(self, task_id: str) -> Path:
        return (
            self.experiment.task_dir(task_id)
            / "tests"
            / str(self.experiment.protocol["rubric_name"])
        )

    def _generate_variant(self, task_id: str, variant_index: int) -> None:
        task_root = self.root / "tasks" / task_id
        task_root.mkdir(parents=True, exist_ok=True)
        rubric_path = task_root / f"variant-{variant_index:03d}.txt"
        metadata_path = task_root / f"variant-{variant_index:03d}.json"
        master_path = self._master_path(task_id)
        master = master_path.read_text(encoding="utf-8")
        if os.path.lexists(rubric_path) or os.path.lexists(metadata_path):
            if rubric_path.is_file() and metadata_path.is_file():
                _validate_variant_files(
                    rubric_path,
                    metadata_path,
                    master,
                    master_path,
                    task_id,
                    variant_index,
                    self.model,
                )
                return
            for path in (rubric_path, metadata_path):
                if not os.path.lexists(path):
                    continue
                if path.is_symlink() or not path.is_file():
                    raise RuntimeError(
                        f"invalid partial rubric paraphrase artifact: {path}"
                    )
                path.unlink()

        last_error: Exception | None = None
        for attempt in range(1, self.max_retries + 2):
            request = _paraphrase_request(
                task_id=task_id,
                variant_index=variant_index,
                master=master,
                repair_error=str(last_error) if last_error is not None else None,
            )
            generation: GenerationResult | None = None
            try:
                generation = self._generate(request)
                value = json.loads(generation.text)
                if not isinstance(value, dict) or set(value) != {"rubric_text"}:
                    raise ValueError("paraphraser response has an invalid schema")
                candidate = value["rubric_text"]
                if type(candidate) is not str:
                    raise ValueError("paraphraser rubric_text must be a string")
                text = validate_semantic_paraphrase(master, candidate)
                with self._commit_lock:
                    prior_hashes = {
                        sha256_file(path)
                        for path in task_root.glob("variant-*.txt")
                        if path.is_file() and not path.is_symlink()
                    }
                    if sha256_text(text) in prior_hashes:
                        raise ValueError("paraphraser returned a duplicate variant")
                    rubric_path.write_text(text, encoding="utf-8")
                    write_json_atomic(metadata_path, {
                        "schema_version": 1,
                        "kind": "sealed-semantic-rubric-paraphrase",
                        "protocol_version": PARAPHRASE_PROTOCOL_VERSION,
                        "task_id": task_id,
                        "variant_index": variant_index,
                        "model": self.model,
                        "attempt_count": attempt,
                        "master_path": str(master_path),
                        "master_sha256": sha256_text(master),
                        "rubric_sha256": sha256_text(text),
                        "prompt_sha256": sha256_text(
                            request.instructions + "\0" + request.evidence
                        ),
                        "generation": generation.provenance(),
                    })
                    make_read_only(rubric_path)
                    make_read_only(metadata_path)
                return
            except Exception as exc:
                last_error = exc
                self._archive_failure(
                    task_root,
                    variant_index,
                    attempt,
                    exc,
                    generation,
                )
        assert last_error is not None
        raise RuntimeError(
            f"paraphraser failed for {task_id} variant {variant_index} after "
            f"{self.max_retries + 1} attempts: {last_error}"
        ) from last_error

    def _generate(self, request: StructuredRequest) -> GenerationResult:
        if self._generation_operation is not None:
            return self._generation_operation(self.model, request)
        endpoint = self.config.vllm_endpoints.get(self.model)
        if endpoint is not None:
            return generate_structured_vllm(self.model, request, endpoint)
        return generate_structured(self.model, request)

    def _archive_failure(
        self,
        task_root: Path,
        variant_index: int,
        attempt: int,
        error: Exception,
        generation: GenerationResult | None,
    ) -> None:
        failure_root = task_root / f"variant-{variant_index:03d}.failures"
        with self._failure_lock:
            failure_root.mkdir(exist_ok=True)
            path = failure_root / f"attempt-{attempt:03d}.json"
            write_json_atomic(path, {
                "schema_version": 1,
                "error_type": type(error).__name__,
                "error": str(error) or type(error).__name__,
                "response": generation.text if generation is not None else None,
                "generation": (
                    generation.provenance() if generation is not None else None
                ),
            })


def _paraphrase_request(
    *,
    task_id: str,
    variant_index: int,
    master: str,
    repair_error: str | None,
) -> StructuredRequest:
    repair = ""
    if repair_error is not None:
        repair = (
            "\nThe previous response failed structural validation: "
            + repair_error
            + "\nReturn a corrected complete paraphrase."
        )
    evidence = f"""Task ID: {task_id}
Paraphrase variant: {variant_index}
Use a distinct but semantically equivalent wording for this variant.{repair}

<master_rubric>
{master}
</master_rubric>
"""
    return StructuredRequest(
        instructions=_INSTRUCTIONS,
        evidence=evidence,
        schema_name="semantic_rubric_paraphrase",
        schema=_RESPONSE_SCHEMA,
        max_output_tokens=PARAPHRASE_MAX_OUTPUT_TOKENS,
    )


def validate_semantic_paraphrase(master: str, candidate: str) -> str:
    text = _validated_complete_rubric(candidate, current_rubric=master)
    if sha256_text(text) == sha256_text(master):
        raise ValueError("paraphraser returned the unchanged master rubric")
    master_levels = parse_rubric_levels_strict(master)
    candidate_levels = parse_rubric_levels_strict(text)
    if list(candidate_levels) != list(master_levels):
        raise ValueError("paraphrase changed criterion count or order")
    for key in master_levels:
        if candidate_levels[key] != master_levels[key]:
            raise ValueError(f"paraphrase changed level weights for {key}")
    if _LEAF_ID.findall(text) != _LEAF_ID.findall(master):
        raise ValueError("paraphrase changed PaperBench leaf IDs")
    return text


def resolve_paraphrase_selection(
    root: Path,
    experiment: Experiment,
    task_id: str,
    replicate: int,
) -> ParaphraseSelection:
    validate_paraphrase_run(root, experiment)
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
    if (
        set(manifest) != {
            "schema_version",
            "kind",
            "benchmark",
            "tasks_dir",
            "protocol_version",
            "model",
            "count",
            "tasks",
            "created_at",
            "updated_at",
        }
        or manifest.get("schema_version") != PARAPHRASE_RUN_SCHEMA_VERSION
        or manifest.get("kind") != PARAPHRASE_RUN_KIND
        or manifest.get("benchmark") != experiment.benchmark.value
        or manifest.get("tasks_dir") != str(experiment.tasks_dir.resolve())
        or manifest.get("protocol_version") != PARAPHRASE_PROTOCOL_VERSION
        or manifest.get("model") != experiment.rubric_paraphrases["model"]
        or manifest.get("count") != experiment.rubric_paraphrases["count"]
        or not isinstance(records, list)
        or any(
            not isinstance(record, dict)
            or set(record) != {"task_id", "master_path", "master_sha256"}
            for record in records
        )
        or type(manifest.get("created_at")) is not str
        or type(manifest.get("updated_at")) is not str
    ):
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
        _validate_task_record(
            resolved,
            experiment,
            task_id,
            record,
            count,
            model,
        )


def _validate_task_record(
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
        _validate_variant_files(
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


def _validate_variant_files(
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
    if (
        metadata.get("schema_version") != 1
        or metadata.get("kind") != "sealed-semantic-rubric-paraphrase"
        or metadata.get("protocol_version") != PARAPHRASE_PROTOCOL_VERSION
        or metadata.get("task_id") != task_id
        or metadata.get("variant_index") != variant_index
        or metadata.get("model") != model
        or metadata.get("master_path") != str(master_path)
        or metadata.get("master_sha256") != sha256_text(master)
        or metadata.get("rubric_sha256") != sha256_text(expected)
        or type(metadata.get("attempt_count")) is not int
        or metadata["attempt_count"] < 1
        or not isinstance(metadata.get("generation"), dict)
        or type(metadata.get("prompt_sha256")) is not str
    ):
        raise RuntimeError(f"rubric paraphrase metadata is invalid: {metadata_path}")


def _selected_index(seed: int, replicate: int, count: int) -> int:
    digest = hashlib.sha256(
        f"{seed}\0{replicate}\0rubric-paraphrase-set".encode("utf-8")
    ).digest()
    return int.from_bytes(digest[:8], "big") % count


@contextmanager
def _pool_lease(root: Path):
    with (root / ".paraphrase.lock").open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _now() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")
