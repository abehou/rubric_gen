"""Common data structures and helpers for BiomniBench agent runs."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

try:
    from tqdm.auto import tqdm
except ImportError:  # pragma: no cover - exercised only without optional dependency.
    tqdm = None


ROOT = Path(__file__).resolve().parents[3]

PROGRESS_BAR_FORMAT = (
    "{desc}: {percentage:3.0f}%|{bar}| {n_fmt}/{total_fmt} "
    "[{elapsed} elapsed, {remaining} remaining, {rate_fmt}]{postfix}"
)


class TerminalProgress:
    """Small context-managed wrapper around the optional terminal progress bar."""

    def __init__(self, *, total: int, description: str, unit: str) -> None:
        self.total = total
        self.description = description
        self.unit = unit
        self._bar: Any = None

    def __enter__(self) -> "TerminalProgress":
        if tqdm is not None:
            self._bar = tqdm(
                total=self.total,
                desc=self.description,
                unit=self.unit,
                dynamic_ncols=True,
                bar_format=PROGRESS_BAR_FORMAT,
                file=sys.stderr,
            )
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        if self._bar is not None:
            self._bar.close()

    def set_status(self, status: str) -> None:
        if self._bar is not None:
            self._bar.set_postfix_str(status)

    def update(self) -> None:
        if self._bar is not None:
            self._bar.update(1)


PROMPT = """You are solving one BiomniBench-DA task in the current directory.

Read ./instruction.md and use only the files under ./data as task data.
Do not read the source paper, source-paper figures, or source-paper supplements.
Do not use web search, web fetch, or browser tools unless the runner explicitly
allows them. Prefer local data analysis and installed package documentation.

Produce exactly these local files:
- ./trace.md: the full analysis trace requested by the instruction.
- ./answer.txt: the final plain-text answer requested by the instruction.

Keep trace.md concise: summarize key commands, scripts, data shapes, metrics,
statistical choices, and limitations; do not paste long tables or full script
bodies when those scripts are saved in the workspace. Write a short provisional
answer.txt as soon as you have a viable result, then update it before stopping.

Use a local uv environment for Python analysis work. If you need Python packages,
create it with `uv venv .venv`, install packages with `uv pip install --python
.venv/bin/python ...`, and run analysis scripts with `.venv/bin/python`.

You may write and run small Python or R scripts in this directory. Keep notes
of commands, intermediate counts, statistical choices, and limitations in
trace.md. Before stopping, verify that both trace.md and answer.txt exist and
are non-empty.
"""

NO_WEB_POLICY = """
[[rule]]
toolName = "google_web_search"
decision = "deny"
priority = 999
denyMessage = "Web search is disabled for this BiomniBench run. Use local task data."

