"""Build and validate the identity of a completed revision study."""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from numbers import Real
from pathlib import Path

from rubric_gen.runtime.agents.models import AgentRunConfig
from rubric_gen.submission_revision.artifacts import (
    read_json_object,
    revision_manifest_keys,
    sha256_file,
    tree_sha256,
)
from rubric_gen.submission_revision.evolution import (
    rubric_generation_implementation_sha256,
)
from rubric_gen.submission_revision.experiment import Experiment
from rubric_gen.submission_revision.feedback import FeedbackPolicy
from rubric_gen.submission_revision.judge import (
    FrozenRubric,
    FrozenRubricJudge,
    SubmissionJudgeConfig,
    resolve_optimizer_rubric,
)
from rubric_gen.submission_revision import paraphrase_validation
from rubric_gen.submission_revision.paraphrase_validation import ParaphraseSelection
from rubric_gen.submission_revision.rubric_generation import (
    RubricGeneration,
    RubricPolicy,
)
from rubric_gen.submission_revision.rubric_generation_store import (
    load_rubric_generation,
)
from rubric_gen.submission_revision.seeds import (
    ResolvedSeed,
    resolve_seed,
    seed_generator_identity,
)
from rubric_gen.submission_revision.store import (
    extract_judge_execution_contract,
    extract_seed_scoring_contract,
)
from rubric_gen.submission_revision.user_simulator import SimulatedUserFeedback
from rubric_gen.submission_revision.assignments import ExperimentAssignment


@dataclass(frozen=True)
class ScoringSetup:
    initial_generation: RubricGeneration
    judge_config: SubmissionJudgeConfig
    initial_rubric: FrozenRubric
    initial_judge: FrozenRubricJudge
    initial_contract: dict[str, object]
    master_judge: FrozenRubricJudge
    master_contract: dict[str, object]


@dataclass(frozen=True)
class ValidationContext:
    experiment_dir: Path
    assignment: ExperimentAssignment
    experiment: Experiment
    protocol: dict[str, object]
    condition: dict[str, object]
    policy: FeedbackPolicy
    rubric_policy: RubricPolicy
    simulator: SimulatedUserFeedback | None
    agent: AgentRunConfig
    seed_agent: AgentRunConfig
    task_dir: Path
    pretreatment_rubric_dir: Path
    selection: ParaphraseSelection
    seed: ResolvedSeed
    seed_contract: dict[str, object]
    manifest: dict[str, object]
    state: dict[str, object]
    max_revisions: int
    min_revisions: int
    expected_ids: tuple[str, ...]
    scoring: ScoringSetup


def build_validation_context(
    experiment_dir: Path,
    assignment: ExperimentAssignment,
    experiment: Experiment,
    seed_run_dir: Path,
    paraphrase_run_dir: Path,
) -> ValidationContext:
    if experiment_dir.is_symlink() or not experiment_dir.is_dir():
        raise RuntimeError(f"revision is not a regular directory: {experiment_dir}")
    manifest = read_json_object(experiment_dir / "manifest.json", "revision manifest")
    state = read_json_object(experiment_dir / "state.json", "revision state")
    protocol = experiment.protocol
    condition = experiment.condition(assignment.condition_id)
    policy = FeedbackPolicy(str(condition["feedback_policy"]))
    simulator_config = experiment.feedback_simulator_config(policy)
    simulator = (
        SimulatedUserFeedback(simulator_config)
        if simulator_config is not None
        else None
    )
    agent = experiment.solver_config(assignment.solver_id)
    seed_agent = experiment.seed_agent_config()
    task_dir = experiment.task_dir(assignment.task_id).resolve()
    pretreatment_value = manifest.get("pretreatment_rubric_dir")
    if type(pretreatment_value) is not str or not pretreatment_value:
        raise RuntimeError("revision manifest has no pre-treatment rubric path")
    pretreatment_rubric_dir = Path(pretreatment_value)
    paraphrase_validation.validate_paraphrase_run(paraphrase_run_dir, experiment)
    selection = paraphrase_validation.resolve_paraphrase_selection(
        paraphrase_run_dir,
        experiment,
        assignment.task_id,
    )
    seed = resolve_seed(
        seed_run_dir,
        task_dir,
        assignment.replicate,
        seed_generator=seed_agent,
        prompt_profile=str(protocol["prompt"]),
        benchmark=experiment.benchmark,
    )
    seed_identity = seed.manifest.get("scoring_identity")
    if not isinstance(seed_identity, dict):
        raise RuntimeError("revision seed has invalid scoring identity")
    manifest_identity = manifest.get("initial_scoring_identity")
    if not isinstance(manifest_identity, dict):
        raise RuntimeError("revision manifest has invalid scoring identity")
    seed_contract = extract_seed_scoring_contract(
        seed_identity,
        context="revision seed",
    )
    manifest_contract = extract_seed_scoring_contract(
        manifest_identity,
        context="revision manifest",
    )
    if extract_judge_execution_contract(
        seed_contract,
        context="revision seed",
    ) != extract_judge_execution_contract(
        manifest_contract,
        context="revision manifest",
    ):
        raise RuntimeError("revision seed and judge use different execution contracts")
    max_revisions = int(protocol["max_revisions"])
    min_revisions = int(protocol["min_revisions"])
    submission_count = manifest.get("submission_count")
    if (
        type(submission_count) is not int
        or not 1 <= submission_count <= max_revisions + 1
    ):
        raise RuntimeError("revision manifest has an invalid submission count")
    expected_ids = tuple(f"s{index:03d}" for index in range(submission_count))
    rubric_policy = RubricPolicy(str(condition["rubric_policy"]))
    scoring = _build_scoring_setup(
        experiment_dir,
        experiment,
        protocol,
        task_dir,
        selection,
        rubric_policy,
    )
    if (
        scoring.initial_rubric.sha256 != selection.optimizer_sha256
        or scoring.master_judge.rubric.sha256 != selection.master_sha256
        or manifest_identity != scoring.initial_judge.scoring_identity()
        or manifest_contract != scoring.initial_contract
    ):
        raise RuntimeError(
            "resolved study rubric identities differ from the sealed manifest"
        )
    return ValidationContext(
        experiment_dir=experiment_dir,
        assignment=assignment,
        experiment=experiment,
        protocol=protocol,
        condition=condition,
        policy=policy,
        rubric_policy=rubric_policy,
        simulator=simulator,
        agent=agent,
        seed_agent=seed_agent,
        task_dir=task_dir,
        pretreatment_rubric_dir=pretreatment_rubric_dir,
        selection=selection,
        seed=seed,
        seed_contract=seed_contract,
        manifest=manifest,
        state=state,
        max_revisions=max_revisions,
        min_revisions=min_revisions,
        expected_ids=expected_ids,
        scoring=scoring,
    )


