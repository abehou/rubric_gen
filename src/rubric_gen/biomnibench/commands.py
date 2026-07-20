"""Command handlers for the BiomniBench CLI."""

from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from rubric_gen.biomnibench.agent.costs import RunCost
from rubric_gen.biomnibench.agent.models import AgentRunConfig, BatchRunConfig
from rubric_gen.biomnibench.agent.runners import AgentRunner, BiomniBenchBatchRunner
from rubric_gen.biomnibench.agent.workspaces import TaskCatalog
from rubric_gen.biomnibench.judging.models import JudgeRunConfig
from rubric_gen.biomnibench.judging.runner import BiomniBenchJudgeRunner
from rubric_gen.biomnibench.perturbation.models import PerturbationRunConfig
from rubric_gen.biomnibench.perturbation.runner import BiomniBenchPerturbationRunner
from rubric_gen.biomnibench.revision import (
    FeedbackPolicy,
    SubmissionRevisionConfig,
    run_submission_revision,
)
from rubric_gen.biomnibench.rubrics.compiler import (
    TaskProcessRubricCompiler,
    TaskRubricCompilerConfig,
)
from rubric_gen.biomnibench.rubrics.retrospective import (
    ProcessRubricConfig,
    ProcessRubricGenerator,
)
from rubric_gen.biomnibench.utils.paths import resolve_project_path
from rubric_gen.biomnibench.utils.progress import TerminalProgress
from rubric_gen.biomnibench.visualization.comparisons import (
    JudgeComparisonConfig,
    JudgeComparisonPlotter,
)


def run_one(args: argparse.Namespace) -> int:
    task_dir = resolve_project_path(args.task)
    runs_dir = resolve_project_path(args.runs_dir)
    exit_code, paths = AgentRunner(config=AgentRunConfig.from_namespace(args)).run(
        task_dir,
        runs_dir,
    )
    print("\nFinished.")
    print(f"Provider: {paths.provider}")
    print(f"Exit code: {exit_code}")
    cost = RunCost.from_stream(paths.stream_path)
    print(f"cost_usd: {cost.cost_usd}")
    print(f"estimated_cost_usd: {cost.estimated_cost_usd}")
    print(f"cost_source: {cost.source}")
    print(f"trace.md: {paths.workspace_dir / 'trace.md'}")
    print(f"answer.txt: {paths.workspace_dir / 'answer.txt'}")
    print(f"raw trajectory: {paths.stream_path}")
    return exit_code


def run_all(args: argparse.Namespace) -> int:
    return BiomniBenchBatchRunner(BatchRunConfig.from_namespace(args)).run()


def _timestamped_revision_experiment_dir() -> Path:
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return resolve_project_path(f"runs/biomnibench-revisions/revision-{stamp}")


def run_revise(args: argparse.Namespace) -> int:
    if args.experiment_dir is None:
        if args.resume:
            raise ValueError("--resume requires --experiment-dir")
        if args.restart:
            raise ValueError("--restart requires --experiment-dir")
        args.experiment_dir = str(_timestamped_revision_experiment_dir())
    if not args.all and not args.full_v_score:
        config = SubmissionRevisionConfig.from_namespace(args)
        if args.dry_run:
            print("Selected 1 task(s) and 1 experiment(s).")
            print(
                f"{config.task_dir.name}\t{config.feedback_policy.value}\t"
                f"{config.experiment_dir}"
            )
            return 0
        run_submission_revision(config)
        return 0
    if args.max_concurrency < 1:
        raise ValueError("max_concurrency must be at least 1")
    task_dirs = (
        TaskCatalog(resolve_project_path(args.tasks_dir)).tasks()
        if args.all
        else [resolve_project_path(args.task)]
    )
    policies = (
        (FeedbackPolicy.FULL, FeedbackPolicy.SCORE_ONLY)
        if args.full_v_score
        else (FeedbackPolicy(args.feedback_policy),)
    )
    configs = [
        replace(
            SubmissionRevisionConfig.from_namespace(
                argparse.Namespace(
                    **{
                        **vars(args),
                        "task": str(task_dir),
                        "feedback_policy": policy.value,
                    }
                )
            ),
            show_progress=False,
        )
        for task_dir in task_dirs
        for policy in policies
    ]
    if args.dry_run:
        print(f"Selected {len(task_dirs)} task(s) and {len(configs)} experiment(s).")
        for config in configs:
            print(
                f"{config.task_dir.name}\t{config.feedback_policy.value}\t"
                f"{config.experiment_dir}"
            )
        return 0
    failures: list[tuple[SubmissionRevisionConfig, Exception]] = []
    with TerminalProgress(
        total=len(configs),
        description="revise batch",
        unit="experiment",
    ) as progress:
        if args.max_concurrency == 1:
            for config in configs:
                try:
                    run_submission_revision(config)
                except Exception as exc:
                    failures.append((config, exc))
                finally:
                    progress.update()
        else:
            with ThreadPoolExecutor(max_workers=args.max_concurrency) as executor:
                futures = {
                    executor.submit(run_submission_revision, config): config
                    for config in configs
                }
                for future in as_completed(futures):
                    try:
                        future.result()
                    except Exception as exc:
                        failures.append((futures[future], exc))
                    finally:
                        progress.update()
    if failures:
        config, exc = failures[0]
        raise RuntimeError(
            f"{len(failures)} revision experiments failed; first: "
            f"{config.task_dir.name} ({config.feedback_policy.value})"
        ) from exc
    return 0


def run_judge(args: argparse.Namespace) -> int:
    return BiomniBenchJudgeRunner(JudgeRunConfig.from_namespace(args)).run()


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
