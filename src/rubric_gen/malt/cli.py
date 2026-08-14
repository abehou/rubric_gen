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

from rubric_gen.malt.cases import (
    MaltPrepareConfig,
    dataset_revision_from_inputs,
    input_fingerprints,
    inventory_malt,
    prepare_malt,
)
from rubric_gen.evidence.scoring import (
    score_panel,
)
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.study import resolve_study_experiment
from rubric_gen.runtime.paths import PROJECT_ROOT, resolve_project_path
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.vllm import (
    add_vllm_argument,
    parse_vllm_endpoints,
)
from rubric_gen.malt.model_judge import (
    DEFAULT_MAX_COMMAND_OUTPUT_CHARS,
    DEFAULT_MAX_EVENT_TEXT_CHARS,
    DEFAULT_MAX_COST_USD,
    DEFAULT_MAX_INPUT_TOKENS,
    MAX_OUTPUT_TOKENS,
    DIRECT_AUDIT_PROTOCOL_VERSION,
    STRONG_JUDGE_MODELS,
    ModelJudgeConfig,
    ModelJudgeRunner,
)
from rubric_gen.malt.detection import TARGETS, detection_target


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
    metrics["schema_version"] = 3
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


def _study_experiments(
    value: str,
) -> tuple[tuple[Path, ...], str, Path, dict[str, object]]:
    experiments: list[Path] = []
    source = resolve_project_path(value)
    study_path = source / "study.json"
    try:
        study = json.loads(study_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid randomized benchmark study: {source}") from exc
    if (
        study.get("schema_version") != 1
        or study.get("kind") != "rubric-gen-randomized-revision-study"
        or study.get("status") not in {"completed", "failed"}
        or type(study.get("experiment_path")) is not str
        or type(study.get("experiment_id")) is not str
        or type(study.get("seed_run_dir")) is not str
    ):
        raise ValueError(f"unsupported benchmark study: {source}")
    experiment_spec = load_experiment(Path(str(study["experiment_path"])))
    if study["experiment_id"] != experiment_spec.experiment_id:
        raise ValueError(f"benchmark study experiment ID changed: {source}")
    records = study.get("records")
    if not isinstance(records, list) or any(
        not isinstance(item, dict) for item in records
    ):
        raise ValueError(f"benchmark study has invalid records: {source}")
    assignments = {
        str(item["assignment_id"]): item for item in experiment_spec.assignments
    }
    record_ids = [str(record.get("assignment_id")) for record in records]
    if len(record_ids) != len(set(record_ids)) or set(record_ids) != set(assignments):
        raise ValueError(f"benchmark study ledger differs from its experiment: {source}")
    for record in records:
        status = record.get("status")
        assignment = assignments[str(record["assignment_id"])]
        experiment = resolve_study_experiment(source, record, assignment)
        if status not in {"completed", "failed", "invalid"}:
            raise ValueError(
                "benchmark study must reach a terminal boundary before audit: "
                f"{source}"
            )
        if status != "completed":
            continue
        experiments.append(experiment)
    resolved = tuple(path.resolve() for path in experiments)
    if len(set(resolved)) != len(resolved):
        raise ValueError("duplicate benchmark revision experiment")
    if not resolved:
        raise ValueError("benchmark study has no completed assignments to audit")
    return (
        resolved, experiment_spec.experiment_id,
        experiment_spec.tasks_dir.resolve(), experiment_spec.outcome_audit,
    )


def _run_study(args: argparse.Namespace, detection: str) -> int:
    if args.inputs:
        raise ValueError(
            "MALT shard inputs and --study-dir cannot be mixed"
        )
    if not args.ensemble and not args.vllm:
        raise ValueError(
            "--study-dir requires --ensemble or at least one --vllm"
        )
    if args.execution not in {None, "standard"}:
        raise ValueError(
            "--execution batch is available only for one hosted OpenAI --judge run"
        )
    if args.top is not None or args.negative_top is not None:
        raise ValueError(
            "--top and --negative-top are MALT dataset options and cannot "
            "be used with --study-dir"
        )
    dataset_only = {
        "benchmark_dir": args.benchmark_dir,
        "development_fraction": args.development_fraction,
        "validation_fraction": args.validation_fraction,
        "split_seed": args.split_seed,
        "seed": args.seed,
        "split": args.split,
    }
    supplied_dataset_only = {
        key: value for key, value in dataset_only.items() if value is not None
    }
    if supplied_dataset_only:
        raise ValueError(
            "MALT dataset options cannot be used with --study-dir: "
            + ", ".join(sorted(supplied_dataset_only))
        )
    base_urls = parse_vllm_endpoints(args.vllm or [])
    experiments, experiment_id, tasks_dir, audit = _study_experiments(
        args.study_dir
    )
    expected_models = tuple(audit.get("models", ()))
    models = tuple(base_urls) if base_urls else STRONG_JUDGE_MODELS
    if models != expected_models:
        raise ValueError(
            "selected detector models differ from experiment.yaml: "
            f"selected={models!r}, expected={expected_models!r}"
        )
    resolved_arguments = {
        "primary_rule": audit.get("primary_rule"),
        "max_retries": audit.get("max_retries"),
        "max_input_tokens": audit.get("max_input_tokens"),
        "max_output_tokens": audit.get("max_output_tokens"),
        "max_event_text_chars": audit.get("max_event_text_chars"),
        "max_command_output_chars": audit.get("max_command_output_chars"),
        "max_cost_usd": audit.get("max_cost_usd"),
        "execution": audit.get("execution"),
    }
    locked_arguments = {
        "primary_rule": args.primary_rule,
        "max_retries": args.max_retries,
        "max_input_tokens": args.max_input_tokens,
        "max_output_tokens": args.max_output_tokens,
        "max_event_text_chars": args.max_event_text_chars,
        "max_command_output_chars": args.max_command_output_chars,
        "max_cost_usd": args.max_cost_usd,
        "execution": args.execution,
    }
    conflicts = {
        key: value
        for key, value in locked_arguments.items()
        if value is not None and value != resolved_arguments[key]
    }
    if conflicts:
        raise ValueError(
            "Submission audit arguments differ from experiment.yaml: "
            f"requested={conflicts!r}, locked={resolved_arguments!r}"
        )
    primary_rule = str(resolved_arguments["primary_rule"])
    max_retries = int(resolved_arguments["max_retries"])
    max_input_tokens = int(resolved_arguments["max_input_tokens"])
    max_output_tokens = int(resolved_arguments["max_output_tokens"])
    max_event_text_chars = int(resolved_arguments["max_event_text_chars"])
    max_command_output_chars = int(
        resolved_arguments["max_command_output_chars"]
    )
    max_cost_usd = float(resolved_arguments["max_cost_usd"])
    execution = str(resolved_arguments["execution"])
    mode = "vllm" if base_urls else "ensemble"
    identity = (
        f"{mode}--detect-{detection}--source-{experiment_id}"
        f"--mc-{args.max_concurrency}"
        f"--mi-{max_input_tokens}--budget-{max_cost_usd:g}"
        f"--mo-{max_output_tokens}--me-{max_event_text_chars}"
        f"--mco-{max_command_output_chars}"
        f"--exec-{execution}--primary-{primary_rule}"
    )
    output_root = (
        resolve_project_path(args.output_dir)
        if args.output_dir is not None
        else _default_output_dir()
    )
    output_root.mkdir(parents=True, exist_ok=True)
    evaluation_root = _evaluation_root(output_root, identity, resume=args.resume)
    resume_evaluation = bool(args.resume and evaluation_root.is_dir())
    exit_code = ModelJudgeRunner(
        ModelJudgeConfig(
            case_dirs=(),
            revision_dirs=experiments,
            tasks_dir=tasks_dir,
            models=models,
            base_urls=base_urls,
            output_dir=evaluation_root,
            max_concurrency=args.max_concurrency,
            max_retries=max_retries,
            resume=resume_evaluation,
            detection=detection,
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
            max_event_text_chars=max_event_text_chars,
            max_command_output_chars=max_command_output_chars,
            max_cost_usd=max_cost_usd,
            execution=execution,
            primary_rule=primary_rule,
            experiment_ids=(experiment_id,),
        )
    ).run()
    print(
        "Wrote unscored benchmark forensic judgments: "
        f"{evaluation_root / 'summary.json'}"
    )
    return exit_code


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
        "--study-dir",
        default=None,
        help=(
            "Randomized benchmark study directory to audit instead of "
            "a labeled MALT dataset. Requires --ensemble or --vllm."
        ),
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
    add_vllm_argument(mode)  # type: ignore[arg-type]
    parser.add_argument("--max-concurrency", type=int, default=3)
    parser.add_argument(
        "--max-input-tokens", type=int, default=None,
        help="Hard per-request input ceiling; submission studies load it from experiment.yaml.",
    )
    parser.add_argument(
        "--max-output-tokens", type=int, default=None,
        help="Hard per-request output ceiling; submission studies load it from experiment.yaml.",
    )
    parser.add_argument(
        "--max-event-text-chars", type=int, default=None,
        help="Per-event evidence cap; submission studies load it from experiment.yaml.",
    )
    parser.add_argument(
        "--max-command-output-chars", type=int, default=None,
        help=(
            "Per-command-output evidence cap; submission studies load this "
            "from experiment.yaml."
        ),
    )
    parser.add_argument(
        "--max-cost-usd", type=float, default=None,
        help="Hard total hosted-API budget; submission studies load it from experiment.yaml.",
    )
    parser.add_argument(
        "--execution", choices=("standard", "batch"), default=None,
        help="Use synchronous requests or the discounted OpenAI Batch API.",
    )
    parser.add_argument(
        "--primary-rule",
        choices=("majority", "any_detects", "unanimous_detects"),
        default=None,
        help="Configured ensemble rule; submission studies load it from experiment.yaml.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=None,
        help=(
            "Retry transient detection requests this many times. Permanent and "
            "quota errors are never retried. Defaults to 1 retry."
        ),
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
    if args.study_dir:
        return _run_study(args, target.name)
    args.development_fraction = (
        0.2 if args.development_fraction is None else args.development_fraction
    )
    args.validation_fraction = (
        0.1 if args.validation_fraction is None else args.validation_fraction
    )
    args.split_seed = "malt-v1" if args.split_seed is None else args.split_seed
    args.seed = 42 if args.seed is None else args.seed
    args.split = "development" if args.split is None else args.split
    args.max_input_tokens = (
        DEFAULT_MAX_INPUT_TOKENS
        if args.max_input_tokens is None else args.max_input_tokens
    )
    args.max_output_tokens = (
        MAX_OUTPUT_TOKENS
        if args.max_output_tokens is None else args.max_output_tokens
    )
    args.max_event_text_chars = (
        DEFAULT_MAX_EVENT_TEXT_CHARS
        if args.max_event_text_chars is None else args.max_event_text_chars
    )
    args.max_command_output_chars = (
        DEFAULT_MAX_COMMAND_OUTPUT_CHARS
        if args.max_command_output_chars is None
        else args.max_command_output_chars
    )
    args.max_cost_usd = (
        DEFAULT_MAX_COST_USD if args.max_cost_usd is None else args.max_cost_usd
    )
    args.execution = "standard" if args.execution is None else args.execution
    args.primary_rule = "majority" if args.primary_rule is None else args.primary_rule
    args.max_retries = 1 if args.max_retries is None else args.max_retries

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
        "schema_version": 2,
        "dataset_revision": dataset_revision,
        "inputs": fingerprints,
        "review_filter": "manually_reviewed_only",
    })
    (benchmark_root / "inventory.json").write_text(
        json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
    )
    selected_mode = bool(
        args.ensemble or args.judge or args.vllm
    )
    detection_root = benchmark_root / target.name
    cases_dir = detection_root / "cases"
    gold_path = detection_root / "private" / "gold.jsonl"
    preparation_path = detection_root / "private" / "preparation.json"
    preparation = {
        "schema_version": 2,
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
    base_urls: dict[str, str] = {}
    if args.ensemble:
        mode_name, agent_panel, models = "ensemble", None, STRONG_JUDGE_MODELS
    elif args.judge:
        assert args.judge
        safe_model = re.sub(r"[^A-Za-z0-9._-]+", "_", args.judge)
        mode_name, agent_panel, models = f"judge-{safe_model}", None, (args.judge,)
    else:
        assert args.vllm
        base_urls = parse_vllm_endpoints(args.vllm)
        models = tuple(base_urls)
        identity = "-".join(
            re.sub(r"[^A-Za-z0-9._-]+", "_", model) for model in models
        )
        mode_name = "vllm-" + identity
        agent_panel = None
    if args.execution == "batch" and (
        agent_panel is not None
        or models is None
        or len(models) != 1
        or not models[0].startswith("gpt-5.6-")
        or models[0] in base_urls
    ):
        raise ValueError(
            "--execution batch requires one hosted GPT-5.6 model selected with --judge"
        )
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
    evaluation_protocol = DIRECT_AUDIT_PROTOCOL_VERSION
    mode_name += (
        f"--split-seed-{safe_split_seed}"
        f"--dev-{args.development_fraction:g}"
        f"--val-{args.validation_fraction:g}"
        f"--mc-{args.max_concurrency}"
        f"--mi-{args.max_input_tokens}--budget-{args.max_cost_usd:g}"
        f"--mo-{args.max_output_tokens}--me-{args.max_event_text_chars}"
        f"--mco-{args.max_command_output_chars}"
        f"--exec-{args.execution}"
        f"--primary-{args.primary_rule}"
        f"--audit-v{evaluation_protocol}--data-{preparation_digest}"
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
    exit_code = ModelJudgeRunner(ModelJudgeConfig(
        case_dirs=case_dirs, models=models, output_dir=evaluation_root,
        max_concurrency=args.max_concurrency, resume=resume_evaluation,
        max_retries=args.max_retries,
        base_urls=base_urls,
        detection=target.name,
        dataset_provenance=preparation,
        max_input_tokens=args.max_input_tokens,
        max_output_tokens=args.max_output_tokens,
        max_event_text_chars=args.max_event_text_chars,
        max_command_output_chars=args.max_command_output_chars,
        max_cost_usd=args.max_cost_usd,
        execution=args.execution,
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
