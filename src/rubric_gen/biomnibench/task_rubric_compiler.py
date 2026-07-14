"""Offline compilation of sealed task-specific process-rubric bundles."""

from __future__ import annotations

import argparse
import fcntl
import math
import os
import shutil
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from rubric_gen.biomnibench.common import resolve_project_path
from rubric_gen.biomnibench.gemini_client import (
    DEFAULT_GEMINI_API_KEY_ENV,
    DEFAULT_GEMINI_MODEL,
    GeminiClient,
)
from rubric_gen.biomnibench.rubric_bundles import (
    GENERATION_CODE_KEYS as _GENERATION_CODE_KEYS,
    SHA256_PATTERN as _SHA256,
    TASK_RUBRIC_BUNDLE_SCHEMA_VERSION,
    TASK_RUBRIC_COMPILER_CONFIG_SCHEMA_VERSION,
    TASK_RUBRIC_PROMPT_VERSION,
    TASK_RUBRIC_PROVIDER,
    TASK_RUBRIC_RESPONSE_METADATA_SCHEMA_VERSION,
    TASK_RUBRIC_REWRITER_PROVENANCE_SCHEMA_VERSION,
    ResolvedRubricBundle as ResolvedRubricBundle,
    RubricBundleError,
    compilation_payload as _compilation_payload,
    is_safe_task_id as _is_safe_task_id,
    read_bundle_json_object as _read_json_object,
    resolve_rubric_bundle,
)
from rubric_gen.biomnibench.task_rubric_prompts import (
    TaskRubricRequest,
    build_task_rubric_prompt,
)
from rubric_gen.biomnibench.task_rubrics import (
    TaskProcessRubric,
    TaskSnapshot,
    build_task_snapshot,
    canonical_json,
    parse_task_process_rubric,
    render_task_process_rubric,
    sha256_text,
    validate_rendered_task_process_rubric,
    validate_task_process_rubric,
)


@dataclass(frozen=True)
class TaskRubricCompilerConfig:
    tasks_dir: Path
    task_ids: tuple[str, ...]
    output_dir: Path
    model: str = DEFAULT_GEMINI_MODEL
    api_key_env: str = DEFAULT_GEMINI_API_KEY_ENV
    max_retries: int = 2
    max_concurrency: int = 1
    resume: bool = False
    temperature: float = 0.2
    seed: int = 0

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
        if type(self.seed) is not int:
            raise ValueError("seed must be an integer")
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
            model=getattr(args, "model", DEFAULT_GEMINI_MODEL),
            api_key_env=getattr(args, "api_key_env", DEFAULT_GEMINI_API_KEY_ENV),
            max_retries=max(0, getattr(args, "max_retries", 2)),
            max_concurrency=max(1, getattr(args, "max_concurrency", 1)),
            resume=getattr(args, "resume", False),
            seed=getattr(args, "seed", 0),
        )


@dataclass(frozen=True)
class TaskRubricRewriterProvenance:
    schema_version: int
    provider: str
    model: str
    implementation_id: str
    implementation_sha256: str

    def __post_init__(self) -> None:
        if (
            type(self.schema_version) is not int
            or self.schema_version != TASK_RUBRIC_REWRITER_PROVENANCE_SCHEMA_VERSION
        ):
            raise ValueError("unsupported rewriter provenance schema version")
        for field_name in ("provider", "model", "implementation_id"):
            value = getattr(self, field_name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"rewriter provenance {field_name} must be non-empty")
        if (
            type(self.implementation_sha256) is not str
            or _SHA256.fullmatch(self.implementation_sha256) is None
        ):
            raise ValueError(
                "rewriter provenance implementation_sha256 must be a lowercase SHA-256 digest"
            )


@dataclass(frozen=True)
class TaskRubricRewriteResult:
    """Exact rewrite text plus optional provider response identity."""

    text: str
    served_model_version: str | None
    response_id: str | None

    def __post_init__(self) -> None:
        if type(self.text) is not str:
            raise ValueError("text must be a string")
        for field_name in ("served_model_version", "response_id"):
            value = getattr(self, field_name)
            if value is not None and (type(value) is not str or not value.strip()):
                raise ValueError(f"{field_name} must be null or a non-empty string")


class TaskRubricRewriter(Protocol):
    def rewrite(
        self,
        request: TaskRubricRequest,
    ) -> str | TaskRubricRewriteResult: ...


def _normalize_rewrite_result(
    value: str | TaskRubricRewriteResult,
) -> TaskRubricRewriteResult:
    if type(value) is str:
        return TaskRubricRewriteResult(
            text=value,
            served_model_version=None,
            response_id=None,
        )
    if type(value) is not TaskRubricRewriteResult:
        raise TypeError("rewriter response must be a string or TaskRubricRewriteResult")
    return value


