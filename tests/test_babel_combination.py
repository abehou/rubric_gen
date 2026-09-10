"""Cross-version comparison keeps native validation and rejects stale inputs."""
import importlib.util
from pathlib import Path
import pytest


def test_combination_identity_and_duplicates(tmp_path,monkeypatch):
    here=Path(__file__).resolve().parents[1]/'investigation/babel-overnight-20260907'
    monkeypatch.syspath_prepend(str(here))
    spec=importlib.util.spec_from_file_location('combine_test',here/'combine_babel.py')
    m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m)
    path=tmp_path/'source.json';path.write_text('{}');sha=m.digest(path)
    row=dict(condition_id='user',task_id='task',replicate=1,model='model',state_path=str(path),state_sha256=sha,score_composition_path=str(path),score_composition_sha256=sha)
    report=dict(rows=[row],coverage=[{'native':'accepted'}],definitions='frozen',analysis_source_sha256='source')
    rows,coverage,definitions=m.combine([report],['control'],'source')
    assert rows[0]['analysis_condition']=='control/user' and 'analysis_condition' not in row
    with pytest.raises(AssertionError,match='definitions changed'):m.combine([report],['control'],'new-source')
    with pytest.raises(AssertionError,match='single native cohort'):m.combine([dict(report,rows=[row,row])],['control'],'source')
    path.write_text('{"changed":true}')
    with pytest.raises(AssertionError,match='source artifact changed'):m.combine([report],['control'],'source')
