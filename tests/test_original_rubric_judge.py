from __future__ import annotations

import json
from pathlib import Path

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
        rubric_sha256="c" * 64,
        review="trace",
        max_review_chars=None,
        initial_submission=submissions / "s000",
        final_submission=submissions / "s010",
    )


def _completed_record(
    job: OriginalRubricJob,
    score: int,
) -> dict[str, object]:
    return {
        **_job_identity(job),
        "status": "completed",
        "score": score,
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
    study = OriginalRubricStudy(
        source=(tmp_path / "study").resolve(),
        experiment_id="test-study",
        targets=(target,),
    )
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
        "completed": 6,
        "failed": 0,
        "pending": 0,
    }
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
    study = OriginalRubricStudy(
        source=(tmp_path / "study").resolve(),
        experiment_id="test-study",
        targets=(target,),
    )
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
                "master_rubric_name": "rubric.txt",
                "master_rubric_sha256": sha256_text(rubric),
                "task_dir": str(task),
                "review": "trace",
                "max_review_chars": None,
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

    monkeypatch.setattr(original_module, "load_experiment", lambda _path: FakeExperiment())
    monkeypatch.setattr(
        original_module,
        "validate_completed_revision",
        lambda *_args, **_kwargs: None,
    )
    loaded = _load_completed_study(source)
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
    study = OriginalRubricStudy(
        source=(tmp_path / "study").resolve(),
        experiment_id="test-study",
        targets=(target,),
    )
    runner = OriginalRubricEnsembleRunner(
        OriginalRubricEnsembleConfig(
            study_dir=study.source,
            output_dir=study.source / "judgments",
        ),
        load_study=lambda _path: study,
    )
    with pytest.raises(ValueError, match="must not contain"):
        runner.run()
