"""Provider-free interface/native-gate fixtures; these do not establish model accuracy."""
import json
from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import pytest
from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.evolution import RubricProposer
from rubric_gen.submission_revision.evolution_serialization import canonical_sha256
from rubric_gen.submission_revision.trace_defense_evidence_v2 import (
    PublicDocument, bind_references, EvidenceContractError, allowed_actions,
    replacement_for_action, native_criterion_payload,
)
from rubric_gen.submission_revision import trace_defense_v2_schema as schema
from rubric_gen.submission_revision.trace_defense_v2_stage import TraceStagesV2
from rubric_gen.submission_revision.trace_defense_v2 import quality_request, application_request, coverage_context, admit_next
from rubric_gen.submission_revision.rubric_generation import RubricGeneration, RubricPolicy
from test_trace_attack_defense import history, current
from test_rubric_evolution import _rubric, _development_rubric, _proposer_output

VERSION = 'attack_defense_v2.dev1'


def ref(source='artifact', start=1, end=1):
    return {'source_id': source, 'start_line': start, 'end_line': end}


def proposer(operation, retries=5):
    return RubricProposer(benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA, model='proposer', max_retries=retries,
                         run_proposer=operation, red_team_trace_version=VERSION)


def test_unicode_crlf_exact_slice_and_display():
    text = '# Result\r\n**均值**: 0.632\r\ncode = "a...b"\nlast'
    doc = PublicDocument('artifact', text)
    record = doc.resolve(2, 3)
    assert record['text'] == '**均值**: 0.632\r\ncode = "a...b"\n'
    assert text[record['char_start']:record['char_end']] == record['text']
    assert text.encode()[record['byte_start']:record['byte_end']] == record['text'].encode()
    assert '[L000002] **均值**: 0.632\r\n' in doc.model_record()['numbered_text']
    assert doc.text == text and '[L' not in doc.resolve(1, 4)['text']
    assert len(PublicDocument('artifact', 'x\n').lines) == 1 and len(doc.lines) == 4


@pytest.mark.parametrize('start,end', [(True,1),(0,1),(3,2),(1,5),(1.0,2)])
def test_bool_and_bounds_rejected(start, end):
    with pytest.raises(ValueError): PublicDocument('artifact','a\nb\nc\nd').resolve(start,end)


def test_source_contract_strict_and_exact_deduplication():
    doc = PublicDocument('artifact', '**均值**: 0.632\r\nlast')
    for pointers in [[ref('other')], [{**ref(), 'quote': 'anything'}], []]:
        with pytest.raises(EvidenceContractError): bind_references(pointers, {'artifact': doc}, required_sources=['artifact'])
    assert bind_references([], {'artifact':doc}) == []
    out = bind_references([ref(),ref(),ref(start=2,end=2)], {'artifact':doc}, required_sources=['artifact'])
    assert len(out) == 2 and out[0]['text'] == '**均值**: 0.632\r\n'
    with pytest.raises(EvidenceContractError): bind_references([ref()]*7, {'artifact':doc})


def test_registry_and_host_metadata_cannot_be_invented():
    cid = 'elicited_0123456789abcdef'
    assert allowed_actions([]) == ('NO_SUPPORTED_RELATION','PREFERENCE_CONFLICT','ADD')
    assert replacement_for_action('REPLACE:'+cid,[cid]) == (cid,)
    assert replacement_for_action('ADD',[cid]) == ()
    for action in ['Criterion 1: Cohort Selection','REPLACE:elicited_missing','NO_SUPPORTED_RELATION','PREFERENCE_CONFLICT']:
        with pytest.raises(ValueError): replacement_for_action(action, [])
    c = {'title':'Relation','requirement':'When X, check Y.','levels':[]}
    native = native_criterion_payload(c,witness_pair_id='pair_x',action='ADD',active_learned_ids=[])
    assert native['provenance_pair_ids'] == ['pair_x'] and native['replaces'] == [] and 'replaces' not in c
    with pytest.raises(ValueError): native_criterion_payload({**c,'replaces':[]},witness_pair_id='pair_x',action='ADD',active_learned_ids=[])
    for ids in [[cid,cid],['Criterion 1'],['elicited_bad']]:
        with pytest.raises(ValueError): allowed_actions(ids)


