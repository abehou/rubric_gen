from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import types
from dataclasses import replace
from pathlib import Path

import pytest

from rubric_gen.biomnibench.cli import build_parser
from rubric_gen.biomnibench.judging.models import (
    JudgeAttempt,
    JudgeRunConfig,
    JudgeTarget,
)
from rubric_gen.biomnibench.judging.runner import BiomniBenchJudgeRunner
from rubric_gen.biomnibench.judging import runner as judge_runner_module
from rubric_gen.biomnibench.judging import scoring as rubric_scoring_module
from rubric_gen.biomnibench.judging import executor as judge_executor_module
from rubric_gen.biomnibench.judging import llm_judge as centralized_judge_module
from rubric_gen.biomnibench.judging.models import DEFAULT_JUDGE_MODEL


def test_judge_path_rewrite_handles_directory_and_child_literals(tmp_path: Path) -> None:
    tests_dir = tmp_path / "tests"
    logs_dir = tmp_path / "logs"
    source = (
        'Path("/tests")\n'
        'Path("/tests/rubric.txt")\n'
        "Path('/logs/verifier')\n"
        "Path('/logs/verifier/reward.json')\n"
    )

    rewritten = judge_executor_module.JudgeExecutor.rewrite_judge_paths(
        source, tests_dir, logs_dir
    )

    assert 'Path("/tests")' not in rewritten
    assert 'Path("/tests/rubric.txt")' not in rewritten
    assert "Path('/logs/verifier')" not in rewritten
    assert "Path('/logs/verifier/reward.json')" not in rewritten
    assert str(tests_dir) in rewritten
    assert str(logs_dir) in rewritten
from rubric_gen.biomnibench.rubrics.compiler import (
    TaskProcessRubricCompiler,
    TaskRubricCompilerConfig,
    TaskRubricRequest,
    TaskRubricRewriterProvenance,
    resolve_rubric_bundle,
)
from rubric_gen.biomnibench.rubrics.schema import canonical_json


class StaticRewriter:
    def rewrite(self, request: TaskRubricRequest) -> str:
        task_id = request.task_snapshot["task_id"]
        return canonical_json(
            {
                "schema_version": 1,
                "task_id": task_id,
                "purpose": "Evaluate the observable analysis process.",
                "criteria": [
                    {
                        "criterion_id": "C1",
                        "title": f"Analysis for {task_id}",
                        "description": "Assess whether the required analysis was executed.",
                        "max_points": 100,
                        "task_anchors": ["summary:C1", "data:input.tsv"],
                        "required_evidence": [
                            "Commands and outputs show the analysis."
                        ],
                        "acceptable_alternatives": ["An equivalent scripted analysis."],
                        "anti_evidence": [
                            "A claim unsupported by a produced artifact."
                        ],
                        "verification": ["Inspect the commands and report.tsv."],
                        "levels": [
                            {
                                "label": "A",
                                "points": 100,
                                "description": "Complete and independently verifiable.",
                            },
                            {
                                "label": "B",
                                "points": 50,
                                "description": "Partial, but supported by evidence.",
                            },
                            {
                                "label": "C",
                                "points": 0,
                                "description": "No supported analysis.",
                            },
                        ],
                    }
                ],
            }
        )


class SignedPenaltyRewriter(StaticRewriter):
    def rewrite(self, request: TaskRubricRequest) -> str:
        payload = json.loads(super().rewrite(request))
        payload["criteria"].append(
            {
                "criterion_id": "C2",
                "title": "Unsupported-claim penalty",
                "description": "Penalize claims that contradict the evidence.",
                "max_points": 0,
                "task_anchors": ["evidence:final-claims"],
                "required_evidence": ["Final claims are traceable to results."],
                "acceptable_alternatives": ["No unsupported claims are made."],
                "anti_evidence": ["The final answer invents a result."],
                "verification": ["Cross-check final claims against artifacts."],
                "levels": [
                    {
                        "label": "A",
                        "points": 0,
                        "description": "Every claim is supported.",
                    },
                    {
                        "label": "B",
                        "points": -5,
                        "description": "One material claim is weakly supported.",
                    },
                    {
                        "label": "C",
                        "points": -10,
                        "description": "A material claim is contradicted.",
                    },
                ],
            }
        )
        return canonical_json(payload)


@pytest.mark.parametrize(
    ("model", "provider"),
    (
        ("gpt-5.6-luna", "openai"),
        ("o3", "openai"),
        ("gemini-3.1-pro-preview", "gemini"),
        ("claude-opus-4", "anthropic"),
    ),
)
def test_centralized_judge_routes_models_to_explicit_providers(
    model: str,
    provider: str,
) -> None:
    assert centralized_judge_module.provider_for_model(model) == provider


def test_default_judge_model_is_gpt_5_6_luna() -> None:
    assert DEFAULT_JUDGE_MODEL == "gpt-5.6-luna"


def test_centralized_openai_judge_uses_responses_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeResponses:
        def create(self, **kwargs: object) -> object:
            observed.update(kwargs)
            return types.SimpleNamespace(output_text='{"criteria": {}}')

    class FakeOpenAI:
        def __init__(self, *, api_key: str) -> None:
            observed["api_key"] = api_key
            self.responses = FakeResponses()

    monkeypatch.setenv("OPENAI_API_KEY", "openai-secret")
    monkeypatch.setitem(sys.modules, "openai", types.SimpleNamespace(OpenAI=FakeOpenAI))

    response = centralized_judge_module.generate_response(
        "gpt-5.6-luna", "judge prompt"
    )

    assert response == '{"criteria": {}}'
    assert observed == {
        "api_key": "openai-secret",
        "model": "gpt-5.6-luna",
        "input": "judge prompt",
        "max_output_tokens": 8192,
    }


