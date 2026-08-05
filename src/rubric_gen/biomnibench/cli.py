"""Command line interface for BiomniBench agent experiments."""

from __future__ import annotations

import argparse

from rubric_gen.biomnibench.agent.adapters import AgentAdapterRegistry
from rubric_gen.biomnibench.agent.prompts import MAX_TRANSIENT_RETRIES, PromptProfile
from rubric_gen.biomnibench.integrations.gemini import DEFAULT_GEMINI_API_KEY_ENV
from rubric_gen.biomnibench.judging.models import DEFAULT_JUDGE_MODEL
from rubric_gen.biomnibench.perturbation.models import (
    DEFAULT_PERTURBATION_MAX_CONCURRENCY,
    DEFAULT_PERTURBATION_LEVELS,
    DEFAULT_PERTURBER_MODEL,
)
from rubric_gen.biomnibench.revision.feedback import FeedbackPolicy
from rubric_gen.biomnibench.forensics.protocol import (
    DEFAULT_RH_MAX_COMMAND_OUTPUT_CHARS,
    DEFAULT_RH_MAX_COST_USD,
    DEFAULT_RH_MAX_EVENT_TEXT_CHARS,
    DEFAULT_RH_MAX_INPUT_TOKENS,
    DEFAULT_RH_MAX_OUTPUT_TOKENS,
    DEFAULT_RH_MAX_RETRIES,
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
        default="codex",
        help="Agent CLI provider to run.",
    )
    parser.add_argument(
        "--executable",
        default=None,
        help="Override the provider executable name or path.",
    )
    parser.add_argument(
        "--model",
        required=True,
        help="Exact provider-native model name. Required for reproducibility.",
    )
    parser.add_argument(
        "--raw", action="store_true", help="Print raw trajectory lines."
    )
    parser.add_argument(
        "--reasoning-effort",
        choices=("minimal", "low", "medium", "high", "xhigh"),
        default=None,
        help="Codex reasoning effort. Recorded exactly in run provenance.",
    )
    parser.add_argument(
        "--service-tier",
        choices=("priority",),
        default=None,
        help="Optional Codex service tier. Omit for provider default.",
    )
    parser.add_argument(
        "--turn-timeout-seconds",
        type=int,
        default=7_200,
        help="Hard wall-clock timeout for each agent invocation.",
    )
    if persistent_session:
        parser.add_argument(
            "--retries",
            type=int,
            choices=range(MAX_TRANSIENT_RETRIES + 1),
            default=MAX_TRANSIENT_RETRIES,
            help=(
                "Resume the same session after transient provider failures this "
                f"many times. Maximum {MAX_TRANSIENT_RETRIES}."
            ),
        )
    else:
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


def _add_generate_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    generate = subparsers.add_parser(
        "generate",
        help="Explore BiomniBench tasks and generate task-specific rubrics.",
    )
    generate.add_argument(
        "task",
        nargs="?",
        help="One task directory. Omit when using --top.",
    )
    generate.add_argument(
        "--top",
        type=int,
        default=None,
        help="Run the first N discovered tasks; -1 runs every task.",
    )
    generate.add_argument(
        "--tasks-dir",
        default="data/biomnibench-da",
        help="Task catalog used by --top.",
    )
    generate.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Output root. Defaults to a timestamped directory under "
            "runs/biomnibench-rubrics in the current repository."
        ),
    )
    generate.add_argument(
        "--harness",
        choices=("gemini-cli", "claude-code", "codex-cli"),
        default="gemini-cli",
        help="Terminal agent harness. Defaults to gemini-cli.",
    )
    generate.add_argument(
        "--model",
        default=None,
        help="Harness-native model ID. Defaults to the strongest configured model for the harness.",
    )
    generate.add_argument("--executable", default=None)
    generate.add_argument(
        "--reasoning-effort",
        choices=("minimal", "low", "medium", "high", "xhigh"),
        default=None,
    )
    generate.add_argument("--service-tier", choices=("priority",), default=None)
    generate.add_argument("--turn-timeout-seconds", type=int, default=7_200)
    generate.add_argument("--max-concurrency", type=int, default=1)
    generate.add_argument("--resume", action="store_true")
    generate.add_argument("--raw", action="store_true")


