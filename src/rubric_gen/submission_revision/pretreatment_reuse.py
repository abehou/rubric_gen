"""Explicit reuse of sealed current-format starting rubrics across studies.

The source's experiment identity and blinding scope are preserved. No source
record is rewritten and no missing source rubric is generated implicitly.
"""
from pathlib import Path
import shutil

from rubric_gen.runtime.yaml import load_yaml_strict
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.experiment import Experiment, load_experiment


def scope_id(experiment: Experiment) -> str:
    source = experiment.pretreatment_source
    return source['experiment_id'] if source else experiment.experiment_id


def source_pool(experiment: Experiment) -> Path | None:
    source = experiment.pretreatment_source
    if source is None:
        return None
    path = Path(source['experiment'])
    raw = load_yaml_strict(path.read_text())
    if not isinstance(raw, dict) or 'pretreatment_source' in raw:
        raise ValueError('nested pre-treatment reuse is not supported')
    original = load_experiment(path)
    if original.experiment_id != source['experiment_id']:
        raise ValueError('pre-treatment source experiment identity mismatch')
    for key in ('benchmark', 'tasks_dir', 'seed_generator', 'rubric_paraphrases'):
        if original.payload[key] != experiment.payload[key]:
            raise ValueError(f'pre-treatment source differs: {key}')
    if not set(experiment.task_ids) <= set(original.task_ids):
        raise ValueError('pre-treatment source is missing tasks')
    for key in ('prompt', 'rubric_name', 'rubric_proposer_model', 'rubric_proposer_max_retries'):
        if original.protocol[key] != experiment.protocol[key]:
            raise ValueError(f'pre-treatment source protocol differs: {key}')
    for stage in ('seed', 'paraphrase'):
        if original.dag[stage]['output_dir'] != experiment.dag[stage]['output_dir']:
            raise ValueError(f'pre-treatment source input path differs: {stage}')
    root = Path(source['study_dir'])
    if root.is_symlink() or not root.is_dir():
        raise ValueError('pre-treatment source study is not a regular directory')
    ledger = read_json_object(root / 'study.json', 'pre-treatment source study')
    if ledger.get('experiment_id') != original.experiment_id or ledger.get('status') != 'completed':
        raise ValueError('pre-treatment source study is not completed with the expected identity')
    pool = root / 'pretreatment-rubrics'
    if pool.is_symlink() or not pool.is_dir():
        raise ValueError('pre-treatment source pool is missing or symlinked')
    return pool


def copy_pool_entry(source: Path, destination: Path) -> None:
    """Copy a prevalidated entry without overwriting; caller validates destination."""
    if source.is_symlink() or not source.is_dir():
        raise ValueError('pre-treatment source entry is missing or symlinked')
    for path in source.rglob('*'):
        if path.is_symlink():
            raise ValueError(f'symlink in pre-treatment source: {path}')
    if destination.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(source, destination)
