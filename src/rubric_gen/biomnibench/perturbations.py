"""LLM-driven perturbations for saved BiomniBench agent trajectories."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any, Protocol

from rubric_gen.biomnibench.common import PROGRESS_BAR_FORMAT
from rubric_gen.biomnibench.common import resolve_project_path

try:
    from tqdm.auto import tqdm
except ImportError:  # pragma: no cover - tqdm is an optional runtime nicety.
    tqdm = None


DEFAULT_PERTURBER_MODEL = "gemini-3.5-flash"
DEFAULT_PERTURBATION_LEVELS = ("C", "L0", "L1", "L2", "L3", "L4", "L5")
DEFAULT_PERTURBATION_MAX_CONCURRENCY = 30
DEFAULT_GEMINI_API_KEY_ENV = "GEMINI_API_KEY"
GEMINI_GENERATE_CONTENT_BASE_URL = "https://generativelanguage.googleapis.com/v1beta"

PERTURBATION_LEVELS = {
    "C": "Exact control copy. Preserve trace, answer, and raw trajectory byte-for-byte where possible.",
    "L0": (
        "Make the process look substantially more detailed and effortful by adding generic background, "
        "verbose explanations, and irrelevant details, while adding no new concrete evidence, no new executed "
        "results, no new data-derived counts, and no real support for the final answer."
    ),
    "L1": "Make harmless cosmetic or presentation-only changes that should not change analytical quality.",
    "L2": (
        "Make the process less auditable while preserving the broad final answer: remove or obscure file "
        "inventory, data-shape checks, overlap counts, setup checks, and other traceability evidence."
    ),
    "L3": (
        "Make the analysis less methodologically rigorous while preserving final-answer plausibility: weaken "
        "evidence for model selection, statistical refinement, diagnostics, null models, and prioritization."
    ),
    "L4": (
        "Keep a polished final answer, but make the process under-supported or mildly inconsistent: remove "
        "decisive commands, reproducibility details, source grounding, and the audit trail for final claims."
    ),
    "L5": "Degrade both the process and the final answer so the task response is clearly low quality.",
}


@dataclass(frozen=True)
class GeminiGenerateContentResponse:
    """One Gemini response with the provider's serving identity intact."""

    text: str
    model_version: str
    response_id: str

    def __post_init__(self) -> None:
        for field_name in ("text", "model_version", "response_id"):
            value = getattr(self, field_name)
            if type(value) is not str or not value.strip():
                raise ValueError(f"{field_name} must be a non-empty string")


@dataclass(frozen=True)
class PerturbationRunConfig:
    base_run: Path
    out_dir: Path
    tasks: tuple[str, ...] = ()
    levels: tuple[str, ...] = DEFAULT_PERTURBATION_LEVELS
    model: str = DEFAULT_PERTURBER_MODEL
    api_key_env: str = DEFAULT_GEMINI_API_KEY_ENV
    resume: bool = False
    dry_run: bool = False
    max_input_chars: int = 120_000
    max_retries: int = 2
    max_concurrency: int = DEFAULT_PERTURBATION_MAX_CONCURRENCY

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "PerturbationRunConfig":
        return cls(
            base_run=resolve_project_path(getattr(args, "base_run")),
            out_dir=resolve_project_path(getattr(args, "out_dir")),
            tasks=parse_csv(getattr(args, "tasks", None)),
            levels=parse_csv(getattr(args, "levels", None)) or DEFAULT_PERTURBATION_LEVELS,
            model=getattr(args, "perturber_model", DEFAULT_PERTURBER_MODEL),
            api_key_env=getattr(args, "api_key_env", DEFAULT_GEMINI_API_KEY_ENV),
            resume=getattr(args, "resume", False),
            dry_run=getattr(args, "dry_run", False),
            max_input_chars=max(1_000, getattr(args, "max_input_chars", 120_000)),
            max_retries=max(0, getattr(args, "max_retries", 2)),
            max_concurrency=max(1, getattr(args, "max_concurrency", DEFAULT_PERTURBATION_MAX_CONCURRENCY)),
        )


@dataclass(frozen=True)
class SourceRun:
    task: str
    task_dir: Path
    run_dir: Path
    workspace_dir: Path
    trajectory_path: Path
    trace_path: Path
    answer_path: Path
    status_path: Path


@dataclass(frozen=True)
class PerturbationRequest:
    task: str
    level: str
    level_intent: str
    instruction_md: str
    trace_md: str
    answer_txt: str
    trajectory_stream_jsonl: str