def _add_design_parser(subparsers: argparse._SubParsersAction) -> None:
    design = subparsers.add_parser(
        "design",
        help="Create an immutable randomized 2x2 revision-study design.",
    )
    design.add_argument("--tasks-dir", default="data/biomnibench-da")
    design.add_argument("--output", required=True)
    design.add_argument("--protocol-id", required=True)
    design.add_argument(
        "--dataset-revision",
        required=True,
        help="Pinned dataset commit/revision or independently verified snapshot ID.",
    )
    design.add_argument("--random-seed", type=int, default=42)
    design.add_argument(
        "--sample-size",
        type=int,
        default=None,
        help="Randomly sample this many tasks; omit to randomize every task.",
    )
    design.add_argument("--replicates", type=int, default=3)
    design.add_argument("--revision-rounds", type=int, default=10)
    design.add_argument(
        "--feedback-policy",
        choices=tuple(policy.value for policy in FeedbackPolicy),
        default=FeedbackPolicy.SEMI.value,
    )
    design.add_argument(
        "--treatment-prompt",
        choices=(PromptProfile.ANTI_RH.value, PromptProfile.DILIGENT.value),
        default=PromptProfile.ANTI_RH.value,
        help="Prompt compared with base. Use anti-rh for an RH-mitigation study.",
    )
    design.add_argument(
        "--stage", choices=("development", "validation", "confirmatory"),
        default="development",
    )
    design.add_argument(
        "--validated-design",
        default=None,
        help=(
            "Path to the actual validation-stage design. Required only for a "
            "confirmatory design; its tasks are excluded from sampling."
        ),
    )
    design.add_argument("--minimum-detectable-effect", type=float, default=0.30)
    design.add_argument("--anticipated-discordance", type=float, default=0.30)
    design.add_argument("--alpha", type=float, default=0.05)
    design.add_argument("--target-power", type=float, default=0.80)
    design.add_argument("--judge", dest="judge_model", default=DEFAULT_JUDGE_MODEL)
    design.add_argument(
        "--judge-max-retries",
        type=int,
        choices=range(MAX_TRANSIENT_RETRIES + 1),
        default=1,
        help="Retry transient optimizer-judge failures this many times.",
    )
    design.add_argument("--rubric", default="rubric.txt")
    design.add_argument("--review", choices=("trace", "trajectory"), default="trace")
    design.add_argument("--max-review-chars", type=int, default=None)
    design.add_argument("--rubric-proposer-model", default="gpt-5.6-luna")
    design.add_argument("--rubric-proposer-step-limit", type=int, default=12)
    design.add_argument(
        "--rubric-proposer-max-retries",
        type=int,
        choices=range(MAX_TRANSIENT_RETRIES + 1),
        default=1,
        help="Retry failed prospective rubric proposals this many times.",
    )
    design.add_argument(
        "--primary-rh-rule",
        choices=("majority", "any_detects", "unanimous_detects"),
        default="majority",
    )
    design.add_argument(
        "--audit-max-input-tokens",
        type=int,
        default=DEFAULT_RH_MAX_INPUT_TOKENS,
    )
    design.add_argument(
        "--audit-max-output-tokens",
        type=int,
        default=DEFAULT_RH_MAX_OUTPUT_TOKENS,
    )
    design.add_argument(
        "--audit-max-event-text-chars",
        type=int,
        default=DEFAULT_RH_MAX_EVENT_TEXT_CHARS,
        help="Per-event text cap after deterministic head/tail evidence compaction.",
    )
    design.add_argument(
        "--audit-max-command-output-chars",
        type=int,
        default=DEFAULT_RH_MAX_COMMAND_OUTPUT_CHARS,
        help=(
            "Per-command-output cap after deterministic head/tail evidence "
            "compaction."
        ),
    )
    design.add_argument(
        "--audit-max-retries", type=int, default=DEFAULT_RH_MAX_RETRIES
    )
    design.add_argument(
        "--audit-max-cost-usd",
        type=float,
        default=DEFAULT_RH_MAX_COST_USD,
        help="Hard total API budget for the prespecified three-provider audit.",
    )
    design.add_argument("--executable", default=None)
    design.add_argument(
        "--model", required=True, help="Exact Codex solver model name."
    )
    design.add_argument(
        "--reasoning-effort",
        choices=("minimal", "low", "medium", "high", "xhigh"),
        default="minimal",
    )
    design.add_argument("--service-tier", choices=("priority",), default=None)
    design.add_argument("--turn-timeout-seconds", type=int, default=7_200)
    design.add_argument(
        "--retries",
        type=int,
        choices=range(MAX_TRANSIENT_RETRIES + 1),
        default=1,
        help="Resume a solver session after transient failures this many times.",
    )
    design.set_defaults(provider="codex", raw=False, quiet=True)


def _add_seed_parser(subparsers: argparse._SubParsersAction) -> None:
    seed = subparsers.add_parser(
        "seed",
        help="Generate one sealed s000 for every task/replicate block in a design.",
    )
    seed.add_argument("--design", required=True)
    seed.add_argument("--output-dir", required=True)
    seed.add_argument("--max-concurrency", type=int, default=1)
    seed.add_argument("--resume", action="store_true")


def _add_run_design_parser(subparsers: argparse._SubParsersAction) -> None:
    run_design = subparsers.add_parser(
        "run-design",
        help="Execute every randomized assignment in a locked design.",
    )
    run_design.add_argument("--design", required=True)
    run_design.add_argument("--seed-run-dir", required=True)
    run_design.add_argument("--output-dir", required=True)
    run_design.add_argument("--max-concurrency", type=int, default=1)
    run_design.add_argument("--resume", action="store_true")
    run_design.add_argument("--dry-run", action="store_true")


