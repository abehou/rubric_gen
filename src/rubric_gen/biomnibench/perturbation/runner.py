"""Orchestrate controlled perturbations of saved agent trajectories."""

from __future__ import annotations

import json
import shutil
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from pathlib import Path
from typing import Any

from rubric_gen.biomnibench.utils.progress import TerminalProgress
from rubric_gen.biomnibench.utils.text import ensure_trailing_newline

from .gemini import GeminiPerturber
from .models import (
    PERTURBATION_LEVELS,
    Perturber,
    PerturbationRequest,
    PerturbationResult,
    PerturbationRunConfig,
    SourceRun,
)


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
        (self.config.out_dir / "perturbation_manifest.json").write_text(
            json.dumps(manifest, indent=2) + "\n"
        )
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
                    progress.record(
                        source.task, level, str(records[index].get("status", "written"))
                    )
                    progress.update()
            else:
                with ThreadPoolExecutor(
                    max_workers=self.config.max_concurrency
                ) as executor:
                    futures = {
                        executor.submit(
                            self.write_level, source, level, level_dir
                        ): index
                        for index, (level, level_dir, source) in enumerate(jobs)
                    }
                    for future in as_completed(futures):
                        index = futures[future]
                        level, _level_dir, source = jobs[index]
                        records[index] = future.result()
                        progress.record(
                            source.task,
                            level,
                            str(records[index].get("status", "written")),
                        )
                        progress.update()
        return [record for record in records if record is not None]

    def validate_levels(self) -> None:
        unknown = [
            level for level in self.config.levels if level not in PERTURBATION_LEVELS
        ]
        if unknown:
            allowed = ", ".join(PERTURBATION_LEVELS)
            raise SystemExit(
                f"Unknown perturbation level(s): {', '.join(unknown)}. Allowed: {allowed}"
            )

    def discover_sources(self) -> list[SourceRun]:
        base = self.config.base_run
        if (base / "tasks").is_dir() and (base / "workspaces").is_dir():
            sources = [
                self.source_from_batch_task(path, base)
                for path in sorted((base / "tasks").iterdir())
                if path.is_dir()
            ]
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

    def source_from_paths(
        self, task: str, task_dir: Path, run_dir: Path, workspace: Path
    ) -> SourceRun:
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

    def write_level(
        self, source: SourceRun, level: str, level_dir: Path
    ) -> dict[str, Any]:
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
                "perturbation_notes": [
                    "existing complete output preserved by --resume"
                ],
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
                perturbation_notes=(
                    "copied original artifacts without LLM perturbation",
                ),
            )
        else:
            result = self.call_with_retries(source, level)

        validate_result(result)
        (output_workspace / "trace.md").write_text(result.trace_md)
        (output_workspace / "answer.txt").write_text(result.answer_txt)
        (output_run / "trajectory.stream.jsonl").write_text(
            ensure_trailing_newline(result.trajectory_stream_jsonl)
        )
        (output_run / "status.json").write_text(
            json.dumps(self.output_status(source, level, output_workspace), indent=2)
            + "\n"
        )
        complete = self.completion_record(source, level, output_run, output_workspace)
        (output_run / "perturbation_complete.json").write_text(
            json.dumps(complete, indent=2) + "\n"
        )
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
        if not all(
            path.is_file() and path.read_text(errors="replace").strip()
            for path in paths
        ):
            return False
        try:
            validate_trajectory_text(
                (output_run / "trajectory.stream.jsonl").read_text(errors="replace")
            )
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
                    raise ValueError(
                        f"Perturber returned level {result.level!r}, expected {level!r}"
                    )
                return result
            except (ValueError, RuntimeError, json.JSONDecodeError) as exc:
                errors.append(str(exc))
        raise SystemExit(
            f"Perturber failed for {source.task} {level}: {'; '.join(errors)}"
        )

    def build_request(
        self, source: SourceRun, level: str, errors: list[str]
    ) -> PerturbationRequest:
        instruction = read_text(source.task_dir / "instruction.md")
        if errors:
            instruction += (
                "\n\nPrevious invalid perturbation attempt(s):\n"
                + "\n".join(f"- {error}" for error in errors)
            )
        return PerturbationRequest(
            task=source.task,
            level=level,
            level_intent=PERTURBATION_LEVELS[level],
            instruction_md=truncate(instruction, self.config.max_input_chars // 5),
            trace_md=truncate(
                read_text(source.trace_path), self.config.max_input_chars // 3
            ),
            answer_txt=truncate(
                read_text(source.answer_path), self.config.max_input_chars // 6
            ),
            trajectory_stream_jsonl=truncate(
                read_text(source.trajectory_path), self.config.max_input_chars // 3
            ),
        )

    def output_status(
        self, source: SourceRun, level: str, output_workspace: Path
    ) -> dict[str, Any]:
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


class PerturbationProgress(TerminalProgress):
    def __init__(self, *, total: int) -> None:
        super().__init__(total=total, description="perturb tasks", unit="job")

    def record(self, task: str, level: str, event: str) -> None:
        self.set_status(f"{level}/{task}: {event}")


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
        if (
            parts[index] == "da"
            and parts[index + 1].isdigit()
            and parts[index + 2].isdigit()
        ):
            return "-".join(parts[index : index + 3])
        if (
            parts[index].startswith("da")
            and parts[index + 1].isdigit()
            and parts[index + 2].isdigit()
        ):
            return "-".join(parts[index : index + 3])
    if run_dir.name.startswith("da-"):
        return run_dir.name
    raise SystemExit(f"Could not infer task name from run directory: {run_dir}")


def truncate(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    head = max_chars // 2
    tail = max_chars - head
    return (
        text[:head]
        + f"\n\n[... truncated to {max_chars} characters for perturbation prompt ...]\n\n"
        + text[-tail:]
    )


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
    normalized, repaired = normalize_generated_trajectory_jsonl(
        result.trajectory_stream_jsonl
    )
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