def application_contract():
    docs={'artifact':PublicDocument('artifact','The sum is 3.\nOperands: 1 + 2.')}
    return schema.ResponseContract('application',schema.application_schema(('A','B','C'),docs),docs,
                                   {'artifact':'artifact_0123456789abcdef'},labels=('A','B','C'))


def application(level='B'):
    return {'applicability':'applicable','public_refs':[ref()], 'check':'Check displayed sum.', 'level':level,'reason':'The stated sum differs.'}


def test_out_of_bounds_repaired_inside_stage_and_locked(tmp_path):
    first=application();first['public_refs']=[ref(start=99,end=99)]
    calls=[]
    def operation(*,stage,evidence,response_schema):
        calls.append(json.loads(evidence))
        value=first if len(calls)==1 else application()
        if len(calls)>1:
            assert calls[-1]['locked_fields']['level']=='B'
            assert calls[-1]['allowed_edit_fields']==['public_refs']
            assert calls[-1]['previous_response']==first
        return _proposer_output(value,stage)
    p=proposer(operation);stages=TraceStagesV2(p,tmp_path)
    assert stages.call('application',{'task':'test'},application_contract())==application()
    assert len(calls)==2
    assert stages.records[-1]['accounting']['locator_repairs']==1
    assert stages.call('application',{'task':'test'},application_contract())==application()
    assert len(calls)==2 and stages.records[-1]['cache_hit']
    result_path=Path(stages.records[-1]['receipt']);result=json.loads(result_path.read_text())
    result['outcome']['resolved_evidence']['public_refs'][0]['text']='forged'
    result['outcome_sha256']=canonical_sha256(result['outcome']);result_path.write_text(json.dumps(result))
    with pytest.raises(RuntimeError,match='source bindings'): stages.call('application',{'task':'test'},application_contract())
    assert len(calls)==2


def test_locked_field_changes_exhaust_and_never_resample_next_generation(tmp_path):
    calls=[]
    def operation(**kwargs):
        calls.append(kwargs);value=application('B' if len(calls)==1 else 'A')
        if len(calls)==1:value['public_refs']=[ref(start=99,end=99)]
        return _proposer_output(value,'application')
    stages=TraceStagesV2(proposer(operation),tmp_path)
    assert stages.call('application',{'task':'test'},application_contract()) is None
    assert len(calls)==3
    assert stages.records[-1]['outcome']['status']=='contract_exhausted'
    assert 'locked_field_changed' in json.dumps(stages.records[-1])
    stages2=TraceStagesV2(stages.proposer,tmp_path)
    assert stages2.call('application',{'task':'test'},application_contract()) is None and len(calls)==3


def test_interrupted_success_resumes_without_paid_draw(tmp_path):
    calls=[]
    def operation(**kwargs):calls.append(kwargs);return _proposer_output(application(),'application')
    stages=TraceStagesV2(proposer(operation),tmp_path)
    stages.call('application',{},application_contract())
    Path(stages.records[-1]['receipt']).unlink()
    assert stages.call('application',{},application_contract())==application() and len(calls)==1


@pytest.mark.parametrize('value',[
    {'applicability':'undecidable','public_refs':[],'check':'Public evidence unavailable.','level':None,'reason':'The displayed operands are unavailable.'},
    {'applicability':'not_applicable','public_refs':[],'check':'No covered claim.','level':'A','reason':'No sum is claimed.'},
    application('C'),
])
def test_valid_scientific_applications_are_not_retried(tmp_path,value):
    calls=[]
    def operation(**kwargs):calls.append(kwargs);return _proposer_output(value,'application')
    stages=TraceStagesV2(proposer(operation),tmp_path)
    assert stages.call('application',{},application_contract())==value and len(calls)==1