@dataclass(frozen=True)
class PerturbationResult:
    level: str
    intent: str
    trace_md: str
    answer_txt: str
    trajectory_stream_jsonl: str
    preserved_claims: tuple[str, ...] = ()
    perturbation_notes: tuple[str, ...] = ()

    @classmethod
    def from_json(cls, text: str) -> "PerturbationResult":
        payload = json.loads(extract_json_object(text))
        required = ("level", "intent", "trace_md", "answer_txt", "trajectory_stream_jsonl")
        missing = [key for key in required if key not in payload]
        if missing:
            raise ValueError(f"Perturber response missing fields: {', '.join(missing)}")
        return cls(
            level=str(payload["level"]),
            intent=str(payload["intent"]),
            trace_md=str(payload["trace_md"]),
            answer_txt=str(payload["answer_txt"]),
            trajectory_stream_jsonl=str(payload["trajectory_stream_jsonl"]),
            preserved_claims=tuple(str(item) for item in payload.get("preserved_claims", ())),
            perturbation_notes=tuple(str(item) for item in payload.get("perturbation_notes", ())),
        )


class Perturber(Protocol):
    def perturb(self, request: PerturbationRequest) -> PerturbationResult:
        ...


class GeminiPerturber:
    def __init__(
        self,
        *,
        model: str = DEFAULT_PERTURBER_MODEL,
        api_key_env: str = DEFAULT_GEMINI_API_KEY_ENV,
        base_url: str = GEMINI_GENERATE_CONTENT_BASE_URL,
        timeout_seconds: int = 600,
    ) -> None:
        self.model = model
        self.api_key_env = api_key_env
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def perturb(self, request: PerturbationRequest) -> PerturbationResult:
        trace_md = self.generate_content(self.build_artifact_prompt(request, "trace_md")).strip()
        answer_txt = self.generate_content(self.build_artifact_prompt(request, "answer_txt")).strip()
        trajectory_stream_jsonl = ensure_trailing_newline(
            self.generate_content(self.build_artifact_prompt(request, "trajectory_stream_jsonl")).strip()
        )
        return PerturbationResult(
            level=request.level,
            intent=request.level_intent,
            trace_md=trace_md,
            answer_txt=answer_txt,
            trajectory_stream_jsonl=trajectory_stream_jsonl,
            preserved_claims=(
                ("broad final conclusion preserved" if request.level != "L5" else "final answer intentionally degraded"),
            ),
            perturbation_notes=(
                f"Generated trace_md, answer_txt, and trajectory_stream_jsonl separately for {request.level}.",
            ),
        )

    def generate_content(self, prompt: str) -> str:
        return self.response_text(self._generate_content_payload(prompt))

    def generate_content_response(
        self,
        prompt: str,
    ) -> GeminiGenerateContentResponse:
        """Generate text while retaining the provider's response identity."""

        return self.response_with_metadata(
            self._generate_content_payload(prompt)
        )

    def _generate_content_payload(self, prompt: str) -> dict[str, Any]:
        api_key = self.api_key()
        request = urllib.request.Request(
            self.generate_content_url(api_key),
            data=json.dumps(self.request_body(prompt)).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout_seconds) as response:
                response_payload = json.loads(response.read().decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise RuntimeError(f"Gemini API request failed with HTTP {exc.code}: {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"Gemini API request failed: {exc}") from exc
        if not isinstance(response_payload, dict):
            raise RuntimeError("Gemini API response must be a JSON object")
        return response_payload

    def request_body(self, prompt: str) -> dict[str, Any]:
        return {
            "contents": [
                {
                    "parts": [
                        {"text": prompt},
                    ],
                }
            ],
            "generationConfig": {
                "temperature": 0.2,
            },
        }

    def api_key(self) -> str:
        key = os.environ.get(self.api_key_env)
        if key:
            return key
        if self.api_key_env == DEFAULT_GEMINI_API_KEY_ENV:
            fallback = os.environ.get("GOOGLE_API_KEY")
            if fallback:
                return fallback
        raise RuntimeError(
            f"Missing Gemini API key. Set {self.api_key_env}"
            + (" or GOOGLE_API_KEY." if self.api_key_env == DEFAULT_GEMINI_API_KEY_ENV else ".")
        )

    def generate_content_url(self, api_key: str) -> str:
        model_name = self.model if self.model.startswith("models/") else f"models/{self.model}"
        quoted_model = urllib.parse.quote(model_name, safe="/")
        quoted_key = urllib.parse.quote(api_key, safe="")
        return f"{self.base_url}/{quoted_model}:generateContent?key={quoted_key}"

    def response_text(self, payload: dict[str, Any]) -> str:
        try:
            parts = payload["candidates"][0]["content"]["parts"]
        except (KeyError, IndexError, TypeError) as exc:
            raise RuntimeError(f"Gemini API response did not contain candidate text: {payload}") from exc
        text = "".join(str(part.get("text", "")) for part in parts if isinstance(part, dict))
        if not text.strip():
            raise RuntimeError(f"Gemini API response contained empty text: {payload}")
        return text

    def response_with_metadata(
        self,
        payload: dict[str, Any],
    ) -> GeminiGenerateContentResponse:
        text = self.response_text(payload)
        metadata: dict[str, str] = {}
        for json_name, field_name in (
            ("modelVersion", "model_version"),
            ("responseId", "response_id"),
        ):
            value = payload.get(json_name)
            if type(value) is not str or not value.strip():
                error = RuntimeError(
                    f"Gemini API response {json_name} must be a non-empty string"
                )
                error.raw_response = text  # type: ignore[attr-defined]
                raise error
            metadata[field_name] = value
        return GeminiGenerateContentResponse(text=text, **metadata)

    def build_prompt(self, request: PerturbationRequest) -> str:
        return self.build_artifact_prompt(request, "all")

    def build_artifact_prompt(self, request: PerturbationRequest, artifact: str) -> str:
        artifact_instructions = {
            "trace_md": (
                "Return only the complete perturbed trace.md content as Markdown/plain text. "
                "Do not wrap it in JSON, XML, code fences, or commentary."
            ),
            "answer_txt": (
                "Return only the complete perturbed answer.txt content as plain text. "
                "Do not wrap it in JSON, XML, code fences, or commentary."
            ),
            "trajectory_stream_jsonl": (
                "Return only the complete perturbed trajectory.stream.jsonl content. "
                "Every event line that starts with { must be valid single-line JSON. "
                "Do not wrap it in Markdown fences or commentary."
            ),
            "all": (
                "Return the perturbed artifacts. This compatibility prompt is only used for prompt inspection."
            ),
        }
        return f"""You are perturbing a saved BiomniBench agent run to create controlled quality variants.

Use only the task instruction and original artifacts below. Do not use any grading rubric, rubric criterion, score,
or hidden evaluator target. Create a generic quality perturbation for the requested level.

Artifact to generate: {artifact}
Output instruction: {artifact_instructions[artifact]}

Level: {request.level}
Level intent: {request.level_intent}

Constraints:
- Preserve the same task identity and local-file setting.
- For L1-L4, preserve the broad final conclusion and final-answer plausibility.
- For L0, make the process more verbose and detailed-looking without adding new concrete evidence.
- For L5, degrade both the process and final answer.
- Keep trace_md, answer_txt, and trajectory_stream_jsonl non-empty.
- Do not mention rubrics, judging, scores, or evaluator criteria.
- trajectory_stream_jsonl should be newline-delimited event text. JSON event lines must remain valid JSON.

<instruction.md>
{request.instruction_md}
</instruction.md>

<original_trace.md>
{request.trace_md}
</original_trace.md>

<original_answer.txt>
{request.answer_txt}
</original_answer.txt>

<original_trajectory.stream.jsonl>
{request.trajectory_stream_jsonl}
</original_trajectory.stream.jsonl>
"""


class BiomniBenchPerturbationRunner:
    def __init__(
        self,
        config: PerturbationRunConfig,
        *,
        perturber: Perturber | None = None,
    ) -> None:
        self.config = config
        self.perturber = perturber or GeminiPerturber(
            model=config.model,
            api_key_env=config.api_key_env,
        )

    def run(self) -> int:
        self.validate_levels()
        sources = self.discover_sources()
        if self.config.dry_run:
            self.print_plan(sources)
            return 0

        if self.config.out_dir.exists() and not self.config.resume:
            shutil.rmtree(self.config.out_dir)
        self.config.out_dir.mkdir(parents=True, exist_ok=True)

        records = self.write_all_levels(sources)

        manifest = {
            "base_run": str(self.config.base_run),
            "out_dir": str(self.config.out_dir),
            "model": self.config.model,
            "api_key_env": self.config.api_key_env,
            "resume": self.config.resume,
            "max_concurrency": self.config.max_concurrency,
            "levels": list(self.config.levels),
            "tasks": [source.task for source in sources],
            "records": records,
        }
        (self.config.out_dir / "perturbation_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        print(f"Wrote perturbation experiment: {self.config.out_dir}")
        return 0

    def write_all_levels(self, sources: list[SourceRun]) -> list[dict[str, Any]]:
        jobs = [
            (level, self.config.out_dir / level, source)
            for level in self.config.levels
            for source in sources
        ]
        records: list[dict[str, Any] | None] = [None] * len(jobs)
        with PerturbationProgress(total=len(jobs)) as progress:
            if self.config.max_concurrency == 1 or len(jobs) <= 1:
                for index, (level, level_dir, source) in enumerate(jobs):
                    records[index] = self.write_level(source, level, level_dir)
                    progress.record(source.task, level, str(records[index].get("status", "written")))
                    progress.update()
            else:
                with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as executor:
                    futures = {
                        executor.submit(self.write_level, source, level, level_dir): index
                        for index, (level, level_dir, source) in enumerate(jobs)
                    }
                    for future in as_completed(futures):
                        index = futures[future]
                        level, _level_dir, source = jobs[index]
                        records[index] = future.result()
                        progress.record(source.task, level, str(records[index].get("status", "written")))
                        progress.update()
        return [record for record in records if record is not None]

    def validate_levels(self) -> None:
        unknown = [level for level in self.config.levels if level not in PERTURBATION_LEVELS]
        if unknown:
            allowed = ", ".join(PERTURBATION_LEVELS)
            raise SystemExit(f"Unknown perturbation level(s): {', '.join(unknown)}. Allowed: {allowed}")

    def discover_sources(self) -> list[SourceRun]:
        base = self.config.base_run
        if (base / "tasks").is_dir() and (base / "workspaces").is_dir():
            sources = [self.source_from_batch_task(path, base) for path in sorted((base / "tasks").iterdir()) if path.is_dir()]
        else:
            sources = [self.source_from_single_run(base)]
        if self.config.tasks:
            wanted = set(self.config.tasks)
            sources = [source for source in sources if source.task in wanted]
        if not sources:
            raise SystemExit("No matching runs found to perturb.")
        return sources

    def source_from_batch_task(self, run_dir: Path, batch_dir: Path) -> SourceRun:
        status = read_json(run_dir / "status.json")
        task = str(status.get("task") or run_dir.name)
        workspace = Path(status.get("workspace_dir") or batch_dir / "workspaces" / task)
        task_dir = Path(status.get("task_dir") or task)
        return self.source_from_paths(task, task_dir, run_dir, workspace)

    def source_from_single_run(self, run_dir: Path) -> SourceRun:
        status = read_json(run_dir / "status.json")
        task = str(status.get("task") or infer_task_name(run_dir))
        workspace = Path(status.get("workspace_dir") or run_dir / "workspace")
        task_dir = Path(status.get("task_dir") or task)
        return self.source_from_paths(task, task_dir, run_dir, workspace)

    def source_from_paths(self, task: str, task_dir: Path, run_dir: Path, workspace: Path) -> SourceRun:
        source = SourceRun(
            task=task,
            task_dir=task_dir,
            run_dir=run_dir,
            workspace_dir=workspace,
            trajectory_path=run_dir / "trajectory.stream.jsonl",
            trace_path=workspace / "trace.md",
            answer_path=workspace / "answer.txt",
            status_path=run_dir / "status.json",
        )
        for path in (source.trajectory_path, source.trace_path, source.answer_path):
            if not path.is_file():
                raise SystemExit(f"Missing required run artifact: {path}")
        return source

    def write_level(self, source: SourceRun, level: str, level_dir: Path) -> dict[str, Any]:
        output_run = level_dir / "tasks" / source.task
        output_workspace = level_dir / "workspaces" / source.task
        if self.config.resume and self.output_complete(output_run, output_workspace):
            return {
                "task": source.task,
                "level": level,
                "status": "resumed",
                "source_run_dir": str(source.run_dir),
                "output_run_dir": str(output_run),
                "output_workspace_dir": str(output_workspace),
                "intent": "reused existing perturbation output",
                "preserved_claims": [],
                "perturbation_notes": ["existing complete output preserved by --resume"],
            }
        output_run.mkdir(parents=True, exist_ok=True)
        output_workspace.mkdir(parents=True, exist_ok=True)

        if level == "C":
            trace = source.trace_path.read_text(errors="replace")
            answer = source.answer_path.read_text(errors="replace")
            trajectory = source.trajectory_path.read_text(errors="replace")
            result = PerturbationResult(
                level="C",
                intent=PERTURBATION_LEVELS["C"],
                trace_md=trace,
                answer_txt=answer,
                trajectory_stream_jsonl=trajectory,
                preserved_claims=("exact control copy",),
                perturbation_notes=("copied original artifacts without LLM perturbation",),
            )
        else:
            result = self.call_with_retries(source, level)

        validate_result(result)
        (output_workspace / "trace.md").write_text(result.trace_md)
        (output_workspace / "answer.txt").write_text(result.answer_txt)
        (output_run / "trajectory.stream.jsonl").write_text(ensure_trailing_newline(result.trajectory_stream_jsonl))
        (output_run / "status.json").write_text(
            json.dumps(self.output_status(source, level, output_workspace), indent=2) + "\n"
        )
        complete = self.completion_record(source, level, output_run, output_workspace)
        (output_run / "perturbation_complete.json").write_text(json.dumps(complete, indent=2) + "\n")
        return {
            "task": source.task,
            "level": level,
            "status": "written",
            "source_run_dir": str(source.run_dir),
            "output_run_dir": str(output_run),
            "output_workspace_dir": str(output_workspace),
            "intent": result.intent,
            "preserved_claims": list(result.preserved_claims),
            "perturbation_notes": list(result.perturbation_notes),
        }

    def completion_record(
        self,
        source: SourceRun,
        level: str,
        output_run: Path,
        output_workspace: Path,
    ) -> dict[str, Any]:
        return {
            "status": "complete",
            "task": source.task,
            "level": level,
            "source_run_dir": str(source.run_dir),
            "output_run_dir": str(output_run),
            "output_workspace_dir": str(output_workspace),
        }

    def output_complete(self, output_run: Path, output_workspace: Path) -> bool:
        marker = output_run / "perturbation_complete.json"
        if not marker.is_file():
            return False
        data = read_json(marker)
        if data.get("status") != "complete":
            return False
        paths = (
            output_run / "trajectory.stream.jsonl",
            output_run / "status.json",
            output_workspace / "trace.md",
            output_workspace / "answer.txt",
        )
        if not all(path.is_file() and path.read_text(errors="replace").strip() for path in paths):
            return False
        try:
            validate_trajectory_text((output_run / "trajectory.stream.jsonl").read_text(errors="replace"))
        except ValueError:
            return False
        return True


    def call_with_retries(self, source: SourceRun, level: str) -> PerturbationResult:
        errors: list[str] = []
        for _attempt in range(self.config.max_retries + 1):
            request = self.build_request(source, level, errors)
            try:
                result = normalize_perturbation_result(self.perturber.perturb(request))
                validate_result(result)
                if result.level != level:
                    raise ValueError(f"Perturber returned level {result.level!r}, expected {level!r}")
                return result
            except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
                errors.append(str(exc))
        raise SystemExit(f"Perturber failed for {source.task} {level}: {'; '.join(errors)}")

    def build_request(self, source: SourceRun, level: str, errors: list[str]) -> PerturbationRequest:
        instruction = read_text(source.task_dir / "instruction.md")
        if errors:
            instruction += "\n\nPrevious invalid perturbation attempt(s):\n" + "\n".join(f"- {error}" for error in errors)
        return PerturbationRequest(
            task=source.task,
            level=level,
            level_intent=PERTURBATION_LEVELS[level],
            instruction_md=truncate(instruction, self.config.max_input_chars // 5),
            trace_md=truncate(read_text(source.trace_path), self.config.max_input_chars // 3),
            answer_txt=truncate(read_text(source.answer_path), self.config.max_input_chars // 6),
            trajectory_stream_jsonl=truncate(read_text(source.trajectory_path), self.config.max_input_chars // 3),
        )

    def output_status(self, source: SourceRun, level: str, output_workspace: Path) -> dict[str, Any]:
        status = read_json(source.status_path)
        status.update(
            {
                "task": source.task,
                "task_dir": str(source.task_dir),
                "workspace_dir": str(output_workspace),
                "perturbation_level": level,
                "perturbation_model": self.config.model,
                "source_run_dir": str(source.run_dir),
                "source_workspace_dir": str(source.workspace_dir),
            }
        )
        return status

    def print_plan(self, sources: list[SourceRun]) -> None:
        print(f"Would perturb {len(sources)} task(s) from {self.config.base_run}")
        print(f"Output: {self.config.out_dir}")
        print(f"Model: {self.config.model}")
        print(f"API key env: {self.config.api_key_env}")
        print(f"Resume: {self.config.resume}")
        print(f"Max concurrency: {self.config.max_concurrency}")
        print(f"Levels: {', '.join(self.config.levels)}")
        for source in sources:
            print(f"- {source.task}: {source.run_dir}")


class PerturbationProgress:
    def __init__(self, *, total: int) -> None:
        self.total = total
        self._bar: Any = None

    def __enter__(self) -> "PerturbationProgress":
        if tqdm is not None:
            self._bar = tqdm(
                total=self.total,
                desc="perturb tasks",
                unit="job",
                dynamic_ncols=True,
                bar_format=PROGRESS_BAR_FORMAT,
                file=sys.stderr,
            )
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._bar is not None:
            self._bar.close()

    def record(self, task: str, level: str, event: str) -> None:
        if self._bar is not None:
            self._bar.set_postfix_str(f"{level}/{task}: {event}")

    def update(self) -> None:
        if self._bar is not None:
            self._bar.update(1)


def parse_csv(value: str | None) -> tuple[str, ...]:
    if not value:
        return ()
    return tuple(item.strip() for item in value.split(",") if item.strip())


def read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def read_text(path: Path) -> str:
    if not path.is_file():
        return ""
    return path.read_text(errors="replace")


def infer_task_name(run_dir: Path) -> str:
    parts = run_dir.name.split("-")
    for index in range(len(parts) - 2):
        if parts[index] == "da" and parts[index + 1].isdigit() and parts[index + 2].isdigit():
            return "-".join(parts[index : index + 3])
        if parts[index].startswith("da") and parts[index + 1].isdigit() and parts[index + 2].isdigit():
            return "-".join(parts[index : index + 3])
    if run_dir.name.startswith("da-"):
        return run_dir.name
    raise SystemExit(f"Could not infer task name from run directory: {run_dir}")


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head
    return text[:head] + f"\n\n[... truncated to {max_chars} characters for perturbation prompt ...]\n\n" + text[-tail:]


def validate_result(result: PerturbationResult) -> None:
    for label, text in (
        ("trace_md", result.trace_md),
        ("answer_txt", result.answer_txt),
        ("trajectory_stream_jsonl", result.trajectory_stream_jsonl),
    ):
        if not text.strip():
            raise ValueError(f"Perturber returned empty {label}")
    validate_trajectory_text(result.trajectory_stream_jsonl)


def normalize_perturbation_result(result: PerturbationResult) -> PerturbationResult:
    normalized, repaired = normalize_generated_trajectory_jsonl(result.trajectory_stream_jsonl)
    if repaired == 0:
        return result
    return replace(
        result,
        trajectory_stream_jsonl=normalized,
        perturbation_notes=(
            *result.perturbation_notes,
            f"normalized {repaired} invalid generated trajectory line(s) into valid JSON wrapper events",
        ),
    )


def normalize_generated_trajectory_jsonl(text: str) -> tuple[str, int]:
    lines: list[str] = []
    repaired = 0
    for index, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped.startswith("{"):
            try:
                event = json.loads(stripped)
            except json.JSONDecodeError as exc:
                event = {
                    "type": "perturbed_invalid_json_line",
                    "line": index,
                    "content": raw,
                    "repair_error": str(exc),
                }
                repaired += 1
            lines.append(json.dumps(event, ensure_ascii=False))
            continue
        lines.append(
            json.dumps(
                {
                    "type": "perturbed_text_line",
                    "line": index,
                    "content": raw,
                },
                ensure_ascii=False,
            )
        )
        repaired += 1
    return ensure_trailing_newline("\n".join(lines)), repaired


def validate_trajectory_text(text: str) -> None:
    for index, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped or not stripped.startswith("{"):
            continue
        try:
            json.loads(stripped)
        except json.JSONDecodeError as exc:
            raise ValueError(f"Invalid JSON trajectory line {index}: {exc}") from exc


def ensure_trailing_newline(text: str) -> str:
    return text if text.endswith("\n") else text + "\n"


def extract_json_object(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        lines = stripped.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].startswith("```"):
            lines = lines[:-1]
        stripped = "\n".join(lines).strip()
    if stripped.startswith("{") and stripped.endswith("}"):
        return stripped
    start = stripped.find("{")
    end = stripped.rfind("}")
    if start == -1 or end == -1 or end <= start:
        raise ValueError("Perturber response did not contain a JSON object")
    return stripped[start : end + 1]
