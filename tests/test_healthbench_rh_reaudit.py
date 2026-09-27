"""Prepared RH-only launcher cannot include quality audits or change model scope."""
from contextlib import nullcontext
import json
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

HERE = Path(__file__).resolve().parents[1] / 'experiments/healthbench-hard-result20'
sys.path.insert(0, str(HERE))
import reaudit_rh


def test_rh_only_plan_keeps_all_assignments_and_separates_output(tmp_path, monkeypatch):
    experiment = SimpleNamespace(outcome_audit={'models': ['gpt-6-luna']},
                                 dag={'revise': {'output_dir': str(tmp_path / 'saved-study')}})
    sources = SimpleNamespace(revisions=tuple(range(240)))
    monkeypatch.setattr(reaudit_rh, 'load_experiment', lambda _: experiment)
    monkeypatch.setattr(reaudit_rh, 'resolve_study_sources', lambda *_: sources)
    calls = []
    def prepare(config, **kwargs):
        calls.append((config, kwargs))
        return config
    monkeypatch.setattr(reaudit_rh, 'prepare_direct_detection', prepare)
    output = tmp_path / 'separate-rh'
    runners = reaudit_rh.make_runners(output)
    assert set(runners) == {'full_trajectory', 'post_update', 'final_revision', 'final_artifact'}
    assert len(calls) == 4
    assert len({id(kwargs['shared_inputs']) for _, kwargs in calls}) == 1
    for config, kwargs in calls:
        assert config.study_dir == tmp_path / 'saved-study'
        assert config.output_dir.is_relative_to(output)
        assert config.max_concurrency == 12 and config.resume is True
        assert kwargs['sources'] is sources
    experiment.outcome_audit['models'] = ['gpt-6-sol']
    with pytest.raises(AssertionError):
        reaudit_rh.make_runners(output)
    assert len(calls) == 4  # Wrong panel fails before planning or provider work.


def test_rh_only_windows_share_executor_and_prepare_resume_first(tmp_path, monkeypatch):
    executor = object()
    events = []
    class Runner:
        def __init__(self, name): self.name = name
        def prepare_resume(self): events.append(('resume', self.name))
        def run_prepared(self, *, executor):
            assert sum(e[0] == 'resume' for e in events) == 4
            events.append(('run', self.name, executor))
            return 0
    names = ('full_trajectory', 'post_update', 'final_revision', 'final_artifact')
    monkeypatch.setattr(reaudit_rh, 'OUTPUT', tmp_path)
    monkeypatch.setattr(reaudit_rh, 'audit_owner', lambda _: nullcontext())
    monkeypatch.setattr(reaudit_rh, 'AuditExecutor', lambda *args: nullcontext(executor))
    monkeypatch.setattr(reaudit_rh, 'make_runners', lambda: {n: Runner(n) for n in names})
    assert reaudit_rh.audit() == 0
    assert all(e[2] is executor for e in events if e[0] == 'run')
    assert set(json.loads((tmp_path / 'stages.json').read_text())) == set(names)
