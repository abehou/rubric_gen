"""Exercise native ownership, scheduling, scope and durable resume boundaries."""
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import threading
import time
from types import SimpleNamespace

import pytest
import yaml

from rubric_gen.runtime.audit_execution import AuditExecutor, audit_owner
from rubric_gen.runtime.capacity import reservation, Slots
from rubric_gen.runtime import capacity
from rubric_gen.submission_revision.assignments import ExperimentAssignment
from rubric_gen.submission_revision.source_resolution import assemble_consumer_ledger, resolve_study_sources
from rubric_gen.submission_revision.study import StudyRunner, StudyRunConfig
from rubric_gen.submission_revision.experiment import load_experiment
from test_experiment import _payload, _task


def _scope(tmp_path):
    assignments = tuple(ExperimentAssignment(f'da-{task}-1', rep, 'luna', condition, i + 1, i + 1)
        for i, (task, rep, condition) in enumerate((t,r,c) for t in range(20) for r in range(1,4)
            for c in ('full-static','user-simulator-static','full-red-team-trace','user-simulator-red-team-trace')))
    exp = SimpleNamespace(assignments=assignments, execution_conditions=('full-red-team-trace','user-simulator-red-team-trace'),
                          experiment_id='consumer', path=tmp_path/'experiment.yaml',
                          protocol={}, benchmark='biomnibench-da', tasks_dir=tmp_path/'tasks',
                          dag={k:{'output_dir':str(tmp_path/k)} for k in ('seed','paraphrase','revise')})
    exp.task_dir=lambda task:exp.tasks_dir/task
    exp.execution_assignments=tuple(a for a in assignments if a.condition_id in exp.execution_conditions)
    rows=[dict(a.record_identity(), status='completed' if a in exp.execution_assignments else 'pending') for a in assignments]
    ledger=dict(kind='rubric-gen-randomized-revision-study',experiment_id='consumer',experiment_path=str(exp.path),
                seed_run_dir=exp.dag['seed']['output_dir'],paraphrase_run_dir=exp.dag['paraphrase']['output_dir'],
                pretreatment_rubric_root=str(tmp_path/'revise'/'pretreatment-rubrics'),status='completed_scope',
                execution_conditions=list(exp.execution_conditions),records=rows)
    return exp, ledger


def test_full_ledger_assembly_keeps_pending_static_and_recovery_subset(tmp_path):
    exp, producer = _scope(tmp_path)
    before = deepcopy(producer)
    recovered = [dict(r) for r in producer['records'] if r['status']=='completed'][-2:]
    for r in producer['records']:
        if r['assignment_id'] in {c['assignment_id'] for c in recovered}:r['status']='failed'
    saved = deepcopy(producer)
    assembled=assemble_consumer_ledger(exp, {'records':recovered}, producer)
    assert producer==saved
    assert len(assembled['records'])==240
    assert sum(r['status']=='completed' for r in assembled['records'])==120
    assert sum(r['status']=='pending' for r in assembled['records'])==120
    assert 'execution_assignment_ids' not in assembled
    with pytest.raises(ValueError,match='full experiment'):
        assemble_consumer_ledger(exp, {'records':recovered}, {'records':producer['records'][:120]})


def test_native_source_rejects_wrong_task_producer_or_storage(tmp_path):
    exp, ledger = _scope(tmp_path)
    root=tmp_path/'revise';root.mkdir()
    (root/'study.json').write_text(json.dumps(ledger))
    for a in exp.execution_assignments:
        d=root/a.study_relative_path;d.mkdir(parents=True)
        (d/'manifest.json').write_text(json.dumps({**{k:v for k,v in a.record_identity().items() if k!='experiment_dir'},
            'kind':'rubric-gen-submission-revision-experiment','experiment_id':'consumer',
            'benchmark':'biomnibench-da','task_dir':str(exp.task_dir(a.task_id))}))
        (d/'state.json').write_text('{}')
    assert len(resolve_study_sources(root,exp).revisions)==120
    path=root/exp.execution_assignments[0].study_relative_path/'manifest.json'
    original=path.read_text()
    for field,value in [('task_id','wrong'),('replicate',9),('condition_id','full-static'),('experiment_id','producer')]:
        data=json.loads(original);data[field]=value;path.write_text(json.dumps(data))
        with pytest.raises(ValueError,match='producer identity'):
            resolve_study_sources(root,exp)
    path.write_text(original)
    bad=deepcopy(ledger);bad['records'][2]['experiment_dir']='wrong/tree';(root/'study.json').write_text(json.dumps(bad))
    with pytest.raises(RuntimeError,match='record identity'):
        resolve_study_sources(root,exp)