def test_incoherent_level_combination_uses_schema_correction(tmp_path):
    bad=application();bad['level']=None
    calls=[]
    def operation(**kwargs):calls.append(kwargs);return _proposer_output(bad if len(calls)==1 else application(),'application')
    stages=TraceStagesV2(proposer(operation),tmp_path)
    assert stages.call('application',{},application_contract())==application()
    assert stages.records[-1]['accounting']['schema_repairs']==1
    assert stages.records[-1]['accounting']['locator_repairs']==0


class MockPipeline:
    def __init__(self,scenario='supported'):
        self.calls=[];self.scenario=scenario
    def __call__(self,*,stage,evidence,response_schema):
        v=json.loads(evidence);self.calls.append((stage,v,response_schema))
        h=history();good=h.artifacts[0].artifact_id
        if stage=='quality':
            assert 'private_attack_evidence' not in v
            result={'artifact_assessments':{'artifact_A':'Public sum checked.','artifact_B':'Public sum checked.'},
                    'decisive_refs':[ref('artifact_A'),ref('artifact_B')],
                    'preferred_artifact_id':good,'reason':'Displayed operands support the first artifact.'}
            if self.scenario=='null_quality':result['preferred_artifact_id']=None
        elif stage=='rubric_view':
            assert set(v)=={'task','artifact','base_rubric','active_penalty_criteria','score_minimum','score_maximum'}
            assert set(v['artifact'])=={'artifact_id','content'}
            result={'artifact_id':v['artifact']['artifact_id'],'base_score':80,'criterion_levels':[], 'reason':'Base scoring.'}
        elif stage=='diagnosis':
            assert v['allowed_actions']==list(allowed_actions([])) and v['replaceable_learned_rules']==[]
            result={'action':'ADD','preferred_refs':[ref('preferred')],'rejected_refs':[ref('rejected')],
                    'relation':'The displayed operands support only one claimed sum.', 'trigger':'When a sum is claimed.',
                    'public_check':'Compute the displayed addition.','shared_defects_not_explained':'Other completion requirements.',
                    'corrective_action':'Correct the sum.','preserve_supported_work':'Keep unrelated results.','explanation':'One arithmetic relation.'}
            if self.scenario in {'equivalent','shared_defect'}:result['action']='NO_SUPPORTED_RELATION'
            if self.scenario=='conflict':result['action']='PREFERENCE_CONFLICT'
        elif stage=='compilation':
            result={'criteria':[{'title':'Displayed sum','requirement':'When stating a sum, ensure the displayed operands yield the claimed sum; repair the computation and retain unrelated results.',
                       'levels':[{'label':'A','description':'No sum claim or correct addition.'},
                                 {'label':'B','description':'Minor arithmetic discrepancy.'},
                                 {'label':'C','description':'Material arithmetic contradiction.'}]}], 'reason':'One relation.'}
            if self.scenario=='empty':result['criteria']=[]
        elif stage=='semantic':
            assert not {'public_sources','comparison','private_attack_evidence','diagnosis'} & set(v)
            result={'observable':True,'nonredundant':self.scenario!='redundant','reason':'Operational condition differs.'}
        elif stage=='application':
            assert set(v)=={'task','criterion','artifact','source_manifest'}
            assert set(v['criterion'])=={'title','requirement','levels'}
            assert 'content' not in v['artifact']
            result=application('A' if v['artifact']['artifact_id']==good else 'C')
            if self.scenario=='both_pass':result['level']='A'
            if self.scenario=='reversed':result['level']='C' if result['level']=='A' else 'A'
            if self.scenario=='undecidable':result.update(applicability='undecidable',level=None)
        else:raise AssertionError(stage)
        return _proposer_output(result,stage)


def run_pipeline(root,scenario='supported'):
    mock=MockPipeline(scenario);p=proposer(mock,0)
    kwargs=dict(instruction='Check arithmetic.',original_rubric=_rubric(),development_rubric=_development_rubric(),
        current_generation=current(),policy=RubricPolicy.RED_TEAM_TRACE,generation_round=2,output_dir=root,
        artifact_history=history(),source_checkpoint=0,source_schedule='pre_revision_v1')
    return p.elicit_rubric(**kwargs),p,mock,kwargs