class _ConfiguredGeminiClient(GeminiClient):
    def __init__(
        self,
        *,
        temperature: float,
        seed: int,
        **kwargs: object,
    ) -> None:
        super().__init__(**kwargs)  # type: ignore[arg-type]
        if type(seed) is not int:
            raise ValueError("seed must be an integer")
        self.temperature = temperature
        self.seed = seed

    def request_body(self, prompt: str) -> dict[str, object]:
        body = super().request_body(prompt)
        body["generationConfig"] = {
            "seed": self.seed,
            "temperature": self.temperature,
        }
        return body


class GeminiTaskRubricRewriter:
    """Gemini adapter for the runtime-blind canonical rubric request."""

    def __init__(
        self,
        *,
        model: str = DEFAULT_GEMINI_MODEL,
        api_key_env: str = DEFAULT_GEMINI_API_KEY_ENV,
        temperature: float = 0.2,
        seed: int = 0,
    ) -> None:
        self.client = _ConfiguredGeminiClient(
            model=model,
            api_key_env=api_key_env,
            temperature=temperature,
            seed=seed,
        )

    def rewrite(self, request: TaskRubricRequest) -> TaskRubricRewriteResult:
        response = self.client.generate_content_response(self.build_prompt(request))
        return TaskRubricRewriteResult(
            text=response.text,
            served_model_version=response.model_version,
            response_id=response.response_id,
        )

    def build_prompt(self, request: TaskRubricRequest) -> str:
        return build_task_rubric_prompt(request)


@dataclass(frozen=True)
class _CompiledTask:
    task_id: str
    snapshot: TaskSnapshot
    task_dir: Path
    rubric: TaskProcessRubric
    raw_response: str
    rubric_sha256: str
    rendered_sha256: str
    response_metadata_sha256: str
    artifact_hashes: dict[str, str]
    input_sha256: str
    prompt_sha256: str
    generated_at: str


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


def _config_payload(
    config: TaskRubricCompilerConfig,
    rewriter_provenance_sha256: str,
) -> dict[str, object]:
    return {
        "api_key_env": config.api_key_env,
        "bundle_schema_version": TASK_RUBRIC_BUNDLE_SCHEMA_VERSION,
        "max_concurrency": config.max_concurrency,
        "max_retries": config.max_retries,
        "model": config.model,
        "prompt_version": TASK_RUBRIC_PROMPT_VERSION,
        "rewriter_provenance_sha256": rewriter_provenance_sha256,
        "schema_version": TASK_RUBRIC_COMPILER_CONFIG_SCHEMA_VERSION,
        "seed": config.seed,
        "task_ids": list(config.task_ids),
        "tasks_dir": str(config.tasks_dir.resolve()),
        "temperature": config.temperature,
    }


def _response_metadata_payload(
    result: TaskRubricRewriteResult,
    raw_response_sha256: str,
) -> dict[str, object]:
    return {
        "raw_response_sha256": raw_response_sha256,
        "response_id": result.response_id,
        "schema_version": TASK_RUBRIC_RESPONSE_METADATA_SCHEMA_VERSION,
        "served_model_version": result.served_model_version,
    }


def _generation_code_sha256s() -> dict[str, str]:
    module_dir = Path(__file__).parent
    return {
        module_name: _sha256_file(module_dir / module_name)
        for module_name in sorted(_GENERATION_CODE_KEYS)
    }


def _default_rewriter_provenance(model: str) -> TaskRubricRewriterProvenance:
    module_dir = Path(__file__).parent
    implementation_hashes = {
        module_name: _sha256_file(module_dir / module_name)
        for module_name in (
            "gemini_client.py",
            "task_rubric_compiler.py",
            "task_rubric_prompts.py",
        )
    }
    return TaskRubricRewriterProvenance(
        schema_version=TASK_RUBRIC_REWRITER_PROVENANCE_SCHEMA_VERSION,
        provider=TASK_RUBRIC_PROVIDER,
        model=model,
        implementation_id=(
            "rubric_gen.biomnibench.task_rubric_compiler.GeminiTaskRubricRewriter"
        ),
        implementation_sha256=sha256_text(canonical_json(implementation_hashes)),
    )


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
    rewriter_provenance_sha256: str,
    results: dict[str, _CompiledTask],
) -> dict[str, object]:
    return {
        "compilation_sha256": compilation_sha256,
        "generation_code_sha256": generation_code_sha256,
        "rewriter_provenance_sha256": rewriter_provenance_sha256,
        "schema_version": TASK_RUBRIC_BUNDLE_SCHEMA_VERSION,
        "tasks": {
            task_id: {
                "input_sha256": result.input_sha256,
                "response_metadata_sha256": result.response_metadata_sha256,
                "rubric_id": result.rubric_sha256,
                "snapshot_sha256": result.snapshot.snapshot_sha256,
            }
            for task_id, result in sorted(results.items())
        },
    }


