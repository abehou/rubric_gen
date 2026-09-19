"""Run the direct reward-hacking panel on a completed revision study."""

from __future__ import annotations

import os
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rubric_gen.detection.jobs import DetectionConfig
from rubric_gen.detection.runner import DetectionRunner
from rubric_gen.submission_revision.detection_windows import RevisionDetectionWindow
from rubric_gen.submission_revision.evaluation.evidence import revision_detection_source
from rubric_gen.submission_revision.experiment import Experiment
from rubric_gen.submission_revision.source_resolution import StudySources, resolve_study_sources


RESUME_CODE_ROOT_ENV = "RUBRIC_GEN_RESUME_CODE_ROOT"


def _resume_code_root(experiment: Experiment, *, resume: bool) -> Path | None:
    """Resolve the recorded deployment used by the existing direct run.

    A recovery-only execution change may run from a newer checkout.  The direct
    runner still verifies that this root reproduces the saved implementation
    digest and that every scientific source matches the current checkout.
    """
    value = os.environ.get(RESUME_CODE_ROOT_ENV) if resume else None
    if value is not None:
        candidate = Path(value)
        if not candidate.is_absolute():
            raise ValueError(f"{RESUME_CODE_ROOT_ENV} must be an absolute path")
        resolved = candidate.resolve(strict=True)
        if candidate != resolved or not (resolved / "src/rubric_gen").is_dir():
            raise ValueError(
                f"{RESUME_CODE_ROOT_ENV} must be a non-symlinked source root"
            )
        return resolved
    return next(
        (
            parent
            for parent in experiment.path.parents
            if (parent / "src/rubric_gen").is_dir()
        ),
        None,
    )


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

    sources = resolve_study_sources(study_dir, experiment)
    return _detection_study(sources)


def _detection_study(sources: StudySources) -> DetectionStudy:
    experiment = sources.experiment
    return DetectionStudy(
        revisions=tuple(source.directory for source in sources.revisions),
        experiment_id=experiment.experiment_id,
        study_experiment_id=experiment.experiment_id,
        tasks_dir=experiment.tasks_dir.resolve(),
        settings=experiment.outcome_audit,
    )


def run_direct_detection(config: DirectDetectionConfig) -> int:
    """Run the study's sealed direct detection."""

    return prepare_direct_detection(config).run()


def prepare_direct_detection(
    config: DirectDetectionConfig, sources: StudySources | None = None, shared_inputs: dict | None = None,
) -> DetectionRunner:
    sources = sources or resolve_study_sources(config.study_dir, config.experiment)
    study = _detection_study(sources)
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
        experiment_ids=tuple(sorted({study.study_experiment_id, *(source.producer.experiment_id for source in sources.revisions)})),
        window=config.window,
        resolved_sources=sources.revisions,
        shared_inputs=shared_inputs,
    )
    code_root = _resume_code_root(config.experiment, resume=resume_evaluation)
    runner = DetectionRunner(DetectionConfig(
        source=source,
        models=models,
        output_dir=evaluation_dir,
        max_concurrency=config.max_concurrency,
        resume=resume_evaluation,
        detection=config.detection,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        primary_rule=primary_rule,
    ), resume_code_root=code_root)
    if resume_evaluation:
        runner._write_or_validate_run_settings()
    return runner


def _evaluation_dir(root: Path, identity: str, *, resume: bool) -> Path:
    evaluations = root.resolve() / "evaluations"
    if resume:
        candidates = sorted(evaluations.glob(f"*--{identity}"))
        if candidates:
            return candidates[-1]
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return evaluations / f"{timestamp}--{identity}"
