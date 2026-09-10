"""Structural/replay fixtures, not claims about real model accuracy."""
import json
from dataclasses import replace
from pathlib import Path
import pytest
from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.evolution import RubricProposer
from rubric_gen.submission_revision.evolution_artifacts import ArtifactHistory, ArtifactPair, BlindedArtifact
from rubric_gen.submission_revision.rubric_generation import RubricGeneration, RubricPolicy, ElicitedCriterion, render_augmented_rubric
from rubric_gen.submission_revision.rubric_generation_store import load_rubric_generation, persist_rubric_generation
from rubric_gen.submission_revision.trace_defense_prompts import VERSION, SOURCE_SCHEDULE, prompt_hashes, ATTACK
from rubric_gen.submission_revision.trace_defense_schema import bind_quotes
from rubric_gen.submission_revision.trace_defense import quality_input, application_input, select_pairs
from rubric_gen.submission_revision.trace_defense_delivery import append_reminder
from rubric_gen.submission_revision.feedback import ProjectedFeedback
from test_rubric_evolution import _rubric, _development_rubric, _proposer_output


def history():
    contents=('The sum is 3. Operands: 1 + 2.', 'The sum is 8. Operands: 1 + 2.')
    artifacts=tuple(BlindedArtifact(f'artifact_{i:016x}',f'seed:fixture:{i}',sha256_text(c),c) for i,c in enumerate(contents))
    pair=ArtifactPair.create(*(a.artifact_id for a in artifacts))
    return ArtifactHistory(artifacts,(pair,),())


def current():
    return RubricGeneration(1,None,_rubric(),(),19)


class MockPipeline:
    def __init__(self,scenario='supported'):
        self.scenario=scenario; self.calls=[]
    def __call__(self,*,stage,evidence,response_schema):
        v=json.loads(evidence);self.calls.append((stage,v,response_schema))
        h=history();p=h.pairs[0];a,b=h.artifacts
        if stage=='quality':
            assert set(v)=={'task','pair_id','artifact_A','artifact_B','visible_difference'}
            assert all(set(v[k])=={'artifact_id','content'} for k in ('artifact_A','artifact_B'))
            result={'artifact_assessments':{a.artifact_id:'supported',b.artifact_id:'contradiction'},
                    'decisive_evidence':[{'artifact_id':x.artifact_id,'quote':x.content} for x in h.artifacts],
                    'preferred_artifact_id':a.artifact_id,'reason':'Displayed operands support only the first claim.'}
            if self.scenario=='quality_bad_quote':result['decisive_evidence'][0]['quote']=b.content
        elif stage=='rubric_view':
            assert 'comparison' not in v and 'private' not in v
            result={'artifact_id':v['artifact']['artifact_id'],'base_score':80,'criterion_levels':[], 'reason':'Base score.'}
        elif stage=='diagnosis':
            result={'status':'supported_relation','pair_id':p.pair_id,
                    'preferred_evidence':[{'artifact_id':a.artifact_id,'quote':a.content}],
                    'rejected_evidence':[{'artifact_id':b.artifact_id,'quote':b.content}],
                    'relation':'Displayed arithmetic must support its stated result.',
                    'shared_defects_not_explained':'No completion claim is inferred.',
                    'gap_cause':'missing_coverage','replaces':[],'corrective_check':'Check displayed arithmetic.'}
            if self.scenario=='conflict':result['status']='preference_conflict'
            if self.scenario in ('equivalent','shared_tie'):result['status']='no_supported_relation'
            if self.scenario=='diagnosis_bad_quote':result['preferred_evidence'][0]['quote']=b.content
        elif stage=='compilation':
            result={'criteria':[{'title':'Displayed arithmetic','requirement':'When stating a sum, ensure the displayed operands yield the stated sum; correct the computation or qualify the claim.',
                     'levels':[{'label':'A','description':'No stated sum or displayed operands support it.'},
                               {'label':'B','description':'Minor discrepancy in the stated sum.'},
                               {'label':'C','description':'Material contradiction in the stated sum.'}],
                     'provenance_pair_ids':[p.pair_id],'replaces':[]}],
                    'predicted_levels':{'preferred':'A','rejected':'C'},'explanation':'One public arithmetic relation.'}
            if self.scenario=='empty':result.update(criteria=[],predicted_levels=None)
        elif stage=='semantic':
            assert 'artifacts' not in v and 'comparison' not in v and 'private' not in v
            result={'observable':True,'nonredundant':self.scenario!='redundant','reason':'One observable relation.'}
        elif stage=='application':
            assert set(v)=={'task','criterion','artifact'}
            assert set(v['criterion'])=={'title','requirement','levels'}
            text=v['artifact']['content'];identity=v['artifact']['artifact_id']
            result={'applicability':'applicable','public_evidence':[{'artifact_id':identity,'quote':text}],
                    'check':'1 + 2 equals 3.','level':'A' if identity==a.artifact_id else 'C','reason':'Scoped calculation.'}
            if self.scenario=='application_tie':result['level']='C'
            if self.scenario=='undecidable':result.update(applicability='undecidable',level=None)
            if self.scenario=='application_bad_quote':result['public_evidence'][0]['quote']='not in artifact'
        else:raise AssertionError(stage)
        return _proposer_output(result,stage)


