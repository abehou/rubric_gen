"""Command line interface for BiomniBench agent experiments."""

from __future__ import annotations

import argparse

from rubric_gen.biomnibench.adapters import AgentAdapterRegistry
from rubric_gen.biomnibench.common import (
    AgentRunConfig,
    BatchRunConfig,
    RunCost,
    resolve_project_path,
)
from rubric_gen.biomnibench.judges import BiomniBenchJudgeRunner, JudgeRunConfig
from rubric_gen.biomnibench.perturbations import (
    DEFAULT_PERTURBER_MODEL,
    DEFAULT_GEMINI_API_KEY_ENV,
    DEFAULT_PERTURBATION_MAX_CONCURRENCY,
    DEFAULT_PERTURBATION_LEVELS,
    BiomniBenchPerturbationRunner,
    PerturbationRunConfig,
)
from rubric_gen.biomnibench.process_rubrics import (
    ProcessRubricConfig,
    ProcessRubricGenerator,
)
from rubric_gen.biomnibench.runners import AgentRunner, BiomniBenchBatchRunner
from rubric_gen.biomnibench.submission_feedback import FeedbackPolicy
from rubric_gen.biomnibench.submission_revision import (
    SubmissionRevisionConfig,
    run_submission_revision,
)
from rubric_gen.biomnibench.task_rubric_compiler import (
    TaskProcessRubricCompiler,
    TaskRubricCompilerConfig,
)
from rubric_gen.biomnibench.visualizations import (
    JudgeComparisonConfig,
    JudgeComparisonPlotter,
)


def add_agent_args(
    parser: argparse.ArgumentParser,
    *,
    persistent_session: bool = False,
) -> None:
    provider_names = AgentAdapterRegistry().names
    parser.add_argument(
        "--provider",
        choices=provider_names,
        default="gemini",
        help="Agent CLI provider to run.",
    )
    parser.add_argument(
        "--executable",
        default=None,
        help="Override the provider executable name or path.",
    )
    parser.add_argument(
        "--model",
        required=persistent_session,
        default=None,
        help=(
            "Provider-native model name (required for persistent sessions)."
            if persistent_session
            else "Optional provider-native model name."
        ),
    )
    parser.add_argument(
        "--raw", action="store_true", help="Print raw trajectory lines."
    )
    parser.add_argument(
        "--skip-trust",
        action="store_true",
        help="Forward provider trust bypass when supported.",
    )
    parser.add_argument(
        "--allow-web",
        action="store_true",
        help="Allow provider web tools when supported. Disabled by prompt/policy by default.",
    )
    parser.add_argument(
        "--approval-mode",
        default=None,
        help="Provider-native approval/permission mode. Defaults are provider-specific.",
    )
    parser.add_argument(
        "--sandbox",
        action="store_true",
        help="Ask the provider to use its sandbox option when supported.",
    )
    if not persistent_session:
        parser.add_argument(
            "--extra-agent-arg",
            action="append",
            default=[],
            help="Append one raw argument to the provider command. Repeat for multiple args.",
        )
        parser.add_argument(
            "--retries",
            type=int,
            default=1,
            help="Retry transient provider stream failures this many times.",
        )


def _add_one_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    one = subparsers.add_parser("one", help="Run one BiomniBench-DA task.")
    one.add_argument(
        "task",
        nargs="?",
        default="data/biomnibench-da/da-10-1",
        help="BiomniBench task directory, e.g. data/biomnibench-da/da-24-3.",
    )
    one.add_argument(
        "--runs-dir",
        default="runs/biomnibench-agents",
        help="Directory where per-run sandboxes and logs are written.",
    )
    add_agent_args(one)


