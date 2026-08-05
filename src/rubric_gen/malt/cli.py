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
from urllib.parse import urlparse

from rubric_gen.biomnibench.forensics.malt import (
    MaltPrepareConfig,
    dataset_revision_from_inputs,
    input_fingerprints,
    inventory_malt,
    prepare_malt,
)
from rubric_gen.biomnibench.forensics.scoring import (
    score_panel,
)
from rubric_gen.biomnibench.experiments import load_design
from rubric_gen.biomnibench.study import (
    resolve_study_experiment,
    validate_completed_revision,
)
from rubric_gen.biomnibench.utils.provenance import require_clean_repository
from rubric_gen.biomnibench.utils.paths import PROJECT_ROOT, resolve_project_path
from rubric_gen.biomnibench.utils.serialization import write_json_atomic
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
        if not candidates:
            raise FileNotFoundError(f"no previous matching run to resume: {identity}")
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


def _biomnibench_experiments(
    value: str,
) -> tuple[tuple[Path, ...], str, Path, dict[str, object]]:
    experiments: list[Path] = []
    source = resolve_project_path(value)
    study_path = source / "study.json"
    try:
        study = json.loads(study_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid randomized Biomni study: {source}") from exc
    if (
        study.get("schema_version") != 1
        or study.get("kind") != "rubric-gen-randomized-revision-study"
        or type(study.get("design_sha256")) is not str
        or study.get("status") not in {"completed", "failed"}
        or type(study.get("design_path")) is not str
        or type(study.get("protocol_id")) is not str
        or type(study.get("seed_run_dir")) is not str
    ):
        raise ValueError(f"unsupported Biomni study: {source}")
    design = load_design(Path(str(study["design_path"])))
    if (
        design.sha256 != study["design_sha256"]
        or study["design_path"] != str(design.path)
        or study["protocol_id"] != design.protocol_id
    ):
        raise ValueError(f"Biomni study design identity changed: {source}")
    records = study.get("records")
    if not isinstance(records, list) or any(
        not isinstance(item, dict) for item in records
    ):
        raise ValueError(f"Biomni study has invalid records: {source}")
    assignments = {
        str(item["assignment_id"]): item for item in design.assignments
    }
    record_ids = [str(record.get("assignment_id")) for record in records]
    if len(record_ids) != len(set(record_ids)) or set(record_ids) != set(assignments):
        raise ValueError(f"Biomni study ledger differs from its design: {source}")
    seed_root = Path(str(study["seed_run_dir"]))
    for record in records:
        status = record.get("status")
        assignment = assignments[str(record["assignment_id"])]
        experiment = resolve_study_experiment(source, record, assignment)
        if status not in {"completed", "failed", "invalid"}:
            raise ValueError(
                f"Biomni study must reach a terminal boundary before audit: {source}"
            )
        if status != "completed":
            continue
        validate_completed_revision(
            experiment,
            assignment,
            design,
            seed_root,
        )
        experiments.append(experiment)
    resolved = tuple(path.resolve() for path in experiments)
    if len(set(resolved)) != len(resolved):
        raise ValueError("duplicate Biomni revision experiment")
    if not resolved:
        raise ValueError("Biomni study has no completed assignments to audit")
    return resolved, design.sha256, design.tasks_dir.resolve(), design.outcome_audit


def _run_biomnibench(args: argparse.Namespace, detection: str) -> int:
    if args.inputs:
        raise ValueError(
            "MALT shard inputs and --biomnibench-study-dir cannot be mixed"
        )
    if not args.ensemble:
        raise ValueError("--biomnibench-study-dir requires --ensemble")
    if args.execution not in {None, "standard"}:
        raise ValueError(
            "--execution batch is available only for one hosted OpenAI --judge run"
        )
    if args.top is not None or args.negative_top is not None:
        raise ValueError(
            "--top and --negative-top are MALT dataset options and cannot "
            "be used with --biomnibench-study-dir"
        )
    dataset_only = {
        "benchmark_dir": args.benchmark_dir,
        "development_fraction": args.development_fraction,
        "validation_fraction": args.validation_fraction,
        "split_seed": args.split_seed,
        "seed": args.seed,
        "split": args.split,
        "vllm_endpoint_dir": args.vllm_endpoint_dir,
        "vllm_qwen_url": args.vllm_qwen_url,
        "vllm_glm_url": args.vllm_glm_url,
        "vllm_gpt_oss_url": args.vllm_gpt_oss_url,
    }
    supplied_dataset_only = {
        key: value for key, value in dataset_only.items() if value is not None
    }
    if supplied_dataset_only:
        raise ValueError(
            "MALT dataset options cannot be used with --biomnibench-study-dir: "
            + ", ".join(sorted(supplied_dataset_only))
        )
    experiments, design_sha256, tasks_dir, audit = _biomnibench_experiments(
        args.biomnibench_study_dir
    )
    if detection != "rh" or audit.get("detection") != "rh":
        raise ValueError("randomized Biomni studies support only the locked RH outcome")
    expected_models = tuple(audit.get("models", ()))
    if expected_models != STRONG_JUDGE_MODELS:
        raise ValueError("Biomni design uses an unsupported primary model panel")
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
            "Biomni audit arguments differ from the locked design: "
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
    require_clean_repository()
    identity_hash = hashlib.sha256(
        "\0".join(str(path) for path in experiments).encode()
    ).hexdigest()[:10]
    mode = "ensemble"
    identity = (
        f"{mode}--detect-{detection}--source-biomnibench-{identity_hash}"
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
    exit_code = ModelJudgeRunner(
        ModelJudgeConfig(
            case_dirs=(),
            revision_dirs=experiments,
            tasks_dir=tasks_dir,
            models=STRONG_JUDGE_MODELS,
            output_dir=evaluation_root,
            max_concurrency=args.max_concurrency,
            max_retries=max_retries,
            resume=args.resume,
            detection=detection,
            max_input_tokens=max_input_tokens,
            max_output_tokens=max_output_tokens,
            max_event_text_chars=max_event_text_chars,
            max_command_output_chars=max_command_output_chars,
            max_cost_usd=max_cost_usd,
            execution=execution,
            primary_rule=primary_rule,
            design_sha256s=(design_sha256,),
            preflight_only=args.preflight_only,
        )
    ).run()
    if args.preflight_only:
        print(f"Wrote Biomni cost preflight: {evaluation_root / 'cost-preflight.json'}")
    else:
        print(
            "Wrote unscored Biomni forensic judgments: "
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
        "--biomnibench-study-dir",
        dest="biomnibench_study_dir",
        default=None,
        help=(
            "Locked randomized Biomni study directories to audit instead of "
            "a labeled MALT dataset. Requires --ensemble."
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
        help="Detection target: reward hacking only (rh) or every non-normal label.",
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
    mode.add_argument(
        "--vllm", action="append", metavar="URL::MODEL",
        help=("Run an open-source judge through a vLLM OpenAI-compatible server. "
              "Repeat for a vLLM panel."),
    )
    mode.add_argument(
        "--vllm-judge", action="store_true",
        help="Run the default Qwen open-source judge on its default local vLLM URL.",
    )
    mode.add_argument(
        "--vllm-ensemble", action="store_true",
        help="Run the default three-model open-source vLLM panel.",
    )
    parser.add_argument(
        "--vllm-endpoint-dir", default=None,
        help=("Directory containing endpoints published by server jobs. "
              "Defaults to runs/vllm-endpoints."),
    )
    parser.add_argument(
        "--vllm-qwen-url", default=None,
        help="Override the dynamically discovered Qwen3.6 endpoint.",
    )
    parser.add_argument(
        "--vllm-glm-url", default=None,
        help="Override the dynamically discovered GLM-4.7-Flash endpoint.",
    )
    parser.add_argument(
        "--vllm-gpt-oss-url", default=None,
        help="Override the dynamically discovered gpt-oss-120b endpoint.",
    )
    parser.add_argument("--max-concurrency", type=int, default=3)
    parser.add_argument(
        "--max-input-tokens", type=int, default=None,
        help="Hard per-request input ceiling; Biomni studies load this from the design.",
    )
    parser.add_argument(
        "--max-output-tokens", type=int, default=None,
        help="Hard per-request output ceiling; Biomni studies load this from the design.",
    )
    parser.add_argument(
        "--max-event-text-chars", type=int, default=None,
        help="Per-event Biomni evidence cap; Biomni studies load this from the design.",
    )
    parser.add_argument(
        "--max-command-output-chars", type=int, default=None,
        help=(
            "Per-command-output Biomni evidence cap; Biomni studies load this "
            "from the design."
        ),
    )
    parser.add_argument(
        "--max-cost-usd", type=float, default=None,
        help="Hard total hosted-API budget; Biomni studies load this from the design.",
    )
    parser.add_argument(
        "--preflight-only",
        action="store_true",
        help="Write exact token/cost preflight and exit before model generation.",
    )
    parser.add_argument(
        "--execution", choices=("standard", "batch"), default=None,
        help="Use synchronous requests or the discounted OpenAI Batch API.",
    )
    parser.add_argument(
        "--primary-rule",
        choices=("majority", "any_detects", "unanimous_detects"),
        default=None,
        help="Prespecified ensemble rule; Biomni studies load this from the design.",
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
    if args.biomnibench_study_dir:
        return _run_biomnibench(args, target.name)
    args.development_fraction = (
        0.2 if args.development_fraction is None else args.development_fraction
    )
    args.validation_fraction = (
        0.1 if args.validation_fraction is None else args.validation_fraction
    )
    args.split_seed = "malt-v1" if args.split_seed is None else args.split_seed
    args.seed = 42 if args.seed is None else args.seed
    args.split = "development" if args.split is None else args.split
    args.vllm_endpoint_dir = (
        "runs/vllm-endpoints"
        if args.vllm_endpoint_dir is None
        else args.vllm_endpoint_dir
    )
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

    def vllm_url(value: str) -> str:
        normalized = value.rstrip("/")
        return normalized if normalized.endswith("/v1") else normalized + "/v1"

    def discovered_vllm_url(filename: str, override: str | None, model: str) -> str:
        if override is not None:
            return vllm_url(override)
        endpoint_path = resolve_project_path(args.vllm_endpoint_dir) / filename
        try:
            specification = endpoint_path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise FileNotFoundError(
                f"missing ready vLLM endpoint for {model}: {endpoint_path}; "
                "start the server jobs first or pass the corresponding URL override"
            ) from exc
        if "::" not in specification:
            raise ValueError(f"malformed vLLM endpoint file: {endpoint_path}")
        url, published_model = specification.rsplit("::", 1)
        if published_model != model:
            raise ValueError(
                f"vLLM endpoint model mismatch in {endpoint_path}: {published_model!r}"
            )
        return vllm_url(url)

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
        args.ensemble or args.judge
        or args.vllm or args.vllm_judge or args.vllm_ensemble
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
    elif args.vllm_judge:
        model = "Qwen/Qwen3.6-27B"
        mode_name, agent_panel, models = "vllm-judge-qwen3.6-27b", None, (model,)
        base_urls[model] = discovered_vllm_url(
            "qwen.endpoint", args.vllm_qwen_url, model
        )
    elif args.vllm_ensemble:
        defaults = (
            ("Qwen/Qwen3.6-27B", "qwen.endpoint", args.vllm_qwen_url),
            ("zai-org/GLM-4.7-Flash", "glm.endpoint", args.vllm_glm_url),
            ("openai/gpt-oss-120b", "gpt-oss.endpoint", args.vllm_gpt_oss_url),
        )
        mode_name, agent_panel, models = (
            "vllm-ensemble-default", None, tuple(model for model, _, _ in defaults)
        )
        base_urls.update(
            (model, discovered_vllm_url(filename, override, model))
            for model, filename, override in defaults
        )
    else:
        assert args.vllm
        parsed: list[tuple[str, str]] = []
        for specification in args.vllm:
            if "::" not in specification:
                raise ValueError("--vllm must use URL::MODEL")
            url, model = specification.rsplit("::", 1)
            if urlparse(url).scheme not in {"http", "https"} or not model:
                raise ValueError(f"invalid --vllm specification: {specification!r}")
            if model in base_urls:
                raise ValueError(f"duplicate vLLM model name: {model}")
            base_urls[model] = vllm_url(url)
            parsed.append((url, model))
        if len(parsed) not in {1, 3}:
            raise ValueError("--vllm requires exactly one server or a three-server panel")
        identity = "-".join(re.sub(r"[^A-Za-z0-9._-]+", "_", model) for _, model in parsed)
        mode_name = ("vllm-judge-" if len(parsed) == 1 else "vllm-ensemble-") + identity
        agent_panel, models = None, tuple(model for _, model in parsed)
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
    assert models is not None
    exit_code = ModelJudgeRunner(ModelJudgeConfig(
        case_dirs=case_dirs, models=models, output_dir=evaluation_root,
        max_concurrency=args.max_concurrency, resume=args.resume,
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
        preflight_only=args.preflight_only,
    )).run()
    summary_path = evaluation_root / "summary.json"
    if not summary_path.is_file():
        artifact = (
            evaluation_root / "cost-preflight.json"
            if args.preflight_only
            else evaluation_root
        )
        print(f"Wrote pre-generation state: {artifact}")
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
