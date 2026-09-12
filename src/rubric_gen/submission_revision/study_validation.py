"""Validate a completed randomized submission-revision experiment."""

from __future__ import annotations

from pathlib import Path

from rubric_gen.submission_revision.experiment import Experiment
from rubric_gen.submission_revision.assignments import ExperimentAssignment
from rubric_gen.submission_revision.study_validation_artifacts import (
    validate_revision_artifacts,
)
from rubric_gen.submission_revision.study_validation_context import (
    build_validation_context,
    validate_manifest,
    validate_state,
)


def validate_completed_revision(
    experiment_dir: Path,
    assignment: ExperimentAssignment,
    experiment: Experiment,
    seed_run_dir: Path,
    paraphrase_run_dir: Path,
    *, source=None,
) -> None:
    if source is not None:
        if source.directory != experiment_dir.resolve() or source.assignment != assignment:
            raise ValueError('completed revision differs from its resolved assignment source')
        if source.producer_directory != source.directory:
            from .artifacts import read_json_object
            if (source.manifest != read_json_object(source.producer_directory / 'manifest.json', 'producer manifest')
                    or source.state != read_json_object(source.producer_directory / 'state.json', 'producer state')):
                raise ValueError('imported scientific manifest/state differs from its producer')
            # Replay sealed producer receipts at their documented paths. Consumer
            # evidence is independently checked before each audit dispatch.
            experiment_dir = source.producer_directory
        experiment = source.producer
        seed_run_dir = Path(experiment.dag['seed']['output_dir'])
        paraphrase_run_dir = Path(experiment.dag['paraphrase']['output_dir'])
    context = build_validation_context(
        experiment_dir,
        assignment,
        experiment,
        seed_run_dir,
        paraphrase_run_dir, source=source,
    )
    validate_manifest(context)
    validate_state(context)
    validate_revision_artifacts(context)
