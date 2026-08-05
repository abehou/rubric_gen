"""Seed, revise, and evaluate BiomniBench submissions."""

from __future__ import annotations

import argparse

from rubric_gen.biomnibench.commands import (
    run_detect,
    run_judge_quality,
    run_revise,
    run_seed,
)


def _add_seed(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("seed", help="Seed submission work.")
    parser.add_argument("--design", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.set_defaults(handler=run_seed)


def _add_revise(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser("revise", help="Revise submissions over rounds.")
    parser.add_argument("--design", required=True)
    parser.add_argument("--seed-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-concurrency", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    parser.set_defaults(handler=run_revise)


def _add_detect(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "detect", help="Detect reward hacking in completed revisions."
    )
    parser.add_argument("--run-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-concurrency", type=int, default=3)
    parser.add_argument("--resume", action="store_true")
    parser.set_defaults(handler=run_detect)


def _add_judge(subparsers: argparse._SubParsersAction) -> None:
    parser = subparsers.add_parser(
        "judge", help="Judge final revision quality without a rubric."
    )
    parser.add_argument("--run-dir", action="append", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument(
        "--models",
        nargs=3,
        default=("gpt-5.6-sol", "claude-opus-4-8", "gemini-3.1-pro-preview"),
        metavar=("OPENAI", "CLAUDE", "GEMINI"),
    )
    parser.add_argument("--max-concurrency", type=int, default=3)
    parser.add_argument("--max-retries", type=int, default=2)
    parser.add_argument("--resume", action="store_true")
    parser.set_defaults(handler=run_judge_quality)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    _add_seed(subparsers)
    _add_revise(subparsers)
    _add_detect(subparsers)
    _add_judge(subparsers)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.handler(args)


if __name__ == "__main__":
    raise SystemExit(main())