def test_centralized_gemini_judge_keeps_client_alive(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeModels:
        def __init__(self, client: object) -> None:
            self.client = client

        def generate_content(self, **kwargs: object) -> object:
            observed.update(kwargs)
            observed["client"] = self.client
            return types.SimpleNamespace(text='{"criteria": {}}')

    class FakeClient:
        def __init__(self, *, api_key: str) -> None:
            observed["api_key"] = api_key
            self.models = FakeModels(self)

    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret")
    monkeypatch.setitem(
        sys.modules,
        "google",
        types.SimpleNamespace(genai=types.SimpleNamespace(Client=FakeClient)),
    )

    response = centralized_judge_module.generate_response(
        "gemini-3.1-pro-preview", "judge prompt"
    )

    assert response == '{"criteria": {}}'
    assert observed["api_key"] == "gemini-secret"
    assert observed["model"] == "gemini-3.1-pro-preview"
    assert observed["contents"] == "judge prompt"
    assert isinstance(observed["client"], FakeClient)


def test_centralized_anthropic_judge_extracts_text_from_multiple_blocks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    class FakeMessages:
        def create(self, **kwargs: object) -> object:
            observed.update(kwargs)
            return types.SimpleNamespace(
                content=[
                    types.SimpleNamespace(type="thinking", thinking="private"),
                    types.SimpleNamespace(type="text", text='{"criteria":'),
                    types.SimpleNamespace(type="text", text=" {}}"),
                ],
                stop_reason="end_turn",
            )

    class FakeAnthropic:
        def __init__(self, *, api_key: str) -> None:
            observed["api_key"] = api_key
            self.messages = FakeMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-secret")
    monkeypatch.setitem(
        sys.modules,
        "anthropic",
        types.SimpleNamespace(Anthropic=FakeAnthropic),
    )

    response = centralized_judge_module.generate_response(
        "claude-fable-5", "judge prompt"
    )

    assert response == '{"criteria":\n {}}'
    assert observed["api_key"] == "anthropic-secret"
    assert observed["model"] == "claude-fable-5"
    assert observed["max_tokens"] == 8192


def test_centralized_anthropic_judge_reports_empty_response(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeMessages:
        def create(self, **kwargs: object) -> object:
            return types.SimpleNamespace(content=[], stop_reason="refusal")

    class FakeAnthropic:
        def __init__(self, *, api_key: str) -> None:
            self.messages = FakeMessages()

    monkeypatch.setenv("ANTHROPIC_API_KEY", "anthropic-secret")
    monkeypatch.setitem(
        sys.modules,
        "anthropic",
        types.SimpleNamespace(Anthropic=FakeAnthropic),
    )

    with pytest.raises(RuntimeError, match="stop_reason='refusal'"):
        centralized_judge_module.generate_response("claude-fable-5", "prompt")


def rewriter_provenance_for(
    rewriter_type: type[object],
) -> TaskRubricRewriterProvenance:
    implementation_id = f"{rewriter_type.__module__}.{rewriter_type.__qualname__}"
    return TaskRubricRewriterProvenance(
        schema_version=1,
        provider="test-static",
        model="gemini-3.5-flash",
        implementation_id=implementation_id,
        implementation_sha256=hashlib.sha256(
            implementation_id.encode("utf-8")
        ).hexdigest(),
    )


def make_task(root: Path, task_id: str) -> Path:
    task_dir = root / task_id
    tests_dir = task_dir / "tests"
    data_dir = task_dir / "environment" / "data"
    tests_dir.mkdir(parents=True)
    data_dir.mkdir(parents=True)
    (task_dir / "instruction.md").write_text(
        "# Task\n\n## Question\n\nAnalyze input.tsv.\n\n"
        "## Data Files\n\nUse `input.tsv`.\n\n"
        "## Required Outputs\n\nWrite `report.tsv`.\n",
        encoding="utf-8",
    )
    (task_dir / "task.toml").write_text(
        f'schema_version = "1.1"\n[task]\nname = "test/{task_id}"\n',
        encoding="utf-8",
    )
    (tests_dir / "rubric.txt").write_text(
        "Criterion 1: Local rubric\nLevels: A=100 B=50 C=0\n",
        encoding="utf-8",
    )
    (tests_dir / "process_rubric.txt").write_text(
        "Criterion 1: Explicit local rubric\nLevels: A=100 B=25 C=0\n",
        encoding="utf-8",
    )
    (tests_dir / "llm_judge.py").write_text("print('judge')\n", encoding="utf-8")
    (data_dir / "input.tsv").write_text("value\n1\n", encoding="utf-8")
    return task_dir


def compile_rubric_set(tmp_path: Path, *task_ids: str) -> tuple[Path, Path]:
    tasks_dir = tmp_path / "compiler-tasks"
    for task_id in task_ids:
        make_task(tasks_dir, task_id)
    output = tmp_path / "rubric-set"
    compiler = TaskProcessRubricCompiler(
        TaskRubricCompilerConfig(
            tasks_dir=tasks_dir,
            task_ids=tuple(task_ids),
            output_dir=output,
            max_retries=0,
        ),
        rewriter=StaticRewriter(),
        rewriter_provenance=rewriter_provenance_for(StaticRewriter),
    )
    assert compiler.run() == 0
    return output, tasks_dir


def make_target(tmp_path: Path, task_id: str = "da-1-1") -> JudgeTarget:
    task_dir = make_task(tmp_path / "runtime-tasks", task_id)
    run_dir = tmp_path / "run" / "tasks" / task_id
    workspace_dir = tmp_path / "run" / "workspaces" / task_id
    run_dir.mkdir(parents=True)
    workspace_dir.mkdir(parents=True)
    trajectory = run_dir / "trajectory.stream.jsonl"
    trajectory.write_text('{"type": "message"}\n', encoding="utf-8")
    (workspace_dir / "trace.md").write_text("trace", encoding="utf-8")
    (workspace_dir / "answer.txt").write_text("answer", encoding="utf-8")
    return JudgeTarget(
        task=task_id,
        task_dir=task_dir,
        run_dir=run_dir,
        workspace_dir=workspace_dir,
        trajectory_path=trajectory,
        output_root=tmp_path / "run",
    )


def make_runner(
    tmp_path: Path,
    *,
    rubric_set: Path | None = None,
    rubric_name: str | None = None,
    dry_run: bool = False,
    resume: bool = False,
    review: str = "trace",
    model: str | None = None,
    max_review_chars: int | None = None,
    repeats: int = 1,
) -> BiomniBenchJudgeRunner:
    return BiomniBenchJudgeRunner(
        JudgeRunConfig(
            run_dir=tmp_path / "run",
            tasks_dir=tmp_path / "runtime-tasks",
            rubric_set=rubric_set,
            rubric_name=rubric_name,
            dry_run=dry_run,
            resume=resume,
            review=review,
            model=model,
            max_review_chars=max_review_chars,
            repeats=repeats,
        )
    )


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_cli_rejects_rubric_and_rubric_set_together(tmp_path: Path) -> None:
    parser = build_parser()
    args = parser.parse_args(
        [
            "judge",
            "--run-dir",
            str(tmp_path / "run"),
            "--rubric-set",
            str(tmp_path / "rubric-set"),
        ]
    )
    config = JudgeRunConfig.from_namespace(args)

    assert config.rubric_set == (tmp_path / "rubric-set").resolve()
    assert config.rubric_name is None
    assert config.artifacts_dir is not None
    assert config.artifacts_dir.is_relative_to(
        Path.cwd() / "runs" / "biomnibench-judges"
    )

    with pytest.raises(SystemExit):
        parser.parse_args(
            [
                "judge",
                "--run-dir",
                str(tmp_path / "run"),
                "--rubric",
                "process_rubric.txt",
                "--rubric-set",
                str(tmp_path / "rubric-set"),
            ]
        )


def test_judge_discovers_final_submissions_from_revision_batch(tmp_path: Path) -> None:
    tasks_dir = tmp_path / "tasks"
    batch = tmp_path / "revision-batch"
    experiment_dirs = []
    for task_id in ("da-1-1", "da-1-2"):
        task_dir = make_task(tasks_dir, task_id)
        experiment = batch / task_id
        submission = experiment / "submissions" / "s001"
        workspace = submission / "workspace"
        workspace.mkdir(parents=True)
        (submission / "trajectory.stream.jsonl").write_text("{}\n")
        (workspace / "trace.md").write_text("trace")
        (workspace / "answer.txt").write_text("answer")
        (experiment / "manifest.json").write_text(
            json.dumps(
                {
                    "kind": "rubric-gen-submission-revision-experiment",
                    "task_id": task_id,
                    "task_dir": str(task_dir),
                }
            )
        )
        (experiment / "state.json").write_text(
            json.dumps({"submission_ids": ["s000", "s001"]})
        )
        experiment_dirs.append(task_id)
    (batch / "batch.json").write_text(
        json.dumps(
            {
                "kind": "rubric-gen-submission-revision-batch",
                "experiment_dirs": experiment_dirs,
            }
        )
    )
    runner = BiomniBenchJudgeRunner(
        JudgeRunConfig(run_dir=batch, tasks_dir=tasks_dir)
    )

    targets = runner.discover_targets()

    assert [target.task for target in targets] == ["da-1-1", "da-1-2"]
    assert all(target.run_dir.name == "s001" for target in targets)
    assert {target.output_root for target in targets} == {
        batch / "da-1-1",
        batch / "da-1-2",
    }


def test_target_task_must_match_canonical_task_directory(tmp_path: Path) -> None:
    rubric_set, _ = compile_rubric_set(tmp_path, "da-1-1", "da-2-1")
    target = make_target(tmp_path, "da-1-1")
    target = replace(target, task="da-2-1")
    runner = make_runner(tmp_path, rubric_set=rubric_set)

    with pytest.raises(SystemExit, match="task directory"):
        runner.resolve_rubric(target)


def test_direct_execute_validates_target_before_creating_output(tmp_path: Path) -> None:
    target = make_target(tmp_path)
    invalid_target = replace(target, task="da-2-1")
    runner = make_runner(tmp_path)
    output_dir = runner.output_dir(invalid_target)

    with pytest.raises(SystemExit):
        runner.execute_judge(
            target.task_dir / "tests" / "llm_judge.py",
            target.task_dir / "tests" / "rubric.txt",
            output_dir,
            "trace",
            "answer",
            attempt=JudgeAttempt(invalid_target, 1),
        )

    assert not output_dir.exists()


@pytest.mark.parametrize("mismatch", ("task", "task_dir", "workspace_dir"))
def test_batch_discovery_rejects_status_identity_mismatch(
    tmp_path: Path,
    mismatch: str,
) -> None:
    task_id = "da-1-1"
    task_dir = make_task(tmp_path / "runtime-tasks", task_id)
    batch_dir = tmp_path / "run"
    run_dir = batch_dir / "tasks" / task_id
    workspace_dir = batch_dir / "workspaces" / task_id
    run_dir.mkdir(parents=True)
    workspace_dir.mkdir(parents=True)
    status = {
        "task": task_id,
        "task_dir": str(task_dir),
        "workspace_dir": str(workspace_dir),
    }
    replacements = {
        "task": "da-2-1",
        "task_dir": str(tmp_path / "runtime-tasks" / "da-2-1"),
        "workspace_dir": str(tmp_path / "outside-workspace"),
    }
    status[mismatch] = replacements[mismatch]
    (run_dir / "status.json").write_text(json.dumps(status), encoding="utf-8")
    runner = make_runner(tmp_path)

    with pytest.raises(SystemExit):
        runner.discover_targets()


def test_single_discovery_rejects_unsafe_status_task(tmp_path: Path) -> None:
    run_dir = tmp_path / "standalone-run"
    run_dir.mkdir()
    (run_dir / "status.json").write_text(
        json.dumps({"task": "../escape"}),
        encoding="utf-8",
    )
    runner = BiomniBenchJudgeRunner(
        JudgeRunConfig(
            run_dir=run_dir,
            tasks_dir=tmp_path / "runtime-tasks",
        )
    )

    with pytest.raises(SystemExit, match="task ID"):
        runner.discover_targets()


def test_single_discovery_rejects_another_runs_workspace(tmp_path: Path) -> None:
    task_id = "da-1-1"
    task_dir = make_task(tmp_path / "runtime-tasks", task_id)
    runs_dir = tmp_path / "runs"
    run_a = runs_dir / f"{task_id}-gemini-A"
    run_b = runs_dir / f"{task_id}-gemini-B"
    workspace_a = runs_dir / "_workspaces" / run_a.name
    workspace_b = runs_dir / "_workspaces" / run_b.name
    for run_dir, workspace in ((run_a, workspace_a), (run_b, workspace_b)):
        run_dir.mkdir(parents=True)
        workspace.mkdir(parents=True)
        (run_dir / "trajectory.stream.jsonl").write_text(
            '{"type": "message"}\n',
            encoding="utf-8",
        )
        (workspace / "trace.md").write_text(run_dir.name, encoding="utf-8")
        (workspace / "answer.txt").write_text(run_dir.name, encoding="utf-8")
    (run_a / "status.json").write_text(
        json.dumps(
            {
                "task": task_id,
                "task_dir": str(task_dir),
                "workspace_dir": str(workspace_b),
            }
        ),
        encoding="utf-8",
    )
    runner = BiomniBenchJudgeRunner(
        JudgeRunConfig(
            run_dir=run_a,
            tasks_dir=tmp_path / "runtime-tasks",
            dry_run=True,
        )
    )

    with pytest.raises(SystemExit, match="workspace"):
        runner.discover_targets()


@pytest.mark.parametrize("max_concurrency", (1, 2))
def test_duplicate_canonical_run_inputs_are_rejected_before_attempts(
    tmp_path: Path,
    max_concurrency: int,
) -> None:
    task_id = "da-1-1"
    task_dir = make_task(tmp_path / "runtime-tasks", task_id)
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / f"{task_id}-gemini-A"
    workspace = runs_dir / "_workspaces" / run_dir.name
    run_dir.mkdir(parents=True)
    workspace.mkdir(parents=True)
    (run_dir / "trajectory.stream.jsonl").write_text(
        '{"type": "message"}\n',
        encoding="utf-8",
    )
    (workspace / "trace.md").write_text("trace", encoding="utf-8")
    (workspace / "answer.txt").write_text("answer", encoding="utf-8")
    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "task": task_id,
                "task_dir": str(task_dir),
                "workspace_dir": str(workspace),
            }
        ),
        encoding="utf-8",
    )
    alias_parent = runs_dir / "alias"
    alias_parent.mkdir()
    run_alias = alias_parent / ".." / run_dir.name
    runner = BiomniBenchJudgeRunner(
        JudgeRunConfig(
            run_dir=run_dir,
            extra_run_dirs=(run_alias,),
            tasks_dir=tmp_path / "runtime-tasks",
            dry_run=True,
            max_concurrency=max_concurrency,
        )
    )

    with pytest.raises(SystemExit, match="Duplicate canonical run directory"):
        runner.run()

    assert not runner.scores_path.exists()


