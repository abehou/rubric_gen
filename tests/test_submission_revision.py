from __future__ import annotations

import hashlib
import json
import os
import re
import signal
import stat
import threading
from dataclasses import replace
from pathlib import Path
from typing import Callable

import pytest

import rubric_gen.biomnibench.cli as cli_module
import rubric_gen.biomnibench.commands as commands_module
import rubric_gen.biomnibench.revision as submission_revision_module
import rubric_gen.biomnibench.revision.artifacts as revision_artifacts_module
import rubric_gen.biomnibench.revision.controller as revision_controller_module
import rubric_gen.biomnibench.revision.reports as revision_reports_module
from rubric_gen.biomnibench.agent.models import AgentRunConfig
from rubric_gen.biomnibench.agent.prompts import PromptMitigation
from rubric_gen.biomnibench.cli import build_parser
from rubric_gen.biomnibench.agent.sessions import SessionTurnResult
from rubric_gen.biomnibench.revision.feedback import (
    FeedbackPolicy,
    project_feedback,
)
from rubric_gen.biomnibench.revision.artifacts import (
    remove_revision_experiment,
)
from rubric_gen.biomnibench.revision import (
    JudgeArtifacts,
    RevisionDependencies,
    SubmissionRevisionConfig,
    SubmissionRevisionController,
)
from rubric_gen.biomnibench.utils.paths import PROJECT_ROOT


def _write_task(root: Path, task_id: str = "da-1-1") -> Path:
    task = root / "tasks" / task_id
    (task / "environment" / "data").mkdir(parents=True)
    (task / "tests").mkdir()
    (task / "instruction.md").write_text("Analyze the supplied table.\n")
    (task / "environment" / "data" / "values.csv").write_text("x\n1\n")
    (task / "tests" / "rubric.txt").write_text(
        "Criterion 1: Correct result\nLevels: A=100 B=50 C=0\n"
    )
    return task


class FakeSessionDriver:
    def __init__(self) -> None:
        self.prompts: list[str] = []
        self.session_ids: list[str] = []
        self.start_count = 0

    def start(
        self,
        workspace: Path,
        prompt: str,
        turn_dir: Path,
        *,
        on_session_id: Callable[[str], None] | None = None,
    ) -> SessionTurnResult:
        self.start_count += 1
        self.prompts.append(prompt)
        self.session_ids.append("solver-session")
        if on_session_id is not None:
            on_session_id("solver-session")
        return self._turn(workspace, turn_dir, 0)

    def resume(
        self,
        workspace: Path,
        prompt: str,
        turn_dir: Path,
        session_id: str,
    ) -> SessionTurnResult:
        self.prompts.append(prompt)
        self.session_ids.append(session_id)
        return self._turn(workspace, turn_dir, len(self.prompts) - 1)

    def _turn(self, workspace: Path, turn_dir: Path, index: int) -> SessionTurnResult:
        turn_dir.mkdir(parents=True, exist_ok=True)
        trajectory = turn_dir / "trajectory.stream.jsonl"
        trajectory.write_text(json.dumps({"turn": index}) + "\n")
        (workspace / "answer.txt").write_text(f"answer-{index}\n")
        (workspace / "trace.md").write_text(f"trace-{index}\n")
        (workspace / "analysis.py").write_text(f"ROUND = {index}\n")
        return SessionTurnResult(
            session_id="solver-session",
            model="test-model",
            exit_code=0,
            trajectory_path=trajectory,
        )


class StreamExhaustionSessionDriver(FakeSessionDriver):
    def resume(
        self,
        workspace: Path,
        prompt: str,
        turn_dir: Path,
        session_id: str,
    ) -> SessionTurnResult:
        self.prompts.append(prompt)
        self.session_ids.append(session_id)
        result = self._turn(workspace, turn_dir, 1)
        attempts = [
            {
                "attempt": index,
                "process_exit_code": 0,
                "exit_code": 1,
                "stream_errors": ["trajectory_error: Invalid stream"],
            }
            for index in range(1, 7)
        ]
        (turn_dir / "status.json").write_text(
            json.dumps(
                {
                    "provider": "gemini",
                    "session_id": session_id,
                    "model": "test-model",
                    "exit_code": 1,
                    "attempt_count": 6,
                    "max_retries": 5,
                    "attempts": attempts,
                    "transport_exit_code": 1,
                }
            )
        )
        return replace(result, exit_code=1)


class FakeJudge:
    def __init__(
        self,
        scores: tuple[int, ...],
        rubric_sha256: str,
        output_root: Path,
    ) -> None:
        self.scores = scores
        self.rubric_sha256 = rubric_sha256
        self.output_root = output_root
        self.submissions: list[str] = []

    def scoring_identity(self) -> dict[str, object]:
        return {
            "scorer_version": "test-scorer-v1",
            "judge_source_sha256": "1" * 64,
            "judge_runner_sha256": "2" * 64,
            "scorer_module_sha256": "3" * 64,
            "effective_judge_model": "test-judge-model",
            "review_mode": "trajectory",
            "max_review_chars": None,
            "rubric_source": "task-local",
            "rubric_set_id": None,
            "rubric_id": None,
            "structured_rubric_sha256": None,
            "rendered_rubric_sha256": self.rubric_sha256,
            "manifest_sha256": None,
        }

    def evaluate(self, submission_dir: Path, attempt_id: str) -> JudgeArtifacts:
        index = len(self.submissions)
        self.submissions.append(submission_dir.name)
        output = self.output_root / submission_dir.name / attempt_id
        output.mkdir(parents=True)
        level = "A" if self.scores[index] >= 80 else "B"
        evaluation = {
            "criteria": {
                "criterion_1": {
                    "level": level,
                    "reason": f"feedback-{index}",
                }
            },
            "reasoning": f"overall-{index}",
        }
        evaluation_path = output / "evaluation.json"
        evaluation_path.write_text(json.dumps(evaluation))
        evaluation_sha256 = hashlib.sha256(evaluation_path.read_bytes()).hexdigest()
        validation_path = output / "score_validation.json"
        validation_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "scorer_version": "test-scorer-v1",
                    "review_input_sha256": hashlib.sha256(
                        f"trace-{index}\n".encode()
                    ).hexdigest(),
                    "answer_input_sha256": hashlib.sha256(
                        f"answer-{index}\n".encode()
                    ).hexdigest(),
                    "judge_source_sha256": "1" * 64,
                    "judge_runner_sha256": "2" * 64,
                    "scorer_module_sha256": "3" * 64,
                    "effective_judge_model": "test-judge-model",
                    "review_mode": "trajectory",
                    "max_review_chars": None,
                    "task": "da-1-1",
                    "run_identity": f"run-{index}",
                    "repeat_index": 1,
                    "score": self.scores[index],
                    "raw_score": self.scores[index],
                    "selected_levels": {"criterion_1": level},
                    "criterion_scores": {"criterion_1": self.scores[index]},
                    "rendered_rubric_sha256": self.rubric_sha256,
                    "rubric_source": "task-local",
                    "rubric_set_id": None,
                    "rubric_id": None,
                    "structured_rubric_sha256": None,
                    "manifest_sha256": None,
                    "evaluation_sha256": evaluation_sha256,
                }
            )
        )
        return JudgeArtifacts(
            score_validation_path=validation_path,
            evaluation_path=evaluation_path,
        )

    def validate(self, submission_dir: Path, attempt_id: str) -> JudgeArtifacts:
        output = self.output_root / submission_dir.name / attempt_id
        return JudgeArtifacts(
            score_validation_path=output / "score_validation.json",
            evaluation_path=output / "evaluation.json",
        )


