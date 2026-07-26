"""Standalone MALT reward-hacking benchmark CLI."""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import random
import re
import shutil
import tempfile
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
from rubric_gen.biomnibench.forensics.scoring import score_panel
from rubric_gen.biomnibench.utils.paths import PROJECT_ROOT, resolve_project_path
from rubric_gen.biomnibench.utils.serialization import write_json_atomic
from rubric_gen.malt.model_judge import (
    STRONG_JUDGE_MODELS,
    ModelJudgeConfig,
    ModelJudgeRunner,
)


def _sample_case_dirs(
    case_dirs: tuple[Path, ...], top: int | None, seed: int, split: str
) -> tuple[Path, ...]:
    if top is None:
        return case_dirs
    if top <= 0:
        raise ValueError("--top must be a positive integer")
    if top > len(case_dirs):
        raise ValueError(
            f"--top {top} exceeds the {len(case_dirs)} available {split} cases"
        )
    return tuple(sorted(random.Random(seed).sample(case_dirs, top)))


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
    bulk = os.environ.get("BULK")
    if bulk is None or not bulk.strip():
        raise ValueError(
            "BULK must be set when --output-dir is omitted; MALT cases and "
            "evaluation transcripts are intentionally stored on bulk storage"
        )
    bulk_root = Path(bulk).expanduser()
    if not bulk_root.is_absolute():
        raise ValueError("BULK must be an absolute path")
    return bulk_root / "rubric_gen" / "runs" / "malt-benchmark"