def test_expanded_targets_reject_duplicate_canonical_run_directory(
    tmp_path: Path,
) -> None:
    target = make_target(tmp_path)
    runner = BiomniBenchJudgeRunner(
        JudgeRunConfig(
            run_dir=target.output_root,
            extra_run_dirs=(target.run_dir,),
            tasks_dir=tmp_path / "runtime-tasks",
            dry_run=True,
        )
    )

    with pytest.raises(SystemExit, match="Duplicate canonical target run directory"):
        runner.discover_targets()


@pytest.mark.parametrize("filename", ("trace.md", "answer.txt"))
def test_batch_review_rejects_symlinked_workspace_artifact(
    tmp_path: Path,
    filename: str,
) -> None:
    target = make_target(tmp_path)
    outside = tmp_path / f"outside-{filename}"
    outside.write_text("outside secret", encoding="utf-8")
    artifact = target.workspace_dir / filename
    artifact.unlink()
    artifact.symlink_to(outside)

    with pytest.raises(SystemExit, match="artifact"):
        make_runner(tmp_path, dry_run=True).review_target(target)


def test_standalone_review_rejects_symlinked_trajectory_artifact(
    tmp_path: Path,
) -> None:
    task_id = "da-1-1"
    task_dir = make_task(tmp_path / "runtime-tasks", task_id)
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / f"{task_id}-gemini-A"
    workspace = runs_dir / "_workspaces" / run_dir.name
    run_dir.mkdir(parents=True)
    workspace.mkdir(parents=True)
    (workspace / "trace.md").write_text("trace", encoding="utf-8")
    (workspace / "answer.txt").write_text("answer", encoding="utf-8")
    outside = tmp_path / "outside-trajectory.stream.jsonl"
    outside.write_text('{"type": "secret"}\n', encoding="utf-8")
    (run_dir / "trajectory.stream.jsonl").symlink_to(outside)
    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "task": task_id,
                "task_dir": str(task_dir),
                "workspace_dir": str(workspace),
            }
        ),
        encoding="utf-8",
    )
    runner = BiomniBenchJudgeRunner(
        JudgeRunConfig(
            run_dir=run_dir,
            tasks_dir=tmp_path / "runtime-tasks",
            review="trajectory",
            dry_run=True,
        )
    )

    with pytest.raises(SystemExit, match="artifact"):
        runner.review_target(runner.discover_targets()[0])


def test_standalone_review_rejects_workspace_parent_replaced_after_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = "da-1-1"
    task_dir = make_task(tmp_path / "runtime-tasks", task_id)
    runs_dir = tmp_path / "runs"
    run_dir = runs_dir / f"{task_id}-gemini-A"
    workspace = runs_dir / "_workspaces" / run_dir.name
    outside_workspace = tmp_path / "outside-workspace"
    run_dir.mkdir(parents=True)
    workspace.mkdir(parents=True)
    outside_workspace.mkdir()
    (run_dir / "trajectory.stream.jsonl").write_text(
        '{"type": "message"}\n',
        encoding="utf-8",
    )
    for root, prefix in ((workspace, "inside"), (outside_workspace, "outside")):
        (root / "trace.md").write_text(f"{prefix} trace", encoding="utf-8")
        (root / "answer.txt").write_text(f"{prefix} answer", encoding="utf-8")
    (run_dir / "status.json").write_text(
        json.dumps(
            {
                "task": task_id,
                "task_dir": str(task_dir),
                "workspace_dir": str(workspace),
            }
        ),
        encoding="utf-8",
    )
    runner = BiomniBenchJudgeRunner(
        JudgeRunConfig(
            run_dir=run_dir,
            tasks_dir=tmp_path / "runtime-tasks",
            dry_run=True,
        )
    )
    target = runner.discover_targets()[0]
    original_validate = runner.validate_target_identity
    original_workspace = workspace.with_name(f"{workspace.name}-original")
    replaced = False

    def validate_then_replace(candidate: JudgeTarget) -> None:
        nonlocal replaced
        original_validate(candidate)
        if not replaced:
            workspace.rename(original_workspace)
            workspace.symlink_to(outside_workspace, target_is_directory=True)
            replaced = True

    monkeypatch.setattr(runner, "validate_target_identity", validate_then_replace)

    with pytest.raises(SystemExit, match="artifact"):
        runner.review_target(target)


