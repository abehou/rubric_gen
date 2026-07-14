from __future__ import annotations

import hashlib
import json
import stat
from pathlib import Path

from rubric_gen.biomnibench.common import AgentRunConfig
from rubric_gen.biomnibench.session_drivers import SessionTurnResult
from rubric_gen.biomnibench.submission_feedback import (
    FeedbackPolicy,
    project_feedback,
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

    def start(self, workspace: Path, prompt: str, turn_dir: Path) -> SessionTurnResult:
        self.prompts.append(prompt)
        self.session_ids.append("solver-session")
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

    def evaluate(self, submission_dir: Path) -> JudgeArtifacts:
        index = len(self.submissions)
        self.submissions.append(submission_dir.name)
        output = self.output_root / submission_dir.name
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
                    "score": self.scores[index],
                    "raw_score": self.scores[index],
                    "selected_levels": {"criterion_1": level},
                    "criterion_scores": {"criterion_1": self.scores[index]},
                    "rendered_rubric_sha256": self.rubric_sha256,
                    "evaluation_sha256": evaluation_sha256,
                }
            )
        )
        return JudgeArtifacts(
            score_validation_path=validation_path,
            evaluation_path=evaluation_path,
        )


def test_linear_revision_keeps_one_session_and_continues_after_regression(
    tmp_path: Path,
) -> None:
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

    result = SubmissionRevisionController(
        config,
        RevisionDependencies(session=session, judge=judge),
    ).run()

    assert result.session_id == "solver-session"
    assert result.submission_ids == ("s000", "s001", "s002")
    assert result.scores == (80, 55, 70)
    assert session.session_ids == ["solver-session"] * 3
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
        config.experiment_dir / "submissions" / "s000" / "workspace" / "answer.txt"
    ).stat().st_mode
    assert not snapshot_mode & stat.S_IWUSR
    cumulative = (
        config.experiment_dir / "submissions" / "s002" / "trajectory.stream.jsonl"
    ).read_text()
    assert [json.loads(line)["turn"] for line in cumulative.splitlines()] == [0, 1, 2]


def test_feedback_projection_full_and_score_only(tmp_path: Path) -> None:
    evaluation = {
        "criteria": {
            "criterion_1": {"level": "B", "reason": "Run a stronger check."}
        },
        "reasoning": "The conclusion is plausible but under-supported.",
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
    assert full.payload["criteria"]["criterion_1"]["judge_reason"] == (
        "Run a stronger check."
    )
    assert "Evidence quality" in full.prompt
    assert score_only.payload == {
        "schema_version": 1,
        "policy": "score_only",
        "score": 64,
    }
    assert "Evidence quality" not in score_only.prompt
    assert "stronger check" not in score_only.prompt