def test_audit_owned_stages_share_pool_and_leave_capacity_for_other_provider(tmp_path):
    held=threading.Event(); release=threading.Event(); other=threading.Event()
    active=0; peak=0; lock=threading.Lock()
    def operation(model):
        nonlocal active, peak
        with reservation():
            with lock: active+=1;peak=max(peak,active)
            if model.startswith('claude'):
                held.set(); assert release.wait(5)
            else: other.set()
            with lock: active-=1
        return model
    with audit_owner(tmp_path/'audit'):
        assert Slots(Path(capacity.policy()['coordination_dir'])/'audit',1).active_count()==1
        with AuditExecutor(8,('claude-test','gpt-test')) as pool:
            slow=[pool.submit(operation,'claude-test',model='claude-test') for _ in range(12)]
            assert held.wait(2)
            fast=pool.submit(operation,'gpt-test',model='gpt-test')
            assert other.wait(2), 'slow provider consumed every request worker'
            release.set()
            assert fast.result(2)=='gpt-test'
            assert all(f.result(2)=='claude-test' for f in slow)
    assert peak<=8


def test_audit_output_owner_excludes_second_owner(tmp_path):
    with audit_owner(tmp_path/'audit'):
        with pytest.raises(RuntimeError,match='already owns'):
            with audit_owner(tmp_path/'audit'):
                pass


def test_native_18_assignment_scheduler_profiles(tmp_path,monkeypatch):
    import rubric_gen.submission_revision.study as module
    tasks=['da-1-1','da-2-1','da-3-1']
    for task in tasks:_task(tmp_path,task)
    payload=_payload(tmp_path);payload['tasks']=tasks
    payload['conditions']=[c for c in payload['conditions'] if c['condition_id'] in ('full-static','user-simulator-static')]
    path=tmp_path/'experiment.yaml';path.write_text(yaml.safe_dump(payload)); exp=load_experiment(path)
    monkeypatch.setattr(module.paraphrase_validation,'validate_paraphrase_run',lambda *a:None)
    monkeypatch.setattr(module.study_validation,'validate_completed_revision',lambda *a:None)
    monkeypatch.setattr(StudyRunner,'_prepare_pretreatment_rubrics',lambda *a:None)
    monkeypatch.setattr(StudyRunner,'_revision_config',lambda self,a,resume:SimpleRevision(a.assignment_id,0))
    measurements=[]
    for workers in (2,4,8):
        events=[];guard=threading.Lock();active=0;peak=0
        def solver(config,**kwargs):
            nonlocal active,peak
            with guard:
                active+=1;peak=max(peak,active);events.append(('start',config.assignment_id,time.monotonic()))
            # Turns stay sequential within each independent assignment.
            for turn in range(3):
                with reservation(): time.sleep(.10)
                with guard:events.append((turn,config.assignment_id,time.monotonic()))
            with guard:active-=1;events.append(('end',config.assignment_id,time.monotonic()))
        monkeypatch.setattr(module,'run_submission_revision',solver)
        runner=StudyRunner(StudyRunConfig(exp,tmp_path/'seed',tmp_path/'paraphrase',tmp_path/f'study-{workers}',workers))
        started=time.monotonic();assert runner.run()==0;elapsed=time.monotonic()-started
        ledger=json.loads((runner.root/'study.json').read_text())
        assert len(ledger['records'])==18 and all(r['status']=='completed' for r in ledger['records'])
        assert peak==workers
        for a in exp.assignments:assert [event[0] for event in events if event[1]==a.assignment_id]==['start',0,1,2,'end']
        measurements.append({'workers':workers,'wall_seconds':elapsed,'peak_assignments':peak,
                             'first_dispatch_seconds':min(e[2] for e in events)-started,'assignments':18,'turns':54})
    assert measurements[0]['wall_seconds']/measurements[2]['wall_seconds']>=2
    print('FIXED_WORK_MEASUREMENTS='+json.dumps(measurements),flush=True)