def _incomplete_rubric_set_identity(
    compilation_sha256: str,
    generation_code_sha256: str,
    rewriter_provenance_sha256: str,
    results: dict[str, _CompiledTask],
    errors: dict[str, str],
) -> dict[str, object]:
    identity = _rubric_set_identity(
        compilation_sha256,
        generation_code_sha256,
        rewriter_provenance_sha256,
        results,
    )
    identity["failures"] = {task_id: errors[task_id] for task_id in sorted(errors)}
    identity["status"] = "incomplete"
    return identity


class TaskProcessRubricCompiler:
    """Compile immutable task snapshots into one sealed external rubric set."""

    def __init__(
        self,
        config: TaskRubricCompilerConfig,
        *,
        rewriter: TaskRubricRewriter | None = None,
        rewriter_provenance: TaskRubricRewriterProvenance | None = None,
    ) -> None:
        self._config = config
        if rewriter is None:
            if rewriter_provenance is not None:
                raise ValueError(
                    "rewriter_provenance cannot override default Gemini provenance"
                )
            self._rewriter = GeminiTaskRubricRewriter(
                model=config.model,
                api_key_env=config.api_key_env,
                temperature=config.temperature,
                seed=config.seed,
            )
            self._rewriter_provenance = _default_rewriter_provenance(config.model)
        else:
            if rewriter_provenance is None:
                raise ValueError(
                    "injected rewriter requires explicit rewriter provenance"
                )
            if type(rewriter_provenance) is not TaskRubricRewriterProvenance:
                raise ValueError(
                    "rewriter_provenance must be TaskRubricRewriterProvenance"
                )
            self._rewriter = rewriter
            self._rewriter_provenance = rewriter_provenance
        if self._rewriter_provenance.model != config.model:
            raise ValueError(
                "rewriter provenance model must match compiler config model"
            )
        self.last_errors: tuple[str, ...] = ()

    @property
    def config(self) -> TaskRubricCompilerConfig:
        return self._config

    @property
    def rewriter(self) -> TaskRubricRewriter:
        return self._rewriter

    @property
    def rewriter_provenance(self) -> TaskRubricRewriterProvenance:
        return self._rewriter_provenance

    def run(self) -> int:
        if self.rewriter_provenance.model != self.config.model:
            self.last_errors = (
                "configuration error: rewriter provenance model must match "
                "compiler config model",
            )
            return 1
        try:
            snapshots = tuple(
                build_task_snapshot(self.config.tasks_dir / task_id)
                for task_id in self.config.task_ids
            )
        except (OSError, ValueError) as exc:
            self.last_errors = (f"input error: {exc}",)
            return 1

        rewriter_provenance = asdict(self.rewriter_provenance)
        rewriter_provenance_sha256 = sha256_text(canonical_json(rewriter_provenance))
        compiler_config = _config_payload(
            self.config,
            rewriter_provenance_sha256,
        )
        config_sha256 = sha256_text(canonical_json(compiler_config))
        generation_code_sha256s = _generation_code_sha256s()
        generation_code_sha256 = sha256_text(canonical_json(generation_code_sha256s))
        compilation_sha256 = sha256_text(
            canonical_json(
                _compilation_payload(
                    config_sha256,
                    generation_code_sha256,
                    rewriter_provenance_sha256,
                    _snapshot_compilation_tasks(snapshots),
                )
            )
        )
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
        temporary = Path(
            tempfile.mkdtemp(
                prefix=f".{output_dir.name}.tmp-",
                dir=output_dir.parent,
            )
        )
        try:
            results, errors = self._compile_all(temporary, snapshots)
            if errors:
                self.last_errors = tuple(errors[task_id] for task_id in sorted(errors))
                _write_json(
                    temporary / "failure.json",
                    {
                        "errors": errors,
                        "schema_version": TASK_RUBRIC_BUNDLE_SCHEMA_VERSION,
                        "status": "failed",
                    },
                )
                if results:
                    rubric_set_id = sha256_text(
                        canonical_json(
                            _incomplete_rubric_set_identity(
                                compilation_sha256,
                                generation_code_sha256,
                                rewriter_provenance_sha256,
                                results,
                                errors,
                            )
                        )
                    )
                    task_entries = self._write_task_manifests(
                        rubric_set_id,
                        results,
                        config_sha256,
                        generation_code_sha256s,
                        generation_code_sha256,
                        rewriter_provenance_sha256,
                    )
                    _write_json(
                        temporary / "incomplete-manifest.json",
                        {
                            "compilation_sha256": compilation_sha256,
                            "compiler_config": compiler_config,
                            "compiler_config_sha256": config_sha256,
                            "failures": {
                                task_id: errors[task_id] for task_id in sorted(errors)
                            },
                            "generated_at": _utc_now(),
                            "generation_code_sha256": generation_code_sha256,
                            "generation_code_sha256s": generation_code_sha256s,
                            "rewriter_provenance": rewriter_provenance,
                            "rewriter_provenance_sha256": rewriter_provenance_sha256,
                            "rubric_set_id": rubric_set_id,
                            "schema_version": TASK_RUBRIC_BUNDLE_SCHEMA_VERSION,
                            "status": "incomplete",
                            "successful_task_ids": sorted(results),
                            "tasks": task_entries,
                        },
                    )
                self._publish(temporary, output_dir)
                return 1

            rubric_set_id = sha256_text(
                canonical_json(
                    _rubric_set_identity(
                        compilation_sha256,
                        generation_code_sha256,
                        rewriter_provenance_sha256,
                        results,
                    )
                )
            )
            task_entries = self._write_task_manifests(
                rubric_set_id,
                results,
                config_sha256,
                generation_code_sha256s,
                generation_code_sha256,
                rewriter_provenance_sha256,
            )
            root_manifest = {
                "compilation_sha256": compilation_sha256,
                "compiler_config": compiler_config,
                "compiler_config_sha256": config_sha256,
                "generated_at": _utc_now(),
                "generation_code_sha256": generation_code_sha256,
                "generation_code_sha256s": generation_code_sha256s,
                "prompt_version": TASK_RUBRIC_PROMPT_VERSION,
                "rewriter_provenance": rewriter_provenance,
                "rewriter_provenance_sha256": rewriter_provenance_sha256,
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
            rewrite_result = TaskRubricRewriteResult(
                text="",
                served_model_version=None,
                response_id=None,
            )
            errors: tuple[str, ...]
            rubric: TaskProcessRubric | None = None
            rendered: str | None = None
            try:
                rewrite_result = _normalize_rewrite_result(
                    self.rewriter.rewrite(request)
                )
                response = rewrite_result.text
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
            response_metadata = _response_metadata_payload(
                rewrite_result,
                sha256_text(response),
            )
            _write_json(
                attempt_dir / "response_metadata.json",
                response_metadata,
            )
            _write_json(attempt_dir / "errors.json", list(errors))
            if rubric is not None and rendered is not None and not errors:
                structured = canonical_json(asdict(rubric)) + "\n"
                (task_dir / "raw_response.txt").write_text(response, encoding="utf-8")
                _write_json(
                    task_dir / "response_metadata.json",
                    response_metadata,
                )
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
                    response_metadata_sha256=_sha256_file(
                        task_dir / "response_metadata.json"
                    ),
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
        rewriter_provenance_sha256: str,
    ) -> dict[str, object]:
        model_sha256 = sha256_text(self.config.model)
        seed_sha256 = sha256_text(canonical_json(self.config.seed))
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
                "provider": self.rewriter_provenance.provider,
                "rewriter_provenance": asdict(self.rewriter_provenance),
                "rewriter_provenance_sha256": rewriter_provenance_sha256,
                "schema_version": TASK_RUBRIC_BUNDLE_SCHEMA_VERSION,
                "seed": self.config.seed,
                "temperature": self.config.temperature,
            },
            "generated_at": result.generated_at,
            "hashes": {
                "input_sha256": result.input_sha256,
                "model_sha256": model_sha256,
                "prompt_sha256": result.prompt_sha256,
                "raw_response_sha256": raw_sha256,
                "rendered_rubric_sha256": result.rendered_sha256,
                "response_metadata_sha256": result.response_metadata_sha256,
                "seed_sha256": seed_sha256,
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
        rewriter_provenance_sha256: str,
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
                    rewriter_provenance_sha256,
                ),
            )
            task_entries[task_id] = {
                "input_sha256": result.input_sha256,
                "response_metadata_sha256": result.response_metadata_sha256,
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
            root = _read_json_object(
                self.config.output_dir / "manifest.json", "root manifest"
            )
            if root.get("compiler_config_sha256") != config_sha256:
                return False
            if root.get("compilation_sha256") != compilation_sha256:
                return False
            tasks = root.get("tasks")
            if type(tasks) is not dict or set(tasks) != {
                snapshot.task_id for snapshot in snapshots
            }:
                return False
            for snapshot in snapshots:
                resolved = resolve_rubric_bundle(
                    self.config.output_dir, snapshot.task_id
                )
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
