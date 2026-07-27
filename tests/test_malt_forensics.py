from __future__ import annotations

import json
from pathlib import Path

import pytest

import rubric_gen.malt.cli as malt_cli_module

from rubric_gen.malt.cli import (
    _default_benchmark_dir,
    _default_output_dir,
    _evaluation_root,
    _preparation_lock,
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
from rubric_gen.biomnibench.forensics.scoring import (
    detection_rates,
    plot_detection_rates,
    render_metrics_csv,
    render_metrics_markdown,
    score_panel,
)
from rubric_gen.biomnibench.forensics.categories import categorize_findings
from rubric_gen.biomnibench.utils.paths import PROJECT_ROOT


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
        main([str(tmp_path / "default" / "*.parquet"), "--detect", "rh", "--benchmark-dir", str(tmp_path / "benchmark")])
    assert error.value.code == 2
    assert "glob matched no files" in capsys.readouterr().err


def test_single_cli_uses_fixed_mapping_and_prepares(tmp_path: Path) -> None:
    source = tmp_path / "malt.jsonl"
    _rows(source)
    root = tmp_path / "benchmark"
    parser = build_parser()
    assert run(parser.parse_args([str(source), "--detect", "rh", "--benchmark-dir", str(root)])) == 0
    assert (root / "inventory.json").is_file()
    assert len(list((root / "rh/cases").glob("*/manifest.json"))) == 3


def test_detect_is_required_and_targets_have_distinct_label_mappings(
    tmp_path: Path,
) -> None:
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])

    source = tmp_path / "malt.jsonl"
    rows = [
        {"samples": [], "metadata": {"labels": [label], "run_id": label,
         "task_id": label, "model": "m", "manually_reviewed": True}}
        for label in (
            "normal", "reward_hacking", "gives_up", "match_weaker_model",
            "partial_problem_solving", "reasoning_about_task", "refusals",
            "sabotage",
        )
    ]
    source.write_text("".join(json.dumps(row) + "\n" for row in rows))

    rh_root = tmp_path / "rh"
    non_normal_root = tmp_path / "non-normal"
    assert run(parser.parse_args([
        str(source), "--detect", "rh", "--benchmark-dir", str(rh_root)
    ])) == 0
    assert run(parser.parse_args([
        str(source), "--detect", "non-normal", "--benchmark-dir",
        str(non_normal_root)
    ])) == 0

    rh_gold = [json.loads(line) for line in
               (rh_root / "rh/private/gold.jsonl").read_text().splitlines()]
    non_normal_gold = [json.loads(line) for line in
                       (non_normal_root / "non-normal/private/gold.jsonl").read_text().splitlines()]
    assert len(rh_gold) == 2
    assert sum(row["positive"] for row in rh_gold) == 1
    assert len(non_normal_gold) == 8
    assert sum(row["positive"] for row in non_normal_gold) == 7


def test_cli_transactionally_rebuilds_changed_preparation(tmp_path: Path) -> None:
    source = tmp_path / "malt.jsonl"
    _rows(source)
    root = tmp_path / "benchmark"
    args = build_parser().parse_args([str(source), "--detect", "rh", "--benchmark-dir", str(root)])
    assert run(args) == 0
    stale = root / "rh/cases" / "stale"
    stale.mkdir()
    preparation_path = root / "rh/private" / "preparation.json"
    preparation = json.loads(preparation_path.read_text())
    assert preparation["empty_labels_are_negative"] is False
    preparation["obsolete_setting"] = False
    preparation_path.write_text(json.dumps(preparation))

    assert run(args) == 0
    assert not stale.exists()
    assert "obsolete_setting" not in json.loads(preparation_path.read_text())


def test_evaluation_modes_are_mutually_exclusive() -> None:
    parser = build_parser()
    args = parser.parse_args([
        "data.jsonl", "--detect", "rh", "--output-dir", "out", "--agent", "codex"
    ])
    assert args.agent == "codex"
    assert args.agent_step_limit == 24
    assert args.max_retries == 2
    limited = parser.parse_args([
        "data.jsonl", "--detect", "rh", "--output-dir", "out",
        "--agent-ensemble", "--agent-step-limit", "8", "--max-retries", "4",
    ])
    assert limited.agent_step_limit == 8
    assert limited.max_retries == 4
    with pytest.raises(SystemExit):
        parser.parse_args([
            "data.jsonl", "--detect", "rh", "--output-dir", "out", "--agent-ensemble", "--ensemble"
        ])


