from __future__ import annotations

import json
import os
import shutil
import subprocess
import threading
from types import SimpleNamespace
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

import rubric_gen.benchmarks.harvey_lab.designer as designer_module
import rubric_gen.benchmarks.harvey_lab.evaluator as evaluator_module
from rubric_gen.benchmarks.harvey_lab.audits import prepare_reward_hacking_cases, run_quality_audit
from rubric_gen.benchmarks.harvey_lab.artifacts import tree_sha256, validate_checkout
from rubric_gen.benchmarks.harvey_lab.config import (
    HarnessDesigner,
    HarveyBenchmark,
    HarveyExperiment,
    HarveyJudge,
    RewardHackingAudit,
    RubricEvolution,
    TaskAgent,
    load_experiment,
)
from rubric_gen.benchmarks.harvey_lab.controller import HarveyEvolutionController, build_ranking
from rubric_gen.benchmarks.harvey_lab.cached_judge import (
    CachedAnthropicJudge,
    JudgeUsage,
    score_criteria,
    split_cached_prompt,
)
from rubric_gen.benchmarks.harvey_lab.designer import DESIGNER_PROMPT, CodexHarnessDesigner, DesignedCandidate
from rubric_gen.benchmarks.harvey_lab.evaluator import (
    CandidateEvaluation,
    HarveyEvaluator,
    validate_harvey_score,
)
from rubric_gen.benchmarks.harvey_lab.podman import (
    cache_image,
    configured_podman_environment,
    restore_cached_image,
)
from rubric_gen.benchmarks.harvey_lab.rubrics import TaskRubricProposer
from rubric_gen.benchmarks.harvey_lab.runtime import runtime_root_from_environment
from rubric_gen.benchmarks.harvey_lab.seal import (
    SEAL_NAME,
    seal_harvey_run,
    validate_harvey_run_seal,
)
from rubric_gen.runtime.llm import GenerationResult, request_parameters_for_model


def _task() -> dict[str, object]:
    return {
        "title": "Review",
        "instructions": "Review the agreement.",
        "deliverables": {"memo.md": "A memo"},
        "criteria": [
            {
                "id": "C-001",
                "title": "Identifies the issue",
                "deliverables": ["memo.md"],
                "match_criteria": "PASS if the memo identifies the issue. FAIL otherwise.",
            },
            {
                "id": "C-002",
                "title": "Gives advice",
                "deliverables": ["memo.md"],
                "match_criteria": "PASS if the memo gives advice. FAIL otherwise.",
            },
        ],
    }


def _score(
    n_passed: int = 1,
    n_criteria: int = 2,
    *,
    run_id: str = "run",
    task: str = "area/task",
) -> dict[str, object]:
    all_pass = n_passed == n_criteria
    criteria = [
        {
            "id": f"C-{index + 1:03d}",
            "title": f"Criterion {index + 1}",
            "verdict": "pass" if index < n_passed else "fail",
            "reasoning": "Evidence.",
        }
        for index in range(n_criteria)
    ]
    return {
        "score": 1.0 if all_pass else 0.0,
        "max_score": 1.0,
        "summary": f"{n_passed}/{n_criteria} criteria passed.",
        "all_pass": all_pass,
        "n_criteria": n_criteria,
        "n_passed": n_passed,
        "criteria_results": criteria,
        "run_id": run_id,
        "task": task,
        "judge_model": "claude-sonnet-4-6",
        "scored_at": "2026-08-27T00:00:00+00:00",
        "judge_usage": {
            "requests": n_criteria,
            "input_tokens": 100,
            "cache_creation_input_tokens": 1_000,
            "cache_read_input_tokens": max(n_criteria - 1, 0) * 1_000,
            "output_tokens": 20,
        },
        "task_agent_usage": {
            "input_tokens": 0,
            "output_tokens": 0,
            "wall_clock_seconds": 0,
        },
        "doc_coverage": {
            "documents_read": 0,
            "total_documents": 0,
            "documents_skipped": 0,
            "documents_read_list": [],
            "documents_skipped_list": [],
        },
    }


def _config_text(tmp_path: Path, *, mode: str = "prospective") -> str:
    proposer = (
        "  proposer_model: gpt-5.6-sol\n"
        if mode == "prospective"
        else ""
    )
    return f"""kind: rubric-gen-harvey-harness-evolution-experiment
experiment_id: harvey-test
output_dir: output
cache_dir: cache
benchmark:
  checkout: checkout
  revision: {'a' * 40}
  development_tasks: [area/task]
  held_out_tasks: []
task_agent:
  model: gpt-5.6-luna
  credential_env: [OPENAI_API_KEY]
judge:
  model: claude-sonnet-4-6
  credential_env: [ANTHROPIC_API_KEY]
designer:
  model: gpt-5.6-sol
  rounds: 2
rubric:
  mode: {mode}
{proposer}  max_changes_per_task: 3
  max_output_tokens: 4096
audit:
  models: [gpt-5.6-sol]
"""


def test_load_harvey_experiment_resolves_paths_and_modes(tmp_path: Path) -> None:
    path = tmp_path / "experiment.yaml"
    path.write_text(_config_text(tmp_path), encoding="utf-8")

    experiment = load_experiment(path)

    assert experiment.output_dir == tmp_path / "output"
    assert experiment.cache_dir == tmp_path / "cache"
    assert experiment.benchmark.checkout == tmp_path / "checkout"
    assert experiment.rubric.mode == "prospective"
    assert experiment.designer.rounds == 2
    assert experiment.task_agent.model == "gpt-5.6-luna"
    assert experiment.audit.primary_rule == "any_detect"


def test_cached_judge_preserves_prompt_and_marks_shared_prefix() -> None:
    template = (
        "Task: {task_description}\nOutput: {agent_output}\n"
        "Criterion: {criterion_title}\n{match_criteria}\n"
        '{{"verdict":"pass","reasoning":"why"}}'
    )
    prefix, suffix = split_cached_prompt(
        template,
        task_description="Review",
        agent_output="Memo",
        criterion_title="Correct advice",
        match_criteria="PASS when correct.",
    )
    calls: list[dict[str, object]] = []

    class Messages:
        def create(self, **arguments: object) -> object:
            calls.append(arguments)
            return SimpleNamespace(
                usage=SimpleNamespace(
                    input_tokens=40,
                    cache_creation_input_tokens=1_000,
                    cache_read_input_tokens=0,
                    output_tokens=12,
                ),
                stop_reason="end_turn",
                content=[SimpleNamespace(
                    type="text",
                    text='{"verdict":"pass","reasoning":"Supported."}',
                )],
            )

    verdict, reasoning, usage = CachedAnthropicJudge(
        "claude-sonnet-4-6",
        SimpleNamespace(messages=Messages()),
    ).evaluate(prefix, suffix)

    assert prefix + suffix == template.format(
        task_description="Review",
        agent_output="Memo",
        criterion_title="Correct advice",
        match_criteria="PASS when correct.",
    )
    content = calls[0]["messages"][0]["content"]  # type: ignore[index]
    assert content[0]["text"] == prefix
    assert content[0]["cache_control"] == {"type": "ephemeral"}
    assert content[1] == {"type": "text", "text": suffix}
    assert verdict == "pass"
    assert reasoning == "Supported."
    assert usage == JudgeUsage(
        requests=1,
        input_tokens=40,
        cache_creation_input_tokens=1_000,
        cache_read_input_tokens=0,
        output_tokens=12,
    )


