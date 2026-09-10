"""Fault injection for joined-child recovery; never provider calls."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

spec=importlib.util.spec_from_file_location('stage_recovery',Path(__file__).resolve().parents[1]/'scripts/babel/stage_recovery.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

def manifest(tmp_path, cause='APITimeoutError', status='failed_scope'):
    value={'status':status,'execution_conditions':['selected'],'records':[
        {'assignment_id':'done','condition_id':'selected','status':'completed'},
        {'assignment_id':'retry','condition_id':'selected','status':'failed','error_type':'RubricProposerProviderError','error':f'stage failed (last error: {cause})'},
        {'assignment_id':'unselected','condition_id':'other','status':'pending'}]}
    (tmp_path/'study.json').write_text(json.dumps(value))

@pytest.mark.parametrize('cause',['AuthenticationError','RateLimitError','RuntimeError','ValueError'])
def test_unknown_or_permanent_stops(tmp_path,cause):
    manifest(tmp_path,cause)
    assert module.revision_retry_evidence(tmp_path) is None

@pytest.mark.parametrize('status',['running','completed_scope'])
def test_nonterminal_or_successful_manifest_not_retried(tmp_path,status):
    manifest(tmp_path,status=status)
    assert module.revision_retry_evidence(tmp_path) is None

def test_transient_then_success_preserves_prior_work(tmp_path):
    manifest(tmp_path);original=(tmp_path/'study.json').read_bytes();attempts=[];checks=[]
    stop=SimpleNamespace(is_set=lambda:False,wait=lambda _:False)
    def run(attempt):attempts.append(attempt);return int(attempt==1)
    assert module.run_revision_attempts(run,study_root=tmp_path,receipt=tmp_path,label='revision',stop=stop,verify_source=lambda:checks.append(1))==0
    assert attempts==[1,2] and len(checks)==2
    assert (tmp_path/'study.json').read_bytes()==original
    evidence=json.loads((tmp_path/'revision-recovery-1.json').read_text())['evidence']
    assert evidence['completed']==1 and evidence['failures']==[{'assignment_id':'retry','error_class':'APITimeoutError'}]

def test_repeated_transient_is_bounded(tmp_path):
    manifest(tmp_path);calls=[];stop=SimpleNamespace(is_set=lambda:False,wait=lambda _:False)
    def run(attempt):calls.append(attempt);return 1
    assert module.run_revision_attempts(run,study_root=tmp_path,receipt=tmp_path,label='revision',stop=stop,verify_source=lambda:None)==1
    assert calls==[1,2,3]

def test_changed_source_prevents_launch(tmp_path):
    def changed():raise RuntimeError('changed')
    with pytest.raises(RuntimeError,match='changed'):
        module.run_revision_attempts(lambda _:pytest.fail('no child'),study_root=tmp_path,receipt=tmp_path,label='revision',stop=SimpleNamespace(is_set=lambda:False),verify_source=changed)


def test_assignment_scope_does_not_retry_inactive_replicates(tmp_path):
    manifest(tmp_path)
    path = tmp_path / 'study.json'
    data = json.loads(path.read_text())
    data['execution_assignment_ids'] = ['retry']
    data['records'][0]['status'] = 'pending'
    path.write_text(json.dumps(data))
    evidence = module.revision_retry_evidence(tmp_path)
    assert evidence['completed'] == 0
    assert evidence['failures'] == [{'assignment_id': 'retry', 'error_class': 'APITimeoutError'}]
