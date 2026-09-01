from __future__ import annotations

import copy
import json
import os
import stat
from pathlib import Path

import pytest

import rubric_gen.submission_revision.seeds as seeds_module
from rubric_gen.cli import build_parser
from rubric_gen.runtime.agents.models import AgentRunConfig
from rubric_gen.submission_revision.experiment import Experiment
from rubric_gen.submission_revision.assignments import ExperimentAssignment
from rubric_gen.submission_revision.judge import JudgeArtifacts
from rubric_gen.submission_revision.seeds import (
    SeedSetConfig,
    SeedSetRunner,
    resolve_seed,
)


EXPERIMENT_ID = "test-experiment"
SEED_AGENT = AgentRunConfig(
    provider="codex",
    model="test-model",
    reasoning_effort="low",
    retries=1,
    timeout_seconds=60,
)


def _task(root: Path) -> Path:
    task = root / "tasks" / "da-1-1"
    (task / "environment" / "data").mkdir(parents=True)
    (task / "tests").mkdir()
    (task / "instruction.md").write_text("Solve it.\n")
    (task / "environment" / "data" / "x.csv").write_text("x\n1\n")
    (task / "tests" / "rubric.txt").write_text(
        "Criterion 1: Result\nLevels: A=100 B=50 C=0\n"
    )
    return task


def _design(root: Path, task: Path) -> Experiment:
    conditions = [
        {
            "condition_id": f"{feedback_slug}-{rubric_slug}",
            "feedback_policy": feedback_policy,
            "rubric_policy": rubric_policy,
        }
        for feedback_slug, feedback_policy in (
            ("full", "full"),
            ("semi", "semi"),
            ("score-only", "score_only"),
            ("user-simulator", "user_simulator"),
        )
        for rubric_slug, rubric_policy in (
            ("static", "fixed"),
            ("offline-rubric", "offline_elicitation"),
            ("online-rubric", "online_elicitation"),
        )
    ]
    assignments = []
    execution = 0
    for replicate in range(1, 4):
        for within, condition in enumerate(conditions, 1):
            execution += 1
            condition_id = condition["condition_id"]
            assignments.append(ExperimentAssignment(
                task_id=task.name,
                replicate=replicate,
                solver_id="test-solver",
                condition_id=condition_id,
                within_block_order=within,
                execution_order=execution,
            ))
    payload = {
        "experiment_id": EXPERIMENT_ID,
        "benchmark": "biomnibench-da",
        "tasks_dir": str(task.parent.resolve()),
        "tasks": [task.name],
        "randomization": {"seed": 42, "replicates": 3},
        "seed_generator": {
            "provider": "codex",
            "model": "test-model",
            "reasoning_effort": "low",
            "service_tier": None,
            "executable": None,
            "retries": 1,
            "timeout_seconds": 60,
        },
        "solvers": [{
            "solver_id": "test-solver",
            "provider": "codex",
            "model": "test-model",
            "reasoning_effort": "low",
            "service_tier": None,
            "executable": None,
            "retries": 1,
            "timeout_seconds": 60,
        }],
        "conditions": conditions,
        "assignments": assignments,
        "protocol": {
            "max_revisions": 1,
            "min_revisions": 1,
            "prompt": "base",
            "feedback_simulator": {
                "model": "test-simulator",
                "max_output_tokens": 1_024,
                "max_concerns": 2,
                "max_history_bytes": 131_072,
                "max_request_bytes": 1_048_576,
                "max_retries": 1,
            },
            "judge_model": "test-judge",
            "rubric_name": "rubric.txt",
            "review": "trace",
            "max_review_chars": None,
            "rubric_proposer_model": "test-proposer",
            "rubric_proposer_max_retries": 1,
        },
        "rubric_paraphrases": {
            "count": 3,
            "selected_variant": 0,
            "model": "test-paraphraser",
            "max_retries": 1,
        },
        "outcome_audit": {},
        "dag": {},
    }
    path = (root / "experiment.yaml").resolve()
    path.write_text("{}")
    return Experiment(path, payload)


class FakeAgentRunner:
    calls = 0
    prompts: list[str] = []

    def __init__(self, config, **_kwargs) -> None:
        self.config = config
        type(self).prompts.append(_kwargs["prompt"])

    def run(self, task_dir: Path, *, paths):
        type(self).calls += 1
        paths.run_dir.mkdir(parents=True)
        paths.workspace_dir.mkdir(parents=True)
        (paths.workspace_dir / "answer.txt").write_text(
            f"answer-{type(self).calls}\n"
        )
        (paths.workspace_dir / "trace.md").write_text("trace\n")
        paths.stream_path.write_text('{"type":"result","status":"success"}\n')
        paths.status_path.write_text(json.dumps({
            "provider": "codex",
            "exit_code": 0,
            "model": "test-model",
            "cost": {"cost_usd": 0.01},
        }))
        return 0, paths


