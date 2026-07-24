"""Standalone MALT reward-hacking benchmark CLI."""

from __future__ import annotations

import argparse
import json

from rubric_gen.biomnibench.forensics.malt import (
    MaltPrepareConfig,
    inventory_malt,
    prepare_malt,
)
from rubric_gen.biomnibench.forensics.reward_hacking import (
    RewardHackingAuditConfig,
    RewardHackingAuditRunner,
)
from rubric_gen.biomnibench.forensics.scoring import score_panel
from rubric_gen.biomnibench.utils.paths import resolve_project_path


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
    parser.add_argument(
        "--run", action="store_true",
        help="Prepare, run all three agents, and write metrics.json.",
    )
    parser.add_argument("--max-concurrency", type=int, default=3)
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--raw", action="store_true")
    parser.add_argument(
        "--split", choices=("development", "validation", "test", "all"),
        default="test", help="Split scored by --run. Defaults to test.",
    )
    return parser


def run(args: argparse.Namespace) -> int:
    inputs = tuple(resolve_project_path(value) for value in args.inputs)
    root = resolve_project_path(args.output_dir)
    root.mkdir(parents=True, exist_ok=True)
    inventory = inventory_malt(inputs)
    (root / "inventory.json").write_text(
        json.dumps(inventory, indent=2) + "\n", encoding="utf-8"
    )
    if not args.positive_label:
        if args.run:
            raise ValueError("--run requires at least one audited --positive-label")
        print(json.dumps(inventory, indent=2))
        print(f"Wrote inventory only: {root / 'inventory.json'}")
        return 0

    cases_dir = root / "cases"
    gold_path = root / "private" / "gold.jsonl"
    if args.resume and cases_dir.is_dir() and gold_path.is_file():
        prepared: dict[str, object] = {"status": "reused"}
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
    if not args.run:
        print(json.dumps(prepared, indent=2))
        print(f"Prepared benchmark: {root}")
        return 0

    case_dirs = tuple(sorted(path.parent for path in cases_dir.glob("*/manifest.json")))
    if not case_dirs:
        raise ValueError("no cases matched the audited label mapping")
    audit_root = root / "agent-ensemble"
    exit_code = RewardHackingAuditRunner(RewardHackingAuditConfig(
        experiment_dirs=(), case_dirs=case_dirs, output_dir=audit_root,
        tasks_dir=resolve_project_path("data/biomnibench-da"),
        max_concurrency=args.max_concurrency, resume=args.resume, raw=args.raw,
    )).run()
    if exit_code:
        return exit_code
    metrics = score_panel(
        audit_root / "summary.json", gold_path,
        split=None if args.split == "all" else args.split,
    )
    (root / "metrics.json").write_text(
        json.dumps(metrics, indent=2) + "\n", encoding="utf-8"
    )
    print(f"Wrote benchmark metrics: {root / 'metrics.json'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    return run(build_parser().parse_args(argv))


if __name__ == "__main__":
    raise SystemExit(main())