def _build_scoring_setup(
    experiment_dir: Path,
    experiment: Experiment,
    protocol: dict[str, object],
    task_dir: Path,
    selection: ParaphraseSelection,
    rubric_policy: RubricPolicy,
) -> ScoringSetup:
    initial_generation = load_rubric_generation(
        experiment_dir,
        0,
        expected_policy=rubric_policy,
    )
    if (
        initial_generation.rubric.content_sha256 != selection.optimizer_sha256
    ):
        raise RuntimeError("initial rubric differs from randomized selection")
    max_review_chars = protocol["max_review_chars"]
    if max_review_chars is not None and type(max_review_chars) is not int:
        raise RuntimeError("experiment max_review_chars is invalid")
    judge_config = SubmissionJudgeConfig(
        task_dir=task_dir,
        experiment_dir=experiment_dir,
        benchmark=experiment.benchmark,
        review=str(protocol["review"]),
        judge_model=str(protocol["judge_model"]),
        rubric_name=None,
        rubric_set=None,
        rubric_path=selection.optimizer_path,
        max_review_chars=max_review_chars,
    )
    initial_rubric = resolve_optimizer_rubric(judge_config)
    initial_judge = FrozenRubricJudge(judge_config, initial_rubric)
    initial_contract = extract_seed_scoring_contract(
        initial_judge.scoring_identity(),
        context="resolved initial rubric",
    )
    master_config = replace(
        judge_config,
        rubric_name=str(protocol["rubric_name"]),
        rubric_path=None,
    )
    master_rubric = resolve_optimizer_rubric(master_config)
    master_judge = FrozenRubricJudge(master_config, master_rubric)
    master_contract = extract_seed_scoring_contract(
        master_judge.scoring_identity(),
        context="resolved master rubric",
    )
    return ScoringSetup(
        initial_generation=initial_generation,
        judge_config=judge_config,
        initial_rubric=initial_rubric,
        initial_judge=initial_judge,
        initial_contract=initial_contract,
        master_judge=master_judge,
        master_contract=master_contract,
    )


def validate_manifest(context: ValidationContext) -> None:
    expected = _expected_manifest(context)
    manifest = context.manifest
    if (
        set(manifest) != revision_manifest_keys(context.policy.value)
        or any(manifest.get(key) != value for key, value in expected.items())
        or type(manifest.get("live_workspace_dir")) is not str
        or type(manifest.get("session_id")) is not str
        or not manifest["session_id"]
        or type(manifest.get("effective_solver_model")) is not str
        or not manifest["effective_solver_model"]
    ):
        raise RuntimeError(f"revision is not complete: {context.experiment_dir}")


