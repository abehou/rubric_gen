from __future__ import annotations

import os
import json
import subprocess
import sys
from pathlib import Path

import pytest

from rubric_gen.runtime.agents.adapters import (
    ClaudeAdapter,
    CodexAdapter,
    GeminiAdapter,
)
from rubric_gen.runtime.agents.models import AgentRunConfig, RunPaths
from rubric_gen.runtime.process_environment import (
    NUMERICAL_THREAD_LIMITS,
    controlled_process_environment,
    controlled_python_prefix,
)


def test_controlled_process_environment_overrides_hostile_parent_values() -> None:
    environment = controlled_process_environment({
        "PATH": "/usr/local/bin:/usr/bin:/bin",
        **{name: "64" for name in NUMERICAL_THREAD_LIMITS},
    })

    assert environment["PATH"].split(os.pathsep)[0] == str(
        controlled_python_prefix() / "bin"
    )
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert {
        name: environment[name]
        for name in NUMERICAL_THREAD_LIMITS
    } == NUMERICAL_THREAD_LIMITS
    if sys.prefix != sys.base_prefix:
        assert environment["VIRTUAL_ENV"] == sys.prefix


def test_controlled_process_environment_deduplicates_python_bin() -> None:
    python_bin = str(controlled_python_prefix() / "bin")
    environment = controlled_process_environment({
        "PATH": f"/usr/bin:{python_bin}:{python_bin}:/bin",
    })

    assert environment["PATH"].split(os.pathsep) == [
        python_bin,
        "/usr/bin",
        "/bin",
    ]


@pytest.mark.parametrize(
    ("adapter", "provider"),
    [
        (CodexAdapter(), "codex"),
        (GeminiAdapter(), "gemini"),
        (ClaudeAdapter(), "claude"),
    ],
)
def test_every_agent_environment_prefers_checkout_python(
    adapter: CodexAdapter | GeminiAdapter | ClaudeAdapter,
    provider: str,
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    paths = RunPaths(
        provider=provider,
        run_dir=tmp_path / "run",
        workspace_dir=workspace,
        prompt_path=tmp_path / "run/prompt.txt",
        policy_path=tmp_path / "run/policy.toml",
        stream_path=tmp_path / "run/stream.jsonl",
        status_path=tmp_path / "run/status.json",
    )

    environment = adapter.build_environment(
        paths,
        AgentRunConfig(provider=provider),
    )

    assert environment["PATH"].split(os.pathsep)[0] == str(
        controlled_python_prefix() / "bin"
    )
    assert environment["PYTHONNOUSERSITE"] == "1"
    assert all(environment[name] == "1" for name in NUMERICAL_THREAD_LIMITS)


def test_controlled_environment_executes_checkout_numpy() -> None:
    environment = controlled_process_environment({"PATH": "/usr/bin:/bin"})
    probe = subprocess.run(
        [
            "python3",
            "-c",
            (
                "import json, os, sys, numpy; "
                "print(json.dumps({"
                "'executable': sys.executable, "
                "'prefix': sys.prefix, "
                "'numpy': numpy.__file__, "
                "'environment': {name: os.environ.get(name) for name in "
                f"{tuple(sorted(NUMERICAL_THREAD_LIMITS | {'PYTHONNOUSERSITE': '1'}))!r}"
                "}}))"
            ),
        ],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    payload = json.loads(probe.stdout)
    prefix = controlled_python_prefix()

    assert Path(payload["prefix"]) == prefix
    assert Path(payload["numpy"]).is_relative_to(prefix)
    assert payload["environment"] == {
        **NUMERICAL_THREAD_LIMITS,
        "PYTHONNOUSERSITE": "1",
    }
