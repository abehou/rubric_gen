from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import replace
from pathlib import Path
from typing import Callable

import pytest

import rubric_gen.biomnibench.cli as cli_module
import rubric_gen.biomnibench.submission_revision as submission_revision_module
import rubric_gen.biomnibench.submission_revision_artifacts as revision_artifacts_module
from rubric_gen.biomnibench.common import AgentRunConfig
from rubric_gen.biomnibench.cli import build_parser
from rubric_gen.biomnibench.session_drivers import SessionTurnResult
from rubric_gen.biomnibench.submission_feedback import (
    FeedbackPolicy,
    project_feedback,
)
from rubric_gen.biomnibench.submission_revision_artifacts import (
    remove_revision_experiment,
)
from rubric_gen.biomnibench.submission_revision import (
    JudgeArtifacts,
    RevisionDependencies,
    SubmissionRevisionConfig,
    SubmissionRevisionController,
)


def _write_task(root: Path) -> Path:
    task = root / "tasks" / "da-1-1"
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
        submission_revision_module,
        "trange",
        fake_trange,
        raising=False,
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
        cli_module,
        "run_submission_revision",
        lambda received: observed_configs.append(received),
    )

    assert cli_module.run_revise(args) == 0
    assert observed_configs == [config]
    assert config.agent.quiet is True
    assert capsys.readouterr().out == ""


@pytest.mark.parametrize(
    ("feedback_policy", "expected_name"),
    [
        (
            "full",
            "da-19-6-process-full--t-da-1-1--fb-full--n-3--p-gemini"
            "--m-test-model--j-default--rb-default--v-trajectory--sb-0--st-0"
            "--web-0--ap-default--mc-all--x-default--raw-0",
        ),
        (
            "score_only",
            "da-19-6-process-score-only--t-da-1-1--fb-score-only--n-3"
            "--p-gemini--m-test-model--j-default--rb-default--v-trajectory"
            "--sb-0--st-0--web-0--ap-default--mc-all--x-default--raw-0",
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


def test_resume_uses_an_existing_legacy_experiment_directory(tmp_path: Path) -> None:
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
            "--resume",
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


def test_feedback_projection_full_and_score_only(tmp_path: Path) -> None:
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
                "rendered_rubric_sha256": hashlib.sha256(
                    b"Criterion 1: Evidence quality"
                ).hexdigest(),
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
        "Criterion 1: Evidence quality",
        hashlib.sha256(b"Criterion 1: Evidence quality").hexdigest(),
        FeedbackPolicy.FULL,
    )
    score_only = project_feedback(
        validation_path,
        evaluation_path,
        "Criterion 1: Evidence quality",
        hashlib.sha256(b"Criterion 1: Evidence quality").hexdigest(),
        FeedbackPolicy.SCORE_ONLY,
    )

    assert full.score == 64
    assert full.payload == {
        "schema_version": 1,
        "policy": "full",
        "rubric_text": "Criterion 1: Evidence quality",
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
    assert "/hidden/judge" not in json.dumps(full.payload)
    assert "secret provider output" not in full.prompt
    assert "unvalidated" not in full.prompt
    assert score_only.payload == {
        "schema_version": 1,
        "policy": "score_only",
        "score": 64,
    }
    assert "Evidence quality" not in score_only.prompt
    assert "stronger check" not in score_only.prompt
