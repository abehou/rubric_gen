"""Configuration and path values for agent runs."""

from __future__ import annotations

import argparse
import datetime as dt
from dataclasses import dataclass
from pathlib import Path



@dataclass(frozen=True)
class RunPaths:
    provider: str
    run_dir: Path
    workspace_dir: Path
    prompt_path: Path
    policy_path: Path
    stream_path: Path
    status_path: Path
    output_schema_path: Path | None = None
    output_last_message_path: Path | None = None

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
class AgentRunConfig:
    provider: str = "codex"
    model: str | None = None
    base_url: str | None = None
    raw: bool = False
    quiet: bool = False
    executable: str | None = None
    reasoning_effort: str | None = None
    service_tier: str | None = None
    retries: int = 1
    timeout_seconds: int = 7_200

    def __post_init__(self) -> None:
        if self.base_url is not None and self.provider != "vllm":
            raise ValueError("base_url is supported only by the vLLM provider")
        if self.reasoning_effort is not None and self.provider != "codex":
            raise ValueError("reasoning_effort is supported only by Codex")
        if self.reasoning_effort not in {None, "minimal", "low", "medium", "high", "xhigh"}:
            raise ValueError("reasoning_effort is invalid")
        if self.service_tier is not None and self.provider != "codex":
            raise ValueError("service_tier is supported only by Codex")
        if type(self.retries) is not int or self.retries < 0:
            raise ValueError("retries must be a non-negative integer")
        if type(self.timeout_seconds) is not int or self.timeout_seconds < 1:
            raise ValueError("timeout_seconds must be a positive integer")

    @classmethod
    def from_namespace(cls, args: argparse.Namespace) -> "AgentRunConfig":
        return cls(
            provider=getattr(args, "provider", "codex"),
            model=getattr(args, "model", None),
            base_url=getattr(args, "base_url", None),
            raw=getattr(args, "raw", False),
            quiet=getattr(args, "quiet", False),
            executable=getattr(args, "executable", None),
            reasoning_effort=getattr(args, "reasoning_effort", None),
            service_tier=getattr(args, "service_tier", None),
            retries=max(0, getattr(args, "retries", 1)),
            timeout_seconds=getattr(args, "turn_timeout_seconds", 7_200),
        )
