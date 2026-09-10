"""Failure diagnostics do not turn harmless text or ambiguous exits into OOM claims."""
import importlib.util
from pathlib import Path


def test_command_failure_signals_deduplicate_and_preserve_unknowns():
    path=Path(__file__).resolve().parents[1]/'investigation/babel-overnight-20260907/execution_failures.py'
    spec=importlib.util.spec_from_file_location('failure_diagnostic',path);module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    def event(identity,code,output):
        return dict(type='item.completed',item=dict(id=identity,type='command_execution',exit_code=code,aggregated_output=output))
    bad=event('bad',1,'Traceback\nTypeError: invalid call')
    counts,errors=module.command_signals([event('ok',0,'MemoryError: quoted example'),bad,bad,event('killed',137,'Killed'),event('unknown',None,''),dict(type='item.started',item=dict(type='command_execution'))])
    assert counts['completed_command_records']==4 and counts['nonzero_exit']==2
    assert counts['unknown_exit_code']==1 and counts['termination_exit_not_proof_of_oom']==1
    assert errors=={'TypeError':1,'no_named_python_exception':1}