from dataclasses import dataclass
@dataclass(frozen=True)
class SimpleRevision:
    assignment_id: str
    progress_position: int


def _imported_scope(tmp_path, monkeypatch):
    import os
    import rubric_gen.submission_revision.source_resolution as module
    exp, ledger = _scope(tmp_path / 'consumer')
    producer = deepcopy(exp)
    producer.experiment_id = 'producer'
    producer.path = tmp_path / 'producer.yaml'
    producer_root = tmp_path / 'producer-study'
    root = Path(exp.dag['revise']['output_dir'])
    root.mkdir(parents=True)
    producer_root.mkdir()
    producer.dag = deepcopy(exp.dag)
    producer.dag['revise']['output_dir'] = str(producer_root)
    source_ledger = deepcopy(ledger)
    source_ledger.update(status='failed_scope', experiment_id='producer', experiment_path=str(producer.path),
                         pretreatment_rubric_root=str(producer_root/'pretreatment-rubrics'))
    imports = []
    for index, assignment in enumerate(exp.execution_assignments):
        directory = root / assignment.study_relative_path
        directory.mkdir(parents=True)
        origin = producer_root / assignment.study_relative_path
        origin.mkdir(parents=True)
        manifest = {**{k:v for k,v in assignment.record_identity().items() if k != 'experiment_dir'},
                    'kind':'rubric-gen-submission-revision-experiment', 'experiment_id':'producer' if index<118 else 'consumer',
                    'benchmark':str(exp.benchmark), 'task_dir':str(exp.task_dir(assignment.task_id)), 'submission_count':7}
        state = {'phase':'completed','submission_ids':[f's{i:03d}' for i in range(7)],
                 'next_turn_index':7,'scores':[10]*7}
        (origin/'manifest.json').write_text(json.dumps(manifest))
        (origin/'state.json').write_text(json.dumps(state))
        os.link(origin/'manifest.json',directory/'manifest.json')
        os.link(origin/'state.json',directory/'state.json')
        cumulative = b''
        for turn in range(7):
            submission = directory/'submissions'/f's{turn:03d}'
            workspace=submission/'workspace'; workspace.mkdir(parents=True)
            (workspace/'answer.txt').write_text('observed result')
            (workspace/'trace.md').write_text('observed computation')
            segment = (json.dumps({'type':'message','role':'assistant','content':f'turn {turn}'})+'\n').encode()
            cumulative += segment
            (submission/'trajectory.stream.jsonl').write_bytes(cumulative)
            (submission/'snapshot.json').write_text(json.dumps({'submission_id':submission.name}))
            (submission/'status.json').write_text(json.dumps({'exit_code':0,'workspace_dir':str(origin/'submissions'/submission.name/'workspace')}))
            if turn:
                path=directory/'turns'/f'turn-{turn:03d}';path.mkdir(parents=True)
                (path/'trajectory.stream.jsonl').write_bytes(segment)
        task=exp.task_dir(assignment.task_id); task.mkdir(parents=True,exist_ok=True)
        (task/'instruction.md').write_text('Compute the observed result.')
        if index < 118:
            from rubric_gen.artifacts.hashing import sha256_file
            digest=sha256_file(origin/'manifest.json')
            receipt={'kind':'v2_to_v21_assignment_import','consumer_experiment_id':'consumer',
                'producer_experiment_id':'producer','consumer_trace_version':None,'producer_trace_version':None,
                'producer_manifest_sha256':digest}
            (directory/'consumer-import.json').write_text(json.dumps(receipt))
            imports.append({'assignment_id':assignment.assignment_id,'experiment_dir':str(assignment.study_relative_path),
                            'producer_manifest_sha256':digest})
        else:
            next(r for r in source_ledger['records'] if r['assignment_id']==assignment.assignment_id)['status']='failed'
    (root/'study.json').write_text(json.dumps(ledger))
    (producer_root/'study.json').write_text(json.dumps(source_ledger))
    cohort={'consumer_study_root':str(root),'producer_study_root':str(producer_root),
            'consumer_experiment_id':'consumer','producer_experiment_id':'producer','imports':imports}
    (root.parent.parent/'consumer-cohort.json').write_text(json.dumps(cohort))
    monkeypatch.setattr(module,'load_experiment',lambda path: producer if path==producer.path else exp)
    return exp,root,producer_root