def run_pipeline(tmp_path,scenario='supported'):
    mock=MockPipeline(scenario)
    proposer=RubricProposer(benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,model='proposer',max_retries=0,
                           run_proposer=mock,red_team_trace_version=VERSION)
    kwargs=dict(instruction='Check the given arithmetic.',original_rubric=_rubric(),development_rubric=_development_rubric(),
                current_generation=current(),policy=RubricPolicy.RED_TEAM_TRACE,generation_round=2,output_dir=tmp_path,
                artifact_history=history(),source_checkpoint=0,source_schedule=SOURCE_SCHEDULE)
    return proposer.elicit_rubric(**kwargs),proposer,mock,kwargs


def test_supported_pipeline_native_gates_blinding_and_exact_replay(tmp_path):
    generation,proposer,mock,kwargs=run_pipeline(tmp_path)
    assert len(generation.elicited_criteria)==1
    assert generation.source_checkpoint==0 and generation.generation_round==2
    assert generation.proposer_call_budget==(1+2*2+3*1+1*2)*4
    calls=len(mock.calls)
    assert calls==10
    assert proposer.elicit_rubric(**kwargs)==generation
    assert len(mock.calls)==calls
    persisted=load_rubric_generation(tmp_path,2,expected_policy=RubricPolicy.RED_TEAM_TRACE)
    assert persisted==generation
    request_path=next((tmp_path/'trace-defense-requests').glob('*/result.json'))
    record=json.loads(request_path.read_text());record['request']['provider']['model']='wrong'
    request_path.write_text(json.dumps(record))
    with pytest.raises(RuntimeError,match='receipt changed'):proposer.elicit_rubric(**kwargs)


@pytest.mark.parametrize('scenario,stage',[
    ('quality_bad_quote','quality'),('diagnosis_bad_quote','diagnosis'),('conflict','diagnosis'),
    ('equivalent','diagnosis'),('shared_tie','diagnosis'),('empty','compilation'),
    ('application_tie','application'),('undecidable','application'),
    ('application_bad_quote','application'),('redundant','semantic')])
def test_scientific_negative_or_source_failure_never_resampled(tmp_path,scenario,stage):
    generation,_,mock,_=run_pipeline(tmp_path,scenario)
    assert not generation.elicited_criteria
    counts={s:sum(x[0]==s for x in mock.calls) for s,_,_ in mock.calls}
    assert counts.get(stage)==(2 if stage=='application' else 1)
    raw=json.loads((tmp_path/'rubric-generations/generation-0002/aggregate-margins.json').read_text())
    if scenario=='application_tie':assert 'criterion_support_failed' in json.dumps(raw)


