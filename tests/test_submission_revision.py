from __future__ import annotations

import hashlib
import json
import stat
from dataclasses import replace
from pathlib import Path
from typing import Callable

import pytest

from rubric_gen.runtime.agents.models import AgentRunConfig
from rubric_gen.submission_revision.prompts import PromptProfile, solver_prompt
from rubric_gen.runtime.agents.sessions import SessionTurnResult
from rubric_gen.submission_revision.experiment import Experiment
from rubric_gen.submission_revision.controller import (
    SubmissionRevisionController,
    fixed_original_attempt_id,
)
from rubric_gen.submission_revision.evolution import RubricEvolution
from rubric_gen.submission_revision.judge import JudgeArtifacts
from rubric_gen.submission_revision.models import (
    RevisionDependencies,
    SubmissionRevisionConfig,
)
from rubric_gen.submission_revision.artifacts import (
    live_root_parent,
    remove_live_tree,
    sha256_file,
    solution_tree_sha256,
    tree_sha256,
)
from rubric_gen.submission_revision.feedback import (
    FeedbackPolicy,
    project_feedback,
    project_simulated_user_feedback,
)
from rubric_gen.submission_revision.seeds import SEED_KIND, SEED_SET_KIND
from rubric_gen.submission_revision.user_simulator import (
    SimulatedUserConfig,
    SimulatedUserFeedback,
    SimulatedUserGeneration,
    SimulatedUserRequest,
)
from rubric_gen.submission_revision.study import (
    _expected_rubric_names,
    validate_completed_revision,
)
from rubric_gen.artifacts.hashing import sha256_text


EXPERIMENT_ID = "test-experiment"


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


def _write_seed_set(
    root: Path,
    task: Path,
    initial_score: int = 80,
    scoring_identity: dict[str, object] | None = None,
) -> Path:
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
        f"{EXPERIMENT_ID}\n{task.name}\n1\n{instruction_sha}\n{data_sha}\n"
        f"{workspace_sha}\n{trajectory_sha}\n"
    )
    (submission / "status.json").write_text(json.dumps({
        "schema_version": 2,
        "task": task.name,
        "replicate": 1,
        "experiment_id": EXPERIMENT_ID,
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
    identity = dict(scoring_identity or _identity(task))
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
        "normalized_score": initial_score / 100,
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
        "experiment_id": EXPERIMENT_ID,
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
    }))
    (seed_set / "manifest.json").write_text(json.dumps({
        "schema_version": 3,
        "kind": SEED_SET_KIND,
        "status": "completed",
        "experiment_id": EXPERIMENT_ID,
    }))
    return seed_set


def _config(
    root: Path,
    task: Path,
    *,
    rounds: int,
    score: int = 80,
    seed_scoring_identity: dict[str, object] | None = None,
):
    return SubmissionRevisionConfig(
        task_dir=task,
        experiment_dir=root / "experiment",
        revision_rounds=rounds,
        seed_run_dir=_write_seed_set(
            root,
            task,
            score,
            scoring_identity=seed_scoring_identity,
        ),
        agent=AgentRunConfig(provider="codex", model="test-model"),
        experiment_id=EXPERIMENT_ID,
        assignment_id=f"{task.name}--rep-001--base-static",
        condition_id="base-static",
        replicate=1,
        execution_order=1,
        feedback_policy=FeedbackPolicy.FULL,
        prompt_profile=PromptProfile.BASE,
        rubric_name="rubric.txt",
        review="trace",
        show_progress=False,
    )