def test_all_four_direct_and_scoring_readers_share_118_imported_two_native(tmp_path, monkeypatch):
    from rubric_gen.submission_revision.evaluation import targets as target_module
    from rubric_gen.submission_revision.evaluation.evidence import revision_detection_source
    from rubric_gen.submission_revision.detection_windows import RevisionDetectionWindow
    from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
    exp,root,producer_root=_imported_scope(tmp_path,monkeypatch)
    sources=resolve_study_sources(root,exp)
    assert len(sources.ledger['records'])==240 and len(sources.revisions)==120
    assert sum(s.producer.experiment_id=='producer' for s in sources.revisions)==118
    monkeypatch.setattr(target_module.paraphrase_validation,'resolve_paraphrase_selection',lambda *a:None)
    def target(config, study, consumer_id, assignment, record, selection, source):
        assert source.assignment==assignment and consumer_id=='consumer'
        return (assignment.assignment_id,source.producer.experiment_id)
    monkeypatch.setattr(target_module,'_load_evaluation_target',target)
    config=EvaluationConfig(exp,root,Path(exp.dag['paraphrase']['output_dir']),tmp_path/'audit',8)
    scored=target_module.load_evaluation_targets(config,sources)
    expected={s.assignment.assignment_id for s in sources.revisions}
    assert {a for a,p in scored}==expected
    shared={}
    for window in RevisionDetectionWindow:
        direct=revision_detection_source(tuple(s.directory for s in sources.revisions),tasks_dir=exp.tasks_dir,
            experiment_ids=('producer','consumer'),window=window,resolved_sources=sources.revisions,shared_inputs=shared)
        assert {c.path for c in direct.cases}=={s.directory for s in sources.revisions}
    assert len(shared)==120
    # A blanket producer whitelist would incorrectly admit this assignment.
    native=sources.revisions[-1]
    manifest=json.loads((native.directory/'manifest.json').read_text())
    manifest['experiment_id']='producer'
    from rubric_gen.artifacts.serialization import write_json_atomic
    write_json_atomic(native.directory/'manifest.json',manifest)
    with pytest.raises(ValueError,match='producer identity'):
        resolve_study_sources(root,exp)


def test_imported_status_location_is_read_time_and_hardlinks_are_unchanged(tmp_path,monkeypatch):
    import os
    from rubric_gen.submission_revision.source_resolution import relocated_workspace
    from rubric_gen.artifacts.serialization import write_json_atomic
    exp,root,producer_root=_imported_scope(tmp_path,monkeypatch)
    sources=resolve_study_sources(root,exp)
    source=sources.revisions[0]
    submission=source.directory/'submissions'/'s000'
    producer_submission=source.producer_directory/'submissions'/'s000'
    producer_submission.mkdir(parents=True)
    status=submission/'status.json'; original=status.read_bytes()
    os.link(status,producer_submission/'status.json')
    recorded=producer_submission/'workspace'
    assert relocated_workspace(submission,recorded)==submission/'workspace'
    assert status.read_bytes()==original and (producer_submission/'status.json').read_bytes()==original
    with pytest.raises(ValueError,match='documented producer'):
        relocated_workspace(submission,tmp_path/'unrelated'/'workspace')
    write_json_atomic(status,{'workspace_dir':str(submission/'workspace')})
    assert (producer_submission/'status.json').read_bytes()==original
    assert os.stat(status).st_ino!=os.stat(producer_submission/'status.json').st_ino


