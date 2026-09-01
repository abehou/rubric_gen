from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import rubric_gen.submission_revision.evaluation.runner as panel_module
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.runner import (
    RubricFreeScoreRunner,
    RubricScoreRunner,
    PANEL_POLICY,
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
        key=f"{instrument or 'rubric_score'}-{model}",
        model=model,
        target=SimpleNamespace(
            study_experiment_id="study-experiment-1",
        ),
    )


def test_rubric_score_panel_is_incomplete_without_every_configured_judge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = RubricScoreRunner(_config(tmp_path), ())
    jobs = tuple(_job(model) for model in MODELS)
    runner._prepared = SimpleNamespace(
        targets=(SimpleNamespace(
            assignment_id="a-1",
            study_experiment_id="study-experiment-1",
        ),),
        jobs=jobs,
        unique_jobs=jobs,
        predispatch_plan={},
    )

    def run_job(job: object) -> dict[str, object]:
        if job.model == "gemini":  # type: ignore[attr-defined]
            raise RuntimeError(
                "rubric-score rubric judge failed after 2 attempts: "
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
            "kind": panel_module.evaluation_jobs.RUBRIC_SCORE_KIND,
            "models": list(MODELS),
            "panel_policy": PANEL_POLICY,
        },
    )
    monkeypatch.setattr(runner, "_run_job", run_job)
    monkeypatch.setattr(
        panel_module.rubric_score,
        "_rubric_score_job_identity",
        lambda job: {"model": job.model, "assignment_id": "a-1"},
    )
    monkeypatch.setattr(panel_module.evaluation_jobs, "_record_sort_key", lambda row: ())
    monkeypatch.setattr(
        panel_module,
        "_summarize_rubric_scores",
        lambda _targets, _records, models: (
            observed_models.append(models) or [{"assignment_id": "a-1"}]
        ),
    )

    assert runner.run() == 1
    assert observed_models == []
    summary = json.loads((tmp_path / "output" / "summary.json").read_text())
    assert summary["status"] == "incomplete"
    assert summary["missing_models"] == ["gemini"]
    assert summary["failed_semantic_judgment_count"] == 1
    assert {record["model"] for record in summary["records"]} == {
        "gpt",
        "claude",
    }


def test_rubric_score_resume_retries_a_failed_exact_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    jobs = tuple(_job(model) for model in MODELS)
    prepared = SimpleNamespace(
        targets=(SimpleNamespace(
            assignment_id="a-1",
            study_experiment_id="study-experiment-1",
        ),),
        jobs=jobs,
        unique_jobs=jobs,
        predispatch_plan={},
    )
    manifest = {
        "kind": panel_module.evaluation_jobs.RUBRIC_SCORE_KIND,
        "models": list(MODELS),
    }

    def configure(runner: RubricScoreRunner) -> None:
        runner._prepared = prepared
        monkeypatch.setattr(runner, "preflight", lambda: None)
        monkeypatch.setattr(runner, "_manifest", lambda *_args: manifest)
        monkeypatch.setattr(
            panel_module.rubric_score,
            "_rubric_score_job_identity",
            lambda job: {"model": job.model, "assignment_id": "a-1"},
        )
        monkeypatch.setattr(
            panel_module.evaluation_jobs,
            "_record_sort_key",
            lambda row: (),
        )
        monkeypatch.setattr(
            panel_module,
            "_summarize_rubric_scores",
            lambda *_args: [{"assignment_id": "a-1"}],
        )

    first = RubricScoreRunner(_config(tmp_path), ())
    configure(first)

    def fail_gemini(job: object) -> dict[str, object]:
        if job.model == "gemini":  # type: ignore[attr-defined]
            raise RuntimeError(
                "rubric-score rubric judge failed after 2 attempts: timeout"
            )
        return {
            "score": 50,
            "attempt_id": "attempt",
            "validation_path": "validation.json",
            "evaluation_path": "evaluation.json",
        }

    monkeypatch.setattr(first, "_run_job", fail_gemini)
    assert first.run() == 1

    retried: list[str] = []
    resumed = RubricScoreRunner(replace(_config(tmp_path), resume=True), ())
    configure(resumed)

    def succeed(job: object) -> dict[str, object]:
        retried.append(str(job.key))  # type: ignore[attr-defined]
        return {
            "score": 50,
            "attempt_id": "attempt",
            "validation_path": "validation.json",
            "evaluation_path": "evaluation.json",
        }

    monkeypatch.setattr(resumed, "_run_job", succeed)

    assert resumed.run() == 0
    assert "rubric_score-gemini" in retried
    summary = json.loads((tmp_path / "output" / "summary.json").read_text())
    assert summary["status"] == "completed"
    assert summary["missing_models"] == []