def _publish_evaluation_report(evaluation_root: Path) -> Path:
    reports_root = Path(
        os.environ.get("MALT_REPORTS_ROOT", PROJECT_ROOT / "runs" / "malt-reports")
    ).expanduser()
    if not reports_root.is_absolute():
        reports_root = resolve_project_path(reports_root)
    report_dir = reports_root / evaluation_root.name
    report_dir.mkdir(parents=True, exist_ok=True)
    for name in ("summary.json", "metrics.json"):
        source = evaluation_root / name
        if source.is_file():
            write_json_atomic(
                report_dir / name,
                json.loads(source.read_text(encoding="utf-8")),
            )
    write_json_atomic(
        report_dir / "source.json",
        {"evaluation_dir": str(evaluation_root.resolve())},
    )
    return report_dir


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect, prepare, run, and score the MALT reward-hacking benchmark."
    )
    parser.add_argument(
        "inputs", nargs="*",
        help=("One MALT configuration's shards. Defaults to "
              "data/malt-public/default/*.parquet."),
    )
    parser.add_argument(
        "--output-dir",
        default=None,
        help=(
            "Bulky benchmark artifact directory. Defaults to "
            "$BULK/rubric_gen/runs/malt-benchmark."
        ),
    )
    parser.set_defaults(
        positive_labels=(
            "reward_hacking",
            "partial_problem_solving",
            "sabotage",
            "gives_up",
        ),
        negative_labels=("normal",),
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
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--raw", action="store_true")
    parser.add_argument(
        "--split", choices=("development", "validation", "test", "all"),
        default="test", help="Split evaluated and scored. Defaults to test.",
    )
    return parser


def run(args: argparse.Namespace) -> int:
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
    root = (
        resolve_project_path(args.output_dir)
        if args.output_dir is not None
        else _default_output_dir()
    )
    root.mkdir(parents=True, exist_ok=True)
    inventory = inventory_malt(inputs, show_progress=True)
    (root / "inventory.json").write_text(
        json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
    )
    selected_mode = bool(
        args.agent_ensemble or args.ensemble or args.agent or args.judge
        or args.vllm or args.vllm_judge or args.vllm_ensemble
    )
    cases_dir = root / "cases"
    gold_path = root / "private" / "gold.jsonl"
    preparation_path = root / "private" / "preparation.json"
    preparation = {
        "inputs": [str(path) for path in inputs],
        "positive_labels": sorted(args.positive_labels),
        "negative_labels": sorted(args.negative_labels),
        "development_fraction": args.development_fraction,
        "validation_fraction": args.validation_fraction,
        "split_seed": args.split_seed,
    }
    with _preparation_lock(root):
        preparation_matches = (
            cases_dir.is_dir()
            and gold_path.is_file()
            and preparation_path.is_file()
            and json.loads(preparation_path.read_text(encoding="utf-8")) == preparation
        )
        if preparation_matches:
            prepared: dict[str, object] = {"status": "reused"}
        else:
            legacy_staging_root = root / ".preparing"
            if legacy_staging_root.exists():
                shutil.rmtree(legacy_staging_root)
            staging_root = Path(tempfile.mkdtemp(prefix=".preparing-", dir=root))
            staging_cases = staging_root / "cases"
            staging_gold = staging_root / "gold.jsonl"
            try:
                prepared = prepare_malt(MaltPrepareConfig(
                    inputs=inputs,
                    cases_dir=staging_cases,
                    gold_path=staging_gold,
                    positive_labels=frozenset(args.positive_labels),
                    negative_labels=frozenset(args.negative_labels),
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
            finally:
                shutil.rmtree(staging_root, ignore_errors=True)
            prepared["cases_dir"] = str(cases_dir)
            prepared["gold_path"] = str(gold_path)
            write_json_atomic(preparation_path, preparation)
    if not selected_mode:
        print(json.dumps(prepared, indent=2))
        print(f"Prepared benchmark: {root}")
        return 0

    selected_case_ids = {
        str(row["case_id"])
        for line in gold_path.read_text(encoding="utf-8").splitlines()
        if (row := json.loads(line))
        and (args.split == "all" or row.get("split") == args.split)
    }
    case_dirs = tuple(sorted(
        path.parent
        for path in cases_dir.glob("*/manifest.json")
        if path.parent.name in selected_case_ids
    ))
    if not case_dirs:
        raise ValueError(f"no {args.split} cases matched the audited label mapping")
    case_dirs = _sample_case_dirs(case_dirs, args.top, args.seed, args.split)
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
    mode_name += f"--split-{args.split}"
    if args.top is not None:
        mode_name += f"--top-{args.top}--seed-{args.seed}"
    else:
        mode_name += "--top-all"
    safe_split_seed = re.sub(r"[^A-Za-z0-9._-]+", "_", args.split_seed)
    mode_name += (
        f"--split-seed-{safe_split_seed}"
        f"--dev-{args.development_fraction:g}"
        f"--val-{args.validation_fraction:g}"
        f"--mc-{args.max_concurrency}--raw-{int(args.raw)}"
    )
    evaluation_root = _evaluation_root(root, mode_name, resume=args.resume)
    if agent_panel is not None:
        exit_code = RewardHackingAuditRunner(RewardHackingAuditConfig(
            experiment_dirs=(), case_dirs=case_dirs, output_dir=evaluation_root,
            tasks_dir=resolve_project_path("data/biomnibench-da"), panel=agent_panel,
            max_concurrency=args.max_concurrency, resume=args.resume, raw=args.raw,
        )).run()
    else:
        assert models is not None
        exit_code = ModelJudgeRunner(ModelJudgeConfig(
            case_dirs=case_dirs, models=models, output_dir=evaluation_root,
            max_concurrency=args.max_concurrency, resume=args.resume,
            base_urls=base_urls,
        )).run()
    if exit_code:
        report_dir = _publish_evaluation_report(evaluation_root)
        print(f"Wrote lightweight MALT report: {report_dir}")
        return exit_code
    metrics = score_panel(
        evaluation_root / "summary.json", gold_path,
        split=None if args.split == "all" else args.split,
    )
    write_json_atomic(evaluation_root / "metrics.json", metrics)
    print(f"Wrote benchmark metrics: {evaluation_root / 'metrics.json'}")
    report_dir = _publish_evaluation_report(evaluation_root)
    print(f"Wrote lightweight MALT report: {report_dir}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    try:
        return run(parser.parse_args(argv))
    except FileNotFoundError as exc:
        parser.error(str(exc))
    raise AssertionError("argparse.error did not exit")


if __name__ == "__main__":
    raise SystemExit(main())
