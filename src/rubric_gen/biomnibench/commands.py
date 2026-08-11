"""Handlers for the BiomniBench experiment DAG."""

from __future__ import annotations

import argparse
from pathlib import Path

from rubric_gen.biomnibench.experiment import load_experiment
from rubric_gen.biomnibench.revision.seeds import SeedSetConfig, SeedSetRunner
from rubric_gen.biomnibench.study import StudyRunConfig, StudyRunner
from rubric_gen.biomnibench.utils.paths import resolve_project_path
from rubric_gen.biomnibench.vllm import parse_vllm_endpoints


def run_seed(args: argparse.Namespace) -> int:
    experiment = load_experiment(resolve_project_path(args.experiment))
    endpoints = parse_vllm_endpoints(getattr(args, "vllm", []))
    return SeedSetRunner(SeedSetConfig(
        experiment=experiment,
        output_dir=Path(str(experiment.dag["seed"]["output_dir"])),
        max_concurrency=args.max_concurrency,
        resume=args.resume,
        vllm_endpoints=endpoints,
    )).run()


def run_revise(args: argparse.Namespace) -> int:
    experiment = load_experiment(resolve_project_path(args.experiment))
    endpoints = parse_vllm_endpoints(getattr(args, "vllm", []))
    return StudyRunner(StudyRunConfig(
        experiment=experiment,
        seed_run_dir=Path(str(experiment.dag["seed"]["output_dir"])),
        output_dir=Path(str(experiment.dag["revise"]["output_dir"])),
        max_concurrency=args.max_concurrency,
        resume=args.resume,
        vllm_endpoints=endpoints,
    )).run()


def run_detect(args: argparse.Namespace) -> int:
    from rubric_gen.malt.cli import main as malt_main

    argv = [
        "--detect", "rh",
        "--biomnibench-study-dir", args.run_dir,
        "--output-dir", args.output_dir,
        "--max-concurrency", str(args.max_concurrency),
    ]
    endpoints = parse_vllm_endpoints(getattr(args, "vllm", []))
    if endpoints:
        for model, url in endpoints.items():
            argv.extend(["--vllm", f"{url}::{model}"])
    else:
        argv.append("--ensemble")
    if args.resume:
        argv.append("--resume")
    return malt_main(argv)


def run_dag(args: argparse.Namespace) -> int:
    experiment = load_experiment(resolve_project_path(args.experiment))
    common = argparse.Namespace(
        experiment=str(experiment.path),
        max_concurrency=args.max_concurrency,
        resume=args.resume,
        vllm=getattr(args, "vllm", []),
    )
    if run_seed(common):
        return 1
    if run_revise(common):
        return 1
    detect = argparse.Namespace(
        run_dir=str(experiment.dag["revise"]["output_dir"]),
        output_dir=str(experiment.dag["detect"]["output_dir"]),
        max_concurrency=min(args.max_concurrency, 3),
        resume=args.resume,
        vllm=getattr(args, "vllm", []),
    )
    return run_detect(detect)


def run_judge(args: argparse.Namespace) -> int:
    from rubric_gen.biomnibench.revision.original_rubric import (
        OriginalRubricEnsembleConfig,
        OriginalRubricEnsembleRunner,
    )

    return OriginalRubricEnsembleRunner(OriginalRubricEnsembleConfig(
        study_dir=resolve_project_path(args.study_dir),
        output_dir=resolve_project_path(args.output_dir),
        max_concurrency=args.max_concurrency,
        max_retries=args.max_retries,
        resume=args.resume,
    )).run()
