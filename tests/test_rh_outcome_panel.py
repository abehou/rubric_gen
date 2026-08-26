from __future__ import annotations

import json
import threading
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import rubric_gen.submission_revision.rh_outcome_panel as panel_module
from rubric_gen.submission_revision.rh_diagnostics import EvaluationConfig
from rubric_gen.submission_revision.rh_outcome_panel import (
    PANEL_POLICY,
    ResilientHolisticPairwiseRunner,
    ResilientMechanisticEvaluationRunner,
)


MODELS = ("gpt", "claude", "gemini")


def _config(tmp_path: Path) -> EvaluationConfig:
    experiment = SimpleNamespace(
        experiment_id="experiment-1",
        outcome_audit={"models": list(MODELS)},
        protocol={"judge_model": "weak"},
    )
    return EvaluationConfig(
        experiment=experiment,
        study_dir=tmp_path / "study",
        paraphrase_dir=tmp_path / "paraphrases",
        output_dir=tmp_path / "output",
        max_concurrency=1,
        resume=False,
    )


def _job(model: str, instrument: str | None = None) -> object:
    return SimpleNamespace(
        key=f"{instrument or 'mechanistic'}-{model}",
        model=model,
    )


def test_mechanistic_panel_uses_every_stage_complete_judge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = ResilientMechanisticEvaluationRunner(_config(tmp_path), ())
    jobs = tuple(_job(model) for model in (*MODELS, "weak"))
    runner._prepared = SimpleNamespace(
        targets=(SimpleNamespace(assignment_id="a-1"),),
        jobs=jobs,
        unique_jobs=jobs,
        predispatch_plan={},
    )

    def run_job(job: object) -> dict[str, object]:
        if job.model == "gemini":  # type: ignore[attr-defined]
            raise RuntimeError(
                "RH audit rubric judge failed after 2 attempts: "
                "429 RESOURCE_EXHAUSTED"
            )
        return {
            "score": 50,
            "attempt_id": "attempt",
            "validation_path": "validation.json",
            "evaluation_path": "evaluation.json",
        }

    observed_models: list[tuple[str, ...]] = []
    monkeypatch.setattr(runner, "preflight", lambda: None)
    monkeypatch.setattr(
        runner,
        "_manifest",
        lambda *_args: {
            "kind": panel_module.rh.MECHANISTIC_KIND,
            "models": list(MODELS),
            "panel_policy": PANEL_POLICY,
        },
    )
    monkeypatch.setattr(runner, "_run_job", run_job)
    monkeypatch.setattr(
        panel_module.rh,
        "_mechanistic_job_identity",
        lambda job: {"model": job.model, "assignment_id": "a-1"},
    )
    monkeypatch.setattr(panel_module.rh, "_record_sort_key", lambda row: ())
    monkeypatch.setattr(
        panel_module,
        "_summarize_mechanistic_scores",
        lambda _targets, _records, models: (
            observed_models.append(models) or [{"assignment_id": "a-1"}]
        ),
    )

    assert runner.run() == 0
    assert observed_models == [("gpt", "claude")]
    summary = json.loads((tmp_path / "output" / "summary.json").read_text())
    assert summary["available_models"] == ["gpt", "claude"]
    assert summary["failed_models"] == ["gemini"]
    assert summary["failed_semantic_judgment_count"] == 1
    assert {record["model"] for record in summary["records"]} == {
        "gpt",
        "claude",
        "weak",
    }


def test_mechanistic_panel_replaces_obsolete_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = replace(_config(tmp_path), resume=True)
    runner = ResilientMechanisticEvaluationRunner(config, ())
    jobs = tuple(_job(model) for model in (*MODELS, "weak"))
    runner._prepared = SimpleNamespace(
        targets=(SimpleNamespace(assignment_id="a-1"),),
        jobs=jobs,
        unique_jobs=jobs,
        predispatch_plan={},
    )
    manifest = {
        "kind": panel_module.rh.MECHANISTIC_KIND,
        "models": list(MODELS),
    }
    runner.output.prepare(manifest, resume=False)
    runner.output.write_json(("summary.json",), {
        "kind": panel_module.rh.MECHANISTIC_KIND,
        "status": "completed",
        "records": [],
    })

    monkeypatch.setattr(runner, "preflight", lambda: None)
    monkeypatch.setattr(runner, "_manifest", lambda *_args: manifest)
    monkeypatch.setattr(
        runner,
        "_run_job",
        lambda _job: {
            "score": 50,
            "attempt_id": "attempt",
            "validation_path": "validation.json",
            "evaluation_path": "evaluation.json",
        },
    )
    monkeypatch.setattr(
        panel_module.rh,
        "_mechanistic_job_identity",
        lambda job: {"model": job.model, "assignment_id": "a-1"},
    )
    monkeypatch.setattr(panel_module.rh, "_record_sort_key", lambda row: ())
    monkeypatch.setattr(
        panel_module,
        "_summarize_mechanistic_scores",
        lambda *_args: [{"assignment_id": "a-1"}],
    )

    assert runner.run() == 0
    summary = json.loads((tmp_path / "output" / "summary.json").read_text())
    assert summary["panel_policy"] == PANEL_POLICY
    assert summary["available_models"] == list(MODELS)


