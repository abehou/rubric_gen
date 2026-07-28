"""Command handlers for the BiomniBench CLI."""

from __future__ import annotations

import argparse
import json
import os
import queue
import signal
import socket
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import replace
from datetime import datetime
from pathlib import Path

from rubric_gen.biomnibench.agent.costs import RunCost
from rubric_gen.biomnibench.agent.models import AgentRunConfig, BatchRunConfig
from rubric_gen.biomnibench.agent.runners import AgentRunner, BiomniBenchBatchRunner
from rubric_gen.biomnibench.agent.workspaces import TaskCatalog
from rubric_gen.biomnibench.judging.models import JudgeRunConfig
from rubric_gen.biomnibench.judging.models import DEFAULT_JUDGE_MODEL
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
from rubric_gen.biomnibench.utils.paths import (
    PROJECT_ROOT,
    directory_component,
    resolve_project_path,
)
from rubric_gen.biomnibench.utils.progress import TerminalProgress
from rubric_gen.biomnibench.utils.serialization import write_json_atomic
from rubric_gen.biomnibench.visualization.comparisons import (
    JudgeComparisonConfig,
    JudgeComparisonPlotter,
)


class _BatchTermination(KeyboardInterrupt):
    pass


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


def run_generate(args: argparse.Namespace) -> int:
    from rubric_gen.biomnibench.rubrics.generator import (
        RubricGenerationConfig,
        RubricGenerationRunner,
    )

    return RubricGenerationRunner(
        RubricGenerationConfig.from_namespace(args)
    ).run()


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
    )).run()


def run_all(args: argparse.Namespace) -> int:
    return BiomniBenchBatchRunner(BatchRunConfig.from_namespace(args)).run()


def _revision_batch_name(args: argparse.Namespace, stamp: str) -> str:
    feedback = (
        "full-v-score"
        if args.full_v_score
        else FeedbackPolicy(args.feedback_policy).value.replace("_", "-")
    )
    rubric = (
        f"set-{directory_component(args.rubric_set)}"
        if args.rubric_set
        else directory_component(args.rubric or "rubric.txt")
    )
    selection = (
        f"top-{'all' if args.top == -1 else args.top}"
        if args.top is not None
        else "tasks-1"
    )
    components = (
        selection,
        f"fb-{feedback}",
        f"pr-{directory_component(args.prompt)}",
        f"n-{args.revision_rounds}",
        f"p-{directory_component(args.provider)}",
        f"m-{directory_component(args.model)}",
        f"j-{directory_component(args.judge_model or DEFAULT_JUDGE_MODEL)}",
        f"rb-{rubric}",
        f"v-{directory_component(args.review)}",
        f"sb-{int(args.sandbox)}",
        f"st-{int(args.skip_trust)}",
        f"web-{int(args.allow_web)}",
        f"net-{int(args.allow_network)}",
        f"ap-{directory_component(args.approval_mode)}",
        f"mc-{args.max_review_chars if args.max_review_chars is not None else 'all'}",
        f"c-{args.max_concurrency}",
        f"x-{directory_component(args.executable)}",
        f"raw-{int(args.raw)}",
    )
    name = "--".join((f"revision-{stamp}", *components))
    if len(name) > 240:
        raise ValueError("derived revision batch directory name is too long")
    return name


def _timestamped_revision_experiment_dir(args: argparse.Namespace) -> Path:
    runs_root = _revision_runs_root()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    return runs_root / _revision_batch_name(args, stamp)


def _revision_runs_root() -> Path:
    return PROJECT_ROOT / "runs" / "biomnibench-revisions"


def _latest_revision_experiment_dir(
    args: argparse.Namespace, task_ids: list[str]
) -> Path:
    runs_root = _revision_runs_root()
    suffix = _revision_batch_name(args, "TIMESTAMP").split("--", 1)[1]
    candidates: list[Path] = []
    for path in runs_root.glob(f"revision-*--{suffix}"):
        manifest_path = path / "batch.json"
        try:
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if manifest.get("task_ids") == task_ids:
            candidates.append(path)
    if not candidates:
        raise FileNotFoundError(
            "no previous revision batch matches the current arguments and tasks"
        )
    return sorted(candidates)[-1]


