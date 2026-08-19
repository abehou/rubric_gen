from __future__ import annotations

import compileall
import hashlib
import json
import os
import shutil
import stat
from dataclasses import replace
from pathlib import Path
from typing import Callable
from types import SimpleNamespace

import pytest

from rubric_gen.runtime.agents.models import AgentRunConfig
from rubric_gen.runtime.agents.workspaces import TaskWorkspace
from rubric_gen.submission_revision.prompts import PromptProfile, solver_prompt
from rubric_gen.runtime.agents.sessions import SessionTurnResult
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.experiment import Experiment
from rubric_gen.submission_revision.controller import (
    SubmissionRevisionController,
    fixed_original_attempt_id,
)
from rubric_gen.submission_revision.judge import (
    FrozenRubricJudge,
    JudgeArtifacts,
    SubmissionJudgeConfig,
    resolve_optimizer_rubric,
)
from rubric_gen.submission_revision.models import (
    RevisionDependencies,
    SubmissionRevisionConfig,
)
from rubric_gen.submission_revision.artifacts import (
    live_root_parent,
    make_tree_owner_writable,
    make_tree_read_only,
    read_json_object,
    remove_live_tree,
    sha256_file,
    solution_tree_sha256,
    tree_sha256,
)
from rubric_gen.submission_revision.feedback import (
    FeedbackPolicy,
    project_bank_feedback,
    project_bank_simulated_user_feedback,
)
from rubric_gen.submission_revision.seeds import SEED_KIND, SEED_SET_KIND
from rubric_gen.submission_revision.user_simulator import (
    SimulatedUserConfig,
    SimulatedUserFeedback,
    SimulatedUserGeneration,
    SimulatedUserRequest,
)
from rubric_gen.submission_revision.evolution import (
    BankProposerOutput,
    RubricBankProposer,
    SemanticReviewerOutput,
)
from rubric_gen.submission_revision.study import (
    _expected_bank_names,
    validate_completed_revision,
)
from rubric_gen.submission_revision.rubric_bank import (
    CompleteRubric,
    RubricBank,
    RubricBankItem,
    RubricLineage,
    RubricBankPolicy,
    identity_criterion_map,
    parse_rubric_member_presentation,
    render_locked_rubric_member,
)
from rubric_gen.artifacts.hashing import sha256_text
import rubric_gen.submission_revision.study as study_module
import rubric_gen.submission_revision.controller as controller_module
import rubric_gen.submission_revision.judging.paperbench_judge as paperbench_module


EXPERIMENT_ID = "test-experiment"


def test_generic_artifact_reader_rejects_duplicate_json_keys(
    tmp_path: Path,
) -> None:
    path = tmp_path / "artifact.json"
    path.write_text('{"score":1,"score":100}\n')

    with pytest.raises(RuntimeError, match="is not valid JSON"):
        read_json_object(path, "test artifact")


@pytest.fixture(autouse=True)
def _resolve_test_paraphrase(monkeypatch: pytest.MonkeyPatch) -> None:
    def resolve(_root, experiment, task_id, _replicate):
        master = (
            experiment.task_dir(task_id)
            / "tests"
            / str(experiment.protocol["rubric_name"])
        )
        digest = sha256_file(master)
        return SimpleNamespace(
            optimizer_path=master,
            optimizer_sha256=digest,
            master_path=master,
            master_sha256=digest,
        )

    monkeypatch.setattr(study_module, "resolve_paraphrase_selection", resolve)


def _write_task(root: Path, task_id: str = "da-1-1") -> Path:
    task = root / "tasks" / task_id
    (task / "environment" / "data").mkdir(parents=True)
    (task / "tests").mkdir()
    (task / "instruction.md").write_text("Analyze the supplied table.\n")
    (task / "environment" / "data" / "values.csv").write_text("x\n1\n")
    (task / "tests" / "rubric.txt").write_text(
        "Criterion 1: Correct result\n"
        "Description: Evaluate the reported result.\n"
        "Levels: A=100 B=50 C=0\n"
        "[A]: Correct and fully supported.\n"
        "[B]: Partly correct with a material limitation.\n"
        "[C]: Incorrect or unsupported.\n"
    )
    return task