def _design(config: SubmissionRevisionConfig, task: Path) -> Experiment:
    agent = config.agent
    protocol: dict[str, object] = {
        "revision_rounds": config.revision_rounds,
        "feedback_policy": config.feedback_policy.value,
        "rubric_auditor_model": config.rubric_auditor_model,
        "rubric_auditor_query_limit": config.rubric_auditor_query_limit,
        "rubric_proposer_model": config.rubric_proposer_model,
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
    }
    if config.feedback_simulator is not None:
        protocol["feedback_simulator"] = {
            "model": config.feedback_simulator.model,
            "max_output_tokens": config.feedback_simulator.max_output_tokens,
            "max_aspects": config.feedback_simulator.max_aspects,
            "max_retries": config.feedback_simulator.max_retries,
        }
    return Experiment(
        task.parent / "experiment.yaml",
        {
            "experiment_id": config.experiment_id,
            "benchmark": "biomnibench-da",
            "tasks_dir": str(task.parent.resolve()),
            "tasks": [task.name],
            "randomization": {"seed": 1, "replicates": 1},
            "conditions": [{
                "condition_id": config.condition_id,
                "prompt": config.prompt_profile.value,
                "rubric_evolution": config.rubric_evolution.value,
            }],
            "protocol": protocol,
            "outcome_audit": {},
            "dag": {},
        },
    )


def test_expected_rubric_versions_use_condition_metadata() -> None:
    assert _expected_rubric_names(
        {"condition_id": "arbitrary-name", "rubric_evolution": "prospective"},
        3,
    ) == ["r0000.txt", "r0001.txt", "r0002.txt"]
    assert _expected_rubric_names(
        {"condition_id": "misleading-prospective", "rubric_evolution": "static"},
        3,
    ) == ["r0000.txt"]


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
            "normalized_score": score / 100,
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


def test_evolved_candidate_uses_canonical_judge_source() -> None:
    rubric = SubmissionRevisionController._frozen_evolved_rubric(
        "candidate rubric\n",
        "a" * 64,
    )

    assert rubric.source == "evolved"