def run_revise(args: argparse.Namespace) -> int:
    if args.top is not None and args.task is not None:
        raise ValueError("TASK and --top are mutually exclusive")
    if args.top is not None and (args.top == 0 or args.top < -1):
        raise ValueError("--top must be -1 or a positive integer")
    if args.top is None and args.task is None:
        args.task = "data/biomnibench-da/da-10-1"
    if args.top is not None:
        task_dirs = TaskCatalog(resolve_project_path(args.tasks_dir)).tasks()
        if args.top != -1:
            task_dirs = task_dirs[: args.top]
    else:
        task_dirs = [resolve_project_path(args.task)]
    automatic_experiment_dir = args.experiment_dir is None
    if automatic_experiment_dir:
        if args.resume:
            args.experiment_dir = str(
                _latest_revision_experiment_dir(
                    args, [task_dir.name for task_dir in task_dirs]
                )
            )
        if args.restart:
            raise ValueError("--restart requires --experiment-dir")
        if args.experiment_dir is None:
            args.experiment_dir = str(_timestamped_revision_experiment_dir(args))
    args.revision_batch_layout = (
        automatic_experiment_dir or args.top is not None or args.full_v_score
    )
    if not args.revision_batch_layout:
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
    policies = (
        (FeedbackPolicy.FULL, FeedbackPolicy.SCORE_ONLY)
        if args.full_v_score
        else (FeedbackPolicy(args.feedback_policy),)
    )
    configs = [
        SubmissionRevisionConfig.from_namespace(
            argparse.Namespace(
                **{
                    **vars(args),
                    "task": str(task_dir),
                    "feedback_policy": policy.value,
                }
            )
        )
        for task_dir in task_dirs
        for policy in policies
    ]
    if args.resume:
        configs = [
            replace(config, resume=os.path.lexists(config.experiment_dir))
            for config in configs
        ]
    if args.dry_run:
        print(f"Selected {len(task_dirs)} task(s) and {len(configs)} experiment(s).")
        for config in configs:
            print(
                f"{config.task_dir.name}\t{config.feedback_policy.value}\t"
                f"{config.experiment_dir}"
            )
        return 0
    batch_root = resolve_project_path(args.experiment_dir)
    batch_root.mkdir(parents=True, exist_ok=True)
    batch_manifest_path = batch_root / "batch.json"
    previous_interruption: dict[str, object] | None = None
    if args.resume and batch_manifest_path.is_file():
        try:
            previous_manifest = json.loads(batch_manifest_path.read_text())
        except (OSError, json.JSONDecodeError):
            previous_manifest = None
        if (
            isinstance(previous_manifest, dict)
            and previous_manifest.get("status") == "running"
        ):
            previous_interruption = {
                "status": "abandoned",
                "started_at": previous_manifest.get("started_at"),
                "pid": previous_manifest.get("pid"),
                "hostname": previous_manifest.get("hostname"),
                "detected_at": datetime.now().astimezone().isoformat(),
            }
    batch_manifest = {
        "schema_version": 2,
        "kind": "rubric-gen-submission-revision-batch",
        "status": "running",
        "started_at": datetime.now().astimezone().isoformat(),
        "pid": os.getpid(),
        "hostname": socket.gethostname(),
        "run_name": batch_root.name,
        "task_ids": [task_dir.name for task_dir in task_dirs],
        "experiment_dirs": [
            str(config.experiment_dir.relative_to(batch_root)) for config in configs
        ],
        "revision_rounds": args.revision_rounds,
        "feedback_policies": [policy.value for policy in policies],
        "configuration": {
            "provider": args.provider,
            "solver_model": args.model,
            "judge_model": args.judge_model or DEFAULT_JUDGE_MODEL,
            "rubric": args.rubric or "rubric.txt",
            "rubric_set": args.rubric_set,
            "review": args.review,
            "prompt": args.prompt,
            "sandbox": args.sandbox,
            "skip_trust": args.skip_trust,
            "allow_web": args.allow_web,
            "allow_network": args.allow_network,
            "approval_mode": args.approval_mode,
            "max_review_chars": args.max_review_chars,
            "max_concurrency": args.max_concurrency,
            "executable": args.executable,
            "raw": args.raw,
        },
    }
    if previous_interruption is not None:
        batch_manifest["previous_interruption"] = previous_interruption
    write_json_atomic(batch_manifest_path, batch_manifest)
    failures: list[tuple[SubmissionRevisionConfig, BaseException, str]] = []

    def terminate_batch(signum: int, frame: object) -> None:
        del frame
        raise _BatchTermination(f"received signal {signum}")

    previous_sigterm_handler = signal.signal(signal.SIGTERM, terminate_batch)
    try:
        with TerminalProgress(
            total=len(configs),
            description="revise batch",
            unit="experiment",
            position=0,
        ) as progress:
            if args.max_concurrency == 1:
                for config in configs:
                    try:
                        run_submission_revision(replace(config, progress_position=1))
                    except (Exception, SystemExit) as exc:
                        failures.append((config, exc, traceback.format_exc()))
                    finally:
                        progress.update()
            else:
                progress_positions: queue.SimpleQueue[int] = queue.SimpleQueue()
                for position in range(1, args.max_concurrency + 1):
                    progress_positions.put(position)

                def run_with_progress(config: SubmissionRevisionConfig) -> None:
                    position = progress_positions.get()
                    try:
                        run_submission_revision(
                            replace(config, progress_position=position)
                        )
                    finally:
                        progress_positions.put(position)

                with ThreadPoolExecutor(max_workers=args.max_concurrency) as executor:
                    futures = {
                        executor.submit(run_with_progress, config): config
                        for config in configs
                    }
                    for future in as_completed(futures):
                        try:
                            future.result()
                        except (Exception, SystemExit) as exc:
                            failures.append(
                                (futures[future], exc, traceback.format_exc())
                            )
                        finally:
                            progress.update()
    except BaseException as exc:
        batch_manifest["status"] = "interrupted"
        batch_manifest["finished_at"] = datetime.now().astimezone().isoformat()
        batch_manifest["interruption"] = {
            "error_type": type(exc).__name__,
            "error": str(exc),
            "traceback": traceback.format_exc(),
        }
        write_json_atomic(batch_manifest_path, batch_manifest)
        raise
    finally:
        signal.signal(signal.SIGTERM, previous_sigterm_handler)
    if failures:
        batch_manifest["status"] = "failed"
        batch_manifest["finished_at"] = datetime.now().astimezone().isoformat()
        batch_manifest["failed_experiments"] = [
            {
                "experiment_dir": str(config.experiment_dir),
                "task_id": config.task_dir.name,
                "feedback_policy": config.feedback_policy.value,
                "error_type": type(exc).__name__,
                "error": str(exc),
                "traceback": failure_traceback,
            }
            for config, exc, failure_traceback in failures
        ]
        write_json_atomic(batch_manifest_path, batch_manifest)
        config, exc, _ = failures[0]
        raise RuntimeError(
            f"{len(failures)} revision experiments failed; first: "
            f"{config.task_dir.name} ({config.feedback_policy.value}): "
            f"{type(exc).__name__}: {exc}"
        ) from exc
    batch_manifest["status"] = "completed"
    batch_manifest["finished_at"] = datetime.now().astimezone().isoformat()
    write_json_atomic(batch_manifest_path, batch_manifest)
    return 0


def run_judge(args: argparse.Namespace) -> int:
    if getattr(args, "agent_ensemble", False):
        from rubric_gen.biomnibench.forensics.reward_hacking import (
            RewardHackingAuditConfig,
            RewardHackingAuditRunner,
        )

        return RewardHackingAuditRunner(
            RewardHackingAuditConfig.from_namespace(args)
        ).run()
    if getattr(args, "case_dir", None):
        raise ValueError("--case-dir is valid only with --agent-ensemble")
    config = JudgeRunConfig.from_namespace(args)
    if config.ensemble:
        from rubric_gen.biomnibench.judging.ensemble import StrongVerifierRunner

        return StrongVerifierRunner(config).run()
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
