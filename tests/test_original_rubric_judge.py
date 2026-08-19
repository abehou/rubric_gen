from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from rubric_gen.benchmarks import SubmissionBenchmarkId
import rubric_gen.submission_revision.original_rubric as original_module
from rubric_gen.submission_revision.original_rubric import (
    OriginalRubricEnsembleConfig,
    OriginalRubricEnsembleRunner,
    OriginalRubricJob,
    OriginalRubricStudy,
    OriginalRubricTarget,
    _job_identity,
    _load_completed_study,
)
from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.reward_hacking.protocol import PRIMARY_RH_MODELS


AUTORUBRIC = """RUBRIC: Test

Criterion 1: Quality
Levels: A=100 B=0
[A]: Complete.
[B]: Missing.
"""


def _target(tmp_path: Path) -> OriginalRubricTarget:
    experiment = tmp_path / "study" / "experiment"
    submissions = experiment / "submissions"
    for submission_id, marker in (("s000", "a"), ("s010", "b")):
        submission = submissions / submission_id
        submission.mkdir(parents=True)
        (submission / "snapshot.json").write_text(
            json.dumps(
                {
                    "workspace_sha256": marker * 64,
                    "trajectory_sha256": marker * 64,
                }
            )
        )
    return OriginalRubricTarget(
        assignment_id="da-1-1--rep-001--base-static",
        task_id="da-1-1",
        replicate=1,
        condition_id="base-static",
        benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,
        experiment_dir=experiment,
        task_dir=tmp_path / "tasks" / "da-1-1",
        rubric_name="rubric.txt",
        rubric_sha256=sha256_text(AUTORUBRIC),
        review="trace",
        max_review_chars=None,
        initial_submission=submissions / "s000",
        final_submission=submissions / "s010",
    )


def _study(
    tmp_path: Path,
    *targets: OriginalRubricTarget,
    max_calls: int = 1_000_000,
) -> OriginalRubricStudy:
    return OriginalRubricStudy(
        source=(tmp_path / "study").resolve(),
        experiment_id="test-study",
        targets=targets,
        mechanistic_max_calls=max_calls,
        mechanistic_max_request_bytes=1_000_000_000,
        mechanistic_max_output_tokens=1_000_000_000,
    )


class FakeJudge:
    def __init__(self, job: OriginalRubricJob) -> None:
        self.job = job
        self.rubric = SimpleNamespace(
            text=AUTORUBRIC,
            sha256=sha256_text(AUTORUBRIC),
        )

    def scoring_identity(self) -> dict[str, object]:
        return {
            "judge_source_sha256": "1" * 64,
            "judge_runner_sha256": "2" * 64,
            "scorer_module_sha256": "3" * 64,
            "effective_judge_model": self.job.model,
            "judge_api_base": None,
            "benchmark": self.job.target.benchmark.value,
            "grading_engine": "autorubric-criterion",
            "review_mode": self.job.target.review,
            "max_review_chars": self.job.target.max_review_chars,
            "rubric_source": "task-rubric",
            "rubric_set_id": None,
            "rubric_id": None,
            "structured_rubric_sha256": None,
            "rendered_rubric_sha256": self.job.target.rubric_sha256,
            "manifest_sha256": None,
        }

    def review_inputs(self, submission: Path) -> tuple[str, str]:
        snapshot = json.loads((submission / "snapshot.json").read_text())
        return (
            f"review:{snapshot['trajectory_sha256']}",
            f"answer:{snapshot['workspace_sha256']}",
        )


def _fake_build_judge(
    _config: OriginalRubricEnsembleConfig,
    job: OriginalRubricJob,
) -> FakeJudge:
    return FakeJudge(job)


def _completed_record(
    job: OriginalRubricJob,
    score: int,
) -> dict[str, object]:
    judge = FakeJudge(job)
    review_text, answer_text = judge.review_inputs(job.submission)
    return {
        **_job_identity(job),
        "status": "completed",
        "score": score,
        "scoring_identity": judge.scoring_identity(),
        "review_input_sha256": sha256_text(review_text),
        "answer_input_sha256": sha256_text(answer_text),
        "score_validation": f"sealed/{job.model}/{job.boundary}/score.json",
        "score_validation_sha256": "1" * 64,
        "evaluation": f"sealed/{job.model}/{job.boundary}/evaluation.json",
        "evaluation_sha256": "2" * 64,
        "usage": f"sealed/{job.model}/{job.boundary}/usage.json",
        "usage_sha256": "3" * 64,
    }