def test_cached_scoring_warms_each_output_scope_before_parallel_calls() -> None:
    criteria = [
        {
            "id": f"C-{index:03d}",
            "title": f"Check {index}",
            "match_criteria": "PASS when supported.",
            "deliverables": ["memo.md"],
        }
        for index in range(1, 6)
    ]
    calls: list[tuple[str, str]] = []

    class Judge:
        def evaluate(self, prefix: str, suffix: str) -> tuple[str, str, JudgeUsage]:
            calls.append((prefix, suffix))
            return "pass", "Supported.", JudgeUsage(requests=1)

    results, usage = score_criteria(
        criteria,
        task_description="Review",
        output_for=lambda scope: "Memo" if scope == (("memo.md",), False) else "",
        prompt_template=(
            "Task {task_description}\nOutput {agent_output}\n"
            "Criterion {criterion_title}\n{match_criteria}"
        ),
        judge=Judge(),  # type: ignore[arg-type]
        parallel=3,
    )

    assert len(calls) == 5
    assert "Check 1" in calls[0][1]
    assert len({prefix for prefix, _ in calls}) == 1
    assert [result.id for result in results] == [f"C-{index:03d}" for index in range(1, 6)]
    assert usage.requests == 5


def test_current_harvey_score_rejects_uncached_usage_artifact() -> None:
    old = _score()
    del old["judge_usage"]

    with pytest.raises(ValueError, match="invalid fields"):
        validate_harvey_score(old, "Harvey score")


def test_static_harvey_experiment_rejects_proposer(tmp_path: Path) -> None:
    path = tmp_path / "experiment.yaml"
    text = _config_text(tmp_path, mode="static").replace(
        "  max_changes_per_task: 3",
        "  proposer_model: gpt-5.6-sol\n  max_changes_per_task: 3",
    )
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="must not configure a proposer"):
        load_experiment(path)