def test_direct_resume_keeps_known_success_and_records_ambiguous_disconnect(tmp_path,monkeypatch):
    from rubric_gen.detection.runner import DetectionRunner
    from rubric_gen.detection.jobs import DetectionConfig
    from test_detection_runner import _case, _source, _generation, _reward_hacking_text
    first=_case(tmp_path/'case-a',{'samples':[]})
    second=_case(tmp_path/'case-b',{'samples':[]})
    calls=[]
    def provider(model,request):
        calls.append(request.flat_prompt())
        if len(calls)==2: raise KeyboardInterrupt('preemption after remote dispatch')
        return _generation(model,_reward_hacking_text())
    config=DetectionConfig(source=_source(first,second),models=('gpt-test',),output_dir=tmp_path/'audit',max_concurrency=1)
    with pytest.raises(KeyboardInterrupt):
        DetectionRunner(config,generate_response=provider).run()
    known=next((config.output_dir/'cases').glob('*/gpt-test/score.json'))
    preserved=known.read_bytes()
    unknown=config.output_dir/'cases/case-b/gpt-test/chunk-001/attempt-001.json'
    assert json.loads(unknown.read_text())['remote_completion']=='unknown'
    assert DetectionRunner(replace(config,resume=True),generate_response=provider).run()==0
    assert len(calls)==3 and known.read_bytes()==preserved
    assert json.loads(unknown.read_text())['remote_completion']=='unknown'
    assert (unknown.parent/'attempt-002.json').is_file()
    assert DetectionRunner(replace(config,resume=True),generate_response=provider).run()==0
    assert len(calls)==3


def test_full_rubric_raw_response_survives_publication_failure(tmp_path,monkeypatch):
    from rubric_gen.submission_revision.evaluation import rubric_judge as module
    from rubric_gen.submission_revision.judging.full_rubric_protocol import FullRubricGeneration
    from rubric_gen.submission_revision.judge import FrozenRubric, SubmissionJudgeConfig
    from rubric_gen.benchmarks import SubmissionBenchmarkId
    from rubric_gen.artifacts.hashing import sha256_text
    from test_evaluation_rubric_judge import RUBRIC
    task=tmp_path/'task';task.mkdir()
    rubric_path=task/'rubric.txt';rubric_path.write_text(RUBRIC)
    submission=tmp_path/'s000';submission.mkdir()
    judge=module.RubricScoreJudge(SubmissionJudgeConfig(task_dir=task,experiment_dir=tmp_path/'audit',
        benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,review='trace',judge_model='gpt-5.6-sol',
        rubric_name=None,rubric_set=None,rubric_path=rubric_path,max_review_chars=None),
        FrozenRubric(RUBRIC,sha256_text(RUBRIC),'rubric-path',None,None,None,None))
    judge._review_delegate=SimpleNamespace(review_inputs=lambda _:('workspace','answer'))
    calls=[]
    def provider(spec,**kwargs):
        calls.append(spec)
        return FullRubricGeneration(text=json.dumps({'criteria':[{'level_index':0,'reason':'observed'} for _ in range(spec.criterion_count)],'overall_reasoning':'observed'}),
            provider=spec.provider,requested_model=spec.requested_model,effective_model=spec.requested_model,
            response_id='terminal-1',request_parameters=module._request_parameters(spec),usage={})
    monkeypatch.setattr(module,'_generate_response',provider)
    original=judge._publish
    def fail_publication(**kwargs): raise OSError('owned filesystem publication interrupted')
    monkeypatch.setattr(judge,'_publish',fail_publication)
    with pytest.raises(OSError): judge.evaluate(submission,'a'*32)
    assert len(calls)==1
    raw=next((tmp_path/'audit').rglob('attempt-001.response.json'))
    assert json.loads(raw.read_text())['generation']['response_id']=='terminal-1'
    monkeypatch.setattr(judge,'_publish',original)
    result=judge.evaluate(submission,'a'*32)
    assert result.evaluation_path.is_file() and len(calls)==1
    assert judge.evaluate(submission,'a'*32)==result and len(calls)==1


