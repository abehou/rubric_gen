from __future__ import annotations

import json
from pathlib import Path

import pytest

import rubric_gen.biomnibench.revision.seeds as seeds_module
from rubric_gen.biomnibench.agent.models import AgentRunConfig
from rubric_gen.biomnibench.cli import build_parser
from rubric_gen.biomnibench.revision.seeds import (
    SeedSetConfig,
    SeedSetRunner,
    resolve_seed,
)
from rubric_gen.biomnibench.revision.judge import JudgeArtifacts


def _task(root: Path, task_id: str = "da-1-1") -> Path:
    task = root / "tasks" / task_id
    (task / "environment" / "data").mkdir(parents=True)
    (task / "instruction.md").write_text("Solve the task.\n")
    (task / "environment" / "data" / "input.csv").write_text("x\n1\n")
    return task


class _FakeAgentRunner:
    def __init__(self, config: AgentRunConfig) -> None:
        self.config = config

    def run(self, task_dir: Path, *, paths):
        paths.workspace_dir.mkdir(parents=True)
        paths.run_dir.mkdir(parents=True)
        (paths.workspace_dir / "answer.txt").write_text(f"answer for {task_dir.name}\n")
        (paths.workspace_dir / "trace.md").write_text("analysis\n")
        (paths.workspace_dir / ".uv_cache").mkdir()
        (paths.workspace_dir / ".uv_cache" / "large-wheel").write_text("excluded\n")
        paths.stream_path.write_text('{"event":"done"}\n')
        paths.status_path.write_text(json.dumps({"status": "completed"}))
        return 0, paths


def _fake_judgment(
    config: SeedSetConfig, task_dir: Path, submission: Path, experiment_dir: Path
):
    del config, task_dir, submission
    experiment_dir.mkdir(parents=True)
    evaluation = experiment_dir / "evaluation.json"
    validation = experiment_dir / "score_validation.json"
    evaluation.write_text('{"score":80}\n')
    validation.write_text('{"score":80}\n')
    identity = {
        "scorer_version": "test", "judge_source_sha256": "1" * 64,
        "judge_runner_sha256": "2" * 64, "scorer_module_sha256": "3" * 64,
        "effective_judge_model": "test-judge", "review_mode": "trace",
        "max_review_chars": None, "rubric_source": "task-local",
        "rubric_set_id": None, "rubric_id": None,
        "structured_rubric_sha256": None, "rendered_rubric_sha256": "4" * 64,
        "manifest_sha256": None,
    }
    return JudgeArtifacts(validation, evaluation), identity


