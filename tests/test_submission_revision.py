from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import replace
from pathlib import Path
from typing import Callable

import pytest

from rubric_gen.biomnibench.agent.models import AgentRunConfig
from rubric_gen.biomnibench.agent.prompts import PromptProfile
from rubric_gen.biomnibench.agent.sessions import SessionTurnResult
from rubric_gen.biomnibench.experiments import ExperimentDesign
from rubric_gen.biomnibench.revision.controller import SubmissionRevisionController
from rubric_gen.biomnibench.revision.judge import JudgeArtifacts
from rubric_gen.biomnibench.revision.models import (
    RevisionDependencies,
    SubmissionRevisionConfig,
)
from rubric_gen.biomnibench.revision.artifacts import (
    live_root_parent,
    sha256_file,
    solution_tree_sha256,
    tree_sha256,
)
from rubric_gen.biomnibench.revision.feedback import FeedbackPolicy, project_feedback
from rubric_gen.biomnibench.revision.seeds import SEED_KIND, SEED_SET_KIND
from rubric_gen.biomnibench.study import validate_completed_revision
from rubric_gen.biomnibench.utils.hashing import sha256_text


DESIGN_SHA = "d" * 64
RUN_PROVENANCE = {"sha256": "9" * 64}


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


def _identity(task: Path) -> dict[str, object]:
    return {
        "scorer_version": "test-scorer-v1",
        "judge_source_sha256": "1" * 64,
        "judge_runner_sha256": "2" * 64,
        "scorer_module_sha256": "3" * 64,
        "effective_judge_model": "test-judge-model",
        "review_mode": "trace",
        "max_review_chars": None,
        "rubric_source": "task-local",
        "rubric_set_id": None,
        "rubric_id": None,
        "structured_rubric_sha256": None,
        "rendered_rubric_sha256": sha256_file(task / "tests" / "rubric.txt"),
        "manifest_sha256": None,
    }


def _write_seed_set(root: Path, task: Path, initial_score: int = 80) -> Path:
    seed_set = root / "seeds"
    seed_root = seed_set / "tasks" / task.name / "rep-001"
    submission = seed_root / "submission"
    workspace = submission / "workspace"
    workspace.mkdir(parents=True, exist_ok=True)
    (workspace / "answer.txt").write_text("seed-answer\n")
    (workspace / "trace.md").write_text("seed-trace\n")
    trajectory = submission / "trajectory.stream.jsonl"
    trajectory.write_text('{"turn":-1}\n')
    workspace_sha = solution_tree_sha256(workspace)
    trajectory_sha = sha256_file(trajectory)
    instruction_sha = sha256_file(task / "instruction.md")
    data_sha = tree_sha256(task / "environment" / "data")
    solution_sha = sha256_text(
        f"{DESIGN_SHA}\n{task.name}\n1\n{instruction_sha}\n{data_sha}\n"
        f"{workspace_sha}\n{trajectory_sha}\n"
    )
    (submission / "status.json").write_text(json.dumps({
        "schema_version": 2,
        "task": task.name,
        "replicate": 1,
        "design_sha256": DESIGN_SHA,
        "workspace_dir": str(workspace),
        "provider": "codex",
        "session_id": None,
        "submission_id": "s000",
        "exit_code": 0,
    }))
    (submission / "snapshot.json").write_text(json.dumps({
        "schema_version": 2,
        "submission_id": "s000",
        "session_id": None,
        "workspace_sha256": workspace_sha,
        "trajectory_sha256": trajectory_sha,
    }))
    judgment = seed_root / "initial_judgment"
    judgment.mkdir()
    evaluation = judgment / "evaluation.json"
    level = "A" if initial_score >= 80 else "B"
    evaluation.write_text(json.dumps({
        "criteria": {"criterion_1": {"level": level, "reason": "seed"}},
        "reasoning": "seed",
    }))
    identity = _identity(task)
    validation = judgment / "score_validation.json"
    usage = judgment / "usage.json"
    usage.write_text('{"schema_version":1,"usage":{}}')
    validation.write_text(json.dumps({
        "schema_version": 2,
        **identity,
        "review_input_sha256": "4" * 64,
        "answer_input_sha256": "5" * 64,
        "task": task.name,
        "run_identity": "seeded-run",
        "repeat_index": 1,
        "score": initial_score,
        "raw_score": initial_score,
        "selected_levels": {"criterion_1": level},
        "criterion_scores": {"criterion_1": initial_score},
        "evaluation_sha256": sha256_file(evaluation),
    }))
    judgment_sha = sha256_text(
        f"{sha256_file(validation)}\n{sha256_file(evaluation)}\n{sha256_file(usage)}\n"
        f"{json.dumps(identity, sort_keys=True, separators=(',', ':'))}\n"
    )
    (seed_root / "manifest.json").write_text(json.dumps({
        "schema_version": 4,
        "kind": SEED_KIND,
        "design_sha256": DESIGN_SHA,
        "protocol_id": "test-protocol",
        "task_id": task.name,
        "replicate": 1,
        "provider": "codex",
        "requested_model": "test-model",
        "instruction_sha256": instruction_sha,
        "data_sha256": data_sha,
        "workspace_sha256": workspace_sha,
        "trajectory_sha256": trajectory_sha,
        "score_validation_sha256": sha256_file(validation),
        "evaluation_sha256": sha256_file(evaluation),
        "usage_sha256": sha256_file(usage),
        "scoring_identity": identity,
        "judgment_sha256": judgment_sha,
        "seed_sha256": sha256_text(f"{solution_sha}{judgment_sha}\n"),
        "source_status": {
            "provider": "codex",
            "exit_code": 0,
            "model": "test-model",
        },
        "run_provenance_sha256": RUN_PROVENANCE["sha256"],
    }))
    (seed_set / "manifest.json").write_text(json.dumps({
        "schema_version": 3,
        "kind": SEED_SET_KIND,
        "status": "completed",
        "design_sha256": DESIGN_SHA,
        "protocol_id": "test-protocol",
    }))
    return seed_set


