"""Resolve consumer membership to its documented producer without rewriting evidence."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from weakref import WeakValueDictionary
from threading import Lock

_PREPARED_LOCATIONS = WeakValueDictionary()
_LOCATION_LOCK = Lock()

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.assignments import ExperimentAssignment
from rubric_gen.submission_revision.execution_scope import terminal_records
from rubric_gen.submission_revision.experiment import Experiment, load_experiment
from rubric_gen.submission_revision.study_layout import resolve_study_experiment


@dataclass(frozen=True)
class RevisionSource:
    assignment: ExperimentAssignment
    consumer_experiment_id: str
    directory: Path
    producer_directory: Path
    producer: Experiment
    manifest: dict
    state: dict


@dataclass(frozen=True)
class StudySources:
    experiment: Experiment
    root: Path
    ledger: dict
    revisions: tuple[RevisionSource, ...]


def resolve_study_sources(study_dir: Path, experiment: Experiment, *, require_terminal: bool = True) -> StudySources:
    root = study_dir.resolve()
    ledger = read_json_object(root / "study.json", "source study")
    if (ledger.get("kind") != "rubric-gen-randomized-revision-study"
            or ledger.get("experiment_id") != experiment.experiment_id
            or ledger.get("experiment_path") != str(experiment.path)
            or ledger.get("seed_run_dir") != str(Path(experiment.dag['seed']['output_dir']).resolve())
            or ledger.get("paraphrase_run_dir") != str(Path(experiment.dag['paraphrase']['output_dir']).resolve())
            or ledger.get("pretreatment_rubric_root") != str(root / "pretreatment-rubrics")):
        raise ValueError(f"source study identity differs from the configured experiment: {root}")
    if require_terminal:
        selected = terminal_records(experiment, ledger)
    else:
        from .execution_scope import selected_records
        selected = selected_records(experiment, ledger)

    assignments = {a.assignment_id: a for a in experiment.assignments}
    producers: dict[Path, tuple[Experiment, dict]] = {}
    cohort = None
    sources = []
    for record in selected:
        assignment = assignments[record['assignment_id']]
        directory = resolve_study_experiment(root, record, assignment).resolve()
        if record['status'] != 'completed':
            continue
        manifest = read_json_object(directory / 'manifest.json', 'source revision manifest')
        state = read_json_object(directory / 'state.json', 'source revision state')
        producer, producer_directory = experiment, directory
        receipt_path = directory / 'consumer-import.json'
        if receipt_path.exists():
            receipt = read_json_object(receipt_path, 'assignment import')
            if cohort is None:
                cohort = read_json_object(root.parent.parent / 'consumer-cohort.json', 'consumer cohort')
            if (receipt.get('kind') != 'v2_to_v21_assignment_import'
                    or receipt.get('consumer_experiment_id') != experiment.experiment_id
                    or receipt.get('consumer_trace_version') != experiment.protocol.get('red_team_trace_version')
                    or cohort.get('consumer_experiment_id') != experiment.experiment_id
                    or Path(cohort['consumer_study_root']).resolve() != root
                    or receipt.get('producer_experiment_id') != cohort.get('producer_experiment_id')):
                raise ValueError(f'import belongs to another consumer or producer: {receipt_path}')
            entries = [entry for entry in cohort['imports'] if entry['assignment_id'] == assignment.assignment_id]
            if (len(entries) != 1 or entries[0]['experiment_dir'] != record['experiment_dir']
                    or entries[0]['producer_manifest_sha256'] != receipt.get('producer_manifest_sha256')
                    or sha256_file(directory / 'manifest.json') != receipt.get('producer_manifest_sha256')):
                raise ValueError(f'import assignment/source binding differs: {receipt_path}')
            producer_root = Path(cohort['producer_study_root']).resolve()
            if producer_root not in producers:
                producer_ledger = read_json_object(producer_root / 'study.json', 'producer study')
                producer = load_experiment(Path(producer_ledger['experiment_path']))
                if producer.experiment_id != producer_ledger.get('experiment_id'):
                    raise ValueError(f'producer config differs from ledger: {producer_root}')
                terminal_records(producer, producer_ledger)
                producers[producer_root] = producer, producer_ledger
            producer, producer_ledger = producers[producer_root]
            producer_assignments = {a.assignment_id: a for a in producer.assignments}
            producer_assignment = producer_assignments.get(assignment.assignment_id)
            if (producer_assignment != assignment
                    or producer.experiment_id != receipt['producer_experiment_id']
                    or producer.protocol.get('red_team_trace_version') != receipt.get('producer_trace_version')):
                raise ValueError(f'import producer assignment differs: {receipt_path}')
            rows = [r for r in producer_ledger['records'] if r['assignment_id'] == assignment.assignment_id]
            if len(rows) != 1 or rows[0]['status'] != 'completed':
                raise ValueError(f'import producer is not completed: {receipt_path}')
            producer_directory = resolve_study_experiment(producer_root, rows[0], producer_assignment).resolve()
            if sha256_file(producer_directory / 'manifest.json') != receipt['producer_manifest_sha256']:
                raise ValueError(f'import differs from documented source tree: {receipt_path}')
        identity = {k: v for k, v in assignment.record_identity().items() if k != 'experiment_dir'}
        identity.update(kind='rubric-gen-submission-revision-experiment', experiment_id=producer.experiment_id,
                        benchmark=str(producer.benchmark), task_dir=str(producer.task_dir(assignment.task_id)))
        if (producer.protocol.get('red_team_trace_version') is not None
                and producer.condition(assignment.condition_id)['rubric_policy'] == 'red_team_trace'):
            identity['red_team_trace_version'] = producer.protocol['red_team_trace_version']
        if any(manifest.get(k) != v for k, v in identity.items()):
            raise ValueError(f'revision producer identity mismatch: {directory}')
        sources.append(RevisionSource(assignment, experiment.experiment_id, directory,
                                      producer_directory, producer, manifest, state))
    if not sources:
        raise ValueError('source study has no completed assignments')
    with _LOCATION_LOCK:
        for source in sources:
            _PREPARED_LOCATIONS[source.directory] = source
    return StudySources(experiment, root, ledger, tuple(sources))


def relocated_workspace(submission: Path, recorded: Path) -> Path:
    """Map only an explicitly imported producer path; never edit status.json."""
    expected = submission / 'workspace'
    if recorded == expected or submission.parent.name != 'submissions':
        return recorded
    revision = submission.parent.parent
    if not (revision / 'consumer-import.json').is_file():
        return recorded
    with _LOCATION_LOCK:
        source = _PREPARED_LOCATIONS.get(revision.resolve())
    if source is not None:
        old = source.producer_directory / 'submissions' / submission.name / 'workspace'
        if recorded != old:
            raise ValueError(f'status path differs from documented producer: {submission}')
        return expected
    # Standalone readers resolve the same documented source; an audit invocation
    # retains StudySources and uses the already prepared location map above.
    # Assignment paths have a fixed layout owned by study_layout.
    for root in revision.parents:
        if (root / 'study.json').is_file():
            ledger = read_json_object(root / 'study.json', 'consumer study')
            sources = resolve_study_sources(root, load_experiment(Path(ledger['experiment_path'])))
            for source in sources.revisions:
                if source.directory == revision.resolve():
                    old = source.producer_directory / 'submissions' / submission.name / 'workspace'
                    if recorded != old:
                        raise ValueError(f'status path differs from documented producer: {submission}')
                    return expected
            break
    raise ValueError(f'imported submission has no documented source: {submission}')


def assemble_consumer_ledger(experiment: Experiment, recovery: dict, producer: dict) -> dict:
    """Merge completed scoped rows into the full ledger, preserving excluded rows."""
    assignments = {a.assignment_id: a for a in experiment.assignments}
    rows = producer.get('records', [])
    if {r.get('assignment_id') for r in rows} != set(assignments) or len(rows) != len(assignments):
        raise ValueError('producer ledger must contain the full experiment assignment set')
    recovery_rows = recovery.get('records', [])
    recovered = {r['assignment_id']: r for r in recovery_rows if r.get('status') == 'completed'}
    if len({r['assignment_id'] for r in recovery_rows}) != len(recovery_rows):
        raise ValueError('duplicate recovery assignment')
    selected = {a.assignment_id for a in experiment.execution_assignments}
    if not set(recovered) <= selected:
        raise ValueError('recovery completed an excluded assignment')
    result = dict(recovery)
    merged = []
    for row in rows:
        assignment = assignments[row['assignment_id']]
        if any(row.get(k) != v for k, v in assignment.record_identity().items()):
            raise ValueError('producer row identity mismatch')
        candidate = recovered.get(assignment.assignment_id, row)
        if any(candidate.get(k) != v for k, v in assignment.record_identity().items()):
            raise ValueError('recovery row identity mismatch')
        if assignment.assignment_id in selected and candidate.get('status') != 'completed':
            raise ValueError(f'consumer still has missing work: {assignment.assignment_id}')
        merged.append(dict(candidate))
    root = Path(experiment.dag['revise']['output_dir']).resolve()
    result.update(kind='rubric-gen-randomized-revision-study', experiment_id=experiment.experiment_id,
                  experiment_path=str(experiment.path), records=merged,
                  status='completed_scope' if experiment.execution_conditions else 'completed',
                  seed_run_dir=str(Path(experiment.dag['seed']['output_dir']).resolve()),
                  paraphrase_run_dir=str(Path(experiment.dag['paraphrase']['output_dir']).resolve()),
                  pretreatment_rubric_root=str(root / 'pretreatment-rubrics'))
    result.pop('execution_assignment_ids', None)
    if experiment.execution_conditions:
        result['execution_conditions'] = list(experiment.execution_conditions)
    terminal_records(experiment, result)
    return result
