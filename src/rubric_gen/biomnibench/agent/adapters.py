"""Provider-specific command adapters for terminal coding agents."""

from __future__ import annotations

import json
import os
import shutil
import stat
from abc import ABC, abstractmethod
from pathlib import Path

from rubric_gen.biomnibench.agent.events import event_text
from rubric_gen.biomnibench.agent.models import AgentRunConfig, RunPaths
from rubric_gen.biomnibench.agent.prompts import NO_WEB_POLICY, PROMPT


class AgentAdapter(ABC):
    name: str
    default_executable: str

    def executable(self, config: AgentRunConfig) -> str:
        return config.executable or self.default_executable

    def install_hint(self) -> str:
        return f"Install `{self.default_executable}` and make it available on PATH."

    def prepare_run(
        self, paths: RunPaths, config: AgentRunConfig, prompt: str = PROMPT
    ) -> None:
        paths.run_dir.mkdir(parents=True, exist_ok=True)
        paths.prompt_path.write_text(prompt)

    def build_environment(
        self, paths: RunPaths, config: AgentRunConfig
    ) -> dict[str, str]:
        """Return a minimal CLI environment, excluding unrelated credentials."""
        allowed_exact = {
            "PATH", "LANG", "LANGUAGE", "LC_ALL", "NO_COLOR",
            "SSL_CERT_FILE", "SSL_CERT_DIR", "NODE_EXTRA_CA_CERTS",
            "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
        }
        allowed_prefixes = ("LC_",)
        environment = {
            key: value
            for key, value in os.environ.items()
            if key in allowed_exact or key.startswith(allowed_prefixes)
        }
        state = paths.workspace_dir.parent / ".agent-state" / self.name
        state.mkdir(parents=True, exist_ok=True, mode=0o700)
        state.chmod(0o700)
        temporary = state / "tmp"
        temporary.mkdir(exist_ok=True, mode=0o700)
        environment.update({
            "HOME": str(state),
            "TMPDIR": str(temporary),
            "NO_COLOR": "1",
        })
        return environment

    @abstractmethod
    def build_command(
        self, paths: RunPaths, config: AgentRunConfig, prompt: str = PROMPT
    ) -> list[str]:
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

    def prepare_run(
        self, paths: RunPaths, config: AgentRunConfig, prompt: str = PROMPT
    ) -> None:
        super().prepare_run(paths, config, prompt)
        paths.policy_path.write_text(NO_WEB_POLICY)

    def build_command(
        self, paths: RunPaths, config: AgentRunConfig, prompt: str = PROMPT
    ) -> list[str]:
        command = [self.executable(config)]
        if config.model:
            command.extend(["-m", config.model])
        command.extend(["-p", prompt, "--output-format", "stream-json"])
        command.extend(["--approval-mode", "yolo", "--sandbox=true"])
        command.extend(["--policy", str(paths.policy_path)])
        return command

    def build_environment(
        self, paths: RunPaths, config: AgentRunConfig
    ) -> dict[str, str]:
        environment = super().build_environment(paths, config)
        for key in ("GEMINI_API_KEY", "GOOGLE_API_KEY"):
            if key in os.environ:
                environment[key] = os.environ[key]
        return environment


class ClaudeAdapter(AgentAdapter):
    name = "claude"
    default_executable = "claude"

    def install_hint(self) -> str:
        return "Install Claude Code from https://github.com/anthropics/claude-code."

    def build_command(
        self, paths: RunPaths, config: AgentRunConfig, prompt: str = PROMPT
    ) -> list[str]:
        command = [
            self.executable(config),
            "--print",
            "--verbose",
            "--output-format",
            "stream-json",
            "--permission-mode",
            "dontAsk",
            "--no-session-persistence",
            "--strict-mcp-config",
            "--mcp-config",
            '{"mcpServers":{}}',
            "--setting-sources",
            "",
            "--no-chrome",
            "--disable-slash-commands",
        ]
        if config.model:
            command.extend(["--model", config.model])
        command.append("--disallowed-tools=WebSearch,WebFetch")
        command.append(prompt)
        return command

    def build_environment(
        self, paths: RunPaths, config: AgentRunConfig
    ) -> dict[str, str]:
        environment = super().build_environment(paths, config)
        if "ANTHROPIC_API_KEY" in os.environ:
            environment["ANTHROPIC_API_KEY"] = os.environ["ANTHROPIC_API_KEY"]
        return environment