def _add_revise_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    revise = subparsers.add_parser(
        "revise",
        help="Run one persistent-session submission revision experiment.",
    )
    revise.add_argument(
        "task",
        nargs="?",
        default="data/biomnibench-da/da-10-1",
        help="BiomniBench task directory, e.g. data/biomnibench-da/da-24-3.",
    )
    revise.add_argument(
        "--experiment-dir",
        required=True,
        help="Base directory name; the revision configuration is appended to it.",
    )
    experiment_mode = revise.add_mutually_exclusive_group()
    experiment_mode.add_argument(
        "--resume",
        action="store_true",
        help="Resume an existing experiment only from its recorded safe boundary.",
    )
    experiment_mode.add_argument(
        "--restart",
        action="store_true",
        help="Delete a matching existing revision experiment and restart from s000.",
    )
    revise.add_argument(
        "--revision-rounds",
        type=int,
        default=3,
        help="Number of same-session revisions after the initial submission. Defaults to 3.",
    )
    revise.add_argument(
        "--feedback-policy",
        choices=tuple(policy.value for policy in FeedbackPolicy),
        default=FeedbackPolicy.FULL.value,
        help="Feedback returned to the solver. Defaults to full.",
    )
    revise.add_argument(
        "--review",
        choices=("trace", "trajectory"),
        default="trajectory",
        help="Judge trace.md or the cumulative raw trajectory. Defaults to trajectory.",
    )
    revise.add_argument(
        "--judge-model",
        default=None,
        help="Set the model used by the task judge subprocess.",
    )
    rubric_source = revise.add_mutually_exclusive_group()
    rubric_source.add_argument(
        "--rubric",
        default=None,
        help="Rubric filename under the task's tests directory. Defaults to rubric.txt.",
    )
    rubric_source.add_argument(
        "--rubric-set",
        default=None,
        help="Sealed external rubric-set directory, resolved by target task ID.",
    )
    revise.add_argument(
        "--max-review-chars",
        type=int,
        default=None,
        help="Optionally truncate the trace or trajectory before judging.",
    )
    add_agent_args(revise, persistent_session=True)
    revise.set_defaults(quiet=True)


def _add_all_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    all_tasks = subparsers.add_parser(
        "all", help="Run every pending BiomniBench-DA task."
    )
    all_tasks.add_argument(
        "--tasks-dir",
        default="data/biomnibench-da",
        help="Directory containing da-* task directories.",
    )
    all_tasks.add_argument(
        "--runs-dir",
        default="runs/biomnibench-agents",
        help="Directory where all-run batch directories are written.",
    )
    all_tasks.add_argument(
        "--resume-run",
        default=None,
        help="Existing all-run directory to resume, e.g. runs/biomnibench-agents/all-gemini-...",
    )
    all_tasks.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Run at most this many pending tasks.",
    )
    all_tasks.add_argument(
        "--force",
        action="store_true",
        help="Run tasks even if a prior successful run exists.",
    )
    all_tasks.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Continue to later tasks when one agent run exits non-zero.",
    )
    all_tasks.add_argument(
        "--max-concurrency",
        type=int,
        default=1,
        help="Run up to this many agent tasks concurrently. Defaults to 1.",
    )
    add_agent_args(all_tasks)


def _add_judge_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    judge = subparsers.add_parser(
        "judge", help="Run task-local LLM judges over saved runs."
    )
    judge.add_argument(
        "--run-dir",
        action="append",
        nargs="+",
        required=True,
        help="Single task run dir or all-run batch dir to judge. Accepts one or more paths; repeat if desired.",
    )
    judge.add_argument(
        "--tasks-dir",
        default="data/biomnibench-da",
        help="Directory containing da-* task directories with tests/llm_judge.py.",
    )
    judge.add_argument(
        "--review",
        choices=("trace", "trajectory"),
        default="trace",
        help="Judge trace.md or the raw trajectory stream as the trace input.",
    )
    judge.add_argument(
        "--model",
        default=None,
        help="Set MODEL_NAME for the task judge subprocess.",
    )
    judge.add_argument(
        "--output",
        default=None,
        help="Score summary JSON path. Defaults to <run_dir>/judge-<review>-scores.json.",
    )
    judge.add_argument(
        "--judge-name",
        default=None,
        help="Override judge filename. Defaults to llm_judge.py, then judge.py.",
    )
    rubric_source = judge.add_mutually_exclusive_group()
    rubric_source.add_argument(
        "--rubric",
        default=None,
        help="Rubric filename under each task's tests directory. Defaults to rubric.txt.",
    )
    rubric_source.add_argument(
        "--rubric-set",
        default=None,
        help="Sealed external rubric-set directory, resolved by target task ID.",
    )
    judge.add_argument(
        "--limit", type=int, default=None, help="Judge at most this many tasks."
    )
    judge.add_argument(
        "--dry-run", action="store_true", help="Plan judge inputs without calling LLMs."
    )
    judge.add_argument(
        "--max-review-chars",
        type=int,
        default=None,
        help="Optionally truncate trace/trajectory input before judging.",
    )
    judge.add_argument(
        "--resume",
        action="store_true",
        help="Skip tasks whose judge output already has a scored reward.json.",
    )
    judge.add_argument(
        "--force",
        action="store_true",
        help="Rerun judge tasks even when --resume finds existing scored outputs.",
    )
    judge.add_argument(
        "--max-concurrency",
        type=int,
        default=1,
        help="Run up to this many judge subprocesses concurrently.",
    )
    judge.add_argument(
        "--repeats",
        type=int,
        default=1,
        help="Run each task judge this many independent times to estimate judge variance.",
    )