@pytest.mark.parametrize(
    ("review", "replacement_trigger"),
    (("trace", "trace.md"), ("trajectory", "trajectory.stream.jsonl")),
)
def test_review_rejects_workspace_replaced_between_artifact_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    review: str,
    replacement_trigger: str,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path, review=review, dry_run=True)
    original_workspace = target.workspace_dir.with_name(
        f"{target.workspace_dir.name}-original"
    )
    replacement_workspace = target.workspace_dir.with_name(
        f"{target.workspace_dir.name}-replacement"
    )
    replacement_workspace.mkdir()
    (replacement_workspace / "trace.md").write_text(
        "replacement trace",
        encoding="utf-8",
    )
    (replacement_workspace / "answer.txt").write_text(
        "replacement answer",
        encoding="utf-8",
    )
    original_read_artifact = runner._read_review_artifact
    replaced = False

    def read_then_replace(
        root: Path,
        name: str,
        *args: object,
        **kwargs: object,
    ) -> str:
        nonlocal replaced
        text = original_read_artifact(root, name, *args, **kwargs)
        if name == replacement_trigger and not replaced:
            target.workspace_dir.rename(original_workspace)
            replacement_workspace.rename(target.workspace_dir)
            replaced = True
        return text

    monkeypatch.setattr(runner, "_read_review_artifact", read_then_replace)

    with pytest.raises(SystemExit, match="identity changed"):
        runner.review_target(target)


def test_trajectory_rejects_regular_run_replacement_after_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path, review="trajectory", dry_run=True)
    original_run = target.run_dir.with_name(f"{target.run_dir.name}-original")
    replacement_run = tmp_path / "replacement-run"
    replacement_run.mkdir()
    (replacement_run / "trajectory.stream.jsonl").write_text(
        '{"type": "replacement"}\n',
        encoding="utf-8",
    )
    original_find_judge = runner.find_judge
    replaced = False

    def find_then_replace(task_dir: Path) -> Path:
        nonlocal replaced
        judge = original_find_judge(task_dir)
        if not replaced:
            target.run_dir.rename(original_run)
            replacement_run.rename(target.run_dir)
            replaced = True
        return judge

    monkeypatch.setattr(runner, "find_judge", find_then_replace)

    with pytest.raises(SystemExit, match="identity changed"):
        runner.review_target(target)


def test_trace_rejects_regular_workspace_replacement_after_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path, dry_run=True)
    original_workspace = target.workspace_dir.with_name(
        f"{target.workspace_dir.name}-original"
    )
    replacement_workspace = tmp_path / "replacement-workspace"
    replacement_workspace.mkdir()
    (replacement_workspace / "trace.md").write_text(
        "replacement trace",
        encoding="utf-8",
    )
    (replacement_workspace / "answer.txt").write_text(
        "replacement answer",
        encoding="utf-8",
    )
    original_find_judge = runner.find_judge
    replaced = False

    def find_then_replace(task_dir: Path) -> Path:
        nonlocal replaced
        judge = original_find_judge(task_dir)
        if not replaced:
            target.workspace_dir.rename(original_workspace)
            replacement_workspace.rename(target.workspace_dir)
            replaced = True
        return judge

    monkeypatch.setattr(runner, "find_judge", find_then_replace)

    with pytest.raises(SystemExit, match="identity changed"):
        runner.review_target(target)


def test_trajectory_rejects_retargeted_run_ancestor_alias(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = "da-1-1"
    task_dir = make_task(tmp_path / "runtime-tasks", task_id)
    run_name = f"{task_id}-gemini-A"
    physical_a = tmp_path / "physical-a"
    physical_b = tmp_path / "physical-b"
    run_a = physical_a / run_name
    run_b = physical_b / run_name
    workspace_a = physical_a / "_workspaces" / run_name
    run_a.mkdir(parents=True)
    run_b.mkdir(parents=True)
    workspace_a.mkdir(parents=True)
    (run_a / "trajectory.stream.jsonl").write_text(
        '{"type": "original"}\n',
        encoding="utf-8",
    )
    (run_b / "trajectory.stream.jsonl").write_text(
        '{"type": "replacement"}\n',
        encoding="utf-8",
    )
    (workspace_a / "trace.md").write_text("safe trace", encoding="utf-8")
    (workspace_a / "answer.txt").write_text("safe answer", encoding="utf-8")
    (run_a / "status.json").write_text(
        json.dumps(
            {
                "task": task_id,
                "task_dir": str(task_dir),
                "workspace_dir": str(workspace_a),
            }
        ),
        encoding="utf-8",
    )
    alias = tmp_path / "run-alias"
    alias.symlink_to(physical_a, target_is_directory=True)
    runner = BiomniBenchJudgeRunner(
        JudgeRunConfig(
            run_dir=alias / run_name,
            tasks_dir=tmp_path / "runtime-tasks",
            review="trajectory",
            dry_run=True,
        )
    )
    target = runner.discover_targets()[0]
    original_find_judge = runner.find_judge
    retargeted = False

    def find_then_retarget(task_path: Path) -> Path:
        nonlocal retargeted
        judge = original_find_judge(task_path)
        if not retargeted:
            alias.unlink()
            alias.symlink_to(physical_b, target_is_directory=True)
            retargeted = True
        return judge

    monkeypatch.setattr(runner, "find_judge", find_then_retarget)

    with pytest.raises(SystemExit, match="identity changed"):
        runner.review_target(target)


def test_score_attestation_uses_bound_run_identity_after_alias_retarget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task_id = "da-1-1"
    task_dir = make_task(tmp_path / "runtime-tasks", task_id)
    run_name = f"{task_id}-gemini-A"
    physical_a = tmp_path / "physical-a"
    physical_b = tmp_path / "physical-b"
    run_a = physical_a / run_name
    run_b = physical_b / run_name
    workspace_a = physical_a / "_workspaces" / run_name
    run_a.mkdir(parents=True)
    run_b.mkdir(parents=True)
    workspace_a.mkdir(parents=True)
    (run_a / "trajectory.stream.jsonl").write_text(
        '{"type": "original"}\n',
        encoding="utf-8",
    )
    (workspace_a / "trace.md").write_text("safe trace", encoding="utf-8")
    (workspace_a / "answer.txt").write_text("safe answer", encoding="utf-8")
    (run_a / "status.json").write_text(
        json.dumps(
            {
                "task": task_id,
                "task_dir": str(task_dir),
                "workspace_dir": str(workspace_a),
            }
        ),
        encoding="utf-8",
    )
    alias = tmp_path / "run-alias"
    alias.symlink_to(physical_a, target_is_directory=True)
    runner = BiomniBenchJudgeRunner(
        JudgeRunConfig(
            run_dir=alias / run_name,
            tasks_dir=tmp_path / "runtime-tasks",
        )
    )
    target = runner.discover_targets()[0]
    original_validate = runner.validate_target_identity
    retargeted = False

    def validate_then_retarget(candidate: JudgeTarget) -> None:
        nonlocal retargeted
        original_validate(candidate)
        if not retargeted:
            alias.unlink()
            alias.symlink_to(physical_b, target_is_directory=True)
            retargeted = True

    monkeypatch.setattr(runner, "validate_target_identity", validate_then_retarget)

    attestation = runner.score_input_attestation(
        attempt=JudgeAttempt(target, 1),
        judge_source=b"print('judge')\n",
        review_text="safe trace",
        answer_text="safe answer",
        effective_judge_model="judge-model-a",
    )

    assert attestation["run_identity"] == str(run_a.resolve())


def test_direct_execute_rejects_regular_output_root_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path)
    output_dir = runner.output_dir(target)
    original_root = tmp_path / "original-output-root"
    replacement_root = tmp_path / "replacement-output-root"
    (replacement_root / "tasks" / target.task).mkdir(parents=True)
    (replacement_root / "workspaces" / target.task).mkdir(parents=True)
    original_safe_output_path = runner._safe_output_path
    replaced = False

    def replace_root_after_path_check(output_root: Path, candidate: Path) -> Path:
        nonlocal replaced
        result = original_safe_output_path(output_root, candidate)
        if candidate == output_dir and not replaced:
            target.output_root.rename(original_root)
            replacement_root.rename(target.output_root)
            replaced = True
        return result

    def fake_run(cmd: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(cmd, 1, stdout="failed\n")

    monkeypatch.setattr(runner, "_safe_output_path", replace_root_after_path_check)
    monkeypatch.setattr("rubric_gen.biomnibench.judging.executor.subprocess.run", fake_run)

    with pytest.raises(SystemExit, match="identity changed"):
        runner.execute_judge(
            target.task_dir / "tests" / "llm_judge.py",
            target.task_dir / "tests" / "rubric.txt",
            output_dir,
            "trace",
            "answer",
            attempt=JudgeAttempt(target, 1),
        )

    assert not (target.output_root / "judges").exists()


def test_output_symlink_escape_is_rejected_before_dry_run_writes(
    tmp_path: Path,
) -> None:
    target = make_target(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (target.output_root / "judges").symlink_to(outside, target_is_directory=True)
    runner = make_runner(tmp_path, dry_run=True)

    with pytest.raises(SystemExit, match="symlink"):
        runner.review_target(target)

    assert list(outside.iterdir()) == []


def test_dry_run_does_not_create_per_target_outputs(tmp_path: Path) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path, dry_run=True)
    output_dir = runner.output_dir(target)

    record = runner.review_target(target)

    assert record["status"] == "planned"
    assert not output_dir.exists()


def test_gemini_judge_subprocess_prefers_gemini_api_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path, model="gemini-test-model")
    captured_env: dict[str, str] = {}

    def fake_run(
        cmd: object, *, cwd: Path, env: dict[str, str], **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        captured_env.update(env)
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setenv("GEMINI_API_KEY", "gemini-secret")
    monkeypatch.setenv("GOOGLE_API_KEY", "google-secret")
    monkeypatch.setattr(
        "rubric_gen.biomnibench.judging.executor.subprocess.run", fake_run
    )

    assert runner.review_target(target)["status"] == "completed"
    assert captured_env["GEMINI_API_KEY"] == "gemini-secret"
    assert "GOOGLE_API_KEY" not in captured_env


def test_output_replacement_after_validation_cannot_redirect_input_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path)
    output_dir = runner.output_dir(target)
    displaced = output_dir.with_name("displaced-output")
    outside = tmp_path / "outside-output"
    outside.mkdir()
    original_safe_output_path = runner._safe_output_path
    replaced = False

    def replace_after_validation(output_root: Path, candidate: Path) -> Path:
        nonlocal replaced
        result = original_safe_output_path(output_root, candidate)
        if candidate == output_dir and candidate.is_dir() and not replaced:
            candidate.rename(displaced)
            candidate.symlink_to(outside, target_is_directory=True)
            replaced = True
        return result

    monkeypatch.setattr(runner, "_safe_output_path", replace_after_validation)

    with pytest.raises(SystemExit):
        runner.review_target(target)

    assert not (outside / "judge_input_trace.md").exists()
    assert not (outside / "judge_input_answer.txt").exists()