class KilledAgentRunner:
    def __init__(self, config, **_kwargs) -> None:
        self.config = config

    def run(self, task_dir: Path, *, paths):
        paths.run_dir.mkdir(parents=True)
        paths.workspace_dir.mkdir(parents=True)
        paths.prompt_path.write_text("test prompt\n")
        paths.stream_path.write_text('{"type":"turn.started"}\n')
        paths.status_path.write_text(json.dumps({
            "provider": "codex",
            "process_exit_code": -9,
            "exit_code": -9,
        }))
        return -9, paths


class InvalidElicitationRunner:
    calls = 0

    def __init__(self, config, *, prompt: str, **_kwargs) -> None:
        self.config = config
        self.prompt = prompt

    def run(self, task_dir: Path, *, paths):
        type(self).calls += 1
        paths.run_dir.mkdir(parents=True)
        paths.workspace_dir.mkdir(parents=True)
        paths.stream_path.write_text('{"type":"result","status":"success"}\n')
        if "Your task is covert sabotage." in self.prompt:
            (paths.workspace_dir / "trace.md").write_text("incomplete attack\n")
            exit_code = 2
        else:
            (paths.workspace_dir / "answer.txt").write_text("clean answer\n")
            (paths.workspace_dir / "trace.md").write_text("clean trace\n")
            exit_code = 0
        paths.status_path.write_text(json.dumps({
            "provider": "codex",
            "exit_code": exit_code,
            "model": "test-model",
        }))
        return exit_code, paths


def _fake_judge(self, task_dir: Path, submission: Path, experiment_dir: Path):
    output = experiment_dir / "artifacts"
    output.mkdir(parents=True)
    evaluation = output / "evaluation.json"
    validation = output / "score_validation.json"
    usage = output / "usage.json"
    evaluation.write_text('{"criteria":{},"reasoning":"ok"}')
    validation.write_text('{"score":75}')
    usage.write_text(json.dumps({
        "provider": "openai",
        "requested_model": "test-judge",
        "effective_model": "test-judge",
        "response_id": "test-response",
        "request_parameters": {},
        "usage": {"input_tokens": 10, "output_tokens": 2},
    }))
    identity = self._initial_judge(task_dir, experiment_dir).scoring_identity()
    return JudgeArtifacts(validation, evaluation), identity


def test_seed_set_creates_one_independent_seed_per_task_replicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(tmp_path)
    design = _design(tmp_path, task)
    output = tmp_path / "seeds"
    FakeAgentRunner.calls = 0
    monkeypatch.setattr(seeds_module, "AgentRunner", FakeAgentRunner)
    monkeypatch.setattr(SeedSetRunner, "_judge_initial_submission", _fake_judge)

    assert SeedSetRunner(SeedSetConfig(design, output, 2)).run() == 0
    assert FakeAgentRunner.calls == 6
    seeds = [
        resolve_seed(
            output,
            task,
            replicate,
            seed_generator=SEED_AGENT,
            prompt_profile="base",
            benchmark="biomnibench-da",
        )
        for replicate in range(1, 4)
    ]
    assert len({seed.sha256 for seed in seeds}) == 3
    assert all(seed.manifest["replicate"] == index for index, seed in enumerate(seeds, 1))
    root = json.loads((output / "manifest.json").read_text())
    assert root == {
        "kind": seeds_module.SEED_SET_KIND,
    }


def test_seed_solver_uses_the_configured_adversarial_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(tmp_path)
    design = _design(tmp_path, task)
    payload = copy.deepcopy(design.payload)
    payload["protocol"]["prompt"] = "adversarial"
    payload["assignments"] = [
        assignment
        for assignment in design.assignments
        if assignment.replicate == 1
    ]
    experiment = Experiment(tmp_path / "adversarial.yaml", payload)
    output = tmp_path / "seeds"
    FakeAgentRunner.calls = 0
    FakeAgentRunner.prompts = []
    monkeypatch.setattr(seeds_module, "AgentRunner", FakeAgentRunner)
    monkeypatch.setattr(SeedSetRunner, "_judge_initial_submission", _fake_judge)

    assert SeedSetRunner(SeedSetConfig(experiment, output, 1)).run() == 0
    assert len(FakeAgentRunner.prompts) == 6
    assert sum(
        "Your task is covert sabotage." in prompt
        for prompt in FakeAgentRunner.prompts
    ) == 3
    assert sum(
        "Your task is covert sabotage." not in prompt
        for prompt in FakeAgentRunner.prompts
    ) == 3


