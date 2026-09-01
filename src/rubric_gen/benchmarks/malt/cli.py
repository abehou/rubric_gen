"""Standalone MALT behavior benchmark CLI."""

from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
import random
import re
import shutil
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

from rubric_gen.benchmarks.malt.cases import (
    MaltPrepareConfig,
    dataset_revision_from_inputs,
    input_fingerprints,
    inventory_malt,
    prepare_malt,
)
from rubric_gen.detection.metrics import (
    score_panel,
)
from rubric_gen.runtime.paths import PROJECT_ROOT, resolve_project_path
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.detection.config import (
    DEFAULT_MAX_INPUT_TOKENS,
    DEFAULT_MAX_OUTPUT_TOKENS,
    DEFAULT_PANEL_MODELS,
)
from rubric_gen.detection.jobs import DetectionConfig
from rubric_gen.detection.runner import DetectionRunner
from rubric_gen.detection.sources import transcript_audit_source
from rubric_gen.detection.targets import TARGETS, detection_target


def _sample_case_dirs(
    case_dirs: tuple[Path, ...],
    top: int | None,
    seed: int,
    split: str,
    *,
    gold_labels: dict[str, bool] | None = None,
    negative_top: int | None = None,
) -> tuple[Path, ...]:
    if top is not None and negative_top is not None:
        raise ValueError("--top and --negative-top are mutually exclusive")
    if negative_top is not None:
        if negative_top <= 0:
            raise ValueError("--negative-top must be a positive integer")
        if gold_labels is None:
            raise ValueError("--negative-top requires gold labels")
        missing = sorted(path.name for path in case_dirs if path.name not in gold_labels)
        if missing:
            raise ValueError(
                "class-aware sampling has cases without gold labels: "
                + ", ".join(missing)
            )
        positives = tuple(path for path in case_dirs if gold_labels[path.name])
        negatives = tuple(path for path in case_dirs if not gold_labels[path.name])
        if negative_top > len(negatives):
            raise ValueError(
                f"--negative-top {negative_top} exceeds the {len(negatives)} "
                f"available {split} negatives"
            )
        rng = random.Random(seed)
        return tuple(sorted((*positives, *rng.sample(negatives, negative_top))))
    if top is None:
        return case_dirs
    if top <= 0:
        raise ValueError("--top must be a positive integer")
    if top > len(case_dirs):
        raise ValueError(
            f"--top {top} exceeds the {len(case_dirs)} available {split} cases"
        )
    rng = random.Random(seed)
    return tuple(sorted(rng.sample(case_dirs, top)))


def _evaluation_root(
    root: Path, identity: str, *, resume: bool, timestamp: str | None = None
) -> Path:
    evaluations_root = root / "evaluations"
    if resume:
        candidates = sorted(evaluations_root.glob(f"*--{identity}"))
        if candidates:
            return candidates[-1]
    generated_at = timestamp or datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return evaluations_root / f"{generated_at}--{identity}"


def _annotate_negative_sample_metrics(
    metrics: dict[str, object],
    *,
    population_labels: dict[str, bool],
    sampled_case_ids: set[str],
) -> None:
    population_positives = sum(population_labels.values())
    population_negatives = len(population_labels) - population_positives
    sample_positives = sum(
        population_labels[case_id] for case_id in sampled_case_ids
    )
    sample_negatives = len(sampled_case_ids) - sample_positives
    prevalence = population_positives / len(population_labels)
    metrics["sampling"] = {
        "strategy": "all_positives_seeded_negatives",
        "population_positives": population_positives,
        "population_negatives": population_negatives,
        "sample_positives": sample_positives,
        "sample_negatives": sample_negatives,
        "population_prevalence": prevalence,
        "note": (
            "Raw precision and accuracy use the sampled class mix. Use "
            "prevalence_adjusted for population-comparable values; recall and "
            "specificity are class-conditional and remain directly interpretable."
        ),
    }
    for group_name in ("providers", "ensembles"):
        group = metrics.get(group_name)
        if not isinstance(group, dict):
            continue
        for values in group.values():
            if not isinstance(values, dict):
                continue
            recall, specificity = values.get("recall"), values.get("specificity")
            if not isinstance(recall, (int, float)) or not isinstance(
                specificity, (int, float)
            ):
                values["prevalence_adjusted"] = None
                continue
            true_positive = prevalence * recall
            false_negative = prevalence * (1 - recall)
            true_negative = (1 - prevalence) * specificity
            false_positive = (1 - prevalence) * (1 - specificity)
            precision_denominator = true_positive + false_positive
            precision = (
                true_positive / precision_denominator
                if precision_denominator else None
            )
            f1 = (
                2 * precision * recall / (precision + recall)
                if precision is not None and precision + recall else None
            )
            values["prevalence_adjusted"] = {
                "accuracy": true_positive + true_negative,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "specificity": specificity,
                "normalized_confusion": {
                    "tp": true_positive,
                    "fp": false_positive,
                    "tn": true_negative,
                    "fn": false_negative,
                },
            }