def test_output_replacement_during_judge_cannot_redirect_result_writes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path)
    output_dir = runner.output_dir(target)
    displaced = output_dir.with_name("displaced-output")
    outside = tmp_path / "outside-output"
    outside.mkdir()

    def fake_run(
        cmd: object, *, cwd: Path, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=100)
        output_dir.rename(displaced)
        output_dir.symlink_to(outside, target_is_directory=True)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judging.executor.subprocess.run", fake_run)

    with pytest.raises(SystemExit):
        runner.review_target(target)

    assert list(outside.iterdir()) == []


def test_output_write_is_rolled_back_if_root_moves_during_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path)
    runner.validate_target_identity(target)
    identities = runner._target_directory_identities(target)
    output_dir = runner.output_dir(target)
    displaced_root = tmp_path / "displaced-output-root"
    original_replace = os.replace
    moved = False

    def replace_after_move(
        source: object,
        destination: object,
        *args: object,
        **kwargs: object,
    ) -> None:
        nonlocal moved
        if destination == "probe.txt" and not moved:
            target.output_root.rename(displaced_root)
            moved = True
        original_replace(source, destination, *args, **kwargs)

    monkeypatch.setattr(judge_runner_module.os, "replace", replace_after_move)

    with pytest.raises(SystemExit, match="identity changed"):
        with runner._open_output_directory(
            target.output_root,
            output_dir,
            expected_root_identity=identities.output_root,
        ) as output:
            runner._write_output_text(output, "probe.txt", "must not persist")

    displaced_output = displaced_root / output_dir.relative_to(target.output_root)
    assert not (displaced_output / "probe.txt").exists()


def test_output_unlink_is_rolled_back_if_root_moves_during_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path)
    runner.validate_target_identity(target)
    identities = runner._target_directory_identities(target)
    output_dir = runner.output_dir(target)
    output_dir.mkdir(parents=True)
    (output_dir / "stale.txt").write_text("preserve me", encoding="utf-8")
    displaced_root = tmp_path / "displaced-output-root"
    original_replace = os.replace
    original_unlink = os.unlink
    moved = False

    def move_before_mutation() -> None:
        nonlocal moved
        if not moved:
            target.output_root.rename(displaced_root)
            moved = True

    def replace_after_move(
        source: object,
        destination: object,
        *args: object,
        **kwargs: object,
    ) -> None:
        if source == "stale.txt":
            move_before_mutation()
        original_replace(source, destination, *args, **kwargs)

    def unlink_after_move(
        path: object,
        *args: object,
        **kwargs: object,
    ) -> None:
        if path == "stale.txt":
            move_before_mutation()
        original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(judge_runner_module.os, "replace", replace_after_move)
    monkeypatch.setattr(judge_runner_module.os, "unlink", unlink_after_move)

    with pytest.raises(SystemExit, match="identity changed"):
        with runner._open_output_directory(
            target.output_root,
            output_dir,
            expected_root_identity=identities.output_root,
        ) as output:
            runner._unlink_output_file(output, "stale.txt")

    displaced_output = displaced_root / output_dir.relative_to(target.output_root)
    assert (displaced_output / "stale.txt").read_text(encoding="utf-8") == "preserve me"


@pytest.mark.parametrize("field", ("judge_name", "rubric_name"))
@pytest.mark.parametrize(
    "unsafe_name",
    (
        "../escape.py",
        "/tmp/escape.py",
        "nested/escape.py",
        r"nested\escape.py",
        ".",
        "..",
    ),
)
def test_judge_artifact_overrides_require_safe_basenames(
    tmp_path: Path,
    field: str,
    unsafe_name: str,
) -> None:
    kwargs = {field: unsafe_name}

    with pytest.raises(ValueError, match="basename"):
        JudgeRunConfig(
            run_dir=tmp_path / "run",
            tasks_dir=tmp_path / "runtime-tasks",
            **kwargs,
        )


def test_default_judge_is_centralized_and_ignores_task_local_script(
    tmp_path: Path,
) -> None:
    target = make_target(tmp_path)
    judge_path = target.task_dir / "tests" / "llm_judge.py"
    outside = tmp_path / "outside-judge.py"
    outside.write_text("print('outside')\n", encoding="utf-8")
    judge_path.unlink()
    judge_path.symlink_to(outside)

    resolved = make_runner(tmp_path).find_judge(target.task_dir)

    assert resolved.name == "llm_judge.py"
    assert resolved.parent.name == "judging"
    assert resolved != judge_path


def test_default_rubric_symlink_is_rejected(tmp_path: Path) -> None:
    target = make_target(tmp_path)
    rubric_path = target.task_dir / "tests" / "rubric.txt"
    outside = tmp_path / "outside-rubric.txt"
    outside.write_text("Criterion 1:\nLevels: A=100 B=0\n", encoding="utf-8")
    rubric_path.unlink()
    rubric_path.symlink_to(outside)

    with pytest.raises(SystemExit, match="symlink"):
        make_runner(tmp_path).resolve_rubric(target)


@pytest.mark.parametrize("field", ("judge_name", "rubric_name"))
def test_overridden_judge_artifact_symlink_is_rejected(
    tmp_path: Path,
    field: str,
) -> None:
    target = make_target(tmp_path)
    override_name = "custom.py" if field == "judge_name" else "custom.txt"
    outside = tmp_path / f"outside-{override_name}"
    outside.write_text("outside\n", encoding="utf-8")
    (target.task_dir / "tests" / override_name).symlink_to(outside)
    runner = BiomniBenchJudgeRunner(
        JudgeRunConfig(
            run_dir=tmp_path / "run",
            tasks_dir=tmp_path / "runtime-tasks",
            **{field: override_name},
        )
    )

    with pytest.raises(SystemExit, match="symlink"):
        if field == "judge_name":
            runner.find_judge(target.task_dir)
        else:
            runner.resolve_rubric(target)


