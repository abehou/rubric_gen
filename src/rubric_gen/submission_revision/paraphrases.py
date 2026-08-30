"""Generate and validate sealed rubric paraphrase pools."""

from __future__ import annotations

import fcntl
import json
import os
import threading
from concurrent.futures import Future, ThreadPoolExecutor, as_completed
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable

from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.llm import (
    GenerationResult,
    StructuredRequest,
    generate_structured,
)
from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.experiment import Experiment
from rubric_gen.submission_revision import paraphrase_validation
from rubric_gen.submission_revision.paraphrase_protocol import (
    PARAPHRASE_INSTRUCTIONS,
    PARAPHRASE_MAX_OUTPUT_TOKENS,
    PARAPHRASE_PROTOCOL,
    PARAPHRASE_RUN_KIND,
    PARAPHRASE_VARIANT_KIND,
    WordingRequestGroup,
    duplicate_title_collisions,
    wording_template,
)


GenerationOperation = Callable[[str, StructuredRequest], GenerationResult]


@dataclass(frozen=True)
class ParaphraseRunConfig:
    experiment: Experiment
    output_dir: Path
    max_concurrency: int

    def __post_init__(self) -> None:
        if type(self.max_concurrency) is not int or self.max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")


@dataclass(frozen=True)
class _GroupGeneration:
    group_id: str
    replacements: dict[str, str]
    attempt_count: int
    prompt_sha256: str
    generation: dict[str, object]


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
        self._request_pool: ThreadPoolExecutor | None = None
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
                paraphrase_validation.validate_task_record(
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
            with ThreadPoolExecutor(
                max_workers=self.config.max_concurrency
            ) as request_pool:
                self._request_pool = request_pool
                try:
                    with ThreadPoolExecutor(
                        max_workers=self.config.max_concurrency
                    ) as variant_pool:
                        futures = [
                            variant_pool.submit(
                                self._generate_variant,
                                task_id,
                                variant_index,
                            )
                            for task_id, variant_index in jobs
                        ]
                        for future in as_completed(futures):
                            try:
                                future.result()
                            except BaseException as exc:
                                errors.append(exc)
                            progress.update()
                finally:
                    self._request_pool = None
        if errors:
            raise RuntimeError(
                f"{len(errors)} rubric paraphrase jobs failed; first error: {errors[0]}"
            ) from errors[0]
        for task_id in missing_tasks:
            record = self._task_record(task_id)
            paraphrase_validation.validate_task_record(
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
        paraphrase_validation.validate_paraphrase_run(self.root, self.experiment)
        return 0

    def _new_manifest(self) -> dict[str, object]:
        return {
            "kind": PARAPHRASE_RUN_KIND,
            "benchmark": self.experiment.benchmark.value,
            "tasks_dir": str(self.experiment.tasks_dir.resolve()),
            "protocol": PARAPHRASE_PROTOCOL,
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
        records = manifest.get("tasks")
        if (
            set(manifest) != keys
            or manifest.get("kind") != PARAPHRASE_RUN_KIND
            or manifest.get("benchmark") != self.experiment.benchmark.value
            or manifest.get("tasks_dir")
            != str(self.experiment.tasks_dir.resolve())
            or manifest.get("protocol") != PARAPHRASE_PROTOCOL
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
        template = wording_template(master)
        if self._resume_variant(
            rubric_path,
            metadata_path,
            master,
            master_path,
            task_id,
            variant_index,
        ):
            return
        ordered_results = self._generate_variant_groups(
            task_root,
            task_id,
            variant_index,
            template.groups,
        )
        replacements = {
            key: value
            for result in ordered_results
            for key, value in result.replacements.items()
        }
        candidate = template.render(replacements)
        text = paraphrase_validation.validate_semantic_paraphrase(master, candidate)
        self._commit_variant(
            task_root,
            rubric_path,
            metadata_path,
            master_path,
            master,
            task_id,
            variant_index,
            text,
            ordered_results,
        )

    def _resume_variant(
        self,
        rubric_path: Path,
        metadata_path: Path,
        master: str,
        master_path: Path,
        task_id: str,
        variant_index: int,
    ) -> bool:
        if not os.path.lexists(rubric_path) and not os.path.lexists(metadata_path):
            return False
        if rubric_path.is_file() and metadata_path.is_file():
            paraphrase_validation.validate_variant_files(
                rubric_path,
                metadata_path,
                master,
                master_path,
                task_id,
                variant_index,
                self.model,
            )
            return True
        for path in (rubric_path, metadata_path):
            if not os.path.lexists(path):
                continue
            if path.is_symlink() or not path.is_file():
                raise RuntimeError(
                    f"invalid partial rubric paraphrase artifact: {path}"
                )
            path.unlink()
        return False

    def _generate_variant_groups(
        self,
        task_root: Path,
        task_id: str,
        variant_index: int,
        groups: tuple[WordingRequestGroup, ...],
    ) -> tuple[_GroupGeneration, ...]:
        request_pool = self._request_pool
        if request_pool is None:
            raise RuntimeError("paraphrase request pool is unavailable")
        futures = {
            request_pool.submit(
                self._generate_group,
                task_root,
                task_id,
                variant_index,
                group,
            ): group.group_id
            for group in groups
        }
        results = self._collect_group_results(
            futures,
            task_id=task_id,
            variant_index=variant_index,
        )
        self._repair_duplicate_titles(
            task_root=task_root,
            task_id=task_id,
            variant_index=variant_index,
            groups=groups,
            results=results,
        )
        return tuple(results[group.group_id] for group in groups)

    @staticmethod
    def _collect_group_results(
        futures: dict[Future[_GroupGeneration], str],
        *,
        task_id: str,
        variant_index: int,
    ) -> dict[str, _GroupGeneration]:
        results: dict[str, _GroupGeneration] = {}
        errors: list[BaseException] = []
        for future in as_completed(futures):
            try:
                result = future.result()
                results[result.group_id] = result
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise RuntimeError(
                f"{len(errors)} wording units failed for {task_id} variant "
                f"{variant_index}; first error: {errors[0]}"
            ) from errors[0]
        return results

    def _commit_variant(
        self,
        task_root: Path,
        rubric_path: Path,
        metadata_path: Path,
        master_path: Path,
        master: str,
        task_id: str,
        variant_index: int,
        text: str,
        results: tuple[_GroupGeneration, ...],
    ) -> None:
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
                "kind": PARAPHRASE_VARIANT_KIND,
                "protocol": PARAPHRASE_PROTOCOL,
                "task_id": task_id,
                "variant_index": variant_index,
                "model": self.model,
                "attempt_count": sum(
                    result.attempt_count for result in results
                ),
                "master_path": str(master_path),
                "master_sha256": sha256_text(master),
                "rubric_sha256": sha256_text(text),
                "prompt_sha256": sha256_text("\0".join(
                    result.prompt_sha256 for result in results
                )),
                "generation": {
                    "strategy": "criterion-wise",
                    "requests": [
                        {
                            "group_id": result.group_id,
                            "attempt_count": result.attempt_count,
                            "prompt_sha256": result.prompt_sha256,
                            "generation": result.generation,
                        }
                        for result in results
                    ],
                },
            })

    def _repair_duplicate_titles(
        self,
        *,
        task_root: Path,
        task_id: str,
        variant_index: int,
        groups: tuple[WordingRequestGroup, ...],
        results: dict[str, _GroupGeneration],
    ) -> None:
        request_pool = self._request_pool
        if request_pool is None:
            raise RuntimeError("paraphrase request pool is unavailable")
        for _repair_round in range(self.max_retries + 1):
            collisions = duplicate_title_collisions(groups, results)
            if not collisions:
                return
            repairs = _duplicate_title_repairs(groups, collisions)
            self._run_title_repairs(
                request_pool,
                task_root,
                task_id,
                variant_index,
                results,
                repairs,
            )

        collisions = duplicate_title_collisions(groups, results)
        fields = ", ".join(
            key
            for collision in collisions
            for _group_id, key, _title in collision
        )
        raise ValueError(
            "paraphrase contains duplicate criterion titles after repair: "
            + fields
        )

    def _run_title_repairs(
        self,
        request_pool: ThreadPoolExecutor,
        task_root: Path,
        task_id: str,
        variant_index: int,
        results: dict[str, _GroupGeneration],
        repairs: dict[str, tuple[WordingRequestGroup, str]],
    ) -> None:
        futures: dict[Future[_GroupGeneration], str] = {}
        for group_id, (group, repair_error) in repairs.items():
            futures[request_pool.submit(
                self._generate_group,
                task_root,
                task_id,
                variant_index,
                group,
                initial_repair_error=repair_error,
                attempt_offset=results[group_id].attempt_count,
            )] = group_id
        for future in as_completed(futures):
            results[futures[future]] = future.result()

    def _generate_group(
        self,
        task_root: Path,
        task_id: str,
        variant_index: int,
        group: WordingRequestGroup,
        *,
        initial_repair_error: str | None = None,
        attempt_offset: int = 0,
    ) -> _GroupGeneration:
        last_error: Exception | None = (
            ValueError(initial_repair_error)
            if initial_repair_error is not None
            else None
        )
        for attempt in range(1, self.max_retries + 2):
            request = _paraphrase_request(
                task_id=task_id,
                variant_index=variant_index,
                group=group,
                repair_error=str(last_error) if last_error is not None else None,
            )
            generation: GenerationResult | None = None
            try:
                generation = self._generate(request)
                value = json.loads(generation.text)
                if not isinstance(value, dict) or set(value) != {"wording"}:
                    raise ValueError("paraphraser response has an invalid schema")
                result = _GroupGeneration(
                    group_id=group.group_id,
                    replacements=group.expand(value["wording"]),
                    attempt_count=attempt_offset + attempt,
                    prompt_sha256=sha256_text(
                        request.instructions + "\0" + request.evidence
                    ),
                    generation=generation.provenance(),
                )
                return result
            except Exception as exc:
                last_error = exc
                self._archive_failure(
                    task_root,
                    variant_index,
                    group.group_id,
                    attempt_offset + attempt,
                    exc,
                    generation,
                )
        assert last_error is not None
        raise RuntimeError(
            f"paraphraser failed for {task_id} variant {variant_index} "
            f"{group.group_id} after {self.max_retries + 1} attempts: "
            f"{last_error}"
        ) from last_error

    def _generate(self, request: StructuredRequest) -> GenerationResult:
        if self._generation_operation is not None:
            return self._generation_operation(self.model, request)
        return generate_structured(self.model, request)

    def _archive_failure(
        self,
        task_root: Path,
        variant_index: int,
        group_id: str,
        attempt: int,
        error: Exception,
        generation: GenerationResult | None,
    ) -> None:
        failure_root = task_root / f"variant-{variant_index:03d}.failures"
        with self._failure_lock:
            failure_root.mkdir(exist_ok=True)
            path = failure_root / f"{group_id}.attempt-{attempt:03d}.json"
            write_json_atomic(path, {
                "group_id": group_id,
                "error_type": type(error).__name__,
                "error": str(error) or type(error).__name__,
                "response": generation.text if generation is not None else None,
                "generation": (
                    generation.provenance() if generation is not None else None
                ),
            })


def _duplicate_title_repairs(
    groups: tuple[WordingRequestGroup, ...],
    collisions: tuple[tuple[tuple[str, str, str], ...], ...],
) -> dict[str, tuple[WordingRequestGroup, str]]:
    groups_by_id = {group.group_id: group for group in groups}
    repairs: dict[str, tuple[WordingRequestGroup, str]] = {}
    for collision in collisions:
        first_group_id, first_key, duplicate_title = collision[0]
        for group_id, key, _title in collision[1:]:
            repairs[group_id] = (
                groups_by_id[group_id],
                f"{key} duplicates {first_key} from {first_group_id}: "
                f"{json.dumps(duplicate_title, ensure_ascii=False)}. "
                "Return a distinct equivalent title that preserves the "
                "source title's distinguishing wording.",
            )
    return repairs


def _paraphrase_request(
    *,
    task_id: str,
    variant_index: int,
    group: WordingRequestGroup,
    repair_error: str | None,
) -> StructuredRequest:
    repair = ""
    if repair_error is not None:
        repair = (
            "\nThe previous response failed wording validation: "
            + repair_error
            + "\nReturn a corrected wording object."
        )
    evidence = f"""Task ID: {task_id}
Paraphrase variant: {variant_index}
Paraphrase unit: {group.group_id}
Use a distinct but semantically equivalent wording for this variant.{repair}

<wording_fields_json>
{json.dumps(
    group.fields,
    ensure_ascii=False,
    indent=2,
)}
</wording_fields_json>
"""
    return StructuredRequest(
        instructions=PARAPHRASE_INSTRUCTIONS,
        evidence=evidence,
        schema_name="wording_only_rubric_paraphrase",
        schema=group.response_schema(),
        max_output_tokens=PARAPHRASE_MAX_OUTPUT_TOKENS,
    )


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