def _config(root: Path, task: Path, *, rounds: int, score: int = 80):
    return SubmissionRevisionConfig(
        task_dir=task,
        experiment_dir=root / "experiment",
        revision_rounds=rounds,
        seed_run_dir=_write_seed_set(root, task, score),
        agent=AgentRunConfig(provider="codex", model="test-model"),
        run_provenance=RUN_PROVENANCE,
        design_sha256=DESIGN_SHA,
        protocol_id="test-protocol",
        assignment_id=f"{task.name}--rep-001--base--static",
        condition_id="base--static",
        replicate=1,
        execution_order=1,
        feedback_policy=FeedbackPolicy.FULL,
        prompt_profile=PromptProfile.BASE,
        rubric_name="rubric.txt",
        review="trace",
        show_progress=False,
    )


def _design(config: SubmissionRevisionConfig, task: Path) -> ExperimentDesign:
    agent = config.agent
    return ExperimentDesign(
        task.parent / "design.json",
        {
            "design_sha256": DESIGN_SHA,
            "protocol_id": config.protocol_id,
            "tasks_dir": str(task.parent.resolve()),
            "tasks": [{
                "task_id": task.name,
                "instruction_sha256": sha256_file(task / "instruction.md"),
                "data_sha256": tree_sha256(task / "environment" / "data"),
                "rubric_sha256": sha256_file(task / "tests" / "rubric.txt"),
            }],
            "conditions": [{
                "condition_id": config.condition_id,
                "prompt": config.prompt_profile.value,
                "rubric_evolution": config.rubric_evolution.value,
            }],
            "protocol": {
                "revision_rounds": config.revision_rounds,
                "feedback_policy": config.feedback_policy.value,
                "rubric_proposer_model": config.rubric_proposer_model,
                "rubric_proposer_step_limit": config.rubric_proposer_step_limit,
                "rubric_proposer_max_retries": config.rubric_proposer_max_retries,
                "review": config.review,
                "judge_model": config.judge_model,
                "judge_max_retries": config.judge_max_retries,
                "max_review_chars": config.max_review_chars,
                "rubric_name": config.rubric_name,
                "solver": {
                    "provider": agent.provider,
                    "model": agent.model,
                    "executable": agent.executable,
                    "reasoning_effort": agent.reasoning_effort,
                    "service_tier": agent.service_tier,
                    "retries": agent.retries,
                    "timeout_seconds": agent.timeout_seconds,
                },
            },
            "run_provenance": RUN_PROVENANCE,
        },
    )