def _identity(
    task: Path,
    *,
    judge_model: str = "test-judge-model",
    base_url: str | None = None,
    experiment_dir: Path | None = None,
) -> dict[str, object]:
    config = SubmissionJudgeConfig(
        task_dir=task,
        experiment_dir=experiment_dir or task.parent.parent / "experiment",
        review="trace",
        judge_model=judge_model,
        base_url=base_url,
        rubric_name=None,
        rubric_set=None,
        rubric_path=task / "tests" / "rubric.txt",
        max_review_chars=None,
    )
    rubric = resolve_optimizer_rubric(config)
    return FrozenRubricJudge(config, rubric).scoring_identity()


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
        "submission_id": "s000",
        "session_id": None,
        "workspace_sha256": workspace_sha,
        "trajectory_sha256": trajectory_sha,
    }))
    judgment = seed_root / "initial_judgment"
    judgment.mkdir()
    (judgment / "judge_input_trace.md").write_text("seed-trace\n")
    (judgment / "judge_input_answer.txt").write_text("seed-answer\n")
    evaluation = judgment / "evaluation.json"
    level = "A" if initial_score >= 80 else "B"
    evaluation.write_text(json.dumps({
        "criteria": {"criterion_1": {"level": level, "reason": "seed"}},
        "reasoning": "seed",
    }))
    identity = dict(scoring_identity or _identity(task))
    validation = judgment / "score_validation.json"
    usage = judgment / "usage.json"
    usage.write_text('{"usage":{}}')
    validation.write_text(json.dumps({
        **identity,
        "review_input_sha256": sha256_text("seed-trace\n"),
        "answer_input_sha256": sha256_text("seed-answer\n"),
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
        "kind": SEED_SET_KIND,
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
        assignment_id=f"{task.name}--rep-001--base-fixed",
        condition_id="base-fixed",
        replicate=1,
        execution_order=1,
        optimizer_rubric_path=task / "tests" / "rubric.txt",
        master_rubric_name="rubric.txt",
        rubric_semantic_judge_model="semantic-model",
        rubric_semantic_judge_max_calls=rounds,
        rubric_semantic_judge_max_request_bytes=1_048_576,
        rubric_semantic_judge_max_output_tokens=32_768,
        feedback_policy=FeedbackPolicy.FULL,
        prompt_profile=PromptProfile.BASE,
        review="trace",
        judge_model="test-judge-model",
        show_progress=False,
    )


def _design(config: SubmissionRevisionConfig, task: Path) -> Experiment:
    agent = config.agent
    protocol: dict[str, object] = {
        "revision_rounds": config.revision_rounds,
        "feedback_policy": config.feedback_policy.value,
        "rubric_proposer_model": config.rubric_proposer_model,
        "rubric_proposer_max_retries": config.rubric_proposer_max_retries,
        "rubric_semantic_judge_model": config.rubric_semantic_judge_model,
        "rubric_semantic_judge_max_calls_per_assignment": (
            config.rubric_semantic_judge_max_calls
        ),
        "rubric_semantic_judge_max_request_bytes_per_call": (
            config.rubric_semantic_judge_max_request_bytes
        ),
        "rubric_semantic_judge_max_output_tokens_per_call": (
            config.rubric_semantic_judge_max_output_tokens
        ),
        "review": config.review,
        "judge_model": config.judge_model,
        "judge_max_retries": config.judge_max_retries,
        "max_review_chars": config.max_review_chars,
        "rubric_name": config.master_rubric_name,
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
            "conditions": [
                {
                    "condition_id": (
                        config.condition_id
                        if policy is config.rubric_policy
                        else f"test-{policy.value.replace('_', '-')}"
                    ),
                    "prompt": config.prompt_profile.value,
                    "rubric_policy": policy.value,
                }
                for policy in RubricBankPolicy
            ],
            "protocol": protocol,
            "rubric_paraphrases": {
                "count": 2,
                "model": "test-paraphraser",
                "max_retries": 0,
            },
            "outcome_audit": {},
            "dag": {},
        },
    )


def test_expected_bank_generations_use_condition_metadata() -> None:
    assert _expected_bank_names(
        {
            "condition_id": "arbitrary-name",
            "rubric_policy": "adaptive_replacement",
        },
        3,
    ) == ["bank-0000", "bank-0001", "bank-0002"]
    assert _expected_bank_names(
        {"condition_id": "misleading", "rubric_policy": "fixed"},
        3,
    ) == ["bank-0000"]


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
    def __init__(
        self,
        task: Path,
        scores: tuple[int, ...],
        root: Path,
        *,
        identity: dict[str, object] | None = None,
    ) -> None:
        self.identity = dict(identity or _identity(task))
        self.task_name = task.name
        self.scores = scores
        self.root = root
        self.calls = 0

    def scoring_identity(self) -> dict[str, object]:
        return dict(self.identity)

    def review_inputs(self, submission_dir: Path) -> tuple[str, str]:
        workspace = submission_dir / "workspace"
        return (
            (workspace / "trace.md").read_text()
            if (workspace / "trace.md").is_file()
            else "",
            (workspace / "answer.txt").read_text()
            if (workspace / "answer.txt").is_file()
            else "",
        )

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
        review_text, answer_text = self.review_inputs(submission_dir)
        (output / "judge_input_trace.md").write_text(review_text)
        (output / "judge_input_answer.txt").write_text(answer_text)
        evaluation = output / "evaluation.json"
        evaluation.write_text(json.dumps({
            "criteria": {"criterion_1": {"level": "A", "reason": "checked"}},
            "reasoning": "checked",
        }))
        validation = output / "score_validation.json"
        validation.write_text(json.dumps({
            **self.identity,
            "review_input_sha256": sha256_text(review_text),
            "answer_input_sha256": sha256_text(answer_text),
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


def test_seed_materialization_makes_only_the_live_solution_tree_writable(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    config = _config(tmp_path, task, rounds=1)
    controller = SubmissionRevisionController(
        config,
        RevisionDependencies(
            session=FakeSession(),
            judge=FakeJudge(task, (80, 90), tmp_path / "judge"),
        ),
    )
    sealed = controller.seed.submission_dir / "workspace"
    package = sealed / "package"
    package.mkdir()
    source = package / "module.py"
    source.write_text("VALUE = 1\n")
    make_tree_read_only(sealed)
    live = tmp_path / "live"
    live.mkdir()

    try:
        controller._materialize_seed(live)

        live_package = live / "package"
        assert live_package.stat().st_mode & stat.S_IWUSR
        assert (live_package / "module.py").stat().st_mode & stat.S_IWUSR
        assert compileall.compile_dir(live_package, quiet=1)
        assert (live_package / "__pycache__").is_dir()
        (live_package / "module.py").unlink()
        (live_package / "replacement.py").write_text("VALUE = 2\n")
        assert source.read_text() == "VALUE = 1\n"
        assert not source.stat().st_mode & stat.S_IWUSR
        assert not package.stat().st_mode & stat.S_IWUSR
    finally:
        make_tree_owner_writable(sealed)


def test_scored_snapshot_restore_makes_only_the_live_copy_writable(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    config = _config(tmp_path, task, rounds=1)
    controller = SubmissionRevisionController(
        config,
        RevisionDependencies(
            session=FakeSession(),
            judge=FakeJudge(task, (80, 90), tmp_path / "judge"),
        ),
    )
    snapshot = config.experiment_dir / "submissions" / "s000"
    sealed_package = snapshot / "workspace" / "package"
    sealed_package.mkdir(parents=True)
    sealed_source = sealed_package / "module.py"
    sealed_source.write_text("VALUE = 1\n")
    trajectory = snapshot / "trajectory.stream.jsonl"
    trajectory.write_text('{"turn":0}\n')
    (snapshot / "status.json").write_text("{}\n")
    (snapshot / "snapshot.json").write_text(json.dumps({
        "submission_id": "s000",
        "workspace_sha256": tree_sha256(snapshot / "workspace"),
        "trajectory_sha256": sha256_file(trajectory),
    }))
    make_tree_read_only(snapshot)

    live = tmp_path / "live"
    TaskWorkspace(task, live).create()
    (live / "stale.py").write_text("raise RuntimeError\n")
    make_tree_read_only(live)

    try:
        controller._restore_last_scored_workspace(
            SimpleNamespace(submission_ids=["s000"]),
            live,
        )

        live_package = live / "package"
        assert compileall.compile_dir(live_package, quiet=1)
        (live_package / "module.py").unlink()
        (live_package / "replacement.py").write_text("VALUE = 2\n")
        assert not (live / "stale.py").exists()
        assert sealed_source.read_text() == "VALUE = 1\n"
        assert not sealed_source.stat().st_mode & stat.S_IWUSR
        assert not sealed_package.stat().st_mode & stat.S_IWUSR
    finally:
        make_tree_owner_writable(snapshot)


def _singleton_replacement_proposer(
    config: SubmissionRevisionConfig,
    *,
    run_proposer: Callable[..., BankProposerOutput] | None = None,
) -> RubricBankProposer:
    def propose(**kwargs) -> BankProposerOutput:
        stage = kwargs["stage"]
        schema = kwargs["response_schema"]
        if stage == "anchor":
            anchor = schema["properties"]["specification_anchor"]
            prior_hash = anchor["properties"]["prior_content_sha256"]["enum"][0]
            value: dict[str, object] = {
                "specification_anchor": {
                    "lineage": "retained",
                    "prior_content_sha256": prior_hash,
                    "rubric": None,
                }
            }
        else:
            member_schema = schema["properties"]["members"]["items"]
            prior_hashes = member_schema["properties"][
                "prior_content_sha256"
            ]["anyOf"][0]["enum"]
            criteria = (
                schema["properties"]["members"]["items"]["properties"]
                ["presentation"]["anyOf"][0]["properties"]["criteria"]
            )
            criterion_ids = criteria["items"]["properties"]
            criterion_ids = criterion_ids["anchor_criterion_id"]["enum"]

            def presentation(label: str) -> dict[str, object]:
                return {
                    "title": f"{label} presentation",
                    "overview": f"Inspect the full task through {label} evidence.",
                    "criteria": [{
                        "anchor_criterion_id": criterion_id,
                        "heading": f"{label} {criterion_id}",
                        "lens": f"Inspect concrete {label} evidence.",
                    } for criterion_id in criterion_ids],
                }

            first_generation = "replacement_generation_round: 1" in kwargs[
                "evidence"
            ]
            value = {"members": [{
                "lineage": "new" if first_generation else "retained",
                "prior_content_sha256": None if first_generation else prior_hashes[0],
                "presentation": (
                    presentation("complete") if first_generation else None
                ),
            }]}
        return BankProposerOutput(
            proposal_text=json.dumps(value),
            cost={
                "cost_usd": None,
                "estimated_cost_usd": 0.01,
                "cost_source": "test-estimate",
            },
            generation={
                "provider": "openai",
                "requested_model": config.rubric_proposer_model,
                "effective_model": config.rubric_proposer_model,
                "response_id": "singleton-replacement",
                "request_parameters": {"max_output_tokens": 96_000},
                "usage": {"input_tokens": 10, "output_tokens": 20},
            },
        )

    def review(**kwargs) -> SemanticReviewerOutput:
        members = kwargs["response_schema"]["properties"]["members"]
        anchor_schema = kwargs["response_schema"]["properties"][
            "anchor_fidelity"
        ]
        anchor_properties = anchor_schema["properties"]
        anchor_fidelity = (
            {"status": "not_applicable"}
            if "status" in anchor_properties
            else {
                "task_fidelity": "faithful",
                "prior_anchor_fidelity": "faithful",
                "issues": [],
            }
        )
        value = {"anchor_fidelity": anchor_fidelity, "members": {}}
        for member_hash, member_schema in members["properties"].items():
            criterion_ids = member_schema["properties"]["criteria"]["required"]
            value["members"][member_hash] = {
                "overall": "equivalent",
                "criteria": {
                    criterion_id: "equivalent" for criterion_id in criterion_ids
                },
                "issues": [],
            }
        return SemanticReviewerOutput(
            response_text=json.dumps(value),
            cost={
                "cost_usd": None,
                "estimated_cost_usd": 0.01,
                "cost_source": "test-estimate",
            },
            generation={
                "provider": "openai",
                "requested_model": config.rubric_semantic_judge_model,
                "effective_model": config.rubric_semantic_judge_model,
                "response_id": "semantic-review",
                "request_parameters": {"max_output_tokens": 32_768},
                "usage": {"input_tokens": 10, "output_tokens": 10},
            },
        )

    return RubricBankProposer(
        benchmark=config.benchmark,
        model=config.rubric_proposer_model,
        base_url=None,
        semantic_judge_model=config.rubric_semantic_judge_model,
        semantic_judge_base_url=None,
        semantic_judge_max_calls=config.rubric_semantic_judge_max_calls,
        semantic_judge_max_request_bytes=(
            config.rubric_semantic_judge_max_request_bytes
        ),
        semantic_judge_max_output_tokens=(
            config.rubric_semantic_judge_max_output_tokens
        ),
        max_retries=config.rubric_proposer_max_retries,
        run_proposer=run_proposer or propose,
        run_semantic_reviewer=review,
    )


def test_bank_member_uses_canonical_judge_source() -> None:
    rubric = SubmissionRevisionController._frozen_bank_member(
        "candidate rubric\n",
        "a" * 64,
    )

    assert rubric.source == "rubric-path"


@pytest.mark.parametrize(
    ("field", "different"),
    [
        ("benchmark", SubmissionBenchmarkId.PAPERBENCH_CODE_DEV),
        ("model", "different-proposer"),
        ("base_url", "http://127.0.0.1:9000/v1"),
        ("max_retries", 7),
        ("service_tier", "priority"),
        ("semantic_judge_model", "different-reviewer"),
        ("semantic_judge_base_url", "http://127.0.0.1:9001/v1"),
        ("semantic_judge_max_calls", 2),
        ("semantic_judge_max_request_bytes", 999_999),
        ("semantic_judge_max_output_tokens", 16_384),
    ],
)
def test_controller_rejects_an_injected_bank_proposer_contract_mismatch(
    tmp_path: Path,
    field: str,
    different: object,
) -> None:
    task = _write_task(tmp_path)
    base = _config(tmp_path, task, rounds=1)
    config = replace(
        base,
        condition_id="base-nonadaptive-replacement",
        assignment_id=f"{task.name}--rep-001--base-nonadaptive-replacement",
        rubric_policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
    )
    proposer = _singleton_replacement_proposer(config)
    setattr(proposer, field, different)

    with pytest.raises(ValueError, match="contract differs"):
        SubmissionRevisionController(
            config,
            RevisionDependencies(
                session=FakeSession(),
                judge=FakeJudge(task, (80,), tmp_path / "judge"),
                bank_proposer=proposer,
            ),
        )


def test_adaptive_fixed_original_score_is_separate_from_on_policy_score(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    base = _config(tmp_path, task, rounds=1)
    config = replace(
        base,
        condition_id="base-adaptive-replacement",
        assignment_id=f"{task.name}--rep-001--base-adaptive-replacement",
        rubric_policy=RubricBankPolicy.ADAPTIVE_REPLACEMENT,
    )
    judge = FakeJudge(task, (0, 72), tmp_path / "judge")
    controller = SubmissionRevisionController(
        config,
        RevisionDependencies(
            session=FakeSession(),
            judge=judge,
            bank_proposer=_singleton_replacement_proposer(
                config,
                run_proposer=lambda **_kwargs: pytest.fail(
                    "this unit test must not propose a bank"
                ),
            ),
        ),
    )
    replacement_rubric = CompleteRubric.from_content(
        controller.initial_bank.bank.items[0].rubric.content.replace(
            "Correct result", "Independent result"
        )
    )
    replacement_presentation = parse_rubric_member_presentation({
        "title": "replacement presentation",
        "overview": "Inspect the complete replacement anchor.",
        "criteria": [{
            "anchor_criterion_id": "criterion_1",
            "heading": "replacement result",
            "lens": "Inspect complete result evidence.",
        }],
    })
    replacement_member, replacement_map = render_locked_rubric_member(
        replacement_rubric,
        replacement_presentation,
    )
    replacement_bank = RubricBank(
        generation_round=2,
        source_boundary=1,
        specification_anchor=replacement_rubric,
        specification_anchor_lineage=RubricLineage.REFINED,
        prior_specification_anchor_sha256=(
            controller.initial_bank.bank.specification_anchor.content_sha256
        ),
        items=(
            RubricBankItem(
                rubric=replacement_member,
                weight=1.0,
                lineage=RubricLineage.NEW,
                criterion_map=replacement_map,
                prior_content_sha256=None,
                presentation=replacement_presentation,
            ),
        ),
    )
    controller._active_bank_generation = lambda _turn: SimpleNamespace(  # type: ignore[method-assign]
        bank=replacement_bank
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
        controller.initial_rubric.sha256,
    )
    assert (
        config.experiment_dir
        / "evaluations"
        / "s001"
        / controller.initial_rubric.sha256
        / attempt_id
    ).is_dir()


def test_fixed_paraphrase_accepts_separate_master_rubric_score(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    optimizer_rubric = tmp_path / "optimizer-rubric.txt"
    optimizer_rubric.write_text(
        "Criterion 1: Produce the correct result\n"
        "Description: Evaluate the result.\n"
        "Levels: A=100 B=50 C=0\n"
        "[A]: Correct and fully supported.\n"
        "[B]: Partly correct.\n"
        "[C]: Incorrect or unsupported.\n"
    )
    config = replace(
        _config(tmp_path, task, rounds=1),
        optimizer_rubric_path=optimizer_rubric,
    )
    optimizer_identity = _identity(task)
    optimizer_identity.update({
        "rubric_source": "rubric-path",
        "rendered_rubric_sha256": sha256_file(optimizer_rubric),
    })
    master_judge = FakeJudge(task, (0, 72), tmp_path / "master-judge")
    controller = SubmissionRevisionController(
        config,
        RevisionDependencies(
            session=FakeSession(),
            judge=FakeJudge(
                task,
                (0, 90),
                tmp_path / "optimizer-judge",
                identity=optimizer_identity,
            ),
            master_judge=master_judge,
        ),
    )
    controller._active_bank_generation = lambda _turn: controller.initial_bank  # type: ignore[method-assign]
    submission = config.experiment_dir / "submissions" / "s001"
    submission.mkdir(parents=True)

    fixed_score = controller._fixed_original_score(
        submission_dir=submission,
        submission_id="s001",
        turn_index=1,
        on_policy_score=90,
    )

    assert fixed_score == 72
    attempt_id = fixed_original_attempt_id(
        config.assignment_id,
        "s001",
        controller.master_rubric.sha256,
    )
    assert (
        config.experiment_dir
        / "evaluations"
        / "s001"
        / controller.master_rubric.sha256
        / attempt_id
    ).is_dir()


def test_revision_rejects_seed_judgment_from_a_different_code_build(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    stale_identity = _identity(task)
    stale_identity.update({
        "judge_source_sha256": "a" * 64,
        "judge_runner_sha256": "b" * 64,
        "scorer_module_sha256": "c" * 64,
    })
    config = _config(
        tmp_path,
        task,
        rounds=1,
        seed_scoring_identity=stale_identity,
    )
    judge = FakeJudge(task, (0, 90), tmp_path / "judge")

    with pytest.raises(RuntimeError, match="scoring contract"):
        SubmissionRevisionController(
            config,
            RevisionDependencies(session=FakeSession(), judge=judge),
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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("judge_api_base", "https://different-judge.invalid/v1"),
        ("benchmark", SubmissionBenchmarkId.PAPERBENCH_CODE_DEV.value),
        ("grading_engine", "paperbench-structured"),
    ],
)
def test_revision_rejects_seed_judgment_with_different_dispatch_identity(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    task = _write_task(tmp_path)
    incompatible_identity = _identity(task)
    incompatible_identity[field] = value
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


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("judge_api_base", "https://different-judge.invalid/v1"),
        ("benchmark", SubmissionBenchmarkId.PAPERBENCH_CODE_DEV.value),
        ("grading_engine", "paperbench-structured"),
    ],
)
def test_study_rejects_changed_non_rubric_judge_execution_identity(
    tmp_path: Path,
    field: str,
    value: str,
) -> None:
    task = _write_task(tmp_path)
    config = _config(tmp_path, task, rounds=0)
    SubmissionRevisionController(
        config,
        RevisionDependencies(
            session=FakeSession(),
            judge=FakeJudge(task, (80,), tmp_path / "judge"),
        ),
    ).run()
    manifest_path = config.experiment_dir / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["initial_member_scoring_identity"][field] = value
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(RuntimeError, match="execution contracts"):
        validate_completed_revision(
            config.experiment_dir,
            {
                "assignment_id": config.assignment_id,
                "task_id": task.name,
                "replicate": 1,
                "condition_id": config.condition_id,
                "execution_order": 1,
            },
            _design(config, task),
            config.seed_run_dir,
            config.experiment_dir / "paraphrases",
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
    initial_submission = config.experiment_dir / "submissions" / "s000"
    assert json.loads((initial_submission / "status.json").read_text()) == {
        "task": task.name,
        "task_dir": str(task.resolve()),
        "workspace_dir": str(initial_submission / "workspace"),
        "provider": "codex",
        "session_id": None,
        "submission_id": "s000",
        "exit_code": 0,
    }
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
        config.experiment_dir / "paraphrases",
    )
    state_path = config.experiment_dir / "state.json"
    state = json.loads(state_path.read_text())
    assert state["fixed_original_scores"] == [80, 55, 70]
    state["next_prompt"] = "persisted historical prompt\n"
    state_path.write_text(json.dumps(state))
    validate_completed_revision(
        config.experiment_dir,
        assignment,
        _design(config, task),
        config.seed_run_dir,
        config.experiment_dir / "paraphrases",
    )
    manifest = json.loads((config.experiment_dir / "manifest.json").read_text())
    assert manifest["live_workspace_removed"] is True
    assert manifest["experiment_id"] == EXPERIMENT_ID
    assert manifest["judge_base_url"] is None
    assert manifest["rubric_proposer_base_url"] is None
    bank_evaluation = json.loads(
        (config.experiment_dir / "bank-evaluations" / "s000.json").read_text()
    )
    preflight = bank_evaluation["dispatch_preflight"]
    assert preflight["bank_sha256"] == bank_evaluation["bank_sha256"]
    assert preflight["cost_shape"]["member_count"] == 1
    assert preflight["cost_shape"]["criterion_calls"] == 1
    unexpected_bank_file = config.experiment_dir / "rubric-banks" / "unexpected"
    unexpected_bank_file.write_text("not a bank\n")
    with pytest.raises(RuntimeError, match="bank set is incomplete"):
        validate_completed_revision(
            config.experiment_dir,
            assignment,
            _design(config, task),
            config.seed_run_dir,
            config.experiment_dir / "paraphrases",
        )
    unexpected_bank_file.unlink()
    invalid_generation_root = config.experiment_dir / "rubric-generations"
    invalid_generation_root.mkdir()
    with pytest.raises(RuntimeError, match="invalid for a fixed"):
        validate_completed_revision(
            config.experiment_dir,
            assignment,
            _design(config, task),
            config.seed_run_dir,
            config.experiment_dir / "paraphrases",
        )
    invalid_generation_root.rmdir()

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
            config.experiment_dir / "paraphrases",
        )


def test_shared_judgments_cross_conditions_preserve_seed_and_alias_only_resume(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _write_task(tmp_path)
    master_path = task / "tests" / "rubric.txt"
    optimizer_path = tmp_path / "optimizer-rubric.txt"
    optimizer_path.write_text(
        "Criterion 1: Independent result\n"
        "Description: Evaluate the independent result.\n"
        "Levels: A=100 B=50 C=0\n"
        "[A]: Correct and fully supported.\n"
        "[B]: Partly correct with a material limitation.\n"
        "[C]: Incorrect or unsupported.\n"
    )

    def scoring_identity(
        *,
        rubric_path: Path | None = None,
        rubric_name: str | None = None,
    ) -> dict[str, object]:
        judge_config = SubmissionJudgeConfig(
            task_dir=task,
            experiment_dir=tmp_path / "identity-only",
            review="trace",
            judge_model="test-judge-model",
            rubric_name=rubric_name,
            rubric_set=None,
            rubric_path=rubric_path,
            max_review_chars=None,
        )
        rubric = resolve_optimizer_rubric(judge_config)
        return FrozenRubricJudge(judge_config, rubric).scoring_identity()

    master_identity = scoring_identity(rubric_name="rubric.txt")
    optimizer_identity = scoring_identity(rubric_path=optimizer_path)
    base = _config(
        tmp_path,
        task,
        rounds=1,
        seed_scoring_identity=master_identity,
    )
    first_config = replace(
        base,
        experiment_dir=tmp_path / "base-arm",
        assignment_id=f"{task.name}--rep-001--base-fixed",
        condition_id="base-fixed",
        execution_order=1,
        optimizer_rubric_path=optimizer_path,
        prompt_profile=PromptProfile.BASE,
    )
    second_config = replace(
        first_config,
        experiment_dir=tmp_path / "matched-arm",
        assignment_id=f"{task.name}--rep-001--matched-fixed",
        condition_id="matched-fixed",
        execution_order=2,
        prompt_profile=PromptProfile.BASE,
    )
    shared_root = tmp_path / "shared-judgments"

    class ReuseJudge(FakeJudge):
        def evaluate(
            self,
            submission_dir: Path,
            attempt_id: str,
        ) -> JudgeArtifacts:
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
            review_text, answer_text = self.review_inputs(submission_dir)
            (output / "judge_input_trace.md").write_text(review_text)
            (output / "judge_input_answer.txt").write_text(answer_text)
            evaluation = output / "evaluation.json"
            evaluation.write_text(json.dumps({
                "criteria": {
                    "criterion_1": {"level": "A", "reason": "checked"}
                },
                "reasoning": "checked",
            }))
            reward = output / "reward.json"
            reward.write_text(json.dumps({"reward": score / 100}))
            usage = output / "usage.json"
            usage.write_text(json.dumps({"usage": {}}))
            validation = output / "score_validation.json"
            validation.write_text(json.dumps({
                **self.identity,
                "review_input_sha256": sha256_text(review_text),
                "answer_input_sha256": sha256_text(answer_text),
                "task": self.task_name,
                "run_identity": str(output),
                "repeat_index": 1,
                "score": score,
                "normalized_score": score / 100,
                "raw_score": score,
                "selected_levels": {"criterion_1": "A"},
                "criterion_scores": {"criterion_1": score},
                "reward_sha256": sha256_file(reward),
                "evaluation_sha256": sha256_file(evaluation),
                "usage_sha256": sha256_file(usage),
            }))
            return JudgeArtifacts(validation, evaluation)

    first_optimizer = ReuseJudge(
        task,
        (0, 61, 71),
        tmp_path / "first-optimizer",
        identity=optimizer_identity,
    )
    first_master = ReuseJudge(
        task,
        (0, 55),
        tmp_path / "first-master",
        identity=master_identity,
    )
    first_result = SubmissionRevisionController(
        first_config,
        RevisionDependencies(
            session=FakeSession(),
            judge=first_optimizer,
            master_judge=first_master,
        ),
        judgment_reuse_root=shared_root,
    ).run()

    second_optimizer = ReuseJudge(
        task,
        (0,),
        tmp_path / "second-optimizer",
        identity=optimizer_identity,
    )
    second_master = ReuseJudge(
        task,
        (0,),
        tmp_path / "second-master",
        identity=master_identity,
    )
    second_result = SubmissionRevisionController(
        second_config,
        RevisionDependencies(
            session=FakeSession(),
            judge=second_optimizer,
            master_judge=second_master,
        ),
        judgment_reuse_root=shared_root,
    ).run()

    assert first_result.scores == second_result.scores == (61, 71)
    assert first_result.fixed_original_scores == (80, 55)
    assert second_result.fixed_original_scores == (80, 55)
    assert first_optimizer.calls == 2
    assert first_master.calls == 1
    assert second_optimizer.calls == 0
    assert second_master.calls == 0
    assert not (second_config.experiment_dir / "evaluations").exists()
    assert len(list((shared_root / "judge" / "entries").iterdir())) == 3

    for config in (first_config, second_config):
        initial_aliases = list(
            (
                config.experiment_dir
                / "judgment-aliases"
                / "s000"
            ).glob("*.json")
        )
        assert len(initial_aliases) == 1
        assert json.loads(initial_aliases[0].read_text())["rubric_sha256"] == (
            sha256_file(optimizer_path)
        )
        later_aliases = list(
            (
                config.experiment_dir
                / "judgment-aliases"
                / "s001"
            ).glob("*.json")
        )
        assert {
            json.loads(path.read_text())["rubric_sha256"]
            for path in later_aliases
        } == {sha256_file(optimizer_path), sha256_file(master_path)}

    resumed_session = FakeSession()
    resumed_optimizer = ReuseJudge(
        task,
        (0,),
        tmp_path / "resumed-optimizer",
        identity=optimizer_identity,
    )
    resumed_master = ReuseJudge(
        task,
        (0,),
        tmp_path / "resumed-master",
        identity=master_identity,
    )
    resumed_result = SubmissionRevisionController(
        replace(second_config, resume=True),
        RevisionDependencies(
            session=resumed_session,
            judge=resumed_optimizer,
            master_judge=resumed_master,
        ),
        judgment_reuse_root=shared_root,
    ).run()
    assert resumed_result == second_result
    assert resumed_session.prompts == []
    assert resumed_optimizer.calls == 0
    assert resumed_master.calls == 0
    assert not (second_config.experiment_dir / "evaluations").exists()

    selection = SimpleNamespace(
        optimizer_path=optimizer_path,
        optimizer_sha256=sha256_file(optimizer_path),
        master_path=master_path,
        master_sha256=sha256_file(master_path),
    )
    monkeypatch.setattr(
        study_module,
        "resolve_paraphrase_selection",
        lambda *_args, **_kwargs: selection,
    )
    validate_completed_revision(
        second_config.experiment_dir,
        {
            "assignment_id": second_config.assignment_id,
            "task_id": task.name,
            "replicate": 1,
            "condition_id": second_config.condition_id,
            "execution_order": second_config.execution_order,
        },
        _design(second_config, task),
        second_config.seed_run_dir,
        tmp_path / "paraphrases",
        judgment_reuse_root=shared_root,
    )
    assert not (second_config.experiment_dir / "evaluations").exists()


def test_paperbench_bank_preflight_failure_dispatches_no_member_judges(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _write_task(tmp_path)
    workspace_identity = _identity(task)
    workspace_identity.update(
        {
            "benchmark": SubmissionBenchmarkId.PAPERBENCH_CODE_DEV.value,
            "grading_engine": "paperbench-structured",
            "review_mode": "workspace",
        }
    )
    config = replace(
        _config(
            tmp_path,
            task,
            rounds=0,
            seed_scoring_identity=workspace_identity,
        ),
        benchmark=SubmissionBenchmarkId.PAPERBENCH_CODE_DEV,
        review="workspace",
    )
    judge = FakeJudge(
        task,
        (0, 80),
        tmp_path / "judge",
        identity=workspace_identity,
    )
    controller = SubmissionRevisionController(
        config,
        RevisionDependencies(session=FakeSession(), judge=judge),
    )
    controller.reuse_seed_judgment = False
    monkeypatch.setattr(
        paperbench_module,
        "PAPERBENCH_MAX_REQUEST_CONTENT_BYTES_PER_CALL",
        1,
    )

    with pytest.raises(ValueError, match="per-call limit"):
        controller.run()

    assert judge.calls == 0
    manifest = json.loads(
        (config.experiment_dir / "manifest.json").read_text()
    )
    remove_live_tree(
        Path(manifest["live_workspace_dir"]).parent,
        config.experiment_dir,
    )


def test_study_validates_every_replacement_generation_record(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    base = _config(tmp_path, task, rounds=2)
    config = replace(
        base,
        condition_id="base-nonadaptive-replacement",
        assignment_id=f"{task.name}--rep-001--base-nonadaptive-replacement",
        rubric_policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
    )

    proposer = _singleton_replacement_proposer(config)
    controller = SubmissionRevisionController(
        config,
        RevisionDependencies(
            session=FakeSession(),
            judge=FakeJudge(task, (80, 90, 90, 90), tmp_path / "judge"),
            bank_proposer=proposer,
        ),
    )
    member_judges: dict[str, FakeJudge] = {}
    original_runtime = controller._bank_member_runtime

    def runtime(item: RubricBankItem, generation_round: int):
        rubric_hash = item.rubric.content_sha256
        if rubric_hash == controller.initial_rubric.sha256:
            return original_runtime(item, generation_round)
        if rubric_hash not in member_judges:
            identity = _identity(task)
            identity.update({
                "rubric_source": "rubric-path",
                "rendered_rubric_sha256": rubric_hash,
            })
            member_judges[rubric_hash] = FakeJudge(
                task,
                (0, 90, 90, 90),
                tmp_path / f"member-{len(member_judges)}",
                identity=identity,
            )
        return (
            controller._frozen_bank_member(item.rubric.content, rubric_hash),
            member_judges[rubric_hash],
        )

    controller._bank_member_runtime = runtime  # type: ignore[method-assign]
    controller.run()
    second_generation = json.loads(
        (
            config.experiment_dir
            / "rubric-generations/bank-0002/generation.json"
        ).read_text()
    )
    assert second_generation["semantic_review"]["cost"]["cost_source"] == (
        "exact-request-reuse"
    )
    assignment = {
        "assignment_id": config.assignment_id,
        "task_id": task.name,
        "replicate": 1,
        "condition_id": config.condition_id,
        "execution_order": 1,
    }
    design = _design(config, task)
    validate_completed_revision(
        config.experiment_dir,
        assignment,
        design,
        config.seed_run_dir,
        config.experiment_dir / "paraphrases",
    )

    extra_generation = config.experiment_dir / "rubric-generations" / "bank-9999"
    extra_generation.mkdir()
    with pytest.raises(RuntimeError, match="generation set is incomplete"):
        validate_completed_revision(
            config.experiment_dir,
            assignment,
            design,
            config.seed_run_dir,
            config.experiment_dir / "paraphrases",
        )
    extra_generation.rmdir()

    metadata_path = (
        config.experiment_dir
        / "rubric-generations"
        / "bank-0001"
        / "generation.json"
    )
    metadata_path.chmod(0o600)
    metadata = json.loads(metadata_path.read_text())
    metadata["member_generation"]["request"]["model"] = "tampered-proposer"
    metadata_path.write_text(json.dumps(metadata))
    with pytest.raises(RuntimeError, match="invalid complete-bank generation"):
        validate_completed_revision(
            config.experiment_dir,
            assignment,
            design,
            config.seed_run_dir,
            config.experiment_dir / "paraphrases",
        )


def test_controller_scores_singleton_bank_exactly(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    base = _config(tmp_path, task, rounds=1)
    config = replace(
        base,
        condition_id="base-nonadaptive-replacement",
        assignment_id=f"{task.name}--rep-001--base-nonadaptive-replacement",
        rubric_policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
    )

    base_judge = FakeJudge(task, (0, 65), tmp_path / "base-judge")
    controller = SubmissionRevisionController(
        config,
        RevisionDependencies(
            session=FakeSession(),
            judge=base_judge,
            bank_proposer=_singleton_replacement_proposer(config),
        ),
    )
    member_judges: dict[str, FakeJudge] = {}
    original_runtime = controller._bank_member_runtime

    def runtime(item: RubricBankItem, generation_round: int):
        rubric_hash = item.rubric.content_sha256
        if rubric_hash == controller.initial_rubric.sha256:
            return original_runtime(item, generation_round)
        if rubric_hash not in member_judges:
            identity = _identity(task)
            identity.update({
                "rubric_source": "rubric-path",
                "rendered_rubric_sha256": rubric_hash,
            })
            score = 60
            member_judges[rubric_hash] = FakeJudge(
                task,
                (0, score),
                tmp_path / f"member-{len(member_judges)}",
                identity=identity,
            )
        return (
            controller._frozen_bank_member(item.rubric.content, rubric_hash),
            member_judges[rubric_hash],
        )

    controller._bank_member_runtime = runtime  # type: ignore[method-assign]
    result = controller.run()

    assert result.scores == (80, 60)
    assert sorted(judge.calls for judge in member_judges.values()) == [1]
    evaluation = json.loads(
        (config.experiment_dir / "bank-evaluations" / "s001.json").read_text()
    )
    assert evaluation["weighted_score"] == 60
    assert sorted(
        (member["weight"], member["score"])
        for member in evaluation["members"].values()
    ) == [(1.0, 60)]
    validate_completed_revision(
        config.experiment_dir,
        {
            "assignment_id": config.assignment_id,
            "task_id": task.name,
            "replicate": 1,
            "condition_id": config.condition_id,
            "execution_order": 1,
        },
        _design(config, task),
        config.seed_run_dir,
        config.experiment_dir / "paraphrases",
    )


def test_simulated_user_feedback_is_llm_generated_partial_and_resumable(
    tmp_path: Path,
) -> None:
    task = _write_task(tmp_path)
    private_value = "expected-private-value-37-of-200"
    (task / "tests" / "rubric.txt").write_text(
        "Criterion 1: Correct result\n"
        "Description: Evaluate the reported result.\n"
        "Levels: A=100 B=50 C=0\n"
        "[A]: Correct and fully supported.\n"
        "[B]: Partly correct with a material limitation.\n"
        "[C]: Incorrect or unsupported.\n"
            f"Private reference: {private_value}.\n"
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
            namespaced_criterion = request.schema["properties"][  # type: ignore[index]
                "referenced_criteria"
            ]["items"]["enum"][0]
            assert namespaced_criterion.endswith(":criterion_1")
            text = json.dumps({
                "referenced_criteria": [namespaced_criterion],
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
    assert set(feedback) == {"policy", "comment", "bank_sha256"}
    generation = json.loads(
        (
            config.experiment_dir
            / "feedback-generations"
            / "s000.json"
        ).read_text()
    )
    assert generation["output"]["referenced_criteria"] == [
        f"{CompleteRubric.from_content((task / 'tests' / 'rubric.txt').read_text()).content_sha256}:criterion_1"
    ]
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
        config.experiment_dir / "paraphrases",
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
            criterion_ids = request.schema["properties"][  # type: ignore[index]
                "referenced_criteria"
            ]["items"]["enum"]
            selected = (
                list(criterion_ids)
                if selection_calls == 1
                else [criterion_ids[0], criterion_ids[2]]
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
    rubric_text = (
        "Scoring protocol: binary test contract\n"
        "Score normalization maximum: 100\n\n"
        "Criterion 1: Result\n"
        "Description: Evaluate the result.\n"
        "Levels: A=40 B=0\n[A]: Full.\n[B]: None.\n"
        "Criterion 2: Evidence\n"
        "Description: Evaluate the evidence.\n"
        "Levels: A=30 B=0\n[A]: Full.\n[B]: None.\n"
        "Criterion 3: Explanation\n"
        "Description: Evaluate the explanation.\n"
        "Levels: A=30 B=0\n[A]: Full.\n[B]: None.\n"
    )
    rubric = CompleteRubric.from_content(rubric_text)
    bank = RubricBank(
        generation_round=0,
        source_boundary=None,
        specification_anchor=rubric,
        specification_anchor_lineage=RubricLineage.NEW,
        prior_specification_anchor_sha256=None,
        items=(RubricBankItem(
            rubric=rubric,
            weight=1.0,
            lineage=RubricLineage.NEW,
            criterion_map=identity_criterion_map(rubric),
        ),),
    )
    record = simulator.generate(
        experiment_id="experiment",
        assignment_id="assignment",
        submission_id="s000",
        generation_round=0,
        instruction="Analyze the table.",
        bank=bank,
        current_submission="The result is positive.",
    )

    assert selection_calls == 2
    assert comment_calls == 1
    assert record["attempt_count"] == 2
    assert record["output"]["referenced_criteria"] == [  # type: ignore[index]
        f"{rubric.content_sha256}:criterion_1",
        f"{rubric.content_sha256}:criterion_3",
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
    scoring_identity = _identity(
        task,
        judge_model="judge-model",
        base_url="http://judge:8000/v1",
        experiment_dir=tmp_path / "experiment",
    )
    config = replace(
        _config(
            tmp_path,
            task,
            rounds=1,
            seed_scoring_identity=scoring_identity,
        ),
        judge_model="judge-model",
        judge_base_url="http://judge:8000/v1",
        rubric_proposer_model="proposer-model",
        rubric_proposer_base_url="http://proposer:8000/v1",
    )
    SubmissionRevisionController(
        config,
        RevisionDependencies(
            session=FakeSession(),
            judge=FakeJudge(
                task,
                (80, 90),
                tmp_path / "judge",
                identity=scoring_identity,
            ),
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
        config.experiment_dir / "paraphrases",
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


def test_resume_persists_one_sealed_proposal_ahead_before_dispatch(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _write_task(tmp_path)
    base = _config(tmp_path, task, rounds=1)
    config = replace(
        base,
        condition_id="base-nonadaptive-replacement",
        assignment_id=f"{task.name}--rep-001--base-nonadaptive-replacement",
        rubric_policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
    )
    original_persist = controller_module.persist_rubric_bank

    class SimulatedCrash(RuntimeError):
        pass

    def crash_before_replacement_bank(*args, **kwargs):
        generation = args[1]
        if generation.bank.generation_round == 1:
            raise SimulatedCrash("crash after proposal sealing")
        return original_persist(*args, **kwargs)

    monkeypatch.setattr(
        controller_module,
        "persist_rubric_bank",
        crash_before_replacement_bank,
    )
    with pytest.raises(SimulatedCrash, match="after proposal sealing"):
        SubmissionRevisionController(
            config,
            RevisionDependencies(
                session=FakeSession(),
                judge=FakeJudge(task, (80,), tmp_path / "initial-judge"),
                bank_proposer=_singleton_replacement_proposer(config),
            ),
        ).run()

    proposal = config.experiment_dir / "rubric-generations" / "bank-0001"
    replacement = config.experiment_dir / "rubric-banks" / "bank-0001"
    assert proposal.is_dir()
    assert not replacement.exists()
    proposal_root = proposal.parent
    ledger_temp = (
        proposal_root
        / ".bank-0001.provider-attempts.json.abcdefgh.tmp"
    )
    rejection_temp = (
        proposal_root
        / ".bank-0001.semantic-rejection.json.abcdefgh.tmp"
    )
    stage = proposal_root / ".bank-0001.abcdefgh"
    ledger_temp.write_text("partial ledger\n", encoding="utf-8")
    rejection_temp.write_text("partial rejection\n", encoding="utf-8")
    stage.mkdir()
    (stage / "partial.json").write_text("{}\n", encoding="utf-8")

    monkeypatch.setattr(
        controller_module,
        "persist_rubric_bank",
        original_persist,
    )
    provider_calls = 0

    def reject_provider_call(**_kwargs) -> BankProposerOutput:
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("resume called the rubric proposer provider")

    resumed_session = FakeSession()
    resumed = SubmissionRevisionController(
        replace(config, resume=True),
        RevisionDependencies(
            session=resumed_session,
            judge=FakeJudge(task, (80,), tmp_path / "resume-judge"),
            bank_proposer=_singleton_replacement_proposer(
                config,
                run_proposer=reject_provider_call,
            ),
        ),
    )
    monkeypatch.setattr(
        controller_module,
        "RubricBankProposer",
        lambda **_kwargs: pytest.fail(
            "resume constructed a proposer instead of replaying on its dependency"
        ),
    )

    class StopAfterReplay(RuntimeError):
        pass

    def stop_before_solver(_state, _workspace) -> None:
        assert replacement.is_dir()
        raise StopAfterReplay("proposal replay completed")

    resumed._run_solver_turn = stop_before_solver  # type: ignore[method-assign]
    with pytest.raises(StopAfterReplay, match="replay completed"):
        resumed.run()

    assert replacement.is_dir()
    assert not ledger_temp.exists()
    assert not rejection_temp.exists()
    assert not stage.exists()
    assert provider_calls == 0
    assert resumed_session.prompts == []
    assert resumed.dependencies.bank_proposer is not None
    assert resumed.dependencies.bank_proposer._validated_semantic_outputs


@pytest.mark.parametrize("kind", ["symlink", "fifo"])
def test_resume_rejects_owned_generation_residue_with_the_wrong_file_type(
    tmp_path: Path,
    kind: str,
) -> None:
    root = tmp_path / "rubric-generations"
    root.mkdir()
    residue = root / ".bank-0001.provider-attempts.json.abcdefgh.tmp"
    if kind == "symlink":
        target = tmp_path / "target"
        target.write_text("do not remove\n", encoding="utf-8")
        residue.symlink_to(target)
    else:
        os.mkfifo(residue)

    with pytest.raises(RuntimeError, match="not a regular file"):
        controller_module._remove_owned_rubric_generation_residue(
            root,
            max_generation_round=1,
        )

    assert os.path.lexists(residue)


def test_resume_rejects_replacement_bank_without_sealed_proposal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = _write_task(tmp_path)
    base = _config(tmp_path, task, rounds=1)
    config = replace(
        base,
        condition_id="base-nonadaptive-replacement",
        assignment_id=f"{task.name}--rep-001--base-nonadaptive-replacement",
        rubric_policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
    )
    original_persist = controller_module.persist_rubric_bank

    class SimulatedCrash(RuntimeError):
        pass

    def persist_bank_then_hide_proposal(*args, **kwargs):
        result = original_persist(*args, **kwargs)
        generation = args[1]
        if generation.bank.generation_round == 1:
            proposal = (
                config.experiment_dir / "rubric-generations" / "bank-0001"
            )
            parent_mode = stat.S_IMODE(proposal.parent.stat().st_mode)
            proposal.parent.chmod(0o700)
            for artifact in proposal.iterdir():
                artifact.chmod(0o600)
            proposal.chmod(0o700)
            shutil.rmtree(proposal)
            proposal.parent.chmod(parent_mode)
            raise SimulatedCrash("crash after bank persistence")
        return result

    monkeypatch.setattr(
        controller_module,
        "persist_rubric_bank",
        persist_bank_then_hide_proposal,
    )
    with pytest.raises(SimulatedCrash, match="after bank persistence"):
        SubmissionRevisionController(
            config,
            RevisionDependencies(
                session=FakeSession(),
                judge=FakeJudge(task, (80,), tmp_path / "initial-judge"),
                bank_proposer=_singleton_replacement_proposer(config),
            ),
        ).run()

    assert (
        config.experiment_dir / "rubric-banks" / "bank-0001"
    ).is_dir()
    assert not (
        config.experiment_dir / "rubric-generations" / "bank-0001"
    ).exists()
    monkeypatch.setattr(
        controller_module,
        "persist_rubric_bank",
        original_persist,
    )

    provider_calls = 0

    def reject_provider_call(**_kwargs) -> BankProposerOutput:
        nonlocal provider_calls
        provider_calls += 1
        raise AssertionError("resume called the rubric proposer provider")

    resumed_session = FakeSession()
    resumed_judge = FakeJudge(task, (80,), tmp_path / "resume-judge")
    with pytest.raises(RuntimeError, match="no matching sealed proposal"):
        SubmissionRevisionController(
            replace(config, resume=True),
            RevisionDependencies(
                session=resumed_session,
                judge=resumed_judge,
                bank_proposer=_singleton_replacement_proposer(
                    config,
                    run_proposer=reject_provider_call,
                ),
            ),
        ).run()

    assert provider_calls == 0
    assert resumed_judge.calls == 0
    assert resumed_session.prompts == []


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
            config.experiment_dir / "paraphrases",
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
    complete_rubric = CompleteRubric.from_content(rubric)
    bank = RubricBank(
        generation_round=0,
        source_boundary=None,
        specification_anchor=complete_rubric,
        specification_anchor_lineage=RubricLineage.NEW,
        prior_specification_anchor_sha256=None,
        items=(RubricBankItem(
            rubric=complete_rubric,
            weight=1.0,
            lineage=RubricLineage.NEW,
            criterion_map=identity_criterion_map(complete_rubric),
        ),),
    )
    artifacts = {rubric_sha: (validation, evaluation)}
    full = project_bank_feedback(
        bank, artifacts, FeedbackPolicy.FULL
    )
    semi = project_bank_feedback(
        bank, artifacts, FeedbackPolicy.SEMI
    )
    score = project_bank_feedback(
        bank, artifacts, FeedbackPolicy.SCORE_ONLY
    )
    simulated = project_bank_simulated_user_feedback(
        bank,
        {rubric_sha: validation},
        "The evidence is hard to verify from the response. Please explain the "
        "key check and connect it to the conclusion.",
    )
    assert "needs more evidence" in full.prompt
    assert '"title": "Evidence"' in semi.prompt
    assert "needs more evidence" not in semi.prompt
    assert "Criterion 2" not in score.prompt
    assert set(simulated.payload) == {"policy", "comment", "bank_sha256"}
    assert "The evidence is hard to verify" in simulated.prompt
    assert "80/100" not in simulated.prompt
    assert "needs more evidence" not in simulated.prompt
    assert '"selected_level"' not in simulated.prompt
    assert all(
        "under ./artifacts, not ./data" in item.prompt
        for item in (full, semi, score, simulated)
    )
    assert score.score == 80


def test_bank_feedback_uses_the_singleton_member_score(
    tmp_path: Path,
) -> None:
    anchor = CompleteRubric.from_content(
        "Criterion 1: Accuracy\nDescription: Evaluate accuracy.\n"
        "Levels: A=100 B=33 C=0\n"
        "[A]: Full.\n[B]: Partial.\n[C]: None.\n"
    )
    presentation = parse_rubric_member_presentation({
        "title": "Result presentation",
        "overview": "Inspect the complete result.",
        "criteria": [{
            "anchor_criterion_id": "criterion_1",
            "heading": "Result accuracy",
            "lens": "Inspect concrete result evidence.",
        }],
    })
    rubric, criterion_map = render_locked_rubric_member(anchor, presentation)
    bank = RubricBank(
        generation_round=2,
        source_boundary=None,
        specification_anchor=anchor,
        specification_anchor_lineage=RubricLineage.RETAINED,
        prior_specification_anchor_sha256=anchor.content_sha256,
        items=(
            RubricBankItem(
                rubric,
                1.0,
                RubricLineage.NEW,
                criterion_map,
                presentation=presentation,
            ),
        ),
    )
    artifacts: dict[str, tuple[Path, Path]] = {}
    evaluation = tmp_path / "evaluation.json"
    validation = tmp_path / "validation.json"
    evaluation.write_text(json.dumps({
        "criteria": {"criterion_1": {"level": "B", "reason": "checked"}},
        "reasoning": "checked",
    }))
    validation.write_text(json.dumps({
        "score": 33,
        "normalized_score": 0.33,
        "raw_score": 33,
        "selected_levels": {"criterion_1": "B"},
        "criterion_scores": {"criterion_1": 33},
        "rendered_rubric_sha256": rubric.content_sha256,
        "evaluation_sha256": sha256_file(evaluation),
    }))
    artifacts[rubric.content_sha256] = (validation, evaluation)

    projected = project_bank_feedback(bank, artifacts, FeedbackPolicy.SEMI)

    assert projected.score == 33
    assert projected.payload["score"] == 33
    assert "33/100" not in projected.prompt
    assert set(projected.payload["members"]) == {rubric.content_sha256}