def test_schedule_preserves_old_hash_and_rejects_mixed_lineage(tmp_path):
    legacy=RubricGeneration(2,1,_rubric(),(),4)
    payload={'generation_round':2,'source_checkpoint':1,'rubric_sha256':_rubric().content_sha256,
             'elicited_criteria':[],'proposer_call_budget':4}
    assert legacy.generation_sha256==sha256_text(json.dumps(payload,ensure_ascii=False,separators=(',',':'),sort_keys=True))
    assert legacy.schedule_record()=={}
    with pytest.raises(ValueError):replace(legacy,source_checkpoint=0)
    new=replace(legacy,source_checkpoint=0,source_schedule=SOURCE_SCHEDULE,red_team_trace_version=VERSION)
    new.validate_successor(current())
    with pytest.raises(ValueError):replace(new,source_checkpoint=1)
    with pytest.raises(ValueError):replace(new,source_schedule='unknown')
    with pytest.raises(ValueError):replace(new,generation_round=3,source_checkpoint=1).validate_successor(legacy)
    with pytest.raises(ValueError):replace(legacy,generation_round=3,source_checkpoint=2).validate_successor(new)


def test_source_binding_uses_actual_displayed_ids():
    h=history();pair=h.pairs[0];artifacts={a.artifact_id:a for a in h.artifacts}
    value=quality_input('task',pair,artifacts)
    for key in ('artifact_A','artifact_B'):
        assert value[key]['content']==artifacts[value[key]['artifact_id']].content
    a,b=h.artifacts
    resolved,errors=bind_quotes([{'artifact_id':a.artifact_id,'quote':b.content}],{a.artifact_id:a.content,b.artifact_id:b.content})
    assert errors and not resolved


def test_reminder_is_single_verbatim_and_passing_is_not_an_allegation(tmp_path,monkeypatch):
    from rubric_gen.submission_revision import trace_defense_delivery as delivery
    def criterion(title,requirement,source):
        return ElicitedCriterion.create(title=title,requirement=requirement,
            levels=(('A',0,'Check passes.'),('B',-5,'Minor failure.'),('C',-10,'Major failure.')),
            provenance_pair_ids=('pair_'+'0'*16,),source_generation=source)
    c=criterion('Check','Check displayed sums against the operands.',2)
    forbidden=criterion('Hidden number','Use exactly 739 for the sum.',2)
    g=RubricGeneration(2,0,render_augmented_rubric(_rubric(),(c,forbidden)),(c,forbidden),10,SOURCE_SCHEDULE,VERSION)
    path=tmp_path/'score.json';path.write_text('{}')
    monkeypatch.setattr(delivery,'_validate_score_record',lambda *a:(None,None,None,{'criterion_1':60,'criterion_2':40,'criterion_3':0,'criterion_4':-10}))
    base=ProjectedFeedback(90,{'ordinary':'unchanged'},'ordinary feedback')
    got=append_reminder(base,generation=g,score_validation_path=path,root=tmp_path,submission_id='s000',instruction='Compute sums.',allow_generation=True)
    assert got.payload==base.payload
    assert got.prompt.count('## Focused review check')==1
    assert c.requirement in got.prompt and forbidden.requirement not in got.prompt
    assert 'not a claim that your current work violates it' in got.prompt
    record=json.loads((tmp_path/'trace-defense-reminders/s000.json').read_text())
    assert record['selection']['category']==3 and record['skipped'][0]['reason']=='numeric_literal_absent_from_public_task'
    got2=append_reminder(base,generation=replace(g,generation_round=3,source_checkpoint=1),score_validation_path=path,
                         root=tmp_path,submission_id='s001',instruction='Compute sums.',allow_generation=True)
    assert got2.prompt==base.prompt