class FakeSession:
    def __init__(self, *, fail: bool = False) -> None:
        self.prompts: list[str] = []
        self.sessions: list[str] = []
        self.fail = fail

    def start(
        self,
        workspace: Path,
        prompt: str,
        turn_dir: Path,
        *,
        on_session_id: Callable[[str], None] | None = None,
    ) -> SessionTurnResult:
        if on_session_id:
            on_session_id("solver-session")
        return self._turn(workspace, prompt, turn_dir, "solver-session")

    def resume(
        self,
        workspace: Path,
        prompt: str,
        turn_dir: Path,
        session_id: str,
    ) -> SessionTurnResult:
        return self._turn(workspace, prompt, turn_dir, session_id)

    def _turn(
        self, workspace: Path, prompt: str, turn_dir: Path, session_id: str
    ) -> SessionTurnResult:
        self.prompts.append(prompt)
        self.sessions.append(session_id)
        index = len(self.prompts)
        turn_dir.mkdir(parents=True, exist_ok=True)
        trajectory = turn_dir / "trajectory.stream.jsonl"
        trajectory.write_text(json.dumps({"turn": index}) + "\n")
        (workspace / "answer.txt").write_text(f"answer-{index}\n")
        (workspace / "trace.md").write_text(f"trace-{index}\n")
        return SessionTurnResult(
            session_id=session_id,
            model="test-model",
            exit_code=1 if self.fail else 0,
            trajectory_path=trajectory,
        )


class FakeJudge:
    def __init__(self, task: Path, scores: tuple[int, ...], root: Path) -> None:
        self.identity = _identity(task)
        self.task_name = task.name
        self.scores = scores
        self.root = root
        self.calls = 0

    def scoring_identity(self) -> dict[str, object]:
        return dict(self.identity)

    def evaluate(self, submission_dir: Path, attempt_id: str) -> JudgeArtifacts:
        self.calls += 1
        score = self.scores[self.calls]
        output = (
            submission_dir.parents[1]
            / "evaluations"
            / submission_dir.name
            / str(self.identity["rendered_rubric_sha256"])
            / attempt_id
            / "run"
            / "judges"
            / "trace"
            / self.task_name
        )
        output.mkdir(parents=True)
        evaluation = output / "evaluation.json"
        evaluation.write_text(json.dumps({
            "criteria": {"criterion_1": {"level": "A", "reason": "checked"}},
            "reasoning": "checked",
        }))
        validation = output / "score_validation.json"
        validation.write_text(json.dumps({
            "schema_version": 2,
            **self.identity,
            "review_input_sha256": "4" * 64,
            "answer_input_sha256": "5" * 64,
            "task": submission_dir.parents[2].name,
            "run_identity": str(output),
            "repeat_index": 1,
            "score": score,
            "raw_score": score,
            "selected_levels": {"criterion_1": "A"},
            "criterion_scores": {"criterion_1": score},
            "evaluation_sha256": sha256_file(evaluation),
        }))
        return JudgeArtifacts(validation, evaluation)

    def validate(self, submission_dir: Path, attempt_id: str) -> JudgeArtifacts:
        output = (
            submission_dir.parents[1]
            / "evaluations"
            / submission_dir.name
            / str(self.identity["rendered_rubric_sha256"])
            / attempt_id
            / "run"
            / "judges"
            / "trace"
            / self.task_name
        )
        return JudgeArtifacts(
            output / "score_validation.json", output / "evaluation.json"
        )