def test_original_rubric_ensemble_scores_boundaries_and_resumes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    phases: list[dict[str, object]] = []

    class RecordingProgress:
        def __init__(
            self,
            *,
            total: int,
            description: str,
            unit: str,
        ) -> None:
            self.phase = {
                "total": total,
                "description": description,
                "unit": unit,
                "updates": 0,
            }
            phases.append(self.phase)

        def __enter__(self) -> RecordingProgress:
            return self

        def __exit__(self, *_args: object) -> None:
            return None

        def update(self) -> None:
            self.phase["updates"] = int(self.phase["updates"]) + 1

        def set_status(self, _status: str) -> None:
            return None

    monkeypatch.setattr(original_module, "TerminalProgress", RecordingProgress)
    target = _target(tmp_path)
    study = _study(tmp_path, target)
    output = tmp_path / "judgments"
    config = OriginalRubricEnsembleConfig(
        study_dir=study.source,
        output_dir=output,
        max_concurrency=2,
        resume=True,
    )
    model_offsets = {
        model: index for index, model in enumerate(PRIMARY_RH_MODELS)
    }
    observed: list[tuple[str, str]] = []

    def evaluate(
        _config: OriginalRubricEnsembleConfig,
        job: OriginalRubricJob,
    ) -> dict[str, object]:
        observed.append((job.model, job.boundary))
        score = 30 + model_offsets[job.model]
        if job.boundary == "final":
            score += 40
        return _completed_record(job, score)

    runner = OriginalRubricEnsembleRunner(
        config,
        load_study=lambda _path: study,
        evaluate_job=evaluate,
        build_judge=_fake_build_judge,
    )
    assert runner.run() == 0
    assert sorted(observed) == sorted(
        (model, boundary)
        for model in PRIMARY_RH_MODELS
        for boundary in ("initial", "final")
    )
    summary = json.loads((output / "summary.json").read_text())
    assert summary["status"] == "completed"
    assert summary["totals"] == {
        "jobs": 6,
        "semantic_judgments": 6,
        "completed": 6,
        "failed": 0,
        "pending": 0,
    }
    assert summary["predispatch_plan"]["base_totals"]["calls"] == 6
    assert summary["predispatch_plan"]["maximum_totals"]["calls"] == 12
    assert summary["predispatch_plan"]["outer_attempt_limit"] == 2
    result = summary["assignments"][target.assignment_id]
    assert result["ensemble"] == {
        "status": "completed",
        "initial_mean": 31.0,
        "final_mean": 71.0,
        "mean_delta": 40.0,
        "initial_median": 31.0,
        "final_median": 71.0,
        "median_delta": 40.0,
        "majority_winner": "final",
        "consensus_winner": "final",
    }
    assert summary["conditions"]["base-static"]["mean_delta"] == 40.0
    assert phases == [{
        "total": 6,
        "description": "original-rubric ensemble judging",
        "unit": "judgment",
        "updates": 6,
    }]

    validated: list[tuple[str, str]] = []

    def validate(
        _config: OriginalRubricEnsembleConfig,
        job: OriginalRubricJob,
    ) -> dict[str, object]:
        validated.append((job.model, job.boundary))
        score = 30 + model_offsets[job.model]
        if job.boundary == "final":
            score += 40
        return _completed_record(job, score)

    resumed = OriginalRubricEnsembleRunner(
        OriginalRubricEnsembleConfig(
            study_dir=study.source,
            output_dir=output,
            max_concurrency=1,
            resume=True,
        ),
        load_study=lambda _path: study,
        evaluate_job=lambda _config, _job: pytest.fail("completed job was rerun"),
        validate_job=validate,
        build_judge=_fake_build_judge,
    )
    assert resumed.run() == 0
    assert len(validated) == 6
    assert phases[1:] == [
        {
            "total": 6,
            "description": "validating resumed judgments",
            "unit": "judgment",
            "updates": 6,
        },
        {
            "total": 6,
            "description": "original-rubric ensemble judging",
            "unit": "judgment",
            "updates": 6,
        },
    ]