def test_prospective_fixed_original_score_is_separate_from_on_policy_score(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    base = _config(tmp_path, task, rounds=1)
    config = replace(
        base,
        condition_id="base-prospective",
        assignment_id=f"{task.name}--rep-001--base-prospective",
        rubric_evolution=RubricEvolution.PROSPECTIVE,
    )
    judge = FakeJudge(task, (0, 72), tmp_path / "judge")
    controller = SubmissionRevisionController(
        config,
        RevisionDependencies(
            session=FakeSession(),
            judge=judge,
            evolver=object(),  # type: ignore[arg-type]
        ),
    )
    submission = config.experiment_dir / "submissions" / "s001"
    submission.mkdir(parents=True)

    fixed_score = controller._fixed_original_score(
        submission_dir=submission,
        submission_id="s001",
        turn_index=1,
        on_policy_score=100,
    )

    assert fixed_score == 72
    attempt_id = fixed_original_attempt_id(
        config.assignment_id,
        "s001",
        controller.rubric.sha256,
    )
    assert (
        config.experiment_dir
        / "evaluations"
        / "s001"
        / controller.rubric.sha256
        / attempt_id
    ).is_dir()


def test_revision_accepts_seed_judgment_from_an_older_code_build(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    legacy_identity = _identity(task)
    legacy_identity.update({
        "scorer_version": "rubric-scoring-v1",
        "judge_source_sha256": "a" * 64,
        "judge_runner_sha256": "b" * 64,
        "scorer_module_sha256": "c" * 64,
    })
    config = _config(
        tmp_path,
        task,
        rounds=1,
        seed_scoring_identity=legacy_identity,
    )
    judge = FakeJudge(task, (0, 90), tmp_path / "judge")

    result = SubmissionRevisionController(
        config,
        RevisionDependencies(session=FakeSession(), judge=judge),
    ).run()

    assert result.scores == (80, 90)
    manifest = json.loads((config.experiment_dir / "manifest.json").read_text())
    assert manifest["scoring_identity"] == judge.identity
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


def test_revision_rejects_seed_judgment_with_different_scoring_semantics(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    incompatible_identity = _identity(task)
    incompatible_identity["review_mode"] = "trajectory"
    config = _config(
        tmp_path,
        task,
        rounds=1,
        seed_scoring_identity=incompatible_identity,
    )

    with pytest.raises(RuntimeError, match="scoring contract"):
        SubmissionRevisionController(
            config,
            RevisionDependencies(
                session=FakeSession(),
                judge=FakeJudge(task, (0, 90), tmp_path / "judge"),
            ),
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
    assert result.fixed_original_scores == (80, 55, 70)
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
    state_path = config.experiment_dir / "state.json"
    state = json.loads(state_path.read_text())
    assert state["schema_version"] == 2
    assert state["fixed_original_scores"] == [80, 55, 70]
    state["next_prompt"] = "persisted historical prompt\n"
    state_path.write_text(json.dumps(state))
    validate_completed_revision(
        config.experiment_dir,
        assignment,
        _design(config, task),
        config.seed_run_dir,
    )
    manifest = json.loads((config.experiment_dir / "manifest.json").read_text())
    assert manifest["live_workspace_removed"] is True
    assert manifest["experiment_id"] == EXPERIMENT_ID
    assert manifest["judge_base_url"] is None
    assert manifest["rubric_proposer_base_url"] is None

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


def test_simulated_user_feedback_is_llm_generated_partial_and_resumable(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    private_value = "expected-private-value-37-of-200"
    (task / "tests" / "rubric.txt").write_text(
        "Criterion 1: Correct result\nLevels: A=100 B=50 C=0\n"
        f"[A]: The private reference is {private_value}.\n"
    )
    simulator_config = SimulatedUserConfig(
        model="gpt-simulated-user",
        max_output_tokens=1_024,
        max_aspects=2,
        max_retries=1,
    )
    config = replace(
        _config(tmp_path, task, rounds=1),
        feedback_policy=FeedbackPolicy.SIMULATED_USER,
        feedback_simulator=simulator_config,
    )
    requests: list[SimulatedUserRequest] = []
    selection_count = 0
    comment_count = 0

    def generate_user_feedback(
        requested: SimulatedUserConfig,
        request: SimulatedUserRequest,
    ) -> SimulatedUserGeneration:
        nonlocal selection_count, comment_count
        requests.append(request)
        assert requested == simulator_config
        assert "score" not in request.evidence
        assert "judge" not in request.evidence
        required = request.schema["required"]
        if required == ["referenced_criteria", "concern_categories"]:
            selection_count += 1
            assert private_value in request.evidence
            assert "<private_rubric>" in request.evidence
            text = json.dumps({
                "referenced_criteria": ["criterion_1"],
                "concern_categories": ["evidence_traceability"],
            })
            response_id = f"selection-{selection_count}"
        else:
            comment_count += 1
            assert required == ["comment"]
            assert private_value not in request.evidence
            assert "<private_rubric>" not in request.evidence
            text = json.dumps({
                "comment": (
                    f"The result in response {comment_count} is not yet well "
                    "supported. Please show the decisive check and explain why "
                    "it justifies the conclusion."
                ),
            })
            response_id = f"comment-{comment_count}"
        return SimulatedUserGeneration(
            text=text,
            provider="openai",
            requested_model=simulator_config.model,
            effective_model="gpt-simulated-user-served",
            response_id=response_id,
            request_parameters={"max_output_tokens": 1_024},
            provider_metadata={"usage": {"output_tokens": 40}},
        )

    simulator = SimulatedUserFeedback(
        simulator_config,
        generator=generate_user_feedback,
    )
    session = FakeSession()
    judge = FakeJudge(task, (80, 90), tmp_path / "judge")
    result = SubmissionRevisionController(
        config,
        RevisionDependencies(
            session=session,
            judge=judge,
            feedback_simulator=simulator,
        ),
    ).run()

    assert result.scores == (80, 90)
    assert len(requests) == 4
    assert selection_count == comment_count == 2
    assert "response 1 is not yet well supported" in session.prompts[0]
    assert "80/100" not in session.prompts[0]
    feedback = json.loads(
        (config.experiment_dir / "feedback" / "s000.json").read_text()
    )
    assert set(feedback) == {"schema_version", "policy", "comment"}
    generation = json.loads(
        (
            config.experiment_dir
            / "feedback-generations"
            / "s000.json"
        ).read_text()
    )
    assert generation["output"]["referenced_criteria"] == ["criterion_1"]
    assert generation["output"]["concern_categories"] == [
        "evidence_traceability"
    ]
    assert generation["selection_generation"]["response_id"] == "selection-1"
    assert generation["comment_generation"]["response_id"] == "comment-1"

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


def test_simulated_user_enforces_non_exhaustive_rubric_attention() -> None:
    config = SimulatedUserConfig(
        model="gpt-simulated-user",
        max_output_tokens=512,
        max_aspects=3,
        max_retries=1,
    )
    selection_calls = 0
    comment_calls = 0

    def generate_user_feedback(
        requested: SimulatedUserConfig,
        request: SimulatedUserRequest,
    ) -> SimulatedUserGeneration:
        nonlocal selection_calls, comment_calls
        if request.schema["required"] == [
            "referenced_criteria",
            "concern_categories",
        ]:
            selection_calls += 1
            selected = (
                ["criterion_1", "criterion_2", "criterion_3"]
                if selection_calls == 1
                else ["criterion_1", "criterion_3"]
            )
            text = json.dumps({
                "referenced_criteria": selected,
                "concern_categories": ["result_reporting", "source_support"],
            })
            response_id = f"selection-{selection_calls}"
        else:
            comment_calls += 1
            text = json.dumps({
                "comment": (
                    "Please strengthen the evidence and explain the conclusion."
                ),
            })
            response_id = f"comment-{comment_calls}"
        return SimulatedUserGeneration(
            text=text,
            provider="openai",
            requested_model=requested.model,
            effective_model="gpt-simulated-user-served",
            response_id=response_id,
            request_parameters={
                "max_output_tokens": request.max_output_tokens,
            },
        )

    simulator = SimulatedUserFeedback(config, generator=generate_user_feedback)
    record = simulator.generate(
        experiment_id="experiment",
        assignment_id="assignment",
        submission_id="s000",
        rubric_version=0,
        instruction="Analyze the table.",
        rubric_text=(
            "Criterion 1: Result\nLevels: A=40 B=0\n"
            "Criterion 2: Evidence\nLevels: A=30 B=0\n"
            "Criterion 3: Explanation\nLevels: A=30 B=0\n"
        ),
        current_submission="The result is positive.",
    )

    assert selection_calls == 2
    assert comment_calls == 1
    assert record["attempt_count"] == 2
    assert record["output"]["referenced_criteria"] == [  # type: ignore[index]
        "criterion_1",
        "criterion_3",
    ]


def test_solver_workspace_data_is_disposable_and_artifacts_are_persisted(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    config = _config(tmp_path, task, rounds=1)

    class WorkspaceMutationSession(FakeSession):
        def _turn(
            self,
            workspace: Path,
            prompt: str,
            turn_dir: Path,
            session_id: str,
        ) -> SessionTurnResult:
            assert (workspace / "artifacts").is_dir()
            (workspace / "data" / "derived.tsv").write_text("derived\n")
            (workspace / "artifacts" / "derived.tsv").write_text("persisted\n")
            return super()._turn(workspace, prompt, turn_dir, session_id)

    result = SubmissionRevisionController(
        config,
        RevisionDependencies(
            session=WorkspaceMutationSession(),
            judge=FakeJudge(task, (80, 90), tmp_path / "judge"),
        ),
    ).run()

    assert result.scores == (80, 90)
    assert (task / "environment" / "data" / "values.csv").read_text() == "x\n1\n"
    snapshot = config.experiment_dir / "submissions" / "s001" / "workspace"
    assert (snapshot / "artifacts" / "derived.tsv").read_text() == "persisted\n"
    assert not (snapshot / "data").exists()


def test_canonical_source_data_mutation_is_still_rejected(tmp_path: Path) -> None:
    task = _write_task(tmp_path)
    config = _config(tmp_path, task, rounds=1)

    class SourceMutationSession(FakeSession):
        def _turn(
            self,
            workspace: Path,
            prompt: str,
            turn_dir: Path,
            session_id: str,
        ) -> SessionTurnResult:
            result = super()._turn(workspace, prompt, turn_dir, session_id)
            (task / "environment" / "data" / "values.csv").write_text("changed\n")
            return result

    with pytest.raises(RuntimeError, match="canonical task data changed"):
        SubmissionRevisionController(
            config,
            RevisionDependencies(
                session=SourceMutationSession(),
                judge=FakeJudge(task, (80, 90), tmp_path / "judge"),
            ),
        ).run()


def test_solver_prompt_routes_generated_outputs_to_artifacts() -> None:
    prompt = solver_prompt(PromptProfile.DILIGENT)

    assert "under ./artifacts" in prompt
    assert "./artifacts/: supporting files" in prompt
    assert "Required deliverables:" in prompt
    assert "Produce exactly these local files:" not in prompt


def test_completed_revision_validates_model_endpoint_manifest_fields(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    config = replace(
        _config(tmp_path, task, rounds=1),
        judge_model="judge-model",
        judge_base_url="http://judge:8000/v1",
        rubric_proposer_model="proposer-model",
        rubric_proposer_base_url="http://proposer:8000/v1",
    )
    SubmissionRevisionController(
        config,
        RevisionDependencies(
            session=FakeSession(),
            judge=FakeJudge(task, (80, 90), tmp_path / "judge"),
        ),
    ).run()
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
        vllm_endpoints={
            "judge-model": "http://judge:8000/v1",
            "proposer-model": "http://proposer:8000/v1",
        },
    )
    manifest = json.loads((config.experiment_dir / "manifest.json").read_text())
    assert manifest["judge_base_url"] == "http://judge:8000/v1"
    assert manifest["rubric_proposer_base_url"] == "http://proposer:8000/v1"


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


def test_judge_resume_accepts_the_persisted_historical_prompt(tmp_path: Path) -> None:
    task = _write_task(tmp_path)
    config = _config(tmp_path, task, rounds=1)
    session = FakeSession()
    judge = FakeJudge(task, (80, 90), tmp_path / "judge")

    class InterruptDuringSeedJudge(SubmissionRevisionController):
        interrupted = False

        def _write_state(self, state) -> None:
            super()._write_state(state)
            if state.phase.value == "judge_in_progress" and not self.interrupted:
                self.interrupted = True
                raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        InterruptDuringSeedJudge(
            config,
            RevisionDependencies(session=session, judge=judge),
        ).run()
    state_path = config.experiment_dir / "state.json"
    state = json.loads(state_path.read_text())
    assert state["phase"] == "judge_in_progress"
    state["next_prompt"] = "historical initial prompt\n"
    state_path.write_text(json.dumps(state))

    result = SubmissionRevisionController(
        replace(config, resume=True),
        RevisionDependencies(session=session, judge=judge),
    ).run()

    assert result.scores == (80, 90)
    assert session.prompts[0] != "historical initial prompt\n"


def test_resume_rebuilds_missing_live_workspace_from_sealed_submission(
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
    manifest = json.loads((config.experiment_dir / "manifest.json").read_text())
    old_live_root = Path(manifest["live_workspace_dir"]).parent
    remove_live_tree(old_live_root, config.experiment_dir)

    result = SubmissionRevisionController(
        replace(config, resume=True),
        RevisionDependencies(session=session, judge=judge),
    ).run()

    assert result.scores == (80, 90)
    events = [
        json.loads(line)
        for line in (config.experiment_dir / "events.jsonl").read_text().splitlines()
    ]
    assert any(event["event"] == "live_workspace_rebuilt" for event in events)


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


def test_failed_solver_turn_rejects_a_prompt_that_differs_from_executed_turn(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    config = _config(tmp_path, task, rounds=1)
    session = FakeSession(fail=True)
    judge = FakeJudge(task, (80, 90), tmp_path / "judge")
    dependencies = RevisionDependencies(session=session, judge=judge)

    with pytest.raises(RuntimeError, match="provider exited"):
        SubmissionRevisionController(config, dependencies).run()
    state_path = config.experiment_dir / "state.json"
    state = json.loads(state_path.read_text())
    state["next_prompt"] = "different prompt\n"
    state_path.write_text(json.dumps(state))

    with pytest.raises(RuntimeError, match="executed turn"):
        SubmissionRevisionController(
            replace(config, resume=True), dependencies
        ).run()


def test_resume_promotes_an_existing_valid_submission_snapshot(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    config = _config(tmp_path, task, rounds=1)
    session = FakeSession()
    judge = FakeJudge(task, (80, 90), tmp_path / "judge")
    dependencies = RevisionDependencies(session=session, judge=judge)

    class InterruptAfterSnapshot(SubmissionRevisionController):
        interrupted = False

        def _snapshot_submission(self, submission_id, workspace, trajectories, session_id):
            result = super()._snapshot_submission(
                submission_id, workspace, trajectories, session_id
            )
            if submission_id == "s001" and not self.interrupted:
                self.interrupted = True
                raise KeyboardInterrupt
            return result

    with pytest.raises(KeyboardInterrupt):
        InterruptAfterSnapshot(config, dependencies).run()
    state_path = config.experiment_dir / "state.json"
    state = json.loads(state_path.read_text())
    state["phase"] = "turn_in_progress"
    state_path.write_text(json.dumps(state))
    turn = config.experiment_dir / "turns" / "turn-001"
    status_path = turn / "status.json"
    turn.chmod(turn.stat().st_mode | stat.S_IWUSR | stat.S_IXUSR)
    status_path.chmod(status_path.stat().st_mode | stat.S_IWUSR)
    status = json.loads(status_path.read_text())
    status.update({
        "status": "failed",
        "exit_code": 0,
        "max_retries": config.agent.retries,
        "attempt_count": 1,
        "attempts": [{
            "process_exit_code": 0,
            "stream_errors": [],
            "output_errors": [],
        }],
    })
    status_path.write_text(json.dumps(status))

    result = SubmissionRevisionController(
        replace(config, resume=True), dependencies
    ).run()

    assert result.scores == (80, 90)
    assert len(session.prompts) == 1
    recovered_status = json.loads(status_path.read_text())
    assert recovered_status["recovered_on_resume"] is True
    assert recovered_status["status"] == "accepted_after_interrupted_boundary"


@pytest.mark.parametrize(
    "failure_reason",
    [
        "controlled Codex configuration changed",
        "codex did not report a session ID during resume",
    ],
)
def test_prelaunch_session_failure_resumes_without_trajectory(
    tmp_path: Path,
    failure_reason: str,
) -> None:
    task = _write_task(tmp_path)
    config = _config(tmp_path, task, rounds=2)

    class ConfigFailureSession(FakeSession):
        fail_once = True

        def resume(
            self,
            workspace: Path,
            prompt: str,
            turn_dir: Path,
            session_id: str,
        ) -> SessionTurnResult:
            if self.fail_once:
                self.fail_once = False
                raise RuntimeError(failure_reason)
            return super().resume(workspace, prompt, turn_dir, session_id)

    session = ConfigFailureSession()
    judge = FakeJudge(task, (80, 90, 95), tmp_path / "judge")
    dependencies = RevisionDependencies(session=session, judge=judge)

    with pytest.raises(RuntimeError, match=failure_reason):
        SubmissionRevisionController(config, dependencies).run()
    failed_turn = config.experiment_dir / "turns" / "turn-002"
    assert not (failed_turn / "trajectory.stream.jsonl").exists()

    result = SubmissionRevisionController(
        replace(config, resume=True), dependencies
    ).run()

    assert result.scores == (80, 90, 95)
    assert len(session.sessions) == 2
    assert (
        config.experiment_dir
        / "interrupted-turns"
        / "turn-002"
        / "status.json"
    ).is_file()


def test_interrupted_attempt_artifacts_restore_boundary_and_restart_session(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    config = _config(tmp_path, task, rounds=2)
    session = FakeSession()
    judge = FakeJudge(task, (80, 90, 95), tmp_path / "judge")
    dependencies = RevisionDependencies(session=session, judge=judge)

    class InterruptAfterFirstRevision(SubmissionRevisionController):
        def _append_event(self, payload: dict[str, object]) -> None:
            super()._append_event(payload)
            if payload.get("event") == "submission_judged" and payload.get(
                "submission_id"
            ) == "s001":
                raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        InterruptAfterFirstRevision(config, dependencies).run()

    state_path = config.experiment_dir / "state.json"
    manifest_path = config.experiment_dir / "manifest.json"
    state = json.loads(state_path.read_text())
    manifest = json.loads(manifest_path.read_text())
    state["phase"] = "turn_in_progress"
    state["effective_solver_model"] = None
    manifest["effective_solver_model"] = None
    state_path.write_text(json.dumps(state))
    manifest_path.write_text(json.dumps(manifest))

    turn = config.experiment_dir / "turns" / "turn-002"
    attempts = turn / "attempts"
    attempts.mkdir(parents=True)
    (turn / "prompt.txt").write_text(state["next_prompt"])
    (attempts / "attempt-001.prompt.txt").write_text(state["next_prompt"])
    (attempts / "attempt-001.trajectory.stream.jsonl").write_text(
        '{"type":"item.completed"}\n'
    )
    workspace = Path(manifest["live_workspace_dir"])
    (workspace / "answer.txt").write_text("uncertain interrupted output\n")

    result = SubmissionRevisionController(
        replace(config, resume=True), dependencies
    ).run()

    assert result.scores == (80, 90, 95)
    assert session.sessions == ["solver-session", "solver-session"]
    archived = config.experiment_dir / "interrupted-turns" / "turn-002"
    assert (archived / "attempts" / "attempt-001.trajectory.stream.jsonl").is_file()
    events = [
        json.loads(line)
        for line in (config.experiment_dir / "events.jsonl").read_text().splitlines()
    ]
    assert any(event["event"] == "solver_session_discarded" for event in events)


def test_live_root_defaults_outside_repository(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("BIOMNIBENCH_LIVE_ROOT", raising=False)
    root = live_root_parent()
    assert "submission-live" in root.name
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
        "normalized_score": 0.8,
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
    simulated = project_simulated_user_feedback(
        validation,
        rubric,
        rubric_sha,
        "The evidence is hard to verify from the response. Please explain the "
        "key check and connect it to the conclusion.",
    )
    assert "needs more evidence" in full.prompt
    assert '"title": "Evidence"' in semi.prompt
    assert "needs more evidence" not in semi.prompt
    assert "Criterion 2" not in score.prompt
    assert set(simulated.payload) == {"schema_version", "policy", "comment"}
    assert "The evidence is hard to verify" in simulated.prompt
    assert "80/100" not in simulated.prompt
    assert "needs more evidence" not in simulated.prompt
    assert '"selected_level"' not in simulated.prompt
    assert all(
        "under ./artifacts, not ./data" in item.prompt
        for item in (full, semi, score, simulated)
    )
    assert score.score == 80