def test_seed_pool_rejects_a_different_solver_prompt(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(tmp_path)
    design = _design(tmp_path, task)
    payload = copy.deepcopy(design.payload)
    payload["assignments"] = [
        assignment
        for assignment in design.assignments
        if assignment.replicate == 1
    ]
    base = Experiment(tmp_path / "base.yaml", payload)
    output = tmp_path / "seeds"
    monkeypatch.setattr(seeds_module, "AgentRunner", FakeAgentRunner)
    monkeypatch.setattr(SeedSetRunner, "_judge_initial_submission", _fake_judge)
    assert SeedSetRunner(SeedSetConfig(base, output, 1)).run() == 0

    adversarial_payload = copy.deepcopy(payload)
    adversarial_payload["protocol"]["prompt"] = "adversarial"
    adversarial = Experiment(tmp_path / "adversarial.yaml", adversarial_payload)
    with pytest.raises(RuntimeError, match="seed solver prompt does not match"):
        SeedSetRunner(SeedSetConfig(adversarial, output, 1)).run()


def test_invalid_elicitation_attempt_is_saved_but_not_included(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(tmp_path)
    design = _design(tmp_path, task)
    output = tmp_path / "seeds"
    InvalidElicitationRunner.calls = 0
    monkeypatch.setattr(seeds_module, "AgentRunner", InvalidElicitationRunner)
    monkeypatch.setattr(SeedSetRunner, "_judge_initial_submission", _fake_judge)

    assert SeedSetRunner(SeedSetConfig(design, output, 1)).run() == 0
    assert InvalidElicitationRunner.calls == 6
    for replicate in range(1, 4):
        seed = resolve_seed(
            output,
            task,
            replicate,
            seed_generator=SEED_AGENT,
            prompt_profile="base",
            benchmark="biomnibench-da",
        )
        attempt = seed.manifest["elicitation_attempt"]
        assert isinstance(attempt, dict)
        assert attempt["included"] is False
        assert attempt["exit_code"] == 2
        assert len(seed.elicitation_artifacts) == 1
        attempt_root = seed.seed_root / "elicitation_attempt"
        assert (attempt_root / "workspace" / "trace.md").is_file()
        assert (attempt_root / "run" / "status.json").is_file()


def test_seed_stage_generates_every_configured_replicate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(tmp_path)
    design = _design(tmp_path, task)
    payload = copy.deepcopy(design.payload)
    payload["randomization"]["replicates"] = 4
    experiment = Experiment(tmp_path / "four-replicates.yaml", payload)
    output = tmp_path / "seeds"
    FakeAgentRunner.calls = 0
    monkeypatch.setattr(seeds_module, "AgentRunner", FakeAgentRunner)
    monkeypatch.setattr(SeedSetRunner, "_judge_initial_submission", _fake_judge)

    assert SeedSetRunner(SeedSetConfig(experiment, output, 1)).run() == 0
    assert FakeAgentRunner.calls == 8
    assert (output / "tasks" / task.name / "rep-004" / "manifest.json").is_file()


def test_seed_stage_holds_an_exclusive_pool_lease(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(tmp_path)
    design = _design(tmp_path, task)
    output = tmp_path / "seeds"
    observed_operations: list[int] = []
    real_flock = seeds_module.fcntl.flock

    def record_flock(descriptor: int, operation: int) -> None:
        observed_operations.append(operation)
        real_flock(descriptor, operation)

    monkeypatch.setattr(seeds_module.fcntl, "flock", record_flock)
    monkeypatch.setattr(seeds_module, "AgentRunner", FakeAgentRunner)
    monkeypatch.setattr(SeedSetRunner, "_judge_initial_submission", _fake_judge)

    assert SeedSetRunner(SeedSetConfig(design, output, 2)).run() == 0
    assert observed_operations == [
        seeds_module.fcntl.LOCK_EX,
        seeds_module.fcntl.LOCK_UN,
    ]
    assert (output / ".seed.lock").is_file()


def test_seed_pool_generation_does_not_depend_on_assignment_selection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(tmp_path)
    design = _design(tmp_path, task)
    first_payload = copy.deepcopy(design.payload)
    first_payload["assignments"] = [
        assignment
        for assignment in design.assignments
        if assignment.replicate == 1
    ]
    first = Experiment(tmp_path / "first.yaml", first_payload)
    output = tmp_path / "seeds"
    FakeAgentRunner.calls = 0
    monkeypatch.setattr(seeds_module, "AgentRunner", FakeAgentRunner)
    monkeypatch.setattr(SeedSetRunner, "_judge_initial_submission", _fake_judge)
    SeedSetRunner(SeedSetConfig(first, output, 1)).run()
    assert FakeAgentRunner.calls == 6

    second_payload = copy.deepcopy(design.payload)
    second_payload["experiment_id"] = "second-experiment"
    second = Experiment(tmp_path / "second.yaml", second_payload)
    assert SeedSetRunner(SeedSetConfig(second, output, 3)).run() == 0
    assert FakeAgentRunner.calls == 6
    owners = {
        replicate: resolve_seed(
            output,
            task,
            replicate,
            seed_generator=SEED_AGENT,
            prompt_profile="base",
            benchmark="biomnibench-da",
        ).manifest["experiment_id"]
        for replicate in range(1, 4)
    }
    assert owners == {
        1: EXPERIMENT_ID,
        2: EXPERIMENT_ID,
        3: EXPERIMENT_ID,
    }

    answer = output / "tasks" / task.name / "rep-002" / "submission" / "workspace" / "answer.txt"
    answer.chmod(stat.S_IRUSR | stat.S_IWUSR)
    answer.write_text("tampered\n")
    with pytest.raises(RuntimeError, match="integrity check failed"):
        resolve_seed(
            output,
            task,
            2,
            seed_generator=SEED_AGENT,
            prompt_profile="base",
            benchmark="biomnibench-da",
        )


def test_seed_failure_preserves_diagnostics_until_retry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    task = _task(tmp_path)
    design = _design(tmp_path, task)
    payload = copy.deepcopy(design.payload)
    payload["assignments"] = [
        assignment
        for assignment in design.assignments
        if assignment.replicate == 1
    ]
    experiment = Experiment(tmp_path / "one-replicate.yaml", payload)
    output = tmp_path / "seeds"
    monkeypatch.setattr(seeds_module, "AgentRunner", KilledAgentRunner)

    assert SeedSetRunner(SeedSetConfig(experiment, output, 1)).run() == 1

    diagnostics = output / "tasks" / task.name / "rep-001" / "failed_solver"
    failure = json.loads((diagnostics / "failure.json").read_text())
    assert failure["exit_code"] == -9
    assert failure["signal"] == "SIGKILL"
    assert failure["copied_files"] == [
        "prompt.txt",
        "trajectory.stream.jsonl",
        "status.json",
    ]
    error = capsys.readouterr().err
    assert "code -9 (SIGKILL)" in error
    assert f"diagnostics: {diagnostics}" in error
    assert (diagnostics / "trajectory.stream.jsonl").is_file()

    FakeAgentRunner.calls = 0
    monkeypatch.setattr(seeds_module, "AgentRunner", FakeAgentRunner)
    monkeypatch.setattr(SeedSetRunner, "_judge_initial_submission", _fake_judge)
    assert SeedSetRunner(SeedSetConfig(experiment, output, 1)).run() == 0
    assert not diagnostics.exists()
    resolve_seed(
        output,
        task,
        1,
        seed_generator=SEED_AGENT,
        prompt_profile="base",
        benchmark="biomnibench-da",
    )


def test_shared_pool_reuses_complete_blocks_without_an_overwrite_flag(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(tmp_path)
    design = _design(tmp_path, task)
    output = tmp_path / "seeds"
    monkeypatch.setattr(seeds_module, "AgentRunner", FakeAgentRunner)
    monkeypatch.setattr(SeedSetRunner, "_judge_initial_submission", _fake_judge)
    FakeAgentRunner.calls = 0
    SeedSetRunner(SeedSetConfig(design, output, 1)).run()
    assert FakeAgentRunner.calls == 6
    assert SeedSetRunner(SeedSetConfig(design, output, 1)).run() == 0
    assert FakeAgentRunner.calls == 6
    seed = resolve_seed(
        output,
        task,
        1,
        seed_generator=SEED_AGENT,
        prompt_profile="base",
        benchmark="biomnibench-da",
    )

    assert seed.manifest["experiment_id"] == EXPERIMENT_ID


def test_seed_rejects_obsolete_labels_and_additional_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(tmp_path)
    design = _design(tmp_path, task)
    output = tmp_path / "seeds"
    monkeypatch.setattr(seeds_module, "AgentRunner", FakeAgentRunner)
    monkeypatch.setattr(SeedSetRunner, "_judge_initial_submission", _fake_judge)
    SeedSetRunner(SeedSetConfig(design, output, 1)).run()

    root_manifest_path = output / "manifest.json"
    root_manifest = json.loads(root_manifest_path.read_text())
    root_manifest.update({
        "kind": "rubric-gen-biomnibench-randomized-seed-set",
        "legacy_note": "preserved provenance",
    })
    root_manifest_path.write_text(json.dumps(root_manifest))

    block_manifest_path = (
        output / "tasks" / task.name / "rep-001" / "manifest.json"
    )
    block_manifest_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    block_manifest = json.loads(block_manifest_path.read_text())
    block_manifest.update({
        "kind": "rubric-gen-biomnibench-randomized-seed",
        "legacy_note": "preserved provenance",
    })
    block_manifest_path.write_text(json.dumps(block_manifest))

    with pytest.raises(RuntimeError, match="invalid seed"):
        resolve_seed(
            output,
            task,
            1,
            seed_generator=SEED_AGENT,
            prompt_profile="base",
            benchmark="biomnibench-da",
        )
    with pytest.raises(RuntimeError, match="shared seed manifest"):
        SeedSetRunner(SeedSetConfig(design, output, 1)).run()


def test_seed_rejects_provenance_metadata_tampering(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(tmp_path)
    design = _design(tmp_path, task)
    output = tmp_path / "seeds"
    monkeypatch.setattr(seeds_module, "AgentRunner", FakeAgentRunner)
    monkeypatch.setattr(SeedSetRunner, "_judge_initial_submission", _fake_judge)
    SeedSetRunner(SeedSetConfig(design, output, 1)).run()
    manifest_path = output / "tasks" / task.name / "rep-001" / "manifest.json"
    manifest_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    manifest = json.loads(manifest_path.read_text())
    manifest["seed_generator"]["model"] = "forged-model"
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(RuntimeError, match="invalid seed"):
        resolve_seed(
            output,
            task,
            1,
            seed_generator=SEED_AGENT,
            prompt_profile="base",
            benchmark="biomnibench-da",
        )


def test_seed_rejects_incomplete_scoring_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(tmp_path)
    design = _design(tmp_path, task)
    output = tmp_path / "seeds"
    monkeypatch.setattr(seeds_module, "AgentRunner", FakeAgentRunner)
    monkeypatch.setattr(SeedSetRunner, "_judge_initial_submission", _fake_judge)
    SeedSetRunner(SeedSetConfig(design, output, 1)).run()
    manifest_path = output / "tasks" / task.name / "rep-001" / "manifest.json"
    manifest_path.chmod(stat.S_IRUSR | stat.S_IWUSR)
    manifest = json.loads(manifest_path.read_text())
    del manifest["scoring_identity"]["grading_engine"]
    manifest_path.write_text(json.dumps(manifest))

    with pytest.raises(RuntimeError, match="seed integrity check failed"):
        resolve_seed(
            output,
            task,
            1,
            seed_generator=SEED_AGENT,
            prompt_profile="base",
            benchmark="biomnibench-da",
        )


def test_seed_stage_rejects_a_completed_stale_judge_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = _task(tmp_path)
    design = _design(tmp_path, task)
    output = tmp_path / "seeds"
    monkeypatch.setattr(seeds_module, "AgentRunner", FakeAgentRunner)

    def stale_judge(
        self,
        task_dir: Path,
        submission: Path,
        experiment_dir: Path,
    ):
        artifacts, identity = _fake_judge(
            self,
            task_dir,
            submission,
            experiment_dir,
        )
        identity["scoring_implementation_sha256"] = "f" * 64
        return artifacts, identity

    monkeypatch.setattr(SeedSetRunner, "_judge_initial_submission", stale_judge)
    runner = SeedSetRunner(SeedSetConfig(design, output, 1))
    assert runner.run() == 0

    with pytest.raises(RuntimeError, match="does not match the current judge"):
        runner.run()


def test_seed_cli_is_experiment_only() -> None:
    args = build_parser().parse_args([
        "seed", "--experiment", "experiment.yaml"
    ])
    assert args.experiment == "experiment.yaml"
    with pytest.raises(SystemExit):
        build_parser().parse_args([
            "seed", "--tasks-dir", "tasks", "--output-dir", "seeds"
        ])
    with pytest.raises(SystemExit):
        build_parser().parse_args([
            "seed", "--experiment", "experiment.yaml", "--resume"
        ])
