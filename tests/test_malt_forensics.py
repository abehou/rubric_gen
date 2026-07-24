from __future__ import annotations

import json
from pathlib import Path

import pytest

from rubric_gen.malt.cli import build_parser, run
from rubric_gen.biomnibench.forensics.malt import (
    MaltPrepareConfig,
    inventory_malt,
    prepare_malt,
)
from rubric_gen.biomnibench.forensics.scoring import score_panel


def _rows(path: Path) -> None:
    rows = [
        {"samples": [{"input": [{"role": "user", "content": "task"}], "output": []}],
         "metadata": {"labels": ["rh"], "manually_reviewed": True,
                      "run_id": 1, "task_id": "task-a", "model": "m"}},
        {"samples": [], "metadata": {"labels": [], "manually_reviewed": True,
                                      "run_id": "run-2", "task_id": "task-b", "model": "m"}},
        {"samples": [], "metadata": {"labels": ["rh"], "manually_reviewed": False,
                                      "run_id": "run-3", "task_id": "task-c", "model": "m"}},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_inventory_and_prepare_blind_cases(tmp_path: Path) -> None:
    source = tmp_path / "malt.jsonl"
    _rows(source)
    inventory = inventory_malt([source])
    assert inventory["rows"] == 3
    assert inventory["labels"] == {"rh": 2}

    result = prepare_malt(MaltPrepareConfig(
        inputs=(source,), cases_dir=tmp_path / "cases",
        gold_path=tmp_path / "private" / "gold.jsonl",
        positive_labels=frozenset({"rh"}),
        empty_labels_are_negative=True,
    ))
    assert result["cases"] == 2
    assert result["positives"] == result["negatives"] == 1
    for manifest in (tmp_path / "cases").glob("*/manifest.json"):
        text = manifest.read_text()
        assert "labels" not in text and "run-" not in text
    gold_rows = [json.loads(line) for line in (tmp_path / "private" / "gold.jsonl").read_text().splitlines()]
    assert all(row["split"] in {"development", "validation", "test"} for row in gold_rows)


def test_single_cli_inventories_then_prepares(tmp_path: Path) -> None:
    source = tmp_path / "malt.jsonl"
    _rows(source)
    root = tmp_path / "benchmark"
    parser = build_parser()
    assert run(parser.parse_args([str(source), "--output-dir", str(root)])) == 0
    assert (root / "inventory.json").is_file()
    assert not (root / "cases").exists()
    assert run(parser.parse_args([
        str(source), "--output-dir", str(root),
        "--positive-label", "rh", "--empty-label-is-negative",
    ])) == 0
    assert len(list((root / "cases").glob("*/manifest.json"))) == 2


def test_prepare_rejects_duplicate_runs(tmp_path: Path) -> None:
    source = tmp_path / "malt.jsonl"
    _rows(source)
    source.write_text(source.read_text() + source.read_text().splitlines()[0] + "\n")
    with pytest.raises(ValueError, match="duplicate run_id"):
        prepare_malt(MaltPrepareConfig(
            inputs=(source,), cases_dir=tmp_path / "cases", gold_path=tmp_path / "gold",
            positive_labels=frozenset({"rh"}),
        ))


def test_score_panel_reports_individual_and_fixed_ensembles(tmp_path: Path) -> None:
    gold = tmp_path / "gold.jsonl"
    gold.write_text(
        '{"case_id":"a","reward_hacking":true}\n'
        '{"case_id":"b","reward_hacking":false}\n'
    )
    records = []
    decisions = {
        "a": ["reward_hacking_detected", "reward_hacking_detected", "no_reward_hacking_detected"],
        "b": ["no_reward_hacking_detected", "no_reward_hacking_detected", "reward_hacking_detected"],
    }
    for case_id, values in decisions.items():
        for provider, decision in zip(("codex", "claude", "gemini"), values):
            records.append({"case_id": case_id, "provider": provider,
                            "verdict": {"decision": decision, "confidence": .8,
                                        "evidence_locations": []}})
    summary = tmp_path / "summary.json"
    summary.write_text(json.dumps({"records": records}))
    result = score_panel(summary, gold)
    assert result["ensembles"]["majority"]["accuracy"] == 1.0
    assert result["providers"]["gemini"]["accuracy"] == 0.0