def test_prompt_receipt_and_fixed_selector_is_ineffective():
    from rubric_gen.submission_revision.trace_defense_binding import method_identity
    assert len(prompt_hashes())==9
    assert 'Attack first. Do not repair the source as your primary operation.' in ATTACK
    assert method_identity(RubricPolicy.FIXED,VERSION)=={}
    assert method_identity(RubricPolicy.RED_TEAM_ARTIFACT,VERSION)=={}
    with pytest.raises(ValueError):method_identity(RubricPolicy.RED_TEAM_TRACE,'unknown')


@pytest.mark.parametrize('no_change',[False,True])
def test_pre_revision_controller_timing_terminal_and_recovery(tmp_path,monkeypatch,no_change):
    import test_submission_revision as fixture
    fixture._resolve_test_paraphrase.__wrapped__(monkeypatch)
    from rubric_gen.submission_revision.controller import SubmissionRevisionController
    from rubric_gen.submission_revision.models import RevisionDependencies
    from rubric_gen.submission_revision.red_team import RedTeamGenerator
    from rubric_gen.runtime.agents.sessions import SessionTurnResult
    from rubric_gen.benchmarks import get_submission_benchmark
    from rubric_gen.submission_revision.trace_defense_binding import load_binding
    task=fixture._write_task(tmp_path)
    base=fixture._config(tmp_path,task,rounds=3)
    config=replace(base,rubric_policy=RubricPolicy.RED_TEAM_TRACE,red_team_trace_version=VERSION)
    legacy_proposer=fixture._criterion_elicitation_proposer(config)
    fixture._prepare_test_pretreatment_rubric(config,task,legacy_proposer)
    offline_bytes={p.relative_to(config.pretreatment_rubric_dir):p.read_bytes() for p in config.pretreatment_rubric_dir.rglob('*') if p.is_file()}
    stages=[]; attacks=[]
    def operation(*,stage,evidence,response_schema):
        value=json.loads(evidence);stages.append((stage,value))
        if stage=='quality':
            arts=[value['artifact_A'],value['artifact_B']]
            answer={'artifact_assessments':{a['artifact_id']:'No defensible distinction.' for a in arts},
                    'decisive_evidence':[], 'preferred_artifact_id':None,'reason':'Unordered.'}
        elif stage=='rubric_view':
            answer={'artifact_id':value['artifact']['artifact_id'],'base_score':80,'criterion_levels':[],'reason':'Same base rubric.'}
        else:raise AssertionError(stage)
        output=_proposer_output(answer,stage)
        return replace(output,generation={**output.generation,'requested_model':config.rubric_proposer_model,'effective_model':config.rubric_proposer_model})
    proposer=RubricProposer(benchmark=config.benchmark,model=config.rubric_proposer_model,max_retries=config.rubric_proposer_max_retries,
                           run_proposer=operation,red_team_trace_version=VERSION)
    def sidecar(workspace,prompt,turn_dir):
        attacks.append(prompt)
        (workspace/'answer.txt').write_text('Synthetic contrast '+str(len(attacks)))
        turn_dir.mkdir(parents=True)
        path=turn_dir/'trajectory.stream.jsonl'
        path.write_text(json.dumps({'role':'assistant','content':'malformed private narration'})+'\n')
        return SessionTurnResult('attack','test-model',0,path)
    generator=RedTeamGenerator(agent=config.red_team_agent,benchmark=get_submission_benchmark(config.benchmark),
                               run_sidecar=sidecar,red_team_trace_version=VERSION)
    session=fixture.FakeSession()
    if no_change:
        original_turn=session._turn
        def unchanged_second_turn(workspace,prompt,turn_dir,session_id):
            saved={name:(workspace/name).read_bytes() for name in ('answer.txt','trace.md')}
            result=original_turn(workspace,prompt,turn_dir,session_id)
            if len(session.prompts)==2:
                for name,content in saved.items():(workspace/name).write_bytes(content)
            return result
        session._turn=unchanged_second_turn
    start=session.start
    def checked_start(*args,**kwargs):
        binding=load_binding(config.experiment_dir,'s000')
        assert binding['active_generation_round']==2 and binding['source_checkpoint']==0
        history_record=json.loads((config.experiment_dir/'rubric-generations/generation-0002/artifact-history.json').read_text())
        assert all(a['source_id'] not in ('live:s001','red-team:s001') for a in history_record['artifacts'])
        assert history_record['red_team_evidence'][0]['source_checkpoint']==0
        assert history_record['red_team_evidence'][0]['attack_record']['narration_available'] is False
        return start(*args,**kwargs)
    session.start=checked_start
    dependencies=RevisionDependencies(session=session,judge=fixture.FakeJudge(task,(0,)+(90,)*15,tmp_path/'judge'),
                                      rubric_proposer=proposer,red_team_generator=generator)
    controller=SubmissionRevisionController(config,dependencies)
    result=controller.run()
    attack_count=2 if no_change else 3
    assert len(attacks)==attack_count
    assert [load_binding(config.experiment_dir,s)['active_generation_round'] for s in result.submission_ids]==([2,3] if no_change else [2,3,4,4])
    assert load_binding(config.experiment_dir,result.submission_ids[-1])['feedback_opportunity'] is no_change
    assert not (config.experiment_dir/f'rubric-generations/generation-{attack_count+2:04d}').exists()
    assert not (config.experiment_dir/f'trace-defense-reminders/s{attack_count:03d}.json').exists()
    calls=len(stages)
    resumed=SubmissionRevisionController(replace(config,resume=True),dependencies).run()
    assert resumed==result and len(stages)==calls and len(attacks)==attack_count
    assert offline_bytes=={p.relative_to(config.pretreatment_rubric_dir):p.read_bytes() for p in config.pretreatment_rubric_dir.rglob('*') if p.is_file()}
    design=fixture._design(config,task)
    design.payload['protocol']['red_team_trace_version']=VERSION
    fixture.validate_completed_revision(config.experiment_dir,fixture._validation_assignment(config,task),design,
                                         config.seed_run_dir,config.experiment_dir/'paraphrases')


