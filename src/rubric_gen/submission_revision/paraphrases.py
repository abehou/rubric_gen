"""Generate sealed rubric paraphrases for optimizer and holdout evaluation."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import threading
from collections import Counter
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
from rubric_gen.submission_revision.experiment import Experiment
from rubric_gen.submission_revision.judging.scoring import (
    parse_rubric_levels_strict,
)


PARAPHRASE_RUN_KIND = "rubric-gen-shared-rubric-paraphrase-pool"
PARAPHRASE_PROTOCOL = "wording-only-rubric-paraphrase"
PARAPHRASE_MAX_OUTPUT_TOKENS = 32_768
PARAPHRASE_VARIANT_KIND = "sealed-wording-only-rubric-paraphrase"
_LEAF_ID = re.compile(r"^PaperBench leaf ID:\s*(\S+)\s*$", re.MULTILINE)
_CRITERION_HEADER = re.compile(
    r"^(?P<prefix>[ \t]*Criterion[ \t]+(?P<number>\d+)[ \t]*:[ \t]*)"
    r"(?P<text>\S[^\r\n]*?)(?P<suffix>[ \t]*)$",
    re.MULTILINE,
)
_DESCRIPTION_LINE = re.compile(
    r"^(?P<prefix>[ \t]*Description:[ \t]*)"
    r"(?P<text>\S[^\r\n]*?)(?P<suffix>[ \t]*)$",
    re.MULTILINE,
)
_LEVELS_LINE = re.compile(r"^[ \t]*Levels:[ \t]*[^\r\n]+$", re.MULTILINE)
_LEVEL_DESCRIPTION = re.compile(
    r"^(?P<prefix>[ \t]*\[(?P<label>[A-Z])\]:[ \t]*)"
    r"(?P<text>\S[^\r\n]*)$",
    re.MULTILINE,
)
_FIXED_PREAMBLE_LINE = re.compile(
    r"^(?:[ \t]*RUBRIC:|[ \t]*#{1,6}[ \t]+|[ \t]*Total Points:|"
    r"[ \t]*CRITERIA(?:[ \t]|\()|[ \t]*Scoring protocol:|"
    r"[ \t]*Score normalization maximum:)"
)
_PREFIXED_PREAMBLE_LINE = re.compile(
    r"^(?P<prefix>[ \t]*(?:Notes|Purpose):[ \t]*)"
    r"(?P<text>\S[^\r\n]*?)(?P<suffix>[ \t]*)$"
)
_NUMBER_TOKEN = re.compile(r"\d+(?:,\d{3})*(?:\.\d+)?%?")
_NUMBER_PLACEHOLDER = re.compile(r"«NUMBER_[A-Z]+»")
_STRUCTURAL_WORDING_LINE = re.compile(
    r"^[ \t]*(?:Criterion[ \t]+\d+[ \t]*:|Description:|Levels:|"
    r"\[[A-Z]\]:|PaperBench leaf ID:|Scoring protocol:|"
    r"Score normalization maximum:|Total Points:|CRITERIA(?:[ \t]|\())",
    re.MULTILINE,
)

_INSTRUCTIONS = f"""Prompt contract: {PARAPHRASE_PROTOCOL}

Rewrite only the supplied wording fields. The program owns and copies all rubric
structure. You cannot edit criterion numbers, criterion order, level labels,
point values, scoring directives, normalization, or PaperBench leaf IDs. Do not
return those fields. Each request contains one complete criterion or the rubric
preamble.

Preserve all semantics within each wording field. Preserve every requirement,
exception, factual anchor, number, filename, command, identifier, example, and
scoring direction. Keep each number with the phrase that it qualifies. Do not
move content between fields. Do not add, remove, merge, split, weaken,
strengthen, clarify, or repair criteria. Do not adapt the rubric to a
submission. Do not turn examples into requirements or requirements into
examples.

