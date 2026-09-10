"""Runtime throughput counts only assignments selected for this invocation."""
import importlib.util
import json
from pathlib import Path
import pytest

spec=importlib.util.spec_from_file_location('babel_monitor',Path(__file__).parents[1]/'scripts/babel/monitor.py')
module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)

@pytest.mark.parametrize('scope,expected',[(None,{'completed':2,'pending':1}),(['trace'],{'completed':1}),([],{})])
def test_selected_assignment_counts(tmp_path,scope,expected):
    study=tmp_path/'study';study.mkdir()
    (study/'study.json').write_text(json.dumps({'execution_conditions':scope,'records':[
        {'condition_id':'trace','status':'completed'},
        {'condition_id':'static','status':'completed'},
        {'condition_id':'static','status':'pending'}]}))
    monitor=module.Monitor(tmp_path/'events',tmp_path/'metrics.jsonl',[study])
    assert dict(monitor._assignments())==expected
    assert monitor.baseline_completed==expected.get('completed',0)


def test_non_http_failures_are_job_scoped_and_counted_once(tmp_path, monkeypatch):
    monkeypatch.setenv('SLURM_JOB_ID', 'owned')
    monkeypatch.setattr(module.Slots, 'active_count', lambda self: 0)
    events=tmp_path/'events';events.mkdir()
    records=[dict(event='operation_failed',operation='hosted-generation',
                  request_key=str(i),elapsed_seconds=600,job_id=job,
                  error_type=error,status_code=status)
             for i,(job,error,status) in enumerate([
                 ('owned','APITimeoutError',None),
                 ('owned','RateLimitError',429),
                 ('other','ConnectionError',None)])]
    (events/'events-test.jsonl').write_text(''.join(json.dumps(r)+'\n' for r in records))
    monitor=module.Monitor(events,tmp_path/'metrics.jsonl',[])
    for _ in range(2):
        result=monitor.sample()
        assert result['operation_failure_types']=={'APITimeoutError':1,'RateLimitError':1}
        assert result['http_failure_statuses']=={'429':1}
        assert result['completed_operations_per_minute']['hosted-generation']==0
