"""Agentic, solution-informed generation of unconstrained task rubrics."""

from __future__ import annotations

import argparse
import errno
import json
import os
import queue
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import TextIO

from rubric_gen.biomnibench.agent.adapters import AgentAdapterRegistry
from rubric_gen.biomnibench.agent.models import AgentRunConfig, RunPaths
from rubric_gen.biomnibench.agent.workspaces import TaskCatalog
from rubric_gen.biomnibench.utils.hashing import sha256_file, sha256_text
from rubric_gen.biomnibench.utils.paths import PROJECT_ROOT, resolve_project_path
from rubric_gen.biomnibench.utils.progress import TerminalProgress


HARNESS_PROVIDERS = {
    "gemini-cli": "gemini",
    "claude-code": "claude",
    "codex-cli": "codex",
}
DEFAULT_MODELS = {
    "gemini-cli": "gemini-3.1-pro-preview",
    "claude-code": "claude-opus-4-8",
    "codex-cli": "gpt-5.6-sol",
}
RUBRIC_NAME = "generated_rubric.md"
NOTES_NAME = "solution_notes.md"


def generation_prompt(task_id: str) -> str:
    return f"""You are generating a task-specific evaluation rubric for BiomniBench task {task_id}.

Work as an investigator, analyst, and rubric author. Do not merely paraphrase instruction.md.

1. Read instruction.md and inspect the files under data/.
2. Explore schemas, identifiers, data quality, and relevant metadata.
3. Attempt a tentative solution. Execute useful scripts or commands and check intermediate results. You are not expected to perfect every expensive analysis, but you must learn enough to identify the actual task requirements, correct methods, expected outputs, tolerances, and likely failure modes.
4. Write solution_notes.md describing what you inspected and attempted, concrete findings that inform the rubric, unresolved uncertainty, and commands/artifacts that support those findings.
5. Write generated_rubric.md containing a standalone, human-usable task-specific rubric.

The rubric format is deliberately open. Choose criteria, weights, scores, levels, checklists, gates, penalties, or combinations that fit this task. Do not force A/B/C tiers or a 100-point total. The rubric must nevertheless be operational: a competent grader should be able to distinguish correct, partial, unsupported, and wrong submissions from observable evidence.

Rubric quality requirements:
- Cover the task's substantive result and the analysis needed to support it.
- Be specific to the real files, fields, entities, methods, outputs, and conclusions you discover.
- Separate independent requirements instead of hiding many unrelated checks in one vague criterion.
- State acceptable alternatives and tolerances where the task permits them.
- Require traceable evidence for numerical or scientific claims.
- Address important data-validation, statistical, biological/scientific interpretation, reporting, and limitation requirements when relevant.
- Penalize fabrication, invented citations or identifiers, unsupported specificity, leakage from unavailable reference answers, and conclusions contradicted by executed evidence.
- Avoid overfitting to incidental details of your tentative implementation.
- Clearly distinguish requirements established from task data from your uncertain inferences.

Do not read or search for tests/rubric.txt, existing generated rubrics, judge feedback, previous runs, or reference answers. They are intentionally unavailable. Do not write trace.md or answer.txt. Your required final artifacts are exactly generated_rubric.md and solution_notes.md in the workspace root.
"""


@dataclass(frozen=True)
class RubricGenerationConfig:
    task_dirs: tuple[Path, ...]
    output_dir: Path
    harness: str = "gemini-cli"
    model: str | None = None
    executable: str | None = None
    allow_web: bool = False
    sandbox: bool = False
    skip_trust: bool = True
    approval_mode: str | None = None
    extra_args: tuple[str, ...] = ()
    max_concurrency: int = 1
    resume: bool = False
    raw: bool = False

    def __post_init__(self) -> None:
        if not self.task_dirs:
            raise ValueError("generate requires at least one task")
        if self.harness not in HARNESS_PROVIDERS:
            raise ValueError(f"unsupported generation harness: {self.harness}")
        if self.max_concurrency < 1:
            raise ValueError("max_concurrency must be at least 1")

    @property
    def effective_model(self) -> str:
        return self.model or DEFAULT_MODELS[self.harness]

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "RubricGenerationConfig":
        tasks_dir = resolve_project_path(args.tasks_dir)
        if args.top is not None and args.task is not None:
            raise ValueError("TASK and --top are mutually exclusive")
        if args.top is not None and (args.top == 0 or args.top < -1):
            raise ValueError("--top must be -1 or a positive integer")
        if args.top is not None:
            task_dirs = tuple(TaskCatalog(tasks_dir).tasks())
            if args.top != -1:
                task_dirs = task_dirs[: args.top]
        else:
            if args.task is None:
                raise ValueError("generate requires TASK or --top")
            task = resolve_project_path(args.task)
            task_dirs = (task,)
        output = (
            resolve_project_path(args.output_dir)
            if args.output_dir
            else default_generation_dir()
        )
        return cls(
            task_dirs=task_dirs,
            output_dir=output,
            harness=args.harness,
            model=args.model,
            executable=args.executable,
            allow_web=args.allow_web,
            sandbox=args.sandbox,
            skip_trust=args.skip_trust,
            approval_mode=args.approval_mode,
            extra_args=tuple(args.extra_agent_arg),
            max_concurrency=args.max_concurrency,
            resume=args.resume,
            raw=args.raw,
        )