Tokens such as `«NUMBER_A»` stand for exact numeric text owned by the program.
Copy each token exactly once. You may reorder a complete phrase when its meaning
does not change. Do not translate, spell out, duplicate, or add numeric text.

Change enough wording that the result is a real paraphrase. Return only the
`wording` object required by the response schema. Keep each value on one line.
Do not use Markdown code fences.
"""


@dataclass(frozen=True)
class _WordingSlot:
    key: str
    start: int
    end: int
    text: str


@dataclass(frozen=True)
class _WordingRequestGroup:
    group_id: str
    slots: tuple[_WordingSlot, ...]

    @property
    def fields(self) -> dict[str, str]:
        fields: dict[str, str] = {}
        seen_text: set[str] = set()
        for slot in self.slots:
            if slot.text in seen_text:
                continue
            fields[slot.key] = _protect_number_tokens(slot.text)
            seen_text.add(slot.text)
        return fields

    @property
    def field_keys(self) -> dict[str, str]:
        first_key_by_text: dict[str, str] = {}
        return {
            slot.key: first_key_by_text.setdefault(slot.text, slot.key)
            for slot in self.slots
        }

    def response_schema(self) -> dict[str, object]:
        fields = self.fields
        return {
            "type": "object",
            "additionalProperties": False,
            "required": ["wording"],
            "properties": {
                "wording": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": list(fields),
                    "properties": {
                        key: {
                            "type": "string",
                            "minLength": 1,
                            "maxLength": max(64, len(text) * 3),
                            "pattern": _protected_wording_pattern(text),
                        }
                        for key, text in fields.items()
                    },
                },
            },
        }

    def expand(self, wording: object) -> dict[str, str]:
        if type(wording) is not dict or set(wording) != set(self.fields):
            raise ValueError("paraphraser wording fields do not match the master")
        replacements: dict[str, str] = {}
        field_keys = self.field_keys
        for slot in self.slots:
            protected_value = wording[field_keys[slot.key]]
            if type(protected_value) is not str:
                raise ValueError(f"{slot.key} must be a string")
            value = _restore_number_tokens(slot, protected_value)
            replacements[slot.key] = value
        return self.validate_replacements(replacements)

    def validate_replacements(self, value: object) -> dict[str, str]:
        expected_keys = {slot.key for slot in self.slots}
        if type(value) is not dict or set(value) != expected_keys:
            raise ValueError("saved paraphrase fields do not match the master")
        replacements: dict[str, str] = {}
        for slot in self.slots:
            replacement = value[slot.key]
            if type(replacement) is not str:
                raise ValueError(f"{slot.key} must be a string")
            _validate_wording_value(slot, replacement)
            replacements[slot.key] = replacement
        if all(replacements[slot.key] == slot.text for slot in self.slots):
            raise ValueError("paraphraser returned an unchanged wording unit")
        return replacements


@dataclass(frozen=True)
class _WordingTemplate:
    source: str
    slots: tuple[_WordingSlot, ...]

    @property
    def groups(self) -> tuple[_WordingRequestGroup, ...]:
        grouped: dict[str, list[_WordingSlot]] = {}
        for slot in self.slots:
            if slot.key.startswith("preamble_"):
                group_id = "preamble"
            else:
                match = re.match(r"criterion_([1-9][0-9]*)_", slot.key)
                if match is None:
                    raise ValueError(f"invalid rubric wording field: {slot.key}")
                group_id = f"criterion-{int(match.group(1)):03d}"
            grouped.setdefault(group_id, []).append(slot)
        return tuple(
            _WordingRequestGroup(group_id, tuple(slots))
            for group_id, slots in grouped.items()
        )

    @property
    def fixed_fragments(self) -> tuple[str, ...]:
        fragments: list[str] = []
        cursor = 0
        for slot in self.slots:
            fragments.append(self.source[cursor:slot.start])
            cursor = slot.end
        fragments.append(self.source[cursor:])
        return tuple(fragments)

    def render(self, wording: object) -> str:
        expected_keys = {slot.key for slot in self.slots}
        if type(wording) is not dict or set(wording) != expected_keys:
            raise ValueError("paraphraser wording fields do not match the master")
        replacements: dict[str, str] = {}
        for slot in self.slots:
            value = wording[slot.key]
            if type(value) is not str:
                raise ValueError(f"{slot.key} must be a string")
            _validate_wording_value(slot, value)
            replacements[slot.key] = value

        pieces: list[str] = []
        cursor = 0
        for slot in self.slots:
            pieces.append(self.source[cursor:slot.start])
            pieces.append(replacements[slot.key])
            cursor = slot.end
        pieces.append(self.source[cursor:])
        return "".join(pieces)


def _wording_template(rubric: str) -> _WordingTemplate:
    if type(rubric) is not str or not rubric.strip():
        raise ValueError("rubric must be a non-empty string")
    if "```" in rubric:
        raise ValueError("rubric must not contain Markdown code fences")

    levels_by_criterion = parse_rubric_levels_strict(rubric)
    headers = list(_CRITERION_HEADER.finditer(rubric))
    expected_numbers = list(range(1, len(headers) + 1))
    actual_numbers = [int(header.group("number")) for header in headers]
    if actual_numbers != expected_numbers:
        raise ValueError("rubric criterion numbers must be contiguous from 1")

    slots: list[_WordingSlot] = []
    preamble = rubric[:headers[0].start()]
    preamble_index = 0
    offset = 0
    for line in preamble.splitlines(keepends=True):
        content = line.rstrip("\r\n")
        if content.strip() and _FIXED_PREAMBLE_LINE.match(content) is None:
            prefixed = _PREFIXED_PREAMBLE_LINE.match(content)
            if prefixed is not None:
                start = offset + prefixed.start("text")
                end = offset + prefixed.end("text")
            else:
                leading = len(content) - len(content.lstrip())
                trailing = len(content.rstrip())
                start = offset + leading
                end = offset + trailing
            preamble_index += 1
            slots.append(_WordingSlot(
                key=f"preamble_{preamble_index:02d}",
                start=start,
                end=end,
                text=rubric[start:end],
            ))
        offset += len(line)

    for index, header in enumerate(headers):
        number = int(header.group("number"))
        block_end = (
            headers[index + 1].start() if index + 1 < len(headers) else len(rubric)
        )
        slots.append(_WordingSlot(
            key=f"criterion_{number}_title",
            start=header.start("text"),
            end=header.end("text"),
            text=header.group("text"),
        ))

        levels_lines = list(_LEVELS_LINE.finditer(rubric, header.end(), block_end))
        if len(levels_lines) != 1:
            raise ValueError(
                f"criterion_{number} must contain exactly one Levels line"
            )
        levels_line = levels_lines[0]

        descriptions = list(
            _DESCRIPTION_LINE.finditer(rubric, header.end(), levels_line.start())
        )
        if len(descriptions) > 1:
            raise ValueError(
                f"criterion_{number} contains more than one Description line"
            )
        if descriptions:
            description = descriptions[0]
            slots.append(_WordingSlot(
                key=f"criterion_{number}_description",
                start=description.start("text"),
                end=description.end("text"),
                text=description.group("text"),
            ))

        level_descriptions = list(
            _LEVEL_DESCRIPTION.finditer(rubric, levels_line.end(), block_end)
        )
        expected_labels = list(levels_by_criterion[f"criterion_{number}"])
        actual_labels = [match.group("label") for match in level_descriptions]
        if actual_labels != expected_labels:
            raise ValueError(
                f"criterion_{number} must contain one description for each level"
            )
        for level_index, match in enumerate(level_descriptions):
            boundary = (
                level_descriptions[level_index + 1].start()
                if level_index + 1 < len(level_descriptions)
                else block_end
            )
            end = boundary
            while end > match.start("text") and rubric[end - 1].isspace():
                end -= 1
            slots.append(_WordingSlot(
                key=f"criterion_{number}_level_{match.group('label')}",
                start=match.start("text"),
                end=end,
                text=rubric[match.start("text"):end],
            ))

    slots.sort(key=lambda slot: slot.start)
    if not slots:
        raise ValueError("rubric contains no paraphrasable wording")
    if len({slot.key for slot in slots}) != len(slots):
        raise ValueError("rubric contains duplicate wording fields")
    for left, right in zip(slots, slots[1:]):
        if left.end > right.start:
            raise ValueError(f"rubric wording fields overlap at {right.key}")
    return _WordingTemplate(source=rubric, slots=tuple(slots))


def _number_placeholder(index: int) -> str:
    label = ""
    value = index + 1
    while value:
        value, remainder = divmod(value - 1, 26)
        label = chr(ord("A") + remainder) + label
    return f"«NUMBER_{label}»"


def _protect_number_tokens(value: str) -> str:
    if "«" in value or "»" in value:
        raise ValueError("rubric wording contains reserved number delimiters")
    index = 0

    def replace(_match: re.Match[str]) -> str:
        nonlocal index
        placeholder = _number_placeholder(index)
        index += 1
        return placeholder

    return _NUMBER_TOKEN.sub(replace, value)


def _protected_wording_pattern(value: str) -> str:
    placeholders = _NUMBER_PLACEHOLDER.findall(value)
    gap = r"[^«»\r\n]*"
    if not placeholders:
        return r"^[^«»\r\n]+$"
    allowed = "(?:" + "|".join(
        re.escape(placeholder) for placeholder in placeholders
    ) + ")"
    return "^" + gap + "(?:" + allowed + gap + ")*$"


def _restore_number_tokens(slot: _WordingSlot, value: str) -> str:
    numbers = _NUMBER_TOKEN.findall(slot.text)
    expected = [_number_placeholder(index) for index in range(len(numbers))]
    actual = _NUMBER_PLACEHOLDER.findall(value)
    if Counter(actual) != Counter(expected) or re.fullmatch(
        _protected_wording_pattern(_protect_number_tokens(slot.text)),
        value,
    ) is None:
        raise ValueError(
            f"{slot.key} changed its numeric placeholders; expected "
            f"{expected}, got {actual}"
        )
    restored = value
    for placeholder, number in zip(expected, numbers):
        restored = restored.replace(placeholder, number)
    return restored


def _validate_wording_value(slot: _WordingSlot, value: str) -> None:
    if not value or value != value.strip():
        raise ValueError(f"{slot.key} must be non-empty without outer whitespace")
    if "\r" in value or "\n" in value:
        raise ValueError(f"{slot.key} must stay on one line")
    if "```" in value:
        raise ValueError(f"{slot.key} must not contain Markdown code fences")
    if _STRUCTURAL_WORDING_LINE.search(value) is not None:
        raise ValueError(f"{slot.key} must not contain rubric structure")
    expected_numbers = _NUMBER_TOKEN.findall(slot.text)
    actual_numbers = _NUMBER_TOKEN.findall(value)
    if Counter(actual_numbers) != Counter(expected_numbers):
        raise ValueError(
            f"{slot.key} changed its numbers; expected "
            f"{expected_numbers}, got {actual_numbers}"
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


@dataclass(frozen=True)
class _GroupGeneration:
    group_id: str
    replacements: dict[str, str]
    attempt_count: int
    prompt_sha256: str
    generation: dict[str, object]


def _group_source_sha256(group: _WordingRequestGroup) -> str:
    return sha256_text(json.dumps(
        [[slot.key, slot.text] for slot in group.slots],
        ensure_ascii=False,
        separators=(",", ":"),
    ))


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
        parts_root = task_root / f"variant-{variant_index:03d}.parts"
        master_path = self._master_path(task_id)
        master = master_path.read_text(encoding="utf-8")
        template = _wording_template(master)
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
                self._remove_parts(parts_root)
                return
            for path in (rubric_path, metadata_path):
                if not os.path.lexists(path):
                    continue
                if path.is_symlink() or not path.is_file():
                    raise RuntimeError(
                        f"invalid partial rubric paraphrase artifact: {path}"
                    )
                path.unlink()

        groups = template.groups
        self._prepare_parts(parts_root, groups)
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
                parts_root / f"{group.group_id}.json",
            ): group.group_id
            for group in groups
        }
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

        ordered_results = [results[group.group_id] for group in groups]
        replacements = {
            key: value
            for result in ordered_results
            for key, value in result.replacements.items()
        }
        candidate = template.render(replacements)
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
                "kind": PARAPHRASE_VARIANT_KIND,
                "protocol": PARAPHRASE_PROTOCOL,
                "task_id": task_id,
                "variant_index": variant_index,
                "model": self.model,
                "attempt_count": sum(
                    result.attempt_count for result in ordered_results
                ),
                "master_path": str(master_path),
                "master_sha256": sha256_text(master),
                "rubric_sha256": sha256_text(text),
                "prompt_sha256": sha256_text("\0".join(
                    result.prompt_sha256 for result in ordered_results
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
                        for result in ordered_results
                    ],
                },
            })
            make_read_only(rubric_path)
            make_read_only(metadata_path)
        self._remove_parts(parts_root)

    def _generate_group(
        self,
        task_root: Path,
        task_id: str,
        variant_index: int,
        group: _WordingRequestGroup,
        checkpoint_path: Path,
    ) -> _GroupGeneration:
        checkpoint = self._read_group_checkpoint(
            checkpoint_path,
            task_id,
            variant_index,
            group,
        )
        if checkpoint is not None:
            return checkpoint
        last_error: Exception | None = None
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
                    attempt_count=attempt,
                    prompt_sha256=sha256_text(
                        request.instructions + "\0" + request.evidence
                    ),
                    generation=generation.provenance(),
                )
                self._write_group_checkpoint(
                    checkpoint_path,
                    task_id,
                    variant_index,
                    group,
                    result,
                )
                return result
            except Exception as exc:
                last_error = exc
                self._archive_failure(
                    task_root,
                    variant_index,
                    group.group_id,
                    attempt,
                    exc,
                    generation,
                )
        assert last_error is not None
        raise RuntimeError(
            f"paraphraser failed for {task_id} variant {variant_index} "
            f"{group.group_id} after {self.max_retries + 1} attempts: "
            f"{last_error}"
        ) from last_error

    def _prepare_parts(
        self,
        parts_root: Path,
        groups: tuple[_WordingRequestGroup, ...],
    ) -> None:
        allowed = {f"{group.group_id}.json" for group in groups}
        if os.path.lexists(parts_root):
            if parts_root.is_symlink() or not parts_root.is_dir():
                raise RuntimeError(
                    f"invalid rubric paraphrase checkpoint directory: {parts_root}"
                )
            unexpected = [
                path for path in parts_root.iterdir()
                if path.name not in allowed
            ]
            if unexpected:
                raise RuntimeError(
                    "rubric paraphrase checkpoint directory contains an "
                    f"unexpected path: {unexpected[0]}"
                )
            return
        parts_root.mkdir()

    def _read_group_checkpoint(
        self,
        path: Path,
        task_id: str,
        variant_index: int,
        group: _WordingRequestGroup,
    ) -> _GroupGeneration | None:
        if not os.path.lexists(path):
            return None
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"invalid rubric paraphrase checkpoint: {path}")
        payload = read_json_object(path, "rubric paraphrase checkpoint")
        replacements = payload.get("replacements")
        generation = payload.get("generation")
        if (
            set(payload) != {
                "task_id",
                "variant_index",
                "group_id",
                "model",
                "source_sha256",
                "replacements",
                "attempt_count",
                "prompt_sha256",
                "generation",
            }
            or payload.get("task_id") != task_id
            or payload.get("variant_index") != variant_index
            or payload.get("group_id") != group.group_id
            or payload.get("model") != self.model
            or payload.get("source_sha256") != _group_source_sha256(group)
            or type(payload.get("attempt_count")) is not int
            or payload["attempt_count"] < 1
            or type(payload.get("prompt_sha256")) is not str
            or not payload["prompt_sha256"]
            or not isinstance(generation, dict)
        ):
            raise RuntimeError(f"rubric paraphrase checkpoint is invalid: {path}")
        try:
            validated = group.validate_replacements(replacements)
        except ValueError as exc:
            raise RuntimeError(
                f"rubric paraphrase checkpoint is invalid: {path}"
            ) from exc
        return _GroupGeneration(
            group_id=group.group_id,
            replacements=validated,
            attempt_count=int(payload["attempt_count"]),
            prompt_sha256=str(payload["prompt_sha256"]),
            generation=dict(generation),
        )

    def _write_group_checkpoint(
        self,
        path: Path,
        task_id: str,
        variant_index: int,
        group: _WordingRequestGroup,
        result: _GroupGeneration,
    ) -> None:
        write_json_atomic(path, {
            "task_id": task_id,
            "variant_index": variant_index,
            "group_id": group.group_id,
            "model": self.model,
            "source_sha256": _group_source_sha256(group),
            "replacements": result.replacements,
            "attempt_count": result.attempt_count,
            "prompt_sha256": result.prompt_sha256,
            "generation": result.generation,
        })
        make_read_only(path)

    @staticmethod
    def _remove_parts(parts_root: Path) -> None:
        if not os.path.lexists(parts_root):
            return
        if parts_root.is_symlink() or not parts_root.is_dir():
            raise RuntimeError(
                f"invalid rubric paraphrase checkpoint directory: {parts_root}"
            )
        for path in parts_root.iterdir():
            if path.is_symlink() or not path.is_file():
                raise RuntimeError(
                    f"invalid rubric paraphrase checkpoint: {path}"
                )
            path.unlink()
        parts_root.rmdir()

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


def _paraphrase_request(
    *,
    task_id: str,
    variant_index: int,
    group: _WordingRequestGroup,
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
        instructions=_INSTRUCTIONS,
        evidence=evidence,
        schema_name="wording_only_rubric_paraphrase",
        schema=group.response_schema(),
        max_output_tokens=PARAPHRASE_MAX_OUTPUT_TOKENS,
    )


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
    if _LEAF_ID.findall(candidate) != _LEAF_ID.findall(master):
        raise ValueError("paraphrase changed PaperBench leaf IDs")
    master_template = _wording_template(master)
    candidate_template = _wording_template(candidate)
    if tuple(slot.key for slot in master_template.slots) != tuple(
        slot.key for slot in candidate_template.slots
    ):
        raise ValueError("paraphrase changed its wording-field layout")
    if candidate_template.fixed_fragments != master_template.fixed_fragments:
        raise ValueError("paraphrase changed immutable rubric structure")
    for master_slot, candidate_slot in zip(
        master_template.slots,
        candidate_template.slots,
    ):
        _validate_wording_value(master_slot, candidate_slot.text)
    return candidate


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
        or manifest.get("kind") != PARAPHRASE_RUN_KIND
        or manifest.get("benchmark") != experiment.benchmark.value
        or manifest.get("tasks_dir") != str(experiment.tasks_dir.resolve())
        or manifest.get("protocol") != PARAPHRASE_PROTOCOL
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
        set(metadata) != {
            "kind", "protocol", "task_id", "variant_index", "model",
            "attempt_count", "master_path", "master_sha256", "rubric_sha256",
            "prompt_sha256", "generation",
        }
        or metadata.get("kind") != PARAPHRASE_VARIANT_KIND
        or metadata.get("protocol") != PARAPHRASE_PROTOCOL
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
