import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rubric_gen.submission_revision import pretreatment_reuse as reuse


@pytest.fixture
def pair(tmp_path, monkeypatch):
    path = tmp_path / 'source.yaml'
    path.write_text('kind: test\n')
    root = tmp_path / 'study'
    (root / 'pretreatment-rubrics').mkdir(parents=True)
    (root / 'study.json').write_text(json.dumps({'experiment_id': 'source', 'status': 'completed'}))
    payload = {k: 'same' for k in ('benchmark', 'tasks_dir', 'seed_generator', 'rubric_paraphrases')}
    protocol = {k: 'same' for k in ('prompt', 'rubric_name', 'rubric_proposer_model', 'rubric_proposer_max_retries')}
    dag = {k: {'output_dir': str(tmp_path / k)} for k in ('seed', 'paraphrase')}
    source = SimpleNamespace(experiment_id='source', payload=payload, protocol=protocol, dag=dag, task_ids=('t1', 't2'))
    current = SimpleNamespace(experiment_id='new', payload=dict(payload), protocol=dict(protocol), dag=dag, task_ids=('t1',),
                              pretreatment_source={'experiment': str(path), 'study_dir': str(root), 'experiment_id': 'source'})
    monkeypatch.setattr(reuse, 'load_experiment', lambda _: source)
    return current, root


def test_explicit_source_preserves_scope(pair):
    current, root = pair
    assert reuse.source_pool(current) == root / 'pretreatment-rubrics'
    assert reuse.scope_id(current) == 'source'


@pytest.mark.parametrize('change', ['identity', 'protocol', 'tasks', 'status', 'nested'])
def test_reject_incompatible_source(pair, change):
    current, root = pair
    if change == 'identity':
        current.pretreatment_source['experiment_id'] = 'wrong'
    elif change == 'protocol':
        current.protocol['rubric_proposer_model'] = 'different'
    elif change == 'tasks':
        current.task_ids = ('absent',)
    elif change == 'status':
        (root / 'study.json').write_text('{"experiment_id":"source","status":"running"}')
    else:
        Path(current.pretreatment_source['experiment']).write_text('pretreatment_source: {}\n')
    with pytest.raises(ValueError):
        reuse.source_pool(current)


def test_no_source_uses_current_identity():
    current = SimpleNamespace(pretreatment_source=None, experiment_id='new')
    assert reuse.scope_id(current) == 'new'
    assert reuse.source_pool(current) is None


def test_copy_preserves_bytes_and_does_not_overwrite(tmp_path):
    source, destination = tmp_path / 'source', tmp_path / 'dest'
    source.mkdir()
    (source / 'record').write_bytes(b'original\r\n')
    reuse.copy_pool_entry(source, destination)
    assert (destination / 'record').read_bytes() == b'original\r\n'
    (destination / 'record').write_bytes(b'changed')
    reuse.copy_pool_entry(source, destination)
    assert (destination / 'record').read_bytes() == b'changed'
    (source / 'link').symlink_to(source / 'record')
    with pytest.raises(ValueError):
        reuse.copy_pool_entry(source, tmp_path / 'other')


def scoped_source(pair, monkeypatch):
    current, root = pair
    original = reuse.load_experiment(None)
    original.assignments = (
        SimpleNamespace(assignment_id='a', condition_id='trace'),
        SimpleNamespace(assignment_id='b', condition_id='static'),
    )
    original.execution_conditions = ('trace',)
    ledger = {'experiment_id': 'source', 'status': 'completed_scope',
              'execution_conditions': ['trace'], 'records': [
                  {'assignment_id': 'a', 'condition_id': 'trace', 'status': 'completed'},
                  {'assignment_id': 'b', 'condition_id': 'static', 'status': 'pending'},
              ]}
    return current, root, ledger


def test_reuse_completed_scope_preserves_inactive_cells(pair, monkeypatch):
    current, root, ledger = scoped_source(pair, monkeypatch)
    path = root / 'study.json'
    path.write_text(json.dumps(ledger))
    before = path.read_bytes()
    assert reuse.source_pool(current) == root / 'pretreatment-rubrics'
    assert path.read_bytes() == before


@pytest.mark.parametrize('fault', ['unfinished', 'scope', 'missing_record', 'condition', 'failed'])
def test_reject_malformed_completed_scope(pair, monkeypatch, fault):
    current, root, ledger = scoped_source(pair, monkeypatch)
    if fault == 'unfinished':
        ledger['records'][0]['status'] = 'pending'
    elif fault == 'scope':
        ledger['execution_conditions'] = ['static']
    elif fault == 'missing_record':
        ledger['records'].pop()
    elif fault == 'condition':
        ledger['records'][0]['condition_id'] = 'static'
    else:
        ledger['status'] = 'failed_scope'
    (root / 'study.json').write_text(json.dumps(ledger))
    with pytest.raises(ValueError):
        reuse.source_pool(current)