def test_symlinked_tests_directory_is_rejected(tmp_path: Path) -> None:
    target = make_target(tmp_path)
    tests_dir = target.task_dir / "tests"
    outside = tmp_path / "outside-tests"
    tests_dir.rename(outside)
    tests_dir.symlink_to(outside, target_is_directory=True)

    with pytest.raises(SystemExit, match="symlink"):
        make_runner(tmp_path).find_judge(target.task_dir)


def test_external_judge_consumes_verified_bundle_snapshots(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rubric_set, _ = compile_rubric_set(tmp_path, "da-1-1")
    target = make_target(tmp_path)
    bundle = resolve_rubric_bundle(rubric_set, target.task)
    verified_text = bundle.rendered_text
    verified_manifest_sha256 = bundle.task_manifest_sha256
    bundle.rendered_path.write_text("tampered after resolve", encoding="utf-8")
    bundle.task_manifest_path.write_text("tampered after resolve", encoding="utf-8")
    monkeypatch.setattr(
        judge_runner_module,
        "resolve_rubric_bundle",
        lambda _rubric_set, _task: bundle,
    )
    runner = make_runner(tmp_path, rubric_set=rubric_set)

    resolved = runner.resolve_rubric(target)

    assert resolved.text == verified_text
    assert resolved.manifest_sha256 == verified_manifest_sha256


def test_external_rubric_never_falls_back(tmp_path: Path) -> None:
    rubric_set, _ = compile_rubric_set(tmp_path, "da-2-1")
    target = make_target(tmp_path, "da-1-1")
    runner = make_runner(tmp_path, rubric_set=rubric_set)

    with pytest.raises(SystemExit):
        runner.resolve_rubric(target)

    assert (target.task_dir / "tests" / "rubric.txt").is_file()


def test_external_rubric_rejects_root_task_manifest_mismatch(tmp_path: Path) -> None:
    rubric_set, _ = compile_rubric_set(tmp_path, "da-1-1")
    target = make_target(tmp_path)
    task_manifest_path = rubric_set / "tasks" / target.task / "manifest.json"
    task_manifest = json.loads(task_manifest_path.read_text())
    task_manifest["task_id"] = "da-9-9"
    task_manifest_path.write_text(
        canonical_json(task_manifest) + "\n", encoding="utf-8"
    )
    root_manifest_path = rubric_set / "manifest.json"
    root_manifest = json.loads(root_manifest_path.read_text())
    root_manifest["tasks"][target.task]["task_manifest_sha256"] = sha256_file(
        task_manifest_path
    )
    root_manifest_path.write_text(
        canonical_json(root_manifest) + "\n", encoding="utf-8"
    )
    runner = make_runner(tmp_path, rubric_set=rubric_set)

    with pytest.raises(SystemExit):
        runner.resolve_rubric(target)


def test_external_rubric_rejects_rendered_hash_mismatch(tmp_path: Path) -> None:
    rubric_set, _ = compile_rubric_set(tmp_path, "da-1-1")
    target = make_target(tmp_path)
    rendered = rubric_set / "tasks" / target.task / "process_rubric.txt"
    rendered.write_text(rendered.read_text() + "tampered\n", encoding="utf-8")
    runner = make_runner(tmp_path, rubric_set=rubric_set)

    with pytest.raises(SystemExit):
        runner.resolve_rubric(target)


def test_dry_run_verifies_external_rubric_bundle(tmp_path: Path) -> None:
    rubric_set, _ = compile_rubric_set(tmp_path, "da-1-1")
    target = make_target(tmp_path)
    rendered = rubric_set / "tasks" / target.task / "process_rubric.txt"
    rendered.write_text(rendered.read_text() + "tampered\n", encoding="utf-8")
    runner = make_runner(tmp_path, rubric_set=rubric_set, dry_run=True)

    with pytest.raises(SystemExit):
        runner.review_target(target)


def test_task_local_and_explicit_rubric_modes_remain_supported(tmp_path: Path) -> None:
    target = make_target(tmp_path)

    default = make_runner(tmp_path).resolve_rubric(target)
    explicit = make_runner(
        tmp_path,
        rubric_name="process_rubric.txt",
    ).resolve_rubric(target)

    assert default.path == target.task_dir / "tests" / "rubric.txt"
    assert default.source == "task-local"
    assert default.rubric_id is None
    assert default.rubric_set_id is None
    assert default.structured_rubric_sha256 is None
    assert (
        default.rendered_rubric_sha256
        == hashlib.sha256(default.text.encode("utf-8")).hexdigest()
    )
    assert default.manifest_path is None
    assert default.manifest_sha256 is None
    assert explicit.path == target.task_dir / "tests" / "process_rubric.txt"
    assert "Explicit local rubric" in explicit.text


def write_judge_artifacts(
    cwd: Path,
    *,
    reported_score: int = 0,
    criteria: object | None = None,
) -> None:
    logs = cwd / "logs" / "verifier"
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "reward.json").write_text(
        json.dumps({"score": reported_score}),
        encoding="utf-8",
    )
    (logs / "evaluation.json").write_text(
        json.dumps(
            {
                "criteria": criteria
                if criteria is not None
                else {"criterion_1": {"level": "A", "evidence": "observable"}}
            }
        ),
        encoding="utf-8",
    )


def test_authoritative_score_and_hash_attestation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path)
    resolved = runner.resolve_rubric(target)
    output_dir = runner.output_dir(target)
    output_dir.mkdir(parents=True)

    def fake_run(
        cmd: object, *, cwd: Path, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=0)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judging.executor.subprocess.run", fake_run)

    result = runner.execute_judge(
        target.task_dir / "tests" / "llm_judge.py",
        resolved,
        output_dir,
        "trace",
        "answer",
        attempt=JudgeAttempt(target, 1),
    )
    validation = json.loads((output_dir / "score_validation.json").read_text())

    assert result["status"] == "completed"
    assert result["exit_code"] == 0
    assert result["judge_exit_code"] == 0
    assert result["score"] == 100
    assert validation == {
        "schema_version": 1,
        "scorer_version": "rubric-scoring-v1",
        "score": 100,
        "raw_score": 100,
        "reported_score": 0,
        "score_matches_reported": False,
        "selected_levels": {"criterion_1": "A"},
        "criterion_scores": {"criterion_1": 100},
        "rubric_source": "task-local",
        "rubric_set_id": None,
        "rubric_id": None,
        "structured_rubric_sha256": None,
        "rendered_rubric_sha256": resolved.rendered_rubric_sha256,
        "manifest_sha256": None,
        "reward_sha256": sha256_file(output_dir / "reward.json"),
        "evaluation_sha256": sha256_file(output_dir / "evaluation.json"),
        "review_input_sha256": hashlib.sha256(b"trace").hexdigest(),
        "answer_input_sha256": hashlib.sha256(b"answer").hexdigest(),
        "judge_source_sha256": sha256_file(target.task_dir / "tests" / "llm_judge.py"),
        "judge_runner_sha256": runner.judge_runner_sha256(),
        "scorer_module_sha256": sha256_file(Path(rubric_scoring_module.__file__)),
        "effective_judge_model": runner.judge_model(os.environ.copy()),
        "review_mode": "trace",
        "max_review_chars": None,
        "task": target.task,
        "run_identity": str(target.run_dir.resolve()),
        "repeat_index": 1,
    }


def test_score_validation_hashes_the_exact_parsed_reward_and_evaluation_bytes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path, model="judge-model-a")
    resolved = runner.resolve_rubric(target)
    output_dir = runner.output_dir(target)
    output_dir.mkdir(parents=True)
    reward_path = output_dir / "reward.json"
    evaluation_path = output_dir / "evaluation.json"
    reward_path.write_text('{"score":100}', encoding="utf-8")
    evaluation_path.write_text(
        '{"criteria":{"criterion_1":{"level":"A"}}}',
        encoding="utf-8",
    )
    reward_sha256 = sha256_file(reward_path)
    evaluation_sha256 = sha256_file(evaluation_path)
    original_load_json = runner.load_json

    def load_then_mutate(path: Path) -> object:
        value = original_load_json(path)
        path.write_text("{}", encoding="utf-8")
        return value

    monkeypatch.setattr(runner, "load_json", load_then_mutate)
    attestation = runner.score_input_attestation(
        attempt=JudgeAttempt(target, 1),
        judge_source=b"print('judge')\n",
        review_text="trace",
        answer_text="answer",
        effective_judge_model="judge-model-a",
    )

    validation = runner.build_score_validation(
        resolved,
        reward_path,
        evaluation_path,
        attestation,
    )

    assert validation["score"] == 100
    assert validation["reward_sha256"] == reward_sha256
    assert validation["evaluation_sha256"] == evaluation_sha256