class CodexAdapter(AgentAdapter):
    name = "codex"
    default_executable = "codex"

    def install_hint(self) -> str:
        return "Install Codex CLI with `npm install -g @openai/codex` or the official installer."

    def build_command(
        self, paths: RunPaths, config: AgentRunConfig, prompt: str = PROMPT
    ) -> list[str]:
        command = [
            self.executable(config),
            "--cd",
            str(paths.workspace_dir.resolve()),
            "exec",
            "--skip-git-repo-check",
            "--strict-config",
            "--ignore-rules",
            "--json",
        ]
        if config.model:
            command.extend(["--model", config.model])
        if config.reasoning_effort:
            command.extend([
                "--config",
                f'model_reasoning_effort="{config.reasoning_effort}"',
            ])
        if config.service_tier:
            command.extend([
                "--config",
                f'service_tier="{config.service_tier}"',
            ])
        command.append(prompt)
        return command

    def prepare_run(
        self, paths: RunPaths, config: AgentRunConfig, prompt: str = PROMPT
    ) -> None:
        super().prepare_run(paths, config, prompt)
        codex_home = self._codex_home(paths)
        codex_home.mkdir(parents=True, exist_ok=True, mode=0o700)
        codex_home.chmod(0o700)
        config_path = codex_home / "config.toml"
        controlled = _CODEX_SCIENTIFIC_CONFIG
        if config_path.exists():
            if config_path.is_symlink() or config_path.read_text() != controlled:
                raise RuntimeError("controlled Codex configuration changed")
        else:
            config_path.write_text(controlled)
            config_path.chmod(0o600)
        self._copy_codex_auth(codex_home)

    def build_environment(
        self, paths: RunPaths, config: AgentRunConfig
    ) -> dict[str, str]:
        environment = super().build_environment(paths, config)
        environment["CODEX_HOME"] = str(self._codex_home(paths))
        for key in ("CODEX_API_KEY", "CODEX_ACCESS_TOKEN"):
            if key in os.environ:
                environment[key] = os.environ[key]
        return environment

    @staticmethod
    def _codex_home(paths: RunPaths) -> Path:
        return paths.workspace_dir.parent / ".agent-state" / "codex"

    @staticmethod
    def _copy_codex_auth(codex_home: Path) -> None:
        if "CODEX_API_KEY" in os.environ or "CODEX_ACCESS_TOKEN" in os.environ:
            return
        source_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
        source = source_home / "auth.json"
        destination = codex_home / "auth.json"
        if destination.exists():
            if destination.is_symlink() or not destination.is_file():
                raise RuntimeError("controlled Codex auth path is invalid")
            return
        if not source.is_file() or source.is_symlink():
            raise RuntimeError(
                "Codex scientific runs require CODEX_API_KEY, CODEX_ACCESS_TOKEN, "
                "or a regular CODEX_HOME/auth.json"
            )
        shutil.copyfile(source, destination)
        destination.chmod(0o600)


_CODEX_SCIENTIFIC_CONFIG = """\
approval_policy = "never"
web_search = "disabled"
allow_login_shell = false
default_permissions = "biomnibench-task"

[permissions.biomnibench-task]
description = "BiomniBench task workspace only; no command network access."

[permissions.biomnibench-task.filesystem]
":minimal" = "read"

[permissions.biomnibench-task.filesystem.":workspace_roots"]
"." = "write"

[permissions.biomnibench-task.network]
enabled = false

[shell_environment_policy]
inherit = "core"
ignore_default_excludes = false

[shell_environment_policy.filters]
"*KEY*" = "exclude"
"*SECRET*" = "exclude"
"*TOKEN*" = "exclude"
"CODEX_HOME" = "exclude"
"HTTP_PROXY" = "exclude"
"HTTPS_PROXY" = "exclude"
"ALL_PROXY" = "exclude"
"""


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
            raise SystemExit(
                f"Unknown provider `{provider}`. Choose one of: {allowed}"
            ) from exc