def _expected_manifest(context: ValidationContext) -> dict[str, object]:
    protocol = context.protocol
    agent = context.agent
    scoring = context.scoring
    expected: dict[str, object] = {
        "kind": "rubric-gen-submission-revision-experiment",
        "experiment_id": context.experiment.experiment_id,
        "benchmark": str(context.experiment.benchmark),
        "assignment_id": context.assignment.assignment_id,
        "condition_id": context.assignment.condition_id,
        "solver_id": context.assignment.solver_id,
        "task_id": context.assignment.task_id,
        "task_dir": str(context.task_dir),
        "replicate": context.assignment.replicate,
        "elicitation_seed_replicates": context.experiment.replicates,
        "execution_order": context.assignment.execution_order,
        "max_revisions": context.max_revisions,
        "min_revisions": context.min_revisions,
        "provider": agent.provider,
        "model": agent.model,
        "executable": agent.executable,
        "isolation": "codex-custom-permission-profile",
        "command_network_access": False,
        "web_search": False,
        "reasoning_effort": agent.reasoning_effort,
        "service_tier": agent.service_tier,
        "turn_timeout_seconds": agent.timeout_seconds,
        "feedback_policy": context.condition["feedback_policy"],
        "prompt": protocol["prompt"],
        "rubric_policy": context.condition["rubric_policy"],
        "rubric_proposer_model": protocol["rubric_proposer_model"],
        "rubric_proposer_max_retries": protocol["rubric_proposer_max_retries"],
        "rubric_generation_implementation_sha256": (
            rubric_generation_implementation_sha256()
        ),
        "review": protocol["review"],
        "judge_model": protocol["judge_model"],
        "max_review_chars": protocol["max_review_chars"],
        "initial_rubric_path": str(context.selection.optimizer_path.resolve()),
        "initial_generation_sha256": (
            scoring.initial_generation.generation_sha256
        ),
        "initial_rubric_sha256": (
            scoring.initial_generation.rubric.content_sha256
        ),
        "initial_scoring_identity": scoring.initial_judge.scoring_identity(),
        "master_rubric_name": protocol["rubric_name"],
        "master_rubric_sha256": context.selection.master_sha256,
        "instruction_sha256": sha256_file(context.task_dir / "instruction.md"),
        "data_sha256": tree_sha256(context.task_dir / "environment" / "data"),
        "seed_run_dir": str(context.seed.root),
        "pretreatment_rubric_dir": str(
            context.pretreatment_rubric_dir.resolve()
        ),
        "seed_generator": seed_generator_identity(context.seed_agent),
        "seed_sha256": context.seed.sha256,
        "submission_count": len(context.expected_ids),
        "live_workspace_removed": True,
    }
    if context.simulator is not None:
        expected["feedback_simulator"] = context.simulator.identity()
    return expected


def validate_state(context: ValidationContext) -> None:
    state = context.state
    expected_ids = context.expected_ids
    valid = (
        set(state)
        == {
            "phase",
            "next_turn_index",
            "session_id",
            "effective_solver_model",
            "submission_ids",
            "scores",
            "fixed_original_scores",
            "judge_attempts",
            "next_prompt",
            "stop_reason",
        }
        and state.get("phase") == "completed"
        and state.get("submission_ids") == list(expected_ids)
        and state.get("next_turn_index") == len(expected_ids)
        and state.get("stop_reason") in {"no_change", "max_revisions"}
        and (
            state.get("stop_reason") != "no_change"
            or len(expected_ids) >= context.min_revisions
        )
        and (
            state.get("stop_reason") != "max_revisions"
            or len(expected_ids) == context.max_revisions + 1
        )
        and state.get("next_prompt") == ""
        and state.get("session_id") == context.manifest.get("session_id")
        and state.get("effective_solver_model")
        == context.manifest.get("effective_solver_model")
        and _valid_score_series(state.get("scores"), len(expected_ids))
        and _valid_score_series(
            state.get("fixed_original_scores"),
            len(expected_ids),
        )
        and _valid_attempts(state.get("judge_attempts"), expected_ids)
    )
    if not valid:
        raise RuntimeError(f"revision is not complete: {context.experiment_dir}")


def _valid_score_series(value: object, count: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == count
        and all(valid_score(score) for score in value)
    )


def valid_score(value: object) -> bool:
    return (
        not isinstance(value, bool)
        and isinstance(value, Real)
        and math.isfinite(float(value))
        and 0 <= float(value) <= 100
    )


def _valid_attempts(value: object, expected_ids: tuple[str, ...]) -> bool:
    return (
        isinstance(value, dict)
        and set(value) == set(expected_ids)
        and all(_valid_attempt(attempt) for attempt in value.values())
    )


def _valid_attempt(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 32
        and all(character in "0123456789abcdef" for character in value)
    )
