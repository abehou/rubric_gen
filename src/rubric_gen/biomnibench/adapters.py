"""Provider-specific command adapters for terminal coding agents."""

from __future__ import annotations

import json
from abc import ABC, abstractmethod

from rubric_gen.biomnibench.common import (
    NO_WEB_POLICY,
    PROMPT,
    AgentRunConfig,
    RunPaths,
    event_text,
)


class AgentAdapter(ABC):
    name: str
    default_executable: str

    def executable(self, config: AgentRunConfig) -> str:
        return config.executable or self.default_executable

    def install_hint(self) -> str:
        return f"Install `{self.default_executable}` and make it available on PATH."

    def prepare_run(self, paths: RunPaths, config: AgentRunConfig) -> None:
        paths.prompt_path.write_text(PROMPT)

    @abstractmethod
    def build_command(self, paths: RunPaths, config: AgentRunConfig) -> list[str]:
        raise NotImplementedError

    def print_line(self, line: str, *, raw: bool) -> None:
        stripped = line.strip()
        if not stripped:
            return
        if raw:
            print(stripped, flush=True)
            return
        try:
            event = json.loads(stripped)
        except json.JSONDecodeError:
            print(stripped, flush=True)
            return
        text = event_text(event)
        if text:
            print(text, flush=True)


class GeminiAdapter(AgentAdapter):
    name = "gemini"
    default_executable = "gemini"

    def install_hint(self) -> str:
        return "Install Gemini CLI with `npm install -g @google/gemini-cli`."

    def prepare_run(self, paths: RunPaths, config: AgentRunConfig) -> None:
        super().prepare_run(paths, config)
        paths.policy_path.write_text(NO_WEB_POLICY)

    def build_command(self, paths: RunPaths, config: AgentRunConfig) -> list[str]:
        command = [self.executable(config)]
        if config.model:
            command.extend(["-m", config.model])
        command.extend(["-p", PROMPT, "--output-format", "stream-json"])
        command.extend(["--approval-mode", config.approval_mode or "yolo"])
        if config.sandbox:
            command.append("--sandbox")
        if config.skip_trust:
            command.append("--skip-trust")
        if not config.allow_web:
            command.extend(["--policy", str(paths.policy_path)])
        command.extend(config.extra_args)
        return command


class ClaudeAdapter(AgentAdapter):
    name = "claude"
    default_executable = "claude"

    def install_hint(self) -> str:
        return "Install Claude Code from https://github.com/anthropics/claude-code."

    def build_command(self, paths: RunPaths, config: AgentRunConfig) -> list[str]:
        command = [
            self.executable(config),
            "--print",
            "--output-format",
            "stream-json",
            "--permission-mode",
            config.approval_mode or "bypassPermissions",
            "--no-session-persistence",
        ]
        if config.model:
            command.extend(["--model", config.model])
        if config.skip_trust:
            command.append("--allow-dangerously-skip-permissions")
        if not config.allow_web:
            command.extend(["--disallowed-tools", "WebSearch", "WebFetch"])
        command.extend(config.extra_args)
        command.append(PROMPT)
        return command


class CodexAdapter(AgentAdapter):
    name = "codex"
    default_executable = "codex"

    def install_hint(self) -> str:
        return "Install Codex CLI with `npm install -g @openai/codex` or the official installer."

    def build_command(self, paths: RunPaths, config: AgentRunConfig) -> list[str]:
        command = [
            self.executable(config),
            "exec",
            "--skip-git-repo-check",
            "--color",
            "never",
            "--json",
            "--ask-for-approval",
            config.approval_mode or "never",
            "--sandbox",
            "workspace-write",
        ]
        if config.model:
            command.extend(["--model", config.model])
        if config.allow_web:
            command.append("--search")
        if config.skip_trust:
            command.append("--dangerously-bypass-hook-trust")
        command.extend(config.extra_args)
        command.append(PROMPT)
        return command


class AgentAdapterRegistry:
    def __init__(self, adapters: tuple[AgentAdapter, ...] | None = None) -> None:
        self._adapters = {
            adapter.name: adapter
            for adapter in (
                adapters
                or (
                    GeminiAdapter(),
                    ClaudeAdapter(),
                    CodexAdapter(),
                )
            )
        }

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(sorted(self._adapters))

    def get(self, provider: str) -> AgentAdapter:
        try:
            return self._adapters[provider]
        except KeyError as exc:
            allowed = ", ".join(self.names)
            raise SystemExit(f"Unknown provider `{provider}`. Choose one of: {allowed}") from exc