def test_harvey_experiment_rejects_duplicate_yaml_keys(tmp_path: Path) -> None:
    path = tmp_path / "experiment.yaml"
    text = _config_text(tmp_path).replace(
        "audit:\n  models: [gpt-5.6-sol]\n",
        "audit:\n"
        "  models: [gpt-5.6-sol]\n"
        "  models: [claude-opus-4-8]\n",
    )
    path.write_text(text, encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate YAML key: models"):
        load_experiment(path)


def test_task_rubric_proposer_preserves_ids_and_deliverables(tmp_path: Path) -> None:
    task_file = tmp_path / "task.json"
    task_file.write_text(json.dumps(_task()), encoding="utf-8")

    def generate(model: str, request: object) -> GenerationResult:
        assert model == "gpt-5.6-sol"
        text = json.dumps(
            {
                "summary": "Make the issue test more precise.",
                "changes": [
                    {
                        "criterion_id": "C-001",
                        "title": "Identifies the controlling issue",
                        "match_criteria": "PASS if the memo identifies the controlling issue and cites the clause. FAIL otherwise.",
                        "reason": "The old test accepted an unsupported label.",
                    }
                ],
            }
        )
        return GenerationResult(
            text=text,
            provider="openai",
            requested_model=model,
            effective_model=model,
            response_id="response-test",
            request_parameters=request_parameters_for_model(model),
        )

    result = TaskRubricProposer(
        "gpt-5.6-sol",
        max_changes=2,
        max_output_tokens=4096,
        generate_response=generate,  # type: ignore[arg-type]
    ).propose(task_file, {"score": 0.5})

    criteria = result.task["criteria"]
    assert isinstance(criteria, list)
    assert criteria[0]["id"] == "C-001"
    assert criteria[0]["deliverables"] == ["memo.md"]
    assert criteria[0]["title"] == "Identifies the controlling issue"
    assert criteria[1] == _task()["criteria"][1]


def test_current_ranking_keeps_nondominated_candidates_without_selecting_parent() -> None:
    evaluations = {
        "h0000": CandidateEvaluation("h0000", {}, 0.8, 0.5),
        "h0001": CandidateEvaluation("h0001", {}, 0.7, 0.8),
        "h0002": CandidateEvaluation("h0002", {}, 0.6, 0.4),
    }

    ranking = build_ranking("r0002", evaluations)

    assert ranking["pareto_frontier"] == ["h0000", "h0001"]
    assert [item["candidate_id"] for item in ranking["ranking"]] == [
        "h0000",
        "h0001",
        "h0002",
    ]
    assert "selected_parent" not in ranking


def test_tree_hash_rejects_symbolic_links(tmp_path: Path) -> None:
    root = tmp_path / "tree"
    root.mkdir()
    (root / "value.txt").write_text("value", encoding="utf-8")
    (root / "link").symlink_to(root / "value.txt")

    with pytest.raises(ValueError, match="link or special file"):
        tree_sha256(root)


def test_harvey_run_seal_binds_artifacts_and_makes_tree_read_only(
    tmp_path: Path,
) -> None:
    root = tmp_path / "output"
    nested = root / "audits"
    nested.mkdir(parents=True)
    artifact = nested / "summary.json"
    artifact.write_text('{"status":"completed"}\n', encoding="utf-8")
    source = tmp_path / "experiment.yaml"
    source.write_text("experiment\n", encoding="utf-8")
    experiment = type("Experiment", (), {
        "experiment_id": "harvey-test",
        "output_dir": root,
        "source": source,
    })()

    try:
        seal = seal_harvey_run(experiment)  # type: ignore[arg-type]

        assert seal["artifact_count"] == 1
        assert seal["artifact_bytes"] == artifact.stat().st_size
        assert validate_harvey_run_seal(experiment) == seal  # type: ignore[arg-type]
        assert not root.stat().st_mode & 0o222
        assert not artifact.stat().st_mode & 0o222
        assert not (root / SEAL_NAME).stat().st_mode & 0o222

        artifact.chmod(artifact.stat().st_mode | 0o200)
        assert seal_harvey_run(experiment) == seal  # type: ignore[arg-type]
        assert not artifact.stat().st_mode & 0o222

        source.write_text("changed experiment\n", encoding="utf-8")
        with pytest.raises(ValueError, match="invalid fields"):
            validate_harvey_run_seal(experiment)  # type: ignore[arg-type]
        source.write_text("experiment\n", encoding="utf-8")

        root.chmod(0o700)
        nested.chmod(0o700)
        artifact.chmod(0o600)
        artifact.write_text('{"status":"changed"}\n', encoding="utf-8")
        with pytest.raises(ValueError, match="does not match its artifacts"):
            validate_harvey_run_seal(experiment)  # type: ignore[arg-type]
    finally:
        for path in (root, *root.rglob("*")):
            path.chmod(path.stat().st_mode | 0o700)


def test_harvey_run_seal_rejects_symbolic_links(tmp_path: Path) -> None:
    root = tmp_path / "output"
    root.mkdir()
    artifact = root / "summary.json"
    artifact.write_text("{}\n", encoding="utf-8")
    (root / "alias.json").symlink_to(artifact)
    source = tmp_path / "experiment.yaml"
    source.write_text("experiment\n", encoding="utf-8")
    experiment = type("Experiment", (), {
        "experiment_id": "harvey-test",
        "output_dir": root,
        "source": source,
    })()

    with pytest.raises(ValueError, match="link or special file"):
        seal_harvey_run(experiment)  # type: ignore[arg-type]


def test_designer_parent_contract_uses_candidate_id_without_history_prefix(
    tmp_path: Path,
) -> None:
    assert "such as `h0000`" in DESIGNER_PROMPT
    assert "do not include the `history/` prefix" in DESIGNER_PROMPT
    workspace = tmp_path / "workspace"
    parent = tmp_path / "parent"
    harness = workspace / "candidate" / "harness"
    for root in (parent, harness):
        root.mkdir(parents=True)
        for name in ("run.py", "system_prompt.md", "agent_loop.py", "tools.py"):
            (root / name).write_text(name, encoding="utf-8")
    (harness / "run.py").write_text("changed", encoding="utf-8")
    (workspace / "proposal.json").write_text(
        json.dumps(
            {
                "parent_harness": "history/h0000",
                "hypothesis": "Improve review.",
                "mechanism": "Add an audit.",
                "expected_effect": "Find omissions.",
                "risks": ["More tokens."],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="without a history/ prefix"):
        CodexHarnessDesigner._validate_artifacts(
            workspace, {"h0000": parent}
        )


def test_designer_retries_semantically_invalid_proposal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    node_local = tmp_path / "node-local"
    node_local.mkdir(mode=0o700)
    node_local.chmod(0o700)
    bulk = tmp_path / "bulk"
    bulk.mkdir()
    monkeypatch.setenv("TMPDIR", str(bulk))
    parent = tmp_path / "parent"
    parent.mkdir()
    for name in ("run.py", "system_prompt.md", "agent_loop.py", "tools.py"):
        (parent / name).write_text(name, encoding="utf-8")
    current = tmp_path / "current"
    current.mkdir()
    (current / "ranking.json").write_text("{}", encoding="utf-8")
    workspace = tmp_path / "workspace"
    designer = CodexHarnessDesigner(
        HarnessDesigner("gpt-5.6-sol", 1, "high", "priority", 60, 1),
        runtime_root=node_local,
    )
    input_hash = designer.prepare_workspace(
        workspace,
        candidate_harnesses={"h0000": parent},
        canonical_evaluations={},
        current_dir=current,
    )
    prompts: list[str] = []
    state_paths: list[Path] = []

    class FakeRunner:
        def __init__(self, config, *, prompt: str, output_errors) -> None:
            prompts.append(prompt)
            assert output_errors.names == ("proposal.json",)

        def ensure_executable(self) -> None:
            return None

        def stream(self, paths) -> int:
            assert paths.state_dir is not None
            state_paths.append(paths.state_dir)
            assert paths.state_dir.parent == node_local
            assert paths.state_dir.stat().st_mode & 0o777 == 0o700
            assert not paths.state_dir.is_symlink()
            state = paths.state_dir / "codex"
            state.mkdir(parents=True, exist_ok=True)
            (state / "auth.json").write_text("test credential", encoding="utf-8")
            harness = workspace / "candidate" / "harness"
            if not harness.exists():
                shutil.copytree(parent, harness)
                (harness / "run.py").write_text("changed", encoding="utf-8")
            proposal = {
                "parent_harness": "history/h0000" if len(prompts) == 1 else "h0000",
                "hypothesis": "Improve review.",
                "mechanism": "Add an audit.",
                "expected_effect": "Find omissions.",
                "risks": ["More tokens."],
            }
            (workspace / "proposal.json").write_text(
                json.dumps(proposal), encoding="utf-8"
            )
            paths.stream_path.write_text(
                '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n',
                encoding="utf-8",
            )
            return 0

        @staticmethod
        def trajectory_errors(path: Path) -> list[str]:
            return []

    monkeypatch.setattr(designer_module, "AgentRunner", FakeRunner)

    result = designer.run(
        workspace,
        tmp_path / "agent",
        expected_input_sha256=input_hash,
        candidate_harnesses={"h0000": parent},
    )

    assert result.parent_id == "h0000"
    assert len(prompts) == 2
    assert "without a history/ prefix" in prompts[1]
    assert all(path.parent == node_local for path in state_paths)
    assert all(not path.exists() for path in state_paths)
    assert not any(bulk.iterdir())


def test_designer_removes_node_local_state_after_runner_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    node_local = tmp_path / "node-local"
    node_local.mkdir(mode=0o700)
    node_local.chmod(0o700)
    state_paths: list[Path] = []

    class FailingRunner:
        def __init__(self, config, *, prompt: str, output_errors) -> None:
            return None

        def ensure_executable(self) -> None:
            return None

        def stream(self, paths) -> int:
            assert paths.state_dir is not None
            state_paths.append(paths.state_dir)
            credential = paths.state_dir / "codex" / "auth.json"
            credential.parent.mkdir()
            credential.write_text("test credential", encoding="utf-8")
            raise RuntimeError("provider failed")

    monkeypatch.setattr(designer_module, "AgentRunner", FailingRunner)
    designer = CodexHarnessDesigner(
        HarnessDesigner("gpt-5.6-sol", 1, "high", "priority", 60, 0),
        runtime_root=node_local,
    )

    with pytest.raises(RuntimeError, match="provider failed"):
        designer.run(
            tmp_path / "workspace",
            tmp_path / "agent",
            expected_input_sha256="unused",
            candidate_harnesses={},
        )

    assert len(state_paths) == 1
    assert not state_paths[0].exists()
    assert not any(node_local.iterdir())


def test_harvey_requires_one_explicit_private_runtime_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    legacy = tmp_path / "legacy"
    legacy.mkdir(mode=0o700)
    legacy.chmod(0o700)
    monkeypatch.setenv("SLURM_TMPDIR", str(legacy))
    monkeypatch.delenv("HARVEY_RUNTIME_ROOT", raising=False)
    with pytest.raises(RuntimeError, match="requires HARVEY_RUNTIME_ROOT"):
        runtime_root_from_environment()

    monkeypatch.setenv("HARVEY_RUNTIME_ROOT", "relative")
    with pytest.raises(RuntimeError, match="must be absolute"):
        runtime_root_from_environment()

    created = tmp_path / "created"
    monkeypatch.setenv("HARVEY_RUNTIME_ROOT", str(created))
    assert runtime_root_from_environment() == created
    assert created.stat().st_mode & 0o777 == 0o700

    public = tmp_path / "public"
    public.mkdir(mode=0o700)
    public.chmod(0o755)
    monkeypatch.setenv("HARVEY_RUNTIME_ROOT", str(public))
    with pytest.raises(RuntimeError, match="mode 0700"):
        runtime_root_from_environment()

    private = tmp_path / "private"
    private.mkdir(mode=0o700)
    private.chmod(0o700)
    alias = tmp_path / "alias"
    alias.symlink_to(private, target_is_directory=True)
    monkeypatch.setenv("HARVEY_RUNTIME_ROOT", str(alias))
    with pytest.raises(RuntimeError, match="regular directory"):
        runtime_root_from_environment()


def test_designer_does_not_read_runtime_root_from_the_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "configured"
    configured.mkdir(mode=0o700)
    configured.chmod(0o700)
    monkeypatch.delenv("SLURM_TMPDIR", raising=False)
    monkeypatch.delenv("HARVEY_RUNTIME_ROOT", raising=False)

    designer = CodexHarnessDesigner(
        HarnessDesigner("gpt-5.6-sol", 1, "high", "priority", 60, 0),
        runtime_root=configured,
    )

    assert designer.runtime_root == configured


def test_designer_rejects_agent_state_outside_node_local_root(
    tmp_path: Path,
) -> None:
    node_local = tmp_path / "node-local"
    node_local.mkdir(mode=0o700)
    node_local.chmod(0o700)
    escaped = tmp_path / "escaped"
    escaped.mkdir(mode=0o700)
    escaped.chmod(0o700)

    with pytest.raises(RuntimeError, match="escaped the runtime root"):
        CodexHarnessDesigner._validate_agent_state(
            escaped,
            node_local,
            require_private_mode=True,
        )


def test_designer_rejects_non_private_or_linked_agent_state(
    tmp_path: Path,
) -> None:
    node_local = tmp_path / "node-local"
    node_local.mkdir(mode=0o700)
    node_local.chmod(0o700)
    state = node_local / "state"
    state.mkdir(mode=0o700)
    state.chmod(0o755)

    with pytest.raises(RuntimeError, match="mode 0700"):
        CodexHarnessDesigner._validate_agent_state(
            state,
            node_local,
            require_private_mode=True,
        )

    state.chmod(0o700)
    alias = node_local / "alias"
    alias.symlink_to(state, target_is_directory=True)
    with pytest.raises(RuntimeError, match="regular directory"):
        CodexHarnessDesigner._validate_agent_state(
            alias,
            node_local,
            require_private_mode=True,
        )


def test_podman_environment_uses_local_storage_and_shared_cache(
    tmp_path: Path,
) -> None:
    commands = tmp_path / "commands"
    commands.mkdir()
    podman = commands / "podman"
    podman.write_text(
        "#!/bin/sh\nprintf '%s\\n' \"$HOME\" \"$XDG_CONFIG_HOME\" \"$@\"\n",
        encoding="utf-8",
    )
    podman.chmod(0o700)
    subuid = tmp_path / "subuid"
    subgid = tmp_path / "subgid"
    subuid.write_text("other:100000:65536\n", encoding="utf-8")
    subgid.write_text("other:100000:65536\n", encoding="utf-8")

    environment = configured_podman_environment(
        {
            "PATH": str(commands),
            "XDG_RUNTIME_DIR": "/run/user/does-not-exist",
            "SLURM_TMPDIR": "/legacy",
        },
        cache_root=tmp_path / "shared",
        runtime_root=tmp_path / "worker",
        uid=1234,
        username="researcher",
        subuid_path=subuid,
        subgid_path=subgid,
        cgroup_limits_available=False,
    )
    environment = configured_podman_environment(
        environment,
        cache_root=tmp_path / "shared",
        runtime_root=tmp_path / "worker",
        uid=1234,
        username="researcher",
        subuid_path=subuid,
        subgid_path=subgid,
        cgroup_limits_available=False,
    )

    assert environment["XDG_RUNTIME_DIR"].endswith(
        "rubric-gen-podman-1234/runtime"
    )
    assert environment["XDG_DATA_HOME"].endswith("rubric-gen-podman-1234/data")
    assert environment["UV_CACHE_DIR"] == str(
        tmp_path / "shared" / "user-1234" / "uv"
    )
    assert environment["TMPDIR"] == str(tmp_path / "worker" / "tmp")
    assert "SLURM_TMPDIR" not in environment
    storage = Path(environment["CONTAINERS_STORAGE_CONF"])
    assert 'ignore_chown_errors = "true"' in storage.read_text(encoding="utf-8")
    assert str(tmp_path / "worker") in storage.read_text(encoding="utf-8")
    assert storage.stat().st_mode & 0o777 == 0o600
    home = Path(environment["XDG_CONFIG_HOME"]).parent
    policy = home / ".config" / "containers" / "policy.json"
    assert json.loads(policy.read_text(encoding="utf-8")) == {
        "default": [{"type": "insecureAcceptAnything"}]
    }
    wrapper = Path(environment["PATH"].split(os.pathsep, 1)[0]) / "podman"
    wrapper_text = wrapper.read_text(encoding="utf-8")
    assert f"export HOME={home}" in wrapper_text
    assert f"export XDG_CONFIG_HOME={home / '.config'}" in wrapper_text
    assert f"--signature-policy={policy}" in wrapper_text
    assert f'exec {podman} "$@"' in wrapper_text
    invocation = subprocess.run(
        [wrapper, "build", "-t", "sandbox", "."],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert invocation == [
        str(home),
        str(home / ".config"),
        "build",
        f"--signature-policy={policy}",
        "-t",
        "sandbox",
        ".",
    ]
    cached_pull = subprocess.run(
        [wrapper, "pull", "registry.example/sandbox:latest"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert cached_pull == [
        str(home),
        str(home / ".config"),
        "image",
        "exists",
        "registry.example/sandbox:latest",
    ]
    limited_run = subprocess.run(
        [
            wrapper,
            "run",
            "--cpus=2",
            "--memory=2g",
            "--pids-limit=256",
            "sandbox",
            "true",
        ],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.splitlines()
    assert limited_run == [
        str(home),
        str(home / ".config"),
        "run",
        "sandbox",
        "true",
    ]


def test_shared_image_cache_saves_and_restores_oci_archive(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    image = "lab-sandbox:latest"
    image_id = "sha256:harvey-image"
    local = True
    calls: list[list[str]] = []

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        nonlocal local
        calls.append(command)
        if command[1:3] == ["image", "inspect"]:
            return subprocess.CompletedProcess(
                command,
                0 if local else 1,
                image_id + "\n" if local else "",
                "",
            )
        if command[1] == "save":
            output = Path(command[command.index("--output") + 1])
            output.write_bytes(b"oci archive")
            return subprocess.CompletedProcess(command, 0, "", "")
        if command[1] == "load":
            local = True
            return subprocess.CompletedProcess(command, 0, "loaded", "")
        raise AssertionError(command)

    monkeypatch.setattr("rubric_gen.benchmarks.harvey_lab.podman.subprocess.run", run)
    cache_root = tmp_path / "shared"
    environment = {"PATH": "/usr/bin"}

    archive = cache_image(
        environment,
        cache_root=cache_root,
        image=image,
        uid=1234,
    )
    assert archive.read_bytes() == b"oci archive"
    assert sum(command[1] == "save" for command in calls) == 1

    local = False
    assert restore_cached_image(
        environment,
        cache_root=cache_root,
        image=image,
        uid=1234,
    )
    assert sum(command[1] == "load" for command in calls) == 1
    assert Path(calls[-2][calls[-2].index("--input") + 1]) == archive


def test_shared_image_cache_miss_does_not_pull(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert command[1:3] == ["image", "inspect"]
        return subprocess.CompletedProcess(command, 1, "", "missing")

    monkeypatch.setattr("rubric_gen.benchmarks.harvey_lab.podman.subprocess.run", run)

    assert not restore_cached_image(
        {"PATH": "/usr/bin"},
        cache_root=tmp_path / "shared",
        image="lab-sandbox:latest",
        uid=1234,
    )


def test_podman_environment_does_not_squash_users_when_subids_exist(
    tmp_path: Path,
) -> None:
    subuid = tmp_path / "subuid"
    subgid = tmp_path / "subgid"
    subuid.write_text("researcher:100000:65536\n", encoding="utf-8")
    subgid.write_text("1234:200000:65536\n", encoding="utf-8")

    environment = configured_podman_environment(
        {},
        cache_root=tmp_path / "shared",
        runtime_root=tmp_path / "worker",
        uid=1234,
        username="researcher",
        subuid_path=subuid,
        subgid_path=subgid,
    )

    assert "CONTAINERS_STORAGE_CONF" not in environment


class _FakeEvaluator:
    def evaluate(
        self,
        identifier: str,
        harness: Path,
        task_files: dict[str, Path],
        destination: Path,
    ) -> CandidateEvaluation:
        value = 0.25 if identifier == "h0000" else 0.75
        scores = {}
        for task_id in task_files:
            score = _score(int(value * 4), 4, run_id=identifier, task=task_id)
            scores[task_id] = score
            result = destination / "tasks" / task_id / "result"
            (result / "output").mkdir(parents=True)
            (result / "output" / "memo.md").write_text("memo", encoding="utf-8")
            (result / "scores.json").write_text(json.dumps(score), encoding="utf-8")
            (result / "metrics.json").write_text("{}", encoding="utf-8")
            (result / "transcript.jsonl").write_text("{}\n", encoding="utf-8")
        evaluation = CandidateEvaluation(identifier, scores, value, 0.0)
        self._summary(destination, evaluation)
        return evaluation

    def rescore(
        self,
        identifier: str,
        source_results: dict[str, Path],
        task_files: dict[str, Path],
        destination: Path,
    ) -> CandidateEvaluation:
        scores = {
            task_id: _score(2, 4, run_id=identifier, task=task_id)
            for task_id in task_files
        }
        evaluation = CandidateEvaluation(identifier, scores, 0.5, 0.0)
        self._summary(destination, evaluation)
        return evaluation

    @staticmethod
    def _summary(destination: Path, evaluation: CandidateEvaluation) -> None:
        destination.mkdir(parents=True, exist_ok=True)
        (destination / "summary.json").write_text(
            json.dumps(
                {
                    "candidate_id": evaluation.candidate_id,
                    "tasks": evaluation.task_scores,
                    "mean_criterion_pass": evaluation.mean_criterion_pass,
                    "mean_all_pass": evaluation.mean_all_pass,
                }
            ),
            encoding="utf-8",
        )


class _FakeDesigner:
    def prepare_workspace(
        self,
        workspace: Path,
        *,
        candidate_harnesses: dict[str, Path],
        canonical_evaluations: dict[str, Path],
        current_dir: Path,
    ) -> str:
        workspace.mkdir(parents=True)
        (workspace / "instruction.md").write_text("instruction", encoding="utf-8")
        (workspace / "current").mkdir()
        shutil.copy2(current_dir / "ranking.json", workspace / "current" / "ranking.json")
        self.parent = candidate_harnesses["h0000"]
        return "inputs"

    def run(
        self,
        workspace: Path,
        run_dir: Path,
        *,
        expected_input_sha256: str,
        candidate_harnesses: dict[str, Path],
    ) -> DesignedCandidate:
        harness = workspace / "candidate" / "harness"
        shutil.copytree(self.parent, harness)
        for path in [harness, *harness.rglob("*")]:
            path.chmod(path.stat().st_mode | 0o700)
        (harness / "system_prompt.md").write_text("changed", encoding="utf-8")
        run_dir.mkdir(parents=True)
        trajectory = run_dir / "trajectory.stream.jsonl"
        trajectory.write_text("{}\n", encoding="utf-8")
        proposal = {
            "parent_harness": "h0000",
            "hypothesis": "A clearer prompt helps.",
            "mechanism": "Change the system prompt.",
            "expected_effect": "More complete work.",
            "risks": ["The prompt can be too long."],
        }
        return DesignedCandidate(
            "h0000", harness, proposal, tree_sha256(harness), trajectory, {}
        )


def test_controller_validates_runtime_root_before_initialization(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runtime_root = tmp_path / "runtime"
    runtime_root.mkdir(mode=0o700)
    runtime_root.chmod(0o755)
    controller = object.__new__(HarveyEvolutionController)
    controller.runtime_root = runtime_root
    initialized = False

    def initialize(*, resume: bool) -> None:
        nonlocal initialized
        initialized = True

    monkeypatch.setattr(controller, "_initialize", initialize)

    with pytest.raises(RuntimeError, match="mode 0700"):
        controller.run()
    assert not initialized


def _fake_checkout(root: Path) -> str:
    for name, content in {
        "harness/run.py": "# run\n",
        "harness/system_prompt.md": "stock\n",
        "harness/agent_loop.py": "# loop\n",
        "harness/tools.py": "# tools\n",
        "evaluation/run_eval.py": "# eval\n",
        "sandbox/sandbox.py": "# sandbox\n",
        "utils/__init__.py": "",
        "pyproject.toml": "[project]\nname='fake'\nversion='0.0.0'\n",
        "tasks/area/task/task.json": json.dumps(_task()),
        "tasks/area/task/documents/source.txt": "source",
    }.items():
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.email", "test@example.com"], check=True)
    subprocess.run(["git", "-C", str(root), "config", "user.name", "Test"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(["git", "-C", str(root), "commit", "-qm", "fixture"], check=True)
    return subprocess.run(
        ["git", "-C", str(root), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()


def test_checkout_validation_only_checks_selected_benchmark_inputs(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "harvey"
    _fake_checkout(checkout)
    unrelated = checkout / "README.md"
    unrelated.write_text("tracked note", encoding="utf-8")
    subprocess.run(["git", "-C", str(checkout), "add", "README.md"], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "commit", "-qm", "tracked note"],
        check=True,
    )
    revision = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    unrelated.write_text("changed tracked note", encoding="utf-8")

    validate_checkout(checkout, revision, ("area/task",))

    untracked = checkout / "harness" / "local.py"
    untracked.write_text("# local input\n", encoding="utf-8")
    with pytest.raises(ValueError, match="untracked input files"):
        validate_checkout(checkout, revision, ("area/task",))
    untracked.unlink()

    ignored = checkout / "harness" / "ignored.py"
    exclude = checkout / ".git" / "info" / "exclude"
    exclude.write_text(exclude.read_text(encoding="utf-8") + "harness/ignored.py\n")
    ignored.write_text("# ignored local input\n", encoding="utf-8")
    with pytest.raises(ValueError, match="untracked input files"):
        validate_checkout(checkout, revision, ("area/task",))
    ignored.unlink()

    (checkout / "tasks" / "area" / "task" / "task.json").write_text(
        json.dumps({**_task(), "title": "Changed"}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="tracked changes"):
        validate_checkout(checkout, revision, ("area/task",))


def test_controller_runs_linear_round_with_free_parent_record_and_resumes(
    tmp_path: Path,
) -> None:
    checkout = tmp_path / "harvey"
    revision = _fake_checkout(checkout)
    source = tmp_path / "experiment.yaml"
    source.write_text("fixture", encoding="utf-8")
    experiment = HarveyExperiment(
        source=source,
        experiment_id="harvey-test",
        output_dir=tmp_path / "output",
        cache_dir=tmp_path / "cache",
        benchmark=HarveyBenchmark(checkout, revision, ("area/task",), ()),
        task_agent=TaskAgent("gpt-5.5", 10, 0.0, 10, None, "image", ("KEY",)),
        judge=HarveyJudge("judge", 1, ("JUDGE_KEY",)),
        designer=HarnessDesigner("codex", 1, None, None, 10, 0),
        rubric=RubricEvolution("static", None, 2, 4096),
        audit=RewardHackingAudit(("judge",), 1, "majority"),
    )
    controller = HarveyEvolutionController(
        experiment,
        runtime_root=tmp_path / "runtime",
        evaluator=_FakeEvaluator(),
        designer=_FakeDesigner(),
    )

    assert controller.run() == 0
    assert controller.run(resume=True) == 0

    candidate = json.loads(
        (experiment.output_dir / "candidates" / "h0001" / "candidate.json").read_text()
    )
    ranking = json.loads(
        (experiment.output_dir / "rounds" / "r0001" / "current" / "ranking.json").read_text()
    )
    assert candidate["parent_harness"] == "h0000"
    assert [item["candidate_id"] for item in ranking["ranking"]] == ["h0001", "h0000"]
    assert run_quality_audit(experiment, evaluator=_FakeEvaluator()) == 0  # type: ignore[arg-type]
    quality = json.loads(
        (experiment.output_dir / "audits" / "quality-transfer" / "summary.json").read_text()
    )
    assert quality["candidates"]["h0001"]["active_minus_original"] == 0.25
    cases = prepare_reward_hacking_cases(experiment)
    assert [path.name for path in cases] == ["h0001"]
    transcript = json.loads((cases[0] / "transcript.json").read_text())
    assert any(
        message.get("name") == "accepted_harness_patch"
        for message in transcript["messages"]
    )


def test_production_evaluator_uses_runtime_modules_and_rescores_read_only_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "harvey"
    revision = _fake_checkout(checkout)
    source = tmp_path / "experiment.yaml"
    source.write_text("fixture", encoding="utf-8")
    experiment = HarveyExperiment(
        source=source,
        experiment_id="harvey-test",
        output_dir=tmp_path / "output",
        cache_dir=tmp_path / "cache",
        benchmark=HarveyBenchmark(checkout, revision, ("area/task",), ()),
        task_agent=TaskAgent("gpt-5.5", 10, 0.0, 10, None, "image", ("KEY",)),
        judge=HarveyJudge("judge", 1, ("JUDGE_KEY",)),
        designer=HarnessDesigner("codex", 1, None, None, 10, 0),
        rubric=RubricEvolution("static", None, 2, 4096),
        audit=RewardHackingAudit(("judge",), 1, "majority"),
    )
    calls: list[list[str]] = []

    def execute(
        command: list[str],
        runtime: Path,
        log: Path,
        credential_names: tuple[str, ...],
        label: str,
    ) -> None:
        calls.append(command)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(label, encoding="utf-8")
        run_id = command[command.index("--run-id") + 1]
        result = runtime / "results" / run_id
        result.mkdir(parents=True, exist_ok=True)
        if label == "task agent":
            assert command[4:7] == ["python", "-m", "harness.run"]
            (result / "output").mkdir()
            (result / "output" / "memo.md").write_text("memo", encoding="utf-8")
            (result / "metrics.json").write_text("{}", encoding="utf-8")
            (result / "transcript.jsonl").write_text("{}\n", encoding="utf-8")
        else:
            assert command[4] == "python"
            assert Path(command[5]).name == "cached_judge.py"
            (result / "scores.json").write_text(
                json.dumps(_score(run_id=run_id)),
                encoding="utf-8",
            )

    monkeypatch.setattr(HarveyEvaluator, "_execute", staticmethod(execute))
    evaluator = HarveyEvaluator(
        experiment,
        runtime_root=tmp_path / "runtime",
        uv_executable="uv-test",
    )
    active = {"area/task": checkout / "tasks" / "area" / "task" / "task.json"}
    canonical = tmp_path / "canonical"

    result = evaluator.evaluate("h0000", checkout / "harness", active, canonical)
    crossed = evaluator.rescore(
        "h0000",
        {"area/task": canonical / "tasks" / "area" / "task" / "result"},
        active,
        tmp_path / "crossed",
    )

    assert result.mean_criterion_pass == 0.5
    assert crossed.mean_criterion_pass == 0.5
    assert len(calls) == 3


def test_production_evaluator_resumes_canonical_and_crossed_task_checkpoints(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "harvey"
    _fake_checkout(checkout)
    second = checkout / "tasks" / "area" / "task-2"
    shutil.copytree(checkout / "tasks" / "area" / "task", second)
    subprocess.run(["git", "-C", str(checkout), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "commit", "-qm", "second task"],
        check=True,
    )
    revision = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    source = tmp_path / "experiment.yaml"
    source.write_text("fixture", encoding="utf-8")
    tasks = ("area/task", "area/task-2")
    experiment = HarveyExperiment(
        source=source,
        experiment_id="harvey-test",
        output_dir=tmp_path / "output",
        cache_dir=tmp_path / "cache",
        benchmark=HarveyBenchmark(checkout, revision, tasks, ()),
        task_agent=TaskAgent("gpt-5.5", 10, 0.0, 10, None, "image", ("KEY",)),
        judge=HarveyJudge("judge", 1, ("JUDGE_KEY",)),
        designer=HarnessDesigner("codex", 1, None, None, 10, 0),
        rubric=RubricEvolution("static", None, 2, 4096),
        audit=RewardHackingAudit(("judge",), 1, "majority"),
    )
    call_counts: dict[tuple[str, str], int] = {}
    lock = threading.Lock()

    def execute(
        command: list[str],
        runtime: Path,
        log: Path,
        credential_names: tuple[str, ...],
        label: str,
    ) -> None:
        task_id = command[command.index("--task") + 1]
        run_id = command[command.index("--run-id") + 1]
        with lock:
            key = (label, task_id)
            call_counts[key] = call_counts.get(key, 0) + 1
            call_count = call_counts[key]
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(label, encoding="utf-8")
        result = runtime / "results" / run_id
        if label == "task agent":
            result.mkdir(parents=True)
            (result / "output").mkdir()
            (result / "output" / "memo.md").write_text("memo", encoding="utf-8")
            (result / "metrics.json").write_text("{}", encoding="utf-8")
            (result / "transcript.jsonl").write_text("{}\n", encoding="utf-8")
            return
        if task_id == "area/task" and call_count == 1:
            log.write_text("deterministic judge failure", encoding="utf-8")
            raise RuntimeError("judge failed")
        (result / "scores.json").write_text(
            json.dumps(_score(run_id=run_id, task=task_id)),
            encoding="utf-8",
        )

    monkeypatch.setattr(HarveyEvaluator, "_execute", staticmethod(execute))
    evaluator = HarveyEvaluator(
        experiment,
        runtime_root=tmp_path / "runtime",
        uv_executable="uv-test",
        max_concurrency=2,
    )
    active = {
        task: checkout / "tasks" / task / "task.json"
        for task in tasks
    }
    canonical = tmp_path / "canonical"

    with pytest.raises(RuntimeError, match="judge failed"):
        evaluator.evaluate("h0000", checkout / "harness", active, canonical)

    stage = tmp_path / ".canonical.attempt-001"
    assert (stage / "tasks" / "area" / "task" / "agent-result").is_dir()
    assert (stage / "tasks" / "area" / "task-2" / "result").is_dir()

    evaluation = evaluator.evaluate("h0000", checkout / "harness", active, canonical)

    assert set(evaluation.task_scores) == set(tasks)
    assert call_counts == {
        ("task agent", "area/task"): 1,
        ("task agent", "area/task-2"): 1,
        ("Harvey judge", "area/task"): 2,
        ("Harvey judge", "area/task-2"): 1,
    }
    assert not stage.exists()
    assert not (canonical / "tasks" / "area" / "task" / "agent-result").exists()
    assert (
        canonical / "tasks" / "area" / "task" / "judge.failed-001.log"
    ).read_text(encoding="utf-8") == "deterministic judge failure"

    crossed = tmp_path / "crossed"
    crossed_stage = tmp_path / ".crossed.attempt-001"
    saved_task = crossed_stage / "tasks" / "area" / "task"
    saved_task.mkdir(parents=True)
    (saved_task / "scores.json").write_text(
        json.dumps(_score(2, 2)),
        encoding="utf-8",
    )

    rescored = evaluator.rescore(
        "h0000",
        {
            task: canonical / "tasks" / task / "result"
            for task in tasks
        },
        active,
        crossed,
    )

    assert rescored.task_scores["area/task"]["n_passed"] == 2
    assert call_counts[("Harvey judge", "area/task")] == 2
    assert call_counts[("Harvey judge", "area/task-2")] == 2
    assert not crossed_stage.exists()


@pytest.mark.parametrize(
    "transient_message",
    [
        "Grammar compilation timed out.",
        (
            "Judge response truncated (stop_reason=max_tokens, "
            "input_tokens=14617, max_tokens=16384)."
        ),
    ],
)
def test_harvey_judge_retries_configured_transient_failures(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    transient_message: str,
) -> None:
    source = tmp_path / "experiment.yaml"
    source.write_text("fixture", encoding="utf-8")
    experiment = HarveyExperiment(
        source=source,
        experiment_id="harvey-test",
        output_dir=tmp_path / "output",
        cache_dir=tmp_path / "cache",
        benchmark=HarveyBenchmark(tmp_path / "checkout", "a" * 40, ("area/task",), ()),
        task_agent=TaskAgent("agent", 10, 0.0, 10, None, "image", ("KEY",)),
        judge=HarveyJudge("judge", 1, ("JUDGE_KEY",)),
        designer=HarnessDesigner("codex", 1, None, None, 10, 0),
        rubric=RubricEvolution("static", None, 2, 4096),
        audit=RewardHackingAudit(("judge",), 1, "majority"),
    )
    calls = 0

    def execute(
        command: list[str],
        runtime: Path,
        log: Path,
        credential_names: tuple[str, ...],
        label: str,
    ) -> None:
        nonlocal calls
        calls += 1
        log.parent.mkdir(parents=True, exist_ok=True)
        if calls <= 3:
            log.write_text(transient_message, encoding="utf-8")
            raise RuntimeError("judge failed")
        log.write_text("success", encoding="utf-8")

    monkeypatch.setattr(HarveyEvaluator, "_execute", staticmethod(execute))
    evaluator = HarveyEvaluator(
        experiment,
        runtime_root=tmp_path / "runtime",
        max_retries=3,
    )
    log = tmp_path / "judge.log"

    evaluator._score_task(tmp_path, "area/task", "run", log)

    assert calls == 4
    assert log.read_text(encoding="utf-8") == "success"
    for index in range(1, 4):
        assert (tmp_path / f"judge.failed-{index:03d}.log").read_text(
            encoding="utf-8"
        ) == transient_message


def test_harvey_task_agent_retries_invalid_prompt_from_clean_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "experiment.yaml"
    source.write_text("fixture", encoding="utf-8")
    experiment = HarveyExperiment(
        source=source,
        experiment_id="harvey-test",
        output_dir=tmp_path / "output",
        cache_dir=tmp_path / "cache",
        benchmark=HarveyBenchmark(tmp_path / "checkout", "a" * 40, ("area/task",), ()),
        task_agent=TaskAgent("agent", 10, 0.0, 10, None, "image", ("KEY",)),
        judge=HarveyJudge("judge", 1, ("JUDGE_KEY",)),
        designer=HarnessDesigner("codex", 1, None, None, 10, 0),
        rubric=RubricEvolution("static", None, 2, 4096),
        audit=RewardHackingAudit(("judge",), 1, "majority"),
    )
    calls = 0
    runtime_result = tmp_path / "results" / "run"

    def execute(
        command: list[str],
        runtime: Path,
        log: Path,
        credential_names: tuple[str, ...],
        label: str,
    ) -> None:
        nonlocal calls
        calls += 1
        assert label == "task agent"
        if calls > 1:
            assert not runtime_result.exists()
        log.parent.mkdir(parents=True, exist_ok=True)
        if calls <= 3:
            runtime_result.mkdir(parents=True)
            (runtime_result / "partial.txt").write_text("partial", encoding="utf-8")
            log.write_text("'code': 'invalid_prompt'", encoding="utf-8")
            raise RuntimeError("task agent failed")
        log.write_text("success", encoding="utf-8")

    monkeypatch.setattr(HarveyEvaluator, "_execute", staticmethod(execute))
    evaluator = HarveyEvaluator(
        experiment,
        runtime_root=tmp_path / "runtime",
        max_retries=3,
    )
    log = tmp_path / "agent.log"

    evaluator._run_task(tmp_path, "area/task", "run", log)

    assert calls == 4
    assert log.read_text(encoding="utf-8") == "success"
    assert not runtime_result.exists()
    for index in range(1, 4):
        assert (tmp_path / f"agent.failed-{index:03d}.log").read_text(
            encoding="utf-8"
        ) == "'code': 'invalid_prompt'"


def test_production_evaluator_runs_independent_tasks_with_bounded_concurrency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "harvey"
    _fake_checkout(checkout)
    second = checkout / "tasks" / "area" / "task-2"
    shutil.copytree(checkout / "tasks" / "area" / "task", second)
    subprocess.run(["git", "-C", str(checkout), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "commit", "-qm", "second task"],
        check=True,
    )
    revision = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    source = tmp_path / "experiment.yaml"
    source.write_text("fixture", encoding="utf-8")
    tasks = ("area/task", "area/task-2")
    experiment = HarveyExperiment(
        source=source,
        experiment_id="harvey-test",
        output_dir=tmp_path / "output",
        cache_dir=tmp_path / "cache",
        benchmark=HarveyBenchmark(checkout, revision, tasks, ()),
        task_agent=TaskAgent("gpt-5.5", 10, 0.0, 10, None, "image", ("KEY",)),
        judge=HarveyJudge("judge", 1, ("JUDGE_KEY",)),
        designer=HarnessDesigner("codex", 1, None, None, 10, 0),
        rubric=RubricEvolution("static", None, 2, 4096),
        audit=RewardHackingAudit(("judge",), 1, "majority"),
    )
    task_agents = threading.Barrier(2, timeout=5)
    active = 0
    peak = 0
    lock = threading.Lock()

    def execute(
        command: list[str],
        runtime: Path,
        log: Path,
        credential_names: tuple[str, ...],
        label: str,
    ) -> None:
        nonlocal active, peak
        run_id = command[command.index("--run-id") + 1]
        result = runtime / "results" / run_id
        result.mkdir(parents=True, exist_ok=True)
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text(label, encoding="utf-8")
        if label == "task agent":
            with lock:
                active += 1
                peak = max(peak, active)
            task_agents.wait()
            with lock:
                active -= 1
            (result / "output").mkdir()
            (result / "output" / "memo.md").write_text("memo", encoding="utf-8")
            (result / "metrics.json").write_text("{}", encoding="utf-8")
            (result / "transcript.jsonl").write_text("{}\n", encoding="utf-8")
        else:
            (result / "scores.json").write_text(
                json.dumps(_score(run_id=run_id)),
                encoding="utf-8",
            )

    monkeypatch.setattr(HarveyEvaluator, "_execute", staticmethod(execute))
    evaluator = HarveyEvaluator(
        experiment,
        runtime_root=tmp_path / "runtime",
        uv_executable="uv-test",
        max_concurrency=2,
    )
    result = evaluator.evaluate(
        "h0000",
        checkout / "harness",
        {
            task: checkout / "tasks" / task / "task.json"
            for task in tasks
        },
        tmp_path / "canonical",
    )

    assert peak == 2
    assert set(result.task_scores) == set(tasks)


def test_production_evaluator_stops_scheduling_after_fatal_task_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    checkout = tmp_path / "harvey"
    _fake_checkout(checkout)
    for index in range(2, 5):
        shutil.copytree(
            checkout / "tasks" / "area" / "task",
            checkout / "tasks" / "area" / f"task-{index}",
        )
    subprocess.run(["git", "-C", str(checkout), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(checkout), "commit", "-qm", "four tasks"],
        check=True,
    )
    revision = subprocess.run(
        ["git", "-C", str(checkout), "rev-parse", "HEAD"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip()
    tasks = ("area/task", "area/task-2", "area/task-3", "area/task-4")
    source = tmp_path / "experiment.yaml"
    source.write_text("fixture", encoding="utf-8")
    experiment = HarveyExperiment(
        source=source,
        experiment_id="harvey-test",
        output_dir=tmp_path / "output",
        cache_dir=tmp_path / "cache",
        benchmark=HarveyBenchmark(checkout, revision, tasks, ()),
        task_agent=TaskAgent("gpt-5.5", 10, 0.0, 10, None, "image", ("KEY",)),
        judge=HarveyJudge("judge", 1, ("JUDGE_KEY",)),
        designer=HarnessDesigner("codex", 1, None, None, 10, 0),
        rubric=RubricEvolution("static", None, 2, 4096),
        audit=RewardHackingAudit(("judge",), 1, "majority"),
    )
    task_agent_calls: list[str] = []
    judge_calls: list[str] = []

    def execute(
        command: list[str],
        runtime: Path,
        log: Path,
        credential_names: tuple[str, ...],
        label: str,
    ) -> None:
        task_id = command[command.index("--task") + 1]
        run_id = command[command.index("--run-id") + 1]
        result = runtime / "results" / run_id
        result.mkdir(parents=True, exist_ok=True)
        log.parent.mkdir(parents=True, exist_ok=True)
        if label == "task agent":
            task_agent_calls.append(task_id)
            (result / "output").mkdir()
            (result / "output" / "memo.md").write_text("memo", encoding="utf-8")
            (result / "metrics.json").write_text("{}", encoding="utf-8")
            (result / "transcript.jsonl").write_text("{}\n", encoding="utf-8")
            return
        judge_calls.append(task_id)
        log.write_text("credit balance is too low", encoding="utf-8")
        raise RuntimeError("judge failed")

    monkeypatch.setattr(HarveyEvaluator, "_execute", staticmethod(execute))
    evaluator = HarveyEvaluator(
        experiment,
        runtime_root=tmp_path / "runtime",
        uv_executable="uv-test",
        max_concurrency=2,
    )

    with pytest.raises(RuntimeError, match="judge failed"):
        evaluator.evaluate(
            "h0000",
            checkout / "harness",
            {
                task: checkout / "tasks" / task / "task.json"
                for task in tasks
            },
            tmp_path / "canonical",
        )

    assert set(task_agent_calls) == set(tasks[:2])
    assert set(judge_calls) == set(tasks[:2])


def test_concurrent_task_agents_initialize_shared_podman_state_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "experiment.yaml"
    source.write_text("fixture", encoding="utf-8")
    experiment = HarveyExperiment(
        source=source,
        experiment_id="harvey-test",
        output_dir=tmp_path / "output",
        cache_dir=tmp_path / "cache",
        benchmark=HarveyBenchmark(tmp_path / "checkout", "a" * 40, ("area/task",), ()),
        task_agent=TaskAgent("agent", 10, 0.0, 10, None, "image", ("KEY",)),
        judge=HarveyJudge("judge", 1, ("JUDGE_KEY",)),
        designer=HarnessDesigner("codex", 1, None, None, 10, 0),
        rubric=RubricEvolution("static", None, 2, 4096),
        audit=RewardHackingAudit(("judge",), 1, "majority"),
    )
    evaluator = HarveyEvaluator(
        experiment,
        runtime_root=tmp_path / "runtime",
        max_concurrency=2,
    )
    monkeypatch.setenv("KEY", "test")
    setup_calls: list[str] = []
    command_barrier = threading.Barrier(2, timeout=5)

    def configure(
        source_env: dict[str, str],
        *,
        cache_root: Path,
        runtime_root: Path,
    ) -> dict[str, str]:
        setup_calls.append("configure")
        assert runtime_root == tmp_path / "runtime"
        return {**source_env, "PODMAN_TEST": str(cache_root)}

    def restore(
        environment: dict[str, str], *, cache_root: Path, image: str
    ) -> bool:
        setup_calls.append("restore")
        return True

    def cache(
        environment: dict[str, str], *, cache_root: Path, image: str
    ) -> Path:
        setup_calls.append("cache")
        return cache_root / "image.oci.tar"

    def run(command: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        assert "PODMAN_TEST" in kwargs["env"]  # type: ignore[operator]
        command_barrier.wait()
        return subprocess.CompletedProcess(command, 0, "", "")

    monkeypatch.setattr(evaluator_module, "configured_podman_environment", configure)
    monkeypatch.setattr(evaluator_module, "restore_cached_image", restore)
    monkeypatch.setattr(evaluator_module, "cache_image", cache)
    monkeypatch.setattr(evaluator_module.subprocess, "run", run)

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [
            pool.submit(
                evaluator._execute,
                ["agent", str(index)],
                tmp_path / f"runtime-{index}",
                tmp_path / f"agent-{index}.log",
                ("KEY",),
                "task agent",
            )
            for index in range(2)
        ]
        for future in futures:
            future.result()

    assert setup_calls == ["configure", "restore", "cache"]