def test_complete_native_pipeline_replay_and_real_reminder(tmp_path,monkeypatch):
    generation,p,mock,kwargs=run_pipeline(tmp_path)
    assert len(generation.elicited_criteria)==1
    c=generation.elicited_criteria[0]
    assert c.provenance_pair_ids==(history().pairs[0].pair_id,)
    assert tuple(points for _,points,_ in c.levels)==(0,-5,-10)
    assert generation.generation_round==2 and generation.source_checkpoint==0
    assert len(mock.calls)==10
    assert p.elicit_rubric(**kwargs)==generation and len(mock.calls)==10
    from rubric_gen.submission_revision import trace_defense_delivery as delivery
    from rubric_gen.submission_revision.feedback import ProjectedFeedback
    monkeypatch.setattr(delivery,'_validate_score_record',lambda *a:(None,None,None,{'criterion_1':60,'criterion_2':40,'criterion_3':0}))
    score=tmp_path/'score.json';score.write_text('{}')
    ordinary=ProjectedFeedback(100,{'ordinary':'unchanged'},'ordinary feedback')
    delivered=delivery.append_reminder(ordinary,generation=generation,score_validation_path=score,root=tmp_path,
        submission_id='s000',instruction='Check arithmetic.',allow_generation=True)
    assert delivered.prompt.count('## Focused review check')==1 and c.requirement in delivered.prompt
    assert delivered.payload==ordinary.payload
    assert 'not a claim that your current work violates it' in delivered.prompt


@pytest.mark.parametrize('scenario',['null_quality','equivalent','shared_defect','conflict','empty','redundant','both_pass','reversed','undecidable'])
def test_scientific_negatives_never_retry_or_activate(tmp_path,scenario):
    generation,p,mock,kwargs=run_pipeline(tmp_path,scenario)
    assert not generation.elicited_criteria
    for path in (tmp_path/'trace-defense-v2-requests').glob('*/result.json'):
        result=json.loads(path.read_text())
        assert result['outcome']['status']=='valid_result' and result['attempt_count']==1
    if scenario in {'both_pass','reversed'}:
        assert 'criterion_support_failed' in (tmp_path/'rubric-generations/generation-0002/aggregate-margins.json').read_text()


def test_version_registry_static_identity_and_mixed_generation_rejection():
    from rubric_gen.submission_revision.trace_defense_binding import method_identity
    from rubric_gen.submission_revision.trace_defense_registry import recipe
    for version in [None,'attack_defense_v1',VERSION,'attack_defense_v2']:
        assert method_identity(RubricPolicy.FIXED,version)=={}
        assert method_identity(RubricPolicy.RED_TEAM_ARTIFACT,version)=={}
    with pytest.raises(ValueError):recipe('attack_defense_v2.dev99')
    old=RubricGeneration(2,1,_rubric(),(),4)
    assert old.schedule_record()=={}
    new=RubricGeneration(2,0,_rubric(),(),4,'pre_revision_v1',VERSION)
    new.validate_successor(current())
    with pytest.raises(ValueError):replace(new,generation_round=3,source_checkpoint=1,red_team_trace_version='attack_defense_v1').validate_successor(new)
    from rubric_gen.submission_revision import trace_defense_prompts as v1, trace_defense_v2_prompts as v2
    assert (v1.RUBRIC_VIEW,v1.CORRECTIVE,v1.ANTICIPATORY)==(v2.RUBRIC_VIEW,v2.CORRECTIVE,v2.ANTICIPATORY)


def test_diagnosis_illegal_action_repairs_encoding_without_changing_relation(tmp_path):
    docs={'preferred':PublicDocument('preferred','good'), 'rejected':PublicDocument('rejected','bad')}
    contract=schema.ResponseContract('diagnosis',schema.diagnosis_schema([],docs),docs,{'preferred':'a','rejected':'b'})
    value={'action':'REPLACE:Criterion 1','preferred_refs':[ref('preferred')],'rejected_refs':[ref('rejected')],
           **{k:'Unchanged relation.' for k in ['relation','trigger','public_check','shared_defects_not_explained','corrective_action','preserve_supported_work','explanation']}}
    calls=[]
    def operation(**kwargs):
        calls.append(kwargs)
        return _proposer_output(value if len(calls)==1 else {**value,'action':'ADD'},'diagnosis')
    stages=TraceStagesV2(proposer(operation),tmp_path)
    result=stages.call('diagnosis',{},contract)
    assert result['action']=='ADD' and result['relation']==value['relation'] and len(calls)==2
    repair=json.loads(calls[1]['evidence'])
    assert 'action' in repair['allowed_edit_fields'] and repair['locked_fields']['relation']==value['relation']
    assert contract.schema['properties']['action']['enum']==list(allowed_actions([]))