def test_completed_cleanup_failure_is_local_and_preserves_scientific_output(tmp_path,monkeypatch):
    import errno
    from rubric_gen.submission_revision import artifacts
    experiment=tmp_path/'experiment';experiment.mkdir()
    (experiment/'manifest.json').write_text('{"completed":true}')
    monkeypatch.setattr(artifacts,'live_root_parent',lambda:tmp_path)
    live=tmp_path/(artifacts.LIVE_ROOT_PREFIX+'test');live.mkdir();(live/'temporary').write_text('closed temporary file')
    artifacts.write_live_root_sentinel(live,experiment)
    def busy(*args,**kwargs): raise OSError(errno.EBUSY,'NFS temporary busy')
    monkeypatch.setattr(artifacts,'_force_remove_directory',busy)
    artifacts.retire_completed_live_tree(live,experiment)
    assert (experiment/'manifest.json').read_text()=='{"completed":true}'
    assert not live.exists()
    assert (experiment/'cleanup.json').is_file()


def test_preparation_dispatches_before_slow_source_and_reads_once(tmp_path, monkeypatch):
    from dataclasses import asdict
    import matplotlib.pyplot as plt
    from rubric_gen.detection.runner import DetectionRunner
    from rubric_gen.detection.jobs import DetectionConfig
    from rubric_gen.detection.sources import AuditSource, AuditCase
    from rubric_gen.detection.prompts import EvidencePrompt
    from test_detection_runner import _generation, _reward_hacking_text
    cases=tuple(AuditCase(str(i),'transcript',tmp_path/str(i),(str(i),)) for i in range(18))
    # Equalize one-time plotting/font startup before either timed invocation.
    figure=plt.figure();figure.savefig(tmp_path/'plot-startup.png');plt.close(figure)
    results=[]
    for serial in (True,False):
        reads=[];calls=[];source_bytes=[];request_bytes=[];finished=[];preparation=[]
        active=0;peak=0;lock=threading.Lock();start=time.monotonic()
        def payload(case,detection):
            began=time.monotonic()
            time.sleep(.08)
            reads.append(case.case_id)
            result=EvidencePrompt(instructions='unchanged', evidence='fixed evidence',
                task_context='task '+case.case_id, behavior_messages=('user: original task','assistant: completed'), stats={})
            source_bytes.append(len(json.dumps(asdict(result),sort_keys=True).encode()))
            preparation.append(time.monotonic()-began)
            return result
        source=AuditSource(cases=cases,provenance={'kind':'controlled-runtime-work'},load_prompt=payload)
        def generate(model,request):
            nonlocal active,peak
            request_bytes.append(len(json.dumps(asdict(request),sort_keys=True).encode()))
            with lock:
                active+=1;peak=max(peak,active);calls.append(time.monotonic()-start)
            time.sleep(.02)
            with lock:
                active-=1;finished.append(time.monotonic()-start)
            return _generation(model,_reward_hacking_text())
        runner=DetectionRunner(DetectionConfig(source=source, models=('gpt-5.6-sol', 'claude-opus-5'),
            output_dir=tmp_path/('serial' if serial else 'pipeline'), max_concurrency=8),
            generate_response=generate, count_tokens=lambda *a:100)
        if serial:
            # Reproduce the former serial source-loading boundary, retaining
            # the same request preparation, panel executor and scientific inputs.
            prepared=[]
            for case in cases:
                p=runner._payload(case)
                for model in runner.config.models: prepared.append(runner._prepare_job(case,model,p))
            from rubric_gen.detection.jobs import PreparedPanel
            assert runner.run_prepared(PreparedPanel(tuple(prepared),()))==0
        else:
            assert runner.run()==0
        results.append({'serial':serial,'elapsed':time.monotonic()-start,'first_dispatch':min(calls),
                        'source_reads':len(reads),'source_payload_bytes':sum(source_bytes),
                        'request_bytes':sum(request_bytes),'requests':len(calls),'peak_active_requests':peak,
                        'aggregate_source_preparation_seconds':sum(preparation),'last_generation':max(finished),
                        'post_generation_seconds':time.monotonic()-start-max(finished)})
        assert len(reads)==18 and len(set(reads))==18 and len(calls)==36
    print('PREPARATION_COMPARISON',json.dumps(results))
    assert results[1]['first_dispatch'] < results[0]['first_dispatch']/2
    assert results[1]['elapsed'] < results[0]['elapsed']/2
    assert results[0]['source_payload_bytes']==results[1]['source_payload_bytes']
    assert results[0]['request_bytes']==results[1]['request_bytes']


@pytest.mark.parametrize('status,category',[(429,'transient_provider'),(529,'transient_provider'),
                                           (401,'authentication'),(400,'configuration')])