def _add_status_parser(subparsers: argparse._SubParsersAction) -> None:
    status = subparsers.add_parser(
        "status", help="Integrity-check completion and health of a randomized study."
    )
    status.add_argument("--design", required=True)
    status.add_argument("--run-dir", required=True)


def _add_cost_parser(subparsers: argparse._SubParsersAction) -> None:
    cost = subparsers.add_parser(
        "cost", help="Report measured API cost and missing coverage by study stage."
    )
    cost.add_argument("--design", required=True)
    cost.add_argument("--seed-run-dir", default=None)
    cost.add_argument("--run-dir", default=None)
    cost.add_argument("--audit-summary", default=None)
    cost.add_argument("--output", default=None)


def _add_analyze_parser(subparsers: argparse._SubParsersAction) -> None:
    analyze = subparsers.add_parser(
        "analyze", help="Run the prespecified clustered 2x2 RH analysis."
    )
    analyze.add_argument("--design", required=True)
    analyze.add_argument("--run-dir", required=True)
    analyze.add_argument("--audit-summary", required=True)
    analyze.add_argument("--output", required=True)


def _add_cross_score_parser(subparsers: argparse._SubParsersAction) -> None:
    cross_score = subparsers.add_parser(
        "cross-score",
        help="Post-hoc score every checkpoint under every realized rubric version.",
    )
    cross_score.add_argument("--design", required=True)
    cross_score.add_argument("--run-dir", required=True)
    cross_score.add_argument("--max-concurrency", type=int, default=1)
    cross_score.add_argument("--resume", action="store_true")


def _add_blind_export_parser(subparsers: argparse._SubParsersAction) -> None:
    blind = subparsers.add_parser(
        "blind-export", help="Export blinded A/B human-review packets."
    )
    blind.add_argument("--design", required=True)
    blind.add_argument("--run-dir", required=True)
    blind.add_argument("--output-dir", required=True)
    blind.add_argument("--key-output", required=True)


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
        help=f"Judge model. Defaults to {DEFAULT_JUDGE_MODEL}.",
    )
    judge.add_argument(
        "--output",
        default=None,
        help="Score summary JSON path. Defaults to <run_dir>/judge-<review>-scores.json.",
    )
    judge.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Judge artifact root. Defaults to a deterministic directory under "
            "runs/biomnibench-judges in the current repository."
        ),
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
        help="Reuse completed judge or forensic-panel outputs.",
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


def _add_rubric_free_parser(
    subparsers: argparse._SubParsersAction,
) -> None:
    rubric_free = subparsers.add_parser(
        "rubric-free",
        help="Compare initial and final revision submissions without a rubric.",
    )
    rubric_free.add_argument("--run-dir", action="append", required=True)
    rubric_free.add_argument(
        "--output-dir", default="runs/biomnibench-rubric-free"
    )
    rubric_free.add_argument(
        "--models", nargs=3,
        default=("gpt-5.6-sol", "claude-opus-4-8", "gemini-3.1-pro-preview"),
        metavar=("OPENAI", "CLAUDE", "GEMINI"),
    )
    rubric_free.add_argument("--max-concurrency", type=int, default=3)
    rubric_free.add_argument("--max-retries", type=int, default=2)
    rubric_free.add_argument(
        "--resume",
        action="store_true",
        help="Reuse completed experiment/model/position judgments.",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command")
    _add_one_parser(subparsers)
    _add_generate_parser(subparsers)
    _add_design_parser(subparsers)
    _add_seed_parser(subparsers)
    _add_run_design_parser(subparsers)
    _add_status_parser(subparsers)
    _add_cost_parser(subparsers)
    _add_analyze_parser(subparsers)
    _add_cross_score_parser(subparsers)
    _add_blind_export_parser(subparsers)
    _add_all_parser(subparsers)
    _add_judge_parser(subparsers)
    _add_compare_judges_parser(subparsers)
    _add_perturb_parser(subparsers)
    _add_task_process_rubrics_parser(subparsers)
    _add_process_rubrics_parser(subparsers)
    _add_rubric_free_parser(subparsers)
    return parser


from rubric_gen.biomnibench.commands import (
    run_all,
    run_analyze,
    run_blind_export,
    run_compare_judges,
    run_cost,
    run_cross_score,
    run_design,
    run_generate,
    run_judge,
    run_one,
    run_perturb,
    run_process_rubrics,
    run_seed,
    run_status,
    run_study,
    run_rubric_free,
    run_task_process_rubrics,
)


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "one":
        return run_one(args)
    if args.command == "generate":
        return run_generate(args)
    if args.command == "design":
        return run_design(args)
    if args.command == "seed":
        return run_seed(args)
    if args.command == "run-design":
        return run_study(args)
    if args.command == "status":
        return run_status(args)
    if args.command == "cost":
        return run_cost(args)
    if args.command == "analyze":
        return run_analyze(args)
    if args.command == "cross-score":
        return run_cross_score(args)
    if args.command == "blind-export":
        return run_blind_export(args)
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
    if args.command == "rubric-free":
        return run_rubric_free(args)
    parser.print_help()
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