def test_quality_binding_and_locked_preference_with_reversed_display(tmp_path):
    h=history();artifacts={a.artifact_id:a for a in h.artifacts}
    evidence,contract=quality_request('Task',h.pairs[0],artifacts)
    for alias in ['artifact_A','artifact_B']:
        item=evidence[alias];assert item['source_sha256']==artifacts[item['artifact_id']].content_sha256
    good={'artifact_assessments':{'artifact_A':'First assessed.','artifact_B':'Second assessed.'},
          'decisive_refs':[ref('artifact_A'),ref('artifact_B')],
          'preferred_artifact_id':evidence['artifact_B']['artifact_id'],'reason':'The second displayed artifact is preferable.'}
    bad={**good,'decisive_refs':[ref('artifact_A')]};calls=[]
    def operation(**kwargs):calls.append(kwargs);return _proposer_output(bad if len(calls)==1 else good,'quality')
    stages=TraceStagesV2(proposer(operation),tmp_path)
    assert stages.call('quality',evidence,contract)==good and len(calls)==2
    with pytest.raises(EvidenceContractError):contract.validate({**good,'decisive_refs':[ref('private_trace')]})
    assert json.loads(calls[1]['evidence'])['locked_fields']['preferred_artifact_id']==good['preferred_artifact_id']


def test_cache_identity_all_contract_dimensions(tmp_path,monkeypatch):
    stages=TraceStagesV2(proposer(lambda **kwargs:None),tmp_path)
    c=application_contract();original=stages.request('application',{'task':'x'},c)
    assert stages.request('application',{'task':'y'},c)!=original
    docs={'artifact':PublicDocument('artifact','changed')}
    assert stages.request('application',{'task':'x'},replace(c,documents=docs))!=original
    assert stages.request('application',{'task':'x'},replace(c,schema={**c.schema,'description':'new contract'}))!=original
    from rubric_gen.submission_revision import trace_defense_v2_prompts as prompts
    monkeypatch.setattr(prompts,'PROMPT_VERSION','new pinned prompt contract')
    assert stages.request('application',{'task':'x'},c)!=original
    stages2=TraceStagesV2(proposer(lambda **kwargs:None),tmp_path)
    stages2.proposer.proposer_contract=replace(stages2.proposer.proposer_contract,model='other-model')
    assert stages2.request('application',{'task':'x'},c)['provider']!=original['provider']
    docs2={'preferred':PublicDocument('preferred','x'),'rejected':PublicDocument('rejected','y')}
    c1=schema.ResponseContract('diagnosis',schema.diagnosis_schema([],docs2),docs2,{'preferred':'a','rejected':'b'})
    cid='elicited_0123456789abcdef'
    c2=replace(c1,active_ids=(cid,),schema=schema.diagnosis_schema([cid],docs2))
    assert c1.identity()!=c2.identity()