def test_mechanistic_panel_skips_holdouts_and_keeps_resume_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = replace(_config(tmp_path), resume=True)
    runner = ResilientMechanisticEvaluationRunner(config, ())

    def job(
        key: str,
        model: str,
        role: str | None = None,
        *,
        bank: bool = False,
    ) -> SimpleNamespace:
        return SimpleNamespace(
            key=key,
            model=model,
            roles=(() if role is None else (SimpleNamespace(name=role),)),
            bank_members=((object(),) if bank else ()),
            specification_anchors=(),
        )

    shared_holdout = job("shared", "gpt", "holdout")
    selected = job("shared", "gpt", "selected")
    pure_holdout = job("skip", "gpt", "holdout")
    weak = job("weak", "weak", bank=True)
    runner._prepared = SimpleNamespace(
        targets=(SimpleNamespace(assignment_id="a-1"),),
        jobs=(shared_holdout, selected, pure_holdout, weak),
        unique_jobs=(shared_holdout, pure_holdout, weak),
        predispatch_plan={},
    )
    manifest = {
        "kind": panel_module.rh.MECHANISTIC_KIND,
        "models": list(MODELS),
    }
    runner.output.prepare(manifest, resume=False)
    runner.output.write_json(("records", "sentinel.json"), {"kept": True})
    calls: list[str] = []

    monkeypatch.setattr(runner, "preflight", lambda: None)
    monkeypatch.setattr(runner, "_manifest", lambda *_args: manifest)
    monkeypatch.setattr(
        runner,
        "_run_job",
        lambda current: (
            calls.append(current.key)
            or {
                "score": 50,
                "attempt_id": "attempt",
                "validation_path": "validation.json",
                "evaluation_path": "evaluation.json",
            }
        ),
    )
    monkeypatch.setattr(
        panel_module.rh,
        "_mechanistic_job_identity",
        lambda current: {
            "model": current.model,
            "assignment_id": "a-1",
        },
    )
    monkeypatch.setattr(panel_module.rh, "_record_sort_key", lambda row: ())
    monkeypatch.setattr(
        panel_module,
        "_summarize_mechanistic_scores",
        lambda *_args: [{"assignment_id": "a-1"}],
    )

    assert runner.run() == 0
    assert calls == ["shared", "weak"]
    assert (tmp_path / "output" / "records" / "sentinel.json").exists()
    summary = json.loads((tmp_path / "output" / "summary.json").read_text())
    assert summary["planned_semantic_judgment_count"] == 2
    assert summary["skipped_holdout_semantic_judgment_count"] == 1
    assert summary["skipped_holdout_assignment_reference_count"] == 2


def test_mechanistic_panel_fails_when_every_strong_judge_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = ResilientMechanisticEvaluationRunner(_config(tmp_path), ())
    jobs = tuple(_job(model) for model in (*MODELS, "weak"))
    runner._prepared = SimpleNamespace(
        targets=(),
        jobs=jobs,
        unique_jobs=jobs,
        predispatch_plan={},
    )

    def run_job(job: object) -> dict[str, object]:
        if job.model in MODELS:  # type: ignore[attr-defined]
            raise RuntimeError("RH audit rubric judge failed after 2 attempts: bad")
        return {
            "score": 50,
            "attempt_id": "attempt",
            "validation_path": "validation.json",
            "evaluation_path": "evaluation.json",
        }

    monkeypatch.setattr(runner, "preflight", lambda: None)
    monkeypatch.setattr(
        runner,
        "_manifest",
        lambda *_args: {
            "kind": panel_module.rh.MECHANISTIC_KIND,
            "models": list(MODELS),
            "panel_policy": PANEL_POLICY,
        },
    )
    monkeypatch.setattr(runner, "_run_job", run_job)

    with pytest.raises(RuntimeError, match="all configured RH mechanistic"):
        runner.run()
    assert not (tmp_path / "output" / "summary.json").exists()


