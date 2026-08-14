#!/usr/bin/env python3
"""Run paper-faithful rubric-free pairwise judging on s000 versus final s010."""

from __future__ import annotations

import argparse

from rubric_gen.submission_revision.rubric_free import (
    RubricFreeConfig,
    RubricFreeRunner,
)
from rubric_gen.runtime.paths import resolve_project_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--max-concurrency", type=int, default=3)
    parser.add_argument("--max-retries", type=int, default=1)
    parser.add_argument("--resume", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return RubricFreeRunner(RubricFreeConfig(
        study_dir=resolve_project_path(args.study_dir),
        output_dir=resolve_project_path(args.output_dir),
        max_concurrency=args.max_concurrency,
        max_retries=args.max_retries,
        resume=args.resume,
    )).run()


if __name__ == "__main__":
    raise SystemExit(main())
