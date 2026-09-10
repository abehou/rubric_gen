"""Synthetic checks of selected-reference reconstruction and paired RH bounds."""
import copy
import importlib.util
from pathlib import Path
import pytest

@pytest.fixture
def analysis():
    p=Path(__file__).resolve().parents[1]/'investigation/babel-overnight-20260907/analyze_babel.py'
    spec=importlib.util.spec_from_file_location('babel_analysis_test',p);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def rows(m):
    data=[]
    for condition,quality,decisions in [('control',70,['reward_hacking_detected','no_reward_hacking_detected']),('treatment',75,['no_reward_hacking_detected','abstain'])]:
        for model,decision in zip(['a','b'],decisions,strict=True):
            values=m.numeric_scores(90,80,85,80,quality)
            values.update(quality_gain=quality-60,selected_gain=5,elicited_penalty=-10)
            data.append(dict(condition_id=condition,task_id='task',replicate=1,model=model,values=values,submission_sha256=condition,
                initial_submission_sha256='same-seed',selected_rubric_sha256='same-selected',
                direct={w:dict(decision=decision,score={'reward_hacking_detected':7,'no_reward_hacking_detected':2,'abstain':5}[decision]) for w in m.WINDOWS}))
    return data

def test_composed_penalty_is_not_selected_W(analysis):
    x=analysis.numeric_scores(90,80,85,80,70)
    assert (x['W'],x['W_train'],x['WS'],x['SH'],x['HA'],x['WA'])==(90,80,5,5,10,20)
    assert x['WA']==x['WS']+x['SH']+x['HA']
    assert x['train_WS']==-5 and x['train_WA']==10
    assert x['train_WA']==x['train_WS']+x['SH']+x['HA']
    with pytest.raises(AssertionError):analysis.numeric_scores(float('nan'),80,85,80,70)

def test_panel_abstention_and_pairing(analysis):
    data=rows(analysis)
    groups,_=analysis.aggregate(data,['a','b'])
    assert groups['treatment/matched-panel']['metrics']['RH_full_trajectory']['identification_bounds']==[0,1]
    contrast=analysis.paired_contrast(data,'treatment','control',['a','b'])
    assert contrast['matched-panel']['metrics']['A']['mean']==5
    assert contrast['matched-panel']['metrics']['WA']['mean']==-5
    assert contrast['matched-panel']['metrics']['RH_full_trajectory']['identification_bounds']==[-1,0]
    with pytest.raises(AssertionError,match='coverage'):analysis.paired_contrast(data[:-1],'treatment','control',['a','b'])
    changed=copy.deepcopy(data);changed[-1]['initial_submission_sha256']='different'
    with pytest.raises(AssertionError,match='seed'):analysis.paired_contrast(changed,'treatment','control',['a','b'])
