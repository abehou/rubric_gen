"""Run rubric-generation experiments and audits."""

from __future__ import annotations

import argparse

from rubric_gen.submission_revision.commands import (
    run_detect as run_submission_detect,
    run_dag,
    run_judge as run_submission_judge,
    run_paraphrase,
    run_revise,
    run_seed,
)
from rubric_gen.submission_revision.experiment import EXPERIMENT_KIND, load_experiment
from rubric_gen.runtime.paths import resolve_project_path
from rubric_gen.runtime.yaml import load_yaml_strict
from rubric_gen.benchmarks.harvey_lab.config import (
    HARVEY_EXPERIMENT_KIND,
    load_experiment as load_harvey_experiment,
)
from rubric_gen.benchmarks.harvey_lab.runtime import runtime_root_from_environment
from rubric_gen.benchmarks.harvey_lab.seal import (
    harvey_run_seal_exists,
    seal_harvey_run,
    validate_harvey_run_seal,
)
from rubric_gen.benchmarks.harvey_lab.study import HarveyStudyController


def _experiment_kind(value: str) -> str:
    path = resolve_project_path(value)
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"experiment must be a regular YAML file: {path}")
    payload = load_yaml_strict(path.read_text(encoding="utf-8"))
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
        if args.max_retries is not None:
            raise ValueError("--max-retries supports only Harvey experiments")
        return run_dag(args)
    if args.restart:
        raise ValueError("Harvey run does not support --restart")
    if args.max_concurrency < 1:
        raise ValueError("--max-concurrency must be positive")
    max_retries = 3 if args.max_retries is None else args.max_retries
    if max_retries < 0:
        raise ValueError("--max-retries must be non-negative")
    experiment = load_harvey_experiment(resolve_project_path(args.experiment))
    if harvey_run_seal_exists(experiment.output_dir):
        if args.resume:
            seal_harvey_run(experiment)
            return 0
        validate_harvey_run_seal(experiment)
        raise FileExistsError(
            f"Harvey run is sealed; use --resume to verify it: {experiment.output_dir}"
        )
    runtime_root = runtime_root_from_environment()
    status = HarveyStudyController(
        experiment,
        runtime_root=runtime_root,
        max_concurrency=args.max_concurrency,
        max_retries=max_retries,
    ).run(resume=args.resume)
    if status:
        return status
    seal = seal_harvey_run(experiment)
    print(f"Harvey run sealed: {seal['artifact_tree_sha256']}")
    return 0


def _judge(args: argparse.Namespace) -> int:
    if _experiment_kind(args.experiment) == HARVEY_EXPERIMENT_KIND:
        if args.output_dir is not None:
            raise ValueError("Harvey judge writes to the experiment output directory")
        if args.resume:
            raise ValueError("Harvey judge does not support --resume")
        if args.max_concurrency < 1:
            raise ValueError("--max-concurrency must be positive")
        if args.max_retries < 0:
            raise ValueError("--max-retries must be non-negative")
        experiment = load_harvey_experiment(resolve_project_path(args.experiment))
        if harvey_run_seal_exists(experiment.output_dir):
            validate_harvey_run_seal(experiment)
            raise ValueError("sealed Harvey runs are immutable")
        runtime_root = runtime_root_from_environment()
        return HarveyStudyController(
            experiment,
            runtime_root=runtime_root,
            max_concurrency=args.max_concurrency,
            max_retries=args.max_retries,
        ).run_quality()
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
        if args.study_dir is not None:
            raise ValueError("Harvey detect does not support --study-dir")
        if args.max_concurrency < 1:
            raise ValueError("--max-concurrency must be positive")
        experiment = load_harvey_experiment(resolve_project_path(args.experiment))
        if harvey_run_seal_exists(experiment.output_dir):
            validate_harvey_run_seal(experiment)
            raise ValueError("sealed Harvey runs are immutable")
        return HarveyStudyController(
            experiment,
            max_concurrency=args.max_concurrency,
        ).run_detection(resume=args.resume)
    return run_submission_detect(args)


def _add_submission_command(
    subparsers: argparse._SubParsersAction,
    name: str,
    handler: object,
    *,
    resumable: bool,
) -> None:
    parser = subparsers.add_parser(name, help=f"{name.title()} submission work.")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--max-concurrency", type=int, default=1)
    if resumable:
        parser.add_argument("--resume", action="store_true")
    parser.set_defaults(handler=_require_submission_experiment, submission_handler=handler)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_submission_command(
        subparsers,
        "seed",
        run_seed,
        resumable=False,
    )
    _add_submission_command(
        subparsers,
        "paraphrase",
        run_paraphrase,
        resumable=False,
    )
    _add_submission_command(
        subparsers,
        "revise",
        run_revise,
        resumable=True,
    )

    run = subparsers.add_parser("run", help="Run an experiment workflow.")
    run.add_argument("--experiment", required=True)
    run.add_argument("--max-concurrency", type=int, default=1)
    run.add_argument("--max-retries", type=int)
    continuation = run.add_mutually_exclusive_group()
    continuation.add_argument("--resume", action="store_true")
    continuation.add_argument("--restart", action="store_true")
    run.set_defaults(handler=_run)

    judge = subparsers.add_parser("judge", help="Run a sealed quality audit.")
    judge.add_argument("--experiment", required=True)
    judge.add_argument("--output-dir")
    judge.add_argument("--max-concurrency", type=int, default=3)
    judge.add_argument("--resume", action="store_true")
    judge.set_defaults(handler=_judge)

    detect = subparsers.add_parser("detect", help="Detect reward hacking.")
    detect.add_argument("--experiment", required=True)
    detect.add_argument("--study-dir")
    detect.add_argument("--max-concurrency", type=int, default=3)
    detect.add_argument("--resume", action="store_true")
    detect.set_defaults(handler=_detect)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