def test_anthropic_array_limit_opens_the_provider_circuit() -> None:
    error = RuntimeError(
        "RH audit rubric judge failed after 2 attempts: Error code: 400 - "
        "output_config.format.schema: For 'array' type, 'minItems' values "
        "other than 0 or 1 are not supported"
    )

    assert panel_module._provider_circuit_reason(error) == (
        "provider-schema-unsupported"
    )


def test_anthropic_low_balance_opens_the_provider_circuit() -> None:
    error = RuntimeError(
        "RH audit rubric judge failed after 2 attempts: Error code: 400 - "
        "Your credit balance is too low to access the Anthropic API"
    )

    assert panel_module._provider_circuit_reason(error) == "provider-unavailable"


def test_terminal_judge_failure_opens_the_model_stage_circuit() -> None:
    circuits: dict[str, str] = {}
    lock = threading.Lock()

    with pytest.raises(RuntimeError, match="failed after 2 attempts"):
        panel_module._run_with_circuit(
            model="claude",
            operation=lambda: (_ for _ in ()).throw(RuntimeError(
                "RH audit rubric judge failed after 2 attempts: timeout"
            )),
            circuits=circuits,
            circuit_lock=lock,
            failure_prefix="RH audit rubric judge failed after ",
        )

    assert circuits == {"claude": "judge-stage-incomplete"}
    with pytest.raises(panel_module._JudgeCircuitOpen) as caught:
        panel_module._run_with_circuit(
            model="claude",
            operation=lambda: {"score": 50},
            circuits=circuits,
            circuit_lock=lock,
            failure_prefix="RH audit rubric judge failed after ",
        )
    assert caught.value.reason == "judge-stage-incomplete"
    assert panel_module._failure_record(
        key="job-2",
        model="claude",
        error=caught.value,
    )["reason"] == "judge-stage-incomplete"


def test_holistic_panel_uses_every_stage_complete_judge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = ResilientHolisticPairwiseRunner(_config(tmp_path), ())
    absolute = tuple(_job(model, "absolute") for model in MODELS)
    pairwise = tuple(_job(model, "pairwise") for model in MODELS)
    runner._prepared = SimpleNamespace(
        targets=(SimpleNamespace(assignment_id="a-1"),),
        models=MODELS,
        implementation_identity={},
        absolute_jobs=absolute,
        pairwise_jobs=pairwise,
        unique_absolute_jobs=absolute,
        unique_pairwise_jobs=pairwise,
        predispatch_plan={},
    )

    def run_job(instrument: str, job: object) -> dict[str, object]:
        key = str(job.key)  # type: ignore[attr-defined]
        if job.model == "gemini":  # type: ignore[attr-defined]
            raise RuntimeError(
                "RH holistic judge failed after 2 attempts: "
                "429 RESOURCE_EXHAUSTED"
            )
        runner.output.write_json(
            ("records", instrument, f"{key}.json"),
            {"key": key},
        )
        return {"verdict": {}}

    observed_models: list[tuple[str, ...]] = []
    monkeypatch.setattr(runner, "preflight", lambda: None)
    monkeypatch.setattr(
        runner,
        "_manifest",
        lambda _prepared: {
            "kind": panel_module.rh.HOLISTIC_KIND,
            "models": list(MODELS),
            "panel_policy": PANEL_POLICY,
        },
    )
    monkeypatch.setattr(
        runner,
        "_run_absolute_job",
        lambda job: run_job("absolute", job),
    )
    monkeypatch.setattr(
        runner,
        "_run_pairwise_job",
        lambda job: run_job("pairwise", job),
    )
    monkeypatch.setattr(
        panel_module.rh,
        "_absolute_assignment_reference",
        lambda job, _judgment: {"model": job.model, "assignment_id": "a-1"},
    )
    monkeypatch.setattr(
        panel_module.rh,
        "_pairwise_assignment_reference",
        lambda job, _judgment: {"model": job.model, "assignment_id": "a-1"},
    )
    monkeypatch.setattr(panel_module.rh, "_record_sort_key", lambda row: ())
    monkeypatch.setattr(
        panel_module.rh,
        "_summarize_holistic_scores",
        lambda _targets, _absolute, _pairwise, models: (
            observed_models.append(models) or [{"assignment_id": "a-1"}]
        ),
    )

    assert runner.run() == 0
    assert observed_models == [("gpt", "claude")]
    summary = json.loads((tmp_path / "output" / "summary.json").read_text())
    assert summary["available_models"] == ["gpt", "claude"]
    assert summary["failed_models"] == ["gemini"]
    assert summary["failed_semantic_judgment_count"] == 2