def test_judge_executes_verified_text_snapshot_when_source_changes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rubric_set, _ = compile_rubric_set(tmp_path, "da-1-1")
    target = make_target(tmp_path)
    runner = make_runner(tmp_path, rubric_set=rubric_set)
    resolved = runner.resolve_rubric(target)
    verified_text = resolved.text
    resolved.path.write_text(
        "Criterion 1: Changed after resolution\nLevels: A=1 B=0\n",
        encoding="utf-8",
    )
    output_dir = runner.output_dir(target)
    output_dir.mkdir(parents=True)

    def fake_run(
        cmd: object, *, cwd: Path, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        assert (Path(cwd) / "tests" / "rubric.txt").read_text() == verified_text
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judging.executor.subprocess.run", fake_run)

    result = runner.execute_judge(
        target.task_dir / "tests" / "llm_judge.py",
        resolved,
        output_dir,
        "trace",
        "answer",
        attempt=JudgeAttempt(target, 1),
    )

    assert result["status"] == "completed"
    assert result["score"] == 100


def test_malformed_criteria_fail_despite_zero_judge_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path)
    resolved = runner.resolve_rubric(target)
    output_dir = runner.output_dir(target)
    output_dir.mkdir(parents=True)

    def fake_run(
        cmd: object, *, cwd: Path, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), criteria={"criterion_9": {"level": "A"}})
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judging.executor.subprocess.run", fake_run)

    result = runner.execute_judge(
        target.task_dir / "tests" / "llm_judge.py",
        resolved,
        output_dir,
        "trace",
        "answer",
        attempt=JudgeAttempt(target, 1),
    )

    assert result["status"] == "failed"
    assert result["exit_code"] == 2
    assert result["judge_exit_code"] == 0
    assert result["score"] is None
    assert not (output_dir / "score_validation.json").exists()


def test_score_summary_excludes_failed_scalar_scores(tmp_path: Path) -> None:
    runner = make_runner(tmp_path)

    summary = runner.score_summary(
        [
            {"task": "da-1-1", "status": "completed", "score": 50},
            {"task": "da-1-2", "status": "failed", "score": 100},
        ]
    )

    assert summary["scored_attempts"] == 1
    assert summary["average_score"] == 50.0
    assert summary["tasks"][1]["score"] is None