def test_linear_revision_uses_shared_seed_one_session_and_exact_completion(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    config = _config(tmp_path, task, rounds=2)
    session = FakeSession()
    judge = FakeJudge(task, (80, 55, 70), tmp_path / "judge")
    result = SubmissionRevisionController(
        config,
        RevisionDependencies(session=session, judge=judge),
    ).run()

    assert result.submission_ids == ("s000", "s001", "s002")
    assert result.scores == (80, 55, 70)
    assert session.sessions == ["solver-session", "solver-session"]
    assert len(session.prompts) == 2
    assignment = {
        "assignment_id": config.assignment_id,
        "task_id": task.name,
        "replicate": 1,
        "condition_id": config.condition_id,
        "execution_order": 1,
    }
    validate_completed_revision(
        config.experiment_dir,
        assignment,
        _design(config, task),
        config.seed_run_dir,
    )
    manifest = json.loads((config.experiment_dir / "manifest.json").read_text())
    assert manifest["live_workspace_removed"] is True
    assert manifest["design_sha256"] == DESIGN_SHA

    evaluation = next(
        (config.experiment_dir / "evaluations" / "s001").glob(
            "*/*/run/judges/trace/da-1-1/evaluation.json"
        )
    )
    evaluation.chmod(stat.S_IRUSR | stat.S_IWUSR)
    evaluation.write_text("{}")
    with pytest.raises(RuntimeError, match="evaluation disagrees"):
        validate_completed_revision(
            config.experiment_dir,
            assignment,
            _design(config, task),
            config.seed_run_dir,
        )


def test_safe_boundary_resume_continues_missing_turns_without_rescoring_seed(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    config = _config(tmp_path, task, rounds=1)
    session = FakeSession()
    judge = FakeJudge(task, (80, 90), tmp_path / "judge")

    class InterruptAfterSeed(SubmissionRevisionController):
        def _append_event(self, payload: dict[str, object]) -> None:
            super()._append_event(payload)
            if payload.get("event") == "submission_judged" and payload.get(
                "submission_id"
            ) == "s000":
                raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        InterruptAfterSeed(
            config, RevisionDependencies(session=session, judge=judge)
        ).run()
    assert judge.calls == 0
    result = SubmissionRevisionController(
        replace(config, resume=True),
        RevisionDependencies(session=session, judge=judge),
    ).run()
    assert result.scores == (80, 90)
    assert judge.calls == 1


def test_failed_solver_turn_is_sealed_and_never_misreported_as_complete(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    config = _config(tmp_path, task, rounds=1)
    session = FakeSession(fail=True)
    judge = FakeJudge(task, (80, 90), tmp_path / "judge")
    with pytest.raises(RuntimeError, match="provider exited"):
        SubmissionRevisionController(
            config, RevisionDependencies(session=session, judge=judge)
        ).run()
    state = json.loads((config.experiment_dir / "state.json").read_text())
    assert state["phase"] == "failed_turn"
    assignment = {
        "assignment_id": config.assignment_id,
        "task_id": task.name,
        "replicate": 1,
        "condition_id": config.condition_id,
        "execution_order": 1,
    }
    with pytest.raises(RuntimeError, match="not complete"):
        validate_completed_revision(
            config.experiment_dir,
            assignment,
            _design(config, task),
            config.seed_run_dir,
        )
    with pytest.raises(RuntimeError, match="provider exited"):
        SubmissionRevisionController(
            replace(config, resume=True),
            RevisionDependencies(session=session, judge=judge),
        ).run()


def test_failed_solver_turn_resumes_from_last_scored_boundary(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    config = _config(tmp_path, task, rounds=1)
    session = FakeSession(fail=True)
    judge = FakeJudge(task, (80, 90), tmp_path / "judge")
    dependencies = RevisionDependencies(session=session, judge=judge)

    with pytest.raises(RuntimeError, match="provider exited"):
        SubmissionRevisionController(config, dependencies).run()
    session.fail = False
    result = SubmissionRevisionController(
        replace(config, resume=True), dependencies
    ).run()

    assert result.submission_ids == ("s000", "s001")
    assert result.scores == (80, 90)
    assert session.sessions == ["solver-session", "solver-session"]
    archived = config.experiment_dir / "interrupted-turns" / "turn-001"
    assert (archived / "status.json").is_file()


def test_live_root_defaults_outside_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BIOMNIBENCH_LIVE_ROOT", raising=False)
    root = live_root_parent()
    assert "biomnibench-live" in root.name
    assert Path.cwd().resolve() not in root.parents


def test_feedback_projection_keeps_policies_distinct(tmp_path: Path) -> None:
    rubric = """Criterion 1: Correctness
Description here.
Levels: A=60 B=30 C=0
[A]: exact
[B]: partial
[C]: wrong

Criterion 2: Evidence
Levels: A=40 B=20 C=0
[A]: strong
[B]: medium
[C]: absent
"""
    rubric_sha = hashlib.sha256(rubric.encode()).hexdigest()
    validation = tmp_path / "validation.json"
    evaluation = tmp_path / "evaluation.json"
    evaluation.write_text(json.dumps({
        "criteria": {
            "criterion_1": {"level": "A", "reason": "correct"},
            "criterion_2": {"level": "B", "reason": "needs more evidence"},
        },
        "reasoning": "overall",
    }))
    validation.write_text(json.dumps({
        "score": 80,
        "raw_score": 80,
        "selected_levels": {"criterion_1": "A", "criterion_2": "B"},
        "criterion_scores": {"criterion_1": 60, "criterion_2": 20},
        "rendered_rubric_sha256": rubric_sha,
        "evaluation_sha256": sha256_file(evaluation),
    }))
    full = project_feedback(
        validation, evaluation, rubric, rubric_sha, FeedbackPolicy.FULL
    )
    semi = project_feedback(
        validation, evaluation, rubric, rubric_sha, FeedbackPolicy.SEMI
    )
    score = project_feedback(
        validation, evaluation, rubric, rubric_sha, FeedbackPolicy.SCORE_ONLY
    )
    assert "needs more evidence" in full.prompt
    assert '"title": "Evidence"' in semi.prompt
    assert "needs more evidence" not in semi.prompt
    assert "Criterion 2" not in score.prompt
    assert score.score == 80
