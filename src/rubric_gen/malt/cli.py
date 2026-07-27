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
    inventory_malt,
    prepare_malt,
)
from rubric_gen.biomnibench.forensics.reward_hacking import (
    PANEL,
    RewardHackingAuditConfig,
    RewardHackingAuditRunner,
)
from rubric_gen.biomnibench.forensics.scoring import (
    score_panel,
)
from rubric_gen.biomnibench.utils.paths import PROJECT_ROOT, resolve_project_path
from rubric_gen.biomnibench.utils.serialization import write_json_atomic
from rubric_gen.malt.model_judge import (
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
    balanced: bool = False,
) -> tuple[Path, ...]:
    if balanced and top is None:
        raise ValueError("--balanced requires --top")
    if top is None:
        return case_dirs
    if top <= 0:
        raise ValueError("--top must be a positive integer")
    if top > len(case_dirs):
        raise ValueError(
            f"--top {top} exceeds the {len(case_dirs)} available {split} cases"
        )
    rng = random.Random(seed)
    if not balanced:
        return tuple(sorted(rng.sample(case_dirs, top)))
    if top % 2:
        raise ValueError("--balanced requires an even --top value")
    if gold_labels is None:
        raise ValueError("balanced sampling requires gold labels")
    missing = sorted(path.name for path in case_dirs if path.name not in gold_labels)
    if missing:
        raise ValueError(
            "balanced sampling has cases without gold labels: " + ", ".join(missing)
        )
    positives = tuple(path for path in case_dirs if gold_labels[path.name])
    negatives = tuple(path for path in case_dirs if not gold_labels[path.name])
    per_class = top // 2
    if len(positives) < per_class or len(negatives) < per_class:
        raise ValueError(
            f"--balanced --top {top} requires {per_class} positive and "
            f"{per_class} negative {split} cases, but only {len(positives)} "
            f"positive and {len(negatives)} negative cases are available"
        )
    return tuple(
        sorted(
            (*rng.sample(positives, per_class), *rng.sample(negatives, per_class))
        )
    )


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


def _biomnibench_experiments(values: list[list[str]]) -> tuple[Path, ...]:
    experiments: list[Path] = []
    for group in values:
        for value in group:
            source = resolve_project_path(value)
            batch_path = source / "batch.json"
            if batch_path.is_file():
                batch = json.loads(batch_path.read_text(encoding="utf-8"))
                if batch.get("kind") != "rubric-gen-submission-revision-batch":
                    raise ValueError(f"unsupported Biomni batch: {source}")
                raw = batch.get("experiment_dirs")
                if not isinstance(raw, list) or any(
                    not isinstance(item, str) for item in raw
                ):
                    raise ValueError(f"Biomni batch has invalid experiment_dirs: {source}")
                for item in raw:
                    relative = Path(item)
                    if relative.is_absolute() or ".." in relative.parts:
                        raise ValueError(f"unsafe Biomni experiment path: {item!r}")
                    experiments.append(source / relative)
            else:
                experiments.append(source)
    resolved = tuple(path.resolve() for path in experiments)
    if len(set(resolved)) != len(resolved):
        raise ValueError("duplicate Biomni revision experiment")
    for experiment in resolved:
        try:
            manifest = json.loads(
                (experiment / "manifest.json").read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"invalid Biomni revision experiment: {experiment}") from exc
        if manifest.get("kind") != "rubric-gen-submission-revision-experiment":
            raise ValueError(f"unsupported Biomni revision experiment: {experiment}")
    return resolved


