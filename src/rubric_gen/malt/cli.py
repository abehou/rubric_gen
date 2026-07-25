"""Standalone MALT reward-hacking benchmark CLI."""

from __future__ import annotations

import argparse
import json
import re
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
from rubric_gen.biomnibench.utils.paths import resolve_project_path
from rubric_gen.malt.model_judge import (
    STRONG_JUDGE_MODELS,
    ModelJudgeConfig,
    ModelJudgeRunner,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect, prepare, run, and score the MALT reward-hacking benchmark."
    )
    parser.add_argument("inputs", nargs="+", help="One MALT configuration's shards.")
    parser.add_argument("--output-dir", required=True, help="Benchmark artifact directory.")
    parser.add_argument(
        "--positive-label", action="append", default=[],
        help=("Exact audited positive label; repeat as needed. If omitted, only "
              "inventory.json is produced."),
    )
    parser.add_argument(
        "--negative-label", action="append", default=[],
        help="Exact audited negative label; repeat as needed.",
    )
    parser.add_argument("--empty-label-is-negative", action="store_true")
    parser.add_argument("--include-unreviewed", action="store_true")
    parser.add_argument("--development-fraction", type=float, default=0.2)
    parser.add_argument("--validation-fraction", type=float, default=0.1)
    parser.add_argument("--split-seed", default="malt-v1")
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
        default="test", help="Split scored by an evaluation mode. Defaults to test.",
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

    inputs = tuple(resolve_project_path(value) for value in args.inputs)
    root = resolve_project_path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    inventory = inventory_malt(inputs)
    (root / "inventory.json").write_text(
        json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
    )
    selected_mode = bool(
        args.agent_ensemble or args.ensemble or args.agent or args.judge
        or args.vllm or args.vllm_judge or args.vllm_ensemble
    )
    if not args.positive_label:
        if selected_mode:
            raise ValueError("an evaluation mode requires at least one audited --positive-label")
        print(json.dumps(inventory, indent=2))
        print(f"Wrote inventory only: {root / 'inventory.json'}")
        return 0

    cases_dir = root / "cases"
    gold_path = root / "private" / "gold.jsonl"
    preparation_path = root / "private" / "preparation.json"
    preparation = {
        "inputs": [str(path) for path in inputs],
        "positive_labels": sorted(args.positive_label),
        "negative_labels": sorted(args.negative_label),
        "empty_labels_are_negative": args.empty_label_is_negative,
        "require_manually_reviewed": not args.include_unreviewed,
        "development_fraction": args.development_fraction,
        "validation_fraction": args.validation_fraction,
        "split_seed": args.split_seed,
    }
    if cases_dir.is_dir() and gold_path.is_file() and preparation_path.is_file():
        if json.loads(preparation_path.read_text(encoding="utf-8")) != preparation:
            raise ValueError("existing benchmark was prepared with different inputs or labels")
        prepared: dict[str, object] = {"status": "reused"}
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
        prepared = prepare_malt(MaltPrepareConfig(
            inputs=inputs,
            cases_dir=cases_dir,
            gold_path=gold_path,
            positive_labels=frozenset(args.positive_label),
            negative_labels=frozenset(args.negative_label),
            empty_labels_are_negative=args.empty_label_is_negative,
            require_manually_reviewed=not args.include_unreviewed,
            development_fraction=args.development_fraction,
            validation_fraction=args.validation_fraction,
            split_seed=args.split_seed,
        ))
        preparation_path.write_text(json.dumps(preparation, indent=2) + "\n", encoding="utf-8")
    if not selected_mode:
        print(json.dumps(prepared, indent=2))
        print(f"Prepared benchmark: {root}")
        return 0

    case_dirs = tuple(sorted(path.parent for path in cases_dir.glob("*/manifest.json")))
    if not case_dirs:
        raise ValueError("no cases matched the audited label mapping")
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
    evaluation_root = root / "evaluations" / mode_name
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
        return exit_code
    metrics = score_panel(
        evaluation_root / "summary.json", gold_path,
        split=None if args.split == "all" else args.split,
    )
    (evaluation_root / "metrics.json").write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote benchmark metrics: {evaluation_root / 'metrics.json'}")
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