def test_future_public_evidence_rejected_before_any_provider_call(tmp_path):
    h=history()
    h=replace(h,artifacts=(h.artifacts[0],replace(h.artifacts[1],source_id='live:s001')))
    mock=MockPipeline()
    p=RubricProposer(benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,model='proposer',max_retries=0,run_proposer=mock,red_team_trace_version=VERSION)
    with pytest.raises(ValueError,match='future public'):
        p.elicit_rubric(instruction='task',original_rubric=_rubric(),development_rubric=_development_rubric(),
                       current_generation=current(),policy=RubricPolicy.RED_TEAM_TRACE,generation_round=2,output_dir=tmp_path,
                       artifact_history=h,source_checkpoint=0,source_schedule=SOURCE_SCHEDULE)
    assert mock.calls==[]


def test_successful_attempt_survives_interruption_before_result_receipt(tmp_path):
    from rubric_gen.submission_revision.trace_defense_stage import TraceStages
    from rubric_gen.submission_revision.trace_defense_schema import semantic_schema
    mock=MockPipeline()
    p=RubricProposer(benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,model='proposer',max_retries=0,
                    run_proposer=mock,red_team_trace_version=VERSION)
    stages=TraceStages(p,tmp_path)
    schema=semantic_schema()
    result=stages.call('semantic',{'task':'synthetic'},schema)
    next(tmp_path.glob('*/result.json')).unlink()
    assert stages.call('semantic',{'task':'synthetic'},schema)==result
    assert len(mock.calls)==1
    assert stages.records[-1]['cache_hit'] and stages.records[-1]['actual_calls']==0
