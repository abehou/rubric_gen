"""Offline compilation and strict resolution of sealed task-rubric bundles."""

from __future__ import annotations

import argparse
import fcntl
import json
import math
import os
import re
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from rubric_gen.biomnibench.common import resolve_project_path
from rubric_gen.biomnibench.perturbations import GeminiPerturber
from rubric_gen.biomnibench.task_rubrics import (
    TaskProcessRubric,
    TaskSnapshot,
    build_task_snapshot,
    canonical_json,
    load_json_strict,
    parse_task_process_rubric,
    render_task_process_rubric,
    sha256_text,
    validate_rendered_task_process_rubric,
    validate_task_process_rubric,
)


TASK_RUBRIC_BUNDLE_SCHEMA_VERSION = 1
TASK_RUBRIC_COMPILER_CONFIG_SCHEMA_VERSION = 1
TASK_RUBRIC_PROMPT_VERSION = "task-process-rubric-v1"
TASK_RUBRIC_PROVIDER = "google-gemini"
_SAFE_TASK_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_COMPILER_CONFIG_KEYS = {
    "api_key_env",
    "bundle_schema_version",
    "max_concurrency",
    "max_retries",
    "model",
    "prompt_version",
    "schema_version",
    "task_ids",
    "tasks_dir",
    "temperature",
}
_GENERATION_CODE_KEYS = {
    "task_rubric_compiler.py",
    "task_rubrics.py",
    "perturbations.py",
}

_RUBRIC_JSON_SCHEMA: dict[str, object] = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "additionalProperties": False,
    "properties": {
        "criteria": {
            "items": {
                "additionalProperties": False,
                "properties": {
                    "acceptable_alternatives": {
                        "items": {"type": "string"},
                        "minItems": 1,
                        "type": "array",
                    },
                    "anti_evidence": {
                        "items": {"type": "string"},
                        "minItems": 1,
                        "type": "array",
                    },
                    "criterion_id": {"type": "string"},
                    "description": {"type": "string"},
                    "levels": {
                        "items": {
                            "additionalProperties": False,
                            "properties": {
                                "description": {"type": "string"},
                                "label": {
                                    "pattern": "^[A-Z]$",
                                    "type": "string",
                                },
                                "points": {"type": "integer"},
                            },
                            "required": ["label", "points", "description"],
                            "type": "object",
                        },
                        "maxItems": 26,
                        "minItems": 3,
                        "type": "array",
                    },
                    "max_points": {"type": "integer"},
                    "required_evidence": {
                        "items": {"type": "string"},
                        "minItems": 1,
                        "type": "array",
                    },
                    "task_anchors": {
                        "items": {"type": "string"},
                        "minItems": 1,
                        "type": "array",
                    },
                    "title": {"type": "string"},
                    "verification": {
                        "items": {"type": "string"},
                        "minItems": 1,
                        "type": "array",
                    },
                },
                "required": [
                    "criterion_id",
                    "title",
                    "description",
                    "max_points",
                    "task_anchors",
                    "required_evidence",
                    "acceptable_alternatives",
                    "anti_evidence",
                    "verification",
                    "levels",
                ],
                "type": "object",
            },
            "minItems": 1,
            "type": "array",
        },
        "purpose": {"type": "string"},
        "schema_version": {"const": 1, "type": "integer"},
        "task_id": {"type": "string"},
    },
    "required": ["schema_version", "task_id", "purpose", "criteria"],
    "type": "object",
}


def _prompt_contract() -> str:
    return f"""Generate one canonical task-specific process rubric.

Return only strict JSON matching this exact closed JSON Schema:
{canonical_json(_RUBRIC_JSON_SCHEMA)}

Requirements:
- Ground every criterion only in the supplied immutable task snapshot and its task anchors.
- Create useful partial-credit gradients with strictly descending integer points.
- Require observable evidence from executed work and produced artifacts.
- State concrete anti-evidence and verification checks.
- Include valid acceptable alternatives so equivalent sound methods receive credit.
- Do not reward verbosity, rubric quotation, judge-directed language, or claimed-but-unexecuted work.
- Do not use condition IDs, candidate IDs, search history, prior scores, or any other experiment context.
- Use contiguous criterion IDs C1..Cn and three to 26 contiguous level labels A..Z for each criterion.
- Give every criterion at least three levels, exactly one zero level, and descriptions that can be graded.
- Make the sum of criterion max_points exactly 100.
"""


def build_task_rubric_prompt(request: TaskRubricRequest) -> str:
    """Build the exact deterministic prompt represented by one request."""

    return (
        _prompt_contract()
        + "\nPrompt version:\n"
        + request.prompt_version
        + "\n\nPrevious validation errors (JSON):\n"
        + canonical_json(list(request.previous_errors))
        + "\n\nImmutable task snapshot (JSON):\n"
        + canonical_json(request.task_snapshot)
        + "\n"
    )