def test_rubric_score_panel_replaces_obsolete_summary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = replace(_config(tmp_path), resume=True)
    runner = RubricScoreRunner(config, ())
    jobs = tuple(_job(model) for model in MODELS)
    runner._prepared = SimpleNamespace(
        targets=(SimpleNamespace(
            assignment_id="a-1",
            study_experiment_id="study-experiment-1",
        ),),
        jobs=jobs,
        unique_jobs=jobs,
        predispatch_plan={},
    )
    manifest = {
        "kind": panel_module.evaluation_jobs.RUBRIC_SCORE_KIND,
        "models": list(MODELS),
    }
    runner.output.prepare(manifest, resume=False)
    runner.output.write_json(("summary.json",), {
        "kind": panel_module.evaluation_jobs.RUBRIC_SCORE_KIND,
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
        panel_module.rubric_score,
        "_rubric_score_job_identity",
        lambda job: {"model": job.model, "assignment_id": "a-1"},
    )
    monkeypatch.setattr(panel_module.evaluation_jobs, "_record_sort_key", lambda row: ())
    monkeypatch.setattr(
        panel_module,
        "_summarize_rubric_scores",
        lambda *_args: [{"assignment_id": "a-1"}],
    )

    assert runner.run() == 0
    summary = json.loads((tmp_path / "output" / "summary.json").read_text())
    assert summary["panel_policy"] == PANEL_POLICY
    assert summary["missing_models"] == []


def test_rubric_score_panel_keeps_resume_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config = replace(_config(tmp_path), resume=True)
    runner = RubricScoreRunner(config, ())

    def job(key: str, model: str) -> SimpleNamespace:
        return SimpleNamespace(
            key=key,
            model=model,
            target=SimpleNamespace(
                study_experiment_id="study-experiment-1",
            ),
        )

    selected = job("selected", "gpt")
    original = job("original", "gpt")
    runner._prepared = SimpleNamespace(
        targets=(SimpleNamespace(
            assignment_id="a-1",
            study_experiment_id="study-experiment-1",
        ),),
        jobs=(selected, original),
        unique_jobs=(selected, original),
        predispatch_plan={},
    )
    manifest = {
        "kind": panel_module.evaluation_jobs.RUBRIC_SCORE_KIND,
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
        panel_module.rubric_score,
        "_rubric_score_job_identity",
        lambda current: {
            "model": current.model,
            "assignment_id": "a-1",
        },
    )
    monkeypatch.setattr(panel_module.evaluation_jobs, "_record_sort_key", lambda row: ())
    monkeypatch.setattr(
        panel_module,
        "_summarize_rubric_scores",
        lambda *_args: [{"assignment_id": "a-1"}],
    )

    assert runner.run() == 0
    assert calls == ["selected", "original"]
    assert (tmp_path / "output" / "records" / "sentinel.json").exists()
    summary = json.loads((tmp_path / "output" / "summary.json").read_text())
    assert summary["planned_semantic_judgment_count"] == 2
    assert summary["assignment_reference_count"] == 2


def test_rubric_score_panel_records_incomplete_when_every_judge_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = RubricScoreRunner(_config(tmp_path), ())
    jobs = tuple(_job(model) for model in MODELS)
    runner._prepared = SimpleNamespace(
        targets=(),
        jobs=jobs,
        unique_jobs=jobs,
        predispatch_plan={},
    )

    def run_job(job: object) -> dict[str, object]:
        if job.model in MODELS:  # type: ignore[attr-defined]
            raise RuntimeError("rubric-score rubric judge failed after 2 attempts: bad")
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
            "kind": panel_module.evaluation_jobs.RUBRIC_SCORE_KIND,
            "models": list(MODELS),
            "panel_policy": PANEL_POLICY,
        },
    )
    monkeypatch.setattr(runner, "_run_job", run_job)

    assert runner.run() == 1
    summary = json.loads((tmp_path / "output" / "summary.json").read_text())
    assert summary["status"] == "incomplete"
    assert summary["missing_models"] == list(MODELS)
    assert summary["records"] == []


def test_judge_failure_has_no_provider_wide_effect() -> None:
    assert panel_module._failure_record(
        key="job-2",
        model="claude",
        error=RuntimeError("rubric-score rubric judge failed after 3 attempts: timeout"),
    )["reason"] == "judge-failed"


def test_rubric_free_panel_is_incomplete_without_every_configured_judge(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runner = RubricFreeScoreRunner(_config(tmp_path), ())
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
                "rubric-free score judge failed after 2 attempts: "
                "429 RESOURCE_EXHAUSTED"
            )
        output = (
            runner.absolute_output
            if instrument == "absolute"
            else runner.pairwise_output
        )
        output.write_json(
            ("records", f"{key}.json"),
            {"key": key},
        )
        return {"verdict": {}}

    observed_models: list[tuple[str, ...]] = []
    monkeypatch.setattr(runner, "preflight", lambda: None)
    monkeypatch.setattr(
        runner,
        "_manifests",
        lambda _prepared: {
            "absolute": {
                "kind": panel_module.evaluation_jobs.ABSOLUTE_SCORE_KIND,
                "models": list(MODELS),
            },
            "pairwise": {
                "kind": panel_module.evaluation_jobs.PAIRWISE_PREFERENCE_KIND,
                "models": list(MODELS),
            },
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
        panel_module.absolute_score,
        "assignment_reference",
        lambda job, _judgment: {"model": job.model, "assignment_id": "a-1"},
    )
    monkeypatch.setattr(
        panel_module.pairwise_preference,
        "assignment_reference",
        lambda job, _judgment: {"model": job.model, "assignment_id": "a-1"},
    )
    monkeypatch.setattr(panel_module.evaluation_jobs, "_record_sort_key", lambda row: ())
    monkeypatch.setattr(
        panel_module.absolute_score,
        "summarize",
        lambda _targets, _records, models: (
            observed_models.append(models) or [{"assignment_id": "a-1"}]
        ),
    )
    monkeypatch.setattr(
        panel_module.pairwise_preference,
        "summarize",
        lambda _targets, _records, models: (
            observed_models.append(models) or [{"assignment_id": "a-1"}]
        ),
    )

    assert runner.run() == 1
    assert observed_models == []
    absolute_summary = json.loads(
        (tmp_path / "output" / "absolute_score" / "summary.json").read_text()
    )
    pairwise_summary = json.loads(
        (tmp_path / "output" / "pairwise_preference" / "summary.json").read_text()
    )
    for summary in (absolute_summary, pairwise_summary):
        assert summary["status"] == "incomplete"
        assert summary["missing_models"] == ["gemini"]
        assert summary["failed_semantic_judgment_count"] == 1
