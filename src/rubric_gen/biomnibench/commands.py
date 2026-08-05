"""Command handlers for the BiomniBench CLI."""

from __future__ import annotations

import argparse
from pathlib import Path

from rubric_gen.biomnibench.agent.costs import RunCost
from rubric_gen.biomnibench.agent.models import AgentRunConfig, BatchRunConfig
from rubric_gen.biomnibench.agent.runners import AgentRunner, BiomniBenchBatchRunner
from rubric_gen.biomnibench.analysis import analyze_study
from rubric_gen.biomnibench.blinding import export_blinded_review
from rubric_gen.biomnibench.cross_scoring import CrossScoreConfig, CrossScoreRunner
from rubric_gen.biomnibench.cost_report import study_cost_report
from rubric_gen.biomnibench.experiments import (
    DesignConfig,
    create_design,
    load_design,
    verify_runtime_provenance,
)
from rubric_gen.biomnibench.judging.models import JudgeRunConfig
from rubric_gen.biomnibench.judging.runner import BiomniBenchJudgeRunner
from rubric_gen.biomnibench.perturbation.models import PerturbationRunConfig
from rubric_gen.biomnibench.perturbation.runner import BiomniBenchPerturbationRunner
from rubric_gen.biomnibench.revision.evolution import RubricEvolution
from rubric_gen.biomnibench.revision.feedback import FeedbackPolicy
from rubric_gen.biomnibench.revision.seeds import SeedSetConfig, SeedSetRunner
from rubric_gen.biomnibench.rubrics.compiler import (
    TaskProcessRubricCompiler,
    TaskRubricCompilerConfig,
)
from rubric_gen.biomnibench.rubrics.retrospective import (
    ProcessRubricConfig,
    ProcessRubricGenerator,
)
from rubric_gen.biomnibench.study import StudyRunConfig, StudyRunner, inspect_study
from rubric_gen.biomnibench.utils.paths import resolve_project_path
from rubric_gen.biomnibench.visualization.comparisons import (
    JudgeComparisonConfig,
    JudgeComparisonPlotter,
)
from rubric_gen.biomnibench.agent.prompts import PromptProfile


def run_one(args: argparse.Namespace) -> int:
    task_dir = resolve_project_path(args.task)
    runs_dir = resolve_project_path(args.runs_dir)
    exit_code, paths = AgentRunner(config=AgentRunConfig.from_namespace(args)).run(
        task_dir,
        runs_dir,
    )
    cost = RunCost.from_stream(paths.stream_path)
    print(f"Provider: {paths.provider}")
    print(f"Exit code: {exit_code}")
    print(f"cost_usd: {cost.cost_usd}")
    print(f"estimated_cost_usd: {cost.estimated_cost_usd}")
    print(f"cost_source: {cost.source}")
    print(f"trace.md: {paths.workspace_dir / 'trace.md'}")
    print(f"answer.txt: {paths.workspace_dir / 'answer.txt'}")
    print(f"raw trajectory: {paths.stream_path}")
    return exit_code


def run_generate(args: argparse.Namespace) -> int:
    from rubric_gen.biomnibench.rubrics.generator import (
        RubricGenerationConfig,
        RubricGenerationRunner,
    )

    return RubricGenerationRunner(
        RubricGenerationConfig.from_namespace(args)
    ).run()


def run_design(args: argparse.Namespace) -> int:
    design = create_design(DesignConfig(
        tasks_dir=resolve_project_path(args.tasks_dir),
        output_path=resolve_project_path(args.output),
        protocol_id=args.protocol_id,
        dataset_revision=args.dataset_revision,
        random_seed=args.random_seed,
        sample_size=args.sample_size,
        replicates=args.replicates,
        revision_rounds=args.revision_rounds,
        feedback_policy=FeedbackPolicy(args.feedback_policy),
        treatment_prompt=PromptProfile(args.treatment_prompt),
        agent=AgentRunConfig.from_namespace(args),
        judge_model=args.judge_model,
        judge_max_retries=args.judge_max_retries,
        minimum_detectable_effect=args.minimum_detectable_effect,
        anticipated_discordance=args.anticipated_discordance,
        stage=args.stage,
        validated_design_path=(
            resolve_project_path(args.validated_design)
            if args.validated_design is not None
            else None
        ),
        rubric_name=args.rubric,
        review=args.review,
        max_review_chars=args.max_review_chars,
        rubric_proposer_model=args.rubric_proposer_model,
        rubric_proposer_step_limit=args.rubric_proposer_step_limit,
        rubric_proposer_max_retries=args.rubric_proposer_max_retries,
        primary_rh_rule=args.primary_rh_rule,
        alpha=args.alpha,
        target_power=args.target_power,
        audit_max_input_tokens=args.audit_max_input_tokens,
        audit_max_output_tokens=args.audit_max_output_tokens,
        audit_max_event_text_chars=args.audit_max_event_text_chars,
        audit_max_command_output_chars=args.audit_max_command_output_chars,
        audit_max_retries=args.audit_max_retries,
        audit_max_cost_usd=args.audit_max_cost_usd,
    ))
    print(f"design_sha256: {design.sha256}")
    print(f"assignments: {len(design.assignments)}")
    cost_plan = design.payload["cost_plan"]
    assert isinstance(cost_plan, dict)
    print(
        "nominal_stage_invocations: "
        f"{cost_plan['nominal_total_stage_invocations']}"
    )
    print(f"design: {design.path}")
    return 0