def test_linear_revision_keeps_one_session_and_continues_after_regression(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    progress_calls: list[tuple[int, int, dict[str, object]]] = []

    def fake_trange(start: int, stop: int, **kwargs: object) -> range:
        progress_calls.append((start, stop, kwargs))
        return range(start, stop)

    monkeypatch.setattr(
        revision_controller_module,
        "trange",
        fake_trange,
    )
    task = _write_task(tmp_path)
    session = FakeSessionDriver()
    rubric_text = (task / "tests" / "rubric.txt").read_text()
    judge = FakeJudge(
        (80, 55, 70),
        hashlib.sha256(rubric_text.encode("utf-8")).hexdigest(),
        tmp_path / "fake-judge",
    )
    config = SubmissionRevisionConfig(
        task_dir=task,
        experiment_dir=tmp_path / "experiment",
        revision_rounds=2,
        agent=AgentRunConfig(provider="gemini", model="test-model"),
        feedback_policy=FeedbackPolicy.FULL,
        rubric_name="rubric.txt",
    )

    class StopAfterFirstJudge(SubmissionRevisionController):
        stopped = False

        def _append_event(self, payload: dict[str, object]) -> None:
            super()._append_event(payload)
            if (
                not self.stopped
                and payload.get("event") == "submission_judged"
                and payload.get("submission_id") == "s000"
            ):
                self.stopped = True
                raise KeyboardInterrupt

    dependencies = RevisionDependencies(session=session, judge=judge)
    with pytest.raises(KeyboardInterrupt):
        StopAfterFirstJudge(config, dependencies).run()

    score_plot_path = config.experiment_dir / "score_improvement.png"
    first_score_plot = score_plot_path.read_bytes()
    assert first_score_plot.startswith(b"\x89PNG\r\n\x1a\n")

    manifest = json.loads((config.experiment_dir / "manifest.json").read_text())
    retained_live_root = Path(manifest["live_workspace_dir"]).parent
    assert retained_live_root.is_dir()
    assert manifest["effective_solver_model"] == "test-model"
    assert manifest["scoring_identity"]["effective_judge_model"] == ("test-judge-model")

    class StopAfterSecondJudge(SubmissionRevisionController):
        def _append_event(self, payload: dict[str, object]) -> None:
            super()._append_event(payload)
            if (
                payload.get("event") == "submission_judged"
                and payload.get("submission_id") == "s001"
            ):
                raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        StopAfterSecondJudge(
            replace(config, resume=True),
            dependencies,
        ).run()

    second_score_plot = score_plot_path.read_bytes()
    assert second_score_plot.startswith(b"\x89PNG\r\n\x1a\n")
    assert second_score_plot != first_score_plot

    interrupted_manifest = json.loads(
        (config.experiment_dir / "manifest.json").read_text()
    )
    assert interrupted_manifest["live_workspace_removed"] is False
    assert retained_live_root.is_dir()

    result = SubmissionRevisionController(
        replace(config, resume=True),
        dependencies,
    ).run()

    assert result.session_id == "solver-session"
    assert result.submission_ids == ("s000", "s001", "s002")
    assert result.scores == (80, 55, 70)
    final_score_plot = score_plot_path.read_bytes()
    assert final_score_plot.startswith(b"\x89PNG\r\n\x1a\n")
    assert final_score_plot != second_score_plot
    assert session.session_ids == ["solver-session"] * 3
    assert session.start_count == 1
    assert "Criterion 1" not in session.prompts[0]
    assert "feedback-0" in session.prompts[1]
    assert "feedback-1" in session.prompts[2]
    assert judge.submissions == ["s000", "s001", "s002"]
    assert (
        config.experiment_dir / "submissions" / "s001" / "workspace" / "answer.txt"
    ).read_text() == "answer-1\n"
    assert (
        config.experiment_dir / "submissions" / "s002" / "workspace" / "answer.txt"
    ).read_text() == "answer-2\n"
    assert not (
        config.experiment_dir / "submissions" / "s001" / "workspace" / "analysis.py"
    ).exists()
    assert (
        config.experiment_dir / "submissions" / "s002" / "workspace" / "analysis.py"
    ).read_text() == "ROUND = 2\n"
    historical_snapshot = json.loads(
        (
            config.experiment_dir / "submissions" / "s001" / "snapshot.json"
        ).read_text()
    )
    assert historical_snapshot["workspace_scope"] == "judge-inputs"
    assert historical_snapshot["historical_workspace_files_removed"] == 1
    snapshot_mode = (
        (config.experiment_dir / "submissions" / "s000" / "workspace" / "answer.txt")
        .stat()
        .st_mode
    )
    assert not snapshot_mode & stat.S_IWUSR
    cumulative = (
        config.experiment_dir / "submissions" / "s002" / "trajectory.stream.jsonl"
    ).read_text()
    assert [json.loads(line)["turn"] for line in cumulative.splitlines()] == [0, 1, 2]
    assert not retained_live_root.exists()
    assert [(start, stop) for start, stop, _ in progress_calls] == [
        (0, 3),
        (1, 3),
        (2, 3),
    ]
    assert [kwargs["initial"] for _, _, kwargs in progress_calls] == [0, 1, 2]
    assert all(kwargs["total"] == 3 for _, _, kwargs in progress_calls)
    assert all(kwargs["unit"] == "round" for _, _, kwargs in progress_calls)


def test_resume_does_not_accept_failed_turn_after_stream_retry_exhaustion(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    session = StreamExhaustionSessionDriver()
    rubric_text = (task / "tests" / "rubric.txt").read_text()
    judge = FakeJudge(
        (60, 85),
        hashlib.sha256(rubric_text.encode("utf-8")).hexdigest(),
        tmp_path / "fake-judge",
    )
    config = SubmissionRevisionConfig(
        task_dir=task,
        experiment_dir=tmp_path / "experiment",
        revision_rounds=1,
        agent=AgentRunConfig(
            provider="gemini",
            model="test-model",
            retries=5,
        ),
        feedback_policy=FeedbackPolicy.FULL,
        rubric_name="rubric.txt",
    )
    dependencies = RevisionDependencies(session=session, judge=judge)

    with pytest.raises(RuntimeError, match="provider exited with code 1"):
        SubmissionRevisionController(config, dependencies).run()

    failed_status_path = config.experiment_dir / "turns" / "turn-001" / "status.json"
    assert json.loads(failed_status_path.read_text())["status"] == "failed"

    with pytest.raises(RuntimeError, match="provider exited with code 1"):
        SubmissionRevisionController(
            replace(config, resume=True),
            dependencies,
        ).run()

    assert len(session.prompts) == 3
    recovered_status = json.loads(failed_status_path.read_text())
    assert recovered_status["status"] == "failed"
    assert recovered_status["exit_code"] == 1
    assert recovered_status["transport_exit_code"] == 1
    assert "accepted_after_retry_exhaustion" not in recovered_status


@pytest.mark.parametrize(
    ("cache_name", "interrupted", "expected_recovery_status"),
    (
        (".uv_cache", False, "accepted_after_cache_exclusion"),
        (".uv-cache", False, "accepted_after_cache_exclusion"),
        (".uv_cache", True, "accepted_after_interrupted_boundary"),
    ),
)
def test_resume_recovers_legacy_workspace_cache_snapshot_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    cache_name: str,
    interrupted: bool,
    expected_recovery_status: str,
) -> None:
    task = _write_task(tmp_path)
    session = FakeSessionDriver()
    rubric_text = (task / "tests" / "rubric.txt").read_text()
    judge = FakeJudge(
        (80,),
        hashlib.sha256(rubric_text.encode("utf-8")).hexdigest(),
        tmp_path / "fake-judge",
    )
    config = SubmissionRevisionConfig(
        task_dir=task,
        experiment_dir=tmp_path / "experiment",
        revision_rounds=0,
        agent=AgentRunConfig(
            provider="gemini",
            model="test-model",
            retries=5,
        ),
        rubric_name="rubric.txt",
    )
    dependencies = RevisionDependencies(session=session, judge=judge)
    original_solution_hash = revision_controller_module._solution_tree_sha256
    monkeypatch.setattr(
        revision_controller_module,
        "_solution_tree_sha256",
        lambda workspace: (_ for _ in ()).throw(
            RuntimeError(
                "snapshot contains a non-regular file: "
                f"{cache_name}/wheels-v6/example"
            )
        ),
    )

    with pytest.raises(RuntimeError, match="snapshot contains a non-regular file"):
        SubmissionRevisionController(config, dependencies).run()

    status_path = config.experiment_dir / "turns" / "turn-000" / "status.json"
    status_path.chmod(status_path.stat().st_mode | stat.S_IWUSR)
    status = json.loads(status_path.read_text())
    status.update(
        {
            "attempt_count": 1,
            "max_retries": 5,
            "attempts": [
                {
                    "process_exit_code": 0,
                    "stream_errors": [],
                    "output_errors": [],
                }
            ],
            "transport_exit_code": 0,
        }
    )
    if interrupted:
        state_path = config.experiment_dir / "state.json"
        state = json.loads(state_path.read_text())
        state["phase"] = "turn_in_progress"
        state_path.write_text(json.dumps(state))
        status.pop("status", None)
        status.pop("validation_errors", None)
        status["exit_code"] = 0
    status_path.write_text(json.dumps(status))
    monkeypatch.setattr(
        revision_controller_module,
        "_solution_tree_sha256",
        original_solution_hash,
    )

    result = SubmissionRevisionController(
        replace(config, resume=True), dependencies
    ).run()

    assert result.submission_ids == ("s000",)
    assert result.scores == (80,)
    recovered_status = json.loads(status_path.read_text())
    assert recovered_status["status"] == expected_recovery_status
    assert recovered_status["recovered_on_resume"] is True


def test_resume_archives_and_retries_an_unrecoverable_failed_turn(
    tmp_path: Path,
) -> None:
    class FirstAttemptFails(FakeSessionDriver):
        def start(
            self,
            workspace: Path,
            prompt: str,
            turn_dir: Path,
            *,
            on_session_id: Callable[[str], None] | None = None,
        ) -> SessionTurnResult:
            result = super().start(
                workspace,
                prompt,
                turn_dir,
                on_session_id=on_session_id,
            )
            return replace(result, exit_code=1)

        def resume(
            self,
            workspace: Path,
            prompt: str,
            turn_dir: Path,
            session_id: str,
        ) -> SessionTurnResult:
            self.prompts.append(prompt)
            self.session_ids.append(session_id)
            return self._turn(workspace, turn_dir, 0)

    task = _write_task(tmp_path)
    session = FirstAttemptFails()
    rubric_text = (task / "tests" / "rubric.txt").read_text()
    judge = FakeJudge(
        (80,),
        hashlib.sha256(rubric_text.encode("utf-8")).hexdigest(),
        tmp_path / "fake-judge",
    )
    config = SubmissionRevisionConfig(
        task_dir=task,
        experiment_dir=tmp_path / "experiment",
        revision_rounds=0,
        agent=AgentRunConfig(provider="gemini", model="test-model"),
        rubric_name="rubric.txt",
    )
    dependencies = RevisionDependencies(session=session, judge=judge)

    with pytest.raises(RuntimeError, match="provider exited with code 1"):
        SubmissionRevisionController(config, dependencies).run()

    result = SubmissionRevisionController(
        replace(config, resume=True), dependencies
    ).run()

    assert result.submission_ids == ("s000",)
    assert session.start_count == 1
    assert len(session.prompts) == 2
    assert (
        config.experiment_dir / "interrupted-turns" / "turn-000" / "status.json"
    ).is_file()


def test_resume_archives_and_retries_a_prompt_only_interrupted_turn(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    session = FakeSessionDriver()
    rubric_text = (task / "tests" / "rubric.txt").read_text()
    judge = FakeJudge(
        (60, 85),
        hashlib.sha256(rubric_text.encode("utf-8")).hexdigest(),
        tmp_path / "fake-judge",
    )
    config = SubmissionRevisionConfig(
        task_dir=task,
        experiment_dir=tmp_path / "experiment",
        revision_rounds=1,
        agent=AgentRunConfig(provider="gemini", model="test-model"),
        rubric_name="rubric.txt",
    )
    dependencies = RevisionDependencies(session=session, judge=judge)
    original_resume = session.resume

    def interrupt_after_prompt(
        workspace: Path,
        prompt: str,
        turn_dir: Path,
        session_id: str,
    ) -> SessionTurnResult:
        raise KeyboardInterrupt

    session.resume = interrupt_after_prompt  # type: ignore[method-assign]
    with pytest.raises(KeyboardInterrupt):
        SubmissionRevisionController(config, dependencies).run()

    turn_dir = config.experiment_dir / "turns" / "turn-001"
    turn_dir.chmod(turn_dir.stat().st_mode | stat.S_IWUSR)
    (turn_dir / "status.json").unlink()
    state_path = config.experiment_dir / "state.json"
    state = json.loads(state_path.read_text())
    state["phase"] = "turn_in_progress"
    state_path.write_text(json.dumps(state))
    assert sorted(path.name for path in turn_dir.iterdir()) == ["prompt.txt"]

    session.resume = original_resume  # type: ignore[method-assign]
    result = SubmissionRevisionController(
        replace(config, resume=True), dependencies
    ).run()

    assert result.submission_ids == ("s000", "s001")
    assert (
        config.experiment_dir / "interrupted-turns" / "turn-001" / "prompt.txt"
    ).is_file()


def test_restart_replaces_an_interrupted_experiment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _write_task(tmp_path)
    experiment_dir = tmp_path / "experiment"
    args = build_parser().parse_args(
        [
            "revise",
            str(task),
            "--experiment-dir",
            str(experiment_dir),
            "--revision-rounds",
            "0",
            "--model",
            "test-model",
            "--restart",
        ]
    )
    restart_config = SubmissionRevisionConfig.from_namespace(args)
    experiment_dir = restart_config.experiment_dir
    initial_config = replace(restart_config, restart=False)
    rubric_text = (task / "tests" / "rubric.txt").read_text()
    rubric_sha256 = hashlib.sha256(rubric_text.encode("utf-8")).hexdigest()

    class InterruptAfterJudge(SubmissionRevisionController):
        def _append_event(self, payload: dict[str, object]) -> None:
            super()._append_event(payload)
            if payload.get("event") == "submission_judged":
                raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        InterruptAfterJudge(
            initial_config,
            RevisionDependencies(
                session=FakeSessionDriver(),
                judge=FakeJudge((60,), rubric_sha256, tmp_path / "old-judge"),
            ),
        ).run()

    manifest = json.loads((experiment_dir / "manifest.json").read_text())
    old_live_root = Path(manifest["live_workspace_dir"]).parent
    assert old_live_root.is_dir()
    manifest.pop("kind")
    (experiment_dir / "manifest.json").write_text(json.dumps(manifest))

    original_remove = revision_artifacts_module._force_remove_directory
    failed_once = False

    def fail_first_experiment_removal(root: Path) -> None:
        nonlocal failed_once
        if root == experiment_dir and not failed_once:
            failed_once = True
            raise OSError("injected experiment cleanup failure")
        original_remove(root)

    monkeypatch.setattr(
        revision_artifacts_module,
        "_force_remove_directory",
        fail_first_experiment_removal,
    )
    with pytest.raises(OSError, match="injected experiment cleanup failure"):
        SubmissionRevisionController(
            restart_config,
            RevisionDependencies(
                session=FakeSessionDriver(),
                judge=FakeJudge((95,), rubric_sha256, tmp_path / "unused-judge"),
            ),
        ).run()
    assert experiment_dir.is_dir()
    assert not old_live_root.exists()

    result = SubmissionRevisionController(
        restart_config,
        RevisionDependencies(
            session=FakeSessionDriver(),
            judge=FakeJudge((95,), rubric_sha256, tmp_path / "new-judge"),
        ),
    ).run()

    assert result.submission_ids == ("s000",)
    assert result.scores == (95,)
    assert not old_live_root.exists()


def test_revise_cli_suppresses_success_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task = _write_task(tmp_path)
    args = build_parser().parse_args(
        [
            "revise",
            str(task),
            "--experiment-dir",
            str(tmp_path / "experiment"),
            "--model",
            "test-model",
        ]
    )
    config = SubmissionRevisionConfig.from_namespace(args)
    observed_configs: list[SubmissionRevisionConfig] = []
    monkeypatch.setattr(
        commands_module,
        "run_submission_revision",
        lambda received: observed_configs.append(received),
    )

    assert cli_module.run_revise(args) == 0
    assert observed_configs == [config]
    assert config.agent.quiet is True
    assert config.agent.retries == 5
    assert capsys.readouterr().out == ""


def test_revision_live_root_can_be_redirected_to_bulk_storage(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bulk_root = tmp_path / "bulk" / "biomnibench-live"
    monkeypatch.setenv("BIOMNIBENCH_LIVE_ROOT", str(bulk_root))

    assert revision_artifacts_module.live_root_parent() == bulk_root
    assert bulk_root.is_dir()


def test_revision_live_root_defaults_to_repository(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BIOMNIBENCH_LIVE_ROOT", raising=False)

    assert revision_artifacts_module.live_root_parent() == (
        PROJECT_ROOT / "tmp" / "biomnibench-live"
    )


def test_solution_snapshot_excludes_disposable_local_uv_cache(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "answer.txt").write_text("answer\n")
    (workspace / "trace.md").write_text("trace\n")
    cache_target = tmp_path / "bulk-cache"
    cache_target.mkdir()
    (workspace / ".uv_cache").symlink_to(cache_target, target_is_directory=True)

    digest = revision_artifacts_module.solution_tree_sha256(workspace)
    snapshot = tmp_path / "snapshot"
    revision_artifacts_module.copy_solution_workspace(workspace, snapshot)

    assert len(digest) == 64
    assert not (snapshot / ".uv_cache").exists()
    assert (snapshot / "answer.txt").read_text() == "answer\n"


def test_solution_snapshot_deduplicates_unchanged_files_from_previous_round(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "answer.txt").write_text("answer-0\n")
    (workspace / "large-result.bin").write_bytes(b"result" * 1024)
    (workspace / "nested").mkdir()
    (workspace / "nested" / "stable.csv").write_text("x\n1\n")
    first = tmp_path / "s000"

    first_stats = revision_artifacts_module.copy_solution_workspace(workspace, first)
    (workspace / "answer.txt").write_text("answer-1\n")
    second = tmp_path / "s001"
    second_stats = revision_artifacts_module.copy_solution_workspace(
        workspace,
        second,
        previous=first,
    )

    assert first_stats.linked_files == 0
    assert second_stats.copied_files == 1
    assert second_stats.linked_files == 2
    assert second_stats.linked_bytes == len(b"result" * 1024) + len("x\n1\n")
    assert (first / "large-result.bin").stat().st_ino == (
        second / "large-result.bin"
    ).stat().st_ino
    assert (first / "nested" / "stable.csv").stat().st_ino == (
        second / "nested" / "stable.csv"
    ).stat().st_ino
    assert (first / "answer.txt").stat().st_ino != (
        second / "answer.txt"
    ).stat().st_ino


def test_solution_snapshot_excludes_disposable_dependency_directories(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "answer.txt").write_text("answer\n")
    for name in (".venv", "venv", "packages"):
        dependency = workspace / name
        dependency.mkdir()
        (dependency / "large-library.so").write_bytes(b"library")

    snapshot = tmp_path / "snapshot"
    stats = revision_artifacts_module.copy_solution_workspace(workspace, snapshot)

    assert (snapshot / "answer.txt").is_file()
    assert stats.copied_files == 1
    for name in (".venv", "venv", "packages"):
        assert not (snapshot / name).exists()


def test_historical_workspace_compaction_keeps_only_judge_inputs(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    nested = workspace / "derived"
    nested.mkdir(parents=True)
    (workspace / "answer.txt").write_text("answer\n")
    (workspace / "trace.md").write_text("trace\n")
    (workspace / "analysis.py").write_text("print('work')\n")
    (nested / "large-result.bin").write_bytes(b"result" * 1024)
    revision_artifacts_module.make_tree_read_only(workspace)

    stats = revision_artifacts_module.compact_historical_workspace(workspace)

    assert sorted(path.name for path in workspace.iterdir()) == [
        "answer.txt",
        "trace.md",
    ]
    assert stats.removed_files == 2
    assert stats.removed_logical_bytes == len("print('work')\n") + len(
        b"result" * 1024
    )
    assert not workspace.stat().st_mode & stat.S_IWUSR

    repeated = revision_artifacts_module.compact_historical_workspace(workspace)
    assert repeated.removed_files == 0
    assert repeated.removed_logical_bytes == 0


def test_evaluation_run_hard_links_immutable_submission_inputs(tmp_path: Path) -> None:
    submission = tmp_path / "submission"
    workspace = submission / "workspace"
    nested = workspace / "nested"
    nested.mkdir(parents=True)
    (workspace / "answer.txt").write_text("answer\n")
    (nested / "result.txt").write_text("result\n")
    (submission / "trajectory.stream.jsonl").write_text('{"turn": 0}\n')
    (submission / "status.json").write_text(
        json.dumps(
            {
                "task": "da-1-1",
                "workspace_dir": str(workspace),
            }
        )
    )

    run = revision_artifacts_module.prepare_evaluation_run(
        submission,
        tmp_path / "evaluation",
    )

    assert (run / "workspace" / "answer.txt").stat().st_ino == (
        workspace / "answer.txt"
    ).stat().st_ino
    assert (run / "workspace" / "nested" / "result.txt").stat().st_ino == (
        nested / "result.txt"
    ).stat().st_ino
    assert (run / "trajectory.stream.jsonl").stat().st_ino == (
        submission / "trajectory.stream.jsonl"
    ).stat().st_ino
    assert json.loads((run / "status.json").read_text())["workspace_dir"] == str(
        run / "workspace"
    )


def test_revision_report_contains_only_plot_and_compact_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    experiment = tmp_path / "revision-test"
    experiment.mkdir()
    (experiment / "score_improvement.png").write_bytes(b"plot")
    (experiment / "manifest.json").write_text(
        json.dumps(
            {
                "task_id": "da-1-1",
                "revision_rounds": 2,
                "feedback_policy": "full",
                "mitigation": "prompt",
                "provider": "gemini",
                "model": "solver-model",
                "judge_model": "judge-model",
                "review": "trajectory",
                "rubric_name": "rubric.txt",
                "rubric_set": None,
            }
        )
    )
    (experiment / "state.json").write_text(
        json.dumps({"phase": "ready_for_turn", "scores": [60, 80]})
    )
    reports_root = tmp_path / "reports"
    monkeypatch.setenv("BIOMNIBENCH_REPORTS_ROOT", str(reports_root))

    report = revision_reports_module.publish_revision_report(experiment)

    assert report == reports_root / "revision-test" / "da-1-1"
    assert {path.name for path in report.iterdir()} == {
        "score_improvement.png",
        "summary.json",
    }
    summary = json.loads((report / "summary.json").read_text())
    assert summary["task_id"] == "da-1-1"
    assert summary["scores"] == [60, 80]
    assert summary["completed_rounds"] == 2
    assert summary["total_rounds"] == 3


def test_revise_cli_generates_one_timestamped_base_for_a_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_task(tmp_path, "da-1-1")
    _write_task(tmp_path, "da-1-2")
    generated_base = tmp_path / "revision" / "revision-20260717-120000"
    args = build_parser().parse_args(
        [
            "revise",
            "--top",
            "1",
            "--full-v-score",
            "--tasks-dir",
            str(tmp_path / "tasks"),
            "--revision-rounds",
            "0",
            "--model",
            "test-model",
        ]
    )
    observed: list[SubmissionRevisionConfig] = []
    monkeypatch.setattr(
        commands_module,
        "_timestamped_revision_experiment_dir",
        lambda args: generated_base,
    )
    monkeypatch.setattr(
        commands_module,
        "run_submission_revision",
        lambda config: observed.append(config),
    )

    assert cli_module.run_revise(args) == 0
    assert len(observed) == 2
    assert {config.experiment_dir for config in observed} == {
        generated_base / "da-1-1" / "full",
        generated_base / "da-1-1" / "score-only",
    }
    batch = json.loads((generated_base / "batch.json").read_text())
    assert batch["kind"] == "rubric-gen-submission-revision-batch"
    assert batch["status"] == "completed"
    assert batch["run_name"] == generated_base.name
    assert batch["configuration"] == {
        "provider": "gemini",
        "solver_model": "test-model",
        "judge_model": "gpt-5.6-luna",
        "rubric": "rubric.txt",
        "rubric_set": None,
        "review": "trajectory",
        "mitigation": "none",
        "sandbox": False,
        "skip_trust": True,
        "allow_web": False,
        "allow_network": False,
        "approval_mode": None,
        "max_review_chars": None,
        "max_concurrency": 1,
        "executable": None,
        "raw": False,
    }


def test_revise_rejects_control_characters_in_experiment_path(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path, "da-1-1")
    args = build_parser().parse_args(
        [
            "revise",
            str(task),
            "--experiment-dir",
            str(tmp_path / "split\npath"),
            "--model",
            "test-model",
        ]
    )

    with pytest.raises(ValueError, match="control characters"):
        cli_module.run_revise(args)


def test_revise_cli_places_automatic_single_task_under_run_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _write_task(tmp_path, "da-1-1")
    generated_base = tmp_path / "revision-identity"
    args = build_parser().parse_args(
        ["revise", str(task), "--revision-rounds", "0", "--model", "test-model"]
    )
    observed: list[SubmissionRevisionConfig] = []
    monkeypatch.setattr(
        commands_module,
        "_timestamped_revision_experiment_dir",
        lambda args: generated_base,
    )
    monkeypatch.setattr(
        commands_module,
        "run_submission_revision",
        lambda config: observed.append(config),
    )

    assert cli_module.run_revise(args) == 0
    assert [config.experiment_dir for config in observed] == [
        generated_base / "da-1-1"
    ]
    assert json.loads((generated_base / "batch.json").read_text())["task_ids"] == [
        "da-1-1"
    ]


def test_revise_default_experiment_base_uses_repository() -> None:
    args = build_parser().parse_args(
        ["revise", "--top", "4", "--model", "test-model"]
    )
    generated = commands_module._timestamped_revision_experiment_dir(args)

    assert generated.parent == (
        PROJECT_ROOT / "runs" / "biomnibench-revisions"
    )
    assert re.fullmatch(
        r"revision-\d{8}-\d{6}--top-4--fb-full--mtg-none--n-3--p-gemini"
        r"--m-test-model--j-gpt-5.6-luna--rb-rubric.txt--v-trajectory--sb-0"
        r"--st-1--web-0--net-0--ap-default--mc-all--c-1--x-default--raw-0",
        generated.name,
    )
def test_revision_batch_report_path_preserves_run_and_task_hierarchy(
    tmp_path: Path,
) -> None:
    batch = tmp_path / "revision-identity-bearing"
    experiment = batch / "da-1-1" / "semi"
    experiment.mkdir(parents=True)
    (batch / "batch.json").write_text("{}\n")

    assert revision_reports_module._report_relative_directory(
        experiment, "da-1-1"
    ) == Path("revision-identity-bearing/da-1-1/semi")


def test_revise_accepts_judge_flag() -> None:
    args = build_parser().parse_args(
        ["revise", "--model", "solver-model", "--judge", "gpt-5.6-luna"]
    )

    assert args.judge_model == "gpt-5.6-luna"


def test_revise_top_resume_starts_missing_experiments(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_task(tmp_path, "da-1-1")
    _write_task(tmp_path, "da-1-2")
    args = build_parser().parse_args(
        [
            "revise",
            "--top",
            "-1",
            "--resume",
            "--tasks-dir",
            str(tmp_path / "tasks"),
            "--experiment-dir",
            str(tmp_path / "revision"),
            "--revision-rounds",
            "0",
            "--model",
            "test-model",
        ]
    )
    first = SubmissionRevisionConfig.from_namespace(
        type(args)(**{**vars(args), "task": str(tmp_path / "tasks/da-1-1")})
    )
    first.experiment_dir.mkdir(parents=True)
    observed: list[SubmissionRevisionConfig] = []
    monkeypatch.setattr(
        commands_module,
        "run_submission_revision",
        lambda config: observed.append(config),
    )

    assert cli_module.run_revise(args) == 0

    by_task = {config.task_dir.name: config for config in observed}
    assert by_task["da-1-1"].resume is True
    assert by_task["da-1-2"].resume is False


def test_revise_cli_requires_explicit_directory_for_existing_run_modes(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    args = build_parser().parse_args(
        ["revise", str(task), "--model", "test-model", "--restart"]
    )

    with pytest.raises(ValueError, match="--restart requires --experiment-dir"):
        cli_module.run_revise(args)


def test_revise_auto_resume_selects_newest_matching_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tasks = tmp_path / "tasks"
    _write_task(tmp_path, "da-1-1")
    monkeypatch.setattr(commands_module, "PROJECT_ROOT", tmp_path)
    args = build_parser().parse_args([
        "revise", "--top", "1", "--tasks-dir", str(tasks),
        "--model", "test-model", "--resume",
    ])
    runs_root = commands_module._revision_runs_root()
    for stamp in ("20260724-120000", "20260725-120000"):
        candidate = runs_root / commands_module._revision_batch_name(args, stamp)
        candidate.mkdir(parents=True)
        (candidate / "batch.json").write_text(
            json.dumps({"task_ids": ["da-1-1"]}) + "\n"
        )
    wrong = runs_root / commands_module._revision_batch_name(args, "20260726-120000")
    wrong.mkdir(parents=True)
    (wrong / "batch.json").write_text(json.dumps({"task_ids": ["da-9-9"]}) + "\n")

    selected = commands_module._latest_revision_experiment_dir(args, ["da-1-1"])
    assert selected.name.startswith("revision-20260725-120000--")


def test_revise_batch_preserves_underlying_failure_details(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_task(tmp_path, "da-1-1")
    batch = tmp_path / "revision"
    args = build_parser().parse_args([
        "revise", "--top", "1", "--tasks-dir", str(tmp_path / "tasks"),
        "--experiment-dir", str(batch), "--model", "test-model",
    ])

    def fail(config: SubmissionRevisionConfig) -> None:
        raise ValueError("specific provider failure")

    monkeypatch.setattr(commands_module, "run_submission_revision", fail)
    with pytest.raises(
        RuntimeError, match="ValueError: specific provider failure"
    ):
        cli_module.run_revise(args)

    failure = json.loads((batch / "batch.json").read_text())["failed_experiments"][0]
    assert failure["task_id"] == "da-1-1"
    assert failure["error_type"] == "ValueError"
    assert failure["error"] == "specific provider failure"
    assert "ValueError: specific provider failure" in failure["traceback"]


def test_concurrent_revise_batch_records_system_exit_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_task(tmp_path, "da-1-1")
    _write_task(tmp_path, "da-1-2")
    batch = tmp_path / "revision"
    args = build_parser().parse_args([
        "revise", "--top", "2", "--tasks-dir", str(tmp_path / "tasks"),
        "--experiment-dir", str(batch), "--model", "test-model",
        "--max-concurrency", "2",
    ])

    def fail(config: SubmissionRevisionConfig) -> None:
        if config.task_dir.name == "da-1-2":
            raise SystemExit("missing provider executable")

    monkeypatch.setattr(commands_module, "run_submission_revision", fail)
    with pytest.raises(RuntimeError, match="SystemExit: missing provider executable"):
        cli_module.run_revise(args)

    manifest = json.loads((batch / "batch.json").read_text())
    assert manifest["status"] == "failed"
    assert manifest["failed_experiments"][0]["error_type"] == "SystemExit"


def test_revise_batch_records_keyboard_interrupt(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_task(tmp_path, "da-1-1")
    batch = tmp_path / "revision"
    args = build_parser().parse_args([
        "revise", "--top", "1", "--tasks-dir", str(tmp_path / "tasks"),
        "--experiment-dir", str(batch), "--model", "test-model",
    ])

    def interrupt(config: SubmissionRevisionConfig) -> None:
        raise KeyboardInterrupt("operator interrupt")

    monkeypatch.setattr(commands_module, "run_submission_revision", interrupt)
    with pytest.raises(KeyboardInterrupt, match="operator interrupt"):
        cli_module.run_revise(args)

    manifest = json.loads((batch / "batch.json").read_text())
    assert manifest["status"] == "interrupted"
    assert manifest["interruption"]["error_type"] == "KeyboardInterrupt"
    assert manifest["interruption"]["error"] == "operator interrupt"
    assert "KeyboardInterrupt: operator interrupt" in manifest["interruption"][
        "traceback"
    ]
    assert manifest["finished_at"]


def test_revise_batch_records_sigterm(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_task(tmp_path, "da-1-1")
    batch = tmp_path / "revision"
    args = build_parser().parse_args([
        "revise", "--top", "1", "--tasks-dir", str(tmp_path / "tasks"),
        "--experiment-dir", str(batch), "--model", "test-model",
    ])

    def terminate(config: SubmissionRevisionConfig) -> None:
        os.kill(os.getpid(), signal.SIGTERM)

    monkeypatch.setattr(commands_module, "run_submission_revision", terminate)
    with pytest.raises(KeyboardInterrupt, match="received signal"):
        cli_module.run_revise(args)

    manifest = json.loads((batch / "batch.json").read_text())
    assert manifest["status"] == "interrupted"
    assert manifest["interruption"]["error_type"] == "_BatchTermination"
    assert manifest["interruption"]["error"] == (
        f"received signal {signal.SIGTERM}"
    )


def test_revise_resume_records_abandoned_running_batch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_task(tmp_path, "da-1-1")
    batch = tmp_path / "revision"
    batch.mkdir()
    (batch / "batch.json").write_text(json.dumps({
        "status": "running",
        "started_at": "2026-07-26T17:29:11-07:00",
        "pid": 1234,
        "hostname": "old-host",
    }))
    args = build_parser().parse_args([
        "revise", "--top", "1", "--resume", "--tasks-dir",
        str(tmp_path / "tasks"), "--experiment-dir", str(batch),
        "--model", "test-model",
    ])
    monkeypatch.setattr(commands_module, "run_submission_revision", lambda config: None)

    assert cli_module.run_revise(args) == 0

    manifest = json.loads((batch / "batch.json").read_text())
    assert manifest["schema_version"] == 2
    assert manifest["status"] == "completed"
    assert manifest["previous_interruption"] == {
        "status": "abandoned",
        "started_at": "2026-07-26T17:29:11-07:00",
        "pid": 1234,
        "hostname": "old-host",
        "detected_at": manifest["previous_interruption"]["detected_at"],
    }


def test_revise_cli_caps_persistent_session_retries_at_five(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)

    with pytest.raises(SystemExit):
        build_parser().parse_args(
            [
                "revise",
                str(task),
                "--experiment-dir",
                str(tmp_path / "experiment"),
                "--model",
                "test-model",
                "--retries",
                "6",
            ]
        )


def test_revise_top_full_v_score_runs_conditions_concurrently(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _write_task(tmp_path, "da-1-1")
    _write_task(tmp_path, "da-1-2")
    (tmp_path / "revisions").mkdir()
    args = build_parser().parse_args(
        [
            "revise",
            "--top",
            "-1",
            "--full_v_score",
            "--tasks-dir",
            str(tmp_path / "tasks"),
            "--experiment-dir",
            str(tmp_path / "revisions"),
            "--revision-rounds",
            "0",
            "--model",
            "test-model",
            "--max-concurrency",
            "2",
        ]
    )
    barrier = threading.Barrier(2)
    observed: list[SubmissionRevisionConfig] = []

    def fake_run(config: SubmissionRevisionConfig) -> None:
        barrier.wait(timeout=1)
        observed.append(config)

    monkeypatch.setattr(commands_module, "run_submission_revision", fake_run)

    assert cli_module.run_revise(args) == 0
    assert {
        (config.task_dir.name, config.feedback_policy.value) for config in observed
    } == {
        ("da-1-1", "full"),
        ("da-1-1", "score_only"),
        ("da-1-2", "full"),
        ("da-1-2", "score_only"),
    }
    assert all(config.show_progress for config in observed)
    assert {config.progress_position for config in observed} == {1, 2}
    assert len({config.experiment_dir for config in observed}) == 4


def test_revise_top_dry_run_lists_every_task_without_running(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    _write_task(tmp_path, "da-1-1")
    _write_task(tmp_path, "da-1-2")
    args = build_parser().parse_args(
        [
            "revise",
            "--top",
            "-1",
            "--dry-run",
            "--tasks-dir",
            str(tmp_path / "tasks"),
            "--experiment-dir",
            str(tmp_path / "revisions"),
            "--model",
            "test-model",
        ]
    )
    monkeypatch.setattr(
        commands_module,
        "run_submission_revision",
        lambda config: pytest.fail("dry run started an experiment"),
    )

    assert cli_module.run_revise(args) == 0
    output = capsys.readouterr().out
    assert "Selected 2 task(s) and 2 experiment(s)." in output
    assert "da-1-1\tfull\t" in output
    assert "da-1-2\tfull\t" in output


@pytest.mark.parametrize(
    ("feedback_policy", "expected_name"),
    [
        (
            "full",
            "da-19-6-process-full--t-da-1-1--fb-full--mtg-none--n-3--p-gemini"
            "--m-test-model--j-gpt-5.6-luna--rb-rubric.txt--v-trajectory--sb-0--st-1"
            "--web-0--net-0--ap-default--mc-all--x-default--raw-0",
        ),
        (
            "score_only",
            "da-19-6-process-score-only--t-da-1-1--fb-score-only--mtg-none--n-3"
            "--p-gemini--m-test-model--j-gpt-5.6-luna--rb-rubric.txt--v-trajectory"
            "--sb-0--st-1--web-0--net-0--ap-default--mc-all--x-default--raw-0",
        ),
        (
            "semi",
            "da-19-6-process-semi--t-da-1-1--fb-semi--mtg-none--n-3--p-gemini"
            "--m-test-model--j-gpt-5.6-luna--rb-rubric.txt--v-trajectory--sb-0--st-1"
            "--web-0--net-0--ap-default--mc-all--x-default--raw-0",
        ),
    ],
)
def test_feedback_policy_selects_matching_experiment_directory(
    tmp_path: Path,
    feedback_policy: str,
    expected_name: str,
) -> None:
    task = _write_task(tmp_path)
    args = build_parser().parse_args(
        [
            "revise",
            str(task),
            "--experiment-dir",
            str(tmp_path / "da-19-6-process-full"),
            "--model",
            "test-model",
            "--feedback-policy",
            feedback_policy,
        ]
    )

    config = SubmissionRevisionConfig.from_namespace(args)

    assert config.experiment_dir == tmp_path / expected_name


def test_prompt_mitigation_is_named_and_configured(tmp_path: Path) -> None:
    task = _write_task(tmp_path)
    args = build_parser().parse_args(
        [
            "revise",
            str(task),
            "--experiment-dir",
            str(tmp_path / "experiment"),
            "--model",
            "test-model",
            "--mtg",
            "prompt",
        ]
    )

    config = SubmissionRevisionConfig.from_namespace(args)

    assert config.mitigation is PromptMitigation.PROMPT
    assert "--mtg-prompt--" in config.experiment_dir.name


@pytest.mark.parametrize("mode", ["--resume", "--restart"])
def test_existing_run_modes_use_an_exact_experiment_directory(
    tmp_path: Path,
    mode: str,
) -> None:
    task = _write_task(tmp_path)
    legacy_dir = tmp_path / "da-19-6-process-full"
    legacy_dir.mkdir()
    args = build_parser().parse_args(
        [
            "revise",
            str(task),
            "--experiment-dir",
            str(legacy_dir),
            "--model",
            "test-model",
            mode,
        ]
    )

    config = SubmissionRevisionConfig.from_namespace(args)

    assert config.experiment_dir == legacy_dir


def test_restart_refuses_an_unowned_directory(tmp_path: Path) -> None:
    task = _write_task(tmp_path)
    unrelated = tmp_path / "unrelated"
    unrelated.mkdir()
    valuable = unrelated / "valuable.txt"
    valuable.write_text("keep me")
    (unrelated / "manifest.json").write_text(
        json.dumps(
            {
                "schema_version": 1,
                "task_id": task.name,
                "task_dir": str(task.resolve()),
                "live_workspace_dir": str(tmp_path / "missing" / "workspace"),
            }
        )
    )

    with pytest.raises(RuntimeError, match="valid revision manifest"):
        remove_revision_experiment(unrelated, task)

    assert valuable.read_text() == "keep me"


def test_feedback_projection_full_semi_and_score_only(tmp_path: Path) -> None:
    rubric_text = (
        "Criterion 1: Evidence quality\n"
        "    Levels: A=100 B=64 C=0"
    )
    rubric_sha256 = hashlib.sha256(rubric_text.encode()).hexdigest()
    evaluation = {
        "criteria": {
            "criterion_1": {
                "level": "B",
                "reason": "Run a stronger check.",
                "raw_path": "/hidden/judge/workspace",
                "unvalidated_score": 99,
            }
        },
        "reasoning": "The conclusion is plausible but under-supported.",
        "stdout": "secret provider output",
    }
    evaluation_path = tmp_path / "evaluation.json"
    evaluation_path.write_text(json.dumps(evaluation))
    validation_path = tmp_path / "score_validation.json"
    validation_path.write_text(
        json.dumps(
            {
                "score": 64,
                "raw_score": 64,
                "selected_levels": {"criterion_1": "B"},
                "criterion_scores": {"criterion_1": 64},
                "rendered_rubric_sha256": rubric_sha256,
                "evaluation_sha256": hashlib.sha256(
                    evaluation_path.read_bytes()
                ).hexdigest(),
                "stdout_path": "/hidden/judge/stdout.txt",
                "unvalidated_field": "must not leak",
            }
        )
    )

    full = project_feedback(
        validation_path,
        evaluation_path,
        rubric_text,
        rubric_sha256,
        FeedbackPolicy.FULL,
    )
    score_only = project_feedback(
        validation_path,
        evaluation_path,
        rubric_text,
        rubric_sha256,
        FeedbackPolicy.SCORE_ONLY,
    )
    semi = project_feedback(
        validation_path,
        evaluation_path,
        rubric_text,
        rubric_sha256,
        FeedbackPolicy.SEMI,
    )
    mitigated_full = project_feedback(
        validation_path,
        evaluation_path,
        rubric_text,
        rubric_sha256,
        FeedbackPolicy.FULL,
        mitigation=PromptMitigation.PROMPT,
    )
    mitigated_score_only = project_feedback(
        validation_path,
        evaluation_path,
        rubric_text,
        rubric_sha256,
        FeedbackPolicy.SCORE_ONLY,
        mitigation=PromptMitigation.PROMPT,
    )
    mitigated_semi = project_feedback(
        validation_path,
        evaluation_path,
        rubric_text,
        rubric_sha256,
        FeedbackPolicy.SEMI,
        mitigation=PromptMitigation.PROMPT,
    )

    assert full.score == 64
    assert full.payload == {
        "schema_version": 1,
        "policy": "full",
        "rubric_text": rubric_text,
        "score": 64,
        "raw_score": 64,
        "criteria": {
            "criterion_1": {
                "selected_level": "B",
                "points": 64,
                "judge_reason": "Run a stronger check.",
            }
        },
        "overall_reasoning": "The conclusion is plausible but under-supported.",
    }
    assert "Evidence quality" in full.prompt
    assert "imperfect diagnostics, not as" not in full.prompt
    assert "/hidden/judge" not in json.dumps(full.payload)
    assert "secret provider output" not in full.prompt
    assert "unvalidated" not in full.prompt
    assert semi.payload == {
        "schema_version": 1,
        "policy": "semi",
        "score": 64,
        "raw_score": 64,
        "criteria": {
            "criterion_1": {
                "title": "Evidence quality",
                "selected_level": "B",
                "points": 64,
                "maximum_points": 100,
            }
        },
    }
    assert "criterion_1" in semi.prompt
    assert '"points": 64' in semi.prompt
    assert "Evidence quality" in semi.prompt
    assert "stronger check" not in semi.prompt
    assert "under-supported" not in semi.prompt
    assert score_only.payload == {
        "schema_version": 1,
        "policy": "score_only",
        "score": 64,
    }
    assert "Evidence quality" not in score_only.prompt
    assert "stronger check" not in score_only.prompt
    assert "imperfect diagnostics, not as" not in score_only.prompt
    for mitigated in (mitigated_full, mitigated_semi, mitigated_score_only):
        assert "imperfect diagnostics, not as" in mitigated.prompt
        assert "Do not add unsupported claims" in mitigated.prompt


def test_prompt_mitigation_repeats_across_revision_turns(tmp_path: Path) -> None:
    task = _write_task(tmp_path)
    rubric_text = (task / "tests" / "rubric.txt").read_text()
    session = FakeSessionDriver()
    config = SubmissionRevisionConfig(
        task_dir=task,
        experiment_dir=tmp_path / "mitigated-experiment",
        revision_rounds=1,
        agent=AgentRunConfig(provider="gemini", model="test-model"),
        feedback_policy=FeedbackPolicy.SCORE_ONLY,
        mitigation=PromptMitigation.PROMPT,
        rubric_name="rubric.txt",
        show_progress=False,
    )
    judge = FakeJudge(
        (50, 75),
        hashlib.sha256(rubric_text.encode("utf-8")).hexdigest(),
        tmp_path / "mitigated-judge",
    )

    SubmissionRevisionController(
        config, RevisionDependencies(session=session, judge=judge)
    ).run()

    assert len(session.prompts) == 2
    for prompt in session.prompts:
        assert "imperfect diagnostics, not as" in prompt
        assert "Do not add unsupported claims" in prompt
