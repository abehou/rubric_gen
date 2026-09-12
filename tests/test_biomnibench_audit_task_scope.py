"""Private audit dispatch can skip a blocked task without changing requests."""
import importlib.util
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / 'experiments/biomnibench-v21-to45/queue2/audit.py'


@pytest.fixture
def dispatch(monkeypatch):
    from rubric_gen.submission_revision import commands, experiment
    calls = []
    monkeypatch.setattr(commands, 'run_detect', lambda args: calls.append(vars(args).copy()) or 0)
    monkeypatch.setattr(experiment, 'load_experiment', lambda path: SimpleNamespace(
        dag={'detect': {'output_dir': str(path)}}))
    monkeypatch.setenv('OPENAI_API_KEY', 'test')
    monkeypatch.setenv('ANTHROPIC_API_KEY', 'test')
    monkeypatch.setenv('RUBRIC_GEN_PROJECT_ROOT', str(ROOT))
    reuse = SimpleNamespace(install=lambda: None)
    monkeypatch.setattr(importlib.util, 'spec_from_file_location', lambda *a: SimpleNamespace(
        loader=SimpleNamespace(exec_module=lambda m: None)))
    monkeypatch.setattr(importlib.util, 'module_from_spec', lambda s: reuse)

    def run(source, *tasks):
        calls.clear()
        monkeypatch.setattr(sys, 'argv', ['audit.py', 'R2', *tasks])
        exec(compile(source, str(SCRIPT), 'exec'), {'__file__': str(SCRIPT)})
        return list(calls)
    return run


def test_default_dispatch_matches_frozen_execution(dispatch):
    previous = subprocess.check_output([
        'git', 'show', '534e797:experiments/biomnibench-v21-to45/queue2/audit.py'
    ], cwd=ROOT, text=True)
    assert dispatch(SCRIPT.read_text()) == dispatch(previous)


def test_remaining_tasks_keep_native_config_and_resume(dispatch):
    source = SCRIPT.read_text()
    all_calls = dispatch(source)
    remaining = dispatch(source, 'da-11-1', 'da-18-1')
    assert remaining == all_calls[1:]
    assert all(c['resume'] and c['max_concurrency'] == 32 for c in remaining)


def test_original_project_config_paths_are_preserved(dispatch, monkeypatch, tmp_path):
    monkeypatch.setenv('RUBRIC_GEN_PROJECT_ROOT', str(tmp_path))
    calls = dispatch(SCRIPT.read_text(), 'da-11-1')
    assert calls[0]['experiment'] == str(
        tmp_path / 'experiments/biomnibench-v21-to45/queue2/configs/R2/da-11-1.yaml')


@pytest.mark.parametrize('tasks', [
    ('unknown',), ('da-18-1', 'da-11-1'), ('da-11-1', 'da-11-1')
])
def test_invalid_scope_fails_before_calls(dispatch, tasks):
    with pytest.raises(ValueError, match='canonical-order subset'):
        dispatch(SCRIPT.read_text(), *tasks)