def run_seed(args: argparse.Namespace) -> int:
    design = load_design(resolve_project_path(args.design))
    verify_runtime_provenance(design)
    return SeedSetRunner(SeedSetConfig(
        design=design,
        output_dir=resolve_project_path(args.output_dir),
        max_concurrency=args.max_concurrency,
        resume=args.resume,
    )).run()


def run_study(args: argparse.Namespace) -> int:
    design = load_design(resolve_project_path(args.design))
    return StudyRunner(StudyRunConfig(
        design=design,
        seed_run_dir=resolve_project_path(args.seed_run_dir),
        output_dir=resolve_project_path(args.output_dir),
        max_concurrency=args.max_concurrency,
        resume=args.resume,
        dry_run=args.dry_run,
    )).run()


def run_status(args: argparse.Namespace) -> int:
    design = load_design(resolve_project_path(args.design))
    health = inspect_study(resolve_project_path(args.run_dir), design)
    print(f"total: {health.total}")
    print(f"completed: {health.completed}")
    print(f"pending: {health.pending}")
    print(f"running: {health.running}")
    print(f"failed: {health.failed}")
    print(f"invalid: {health.invalid}")
    print(f"healthy: {str(health.healthy).lower()}")
    print(f"complete: {str(health.complete).lower()}")
    return 0 if health.complete else 1


def run_cost(args: argparse.Namespace) -> int:
    design = load_design(resolve_project_path(args.design))
    result = study_cost_report(
        design,
        seed_run_dir=(
            resolve_project_path(args.seed_run_dir)
            if args.seed_run_dir is not None else None
        ),
        study_dir=(
            resolve_project_path(args.run_dir)
            if args.run_dir is not None else None
        ),
        audit_summary=(
            resolve_project_path(args.audit_summary)
            if args.audit_summary is not None else None
        ),
        output_path=(
            resolve_project_path(args.output)
            if args.output is not None else None
        ),
    )
    stages = result["stages"]
    assert isinstance(stages, dict)
    for name, stage in stages.items():
        assert isinstance(stage, dict)
        print(
            f"{name}: ${float(stage['observed_cost_usd']):.2f} "
            f"({stage['observed_stage_invocations']}/"
            f"{stage['planned_stage_invocations']} stages observed; "
            f"{stage['fully_priced_stage_invocations']} fully, "
            f"{stage['partially_priced_stage_invocations']} partially, "
            f"{stage['unpriced_stage_invocations']} unpriced)"
        )
    print(f"observed_total: ${float(result['observed_cost_usd']):.2f}")
    if args.output is not None:
        print(f"report: {resolve_project_path(args.output)}")
    return 0


def run_analyze(args: argparse.Namespace) -> int:
    design = load_design(resolve_project_path(args.design))
    result = analyze_study(
        design,
        resolve_project_path(args.run_dir),
        resolve_project_path(args.audit_summary),
        resolve_project_path(args.output),
    )
    print(f"observed: {result['observed_count']}/{result['assignment_count']}")
    print(f"analysis: {resolve_project_path(args.output)}")
    return 0


def run_cross_score(args: argparse.Namespace) -> int:
    design = load_design(resolve_project_path(args.design))
    return CrossScoreRunner(CrossScoreConfig(
        design=design,
        study_dir=resolve_project_path(args.run_dir),
        max_concurrency=args.max_concurrency,
        resume=args.resume,
    )).run()


def run_blind_export(args: argparse.Namespace) -> int:
    design = load_design(resolve_project_path(args.design))
    count = export_blinded_review(
        design,
        resolve_project_path(args.run_dir),
        resolve_project_path(args.output_dir),
        resolve_project_path(args.key_output),
    )
    print(f"blinded cases: {count}")
    print(f"review packet: {resolve_project_path(args.output_dir)}")
    print(f"private key: {resolve_project_path(args.key_output)}")
    return 0


def run_rubric_free(args: argparse.Namespace) -> int:
    from rubric_gen.biomnibench.revision.rubric_free import (
        RubricFreeConfig,
        RubricFreeRunner,
    )

    return RubricFreeRunner(RubricFreeConfig(
        experiment_dirs=tuple(resolve_project_path(path) for path in args.run_dir),
        output_dir=resolve_project_path(args.output_dir),
        models=tuple(args.models),
        max_concurrency=args.max_concurrency,
        max_retries=args.max_retries,
        resume=args.resume,
    )).run()


def run_all(args: argparse.Namespace) -> int:
    return BiomniBenchBatchRunner(BatchRunConfig.from_namespace(args)).run()


def run_judge(args: argparse.Namespace) -> int:
    config = JudgeRunConfig.from_namespace(args)
    return BiomniBenchJudgeRunner(config).run()


def run_compare_judges(args: argparse.Namespace) -> int:
    return JudgeComparisonPlotter(JudgeComparisonConfig.from_namespace(args)).run()


def run_perturb(args: argparse.Namespace) -> int:
    return BiomniBenchPerturbationRunner(
        PerturbationRunConfig.from_namespace(args)
    ).run()


def run_process_rubrics(args: argparse.Namespace) -> int:
    return ProcessRubricGenerator(ProcessRubricConfig.from_namespace(args)).run()


def run_task_process_rubrics(args: argparse.Namespace) -> int:
    return TaskProcessRubricCompiler(TaskRubricCompilerConfig.from_namespace(args)).run()