def _add_compare_judges_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    compare_judges = subparsers.add_parser(
        "compare-judges",
        help="Plot paired judge score comparisons.",
    )
    compare_judges.add_argument(
        "--run-dir",
        required=True,
        help="All-run batch dir containing judge-trace-scores.json and judge-trajectory-scores.json.",
    )
    compare_judges.add_argument(
        "--trace-scores",
        default=None,
        help="Override path to judge-trace-scores.json.",
    )
    compare_judges.add_argument(
        "--trajectory-scores",
        default=None,
        help="Override path to judge-trajectory-scores.json.",
    )
    compare_judges.add_argument(
        "--left-scores",
        default=None,
        help="Generic left/X-axis score JSON path. Overrides --trace-scores.",
    )
    compare_judges.add_argument(
        "--right-scores",
        default=None,
        help="Generic right/Y-axis score JSON path. Overrides --trajectory-scores.",
    )
    compare_judges.add_argument(
        "--left-label",
        default=None,
        help="Label for the left/X-axis scores.",
    )
    compare_judges.add_argument(
        "--right-label",
        default=None,
        help="Label for the right/Y-axis scores.",
    )
    compare_judges.add_argument(
        "--out-dir",
        default=None,
        help="Output directory for plots. Defaults to <run-dir>/judge-comparison-plots.",
    )
    compare_judges.add_argument(
        "--label-top-n",
        type=int,
        default=8,
        help="Label this many largest-disagreement tasks on the scatter plot.",
    )


def _add_perturb_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    perturb = subparsers.add_parser(
        "perturb", help="Create LLM-perturbed variants of saved BiomniBench runs."
    )
    perturb.add_argument(
        "--base-run",
        required=True,
        help="Existing single task run dir or all-run batch dir to perturb.",
    )
    perturb.add_argument(
        "--out-dir",
        required=True,
        help="Directory where perturbation level run dirs and manifest are written.",
    )
    perturb.add_argument(
        "--tasks",
        default=None,
        help="Comma-separated task ids to perturb. Defaults to every task discovered in --base-run.",
    )
    perturb.add_argument(
        "--levels",
        default=",".join(DEFAULT_PERTURBATION_LEVELS),
        help="Comma-separated perturbation levels. Defaults to C,L0,L1,L2,L3,L4,L5.",
    )
    perturb.add_argument(
        "--perturber-model",
        default=DEFAULT_PERTURBER_MODEL,
        help=f"Gemini model used for perturbation. Defaults to {DEFAULT_PERTURBER_MODEL}.",
    )
    perturb.add_argument(
        "--api-key-env",
        default=DEFAULT_GEMINI_API_KEY_ENV,
        help=f"Environment variable containing the Gemini API key. Defaults to {DEFAULT_GEMINI_API_KEY_ENV}.",
    )
    perturb.add_argument(
        "--max-input-chars",
        type=int,
        default=120_000,
        help="Maximum source-artifact characters to include in each perturber prompt.",
    )
    perturb.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Retry invalid Gemini perturbation responses this many times.",
    )
    perturb.add_argument(
        "--max-concurrency",
        type=int,
        default=DEFAULT_PERTURBATION_MAX_CONCURRENCY,
        help=f"Run up to this many perturbation jobs concurrently. Defaults to {DEFAULT_PERTURBATION_MAX_CONCURRENCY}.",
    )
    perturb.add_argument(
        "--resume",
        action="store_true",
        help="Keep the existing output directory and skip task-level perturbations whose files are already complete.",
    )
    perturb.add_argument(
        "--dry-run",
        action="store_true",
        help="Print perturbation plan without writing files.",
    )