[[rule]]
toolName = "web_fetch"
decision = "deny"
priority = 999
denyMessage = "Web fetch is disabled for this BiomniBench run. Use local task data."
""".lstrip()

GEMINI_API_PRICING_SOURCE = "https://ai.google.dev/gemini-api/docs/pricing"
GEMINI_COST_SOURCE = "estimated_google_gemini_api_standard"
MAX_TRANSIENT_RETRIES = 5

GEMINI_STANDARD_PRICES_PER_MILLION = {
    "gemini-3.5-flash": {
        "input": 1.50,
        "output": 9.00,
        "cached": 0.15,
    },
    "gemini-3.1-flash-lite": {
        "input": 0.25,
        "output": 1.50,
        "cached": 0.025,
    },
    "gemini-3-flash-preview": {
        "input": 0.50,
        "output": 3.00,
        "cached": 0.05,
    },
    "gemini-3-flash": {
        "input": 0.50,
        "output": 3.00,
        "cached": 0.05,
    },
}


def resolve_project_path(path: str | Path) -> Path:
    candidate = Path(path)
    if candidate.is_absolute():
        return candidate
    return (ROOT / candidate).resolve()


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
        batch_dir = runs_dir / f"all-{provider}-{stamp}"
        return cls.from_batch_dir(
            provider=provider, batch_dir=batch_dir, is_resume=False
        )

    @classmethod
    def resume(cls, batch_dir: Path, provider: str) -> "BatchRunPaths":
        return cls.from_batch_dir(
            provider=provider, batch_dir=batch_dir, is_resume=True
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
class RunCost:
    cost_usd: float | None = None
    estimated_cost_usd: float | None = None
    source: str | None = None

    @classmethod
    def from_stream(cls, stream_path: Path) -> "RunCost":
        cost_usd: float | None = None
        estimated_cost_usd: float | None = None
        if not stream_path.is_file():
            return cls()

        with stream_path.open() as stream:
            for line in stream:
                try:
                    event = json.loads(line)
                except json.JSONDecodeError:
                    continue
                event_cost = cls.from_event(event)
                if event_cost.cost_usd is not None:
                    cost_usd = event_cost.cost_usd
                if event_cost.estimated_cost_usd is not None:
                    estimated_cost_usd = event_cost.estimated_cost_usd
        source = "reported" if cost_usd is not None else None
        if source is None and estimated_cost_usd is not None:
            source = GEMINI_COST_SOURCE
        return cls(cost_usd, estimated_cost_usd, source)

    @classmethod
    def from_status(cls, status_path: Path) -> "RunCost":
        if not status_path.is_file():
            return cls()
        try:
            status = json.loads(status_path.read_text())
        except json.JSONDecodeError:
            return cls()
        cost_usd = _parse_cost_value(status.get("cost_usd"))
        estimated_cost_usd = _parse_cost_value(status.get("estimated_cost_usd"))
        return cls(
            cost_usd=cost_usd,
            estimated_cost_usd=estimated_cost_usd,
            source=status.get("cost_source"),
        )

    @classmethod
    def for_run_dir(cls, run_dir: Path) -> "RunCost":
        status_cost = cls.from_status(run_dir / "status.json")
        if (
            status_cost.cost_usd is not None
            or status_cost.estimated_cost_usd is not None
        ):
            return status_cost
        return cls.from_stream(run_dir / "trajectory.stream.jsonl")

    @classmethod
    def from_event(cls, event: Any) -> "RunCost":
        cost_usd = _find_cost_usd(event)
        estimated_cost_usd = _estimate_gemini_event_cost(event)
        source = "reported" if cost_usd is not None else None
        if source is None and estimated_cost_usd is not None:
            source = GEMINI_COST_SOURCE
        return cls(cost_usd, estimated_cost_usd, source)

    def fields(self) -> dict[str, float | str | None]:
        return {
            "cost_usd": self.cost_usd,
            "estimated_cost_usd": self.estimated_cost_usd,
            "cost_source": self.source,
        }


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


class TaskWorkspace:
    def __init__(self, task_dir: Path, workspace_dir: Path) -> None:
        self.task_dir = task_dir
        self.workspace_dir = workspace_dir

    @property
    def instruction_path(self) -> Path:
        return self.task_dir / "instruction.md"

    @property
    def data_dir(self) -> Path:
        return self.task_dir / "environment" / "data"

    def validate(self) -> None:
        if not self.instruction_path.is_file():
            raise SystemExit(f"Missing instruction.md in {self.task_dir}")
        if not self.data_dir.is_dir():
            raise SystemExit(f"Missing environment/data in {self.task_dir}")

    def prepare(self) -> None:
        self.validate()
        (self.workspace_dir / "data").mkdir(parents=True, exist_ok=True)
        shutil.copy2(self.instruction_path, self.workspace_dir / "instruction.md")
        shutil.copytree(
            self.data_dir,
            self.workspace_dir / "data",
            dirs_exist_ok=True,
        )


class TaskCatalog:
    def __init__(self, tasks_dir: Path) -> None:
        self.tasks_dir = tasks_dir

    def tasks(self) -> list[Path]:
        if not self.tasks_dir.is_dir():
            raise SystemExit(f"Missing tasks directory: {self.tasks_dir}")
        return sorted(
            task_dir
            for task_dir in self.tasks_dir.iterdir()
            if task_dir.is_dir()
            and task_dir.name.startswith("da-")
            and (task_dir / "instruction.md").is_file()
            and (task_dir / "environment" / "data").is_dir()
        )


class CompletedRunIndex:
    def __init__(self, runs_dir: Path, provider: str) -> None:
        self.runs_dir = runs_dir
        self.provider = provider

    def find(self, task_name: str) -> Path | None:
        for run_dir in sorted(
            self.runs_dir.glob(f"{task_name}-{self.provider}-*"), reverse=True
        ):
            if self.is_completed(run_dir, self.provider):
                return run_dir
        return None

    @staticmethod
    def is_completed(run_dir: Path, provider: str) -> bool:
        status_path = run_dir / "status.json"
        if not status_path.is_file():
            return False
        try:
            status = json.loads(status_path.read_text())
        except json.JSONDecodeError:
            return False
        if status.get("provider") not in (None, provider):
            return False

        workspace_dir = Path(status.get("workspace_dir") or run_dir / "workspace")
        trace_path = workspace_dir / "trace.md"
        answer_path = workspace_dir / "answer.txt"
        return (
            status.get("exit_code") == 0
            and not status.get("validation_errors")
            and trace_path.is_file()
            and answer_path.is_file()
            and trace_path.stat().st_size > 0
            and answer_path.stat().st_size > 0
        )


def event_text(event: Any) -> str | None:
    if not isinstance(event, dict):
        return None

    candidates: list[str] = []
    stack: list[Any] = [event]
    interesting_keys = {
        "text",
        "content",
        "message",
        "thought",
        "name",
        "command",
        "status",
        "type",
    }

    while stack:
        value = stack.pop()
        if isinstance(value, dict):
            for key, child in value.items():
                if key in interesting_keys and isinstance(child, str) and child.strip():
                    candidates.append(f"{key}={child.strip()}")
                elif isinstance(child, (dict, list)):
                    stack.append(child)
        elif isinstance(value, list):
            stack.extend(value)

    if not candidates:
        return None
    return " | ".join(candidates[:6])


def _find_cost_usd(value: Any) -> float | None:
    if isinstance(value, dict):
        for key, child in value.items():
            if _is_usd_cost_key(key):
                cost = _parse_cost_value(child)
                if cost is not None:
                    return cost
            cost = _find_cost_usd(child)
            if cost is not None:
                return cost
    elif isinstance(value, list):
        for child in value:
            cost = _find_cost_usd(child)
            if cost is not None:
                return cost
    return None


def _is_usd_cost_key(key: str) -> bool:
    normalized = "".join(char for char in key.lower() if char.isalnum())
    return "cost" in normalized and "usd" in normalized


def _parse_cost_value(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        stripped = value.strip().removeprefix("$")
        try:
            return float(stripped)
        except ValueError:
            return None
    return None


def _estimate_gemini_event_cost(event: Any) -> float | None:
    if not isinstance(event, dict):
        return None
    stats = event.get("stats")
    if not isinstance(stats, dict):
        return None
    models = stats.get("models")
    if not isinstance(models, dict):
        return None

    total = 0.0
    matched = False
    for model_name, model_stats in models.items():
        if not isinstance(model_name, str) or not isinstance(model_stats, dict):
            continue
        prices = GEMINI_STANDARD_PRICES_PER_MILLION.get(model_name)
        if prices is None:
            continue
        matched = True
        cached_tokens = _parse_token_count(model_stats.get("cached")) or 0
        input_tokens = _parse_token_count(model_stats.get("input"))
        if input_tokens is None:
            total_input_tokens = (
                _parse_token_count(model_stats.get("input_tokens")) or 0
            )
            input_tokens = max(total_input_tokens - cached_tokens, 0)
        output_tokens = _parse_token_count(model_stats.get("output_tokens")) or 0
        total += (
            input_tokens * prices["input"]
            + cached_tokens * prices["cached"]
            + output_tokens * prices["output"]
        ) / 1_000_000

    if not matched:
        return None
    return round(total, 6)


def _parse_token_count(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    return None