def test_seed_set_is_compact_immutable_and_integrity_checked(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(tmp_path)
    output = tmp_path / "seed-set"
    progress_events: list[tuple[str, str]] = []
    judge_roots: list[Path] = []

    class _Progress:
        def __init__(self, *, description: str, **kwargs: object) -> None:
            del kwargs
            self.description = description

        def __enter__(self):
            progress_events.append((self.description, "opened"))
            return self

        def __exit__(self, *args: object) -> None:
            del args

        def set_status(self, status: str) -> None:
            progress_events.append((self.description, status))

        def update(self) -> None:
            progress_events.append((self.description, "updated"))

    monkeypatch.setattr(seeds_module, "AgentRunner", _FakeAgentRunner)
    monkeypatch.setattr(seeds_module, "TerminalProgress", _Progress)
    def record_judgment(*args, **kwargs):
        judge_roots.append(args[3])
        return _fake_judgment(*args, **kwargs)

    monkeypatch.setattr(seeds_module, "_judge_initial_submission", record_judgment)

    exit_code = SeedSetRunner(SeedSetConfig(
        tasks_dir=tmp_path / "tasks",
        output_dir=output,
        agent=AgentRunConfig(provider="gemini", model="test-model"),
        top=-1,
        max_concurrency=1,
    )).run()

    assert exit_code == 0
    seed = resolve_seed(output, task)
    assert (seed.submission_dir / "workspace" / "answer.txt").is_file()
    assert not (seed.submission_dir / "workspace" / ".uv_cache").exists()
    assert json.loads((output / "manifest.json").read_text())["status"] == "completed"
    assert ("seed batch", "updated") in progress_events
    assert ("seed da-1-1", "solver") in progress_events
    assert ("seed da-1-1", "judge") in progress_events
    assert judge_roots == [output / "tasks" / task.name / ".initial-judge-work"]
    assert not judge_roots[0].exists()
    assert ("seed da-1-1", "updated") in progress_events
    assert not (seed.submission_dir / "workspace" / "answer.txt").stat().st_mode & 0o200

    answer = seed.submission_dir / "workspace" / "answer.txt"
    answer.chmod(answer.stat().st_mode | 0o200)
    answer.write_text("tampered\n")
    with pytest.raises(RuntimeError, match="integrity check failed"):
        resolve_seed(output, task)


def test_seed_set_refuses_to_overwrite(tmp_path: Path) -> None:
    output = tmp_path / "seed-set"
    output.mkdir()
    with pytest.raises(FileExistsError, match="already exists"):
        SeedSetRunner(SeedSetConfig(
            tasks_dir=tmp_path / "tasks",
            output_dir=output,
            agent=AgentRunConfig(provider="gemini", model="test-model"),
            top=-1,
            max_concurrency=1,
        )).run()


def test_seed_set_records_task_system_exit_instead_of_aborting_batch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _task(tmp_path)
    output = tmp_path / "seed-set"
    monkeypatch.setattr(seeds_module, "AgentRunner", _FakeAgentRunner)

    def reject_judgment(*args: object, **kwargs: object):
        raise SystemExit("invalid staged judge layout")

    monkeypatch.setattr(
        seeds_module, "_judge_initial_submission", reject_judgment
    )

    assert SeedSetRunner(SeedSetConfig(
        tasks_dir=tmp_path / "tasks",
        output_dir=output,
        agent=AgentRunConfig(provider="gemini", model="test-model"),
        top=-1,
        max_concurrency=1,
    )).run() == 1
    manifest = json.loads((output / "manifest.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["failures"] == [{
        "task_id": "da-1-1",
        "error_type": "SystemExit",
        "error": "invalid staged judge layout",
    }]


def test_seed_resume_reuses_valid_tasks_and_runs_only_missing_tasks(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = _task(tmp_path, "da-1-1")
    _task(tmp_path, "da-1-2")
    output = tmp_path / "seed-set"
    calls: list[str] = []

    class _FailsSecond(_FakeAgentRunner):
        def run(self, task_dir: Path, *, paths):
            calls.append(task_dir.name)
            exit_code, paths = super().run(task_dir, paths=paths)
            return (1 if task_dir.name == "da-1-2" else exit_code), paths

    monkeypatch.setattr(seeds_module, "AgentRunner", _FailsSecond)
    monkeypatch.setattr(seeds_module, "_judge_initial_submission", _fake_judgment)
    config = SeedSetConfig(
        tasks_dir=tmp_path / "tasks",
        output_dir=output,
        agent=AgentRunConfig(provider="gemini", model="test-model"),
        top=-1,
        max_concurrency=2,
    )
    assert SeedSetRunner(config).run() == 1
    first_inode = (
        output / "tasks" / first.name / "submission" / "workspace" / "answer.txt"
    ).stat().st_ino

    class _Succeeds(_FakeAgentRunner):
        def run(self, task_dir: Path, *, paths):
            calls.append(task_dir.name)
            return super().run(task_dir, paths=paths)

    monkeypatch.setattr(seeds_module, "AgentRunner", _Succeeds)
    assert SeedSetRunner(
        SeedSetConfig(**{**config.__dict__, "resume": True})
    ).run() == 0

    assert calls.count("da-1-1") == 1
    assert calls.count("da-1-2") == 2
    assert (
        output / "tasks" / first.name / "submission" / "workspace" / "answer.txt"
    ).stat().st_ino == first_inode
    assert json.loads((output / "manifest.json").read_text())["status"] == "completed"
    resolve_seed(output, first)


def test_seed_cli_accepts_resume() -> None:
    args = build_parser().parse_args([
        "seed",
        "--output-dir",
        "seed-output",
        "--model",
        "test-model",
        "--resume",
    ])
    assert args.resume is True