@dataclass(frozen=True)
class TaskRubricCompilerConfig:
    tasks_dir: Path
    task_ids: tuple[str, ...]
    output_dir: Path
    model: str = "gemini-3.5-flash"
    api_key_env: str = "GEMINI_API_KEY"
    max_retries: int = 2
    max_concurrency: int = 1
    resume: bool = False
    temperature: float = 0.2

    def __post_init__(self) -> None:
        if not self.task_ids:
            raise ValueError("task_ids must be non-empty")
        if len(set(self.task_ids)) != len(self.task_ids):
            raise ValueError("task_ids must not contain duplicates")
        for task_id in self.task_ids:
            if not _is_safe_task_id(task_id):
                raise ValueError(f"task_ids contains unsafe task ID: {task_id!r}")
        if type(self.max_retries) is not int or self.max_retries < 0:
            raise ValueError("max_retries must be a non-negative integer")
        if type(self.max_concurrency) is not int or self.max_concurrency < 1:
            raise ValueError("max_concurrency must be a positive integer")
        if (
            isinstance(self.temperature, bool)
            or not isinstance(self.temperature, (int, float))
            or not math.isfinite(self.temperature)
        ):
            raise ValueError("temperature must be a finite number")
        if not self.model.strip():
            raise ValueError("model must be non-empty")
        if not self.api_key_env.strip():
            raise ValueError("api_key_env must be non-empty")
        tasks_root = self.tasks_dir.expanduser().resolve()
        output_root = self.output_dir.expanduser().resolve()
        if (
            tasks_root == output_root
            or tasks_root.is_relative_to(output_root)
            or output_root.is_relative_to(tasks_root)
        ):
            raise ValueError("output_dir and tasks_dir must not overlap")

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "TaskRubricCompilerConfig":
        return cls(
            tasks_dir=resolve_project_path(args.tasks_dir),
            task_ids=tuple(args.tasks),
            output_dir=resolve_project_path(args.output_dir),
            model=getattr(args, "model", "gemini-3.5-flash"),
            api_key_env=getattr(args, "api_key_env", "GEMINI_API_KEY"),
            max_retries=max(0, getattr(args, "max_retries", 2)),
            max_concurrency=max(1, getattr(args, "max_concurrency", 1)),
            resume=getattr(args, "resume", False),
        )


@dataclass(frozen=True)
class TaskRubricRequest:
    schema_version: int
    prompt_version: str
    task_snapshot: dict[str, object]
    previous_errors: tuple[str, ...] = ()


class TaskRubricRewriter(Protocol):
    def rewrite(self, request: TaskRubricRequest) -> str:
        ...


class _ConfiguredGeminiPerturber(GeminiPerturber):
    def __init__(self, *, temperature: float, **kwargs: object) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self.temperature = temperature

    def request_body(self, prompt: str) -> dict[str, object]:
        body = super().request_body(prompt)
        body["generationConfig"] = {"temperature": self.temperature}
        return body


class GeminiTaskRubricRewriter:
    """Gemini adapter for the runtime-blind canonical rubric request."""

    def __init__(
        self,
        *,
        model: str = "gemini-3.5-flash",
        api_key_env: str = "GEMINI_API_KEY",
        temperature: float = 0.2,
    ) -> None:
        self.client = _ConfiguredGeminiPerturber(
            model=model,
            api_key_env=api_key_env,
            temperature=temperature,
        )

    def rewrite(self, request: TaskRubricRequest) -> str:
        return self.client.generate_content(self.build_prompt(request))

    def build_prompt(self, request: TaskRubricRequest) -> str:
        return build_task_rubric_prompt(request)


class RubricBundleError(ValueError):
    """Raised when a sealed rubric bundle cannot be trusted."""


@dataclass(frozen=True)
class ResolvedRubricBundle:
    task_id: str
    rubric_set_id: str
    rubric_id: str
    rubric_sha256: str
    rubric_json_path: Path
    rendered_path: Path
    task_manifest_path: Path


@dataclass(frozen=True)
class _CompiledTask:
    task_id: str
    snapshot: TaskSnapshot
    task_dir: Path
    rubric: TaskProcessRubric
    raw_response: str
    rubric_sha256: str
    rendered_sha256: str
    artifact_hashes: dict[str, str]
    input_sha256: str
    prompt_sha256: str
    generated_at: str