def test_sequential_replacement_reservation_and_inherited_support():
    from rubric_gen.submission_revision import evolution_protocol as p, evolution_assessment as a
    from rubric_gen.submission_revision.rubric_generation import ElicitedCriterion,render_augmented_rubric
    from test_rubric_evolution import _comparisons
    comparisons=_comparisons()[:2];first,second=comparisons
    old=ElicitedCriterion.create(title='Old condition',requirement='Check old condition.',levels=(('A',0,'Pass.'),('B',-5,'Moderate.'),('C',-10,'Material.')),
         provenance_pair_ids=(first.pair_id,),source_generation=1)
    prior=RubricGeneration(1,None,render_augmented_rubric(_rubric(),(old,)),(old,),19)
    candidate=p.CriterionCandidate(ElicitedCriterion.create(title='Refined condition',requirement='Check refined condition.',levels=old.levels,
        provenance_pair_ids=(second.pair_id,),source_generation=2),(old.criterion_id,))
    ids=a.validation_artifact_ids(comparisons)
    # Satisfy the fresh witness but not inherited support: native rejection is retained.
    grades={i:'B' for i in ids};grades[second.preferred_artifact_id]='A';grades[second.rejected_artifact_id]='C'
    grades[first.preferred_artifact_id]=grades[first.rejected_artifact_id]
    validation=p.CandidateValidation(candidate.criterion.criterion_id,True,True,tuple(p.ArtifactApplication(i,grades[i],'Scoped check.') for i in ids),'Valid scope.')
    passed,decision=admit_next([],[],candidate,validation,comparisons,prior)
    assert not passed and decision.reason=='criterion_support_failed'
    reserved=set()
    if passed:reserved.update(candidate.replaces)
    available=[c.criterion_id for c in prior.elicited_criteria if c.criterion_id not in reserved]
    assert old.criterion_id in available
    # Complete strict support in a single-pair case can accept the same legal target later.
    comp=first
    candidate=replace(candidate,criterion=replace(candidate.criterion,provenance_pair_ids=(comp.pair_id,)))
    grades={comp.preferred_artifact_id:'A',comp.rejected_artifact_id:'C'}
    validation=replace(validation,artifact_applications=tuple(p.ArtifactApplication(i,l,'Checked.') for i,l in grades.items()))
    passed,decision=admit_next([],[],candidate,validation,(comp,),prior)
    assert passed
    reserved.update(candidate.replaces)
    available=[c.criterion_id for c in prior.elicited_criteria if c.criterion_id not in reserved]
    assert available==[]
    context=coverage_context(_rubric(),prior,[candidate],available)
    assert context['immutable_base_rubric']==_rubric().content
    assert [c['criterion_id'] for c in context['active_learned_rules']]==[candidate.criterion.criterion_id]
    assert context['replaceable_learned_rules']==[] and context['allowed_actions']==list(allowed_actions([]))


def test_native_global_margin_still_blocks_candidate():
    from rubric_gen.submission_revision import evolution_protocol as p, evolution_assessment as a
    from rubric_gen.submission_revision.rubric_generation import ElicitedCriterion
    from test_rubric_evolution import _comparisons
    pair=_comparisons()[0]
    # Distinct protected pair uses the same public endpoints in reversed quality direction.
    protected=replace(pair,pair_id='pair_'+'f'*16,preferred_artifact_id=pair.rejected_artifact_id,rejected_artifact_id=pair.preferred_artifact_id,
                      active_rubric_scores=tuple(reversed(pair.active_rubric_scores)),development_rubric_scores=tuple(reversed(pair.development_rubric_scores)),gap_views=())
    c=ElicitedCriterion.create(title='Scoped',requirement='Check scoped condition.',levels=(('A',0,'Pass.'),('B',-5,'Moderate.'),('C',-10,'Material.')),
        provenance_pair_ids=(pair.pair_id,),source_generation=2)
    candidate=p.CriterionCandidate(c,())
    validation=p.CandidateValidation(c.criterion_id,True,True,(p.ArtifactApplication(pair.preferred_artifact_id,'A','Pass.'),p.ArtifactApplication(pair.rejected_artifact_id,'C','Fail.')),'Observable.')
    passed,decision=admit_next([],[],candidate,validation,(pair,protected),current())
    assert not passed and decision.reason=='aggregate_margin_failed'
    assert any(not m.passed and m.pair_id==protected.pair_id for m in decision.margin_checks)


@pytest.mark.parametrize('no_change',[False,True])
def test_v2_controller_timing_terminal_and_recovery(tmp_path,monkeypatch,no_change):
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
            answer={'artifact_assessments':{'artifact_A':'No defensible distinction.','artifact_B':'No defensible distinction.'},
                    'decisive_refs':[], 'preferred_artifact_id':None,'reason':'Unordered.'}
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