@pytest.mark.parametrize("changed", ("rubric", "reward", "evaluation"))
def test_resume_requires_matching_artifact_hashes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed: str,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path)
    resolved = runner.resolve_rubric(target)
    output_dir = runner.output_dir(target)
    output_dir.mkdir(parents=True)

    def fake_run(
        cmd: object, *, cwd: Path, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judging.executor.subprocess.run", fake_run)
    assert (
        runner.execute_judge(
            runner.find_judge(target.task_dir),
            resolved,
            output_dir,
            "trace",
            "answer",
            attempt=JudgeAttempt(target, 1),
        )["status"]
        == "completed"
    )
    resume_runner = make_runner(tmp_path, resume=True)
    attempt = JudgeAttempt(target=target, repeat_index=1)
    assert resume_runner.completed_record(attempt) is not None

    changed_paths = {
        "rubric": target.task_dir / "tests" / "rubric.txt",
        "reward": output_dir / "reward.json",
        "evaluation": output_dir / "evaluation.json",
    }
    path = changed_paths[changed]
    path.write_text(path.read_text() + "\n", encoding="utf-8")

    assert resume_runner.completed_record(attempt) is None


def test_resume_rejects_output_root_replaced_during_cache_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path)

    def fake_run(
        cmd: object,
        *,
        cwd: Path,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judging.executor.subprocess.run", fake_run)
    assert runner.review_target(target)["status"] == "completed"

    replacement_root = tmp_path / "replacement-output-root"
    displaced_root = tmp_path / "displaced-output-root"
    shutil.copytree(target.output_root, replacement_root)
    resume_runner = make_runner(tmp_path, resume=True)
    resume_runner.validate_target_identity(target)
    original_validation = resume_runner.valid_score_validation
    replaced = False

    def validate_after_replacement(
        *args: object,
        **kwargs: object,
    ) -> dict[str, object] | None:
        nonlocal replaced
        if not replaced:
            target.output_root.rename(displaced_root)
            replacement_root.rename(target.output_root)
            replaced = True
        return original_validation(*args, **kwargs)

    monkeypatch.setattr(
        resume_runner,
        "valid_score_validation",
        validate_after_replacement,
    )

    with pytest.raises(SystemExit, match="identity changed"):
        resume_runner.completed_record(JudgeAttempt(target, 1))


def test_resume_rejects_cache_transplanted_between_repeats(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path, repeats=2)

    def fake_run(
        cmd: object, *, cwd: Path, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judging.executor.subprocess.run", fake_run)
    assert runner.review_target(target, repeat_index=1)["status"] == "completed"
    shutil.copytree(runner.output_dir(target, 1), runner.output_dir(target, 2))

    resume_runner = make_runner(tmp_path, repeats=2, resume=True)

    assert resume_runner.completed_record(JudgeAttempt(target, 2)) is None


def test_resume_rejects_cache_transplanted_between_tasks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = make_target(tmp_path, "da-1-1")
    destination = make_target(tmp_path, "da-2-1")
    runner = make_runner(tmp_path)

    def fake_run(
        cmd: object, *, cwd: Path, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judging.executor.subprocess.run", fake_run)
    assert runner.review_target(source)["status"] == "completed"
    shutil.copytree(runner.output_dir(source), runner.output_dir(destination))

    resume_runner = make_runner(tmp_path, resume=True)

    assert resume_runner.completed_record(JudgeAttempt(destination, 1)) is None


def test_resume_rejects_cache_transplanted_between_runs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_root = tmp_path / "first"
    second_root = tmp_path / "second"
    source = make_target(first_root)
    destination = make_target(second_root)
    first_runner = make_runner(first_root)

    def fake_run(
        cmd: object, *, cwd: Path, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judging.executor.subprocess.run", fake_run)
    assert first_runner.review_target(source)["status"] == "completed"
    second_runner = make_runner(second_root, resume=True)
    shutil.copytree(
        first_runner.output_dir(source),
        second_runner.output_dir(destination),
    )

    assert second_runner.completed_record(JudgeAttempt(destination, 1)) is None


@pytest.mark.parametrize(
    "changed",
    (
        "trace",
        "answer",
        "judge-source",
        "model",
        "max-review-chars",
        "scorer-version",
        "score-schema-type",
        "judge-runner-module",
        "scorer-module",
    ),
)
def test_resume_binds_actual_scoring_inputs_and_implementation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    changed: str,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path, model="judge-model-a")
    resolved = runner.resolve_rubric(target)
    output_dir = runner.output_dir(target)
    output_dir.mkdir(parents=True)

    def fake_run(
        cmd: object, *, cwd: Path, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judging.executor.subprocess.run", fake_run)
    assert (
        runner.execute_judge(
            target.task_dir / "tests" / "llm_judge.py",
            resolved,
            output_dir,
            runner.review_text(target),
            runner.read_text(target.workspace_dir / "answer.txt"),
            attempt=JudgeAttempt(target, 1),
        )["status"]
        == "completed"
    )

    resume_runner = make_runner(tmp_path, resume=True, model="judge-model-a")
    if changed == "trace":
        (target.workspace_dir / "trace.md").write_text("changed trace")
    elif changed == "answer":
        (target.workspace_dir / "answer.txt").write_text("changed answer")
    elif changed == "judge-source":
        (target.task_dir / "tests" / "llm_judge.py").write_text(
            "print('changed judge')\n"
        )
    elif changed == "model":
        resume_runner = make_runner(tmp_path, resume=True, model="judge-model-b")
    elif changed == "max-review-chars":
        resume_runner = make_runner(
            tmp_path,
            resume=True,
            model="judge-model-a",
            max_review_chars=100,
        )
    elif changed == "scorer-version":
        monkeypatch.setattr(
            judge_executor_module,
            "RUBRIC_SCORER_VERSION",
            "changed-version",
            raising=False,
        )
    elif changed == "score-schema-type":
        validation_path = output_dir / "score_validation.json"
        validation = json.loads(validation_path.read_text())
        validation["schema_version"] = True
        validation_path.write_text(json.dumps(validation))
    elif changed == "judge-runner-module":
        monkeypatch.setattr(
            BiomniBenchJudgeRunner,
            "judge_runner_sha256",
            lambda _self: "0" * 64,
            raising=False,
        )
    else:
        monkeypatch.setattr(
            BiomniBenchJudgeRunner,
            "scorer_module_sha256",
            lambda _self: "0" * 64,
            raising=False,
        )

    assert resume_runner.completed_record(JudgeAttempt(target, 1)) is None


def test_resume_binds_exact_trajectory_review_input(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path, review="trajectory", model="judge-model-a")
    resolved = runner.resolve_rubric(target)
    output_dir = runner.output_dir(target)
    output_dir.mkdir(parents=True)

    def fake_run(
        cmd: object, *, cwd: Path, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judging.executor.subprocess.run", fake_run)
    assert (
        runner.execute_judge(
            target.task_dir / "tests" / "llm_judge.py",
            resolved,
            output_dir,
            runner.review_text(target),
            runner.read_text(target.workspace_dir / "answer.txt"),
            attempt=JudgeAttempt(target, 1),
        )["status"]
        == "completed"
    )
    target.trajectory_path.write_text('{"type": "changed"}\n')

    resume_runner = make_runner(
        tmp_path,
        resume=True,
        review="trajectory",
        model="judge-model-a",
    )
    assert resume_runner.completed_record(JudgeAttempt(target, 1)) is None


def test_resume_binds_review_mode_even_with_identical_review_text(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path, model="judge-model-a")
    resolved = runner.resolve_rubric(target)
    output_dir = runner.output_dir(target)
    output_dir.mkdir(parents=True)

    def fake_run(
        cmd: object, *, cwd: Path, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judging.executor.subprocess.run", fake_run)
    assert (
        runner.execute_judge(
            target.task_dir / "tests" / "llm_judge.py",
            resolved,
            output_dir,
            "trace",
            "answer",
            attempt=JudgeAttempt(target, 1),
        )["status"]
        == "completed"
    )

    resume_runner = make_runner(
        tmp_path,
        resume=True,
        review="trajectory",
        model="judge-model-a",
    )
    trajectory_output = resume_runner.output_dir(target)
    shutil.copytree(output_dir, trajectory_output)
    monkeypatch.setattr(resume_runner, "review_text", lambda _target: "trace")

    assert resume_runner.completed_record(JudgeAttempt(target, 1)) is None


def test_resume_rejects_identical_rubric_from_different_set(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    first_set, _ = compile_rubric_set(tmp_path / "first", "da-1-1")
    second_set, _ = compile_rubric_set(
        tmp_path / "second",
        "da-1-1",
        "da-2-1",
    )
    target = make_target(tmp_path)
    first_runner = make_runner(tmp_path, rubric_set=first_set)
    first_rubric = first_runner.resolve_rubric(target)
    second_rubric = make_runner(
        tmp_path,
        rubric_set=second_set,
    ).resolve_rubric(target)
    assert first_rubric.structured_rubric_sha256 == (
        second_rubric.structured_rubric_sha256
    )
    assert first_rubric.rubric_set_id != second_rubric.rubric_set_id
    assert first_rubric.manifest_sha256 != second_rubric.manifest_sha256

    output_dir = first_runner.output_dir(target)
    output_dir.mkdir(parents=True)

    def fake_run(
        cmd: object, *, cwd: Path, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judging.executor.subprocess.run", fake_run)
    result = first_runner.execute_judge(
        target.task_dir / "tests" / "llm_judge.py",
        first_rubric,
        output_dir,
        "trace",
        "answer",
        attempt=JudgeAttempt(target, 1),
    )
    assert result["status"] == "completed"
    validation = json.loads((output_dir / "score_validation.json").read_text())
    assert validation["rubric_set_id"] == first_rubric.rubric_set_id
    assert validation["manifest_sha256"] == first_rubric.manifest_sha256

    second_runner = make_runner(tmp_path, rubric_set=second_set, resume=True)
    assert second_runner.completed_record(JudgeAttempt(target, 1)) is None


def test_resume_rejects_non_strict_attestation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    target = make_target(tmp_path)
    runner = make_runner(tmp_path)
    resolved = runner.resolve_rubric(target)
    output_dir = runner.output_dir(target)
    output_dir.mkdir(parents=True)

    def fake_run(
        cmd: object, *, cwd: Path, **kwargs: object
    ) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(Path(cwd), reported_score=100)
        return subprocess.CompletedProcess(cmd, 0, stdout="ok\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judging.executor.subprocess.run", fake_run)
    runner.execute_judge(
        target.task_dir / "tests" / "llm_judge.py",
        resolved,
        output_dir,
        "trace",
        "answer",
        attempt=JudgeAttempt(target, 1),
    )
    validation_path = output_dir / "score_validation.json"
    validation = json.loads(validation_path.read_text())
    validation["unexpected"] = True
    validation_path.write_text(json.dumps(validation), encoding="utf-8")

    resume_runner = make_runner(tmp_path, resume=True)
    assert resume_runner.completed_record(JudgeAttempt(target, 1)) is None


def test_offline_frozen_rubric_workflow_end_to_end(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tasks_dir = tmp_path / "compiler-tasks"
    compiler_task = make_task(tasks_dir, "da-1-1")
    (compiler_task / "trace.md").write_text("private runtime trace", encoding="utf-8")
    (compiler_task / "answer.txt").write_text(
        "private runtime answer", encoding="utf-8"
    )
    runtime_dir = compiler_task / "runs" / "condition_id-private"
    runtime_dir.mkdir(parents=True)
    (runtime_dir / "trajectory.jsonl").write_text(
        '{"search_history": "private runtime history"}\n',
        encoding="utf-8",
    )
    rubric_set = tmp_path / "rubric-set"
    compiler = TaskProcessRubricCompiler(
        TaskRubricCompilerConfig(
            tasks_dir=tasks_dir,
            task_ids=(compiler_task.name,),
            output_dir=rubric_set,
            max_retries=0,
        ),
        rewriter=SignedPenaltyRewriter(),
        rewriter_provenance=rewriter_provenance_for(SignedPenaltyRewriter),
    )

    assert compiler.run() == 0
    bundle = resolve_rubric_bundle(rubric_set, compiler_task.name)
    request_path = (
        bundle.task_manifest_path.parent / "attempts" / "attempt-1" / "request.json"
    )
    compiler_request = request_path.read_text(encoding="utf-8")

    target = make_target(tmp_path, compiler_task.name)
    runner = make_runner(tmp_path, rubric_set=rubric_set)

    def fake_run(
        cmd: object,
        *,
        cwd: Path,
        **kwargs: object,
    ) -> subprocess.CompletedProcess[str]:
        write_judge_artifacts(
            Path(cwd),
            reported_score=99,
            criteria={
                "criterion_1": {"level": "C", "evidence": "missing analysis"},
                "criterion_2": {"level": "C", "evidence": "contradicted claim"},
            },
        )
        return subprocess.CompletedProcess(cmd, 0, stdout="offline judge\n")

    monkeypatch.setattr("rubric_gen.biomnibench.judging.executor.subprocess.run", fake_run)

    record = runner.review_target(target)
    final_record = json.loads(Path(record["score_validation"]).read_text())

    assert record["status"] == "completed"
    assert record["rubric_set_id"] == bundle.rubric_set_id
    assert record["structured_rubric_sha256"] == bundle.rubric_sha256
    assert final_record["rubric_set_id"] == bundle.rubric_set_id
    assert final_record["structured_rubric_sha256"] == bundle.rubric_sha256
    assert final_record["raw_score"] == -10
    assert final_record["score"] == record["score"] == 0
    for forbidden in (
        "trajectory",
        "trace.md",
        "answer.txt",
        "condition_id",
        "search_history",
    ):
        assert forbidden not in compiler_request