def _is_safe_task_id(task_id: object) -> bool:
    return isinstance(task_id, str) and bool(_SAFE_TASK_ID.fullmatch(task_id))


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256_file(path: Path) -> str:
    import hashlib

    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(65_536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(canonical_json(value) + "\n", encoding="utf-8")


def _artifact_hashes(task_dir: Path) -> dict[str, str]:
    artifacts: dict[str, str] = {}
    for path in sorted(task_dir.rglob("*")):
        if path.is_symlink():
            raise RubricBundleError(f"bundle artifact must not be a symlink: {path}")
        if path.is_file() and path.name != "manifest.json":
            artifacts[path.relative_to(task_dir).as_posix()] = _sha256_file(path)
    return artifacts


def _input_sha256(snapshot: TaskSnapshot) -> str:
    return sha256_text(canonical_json([list(item) for item in snapshot.input_hashes]))


def _config_payload(config: TaskRubricCompilerConfig) -> dict[str, object]:
    return {
        "api_key_env": config.api_key_env,
        "bundle_schema_version": TASK_RUBRIC_BUNDLE_SCHEMA_VERSION,
        "max_concurrency": config.max_concurrency,
        "max_retries": config.max_retries,
        "model": config.model,
        "prompt_version": TASK_RUBRIC_PROMPT_VERSION,
        "schema_version": TASK_RUBRIC_COMPILER_CONFIG_SCHEMA_VERSION,
        "task_ids": list(config.task_ids),
        "tasks_dir": str(config.tasks_dir.resolve()),
        "temperature": config.temperature,
    }


def _generation_code_sha256s() -> dict[str, str]:
    module_dir = Path(__file__).parent
    return {
        module_name: _sha256_file(module_dir / module_name)
        for module_name in sorted(_GENERATION_CODE_KEYS)
    }


def _compilation_payload(
    config_sha256: str,
    generation_code_sha256: str,
    tasks: dict[str, dict[str, str]],
) -> dict[str, object]:
    return {
        "compiler_config_sha256": config_sha256,
        "generation_code_sha256": generation_code_sha256,
        "tasks": tasks,
    }


def _snapshot_compilation_tasks(
    snapshots: tuple[TaskSnapshot, ...],
) -> dict[str, dict[str, str]]:
    return {
        snapshot.task_id: {
            "input_sha256": _input_sha256(snapshot),
            "snapshot_sha256": snapshot.snapshot_sha256,
        }
        for snapshot in snapshots
    }


def _rubric_set_identity(
    compilation_sha256: str,
    generation_code_sha256: str,
    results: dict[str, _CompiledTask],
) -> dict[str, object]:
    return {
        "compilation_sha256": compilation_sha256,
        "generation_code_sha256": generation_code_sha256,
        "schema_version": TASK_RUBRIC_BUNDLE_SCHEMA_VERSION,
        "tasks": {
            task_id: {
                "input_sha256": result.input_sha256,
                "rubric_id": result.rubric_sha256,
                "snapshot_sha256": result.snapshot.snapshot_sha256,
            }
            for task_id, result in sorted(results.items())
        },
    }


def _incomplete_rubric_set_identity(
    compilation_sha256: str,
    generation_code_sha256: str,
    results: dict[str, _CompiledTask],
    errors: dict[str, str],
) -> dict[str, object]:
    identity = _rubric_set_identity(
        compilation_sha256,
        generation_code_sha256,
        results,
    )
    identity["failures"] = {
        task_id: errors[task_id]
        for task_id in sorted(errors)
    }
    identity["status"] = "incomplete"
    return identity


class TaskProcessRubricCompiler:
    """Compile immutable task snapshots into one sealed external rubric set."""

    def __init__(
        self,
        config: TaskRubricCompilerConfig,
        *,
        rewriter: TaskRubricRewriter | None = None,
    ) -> None:
        self.config = config
        self.rewriter = rewriter or GeminiTaskRubricRewriter(
            model=config.model,
            api_key_env=config.api_key_env,
            temperature=config.temperature,
        )
        self.last_errors: tuple[str, ...] = ()

    def run(self) -> int:
        try:
            snapshots = tuple(
                build_task_snapshot(self.config.tasks_dir / task_id)
                for task_id in self.config.task_ids
            )
        except (OSError, ValueError) as exc:
            self.last_errors = (f"input error: {exc}",)
            return 1

        compiler_config = _config_payload(self.config)
        config_sha256 = sha256_text(canonical_json(compiler_config))
        generation_code_sha256s = _generation_code_sha256s()
        generation_code_sha256 = sha256_text(canonical_json(
            generation_code_sha256s
        ))
        compilation_sha256 = sha256_text(canonical_json(
            _compilation_payload(
                config_sha256,
                generation_code_sha256,
                _snapshot_compilation_tasks(snapshots),
            )
        ))
        output_dir = self.config.output_dir
        if os.path.lexists(output_dir):
            if self.config.resume and self._can_resume(
                snapshots,
                config_sha256,
                compilation_sha256,
            ):
                return 0
            self.last_errors = (
                f"output directory already exists and cannot be overwritten: {output_dir}",
            )
            return 1

        output_dir.parent.mkdir(parents=True, exist_ok=True)
        temporary = Path(tempfile.mkdtemp(
            prefix=f".{output_dir.name}.tmp-",
            dir=output_dir.parent,
        ))
        try:
            results, errors = self._compile_all(temporary, snapshots)
            if errors:
                self.last_errors = tuple(errors[task_id] for task_id in sorted(errors))
                _write_json(temporary / "failure.json", {
                    "errors": errors,
                    "schema_version": TASK_RUBRIC_BUNDLE_SCHEMA_VERSION,
                    "status": "failed",
                })
                if results:
                    rubric_set_id = sha256_text(canonical_json(
                        _incomplete_rubric_set_identity(
                            compilation_sha256,
                            generation_code_sha256,
                            results,
                            errors,
                        )
                    ))
                    task_entries = self._write_task_manifests(
                        rubric_set_id,
                        results,
                        config_sha256,
                        generation_code_sha256s,
                        generation_code_sha256,
                    )
                    _write_json(temporary / "incomplete-manifest.json", {
                        "compilation_sha256": compilation_sha256,
                        "compiler_config": compiler_config,
                        "compiler_config_sha256": config_sha256,
                        "failures": {
                            task_id: errors[task_id]
                            for task_id in sorted(errors)
                        },
                        "generated_at": _utc_now(),
                        "generation_code_sha256": generation_code_sha256,
                        "generation_code_sha256s": generation_code_sha256s,
                        "rubric_set_id": rubric_set_id,
                        "schema_version": TASK_RUBRIC_BUNDLE_SCHEMA_VERSION,
                        "status": "incomplete",
                        "successful_task_ids": sorted(results),
                        "tasks": task_entries,
                    })
                self._publish(temporary, output_dir)
                return 1

            rubric_set_id = sha256_text(canonical_json(
                _rubric_set_identity(
                    compilation_sha256,
                    generation_code_sha256,
                    results,
                )
            ))
            task_entries = self._write_task_manifests(
                rubric_set_id,
                results,
                config_sha256,
                generation_code_sha256s,
                generation_code_sha256,
            )
            root_manifest = {
                "compilation_sha256": compilation_sha256,
                "compiler_config": compiler_config,
                "compiler_config_sha256": config_sha256,
                "generated_at": _utc_now(),
                "generation_code_sha256": generation_code_sha256,
                "generation_code_sha256s": generation_code_sha256s,
                "prompt_version": TASK_RUBRIC_PROMPT_VERSION,
                "rubric_set_id": rubric_set_id,
                "schema_version": TASK_RUBRIC_BUNDLE_SCHEMA_VERSION,
                "status": "sealed",
                "tasks": task_entries,
            }
            _write_json(temporary / "manifest.json", root_manifest)
            self._publish(temporary, output_dir)
            return 0
        except (OSError, RubricBundleError) as exc:
            self.last_errors = (f"bundle write error: {exc}",)
            return 1
        finally:
            if temporary.exists():
                shutil.rmtree(temporary)

    def _compile_all(
        self,
        temporary: Path,
        snapshots: tuple[TaskSnapshot, ...],
    ) -> tuple[dict[str, _CompiledTask], dict[str, str]]:
        results: dict[str, _CompiledTask] = {}
        errors: dict[str, str] = {}
        if self.config.max_concurrency == 1 or len(snapshots) == 1:
            for snapshot in snapshots:
                result, error = self._compile_task(temporary, snapshot)
                if result is not None:
                    results[snapshot.task_id] = result
                else:
                    errors[snapshot.task_id] = error
            return results, errors

        with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as executor:
            futures = {
                executor.submit(self._compile_task, temporary, snapshot): snapshot
                for snapshot in snapshots
            }
            for future in as_completed(futures):
                snapshot = futures[future]
                result, error = future.result()
                if result is not None:
                    results[snapshot.task_id] = result
                else:
                    errors[snapshot.task_id] = error
        return results, errors

    def _compile_task(
        self,
        temporary: Path,
        snapshot: TaskSnapshot,
    ) -> tuple[_CompiledTask | None, str]:
        task_dir = temporary / "tasks" / snapshot.task_id
        attempts_dir = task_dir / "attempts"
        attempts_dir.mkdir(parents=True)
        previous_errors: list[str] = []

        for attempt_index in range(self.config.max_retries + 1):
            request = TaskRubricRequest(
                schema_version=TASK_RUBRIC_BUNDLE_SCHEMA_VERSION,
                prompt_version=TASK_RUBRIC_PROMPT_VERSION,
                task_snapshot=snapshot.to_dict(),
                previous_errors=tuple(previous_errors),
            )
            attempt_dir = attempts_dir / f"attempt-{attempt_index + 1}"
            attempt_dir.mkdir()
            _write_json(attempt_dir / "request.json", asdict(request))
            response = ""
            errors: tuple[str, ...]
            rubric: TaskProcessRubric | None = None
            rendered: str | None = None
            try:
                response = self.rewriter.rewrite(request)
                if not isinstance(response, str):
                    raise TypeError("rewriter response must be a string")
                rubric = parse_task_process_rubric(response)
                errors = validate_task_process_rubric(rubric, snapshot)
                if not errors:
                    rendered = render_task_process_rubric(rubric)
                    validate_rendered_task_process_rubric(rubric, rendered)
            except Exception as exc:  # The attempt is audited and may be retried.
                raw_response = getattr(exc, "raw_response", None)
                if isinstance(raw_response, str):
                    response = raw_response
                errors = (f"invalid JSON rubric: {type(exc).__name__}: {exc}",)

            (attempt_dir / "response.txt").write_text(response, encoding="utf-8")
            _write_json(attempt_dir / "errors.json", list(errors))
            if rubric is not None and rendered is not None and not errors:
                structured = canonical_json(asdict(rubric)) + "\n"
                (task_dir / "raw_response.txt").write_text(response, encoding="utf-8")
                (task_dir / "rubric.json").write_text(structured, encoding="utf-8")
                (task_dir / "process_rubric.txt").write_text(rendered, encoding="utf-8")
                prompt_sha256 = sha256_text(build_task_rubric_prompt(request))
                return _CompiledTask(
                    task_id=snapshot.task_id,
                    snapshot=snapshot,
                    task_dir=task_dir,
                    rubric=rubric,
                    raw_response=response,
                    rubric_sha256=_sha256_file(task_dir / "rubric.json"),
                    rendered_sha256=_sha256_file(task_dir / "process_rubric.txt"),
                    artifact_hashes=_artifact_hashes(task_dir),
                    input_sha256=_input_sha256(snapshot),
                    prompt_sha256=prompt_sha256,
                    generated_at=_utc_now(),
                ), ""
            previous_errors.extend(errors)

        return None, previous_errors[-1]

    def _task_manifest(
        self,
        rubric_set_id: str,
        result: _CompiledTask,
        compiler_config_sha256: str,
        generation_code_sha256s: dict[str, str],
        generation_code_sha256: str,
    ) -> dict[str, object]:
        model_sha256 = sha256_text(self.config.model)
        temperature_sha256 = sha256_text(canonical_json(self.config.temperature))
        raw_sha256 = result.artifact_hashes["raw_response.txt"]
        return {
            "artifacts": result.artifact_hashes,
            "compiler": {
                "code_sha256": generation_code_sha256,
                "code_sha256s": generation_code_sha256s,
                "compiler_config_sha256": compiler_config_sha256,
                "model": self.config.model,
                "prompt_version": TASK_RUBRIC_PROMPT_VERSION,
                "provider": TASK_RUBRIC_PROVIDER,
                "schema_version": TASK_RUBRIC_BUNDLE_SCHEMA_VERSION,
                "temperature": self.config.temperature,
            },
            "generated_at": result.generated_at,
            "hashes": {
                "input_sha256": result.input_sha256,
                "model_sha256": model_sha256,
                "prompt_sha256": result.prompt_sha256,
                "raw_response_sha256": raw_sha256,
                "rendered_rubric_sha256": result.rendered_sha256,
                "snapshot_sha256": result.snapshot.snapshot_sha256,
                "structured_rubric_sha256": result.rubric_sha256,
                "temperature_sha256": temperature_sha256,
            },
            "rubric_id": result.rubric_sha256,
            "rubric_set_id": rubric_set_id,
            "rubric_sha256": result.rubric_sha256,
            "schema_version": TASK_RUBRIC_BUNDLE_SCHEMA_VERSION,
            "snapshot": {
                "input_hashes": [list(item) for item in result.snapshot.input_hashes],
                "input_sha256": result.input_sha256,
                "sha256": result.snapshot.snapshot_sha256,
            },
            "status": "valid",
            "task_id": result.task_id,
            "validation_errors": [],
        }

    def _write_task_manifests(
        self,
        rubric_set_id: str,
        results: dict[str, _CompiledTask],
        compiler_config_sha256: str,
        generation_code_sha256s: dict[str, str],
        generation_code_sha256: str,
    ) -> dict[str, dict[str, object]]:
        task_entries: dict[str, dict[str, object]] = {}
        for task_id, result in sorted(results.items()):
            task_manifest_path = result.task_dir / "manifest.json"
            _write_json(
                task_manifest_path,
                self._task_manifest(
                    rubric_set_id,
                    result,
                    compiler_config_sha256,
                    generation_code_sha256s,
                    generation_code_sha256,
                ),
            )
            task_entries[task_id] = {
                "input_sha256": result.input_sha256,
                "rubric_id": result.rubric_sha256,
                "rubric_sha256": result.rubric_sha256,
                "snapshot_sha256": result.snapshot.snapshot_sha256,
                "task_manifest_path": f"tasks/{task_id}/manifest.json",
                "task_manifest_sha256": _sha256_file(task_manifest_path),
            }
        return task_entries

    def _can_resume(
        self,
        snapshots: tuple[TaskSnapshot, ...],
        config_sha256: str,
        compilation_sha256: str,
    ) -> bool:
        try:
            root = _read_json_object(self.config.output_dir / "manifest.json", "root manifest")
            if root.get("compiler_config_sha256") != config_sha256:
                return False
            if root.get("compilation_sha256") != compilation_sha256:
                return False
            if set(_object(root.get("tasks"), "root tasks")) != {
                snapshot.task_id for snapshot in snapshots
            }:
                return False
            for snapshot in snapshots:
                resolved = resolve_rubric_bundle(self.config.output_dir, snapshot.task_id)
                if resolved.task_id != snapshot.task_id:
                    return False
            return True
        except (OSError, RubricBundleError):
            return False

    @staticmethod
    def _publish(temporary: Path, output_dir: Path) -> None:
        lock_path = output_dir.parent / f".{output_dir.name}.lock"
        with lock_path.open("a+b") as lock_stream:
            fcntl.flock(lock_stream.fileno(), fcntl.LOCK_EX)
            try:
                if os.path.lexists(output_dir):
                    raise RubricBundleError(
                        f"refusing to overwrite existing output: {output_dir}"
                    )
                temporary.rename(output_dir)
            finally:
                fcntl.flock(lock_stream.fileno(), fcntl.LOCK_UN)


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
    if not _SHA256.fullmatch(digest):
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
    for field_name in ("api_key_env", "model", "tasks_dir"):
        if type(config[field_name]) is not str or not config[field_name]:
            raise RubricBundleError(f"compiler config {field_name} must be a string")
    task_ids = config["task_ids"]
    if (
        type(task_ids) is not list
        or not task_ids
        or any(not _is_safe_task_id(task_id) for task_id in task_ids)
        or len(set(task_ids)) != len(task_ids)
    ):
        raise RubricBundleError("compiler config task_ids is invalid")
    if type(config["max_retries"]) is not int or config["max_retries"] < 0:
        raise RubricBundleError("compiler config max_retries is invalid")
    if type(config["max_concurrency"]) is not int or config["max_concurrency"] < 1:
        raise RubricBundleError("compiler config max_concurrency is invalid")
    temperature = config["temperature"]
    if (
        isinstance(temperature, bool)
        or not isinstance(temperature, (int, float))
        or not math.isfinite(temperature)
    ):
        raise RubricBundleError("compiler config temperature is invalid")
    return config


def _validated_generation_code_sha256s(value: object) -> dict[str, str]:
    raw_hashes = _object(value, "generation code hashes")
    _closed_keys(raw_hashes, _GENERATION_CODE_KEYS, "generation code hashes")
    return {
        module_name: _hash(raw_hashes[module_name], f"generation code {module_name}")
        for module_name in sorted(_GENERATION_CODE_KEYS)
    }


_ROOT_TASK_ENTRY_KEYS = {
    "input_sha256",
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
        if not _is_safe_task_id(member_id):
            raise RubricBundleError(f"unsafe root task ID: {member_id!r}")
        entry = _object(raw_entry, f"root task entry {member_id}")
        _closed_keys(entry, _ROOT_TASK_ENTRY_KEYS, f"root task entry {member_id}")
        input_sha256 = _hash(entry["input_sha256"], f"root input hash {member_id}")
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
            "rubric_id": rubric_id,
            "snapshot_sha256": snapshot_sha256,
        }
    return entries, compilation_tasks, identity_tasks


def _read_json_object(path: Path, context: str) -> dict[str, object]:
    if path.is_symlink() or not path.is_file():
        raise RubricBundleError(f"missing regular {context}: {path}")
    try:
        value = load_json_strict(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise RubricBundleError(f"invalid {context}: {exc}") from exc
    return _object(value, context)


def _read_json_string_list(path: Path, context: str) -> list[str]:
    if path.is_symlink() or not path.is_file():
        raise RubricBundleError(f"missing regular {context}: {path}")
    try:
        value = load_json_strict(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise RubricBundleError(f"invalid {context}: {exc}") from exc
    if type(value) is not list or any(not isinstance(item, str) for item in value):
        raise RubricBundleError(f"{context} must be an array of strings")
    return value


def _artifact_path(task_dir: Path, relative: str) -> Path:
    candidate = Path(relative)
    if candidate.is_absolute() or ".." in candidate.parts or candidate.as_posix() != relative:
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
    task_dir: Path,
) -> None:
    snapshot_record = _object(task_manifest["snapshot"], "snapshot record")
    _closed_keys(snapshot_record, {"input_hashes", "input_sha256", "sha256"}, "snapshot record")
    input_hashes = snapshot_record["input_hashes"]
    if type(input_hashes) is not list:
        raise RubricBundleError("snapshot input_hashes must be an array")
    input_sha256 = _hash(snapshot_record["input_sha256"], "snapshot input_sha256")
    if sha256_text(canonical_json(input_hashes)) != input_sha256:
        raise RubricBundleError("snapshot input hash mismatch")
    snapshot_sha256 = _hash(snapshot_record["sha256"], "snapshot sha256")

    attempts_root = task_dir / "attempts"
    if attempts_root.is_symlink() or not attempts_root.is_dir():
        raise RubricBundleError("attempts root must be a regular directory")
    raw_attempts = list(attempts_root.iterdir())
    if not raw_attempts:
        raise RubricBundleError("task bundle has no generation attempts")
    attempt_numbers: list[int] = []
    for path in raw_attempts:
        match = re.fullmatch(r"attempt-([1-9][0-9]*)", path.name)
        if path.is_symlink() or not path.is_dir() or match is None:
            raise RubricBundleError("attempt directories are not canonical")
        attempt_numbers.append(int(match.group(1)))
    attempt_numbers.sort()
    if attempt_numbers != list(range(1, len(attempt_numbers) + 1)):
        raise RubricBundleError("attempt directories must be contiguous")

    snapshot: dict[str, object] | None = None
    flattened_errors: list[str] = []
    successful_request: dict[str, object] | None = None
    successful_attempt: Path | None = None
    expected_files = {"request.json", "response.txt", "errors.json"}
    for attempt_number in attempt_numbers:
        attempt_dir = attempts_root / f"attempt-{attempt_number}"
        attempt_members = list(attempt_dir.iterdir())
        if (
            {path.name for path in attempt_members} != expected_files
            or any(path.is_symlink() or not path.is_file() for path in attempt_members)
        ):
            raise RubricBundleError(
                f"attempt-{attempt_number} does not contain exactly the required files"
            )
        context = f"attempt-{attempt_number} request"
        request = _read_json_object(attempt_dir / "request.json", context)
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
        if (
            type(previous_errors) is not list
            or any(not isinstance(error, str) for error in previous_errors)
        ):
            raise RubricBundleError(f"{context} previous_errors must be strings")
        if previous_errors != flattened_errors:
            raise RubricBundleError(f"{context} previous-error chain mismatch")
        errors = _read_json_string_list(
            attempt_dir / "errors.json",
            f"attempt-{attempt_number} errors",
        )
        is_final = attempt_number == attempt_numbers[-1]
        if is_final:
            if errors:
                raise RubricBundleError("final generation attempt was not successful")
            successful_request = request
            successful_attempt = attempt_dir
        elif not errors:
            raise RubricBundleError("intermediate generation attempt has no errors")
        flattened_errors.extend(errors)

    if snapshot is None or successful_request is None or successful_attempt is None:
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
    if _sha256_file(successful_attempt / "response.txt") != hashes["raw_response_sha256"]:
        raise RubricBundleError("successful response does not match raw response")


def resolve_rubric_bundle(
    rubric_set_dir: Path,
    task_id: str,
) -> ResolvedRubricBundle:
    """Resolve one task from a sealed set after verifying all bundle attestations."""

    if not _is_safe_task_id(task_id):
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
    _closed_keys(root_manifest, {
        "compilation_sha256",
        "compiler_config",
        "compiler_config_sha256",
        "generated_at",
        "generation_code_sha256",
        "generation_code_sha256s",
        "prompt_version",
        "rubric_set_id",
        "schema_version",
        "status",
        "tasks",
    }, "root manifest")
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
    if (
        sha256_text(canonical_json(generation_code_sha256s))
        != generation_code_sha256
    ):
        raise RubricBundleError("generation code hash-map mismatch")
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
    expected_compilation_sha256 = sha256_text(canonical_json(
        _compilation_payload(
            compiler_config_sha256,
            generation_code_sha256,
            compilation_tasks,
        )
    ))
    if compilation_sha256 != expected_compilation_sha256:
        raise RubricBundleError("compilation hash mismatch")

    tasks_root = root / "tasks"
    if tasks_root.is_symlink() or not tasks_root.is_dir():
        raise RubricBundleError("tasks root must be a regular directory")
    actual_tasks = {path.name for path in tasks_root.iterdir() if path.is_dir()}
    if actual_tasks != set(tasks) or any(not path.is_dir() for path in tasks_root.iterdir()):
        raise RubricBundleError("task directory membership does not match root manifest")

    task_entry = task_entries[task_id]

    task_dir = tasks_root / task_id
    if task_dir.is_symlink() or task_dir.resolve(strict=True).parent != tasks_root.resolve(strict=True):
        raise RubricBundleError("task bundle leaves rubric set root")
    task_manifest_path = task_dir / "manifest.json"
    expected_manifest_sha256 = _hash(
        task_entry["task_manifest_sha256"],
        "task manifest sha256",
    )
    try:
        actual_manifest_sha256 = _sha256_file(task_manifest_path)
    except OSError as exc:
        raise RubricBundleError(
            f"missing or unreadable task manifest: {task_manifest_path}"
        ) from exc
    if actual_manifest_sha256 != expected_manifest_sha256:
        raise RubricBundleError("task manifest hash mismatch")
    task_manifest = _read_json_object(task_manifest_path, "task manifest")
    _closed_keys(task_manifest, {
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
    }, "task manifest")
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
    required_artifacts = {"raw_response.txt", "rubric.json", "process_rubric.txt"}
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
    for relative, expected in artifacts.items():
        path = _artifact_path(task_dir, relative)
        if path.is_symlink() or not path.is_file():
            raise RubricBundleError(f"bundle artifact is not a regular file: {relative}")
        if _sha256_file(path) != _hash(expected, f"artifact hash {relative}"):
            raise RubricBundleError(f"bundle artifact hash mismatch: {relative}")

    compiler = _object(task_manifest["compiler"], "compiler record")
    _closed_keys(compiler, {
        "code_sha256",
        "code_sha256s",
        "compiler_config_sha256",
        "model",
        "prompt_version",
        "provider",
        "schema_version",
        "temperature",
    }, "compiler record")
    if (
        _hash(compiler["code_sha256"], "compiler code sha256")
        != generation_code_sha256
    ):
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
    if compiler["provider"] != TASK_RUBRIC_PROVIDER:
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
    if canonical_json(compiler["temperature"]) != canonical_json(
        compiler_config["temperature"]
    ):
        raise RubricBundleError(
            "task compiler temperature disagrees with root config"
        )

    hashes = _object(task_manifest["hashes"], "task hashes")
    _closed_keys(hashes, {
        "input_sha256",
        "model_sha256",
        "prompt_sha256",
        "raw_response_sha256",
        "rendered_rubric_sha256",
        "snapshot_sha256",
        "structured_rubric_sha256",
        "temperature_sha256",
    }, "task hashes")
    for name, digest in hashes.items():
        _hash(digest, name)
    if hashes["model_sha256"] != sha256_text(_string(compiler["model"], "compiler model")):
        raise RubricBundleError("model hash mismatch")
    if hashes["temperature_sha256"] != sha256_text(canonical_json(compiler["temperature"])):
        raise RubricBundleError("temperature hash mismatch")
    if hashes["raw_response_sha256"] != artifacts["raw_response.txt"]:
        raise RubricBundleError("raw-response hash mismatch")
    if hashes["structured_rubric_sha256"] != artifacts["rubric.json"]:
        raise RubricBundleError("structured-rubric hash mismatch")
    if hashes["rendered_rubric_sha256"] != artifacts["process_rubric.txt"]:
        raise RubricBundleError("rendered-rubric hash mismatch")
    if hashes["input_sha256"] != task_entry["input_sha256"]:
        raise RubricBundleError("root input hash mismatch")
    if hashes["snapshot_sha256"] != task_entry["snapshot_sha256"]:
        raise RubricBundleError("root snapshot hash mismatch")
    _validate_snapshot_attestation(task_id, task_manifest, task_dir)

    rubric_json_path = task_dir / "rubric.json"
    rubric_sha256 = _hash(task_manifest["rubric_sha256"], "rubric sha256")
    rubric_id = _hash(task_manifest["rubric_id"], "rubric ID")
    if rubric_sha256 != artifacts["rubric.json"] or rubric_id != rubric_sha256:
        raise RubricBundleError("rubric ID or hash mismatch")
    if task_entry["rubric_sha256"] != rubric_sha256 or task_entry["rubric_id"] != rubric_id:
        raise RubricBundleError("root rubric ID or hash mismatch")
    try:
        rubric_text = rubric_json_path.read_text(encoding="utf-8")
        rubric = parse_task_process_rubric(rubric_text)
    except (OSError, UnicodeError, ValueError, json.JSONDecodeError) as exc:
        raise RubricBundleError(f"invalid structured rubric: {exc}") from exc
    if rubric.task_id != task_id:
        raise RubricBundleError("structured rubric task ID mismatch")
    if rubric_text != canonical_json(asdict(rubric)) + "\n":
        raise RubricBundleError("structured rubric is not canonical JSON")
    rendered_path = task_dir / "process_rubric.txt"
    try:
        rendered_text = rendered_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
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
        rendered_path=rendered_path,
        task_manifest_path=task_manifest_path,
    )