def default_generation_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return PROJECT_ROOT / "runs" / "biomnibench-rubrics" / f"generation-{stamp}"


class RubricGenerationRunner:
    def __init__(self, config: RubricGenerationConfig) -> None:
        self.config = config
        self.registry = AgentAdapterRegistry()
        provider = HARNESS_PROVIDERS[config.harness]
        self.agent_config = AgentRunConfig(
            provider=provider,
            model=config.effective_model,
            raw=config.raw,
            quiet=True,
            skip_trust=config.skip_trust,
            allow_web=config.allow_web,
            approval_mode=config.approval_mode,
            sandbox=config.sandbox,
            executable=config.executable,
            extra_args=config.extra_args,
            retries=0,
        )
        self.adapter = self.registry.get(provider)

    def run(self) -> int:
        executable = self.adapter.executable(self.agent_config)
        if shutil.which(executable) is None:
            raise SystemExit(
                f"Could not find `{executable}` on PATH. {self.adapter.install_hint()}"
            )
        try:
            self.config.output_dir.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            if exc.errno == errno.EDQUOT:
                raise RuntimeError(
                    f"storage quota exceeded while creating {self.config.output_dir}; "
                    "the filesystem may still have free space because this is an "
                    "account or project quota. Free space in that allocation or pass "
                    "--output-dir on a different writable filesystem"
                ) from exc
            raise
        records: list[dict[str, object]] = []
        with TerminalProgress(
            total=len(self.config.task_dirs),
            description="generate rubrics",
            unit="task",
            position=0,
        ) as progress:
            positions: queue.SimpleQueue[int] = queue.SimpleQueue()
            for position in range(1, self.config.max_concurrency + 1):
                positions.put(position)

            def run_with_progress(task: Path) -> dict[str, object]:
                position = positions.get()
                try:
                    with TerminalProgress(
                        total=1,
                        description=f"generate {task.name}",
                        unit="task",
                        position=position,
                        leave=False,
                    ) as child:
                        child.set_status(self.config.effective_model)
                        result = self._run_task(task)
                        child.update()
                        return result
                finally:
                    positions.put(position)

            with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as pool:
                futures = {
                    pool.submit(run_with_progress, task): task
                    for task in self.config.task_dirs
                }
                for future in as_completed(futures):
                    try:
                        records.append(future.result())
                    except Exception as exc:
                        records.append(
                            {
                                "task_id": futures[future].name,
                                "status": "failed",
                                "error": str(exc),
                            }
                        )
                    progress.update()
        records.sort(key=lambda record: str(record["task_id"]))
        summary = {
            "schema_version": 1,
            "kind": "biomnibench-agentic-rubric-generation",
            "harness": self.config.harness,
            "model": self.config.effective_model,
            "records": records,
        }
        (self.config.output_dir / "summary.json").write_text(
            json.dumps(summary, indent=2) + "\n", encoding="utf-8"
        )
        failures = [record for record in records if record["status"] == "failed"]
        if failures:
            print(f"{len(failures)} rubric generation task(s) failed; first: {failures[0]}")
            return 1
        print(f"Wrote generated rubrics: {self.config.output_dir}")
        return 0

    def _run_task(self, task_dir: Path) -> dict[str, object]:
        task_id = task_dir.name
        run_dir = self.config.output_dir / "tasks" / task_id
        workspace = self.config.output_dir / "workspaces" / task_id
        rubric = workspace / RUBRIC_NAME
        if self.config.resume and self._valid_rubric(rubric):
            return self._record(task_dir, run_dir, workspace, "skipped", 0)
        if run_dir.exists() or workspace.exists():
            raise RuntimeError(
                f"generation output already exists for {task_id}; use --resume or a new --output-dir"
            )
        self._prepare_workspace(task_dir, workspace)
        run_dir.mkdir(parents=True)
        paths = RunPaths(
            provider=self.agent_config.provider,
            run_dir=run_dir,
            workspace_dir=workspace,
            prompt_path=run_dir / "prompt.txt",
            policy_path=run_dir / "no-web-policy.toml",
            stream_path=run_dir / "trajectory.stream.jsonl",
            status_path=run_dir / "status.json",
        )
        prompt = generation_prompt(task_id)
        self.adapter.prepare_run(paths, self.agent_config, prompt)
        command = self.adapter.build_command(paths, self.agent_config, prompt)
        env = os.environ.copy()
        env.setdefault("NO_COLOR", "1")
        with paths.stream_path.open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                command,
                cwd=workspace,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                bufsize=1,
            )
            assert process.stdout is not None
            self._stream(process.stdout, log)
            process_exit = process.wait()
        shutil.rmtree(workspace / "data")
        errors = self._validate_outputs(workspace)
        exit_code = process_exit if process_exit else (1 if errors else 0)
        status = {
            "schema_version": 1,
            "task_id": task_id,
            "task_dir": str(task_dir.resolve()),
            "workspace_dir": str(workspace.resolve()),
            "harness": self.config.harness,
            "provider": self.agent_config.provider,
            "model": self.config.effective_model,
            "process_exit_code": process_exit,
            "exit_code": exit_code,
            "validation_errors": errors,
            "instruction_sha256": sha256_file(task_dir / "instruction.md"),
            "prompt_sha256": sha256_text(prompt),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        if not errors:
            status["rubric_sha256"] = sha256_file(rubric)
            status["solution_notes_sha256"] = sha256_file(workspace / NOTES_NAME)
        paths.status_path.write_text(json.dumps(status, indent=2) + "\n", encoding="utf-8")
        return self._record(
            task_dir,
            run_dir,
            workspace,
            "completed" if exit_code == 0 else "failed",
            exit_code,
            errors,
        )

    def _prepare_workspace(self, task_dir: Path, workspace: Path) -> None:
        instruction = task_dir / "instruction.md"
        data = task_dir / "environment" / "data"
        if not instruction.is_file() or not data.is_dir():
            raise RuntimeError(f"invalid BiomniBench task: {task_dir}")
        workspace.mkdir(parents=True)
        shutil.copy2(instruction, workspace / "instruction.md")
        # The disposable copy prevents an autonomous harness from mutating task data.
        # It is removed immediately after the harness exits.
        shutil.copytree(data, workspace / "data")

    def _stream(self, source: TextIO, log: TextIO) -> None:
        for line in source:
            log.write(line)
            log.flush()
            if self.config.raw:
                print(line.rstrip(), flush=True)

    @staticmethod
    def _valid_rubric(path: Path) -> bool:
        if path.is_symlink() or not path.is_file():
            return False
        try:
            text = path.read_text(encoding="utf-8")
        except (OSError, UnicodeError):
            return False
        return len(text.strip()) >= 200 and "rubric" in text.lower()

    def _validate_outputs(self, workspace: Path) -> list[str]:
        errors: list[str] = []
        rubric = workspace / RUBRIC_NAME
        notes = workspace / NOTES_NAME
        if not self._valid_rubric(rubric):
            errors.append(f"missing_or_invalid: {RUBRIC_NAME}")
        if notes.is_symlink() or not notes.is_file() or notes.stat().st_size < 100:
            errors.append(f"missing_or_invalid: {NOTES_NAME}")
        return errors

    def _record(
        self,
        task_dir: Path,
        run_dir: Path,
        workspace: Path,
        status: str,
        exit_code: int,
        errors: list[str] | None = None,
    ) -> dict[str, object]:
        return {
            "task_id": task_dir.name,
            "status": status,
            "exit_code": exit_code,
            "run_dir": str(run_dir),
            "workspace_dir": str(workspace),
            "rubric": str(workspace / RUBRIC_NAME),
            "solution_notes": str(workspace / NOTES_NAME),
            "validation_errors": errors or [],
        }
