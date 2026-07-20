from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import rubric_gen.biomnibench.revision.judge as judge_module
from rubric_gen.biomnibench.revision.judge import (
    BiomniSubmissionJudge,
    FrozenRubric,
    JudgeArtifacts,
    SubmissionJudgeConfig,
)


class ScriptedJudgeRunner:
    def __init__(self, output_dir: Path, failures: int) -> None:
        self._output_dir = output_dir
        self.failures = failures
        self.calls = 0

    def review_target(self, target: object) -> dict[str, object]:
        self.calls += 1
        self._output_dir.mkdir(parents=True, exist_ok=True)
        (self._output_dir / "stdout.txt").write_text(
            f"judge attempt {self.calls} failed\n"
        )
        if self.calls <= self.failures:
            return {
                "status": "failed",
                "exit_code": 1,
                "score": None,
                "stdout": str(self._output_dir / "stdout.txt"),
            }
        return {
            "status": "completed",
            "exit_code": 0,
            "score": 75,
            "stdout": str(self._output_dir / "stdout.txt"),
        }

    def output_dir(self, target: object) -> Path:
        return self._output_dir


def _judge(tmp_path: Path, *, max_retries: int = 5) -> BiomniSubmissionJudge:
    task = tmp_path / "tasks" / "da-1-1"
    task.mkdir(parents=True)
    rubric_text = "Criterion 1: result\nLevels: A=100 B=50 C=0\n"
    return BiomniSubmissionJudge(
        SubmissionJudgeConfig(
            task_dir=task,
            experiment_dir=tmp_path / "experiment",
            review="trajectory",
            judge_model="judge-model",
            rubric_name="rubric.txt",
            rubric_set=None,
            max_review_chars=None,
            max_retries=max_retries,
        ),
        FrozenRubric(
            text=rubric_text,
            sha256=hashlib.sha256(rubric_text.encode()).hexdigest(),
            source="task-local",
            rubric_set_id=None,
            rubric_id=None,
            structured_rubric_sha256=None,
            manifest_sha256=None,
        ),
    )


def test_optimizer_judge_retries_and_archives_failed_attempts(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    judge = _judge(tmp_path)
    submission = tmp_path / "experiment" / "submissions" / "s000"
    submission.mkdir(parents=True)
    evaluation_root = judge._evaluation_root(submission, "a" * 32)
    output_dir = evaluation_root / "run" / "judges" / "trajectory" / "da-1-1"
    runner = ScriptedJudgeRunner(output_dir, failures=2)
    target = object()

    def fake_prepare(submission_dir: Path, root: Path) -> Path:
        run = root / "run"
        run.mkdir(parents=True)
        return run

    artifacts = JudgeArtifacts(
        score_validation_path=output_dir / "score_validation.json",
        evaluation_path=output_dir / "evaluation.json",
    )
    monkeypatch.setattr(judge_module, "prepare_evaluation_run", fake_prepare)
    monkeypatch.setattr(judge, "_runner_and_target", lambda run: (runner, target))
    monkeypatch.setattr(
        judge,
        "_validated_cached_artifacts",
        lambda *args: artifacts,
    )

    assert judge.evaluate(submission, "a" * 32) == artifacts
    assert runner.calls == 3
    attempts = evaluation_root / "judge-attempts"
    assert sorted(path.name for path in attempts.iterdir()) == [
        "attempt-001",
        "attempt-002",
    ]
    assert (
        attempts / "attempt-001" / "stdout.txt"
    ).read_text() == "judge attempt 1 failed\n"
    first_record = json.loads((attempts / "attempt-001" / "record.json").read_text())
    assert first_record["exit_code"] == 1


def test_optimizer_judge_reports_details_after_five_retries(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    judge = _judge(tmp_path)
    submission = tmp_path / "experiment" / "submissions" / "s000"
    submission.mkdir(parents=True)
    evaluation_root = judge._evaluation_root(submission, "b" * 32)
    output_dir = evaluation_root / "run" / "judges" / "trajectory" / "da-1-1"
    runner = ScriptedJudgeRunner(output_dir, failures=6)

    def fake_prepare(submission_dir: Path, root: Path) -> Path:
        run = root / "run"
        run.mkdir(parents=True)
        return run

    monkeypatch.setattr(judge_module, "prepare_evaluation_run", fake_prepare)
    monkeypatch.setattr(
        judge,
        "_runner_and_target",
        lambda run: (runner, object()),
    )

    with pytest.raises(
        RuntimeError,
        match=r"failed after 6 attempts.*exit_code=1.*stdout=.*stdout.txt",
    ):
        judge.evaluate(submission, "b" * 32)

    assert runner.calls == 6
    assert len(list((evaluation_root / "judge-attempts").iterdir())) == 6


def test_optimizer_judge_does_not_retry_an_unavailable_model(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    judge = _judge(tmp_path)
    submission = tmp_path / "experiment" / "submissions" / "s000"
    submission.mkdir(parents=True)
    evaluation_root = judge._evaluation_root(submission, "c" * 32)
    output_dir = evaluation_root / "run" / "judges" / "trajectory" / "da-1-1"
    runner = ScriptedJudgeRunner(output_dir, failures=6)

    def unavailable_model(target: object) -> dict[str, object]:
        record = ScriptedJudgeRunner.review_target(runner, target)
        (output_dir / "stdout.txt").write_text(
            "404 NOT_FOUND: models/gemini-3.5-pro is not found or is not "
            "supported for generateContent\n"
        )
        return record

    runner.review_target = unavailable_model  # type: ignore[method-assign]

    def fake_prepare(submission_dir: Path, root: Path) -> Path:
        run = root / "run"
        run.mkdir(parents=True)
        return run

    monkeypatch.setattr(judge_module, "prepare_evaluation_run", fake_prepare)
    monkeypatch.setattr(judge, "_runner_and_target", lambda run: (runner, object()))

    with pytest.raises(RuntimeError, match="non-retryable configuration error"):
        judge.evaluate(submission, "c" * 32)

    assert runner.calls == 1
