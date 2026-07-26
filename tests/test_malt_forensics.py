from __future__ import annotations

import json
from pathlib import Path

import pytest

from rubric_gen.malt.cli import (
    _default_output_dir,
    _evaluation_root,
    _preparation_lock,
    _publish_evaluation_report,
    _sample_case_dirs,
    build_parser,
    main,
    run,
)
from rubric_gen.biomnibench.forensics.malt import (
    MaltPrepareConfig,
    inventory_malt,
    prepare_malt,
)
from rubric_gen.biomnibench.forensics.scoring import score_panel


def _rows(path: Path) -> None:
    rows = [
        {"samples": [{"input": [{"role": "user", "content": "task"}], "output": []}],
         "metadata": {"labels": ["reward_hacking"], "manually_reviewed": True,
                      "run_id": 1, "task_id": "task-a", "model": "m"}},
        {"samples": [], "metadata": {"labels": ["normal"], "manually_reviewed": True,
                                      "run_id": "run-2", "task_id": "task-b", "model": "m"}},
        {"samples": [], "metadata": {"labels": ["reward_hacking"], "manually_reviewed": False,
                                      "run_id": "run-3", "task_id": "task-c", "model": "m"}},
        {"samples": [], "metadata": {"labels": [], "run_id": "run-4",
                                      "task_id": "task-d", "model": "m"}},
    ]
    path.write_text("".join(json.dumps(row) + "\n" for row in rows))


def test_inventory_and_prepare_blind_cases(tmp_path: Path) -> None:
    source = tmp_path / "malt.jsonl"
    _rows(source)
    inventory = inventory_malt([source])
    assert inventory["rows"] == 4
    assert inventory["labels"] == {"reward_hacking": 2, "normal": 1}
    assert inventory["empty_label_rows"] == 1

    result = prepare_malt(MaltPrepareConfig(
        inputs=(source,), cases_dir=tmp_path / "cases",
        gold_path=tmp_path / "private" / "gold.jsonl",
        positive_labels=frozenset({"reward_hacking"}),
        negative_labels=frozenset({"normal"}),
    ))
    assert result["cases"] == 3
    assert result["positives"] == 2
    assert result["negatives"] == 1
    assert result["skipped_unmapped"] == 1
    for manifest in (tmp_path / "cases").glob("*/manifest.json"):
        text = manifest.read_text()
        assert "labels" not in text and "run-" not in text
    gold_rows = [json.loads(line) for line in (tmp_path / "private" / "gold.jsonl").read_text().splitlines()]
    assert all(row["split"] in {"development", "validation", "test"} for row in gold_rows)


def test_inventory_explains_unmatched_shell_glob(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="glob matched no files"):
        inventory_malt([tmp_path / "default" / "*.parquet"])