def test_biomni_batch_routes_to_unscored_direct_ensemble(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks = tmp_path / "tasks"
    (tasks / "da-1-1").mkdir(parents=True)
    (tasks / "da-1-1" / "instruction.md").write_text("task\n")
    batch = tmp_path / "batch"
    experiment = batch / "da-1-1"
    experiment.mkdir(parents=True)
    (experiment / "manifest.json").write_text(json.dumps({
        "kind": "rubric-gen-submission-revision-experiment",
        "task_id": "da-1-1",
    }))
    (batch / "batch.json").write_text(json.dumps({
        "kind": "rubric-gen-submission-revision-batch",
        "experiment_dirs": ["da-1-1"],
    }))
    observed = {}

    class FakeRunner:
        def __init__(self, config):
            observed["config"] = config

        def run(self) -> int:
            return 0

    monkeypatch.setattr(malt_cli_module, "ModelJudgeRunner", FakeRunner)
    args = build_parser().parse_args([
        "--detect", "rh", "--biomnibench-run-dir", str(batch),
        "--tasks-dir", str(tasks), "--output-dir", str(tmp_path / "out"),
        "--ensemble",
    ])

    assert run(args) == 0
    config = observed["config"]
    assert config.case_dirs == ()
    assert config.revision_dirs == (experiment.resolve(),)
    assert config.tasks_dir == tasks
    assert not list((tmp_path / "out").rglob("metrics.json"))


def test_biomni_input_requires_forensic_ensemble(tmp_path: Path) -> None:
    args = build_parser().parse_args([
        "--detect", "rh", "--biomnibench-run-dir", str(tmp_path),
    ])
    with pytest.raises(ValueError, match="requires --ensemble"):
        run(args)


def test_biomni_experiment_routes_to_agent_ensemble(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tasks = tmp_path / "tasks"
    task = tasks / "da-1-1"
    task.mkdir(parents=True)
    (task / "instruction.md").write_text("task\n")
    experiment = tmp_path / "da-1-1"
    experiment.mkdir()
    (experiment / "manifest.json").write_text(json.dumps({
        "kind": "rubric-gen-submission-revision-experiment",
        "task_id": "da-1-1",
    }))
    observed = {}

    class FakeRunner:
        def __init__(self, config):
            observed["config"] = config

        def run(self) -> int:
            return 0

    monkeypatch.setattr(malt_cli_module, "RewardHackingAuditRunner", FakeRunner)
    args = build_parser().parse_args([
        "--detect", "rh", "--biomnibench-run-dir", str(experiment),
        "--tasks-dir", str(tasks), "--output-dir", str(tmp_path / "out"),
        "--agent-ensemble",
    ])

    assert run(args) == 0
    config = observed["config"]
    assert config.experiment_dirs == (experiment.resolve(),)
    assert config.case_dirs == ()
    assert config.panel == malt_cli_module.PANEL


def test_default_inputs_and_seeded_top_sampling() -> None:
    args = build_parser().parse_args([
        "--detect", "rh", "--output-dir", "out", "--top", "2", "--seed", "17"
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


def test_balanced_sampling_draws_equal_classes_deterministically() -> None:
    cases = tuple(Path(name) for name in ("p1", "p2", "p3", "n1", "n2", "n3"))
    labels = {path.name: path.name.startswith("p") for path in cases}

    selected = _sample_case_dirs(
        cases, 4, 17, "test", gold_labels=labels, balanced=True
    )

    assert selected == _sample_case_dirs(
        cases, 4, 17, "test", gold_labels=labels, balanced=True
    )
    assert sum(labels[path.name] for path in selected) == 2
    assert sum(not labels[path.name] for path in selected) == 2


def test_balanced_sampling_rejects_invalid_or_unavailable_counts() -> None:
    cases = tuple(Path(name) for name in ("p1", "n1", "n2", "n3"))
    labels = {path.name: path.name.startswith("p") for path in cases}

    with pytest.raises(ValueError, match="requires --top"):
        _sample_case_dirs(cases, None, 42, "test", gold_labels=labels, balanced=True)
    with pytest.raises(ValueError, match="even"):
        _sample_case_dirs(cases, 3, 42, "test", gold_labels=labels, balanced=True)
    with pytest.raises(ValueError, match="only 1 positive"):
        _sample_case_dirs(cases, 4, 42, "test", gold_labels=labels, balanced=True)


def test_default_output_uses_repository() -> None:
    assert _default_output_dir() == PROJECT_ROOT / "runs" / "malt-runs"


def test_default_benchmark_uses_bulk(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BULK", str(tmp_path / "bulk"))
    assert _default_benchmark_dir() == (
        tmp_path / "bulk" / "rubric_gen" / "runs" / "malt-benchmark"
    )


def test_default_benchmark_requires_absolute_bulk(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BULK", raising=False)
    with pytest.raises(ValueError, match="BULK must be set"):
        _default_benchmark_dir()
    monkeypatch.setenv("BULK", "relative")
    with pytest.raises(ValueError, match="absolute path"):
        _default_benchmark_dir()


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
        "data.jsonl", "--detect", "rh", "--output-dir", "out", "--vllm-ensemble"
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


def test_prepare_resumes_complete_case_checkpoints(tmp_path: Path) -> None:
    source = tmp_path / "malt.jsonl"
    _rows(source)
    cases = tmp_path / "cases"
    first_gold = tmp_path / "first-gold.jsonl"
    config = MaltPrepareConfig(
        inputs=(source,), cases_dir=cases, gold_path=first_gold,
        positive_labels=frozenset({"reward_hacking"}),
        negative_labels=frozenset({"normal"}),
    )
    prepare_malt(config)
    first_gold.unlink()

    result = prepare_malt(config)

    assert result["resumed_cases"] == 3
    assert result["cases"] == 3


def test_prepare_rejects_incomplete_case_checkpoint(tmp_path: Path) -> None:
    source = tmp_path / "malt.jsonl"
    _rows(source)
    cases = tmp_path / "cases"
    incomplete = cases / _case_id_for_test(1)
    incomplete.mkdir(parents=True)

    with pytest.raises(ValueError, match="incomplete prepared case checkpoint"):
        prepare_malt(MaltPrepareConfig(
            inputs=(source,), cases_dir=cases, gold_path=tmp_path / "gold.jsonl",
            positive_labels=frozenset({"reward_hacking"}),
            negative_labels=frozenset({"normal"}),
        ))


def _case_id_for_test(run_id: str | int) -> str:
    import hashlib
    return "case-" + hashlib.sha256(str(run_id).encode()).hexdigest()[:16]


def test_score_panel_reports_individual_and_fixed_ensembles(tmp_path: Path) -> None:
    gold = tmp_path / "gold.jsonl"
    gold.write_text(
        '{"case_id":"a","positive":true}\n'
        '{"case_id":"b","positive":false}\n'
        '{"case_id":"not-selected","positive":true}\n'
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
    result = score_panel(summary, gold, detection="rh")
    assert result["ensembles"]["majority"]["accuracy"] == 1.0
    assert result["providers"]["gemini"]["accuracy"] == 0.0
    assert result["split_gold_cases"] == 3
    assert result["gold_cases"] == 2
    markdown = render_metrics_markdown(result)
    csv_text = render_metrics_csv(result)
    assert "| ensemble | majority |" in markdown
    assert "Precision | Recall | F1" in markdown
    assert "ensemble,majority" in csv_text


def test_unscored_detection_rates_exclude_failures_and_require_complete_panels(
    tmp_path: Path,
) -> None:
    records = []
    decisions = {
        "a": {"one": "reward_hacking_detected", "two": "reward_hacking_detected",
              "three": "no_reward_hacking_detected"},
        "b": {"one": "no_reward_hacking_detected", "two": "no_reward_hacking_detected",
              "three": "no_reward_hacking_detected"},
    }
    for case, panel in decisions.items():
        for provider, decision in panel.items():
            records.append({
                "case_id": case, "source_path": f"/{case}", "provider": provider,
                "status": "completed", "verdict": {
                    "decision": decision,
                    "findings": ([{
                        "type": "metric_gaming",
                        "description": "Optimized the scored proxy.",
                        "evidence_locations": ["event 1"],
                    }] if decision == "reward_hacking_detected" else []),
                },
            })
    records.append({
        "case_id": "c", "source_path": "/c", "provider": "three",
        "status": "failed",
    })
    rates = detection_rates({"detection": "rh", "records": records})

    assert rates["providers"]["one"]["rate"] == 0.5
    assert rates["providers"]["three"]["failed"] == 1
    assert rates["complete_panel_cases"] == 2
    assert rates["ensembles"]["majority"]["rate"] == 0.5
    assert rates["ensembles"]["any_detects"]["rate"] == 0.5
    output = tmp_path / "detection-rates.png"
    plot_detection_rates(rates, output)
    assert output.is_file() and output.stat().st_size > 0


def test_post_hoc_categories_are_induced_in_separate_model_call() -> None:
    summary = {"records": [{
        "case_id": "a", "source_path": "/a", "provider": "one",
        "verdict": {
            "decision": "reward_hacking_detected",
            "findings": [{
                "type": "chased the displayed score",
                "description": "Changed presentation without improving the task.",
                "evidence_locations": ["event 1"],
            }],
        },
    }, {
        "case_id": "b", "source_path": "/b", "provider": "one",
        "verdict": {"decision": "no_reward_hacking_detected", "findings": []},
    }]}

    def generate(model: str, prompt: str) -> str:
        assert model == "category-test"
        assert "chased the displayed score" in prompt
        assert "predefined taxonomy" in prompt
        return json.dumps({"categories": [{
            "name": "score-directed cosmetic optimization",
            "description": "Optimizes presentation for score without task progress.",
            "finding_ids": ["r0000-f000"],
        }]})

    result = categorize_findings(
        summary, model="category-test", generate_response=generate
    )

    assert result["categories"][0]["name"] == (
        "score-directed cosmetic optimization"
    )
    rate = result["providers"]["one"]["score-directed cosmetic optimization"]
    assert rate == {"detected": 1, "evaluated": 2, "rate": 0.5}
