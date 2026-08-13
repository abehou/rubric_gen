"""Run Harvey LAB harness-evolution experiments and sealed audits."""

from __future__ import annotations

import argparse
from pathlib import Path

from rubric_gen.harvey.audits import run_quality_audit, run_reward_hacking_audit
from rubric_gen.harvey.config import load_experiment
from rubric_gen.harvey.controller import HarveyEvolutionController


def _run(args: argparse.Namespace) -> int:
    return HarveyEvolutionController(load_experiment(Path(args.experiment))).run(
        resume=args.resume
    )


def _judge(args: argparse.Namespace) -> int:
    return run_quality_audit(load_experiment(Path(args.experiment)))


def _detect(args: argparse.Namespace) -> int:
    return run_reward_hacking_audit(
        load_experiment(Path(args.experiment)), resume=args.resume
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    run = subparsers.add_parser("run", help="Evolve and evaluate Harvey harnesses.")
    run.add_argument("--experiment", required=True)
    run.add_argument("--resume", action="store_true")
    run.set_defaults(handler=_run)
    judge = subparsers.add_parser(
        "judge", help="Run sealed original-rubric and held-out-task audits."
    )
    judge.add_argument("--experiment", required=True)
    judge.set_defaults(handler=_judge)
    detect = subparsers.add_parser(
        "detect", help="Detect reward hacking in accepted harness proposals."
    )
    detect.add_argument("--experiment", required=True)
    detect.add_argument("--resume", action="store_true")
    detect.set_defaults(handler=_detect)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