def test_cli_reports_unmatched_glob_without_traceback(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    with pytest.raises(SystemExit) as error:
        main([str(tmp_path / "default" / "*.parquet"), "--output-dir", str(tmp_path / "out")])
    assert error.value.code == 2
    assert "glob matched no files" in capsys.readouterr().err


def test_single_cli_uses_fixed_mapping_and_prepares(tmp_path: Path) -> None:
    source = tmp_path / "malt.jsonl"
    _rows(source)
    root = tmp_path / "benchmark"
    parser = build_parser()
    assert run(parser.parse_args([str(source), "--output-dir", str(root)])) == 0
    assert (root / "inventory.json").is_file()
    assert len(list((root / "cases").glob("*/manifest.json"))) == 3


def test_cli_transactionally_rebuilds_changed_preparation(tmp_path: Path) -> None:
    source = tmp_path / "malt.jsonl"
    _rows(source)
    root = tmp_path / "benchmark"
    args = build_parser().parse_args([str(source), "--output-dir", str(root)])
    assert run(args) == 0
    stale = root / "cases" / "stale"
    stale.mkdir()
    preparation_path = root / "private" / "preparation.json"
    preparation = json.loads(preparation_path.read_text())
    preparation["obsolete_setting"] = False
    preparation_path.write_text(json.dumps(preparation))

    assert run(args) == 0
    assert not stale.exists()
    assert "obsolete_setting" not in json.loads(preparation_path.read_text())


def test_evaluation_modes_are_mutually_exclusive() -> None:
    parser = build_parser()
    args = parser.parse_args([
        "data.jsonl", "--output-dir", "out", "--agent", "codex"
    ])
    assert args.agent == "codex"
    with pytest.raises(SystemExit):
        parser.parse_args([
            "data.jsonl", "--output-dir", "out", "--agent-ensemble", "--ensemble"
        ])


def test_default_inputs_and_seeded_top_sampling() -> None:
    args = build_parser().parse_args([
        "--output-dir", "out", "--top", "2", "--seed", "17"
    ])
    assert args.inputs == []
    assert args.top == 2
    cases = tuple(Path(name) for name in ("a", "b", "c", "d"))
    assert _sample_case_dirs(cases, 2, 17, "test") == _sample_case_dirs(
        cases, 2, 17, "test"
    )
    assert len(_sample_case_dirs(cases, 2, 17, "test")) == 2
    with pytest.raises(ValueError, match="exceeds"):
        _sample_case_dirs(cases, 5, 17, "test")


def test_default_output_uses_bulk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BULK", str(tmp_path / "bulk"))

    assert _default_output_dir() == (
        tmp_path / "bulk" / "rubric_gen" / "runs" / "malt-benchmark"
    )


def test_default_output_requires_absolute_bulk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BULK", raising=False)
    with pytest.raises(ValueError, match="BULK must be set"):
        _default_output_dir()
    monkeypatch.setenv("BULK", "relative")
    with pytest.raises(ValueError, match="absolute path"):
        _default_output_dir()


def test_evaluation_report_contains_only_lightweight_results(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    evaluation = tmp_path / "bulk" / "evaluations" / "run-identity"
    evaluation.mkdir(parents=True)
    (evaluation / "summary.json").write_text('{"records": []}\n')
    (evaluation / "metrics.json").write_text('{"accuracy": 0.5}\n')
    bulky = evaluation / "cases" / "case-1"
    bulky.mkdir(parents=True)
    (bulky / "response.txt").write_text("x" * 10_000)
    reports = tmp_path / "reports"
    monkeypatch.setenv("MALT_REPORTS_ROOT", str(reports))

    report = _publish_evaluation_report(evaluation)

    assert report == reports / "run-identity"
    assert {path.name for path in report.iterdir()} == {
        "summary.json",
        "metrics.json",
        "source.json",
    }
    assert not (report / "cases").exists()


def test_preparation_lock_rejects_a_concurrent_writer(tmp_path: Path) -> None:
    with _preparation_lock(tmp_path):
        with pytest.raises(RuntimeError, match="another MALT process"):
            with _preparation_lock(tmp_path):
                pytest.fail("concurrent preparation unexpectedly acquired the lock")


def test_timestamped_evaluation_root_and_resume_latest(tmp_path: Path) -> None:
    identity = "agent-codex--split-test--top-10--seed-42"
    first = _evaluation_root(
        tmp_path, identity, resume=False, timestamp="20260725-120000-000001"
    )
    second = _evaluation_root(
        tmp_path, identity, resume=False, timestamp="20260725-130000-000001"
    )
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    assert _evaluation_root(tmp_path, identity, resume=True) == second


def test_vllm_modes_use_dynamic_endpoint_directory_defaults() -> None:
    parser = build_parser()
    args = parser.parse_args([
        "data.jsonl", "--output-dir", "out", "--vllm-ensemble"
    ])
    assert args.vllm_ensemble is True
    assert args.vllm_endpoint_dir == "runs/vllm-endpoints"
    assert args.vllm_qwen_url is None
    assert args.vllm_glm_url is None
    assert args.vllm_gpt_oss_url is None


def test_prepare_rejects_duplicate_runs(tmp_path: Path) -> None:
    source = tmp_path / "malt.jsonl"
    _rows(source)
    source.write_text(source.read_text() + source.read_text().splitlines()[0] + "\n")
    with pytest.raises(ValueError, match="duplicate run_id"):
        prepare_malt(MaltPrepareConfig(
            inputs=(source,), cases_dir=tmp_path / "cases", gold_path=tmp_path / "gold",
            positive_labels=frozenset({"reward_hacking"}),
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