def test_original_rubric_judge_rejects_nonempty_output_without_resume(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    study = _study(tmp_path, target)
    output = tmp_path / "judgments"
    output.mkdir()
    (output / "foreign.txt").write_text("do not overwrite")
    runner = OriginalRubricEnsembleRunner(
        OriginalRubricEnsembleConfig(study_dir=study.source, output_dir=output),
        load_study=lambda _path: study,
    )
    with pytest.raises(FileExistsError, match="--resume"):
        runner.run()
    assert (output / "foreign.txt").read_text() == "do not overwrite"


def test_load_completed_study_uses_the_sealed_master_not_optimizer_paraphrase(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = tmp_path / "study"
    experiment_spec = tmp_path / "experiment.yaml"
    experiment_spec.write_text("test")
    task = tmp_path / "tasks" / "da-1-1"
    (task / "tests").mkdir(parents=True)
    rubric = "Criterion 1: Valid result\nLevels: A=100 B=50 C=0\n"
    (task / "tests" / "rubric.txt").write_text(rubric)
    assignment = {
        "assignment_id": "da-1-1--rep-001--base-static",
        "task_id": "da-1-1",
        "replicate": 1,
        "condition_id": "base-static",
        "execution_order": 1,
    }
    record = {
        **assignment,
        "experiment_dir": "experiments/da-1-1/rep-001/base-static",
        "status": "completed",
    }
    source.mkdir()
    (source / "study.json").write_text(
        json.dumps(
            {
                "kind": "rubric-gen-randomized-revision-study",
                "status": "completed",
                "experiment_path": str(experiment_spec),
                "experiment_id": "test-study",
                    "seed_run_dir": str(tmp_path / "seeds"),
                    "paraphrase_run_dir": str(tmp_path / "paraphrases"),
                "records": [record],
            }
        )
    )
    experiment_dir = source / record["experiment_dir"]
    (experiment_dir / "rubric").mkdir(parents=True)
    (experiment_dir / "rubric" / "r0000.txt").write_text(rubric)
    (experiment_dir / "submissions" / "s000").mkdir(parents=True)
    (experiment_dir / "submissions" / "s010").mkdir(parents=True)
    (experiment_dir / "manifest.json").write_text(
        json.dumps(
            {
                "provider": "vllm",
                "model": "solver-model",
                "solver_base_url": "http://solver.test/v1",
                "master_rubric_name": "rubric.txt",
                "master_rubric_sha256": sha256_text(rubric),
                "task_dir": str(task),
                "review": "trace",
                "max_review_chars": None,
                "judge_model": "judge-model",
                "judge_base_url": "http://judge.test/v1",
                "rubric_proposer_model": "proposer-model",
                "rubric_proposer_base_url": "http://proposer.test/v1",
                "rubric_semantic_judge_model": "reviewer-model",
                "rubric_semantic_judge_base_url": "http://reviewer.test/v1",
                "feedback_simulator": {
                    "implementation_sha256": "1" * 64,
                    "model": "simulator-model",
                    "base_url": "http://simulator.test/v1/",
                    "max_output_tokens": 1024,
                    "max_aspects": 2,
                    "max_retries": 1,
                },
            }
        )
    )
    (experiment_dir / "state.json").write_text(
        json.dumps({"submission_ids": ["s000", "s010"]})
    )

    class FakeExperiment:
        experiment_id = "test-study"
        benchmark = SubmissionBenchmarkId.BIOMNIBENCH_DA
        assignments = (assignment,)
        outcome_audit = {
            "mechanistic_max_calls": 100,
            "mechanistic_max_request_bytes": 1_000_000,
            "mechanistic_max_output_tokens": 1_000_000,
        }

    monkeypatch.setattr(original_module, "load_experiment", lambda _path: FakeExperiment())
    validations: list[dict[str, object]] = []

    def validate(*_args, **kwargs) -> None:
        validations.append(kwargs)

    monkeypatch.setattr(original_module, "validate_completed_revision", validate)
    loaded = _load_completed_study(source)
    assert validations[-1]["vllm_endpoints"] == {
        "solver-model": "http://solver.test/v1",
        "judge-model": "http://judge.test/v1",
        "proposer-model": "http://proposer.test/v1",
        "reviewer-model": "http://reviewer.test/v1",
        "simulator-model": "http://simulator.test/v1",
    }
    assert validations[-1]["judgment_reuse_root"] == (
        source / "shared-judgments"
    )
    assert loaded.targets[0].rubric_sha256 == sha256_text(rubric)
    assert loaded.targets[0].initial_submission.name == "s000"
    assert loaded.targets[0].final_submission.name == "s010"

    (experiment_dir / "rubric" / "r0000.txt").write_text("optimizer paraphrase")
    assert _load_completed_study(source).targets[0].rubric_sha256 == sha256_text(
        rubric
    )
    (task / "tests" / "rubric.txt").write_text("changed")
    with pytest.raises(RuntimeError, match="master rubric changed"):
        _load_completed_study(source)


def test_original_rubric_judge_rejects_output_inside_source(tmp_path: Path) -> None:
    target = _target(tmp_path)
    study = _study(tmp_path, target)
    runner = OriginalRubricEnsembleRunner(
        OriginalRubricEnsembleConfig(
            study_dir=study.source,
            output_dir=study.source / "judgments",
        ),
        load_study=lambda _path: study,
    )
    with pytest.raises(ValueError, match="must not contain"):
        runner.run()


def test_original_rubric_judge_reuses_identical_semantic_requests(
    tmp_path: Path,
) -> None:
    first = _target(tmp_path)
    second = replace(
        first,
        assignment_id="da-1-1--rep-001--adaptive-replacement",
        condition_id="adaptive-replacement",
    )
    study = _study(tmp_path, first, second)
    output = tmp_path / "judgments"
    observed: list[tuple[str, str, str]] = []

    def evaluate(
        _config: OriginalRubricEnsembleConfig,
        job: OriginalRubricJob,
    ) -> dict[str, object]:
        observed.append(job.key)
        score = 70 if job.boundary == "final" else 30
        return _completed_record(job, score)

    runner = OriginalRubricEnsembleRunner(
        OriginalRubricEnsembleConfig(
            study_dir=study.source,
            output_dir=output,
            max_retries=0,
        ),
        load_study=lambda _path: study,
        evaluate_job=evaluate,
        build_judge=_fake_build_judge,
    )
    assert runner.run() == 0
    assert len(observed) == 6

    summary = json.loads((output / "summary.json").read_text())
    assert summary["totals"] == {
        "jobs": 12,
        "semantic_judgments": 6,
        "completed": 12,
        "failed": 0,
        "pending": 0,
    }
    assert summary["predispatch_plan"]["dispatch_count"] == 6
    assert summary["predispatch_plan"]["logical_reference_count"] == 12
    semantic_counts: dict[str, int] = {}
    for record in summary["records"]:
        semantic_id = record["semantic_judgment_id"]
        semantic_counts[semantic_id] = semantic_counts.get(semantic_id, 0) + 1
    assert sorted(semantic_counts.values()) == [2] * 6
    assert summary["conditions"]["base-static"]["mean_delta"] == 40.0
    assert summary["conditions"]["adaptive-replacement"]["mean_delta"] == 40.0

    validated: list[tuple[str, str, str]] = []

    def validate(
        _config: OriginalRubricEnsembleConfig,
        job: OriginalRubricJob,
    ) -> dict[str, object]:
        validated.append(job.key)
        score = 70 if job.boundary == "final" else 30
        return _completed_record(job, score)

    resumed = OriginalRubricEnsembleRunner(
        OriginalRubricEnsembleConfig(
            study_dir=study.source,
            output_dir=output,
            max_retries=0,
            resume=True,
        ),
        load_study=lambda _path: study,
        evaluate_job=lambda _config, _job: pytest.fail(
            "deduplicated completed judgment was rerun"
        ),
        validate_job=validate,
        build_judge=_fake_build_judge,
    )
    assert resumed.run() == 0
    assert len(validated) == 6


def test_original_rubric_judge_rejects_cap_before_output_or_dispatch(
    tmp_path: Path,
) -> None:
    target = _target(tmp_path)
    study = _study(tmp_path, target, max_calls=1)
    output = tmp_path / "judgments"
    dispatched = False

    def evaluate(
        _config: OriginalRubricEnsembleConfig,
        job: OriginalRubricJob,
    ) -> dict[str, object]:
        nonlocal dispatched
        dispatched = True
        return _completed_record(job, 50)

    runner = OriginalRubricEnsembleRunner(
        OriginalRubricEnsembleConfig(
            study_dir=study.source,
            output_dir=output,
            max_retries=0,
        ),
        load_study=lambda _path: study,
        evaluate_job=evaluate,
        build_judge=_fake_build_judge,
    )
    with pytest.raises(
        RuntimeError,
        match="predispatch calls exceeds its hard cap",
    ):
        runner.run()
    assert not output.exists()
    assert not dispatched
