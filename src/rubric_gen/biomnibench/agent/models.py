"""Configuration and path values for agent runs."""

from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass, field
from pathlib import Path

from rubric_gen.biomnibench.utils.paths import resolve_project_path


@dataclass(frozen=True)
class RunPaths:
    provider: str
    run_dir: Path
    workspace_dir: Path
    prompt_path: Path
    policy_path: Path
    stream_path: Path
    status_path: Path

    @classmethod
    def for_task(
        cls,
        task_dir: Path,
        runs_dir: Path,
        provider: str = "gemini",
        stamp: str | None = None,
    ) -> "RunPaths":
        stamp = stamp or dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        run_name = f"{task_dir.name}-{provider}-{stamp}"
        run_dir = runs_dir / run_name
        return cls(
            provider=provider,
            run_dir=run_dir,
            workspace_dir=runs_dir / "_workspaces" / run_name,
            prompt_path=run_dir / "prompt.txt",
            policy_path=run_dir / "no-web-policy.toml",
            stream_path=run_dir / "trajectory.stream.jsonl",
            status_path=run_dir / "status.json",
        )


@dataclass(frozen=True)
class BatchRunPaths:
    provider: str
    batch_dir: Path
    tasks_dir: Path
    workspaces_dir: Path
    summary_path: Path
    progress_path: Path
    status_path: Path
    is_resume: bool = False

    @classmethod
    def create(
        cls,
        runs_dir: Path,
        provider: str,
        stamp: str | None = None,
    ) -> "BatchRunPaths":
        stamp = stamp or dt.datetime.now().strftime("%Y%m%d-%H%M%S")
        return cls.from_batch_dir(
            provider=provider,
            batch_dir=runs_dir / f"all-{provider}-{stamp}",
            is_resume=False,
        )

    @classmethod
    def resume(cls, batch_dir: Path, provider: str) -> "BatchRunPaths":
        return cls.from_batch_dir(
            provider=provider,
            batch_dir=batch_dir,
            is_resume=True,
        )

    @classmethod
    def from_batch_dir(
        cls,
        provider: str,
        batch_dir: Path,
        *,
        is_resume: bool,
    ) -> "BatchRunPaths":
        return cls(
            provider=provider,
            batch_dir=batch_dir,
            tasks_dir=batch_dir / "tasks",
            workspaces_dir=batch_dir / "workspaces",
            summary_path=batch_dir / "all-runs-summary.jsonl",
            progress_path=batch_dir / "progress.jsonl",
            status_path=batch_dir / "batch-status.json",
            is_resume=is_resume,
        )

    def task_paths(self, task_dir: Path) -> RunPaths:
        task_name = task_dir.name
        run_dir = self.tasks_dir / task_name
        return RunPaths(
            provider=self.provider,
            run_dir=run_dir,
            workspace_dir=self.workspaces_dir / task_name,
            prompt_path=run_dir / "prompt.txt",
            policy_path=run_dir / "no-web-policy.toml",
            stream_path=run_dir / "trajectory.stream.jsonl",
            status_path=run_dir / "status.json",
        )


@dataclass(frozen=True)
class AgentRunConfig:
    provider: str = "gemini"
    model: str | None = None
    raw: bool = False
    quiet: bool = False
    skip_trust: bool = False
    allow_web: bool = False
    approval_mode: str | None = None
    sandbox: bool = False
    executable: str | None = None
    extra_args: tuple[str, ...] = field(default_factory=tuple)
    retries: int = 1

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "AgentRunConfig":
        return cls(
            provider=getattr(args, "provider", "gemini"),
            model=getattr(args, "model", None),
            raw=getattr(args, "raw", False),
            quiet=getattr(args, "quiet", False),
            skip_trust=getattr(args, "skip_trust", False),
            allow_web=getattr(args, "allow_web", False),
            approval_mode=getattr(args, "approval_mode", None),
            sandbox=getattr(args, "sandbox", False),
            executable=getattr(args, "executable", None),
            extra_args=tuple(getattr(args, "extra_agent_arg", None) or ()),
            retries=max(0, getattr(args, "retries", 1)),
        )


@dataclass(frozen=True)
class BatchRunConfig:
    tasks_dir: Path
    runs_dir: Path
    provider: str = "gemini"
    model: str | None = None
    raw: bool = False
    skip_trust: bool = False
    allow_web: bool = False
    approval_mode: str | None = None
    sandbox: bool = False
    executable: str | None = None
    extra_args: tuple[str, ...] = field(default_factory=tuple)
    limit: int | None = None
    force: bool = False
    continue_on_error: bool = False
    resume_run: Path | None = None
    retries: int = 1
    max_concurrency: int = 1

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "BatchRunConfig":
        resume_run = getattr(args, "resume_run", None)
        return cls(
            tasks_dir=resolve_project_path(getattr(args, "tasks_dir")),
            runs_dir=resolve_project_path(getattr(args, "runs_dir")),
            provider=getattr(args, "provider", "gemini"),
            model=getattr(args, "model", None),
            raw=getattr(args, "raw", False),
            skip_trust=getattr(args, "skip_trust", False),
            allow_web=getattr(args, "allow_web", False),
            approval_mode=getattr(args, "approval_mode", None),
            sandbox=getattr(args, "sandbox", False),
            executable=getattr(args, "executable", None),
            extra_args=tuple(getattr(args, "extra_agent_arg", None) or ()),
            limit=getattr(args, "limit", None),
            force=getattr(args, "force", False),
            continue_on_error=getattr(args, "continue_on_error", False),
            resume_run=resolve_project_path(resume_run) if resume_run else None,
            retries=max(0, getattr(args, "retries", 1)),
            max_concurrency=max(1, getattr(args, "max_concurrency", 1)),
        )

    def agent_config(self) -> AgentRunConfig:
        return AgentRunConfig(
            provider=self.provider,
            model=self.model,
            raw=self.raw,
            quiet=True,
            skip_trust=self.skip_trust,
            allow_web=self.allow_web,
            approval_mode=self.approval_mode,
            sandbox=self.sandbox,
            executable=self.executable,
            extra_args=self.extra_args,
            retries=self.retries,
        )
