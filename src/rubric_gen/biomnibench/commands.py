"""Handlers for the four BiomniBench workflow commands."""

from __future__ import annotations

import argparse

from rubric_gen.biomnibench.experiments import load_design, verify_runtime_provenance
from rubric_gen.biomnibench.revision.seeds import SeedSetConfig, SeedSetRunner
from rubric_gen.biomnibench.study import StudyRunConfig, StudyRunner
from rubric_gen.biomnibench.utils.paths import resolve_project_path


def run_seed(args: argparse.Namespace) -> int:
    design = load_design(resolve_project_path(args.design))
    verify_runtime_provenance(design)
    return SeedSetRunner(SeedSetConfig(
        design=design,
        output_dir=resolve_project_path(args.output_dir),
        max_concurrency=args.max_concurrency,
        resume=args.resume,
    )).run()


def run_revise(args: argparse.Namespace) -> int:
    design = load_design(resolve_project_path(args.design))
    return StudyRunner(StudyRunConfig(
        design=design,
        seed_run_dir=resolve_project_path(args.seed_dir),
        output_dir=resolve_project_path(args.output_dir),
        max_concurrency=args.max_concurrency,
        resume=args.resume,
    )).run()


def run_detect(args: argparse.Namespace) -> int:
    from rubric_gen.malt.cli import main as malt_main

    argv = [
        "--detect", "rh",
        "--biomnibench-study-dir", args.run_dir,
        "--ensemble",
        "--output-dir", args.output_dir,
        "--max-concurrency", str(args.max_concurrency),
    ]
    if args.resume:
        argv.append("--resume")
    return malt_main(argv)


def run_judge_quality(args: argparse.Namespace) -> int:
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
        resume=args.resume,
    )).run()