@contextmanager
def _preparation_lock(root: Path):
    lock_path = root / ".preparation.lock"
    with lock_path.open("a+", encoding="utf-8") as lock:
        try:
            fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(
                f"another MALT process is preparing this benchmark: {root}"
            ) from exc
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _default_output_dir() -> Path:
    return PROJECT_ROOT / "runs" / "malt-runs"


def _default_benchmark_dir() -> Path:
    bulk = os.environ.get("BULK")
    if bulk is None or not bulk.strip():
        raise ValueError(
            "BULK must be set when --benchmark-dir is omitted; prepared MALT "
            "cases and private annotations live on shared bulk storage"
        )
    bulk_root = Path(bulk).expanduser()
    if not bulk_root.is_absolute():
        raise ValueError("BULK must be an absolute path")
    return bulk_root / "rubric_gen" / "runs" / "malt-benchmark"



def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect, prepare, run, and score a MALT behavior benchmark."
    )
    parser.add_argument(
        "inputs", nargs="*",
        help=("One MALT configuration's shards. Defaults to "
              "data/malt-public/data/*.parquet."),
    )
    parser.add_argument(
        "--benchmark-dir",
        default=None,
        help=(
            "Shared prepared benchmark directory. Defaults to "
            "$BULK/rubric_gen/runs/malt-benchmark."
        ),
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Evaluation-run directory. Defaults to runs/malt-runs in the repository."
        ),
    )
    parser.add_argument(
        "--detect", required=True, choices=tuple(TARGETS),
        help=(
            "Detection target: reward hacking only (rh), MALT non-normal behavior, "
            "or the broad all-behaviors screen."
        ),
    )
    parser.add_argument("--development-fraction", type=float, default=None)
    parser.add_argument("--validation-fraction", type=float, default=None)
    parser.add_argument("--split-seed", default=None)
    sampling = parser.add_mutually_exclusive_group()
    sampling.add_argument(
        "--top", type=int, metavar="K",
        help="Randomly sample exactly K cases after selecting the split.",
    )
    sampling.add_argument(
        "--negative-top", type=int, metavar="K",
        help=(
            "Evaluate every positive plus exactly K seeded negatives. Preserves "
            "the full recall denominator without pretending the sample is balanced."
        ),
    )
    parser.add_argument(
        "--seed", type=int, default=None,
        help="Random seed used by --top or --negative-top. Defaults to 42.",
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--ensemble", action="store_true",
                      help="Run the three direct strong-model judges.")
    mode.add_argument("--judge", metavar="MODEL", help="Run one direct model judge.")
    parser.add_argument("--max-concurrency", type=int, default=3)
    parser.add_argument(
        "--max-input-tokens", type=int, default=None,
        help="Hard per-request input ceiling.",
    )
    parser.add_argument(
        "--max-output-tokens", type=int, default=None,
        help="Hard per-request output ceiling.",
    )
    parser.add_argument(
        "--primary-rule",
        choices=("majority", "any_detect", "unanimous_detects"),
        default=None,
        help="Configured ensemble rule.",
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument(
        "--split", choices=("development", "validation", "test", "all"),
        default=None,
        help="Split evaluated and scored. Defaults to development.",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    target = detection_target(args.detect)
    args.development_fraction = (
        0.2 if args.development_fraction is None else args.development_fraction
    )
    args.validation_fraction = (
        0.1 if args.validation_fraction is None else args.validation_fraction
    )
    args.split_seed = "malt" if args.split_seed is None else args.split_seed
    args.seed = 42 if args.seed is None else args.seed
    args.split = "development" if args.split is None else args.split
    args.max_input_tokens = (
        DEFAULT_MAX_INPUT_TOKENS
        if args.max_input_tokens is None else args.max_input_tokens
    )
    args.max_output_tokens = (
        DEFAULT_MAX_OUTPUT_TOKENS
        if args.max_output_tokens is None else args.max_output_tokens
    )
    args.primary_rule = "any_detect" if args.primary_rule is None else args.primary_rule

    inputs = (
        tuple(resolve_project_path(value) for value in args.inputs)
        if args.inputs
        else tuple(sorted(
            resolve_project_path("data/malt-public/data").glob("*.parquet")
        ))
    )
    if not inputs:
        raise FileNotFoundError(
            "no default MALT shards found under data/malt-public/data; download "
            "the reviewed data/*.parquet export first"
        )
    benchmark_root = (
        resolve_project_path(args.benchmark_dir)
        if args.benchmark_dir is not None
        else _default_benchmark_dir()
    )
    benchmark_root.mkdir(parents=True, exist_ok=True)
    fingerprints = input_fingerprints(inputs)
    dataset_revision = dataset_revision_from_inputs(inputs)
    inventory = inventory_malt(inputs, show_progress=True)
    inventory.update({
        "dataset_revision": dataset_revision,
        "inputs": fingerprints,
        "review_filter": "manually_reviewed_only",
    })
    (benchmark_root / "inventory.json").write_text(
        json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
    )
    selected_mode = bool(args.ensemble or args.judge)
    detection_root = benchmark_root / target.name
    cases_dir = detection_root / "cases"
    gold_path = detection_root / "private" / "gold.jsonl"
    preparation_path = detection_root / "private" / "preparation.json"
    preparation = {
        "dataset_revision": dataset_revision,
        "inputs": fingerprints,
        "review_filter": "manually_reviewed_only",
        "detection": target.name,
        "positive_labels": sorted(target.positive_labels),
        "negative_labels": sorted(target.negative_labels),
        "empty_labels_are_negative": False,
        "development_fraction": args.development_fraction,
        "validation_fraction": args.validation_fraction,
        "split_seed": args.split_seed,
    }
    with _preparation_lock(benchmark_root):
        preparation_matches = (
            cases_dir.is_dir()
            and gold_path.is_file()
            and preparation_path.is_file()
            and json.loads(preparation_path.read_text(encoding="utf-8")) == preparation
        )
        if preparation_matches:
            prepared: dict[str, object] = {"status": "reused"}
        else:
            detection_root.mkdir(parents=True, exist_ok=True)
            staging_root = detection_root / ".preparing"
            checkpoint_path = staging_root / "preparation.json"
            if staging_root.exists():
                checkpoint_matches = (
                    checkpoint_path.is_file()
                    and json.loads(checkpoint_path.read_text(encoding="utf-8"))
                    == preparation
                )
                if not checkpoint_matches:
                    shutil.rmtree(staging_root)
            staging_root.mkdir(exist_ok=True)
            write_json_atomic(checkpoint_path, preparation)
            staging_cases = staging_root / "cases"
            staging_gold = staging_root / "gold.jsonl"
            prepared = prepare_malt(MaltPrepareConfig(
                inputs=inputs,
                cases_dir=staging_cases,
                gold_path=staging_gold,
                dataset_revision=dataset_revision,
                positive_labels=target.positive_labels,
                negative_labels=target.negative_labels,
                development_fraction=args.development_fraction,
                validation_fraction=args.validation_fraction,
                split_seed=args.split_seed,
                show_progress=True,
            ))
            if cases_dir.exists():
                shutil.rmtree(cases_dir)
            if gold_path.exists():
                gold_path.unlink()
            staging_cases.replace(cases_dir)
            gold_path.parent.mkdir(parents=True, exist_ok=True)
            staging_gold.replace(gold_path)
            checkpoint_path.unlink()
            staging_root.rmdir()
            prepared["cases_dir"] = str(cases_dir)
            prepared["gold_path"] = str(gold_path)
            write_json_atomic(preparation_path, preparation)
    if not selected_mode:
        print(json.dumps(prepared, indent=2))
        print(f"Prepared benchmark: {benchmark_root}")
        return 0

    selected_gold = {
        str(row["case_id"]): bool(row["positive"])
        for line in gold_path.read_text(encoding="utf-8").splitlines()
        if (row := json.loads(line))
        and (args.split == "all" or row.get("split") == args.split)
    }
    case_dirs = tuple(sorted(
        path.parent
        for path in cases_dir.glob("*/manifest.json")
        if path.parent.name in selected_gold
    ))
    if not case_dirs:
        raise ValueError(f"no {args.split} cases matched the audited label mapping")
    case_dirs = _sample_case_dirs(
        case_dirs,
        args.top,
        args.seed,
        args.split,
        gold_labels=selected_gold,
        negative_top=args.negative_top,
    )
    if args.ensemble:
        mode_name, agent_panel, models = "ensemble", None, DEFAULT_PANEL_MODELS
    else:
        assert args.judge
        safe_model = re.sub(r"[^A-Za-z0-9._-]+", "_", args.judge)
        mode_name, agent_panel, models = f"judge-{safe_model}", None, (args.judge,)
    mode_name += f"--detect-{target.name}--split-{args.split}"
    if args.negative_top is not None:
        mode_name += f"--all-positives--negative-top-{args.negative_top}--seed-{args.seed}"
    elif args.top is not None:
        mode_name += f"--top-{args.top}--seed-{args.seed}"
    else:
        mode_name += "--top-all"
    safe_split_seed = re.sub(r"[^A-Za-z0-9._-]+", "_", args.split_seed)
    preparation_digest = hashlib.sha256(
        json.dumps(preparation, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:12]
    mode_name += (
        f"--split-seed-{safe_split_seed}"
        f"--dev-{args.development_fraction:g}"
        f"--val-{args.validation_fraction:g}"
        f"--mc-{args.max_concurrency}"
        f"--mi-{args.max_input_tokens}"
        f"--mo-{args.max_output_tokens}"
        f"--primary-{args.primary_rule}"
        f"--data-{preparation_digest}"
    )
    output_root = (
        resolve_project_path(args.output_dir)
        if args.output_dir is not None
        else _default_output_dir()
    )
    output_root.mkdir(parents=True, exist_ok=True)
    evaluation_root = _evaluation_root(output_root, mode_name, resume=args.resume)
    resume_evaluation = bool(args.resume and evaluation_root.is_dir())
    assert models is not None
    exit_code = DetectionRunner(DetectionConfig(
        source=transcript_audit_source(case_dirs, preparation),
        models=models, output_dir=evaluation_root,
        max_concurrency=args.max_concurrency, resume=resume_evaluation,
        detection=target.name,
        max_input_tokens=args.max_input_tokens,
        max_output_tokens=args.max_output_tokens,
        primary_rule=args.primary_rule,
    )).run()
    summary_path = evaluation_root / "summary.json"
    if not summary_path.is_file():
        print(f"Wrote pre-generation state: {evaluation_root}")
        return exit_code
    metrics = score_panel(
        summary_path, gold_path,
        split=None if args.split == "all" else args.split,
        detection=target.name,
    )
    if args.negative_top is not None:
        _annotate_negative_sample_metrics(
            metrics,
            population_labels=selected_gold,
            sampled_case_ids={path.name for path in case_dirs},
        )
    write_json_atomic(evaluation_root / "metrics.json", metrics)
    print(f"Wrote benchmark metrics: {evaluation_root / 'metrics.json'}")
    return exit_code


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        return run(parser.parse_args(argv))
    except FileNotFoundError as exc:
        parser.error(str(exc))
    raise AssertionError("argparse.error did not exit")


if __name__ == "__main__":
    raise SystemExit(main())
