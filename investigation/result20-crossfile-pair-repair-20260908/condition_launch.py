"""Private, source-sealed matched dev3 launcher with native same-job recovery."""
import argparse,hashlib,json,os,signal,socket,subprocess,sys,threading,time
from datetime import datetime,timezone
from pathlib import Path
from dotenv import dotenv_values
from rubric_gen.runtime.paths import PROJECT_ROOT as CODE_ROOT
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.study import _exclusive_study_lease
ROOT=Path('/home/aydanh/repos/rubric_gen');BUNDLE=Path(__file__).parent
sys.path.insert(0,str(CODE_ROOT/'scripts/babel'))
from launch import check_shared_mount
from monitor import Monitor
from stage_recovery import run_revision_attempts

ACCEPTANCE={'trace': True}
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def gate(arm,task):
    if arm not in ACCEPTANCE or task not in {'results20'}:raise ValueError('outside approved comparison')
    original=ROOT/'runs/babel-result20-crossfile-consistency-20260908/trace/study/biomnibench-da-factorial-r10-f0203f5d69f3/study.json'
    records=json.loads(original.read_text())['records']
    failed=[r for r in records if r['assignment_id']=='da-13-3--rep-001--solver-luna--user-simulator-red-team-trace']
    if len(failed)!=1 or failed[0]['status']!='failed' or failed[0].get('error')!='artifact history has invalid red-team evidence':
        raise RuntimeError('original cell is not the authorized terminal infrastructure failure')
    receipt=BUNDLE/'acceptance.json'
    accepted=json.loads(receipt.read_text())
    if not accepted['success'] or arm not in {r['arm'] for r in accepted['inputs']}:raise RuntimeError('acceptance incomplete')
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=CODE_ROOT,text=True).strip()
    if commit!=accepted['commit']:raise RuntimeError('wrong source commit')
    for name,h in accepted['source_hashes'].items():
        if sha(name)!=h:raise RuntimeError('validated source changed')
    config=BUNDLE/f'{arm}-{task}.yaml'
    row=next(x for x in accepted['inputs'] if x['task']==task and x['arm']==arm)
    if sha(config)!=row['config_sha256']:raise RuntimeError('validated config changed')
    return load_experiment(config),receipt,commit

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('arm',choices=list(ACCEPTANCE));p.add_argument('task',choices=['results20']);p.add_argument('--workers',type=int,default=60);p.add_argument('--audit-workers',type=int,default=60);a=p.parse_args()
    if not os.environ.get('SLURM_JOB_ID'):raise RuntimeError('Slurm required')
    if not all(1<=n<=60 for n in (a.workers,a.audit_workers)):p.error('workers must be 1–60')
    exp,acceptance,commit=gate(a.arm,a.task);mount=check_shared_mount()
    # Native validators run again before credentials or new experiment mutation.
    from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run
    from rubric_gen.submission_revision.seeds import resolve_seed
    validate_paraphrase_run(Path(exp.dag['paraphrase']['output_dir']),exp)
    for task_id in exp.task_ids:
        for rep in range(1,4):resolve_seed(Path(exp.dag['seed']['output_dir']),exp.task_dir(task_id),rep,seed_generator=exp.seed_agent_config(),prompt_profile=exp.protocol['prompt'],benchmark=exp.benchmark)
    owner=ROOT/f'runs/babel-result20-crossfile-pair-repair-20260908/owners/{a.arm}-{a.task}';owner.mkdir(parents=True,exist_ok=True)
    with _exclusive_study_lease(owner):
        files=[*CODE_ROOT.joinpath('src').rglob('*.py'),*CODE_ROOT.joinpath('scripts/babel').glob('*.py'),CODE_ROOT/'uv.lock',CODE_ROOT/'pyproject.toml',CODE_ROOT/'config/runtime.json',exp.path,acceptance,Path(__file__),BUNDLE/'condition.sbatch',CODE_ROOT/'scripts/diagnostics/check_audit_coverage.py',CODE_ROOT/'scripts/diagnostics/artifact_locations.py']
        frozen={str(x.resolve()):sha(x) for x in files};identity=owner/'runtime-identity.json'
        if identity.exists() and json.loads(identity.read_text())!=frozen:raise RuntimeError('source/config changed; refuse incompatible resume')
        if not identity.exists():identity.write_text(json.dumps(frozen,indent=2)+'\n')
        def verify():
            if any(sha(n)!=h for n,h in frozen.items()):raise RuntimeError('frozen source/config changed')
        credentials=dotenv_values(ROOT/'.env.local')
        for key in ['OPENAI_API_KEY','ANTHROPIC_API_KEY']:
            if not credentials.get(key):raise RuntimeError('missing configured provider credential')
            os.environ[key]=credentials[key]
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');receipt=owner/f'{os.environ["SLURM_JOB_ID"]}-{stamp}';receipt.mkdir()
        launch=dict(job_id=os.environ['SLURM_JOB_ID'],hostname=socket.gethostname(),started_at=stamp,arm=a.arm,task=a.task,git_commit=commit,config=str(exp.path),experiment_id=exp.experiment_id,outputs=exp.dag,source_hashes=frozen,command=sys.argv,workers=a.workers,audit_workers=a.audit_workers,policy=policy(),mount=mount,resume=True,resource_request=dict(account=None,partition='preempt',qos='preempt_cpu_qos',cpus=4,memory='128G',nodes=1,tasks=1,gpus=0,time='2-00:00:00'),live_root=os.environ['BIOMNIBENCH_LIVE_ROOT'])
        (receipt/'launch.json').write_text(json.dumps(launch,indent=2)+'\n')
        stop=threading.Event();signal.signal(signal.SIGTERM,lambda *_:stop.set());signal.signal(signal.SIGINT,lambda *_:stop.set())
        monitor=Monitor(policy()['coordination_dir'],receipt/'metrics.jsonl',[exp.dag['revise']['output_dir']])
        def stage(name,limit,attempt=1):
            verify();cmd=[str(Path(sys.executable).with_name('rubric-gen')),name,'--experiment',str(exp.path),'--max-concurrency',str(limit),'--resume'];label=f'{name}-{attempt}'
            (receipt/f'{label}-command.json').write_text(json.dumps(cmd)+'\n')
            with (receipt/f'{label}.log').open('x') as log:
                child=subprocess.Popen(cmd,cwd=CODE_ROOT,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);stopped=None;sample_at=0
                try:
                    while child.poll() is None:
                        if time.monotonic()>=sample_at:monitor.sample();sample_at=time.monotonic()+30
                        if stop.is_set():
                            stopped=stopped or time.monotonic()
                            try:os.killpg(child.pid,signal.SIGKILL if time.monotonic()-stopped>120 else signal.SIGTERM)
                            except ProcessLookupError:pass
                        time.sleep(1)
                except BaseException:
                    try:os.killpg(child.pid,signal.SIGTERM)
                    except ProcessLookupError:pass
                    try:child.wait(timeout=120)
                    except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
                    raise
                return child.wait()
        exits=[run_revision_attempts(lambda attempt:stage('revise',a.workers,attempt),study_root=exp.dag['revise']['output_dir'],receipt=receipt,label='revise',stop=stop,verify_source=verify)]
        if exits==[0] and not stop.is_set():exits.append(stage('detect',a.audit_workers))
        coverage=None
        if exits==[0,0] and not stop.is_set():
            sys.path.insert(0,str(CODE_ROOT/'scripts/diagnostics'));from check_audit_coverage import check
            coverage=check(Path(exp.dag['revise']['output_dir']),Path(exp.dag['detect']['output_dir']),expected_models=exp.outcome_audit['models'])
            if coverage['assignment_count']!=len(exp.execution_assignments):raise RuntimeError('coverage count mismatch')
            (receipt/'coverage.json').write_text(json.dumps(coverage,indent=2)+'\n')
        verify();monitor.sample();success=exits==[0,0] and coverage is not None and not stop.is_set()
        (receipt/'result.json').write_text(json.dumps(dict(success=success,exits=exits,source_unchanged=True))+'\n');return int(not success)
if __name__=='__main__':raise SystemExit(main())
