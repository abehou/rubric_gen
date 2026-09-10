"""Explicit reuse of sealed current-format starting rubrics across studies.

The source's experiment identity and blinding scope are preserved. No source
record is rewritten and no missing source rubric is generated implicitly.
"""
from pathlib import Path
import shutil

from rubric_gen.runtime.yaml import load_yaml_strict
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.experiment import Experiment, load_experiment
from rubric_gen.submission_revision.execution_scope import terminal_records


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
    for key in ('benchmark', 'seed_generator', 'rubric_paraphrases'):
        if original.payload[key] != experiment.payload[key]:
            raise ValueError(f'pre-treatment source differs: {key}')
    if not set(experiment.task_ids) <= set(original.task_ids):
        raise ValueError('pre-treatment source is missing tasks')
    for key in ('prompt', 'rubric_name', 'rubric_proposer_model', 'rubric_proposer_max_retries'):
        if original.protocol[key] != experiment.protocol[key]:
            raise ValueError(f'pre-treatment source protocol differs: {key}')
    # Storage relocation preserves current-format input identity. Native seed,
    # paraphrase, and complete generation replay still validate the contents.
    if original.payload['tasks_dir'] != experiment.payload['tasks_dir']:
        for task in experiment.task_ids:
            for name in ('instruction.md', 'tests/rubric.txt'):
                _same_file(original.task_dir(task) / name, experiment.task_dir(task) / name)
    for stage in ('seed', 'paraphrase'):
        old = Path(original.dag[stage]['output_dir'])
        new = Path(experiment.dag[stage]['output_dir'])
        if old == new:
            continue
        if stage == 'seed':
            for task in experiment.task_ids:
                for rep in range(1, experiment.replicates + 1):
                    name = Path('tasks') / task / f'rep-{rep:03d}' / 'manifest.json'
                    _same_file(old / name, new / name)
        else:
            from .trace_defense_prompts import VERSION
            if experiment.protocol.get('red_team_trace_version') == VERSION:
                from .paraphrase_validation import validate_paraphrase_run
                validate_paraphrase_run(old, original)
                validate_paraphrase_run(new, experiment)
                for task in experiment.task_ids:
                    for variant in (int(experiment.rubric_paraphrases['selected_variant']), int(experiment.rubric_paraphrases['development_variant'])):
                        for suffix in ('txt','json'):
                            name = Path('tasks') / task / f'variant-{variant:03d}.{suffix}'
                            _same_file(old / name, new / name)
                continue
            _same_file(old / 'manifest.json', new / 'manifest.json')
            for task in experiment.task_ids:
                old_files = {p.relative_to(old) for p in (old / 'tasks' / task).rglob('*') if p.is_file()}
                new_files = {p.relative_to(new) for p in (new / 'tasks' / task).rglob('*') if p.is_file()}
                if not old_files or old_files != new_files:
                    raise ValueError('pre-treatment paraphrase inventory differs')
                for name in old_files:
                    _same_file(old / name, new / name)
    root = Path(source['study_dir'])
    if root.is_symlink() or not root.is_dir():
        raise ValueError('pre-treatment source study is not a regular directory')
    ledger = read_json_object(root / 'study.json', 'pre-treatment source study')
    if ledger.get('experiment_id') != original.experiment_id or ledger.get('status') not in {'completed', 'completed_scope'}:
        raise ValueError('pre-treatment source study is not completed with the expected identity')
    if ledger.get('status') == 'completed_scope':
        # Validate the declared scope and complete full ledger; inactive cells
        # may remain pending, but every selected assignment must be completed.
        terminal_records(original, ledger)
    pool = root / 'pretreatment-rubrics'
    if pool.is_symlink() or not pool.is_dir():
        raise ValueError('pre-treatment source pool is missing or symlinked')
    return pool


def _same_file(source: Path, destination: Path) -> None:
    if (source.is_symlink() or destination.is_symlink()
            or not source.is_file() or not destination.is_file()
            or source.read_bytes() != destination.read_bytes()):
        raise ValueError(f'pre-treatment source input content differs: {destination}')


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
