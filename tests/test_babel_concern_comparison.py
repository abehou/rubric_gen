"""Select predeclared native cohorts without duplicating auditors or changing sources."""
import importlib.util
from pathlib import Path
import pytest


def module():
    path=Path(__file__).resolve().parents[1]/'investigation/babel-overnight-20260907/compare_concern_replication.py'
    spec=importlib.util.spec_from_file_location('concern_comparison_test',path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m


def test_explicit_cohort_selection_and_incomplete_panel_rejection(tmp_path):
    m=module();rows=[]
    for cohort in ('control/user','concern1/user'):
        for rep in (1,2,3):
            p=tmp_path/f'{cohort.replace("/","-")}-{rep}.json';p.write_text('{}')
            for model in ('gpt-5.6-sol','claude-opus-5'):
                rows.append(dict(analysis_condition=cohort,task_id='da-11-1',replicate=rep,model=model,state_path=str(p),state_sha256=m.digest(p),score_composition_path=str(p),score_composition_sha256=m.digest(p)))
    selected=m.selected_rows({'rows':rows},{'concern1/user':'repeat-control'})
    assert len(selected)==6 and {r['analysis_condition'] for r in selected}=={'repeat-control'}
    assert rows[-1]['analysis_condition']=='concern1/user'
    with pytest.raises(AssertionError,match='complete'):m.selected_rows({'rows':rows[:-1]},{'concern1/user':'repeat-control'})
    Path(selected[0]['state_path']).write_text('{"changed":true}')
    with pytest.raises(AssertionError,match='source changed'):m.selected_rows({'rows':rows},{'concern1/user':'repeat-control'})
