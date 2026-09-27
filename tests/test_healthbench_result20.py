"""Budget admission and actual mixed-panel routing; no paid requests."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import tomllib

import pytest
import yaml

HERE = Path(__file__).resolve().parents[1]/'experiments/healthbench-hard-result20'
sys.path.insert(0,str(HERE))
from budget_proxy import Ledger, actual_cost, upper_bound, prepare_payload
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.runner import RubricFreeScoreRunner


def test_budget_pending_is_reserved_and_unknown_usage_is_not_refunded(tmp_path):
    ledger=Ledger(tmp_path/'budget.json',1.)
    key=ledger.reserve(.8)
    assert sum(ledger.state['pending'].values()) == .8
    ledger.finish(key,None)
    with pytest.raises(RuntimeError, match=r'Approved \$1 budget'): ledger.reserve(.21)
    assert ledger.state['spent_usd']==.8


def test_crashed_requests_remain_charged_on_resume(tmp_path):
    path=tmp_path/'budget.json'
    ledger=Ledger(path,1.)
    ledger.reserve(.8)
    resumed=Ledger(path,1.)
    assert resumed.state['spent_usd']==.8
    assert resumed.state['uncertain']==1
    assert resumed.state['pending']=={}


def test_token_count_does_not_receive_generation_only_parameters():
    payload={'model':'gpt-6-luna','input':'example','text':{'format':{'type':'text'}}}
    original=json.loads(json.dumps(payload))
    assert prepare_payload('/v1/responses/input_tokens',payload)>0
    assert payload==original
    prepare_payload('/v1/responses',payload)
    assert payload['service_tier']=='default'
    assert payload['max_output_tokens']==128000


def test_authorized_overrun_preserves_accounting_without_budget_stop(tmp_path):
    path=tmp_path/'budget.json'
    ledger=Ledger(path,1.)
    key=ledger.reserve(.8); ledger.finish(key,.8)
    resumed=Ledger(path,1.,allow_overrun=True)
    key=resumed.reserve(.9); resumed.finish(key,.9)
    assert resumed.state['spent_usd']==pytest.approx(1.7)
    assert not resumed.state['stopped']
    assert resumed.state['allow_overrun'] is True
    # Overrun permission is explicit per invocation, never silently inherited.
    capped=Ledger(path,1.)
    with pytest.raises(RuntimeError): capped.reserve(.01)


def test_known_usage_releases_excess_and_includes_cache_write(tmp_path):
    usage={'input_tokens':1000,'output_tokens':500,
           'input_tokens_details':{'cached_tokens':200,'cache_write_tokens':300}}
    cost=actual_cost('gpt-6-sol',usage)
    assert cost==pytest.approx(.00679)
    ledger=Ledger(tmp_path/'budget.json',1.)
    key=ledger.reserve(.8); ledger.finish(key,cost)
    assert ledger.state['spent_usd']==cost
    ledger.reserve(.8)


@pytest.mark.parametrize('extra',[{'model':'gpt-6-astra'},{'tools':[{'type':'web_search'}]},
                                    {'previous_response_id':'resp_x'}, {'service_tier':'priority'}])
def test_unbudgeted_requests_fail_before_dispatch(extra):
    with pytest.raises((ValueError,KeyError)):
        upper_bound({'model':'gpt-5.6-luna','input':'test',**extra})


def test_encrypted_context_reserves_more_and_output_cap_is_explicit():
    plain={'model':'gpt-5.6-luna','input':'test'}
    encrypted={'model':'gpt-5.6-luna','input':[{'encrypted_content':'opaque'}]}
    assert upper_bound(encrypted)>upper_bound(plain)
    assert encrypted['max_output_tokens']==plain['max_output_tokens']==128000


def test_mixed_models_reach_rubric_free_planner(tmp_path,monkeypatch):
    import rubric_gen.submission_revision.evaluation.score_execution as module
    experiment=SimpleNamespace(outcome_audit={'models':['gpt-6-luna'],
                                              'rubric_free_models':['gpt-6-sol']})
    config=EvaluationConfig(experiment=experiment,study_dir=tmp_path/'study',
                            paraphrase_dir=tmp_path/'para',output_dir=tmp_path/'audit',
                            max_concurrency=1,resume=False)
    runner=RubricFreeScoreRunner(config,())
    monkeypatch.setattr(runner,'_predispatch_plan',lambda *a:{})
    monkeypatch.setattr(module,'pairwise_order_plan',lambda targets:{})
    runner.preflight()
    assert runner._prepared.models==('gpt-6-sol',)
    assert experiment.outcome_audit['models']==['gpt-6-luna']


def test_mixed_panel_resume_checks_the_stage_models(tmp_path):
    from rubric_gen.submission_revision.evaluation.resume import _completed_summary
    summary={'status':'completed','experiment_id':'test','study_dir':str(tmp_path.resolve()),
             'models':['gpt-6-sol']}
    (tmp_path/'summary.json').write_text(json.dumps(summary))
    output=SimpleNamespace(path=lambda name:tmp_path/name)
    config=SimpleNamespace(resume=True,study_dir=tmp_path,
        experiment=SimpleNamespace(experiment_id='test',outcome_audit={'models':['gpt-6-luna']}))
    assert _completed_summary(output,config,models=('gpt-6-sol',))==summary
    with pytest.raises(RuntimeError,match='another study or panel'):
        _completed_summary(output,config)


def test_shards_preserve_allocation_and_native_identity(tmp_path):
    ids=[]
    for path in sorted(HERE.glob('shard-*.yaml')):
        payload=yaml.safe_load(path.read_text())
        payload['tasks_dir']=str(HERE.parents[1]/'data/healthbench-hard/challenge20-20260926')
        local=tmp_path/path.name; local.write_text(yaml.safe_dump(payload))
        experiment=load_experiment(local)
        assert len(experiment.assignments)==60
        assert experiment.outcome_audit['models']==['gpt-6-luna']
        assert experiment.outcome_audit['rubric_free_models']==['gpt-6-sol']
        assert experiment.protocol['rubric_proposer_reasoning_effort_by_stage']['validation']=='high'
        ids.extend(payload['tasks'])
    assert len(ids)==len(set(ids))==20


def test_budget_route_in_isolated_codex_config(monkeypatch):
    from rubric_gen.runtime.agents.adapters import _codex_scientific_config
    from rubric_gen.runtime.agents.models import AgentRunConfig
    monkeypatch.setenv('RUBRIC_GEN_OPENAI_BUDGET_URL','http://127.0.0.1:18765/v1')
    monkeypatch.setattr('rubric_gen.runtime.agents.adapters._codex_sandbox_support_paths',lambda c:())
    config=tomllib.loads(_codex_scientific_config(AgentRunConfig(provider='codex')))
    assert config['model_provider']=='budget-openai'
    assert config['model_providers']['budget-openai']['base_url']=='http://127.0.0.1:18765/v1'
    assert config['model_providers']['budget-openai']['supports_websockets'] is False
    assert config['model_providers']['budget-openai']['env_key']=='CODEX_API_KEY'
    assert config['features']['enable_request_compression'] is False
    assert config['permissions']['benchmark-task']['network']['enabled'] is False


def test_installed_codex_accepts_budget_config_without_provider_call(tmp_path,monkeypatch):
    import shutil
    import subprocess
    from rubric_gen.runtime.agents.adapters import _codex_scientific_config
    from rubric_gen.runtime.agents.models import AgentRunConfig
    from rubric_gen.runtime.process_environment import controlled_process_environment
    executable=shutil.which('codex')
    if executable is None: pytest.skip('Codex not installed')
    monkeypatch.setenv('RUBRIC_GEN_OPENAI_BUDGET_URL','http://127.0.0.1:18765/v1')
    (tmp_path/'config.toml').write_text(_codex_scientific_config(AgentRunConfig(provider='codex')))
    env=controlled_process_environment()
    env.update(CODEX_HOME=str(tmp_path),CODEX_API_KEY='sk-local-test-only')
    result=subprocess.run([executable,'features','list'],cwd=tmp_path,env=env,
                          capture_output=True,text=True,timeout=30)
    assert result.returncode==0,result.stderr


def test_local_queue_preserves_approved_science(tmp_path):
    payload=yaml.safe_load((HERE/'local.yaml').read_text())
    payload['tasks_dir']=str(HERE.parents[1]/'data/healthbench-hard/challenge20-20260926')
    path=tmp_path/'local.yaml'; path.write_text(yaml.safe_dump(payload))
    experiment=load_experiment(path)
    assert len(experiment.assignments)==240
    assert len(payload['tasks'])==20
    assert experiment.outcome_audit['rubric_free_models']==['gpt-6-sol']
    assert experiment.outcome_audit['models']==['gpt-6-luna']
    assert experiment.protocol['rubric_proposer_reasoning_effort_by_stage']['validation']=='high'
    runtime=json.loads((HERE/'runtime.json').read_text())
    assert runtime['aggregate_concurrency']==12


def test_output_recovery_is_input_scoped_and_plan_matches_request(monkeypatch):
    from rubric_gen.artifacts.hashing import sha256_text
    from rubric_gen.submission_revision.evaluation.rubric_judge import build_rubric_score_run_spec
    from rubric_gen.submission_revision.evaluation.rubric_score import preflight_judge_dispatches
    from rubric_gen.submission_revision.judging.preflight import JudgeDispatchInput
    from rubric_gen.submission_revision.evaluation.resume import _plan_science
    from rubric_gen.submission_revision.judging.full_rubric_protocol import full_rubric_cost_shape
    rubric='Score normalization maximum: 17\n\n'+''.join(
        f'Criterion {i}: Requirement {i}.\nLevels: A=1 B=0\n[A]: Complete.\n[B]: Missing.\n\n'
        for i in range(1,18))
    review='review'; answer='answer'
    binding={'rubric_sha256':sha256_text(rubric),'review_input_sha256':sha256_text(review),
             'answer_input_sha256':sha256_text(answer)}
    args=dict(rubric_text=rubric,review_text=review,answer_text=answer,requested_model='gpt-6-luna',seed=1)
    monkeypatch.delenv('RUBRIC_GEN_AUDIT_OUTPUT_RECOVERY',raising=False)
    original=build_rubric_score_run_spec(**args)
    old_shape=full_rubric_cost_shape(rubric,review_text=review,answer_text=answer).as_json()
    monkeypatch.setenv('RUBRIC_GEN_AUDIT_OUTPUT_RECOVERY',json.dumps({**binding,'max_output_tokens':8192}))
    recovered=build_rubric_score_run_spec(**args)
    assert recovered.max_output_tokens_per_call==8192
    assert build_rubric_score_run_spec(**{**args,'answer_text':'other'}).max_output_tokens_per_call==original.max_output_tokens_per_call
    plan=preflight_judge_dispatches('healthbench-hard',[JudgeDispatchInput(rubric,review,answer)])
    assert plan['output_tokens']==8192
    assert _plan_science({**binding,'shape':old_shape})==_plan_science({**binding,'shape':plan['jobs'][0]})
    assert _plan_science({**binding,'shape':old_shape})!=_plan_science({**binding,'answer_input_sha256':'changed','shape':plan['jobs'][0]})