def test_token_preparation_retries_only_transients_without_active_reservations(tmp_path,monkeypatch,status,category):
    from rubric_gen.detection.runner import DetectionRunner
    from rubric_gen.runtime.failures import failure_category
    import httpx
    from openai import APIStatusError
    error=APIStatusError('controlled provider failure',response=httpx.Response(status,
        headers={'Retry-After':'0'},request=httpx.Request('POST','https://provider.invalid')),body=None)
    assert failure_category(error)==category
    calls=[]
    def count(*args):
        calls.append(1)
        assert Slots(Path(capacity.policy()['coordination_dir'])/'provider',60).active_count()==0
        raise error
    runner=DetectionRunner.__new__(DetectionRunner);runner.count_tokens=count
    with pytest.raises(APIStatusError):runner._count_preparation_tokens('gpt-5.6-sol',None)
    assert len(calls)==(3 if status in (429,529) else 1)


def test_resume_never_rebuys_a_known_direct_score_with_incompatible_metadata(tmp_path):
    from rubric_gen.detection.runner import DetectionRunner
    from rubric_gen.detection.jobs import DetectionConfig
    from test_detection_runner import _case, _source, _generation, _reward_hacking_text
    import shutil
    case=_case(tmp_path/'case',{'samples':[]});calls=[]
    def provider(model,request):
        calls.append(request);return _generation(model,_reward_hacking_text())
    config=DetectionConfig(source=_source(case),models=('gpt-test',),output_dir=tmp_path/'audit')
    assert DetectionRunner(config,generate_response=provider).run()==0
    path=next(config.output_dir.glob('cases/*/*/score.json'))
    data=json.loads(path.read_text());data['identity']['input_tokens']=[999]
    path.write_text(json.dumps(data));preserved=path.read_bytes()
    for root in path.parent.glob('chunk-*'):shutil.rmtree(root)
    assert DetectionRunner(replace(config,resume=True),generate_response=provider).run()==1
    assert len(calls)==1 and path.read_bytes()==preserved
    result=json.loads((config.output_dir/'summary.json').read_text())
    assert 'refusing duplicate generation' in result['records'][0]['error']


def test_imported_state_must_match_its_documented_producer(tmp_path,monkeypatch):
    exp,root,producer_root=_imported_scope(tmp_path,monkeypatch)
    sources=resolve_study_sources(root,exp)
    source=sources.revisions[0]
    path=source.directory/'state.json'
    state=json.loads(path.read_text());state['scores']=[99]*len(state['scores'])
    from rubric_gen.artifacts.serialization import write_json_atomic
    write_json_atomic(path,state)
    with pytest.raises(ValueError,match='scientific state differs'):
        resolve_study_sources(root,exp)


def test_completed_direct_preparation_uses_saved_counts_and_republishes_without_http(tmp_path):
    from rubric_gen.detection.runner import DetectionRunner
    from rubric_gen.detection.jobs import DetectionConfig
    from test_detection_runner import _case, _source, _generation, _reward_hacking_text
    case=_case(tmp_path/'case',{'samples':[]});calls=[];counts=[]
    def provider(model,request):
        calls.append(request);return _generation(model,_reward_hacking_text())
    def counter(*args):counts.append(1);return 100
    config=DetectionConfig(source=_source(case),models=('gpt-test',),output_dir=tmp_path/'audit')
    assert DetectionRunner(config,generate_response=provider,count_tokens=counter).run()==0
    summary=(config.output_dir/'summary.json').read_bytes()
    runner=DetectionRunner(replace(config,resume=True),generate_response=provider,count_tokens=counter)
    runner._write_or_validate_run_settings()
    assert runner.prepare_resume()
    assert runner.run_prepared()==0
    assert (config.output_dir/'summary.json').read_bytes()==summary
    (config.output_dir/'summary.json').unlink()
    assert runner.run_prepared()==0
    assert len(calls)==len(counts)==1


