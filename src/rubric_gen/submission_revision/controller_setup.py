"""Build and validate dependencies for one submission revision."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rubric_gen.benchmarks import SubmissionBenchmark, get_submission_benchmark
from rubric_gen.runtime.agents.codex_sessions import CodexSdkSessionDriver
from rubric_gen.runtime.agents.sessions import CliSolverSessionDriver, SolverSessionDriver
from rubric_gen.submission_revision.artifacts import sha256_file, tree_sha256
from rubric_gen.submission_revision.evolution import RubricProposer
from rubric_gen.submission_revision.feedback import FeedbackPolicy
from rubric_gen.submission_revision.judge import (
    SCORING_IDENTITY_KEYS,
    FrozenRubric,
    FrozenRubricJudge,
    SubmissionJudge,
    resolve_optimizer_rubric,
)
from rubric_gen.submission_revision.judgment_reuse import (
    ExactJudgmentReuseStore,
)
from rubric_gen.submission_revision.models import (
    RevisionDependencies,
    SubmissionRevisionConfig,
)
from rubric_gen.submission_revision.red_team import RedTeamGenerator
from rubric_gen.submission_revision.rubric_generation import (
    CompleteRubric,
    RubricGeneration,
    RubricPolicy,
)
from rubric_gen.submission_revision.seeds import (
    ResolvedSeed,
    resolve_seed,
    seed_generator_identity,
)
from rubric_gen.submission_revision.store import (
    RevisionStore,
    extract_judge_execution_contract,
    extract_scoring_identity,
    extract_seed_scoring_contract,
)
from rubric_gen.submission_revision.user_simulator import SimulatedUserFeedback


@dataclass(frozen=True)
class RevisionSetup:
    benchmark: SubmissionBenchmark
    experiment_dir: Path
    task_dir: Path
    judgment_reuse: ExactJudgmentReuseStore | None
    initial_rubric: FrozenRubric
    development_rubric: CompleteRubric
    rubric_policy: RubricPolicy
    initial_generation: RubricGeneration
    master_rubric: FrozenRubric
    instruction_sha256: str
    data_sha256: str
    seed: ResolvedSeed
    dependencies: RevisionDependencies
    master_judge: SubmissionJudge
    scoring_identity: dict[str, object]
    master_scoring_identity: dict[str, object]
    reuse_seed_judgment: bool
    reuse_seed_master_judgment: bool
    store: RevisionStore


def _initial_generation(initial_rubric: FrozenRubric) -> RubricGeneration:
    rubric = CompleteRubric.from_content(initial_rubric.text)
    return RubricGeneration(
        generation_round=0,
        source_checkpoint=None,
        rubric=rubric,
        elicited_criteria=(),
        proposer_call_budget=0,
    )


def _default_dependencies(
    config: SubmissionRevisionConfig,
    benchmark: SubmissionBenchmark,
    initial_rubric: FrozenRubric,
    master_rubric: FrozenRubric,
    rubric_policy: RubricPolicy,
) -> RevisionDependencies:
    proposer = None
    if rubric_policy is not RubricPolicy.FIXED:
        proposer = RubricProposer(
            benchmark=config.benchmark,
            model=config.rubric_proposer_model,
            service_tier=config.seed_agent.service_tier,
            max_retries=config.rubric_proposer_max_retries,
        )
    session: SolverSessionDriver
    if config.agent.provider == "codex":
        session = CodexSdkSessionDriver(config.agent, contract=benchmark)
    else:
        session = CliSolverSessionDriver(config.agent, contract=benchmark)
    return RevisionDependencies(
        session=session,
        judge=FrozenRubricJudge(config.judge_config(), initial_rubric),
        master_judge=FrozenRubricJudge(
            config.master_judge_config(),
            master_rubric,
        ),
        rubric_proposer=proposer,
        feedback_simulator=(
            SimulatedUserFeedback(config.feedback_simulator)
            if config.feedback_simulator is not None
            else None
        ),
        red_team_generator=(
            RedTeamGenerator(
                agent=config.red_team_agent,
                benchmark=benchmark,
            )
            if rubric_policy.uses_red_team
            else None
        ),
    )


def _validate_proposer(
    config: SubmissionRevisionConfig,
    dependencies: RevisionDependencies,
    rubric_policy: RubricPolicy,
) -> None:
    proposer = dependencies.rubric_proposer
    if rubric_policy is RubricPolicy.FIXED:
        return
    if proposer is None:
        raise ValueError("an elicitation policy requires a rubric proposer")
    expected_service_tier = config.seed_agent.service_tier
    actual = (
        proposer.benchmark,
        proposer.proposer_contract.model,
        proposer.max_retries,
        proposer.proposer_contract.service_tier,
    )
    expected = (
        config.benchmark,
        config.rubric_proposer_model,
        config.rubric_proposer_max_retries,
        expected_service_tier,
    )
    if actual != expected:
        raise ValueError("rubric proposer contract differs from revision config")


def _validate_feedback_simulator(
    config: SubmissionRevisionConfig,
    dependencies: RevisionDependencies,
) -> None:
    simulator = dependencies.feedback_simulator
    uses_simulator = (
        FeedbackPolicy(config.feedback_policy) is FeedbackPolicy.USER_SIMULATOR
    )
    if uses_simulator and simulator is None:
        raise ValueError("user_simulator feedback requires a feedback simulator")
    if not uses_simulator and simulator is not None:
        raise ValueError(
            "feedback simulator dependency is only valid for user_simulator"
        )
    if simulator is None:
        return
    if config.feedback_simulator is None:
        raise AssertionError("simulator policy has no simulator configuration")
    if simulator.identity() != config.feedback_simulator.identity():
        raise ValueError("feedback simulator identity differs from revision config")


def _validate_red_team_generator(
    config: SubmissionRevisionConfig,
    dependencies: RevisionDependencies,
    rubric_policy: RubricPolicy,
) -> None:
    generator = dependencies.red_team_generator
    if rubric_policy.uses_red_team:
        if generator is None:
            raise ValueError(
                "red-team rubric policy requires a red-team generator"
            )
        if generator.identity() != seed_generator_identity(config.red_team_agent):
            raise ValueError(
                "red-team generator identity differs from revision config"
            )
        return
    if generator is not None:
        raise ValueError(
            "red-team generator dependency is valid only for red-team policies"
        )


def _judge_identity(
    judge: SubmissionJudge,
    rubric: FrozenRubric,
    context: str,
) -> dict[str, object]:
    reported = judge.scoring_identity()
    if set(reported) != set(SCORING_IDENTITY_KEYS):
        raise RuntimeError(f"{context} returned an incomplete scoring identity")
    identity = extract_scoring_identity(reported, context=context)
    if identity["rendered_rubric_sha256"] != rubric.sha256:
        raise RuntimeError(f"{context} resolved a different rubric")
    return identity


def _seed_reuse(
    seed: ResolvedSeed,
    scoring_identity: dict[str, object],
    master_scoring_identity: dict[str, object],
) -> tuple[bool, bool]:
    _, _, seed_identity = seed.judgment
    seed_contract = extract_seed_scoring_contract(
        seed_identity,
        context="seeded initial judgment",
    )
    optimizer_contract = extract_seed_scoring_contract(
        scoring_identity,
        context="submission judge",
    )
    master_contract = extract_seed_scoring_contract(
        master_scoring_identity,
        context="master rubric judge",
    )
    seed_execution = extract_judge_execution_contract(
        seed_contract,
        context="seeded initial judgment",
    )
    if (
        seed_execution
        != extract_judge_execution_contract(
            optimizer_contract,
            context="optimizer judge",
        )
        or seed_execution
        != extract_judge_execution_contract(
            master_contract,
            context="master judge",
        )
    ):
        raise RuntimeError(
            "seeded initial judgment uses a different scoring contract for "
            "judge execution"
        )
    return seed_contract == optimizer_contract, seed_contract == master_contract


def build_revision_setup(
    config: SubmissionRevisionConfig,
    dependencies: RevisionDependencies | None,
    judgment_reuse_root: Path | None,
) -> RevisionSetup:
    benchmark = get_submission_benchmark(config.benchmark)
    experiment_dir = Path(config.experiment_dir).resolve()
    task_dir = Path(config.task_dir).resolve()
    judgment_reuse = (
        ExactJudgmentReuseStore(judgment_reuse_root / "judge")
        if judgment_reuse_root is not None
        else None
    )
    initial_rubric = resolve_optimizer_rubric(config.judge_config())
    initial_generation = _initial_generation(initial_rubric)
    development_rubric = CompleteRubric.from_content(
        config.development_rubric_path.read_text(encoding="utf-8")
    )
    rubric_policy = RubricPolicy(config.rubric_policy)
    master_rubric = resolve_optimizer_rubric(config.master_judge_config())
    seed = resolve_seed(
        config.seed_run_dir,
        task_dir,
        config.replicate,
        seed_generator=config.seed_agent,
        prompt_profile=config.prompt_profile,
        benchmark=config.benchmark,
    )
    resolved_dependencies = dependencies or _default_dependencies(
        config,
        benchmark,
        initial_rubric,
        master_rubric,
        rubric_policy,
    )
    _validate_proposer(config, resolved_dependencies, rubric_policy)
    _validate_feedback_simulator(config, resolved_dependencies)
    _validate_red_team_generator(config, resolved_dependencies, rubric_policy)
    master_judge = resolved_dependencies.master_judge or resolved_dependencies.judge
    scoring_identity = _judge_identity(
        resolved_dependencies.judge,
        initial_rubric,
        "submission judge",
    )
    master_scoring_identity = _judge_identity(
        master_judge,
        master_rubric,
        "master rubric judge",
    )
    reuse_seed_judgment, reuse_seed_master_judgment = _seed_reuse(
        seed,
        scoring_identity,
        master_scoring_identity,
    )
    store = RevisionStore(
        experiment_dir,
        initial_generation=initial_generation,
        rubric_policy=rubric_policy,
        scoring_identity=scoring_identity,
    )
    return RevisionSetup(
        benchmark=benchmark,
        experiment_dir=experiment_dir,
        task_dir=task_dir,
        judgment_reuse=judgment_reuse,
        initial_rubric=initial_rubric,
        development_rubric=development_rubric,
        rubric_policy=rubric_policy,
        initial_generation=initial_generation,
        master_rubric=master_rubric,
        instruction_sha256=sha256_file(task_dir / "instruction.md"),
        data_sha256=tree_sha256(task_dir / "environment" / "data"),
        seed=seed,
        dependencies=resolved_dependencies,
        master_judge=master_judge,
        scoring_identity=scoring_identity,
        master_scoring_identity=master_scoring_identity,
        reuse_seed_judgment=reuse_seed_judgment,
        reuse_seed_master_judgment=reuse_seed_master_judgment,
        store=store,
    )
