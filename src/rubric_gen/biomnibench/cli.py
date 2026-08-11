"""Seed, revise, and evaluate BiomniBench submissions."""

from __future__ import annotations

import argparse

from rubric_gen.biomnibench.commands import (
    run_detect,
    run_dag,
    run_judge,
    run_revise,
    run_seed,
)
from rubric_gen.biomnibench.vllm import add_vllm_argument


def _add_seed(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("seed", help="Seed submission work.")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    add_vllm_argument(parser)
    parser.set_defaults(handler=run_seed)


def _add_revise(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("revise", help="Revise submissions over rounds.")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    add_vllm_argument(parser)
    parser.set_defaults(handler=run_revise)


def _add_detect(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "detect", help="Detect reward hacking in completed revisions."
    )
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-concurrency", type=int, default=3)
    parser.add_argument("--resume", action="store_true")
    add_vllm_argument(parser)
    parser.set_defaults(handler=run_detect)


def _add_judge(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "judge",
        help=(
            "Re-score initial and final submissions against the original rubric "
            "with the strong ensemble."
        ),
    )
    parser.add_argument("--study-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-concurrency", type=int, default=3)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.set_defaults(handler=run_judge)


def _add_run(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("run", help="Run the experiment DAG.")
    parser.add_argument("--experiment", required=True)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    add_vllm_argument(parser)
    parser.set_defaults(handler=run_dag)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_seed(subparsers)
    _add_revise(subparsers)
    _add_detect(subparsers)
    _add_judge(subparsers)
    _add_run(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