def _run_biomnibench(args: argparse.Namespace, detection: str) -> int:
    if args.inputs:
        raise ValueError(
            "MALT shard inputs and --biomnibench-run-dir cannot be mixed"
        )
    if not (args.agent_ensemble or args.ensemble):
        raise ValueError(
            "--biomnibench-run-dir requires --ensemble or --agent-ensemble"
        )
    if args.top is not None or args.balanced or args.split != "test":
        raise ValueError(
            "--top, --balanced, and --split are MALT dataset options and cannot "
            "be used with --biomnibench-run-dir"
        )
    experiments = _biomnibench_experiments(args.biomnibench_run_dir)
    identity_hash = hashlib.sha256(
        "\0".join(str(path) for path in experiments).encode()
    ).hexdigest()[:10]
    mode = "agent-ensemble" if args.agent_ensemble else "ensemble"
    identity = (
        f"{mode}--detect-{detection}--source-biomnibench-{identity_hash}"
        f"--mc-{args.max_concurrency}--raw-{int(args.raw)}"
    )
    identity += "--cat-" + re.sub(r"[^A-Za-z0-9._-]+", "_", args.category_model)
    if args.agent_ensemble:
        identity += f"--steps-{args.agent_step_limit}"
    output_root = (
        resolve_project_path(args.output_dir)
        if args.output_dir is not None
        else _default_output_dir()
    )
    output_root.mkdir(parents=True, exist_ok=True)
    evaluation_root = _evaluation_root(output_root, identity, resume=args.resume)
    tasks_dir = resolve_project_path(args.tasks_dir)
    if args.agent_ensemble:
        exit_code = RewardHackingAuditRunner(
            RewardHackingAuditConfig(
                experiment_dirs=experiments,
                output_dir=evaluation_root,
                tasks_dir=tasks_dir,
                panel=PANEL,
                max_concurrency=args.max_concurrency,
                max_retries=args.max_retries,
                step_limit=args.agent_step_limit,
                resume=args.resume,
                raw=args.raw,
                detection=detection,
                category_model=args.category_model,
            )
        ).run()
    else:
        exit_code = ModelJudgeRunner(
            ModelJudgeConfig(
                case_dirs=(),
                revision_dirs=experiments,
                tasks_dir=tasks_dir,
                models=STRONG_JUDGE_MODELS,
                output_dir=evaluation_root,
                max_concurrency=args.max_concurrency,
                max_retries=args.max_retries,
                resume=args.resume,
                detection=detection,
                category_model=args.category_model,
            )
        ).run()
    print(f"Wrote unscored Biomni forensic judgments: {evaluation_root / 'summary.json'}")
    return exit_code


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect, prepare, run, and score a MALT behavior benchmark."
    )
    parser.add_argument(
        "inputs", nargs="*",
        help=("One MALT configuration's shards. Defaults to "
              "data/malt-public/default/*.parquet."),
    )
    parser.add_argument(
        "--biomnibench-run-dir",
        action="append",
        nargs="+",
        default=[],
        help=(
            "Biomni revision experiment or batch directories to audit instead of "
            "a labeled MALT dataset. May be repeated. Requires --ensemble or "
            "--agent-ensemble."
        ),
    )
    parser.add_argument(
        "--tasks-dir",
        default="data/biomnibench-da",
        help="Biomni task root used with --biomnibench-run-dir.",
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
    parser.add_argument("--development-fraction", type=float, default=0.2)
    parser.add_argument("--validation-fraction", type=float, default=0.1)
    parser.add_argument("--split-seed", default="malt-v1")
    parser.add_argument(
        "--top", type=int, metavar="K",
        help="Randomly sample exactly K cases after selecting the split.",
    )
    parser.add_argument(
        "--seed", type=int, default=42,
        help="Random seed used by --top. Defaults to 42.",
    )
    parser.add_argument(
        "--balanced",
        action="store_true",
        help=(
            "Draw equal positive and negative classes. Requires an even --top; "
            "for example, --balanced --top 100 draws 50 of each."
        ),
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--agent-ensemble", action="store_true",
                      help="Run Codex, Claude Code, and Gemini CLI judges.")
    mode.add_argument("--ensemble", action="store_true",
                      help="Run the three direct strong-model judges.")
    mode.add_argument("--agent", choices=tuple(provider for provider, _ in PANEL),
                      help="Run one terminal-agent judge.")
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
        "--vllm-endpoint-dir", default="runs/vllm-endpoints",
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
        "--category-model",
        default="gpt-5.6-sol",
        help="Model used only to induce post-hoc finding categories.",
    )
    parser.add_argument(
        "--max-retries",
        type=int,
        default=2,
        help=(
            "Retry each failed detection member this many times. Defaults to 2 "
            "retries (3 total attempts)."
        ),
    )
    parser.add_argument(
        "--agent-step-limit",
        type=int,
        default=24,
        help=(
            "Maximum completed investigative tool actions per agent-ensemble "
            "member. Defaults to 24."
        ),
    )
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--raw", action="store_true")
    parser.add_argument(
        "--split", choices=("development", "validation", "test", "all"),
        default="test", help="Split evaluated and scored. Defaults to test.",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    target = detection_target(args.detect)
    if args.biomnibench_run_dir:
        return _run_biomnibench(args, target.name)

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
            resolve_project_path("data/malt-public/default").glob("*.parquet")
        ))
    )
    if not inputs:
        raise FileNotFoundError(
            "no default MALT shards found under data/malt-public/default"
        )
    benchmark_root = (
        resolve_project_path(args.benchmark_dir)
        if args.benchmark_dir is not None
        else _default_benchmark_dir()
    )
    benchmark_root.mkdir(parents=True, exist_ok=True)
    inventory = inventory_malt(inputs, show_progress=True)
    (benchmark_root / "inventory.json").write_text(
        json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
    )
    selected_mode = bool(
        args.agent_ensemble or args.ensemble or args.agent or args.judge
        or args.vllm or args.vllm_judge or args.vllm_ensemble
    )
    detection_root = benchmark_root / target.name
    cases_dir = detection_root / "cases"
    gold_path = detection_root / "private" / "gold.jsonl"
    preparation_path = detection_root / "private" / "preparation.json"
    preparation = {
        "inputs": [str(path) for path in inputs],
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
        balanced=args.balanced,
    )
    base_urls: dict[str, str] = {}
    if args.agent_ensemble:
        mode_name, agent_panel, models = "agent-ensemble", PANEL, None
    elif args.agent:
        member = next(item for item in PANEL if item[0] == args.agent)
        mode_name, agent_panel, models = f"agent-{args.agent}", (member,), None
    elif args.ensemble:
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
    mode_name += f"--detect-{target.name}--split-{args.split}"
    if args.top is not None:
        mode_name += f"--top-{args.top}--seed-{args.seed}"
    else:
        mode_name += "--top-all"
    if args.balanced:
        mode_name += "--balanced"
    safe_split_seed = re.sub(r"[^A-Za-z0-9._-]+", "_", args.split_seed)
    mode_name += (
        f"--split-seed-{safe_split_seed}"
        f"--dev-{args.development_fraction:g}"
        f"--val-{args.validation_fraction:g}"
        f"--mc-{args.max_concurrency}--raw-{int(args.raw)}"
    )
    if agent_panel is not None:
        mode_name += f"--steps-{args.agent_step_limit}"
    mode_name += "--cat-" + re.sub(
        r"[^A-Za-z0-9._-]+", "_", args.category_model
    )
    output_root = (
        resolve_project_path(args.output_dir)
        if args.output_dir is not None
        else _default_output_dir()
    )
    output_root.mkdir(parents=True, exist_ok=True)
    evaluation_root = _evaluation_root(output_root, mode_name, resume=args.resume)
    if agent_panel is not None:
        exit_code = RewardHackingAuditRunner(RewardHackingAuditConfig(
            experiment_dirs=(), case_dirs=case_dirs, output_dir=evaluation_root,
            tasks_dir=resolve_project_path("data/biomnibench-da"), panel=agent_panel,
            max_concurrency=args.max_concurrency, resume=args.resume, raw=args.raw,
            max_retries=args.max_retries,
            step_limit=args.agent_step_limit,
            detection=target.name,
            category_model=args.category_model,
        )).run()
    else:
        assert models is not None
        exit_code = ModelJudgeRunner(ModelJudgeConfig(
            case_dirs=case_dirs, models=models, output_dir=evaluation_root,
            max_concurrency=args.max_concurrency, resume=args.resume,
            max_retries=args.max_retries,
            base_urls=base_urls,
            detection=target.name,
            category_model=args.category_model,
        )).run()
    metrics = score_panel(
        evaluation_root / "summary.json", gold_path,
        split=None if args.split == "all" else args.split,
        detection=target.name,
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
