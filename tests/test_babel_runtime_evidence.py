"""Event evidence counts reserved slots across overlapping jobs."""
import importlib.util
from pathlib import Path


def test_overlapping_reservations_and_balanced_release():
    p=Path(__file__).resolve().parents[1]/'investigation/babel-overnight-20260907/runtime_evidence.py'
    spec=importlib.util.spec_from_file_location('runtime_evidence_test',p)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    rows=[dict(event=event,time=t,kind='provider',slots=n,lease_id=lease,job_id=job) for event,t,n,lease,job in [
        ('acquired',0,59,'a','job1'),('acquired',1,1,'b','job2'),
        ('released',3,1,'b','job2'),('released',5,59,'a','job1')]]
    result=module.summarize(rows)
    assert result['event_observed_provider_peak']==60
    assert result['seconds_at_least54']==5 and result['seconds_at_least60']==2
    assert result['outstanding_event_slots']==0 and result['failures']==[]