def test_completed_suite_does_not_wait_for_an_active_generation_study(tmp_path,monkeypatch):
    import argparse
    from rubric_gen.submission_revision import commands, source_resolution
    from rubric_gen.submission_revision.evaluation import targets, runner, direct
    exp=SimpleNamespace(dag={'revise':{'output_dir':str(tmp_path/'study')},
        'paraphrase':{'output_dir':str(tmp_path/'pool')},'detect':{'output_dir':str(tmp_path/'audit')}},
        outcome_audit={'models':['gpt-test','claude-test']})
    monkeypatch.setattr(commands,'load_experiment',lambda _:exp)
    monkeypatch.setattr(source_resolution,'resolve_study_sources',lambda *a:object())
    monkeypatch.setattr(targets,'load_evaluation_targets',lambda *a:())
    completed=[]
    class Finished:
        def __init__(self,*a):pass
        def preflight(self):pass
        def prepare_resume(self):return True
        def run_prepared(self,executor=None):
            assert Slots(Path(capacity.policy()['coordination_dir'])/'audit',1).active_count()==1
            completed.append(1);return 0
    monkeypatch.setattr(runner,'RubricScoreRunner',Finished)
    monkeypatch.setattr(runner,'RubricFreeScoreRunner',Finished)
    monkeypatch.setattr(direct,'prepare_direct_detection',lambda *a:Finished())
    with ThreadPoolExecutor(max_workers=1) as pool:
        with reservation('audit'):
            future=pool.submit(commands.run_detect,argparse.Namespace(experiment='fixture.yaml',max_concurrency=8,resume=True))
            assert future.result(timeout=3)==0
    assert len(completed)==6


@pytest.mark.parametrize('condition_scope',[True,False])
def test_native_revision_resume_retains_declared_assignment_subset(tmp_path,monkeypatch,condition_scope):
    from rubric_gen.submission_revision import study as module
    for task in ('da-1-1','da-2-1','da-3-1'):_task(tmp_path,task)
    payload=_payload(tmp_path);payload['tasks']=['da-1-1','da-2-1','da-3-1']
    payload['conditions']=[c for c in payload['conditions'] if c['condition_id'] in ('full-static','user-simulator-static')]
    if not condition_scope: payload.pop('execution_conditions',None)
    path=tmp_path/'experiment.yaml';path.write_text(yaml.safe_dump(payload));exp=load_experiment(path)
    root=Path(exp.dag['revise']['output_dir'])
    selected=tuple(a.assignment_id for a in exp.execution_assignments[:2])
    monkeypatch.setattr(module.paraphrase_validation,'validate_paraphrase_run',lambda *a:None)
    monkeypatch.setattr(module.study_validation,'validate_completed_revision',lambda *a:None)
    monkeypatch.setattr(StudyRunner,'_prepare_pretreatment_rubrics',lambda *a:None)
    monkeypatch.setattr(StudyRunner,'_revision_config',lambda self,a,resume:SimpleRevision(a.assignment_id,0))
    calls=[]
    monkeypatch.setattr(module,'run_submission_revision',lambda cfg,**kw:calls.append(cfg.assignment_id))
    config=StudyRunConfig(exp,Path(exp.dag['seed']['output_dir']),Path(exp.dag['paraphrase']['output_dir']),root,8,assignment_ids=selected)
    assert StudyRunner(config).run()==0
    for assignment in exp.execution_assignments[:2]:
        d=root/assignment.study_relative_path;d.mkdir(parents=True)
        (d/'manifest.json').write_text(json.dumps({**{k:v for k,v in assignment.record_identity().items() if k!='experiment_dir'},
            'kind':'rubric-gen-submission-revision-experiment','experiment_id':exp.experiment_id,
            'benchmark':exp.benchmark.value,'task_dir':str(exp.task_dir(assignment.task_id))}))
        (d/'state.json').write_text('{}')
    assert StudyRunner(replace(config,resume=True,assignment_ids=None)).run()==0
    ledger=json.loads((root/'study.json').read_text())
    assert ledger['execution_assignment_ids']==list(selected)
    assert set(calls)==set(selected) and len(calls)==2
    assert len(ledger['records'])==18
    assert sum(r['status']=='pending' for r in ledger['records'])==16
    from rubric_gen.submission_revision.execution_scope import terminal_records
    assert {row['assignment_id'] for row in terminal_records(exp,ledger)}==set(selected)
