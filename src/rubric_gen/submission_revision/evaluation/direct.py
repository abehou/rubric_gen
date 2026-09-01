"""Run the direct reward-hacking panel on a completed revision study."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rubric_gen.detection.jobs import DetectionConfig
from rubric_gen.detection.runner import DetectionRunner
from rubric_gen.submission_revision.detection_windows import RevisionDetectionWindow
from rubric_gen.submission_revision.evaluation.evidence import revision_detection_source
from rubric_gen.submission_revision.experiment import Experiment
from rubric_gen.submission_revision.study_layout import resolve_study_experiment


@dataclass(frozen=True)
class DirectDetectionConfig:
    experiment: Experiment
    study_dir: Path
    output_dir: Path
    max_concurrency: int
    resume: bool
    window: RevisionDetectionWindow
    detection: str = "rh"

    def __post_init__(self) -> None:
        RevisionDetectionWindow(self.window)


@dataclass(frozen=True)
class DetectionStudy:
    revisions: tuple[Path, ...]
    experiment_id: str
    study_experiment_id: str
    tasks_dir: Path
    settings: dict[str, object]


def load_detection_study(study_dir: Path, experiment: Experiment) -> DetectionStudy:
    """Validate a terminal study and return its completed revisions."""

    source = study_dir.resolve()
    study_path = source / "study.json"
    try:
        study = json.loads(study_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid randomized benchmark study: {source}") from exc
    if (
        study.get("kind") != "rubric-gen-randomized-revision-study"
        or study.get("status") not in {"completed", "failed"}
        or type(study.get("experiment_path")) is not str
        or type(study.get("experiment_id")) is not str
        or type(study.get("seed_run_dir")) is not str
        or type(study.get("paraphrase_run_dir")) is not str
        or study.get("pretreatment_rubric_root")
        != str(source / "pretreatment-rubrics")
    ):
        raise ValueError(f"unsupported benchmark study: {source}")

    if study["experiment_path"] != str(experiment.path):
        raise ValueError(f"benchmark study uses a different experiment: {source}")
    records = study.get("records")
    if not isinstance(records, list) or any(
        not isinstance(item, dict) for item in records
    ):
        raise ValueError(f"benchmark study has invalid records: {source}")
    assignments = {
        item.assignment_id: item for item in experiment.assignments
    }
    record_ids = [str(record.get("assignment_id")) for record in records]
    if len(record_ids) != len(set(record_ids)) or set(record_ids) != set(assignments):
        raise ValueError(f"benchmark study ledger differs from its experiment: {source}")

    revisions: list[Path] = []
    for record in records:
        status = record.get("status")
        if status not in {"completed", "failed", "invalid"}:
            raise ValueError(
                "benchmark study must reach a terminal checkpoint before audit: "
                f"{source}"
            )
        if status == "completed":
            assignment = assignments[str(record["assignment_id"])]
            revisions.append(
                resolve_study_experiment(source, record, assignment).resolve()
            )
    if len(revisions) != len(set(revisions)):
        raise ValueError("duplicate benchmark revision experiment")
    if not revisions:
        raise ValueError("benchmark study has no completed assignments to audit")
    return DetectionStudy(
        revisions=tuple(revisions),
        experiment_id=experiment.experiment_id,
        study_experiment_id=str(study["experiment_id"]),
        tasks_dir=experiment.tasks_dir.resolve(),
        settings=experiment.outcome_audit,
    )


def run_direct_detection(config: DirectDetectionConfig) -> int:
    """Run the study's sealed direct detection."""

    study = load_detection_study(config.study_dir, config.experiment)
    models = tuple(study.settings.get("models", ()))
    primary_rule = str(study.settings["primary_rule"])
    max_input_tokens = int(study.settings["max_input_tokens"])
    max_output_tokens = int(study.settings["max_output_tokens"])
    identity = (
        f"ensemble--detect-{config.detection}--experiment-{study.experiment_id}"
        f"--source-{study.study_experiment_id}"
        f"--window-{config.window.value}"
        f"--max-input-{max_input_tokens}"
        f"--max-output-{max_output_tokens}"
        f"--primary-{primary_rule}"
    )
    evaluation_dir = _evaluation_dir(
        config.output_dir,
        identity,
        resume=config.resume,
    )
    resume_evaluation = config.resume and evaluation_dir.is_dir()
    source = revision_detection_source(
        study.revisions,
        tasks_dir=study.tasks_dir,
        experiment_ids=(study.study_experiment_id,),
        window=config.window,
    )
    result = DetectionRunner(DetectionConfig(
        source=source,
        models=models,
        output_dir=evaluation_dir,
        max_concurrency=config.max_concurrency,
        resume=resume_evaluation,
        detection=config.detection,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        primary_rule=primary_rule,
    )).run()
    print(
        "Wrote direct reward-hacking judgments "
        f"for {config.window.value}: {evaluation_dir / 'summary.json'}"
    )
    return result


def _evaluation_dir(root: Path, identity: str, *, resume: bool) -> Path:
    evaluations = root.resolve() / "evaluations"
    if resume:
        candidates = sorted(evaluations.glob(f"*--{identity}"))
        if candidates:
            return candidates[-1]
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return evaluations / f"{timestamp}--{identity}"
