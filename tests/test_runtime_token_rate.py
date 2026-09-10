"""Provider token pacing without API calls."""
import json
from pathlib import Path
import pytest
from rubric_gen.runtime import capacity


def test_rolling_window_and_cooldown(tmp_path,monkeypatch):
    now=[100.0];monkeypatch.setattr(capacity.time,'time',lambda:now[0])
    bucket=capacity.SharedTokenWindow(tmp_path,budget=100,window=60)
    assert bucket.acquire_delay(60)==60
    now[0]=160.01
    assert bucket.acquire_delay(60)==0
    assert bucket.acquire_delay(40)==0
    assert bucket.acquire_delay(1)>59
    bucket.cool_down(80)
    now[0]=221
    assert bucket.acquire_delay(1)>19
    now[0]=240.02
    assert bucket.acquire_delay(100)==0
    with pytest.raises(ValueError):bucket.acquire_delay(101)
    with pytest.raises(RuntimeError,match='policy changed'):
        capacity.SharedTokenWindow(tmp_path,budget=99).acquire_delay(1)


def test_independent_instances_share_budget(tmp_path,monkeypatch):
    now=[10.0];monkeypatch.setattr(capacity.time,'time',lambda:now[0])
    a=capacity.SharedTokenWindow(tmp_path,budget=10,window=1)
    b=capacity.SharedTokenWindow(tmp_path,budget=10,window=1)
    assert a.acquire_delay(6)>0
    now[0]=12
    assert a.acquire_delay(6)==0
    assert b.acquire_delay(5)>0
    assert b.acquire_delay(4)==0


def test_hosted_pacing_counts_tokens_and_releases_slots_while_waiting(tmp_path,monkeypatch):
    import rubric_gen.runtime.llm as llm
    monkeypatch.setattr(capacity,'policy',lambda:dict(version=1,aggregate_concurrency=1,audit_studies=1,coordination_dir=str(tmp_path)))
    now=[100.0];monkeypatch.setattr(capacity.time,'time',lambda:now[0])
    counts=[];sleeps=[]
    monkeypatch.setattr(capacity,'_TOKEN_COUNTS',{})
    monkeypatch.setattr(llm,'count_input_tokens',lambda model,request:counts.append(model) or 100)
    def sleep(seconds):
        assert capacity.Slots(tmp_path/'provider',1).active_count()==0
        sleeps.append(seconds);now[0]+=seconds
    monkeypatch.setattr(capacity.time,'sleep',sleep)
    @capacity.limited('hosted-generation')
    def generate(model,request_value):return 'ok'
    assert generate('claude-opus-5','fake request')=='ok'
    assert generate('claude-opus-5','fake request')=='ok'
    assert counts==['claude-opus-5'] and sum(sleeps)>=60
    assert generate('gpt-5.6-sol','fake request')=='ok'
    assert counts==['claude-opus-5']
    state=json.loads((tmp_path/'anthropic-input-tokens/window.json').read_text())
    assert sum(n for _,n in state['entries'])==200
