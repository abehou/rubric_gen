"""Run rubric-generation experiments and audits."""

from __future__ import annotations

import argparse

import yaml

from rubric_gen.submission_revision.commands import (
    run_detect as run_submission_detect,
    run_dag,
    run_judge as run_submission_judge,
    run_revise,
    run_seed,
)
from rubric_gen.submission_revision.experiment import EXPERIMENT_KIND, load_experiment
from rubric_gen.runtime.paths import resolve_project_path
from rubric_gen.runtime.vllm import add_vllm_argument
from rubric_gen.harvey.audits import run_quality_audit, run_reward_hacking_audit
from rubric_gen.harvey.config import (
    HARVEY_EXPERIMENT_KIND,
    load_experiment as load_harvey_experiment,
)
from rubric_gen.harvey.controller import HarveyEvolutionController


def _experiment_kind(value: str) -> str:
    path = resolve_project_path(value)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"experiment must be a regular YAML file: {path}")
    payload = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or not isinstance(payload.get("kind"), str):
        raise ValueError(f"experiment kind is missing or invalid: {path}")
    kind = payload["kind"]
    if kind not in {EXPERIMENT_KIND, HARVEY_EXPERIMENT_KIND}:
        raise ValueError(f"unsupported experiment kind: {kind}")
    return kind


def _require_submission_experiment(args: argparse.Namespace) -> int:
    if _experiment_kind(args.experiment) != EXPERIMENT_KIND:
        raise ValueError(f"{args.command} does not support Harvey experiments")
    return args.submission_handler(args)


def _run(args: argparse.Namespace) -> int:
    if _experiment_kind(args.experiment) == EXPERIMENT_KIND:
        return run_dag(args)
    if args.restart:
        raise ValueError("Harvey run does not support --restart")
    if args.max_concurrency != 1:
        raise ValueError("Harvey run does not support --max-concurrency")
    if args.vllm:
        raise ValueError("Harvey run does not support --vllm")
    experiment = load_harvey_experiment(resolve_project_path(args.experiment))
    return HarveyEvolutionController(experiment).run(resume=args.resume)


def _judge(args: argparse.Namespace) -> int:
    if _experiment_kind(args.experiment) == HARVEY_EXPERIMENT_KIND:
        if args.output_dir is not None:
            raise ValueError("Harvey judge writes to the experiment output directory")
        if args.resume:
            raise ValueError("Harvey judge does not support --resume")
        experiment = load_harvey_experiment(resolve_project_path(args.experiment))
        return run_quality_audit(experiment)
    if args.output_dir is None:
        raise ValueError("submission judge requires --output-dir")
    experiment = load_experiment(resolve_project_path(args.experiment))
    forwarded = argparse.Namespace(
        study_dir=str(experiment.dag["revise"]["output_dir"]),
        output_dir=args.output_dir,
        max_concurrency=args.max_concurrency,
        max_retries=args.max_retries,
        resume=args.resume,
    )
    return run_submission_judge(forwarded)


def _detect(args: argparse.Namespace) -> int:
    if _experiment_kind(args.experiment) == HARVEY_EXPERIMENT_KIND:
        if args.max_concurrency != 3:
            raise ValueError("Harvey detect does not support --max-concurrency")
        if args.vllm:
            raise ValueError("Harvey detect does not support --vllm")
        experiment = load_harvey_experiment(resolve_project_path(args.experiment))
        return run_reward_hacking_audit(experiment, resume=args.resume)
    experiment = load_experiment(resolve_project_path(args.experiment))
    forwarded = argparse.Namespace(
        run_dir=str(experiment.dag["revise"]["output_dir"]),
        output_dir=str(experiment.dag["detect"]["output_dir"]),
        max_concurrency=args.max_concurrency,
        resume=args.resume,
        vllm=args.vllm,
    )
    return run_submission_detect(forwarded)


def _add_submission_command(
    subparsers: argparse._SubParsersAction, name: str, handler: object
) -> None:
    parser = subparsers.add_parser(name, help=f"{name.title()} submission work.")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    add_vllm_argument(parser)
    parser.set_defaults(handler=_require_submission_experiment, submission_handler=handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_submission_command(subparsers, "seed", run_seed)
    _add_submission_command(subparsers, "revise", run_revise)

    run = subparsers.add_parser("run", help="Run an experiment workflow.")
    run.add_argument("--experiment", required=True)
    run.add_argument("--max-concurrency", type=int, default=1)
    continuation = run.add_mutually_exclusive_group()
    continuation.add_argument("--resume", action="store_true")
    continuation.add_argument("--restart", action="store_true")
    add_vllm_argument(run)
    run.set_defaults(handler=_run)

    judge = subparsers.add_parser("judge", help="Run a sealed quality audit.")
    judge.add_argument("--experiment", required=True)
    judge.add_argument("--output-dir")
    judge.add_argument("--max-concurrency", type=int, default=3)
    judge.add_argument("--max-retries", type=int, default=1)
    judge.add_argument("--resume", action="store_true")
    judge.set_defaults(handler=_judge)

    detect = subparsers.add_parser("detect", help="Detect reward hacking.")
    detect.add_argument("--experiment", required=True)
    detect.add_argument("--max-concurrency", type=int, default=3)
    detect.add_argument("--resume", action="store_true")
    add_vllm_argument(detect)
    detect.set_defaults(handler=_detect)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