def _add_task_process_rubrics_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    task_process_rubrics = subparsers.add_parser(
        "task-process-rubrics",
        help="Compile canonical task-only process rubrics.",
    )
    task_process_rubrics.add_argument(
        "--task",
        dest="tasks",
        action="append",
        required=True,
        help="Task ID to compile. Repeat for multiple tasks.",
    )
    task_process_rubrics.add_argument(
        "--output-dir",
        required=True,
        help="External directory where the sealed rubric bundle is written.",
    )
    task_process_rubrics.add_argument(
        "--tasks-dir",
        default="data/biomnibench-da",
        help="Directory containing da-* task directories.",
    )
    task_process_rubrics.add_argument(
        "--model",
        default="gemini-3.5-flash",
        help="Gemini model used for canonical rubric compilation.",
    )
    task_process_rubrics.add_argument(
        "--api-key-env",
        default="GEMINI_API_KEY",
        help="Environment variable containing the Gemini API key.",
    )
    task_process_rubrics.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Retry invalid compiler responses this many times.",
    )
    task_process_rubrics.add_argument(
        "--max-concurrency",
        type=int,
        default=1,
        help="Compile up to this many task rubrics concurrently.",
    )
    task_process_rubrics.add_argument(
        "--seed",
        type=int,
        default=0,
        help="Deterministic Gemini decoding seed. Defaults to 0.",
    )
    task_process_rubrics.add_argument(
        "--resume",
        action="store_true",
        help="Reuse an exact matching sealed rubric bundle when available.",
    )


def _add_process_rubrics_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    process_rubrics = subparsers.add_parser(
        "process-rubrics",
        help="Generate trajectory-informed retrospective rubrics (not canonical).",
        description="Generate trajectory-informed retrospective rubrics; not canonical.",
    )
    process_rubrics.add_argument(
        "--tasks-dir",
        default="data/biomnibench-da",
        help="Directory containing da-* task directories.",
    )
    process_rubrics.add_argument(
        "--run-dir",
        default="runs/biomnibench-agents/all-gemini-20260705-185054",
        help="All-run batch directory containing task trajectories and workspaces.",
    )
    process_rubrics.add_argument(
        "--model",
        default=DEFAULT_PERTURBER_MODEL,
        help=f"Gemini model used for rubric rewriting. Defaults to {DEFAULT_PERTURBER_MODEL}.",
    )
    process_rubrics.add_argument(
        "--api-key-env",
        default=DEFAULT_GEMINI_API_KEY_ENV,
        help=f"Environment variable containing the Gemini API key. Defaults to {DEFAULT_GEMINI_API_KEY_ENV}.",
    )
    process_rubrics.add_argument(
        "--max-input-chars",
        type=int,
        default=140_000,
        help="Maximum evidence-packet characters to include in each rewrite prompt.",
    )
    process_rubrics.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help="Retry invalid LLM rubric responses this many times.",
    )
    process_rubrics.add_argument(
        "--max-concurrency",
        type=int,
        default=1,
        help="Run up to this many rubric rewrite jobs concurrently.",
    )
    process_rubrics.add_argument(
        "--resume",
        action="store_true",
        help="Skip tasks with an existing valid process_rubric.txt.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    _add_one_parser(subparsers)
    _add_revise_parser(subparsers)
    _add_all_parser(subparsers)
    _add_judge_parser(subparsers)
    _add_compare_judges_parser(subparsers)
    _add_perturb_parser(subparsers)
    _add_task_process_rubrics_parser(subparsers)
    _add_process_rubrics_parser(subparsers)
    return parser


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


def run_revise(args: argparse.Namespace) -> int:
    run_submission_revision(SubmissionRevisionConfig.from_namespace(args))
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
    config = TaskRubricCompilerConfig.from_namespace(args)
    return TaskProcessRubricCompiler(config).run()


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "one":
        return run_one(args)
    if args.command == "revise":
        return run_revise(args)
    if args.command == "all":
        return run_all(args)
    if args.command == "judge":
        return run_judge(args)
    if args.command == "compare-judges":
        return run_compare_judges(args)
    if args.command == "perturb":
        return run_perturb(args)
    if args.command == "process-rubrics":
        return run_process_rubrics(args)
    if args.command == "task-process-rubrics":
        return run_task_process_rubrics(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
