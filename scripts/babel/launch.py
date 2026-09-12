"""Private Slurm dispatcher for the fixed two-task dev3 continuation."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
from dotenv import dotenv_values
from monitor import Monitor
from stage_recovery import run_revision_attempts
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run
from rubric_gen.submission_revision.seeds import resolve_seed
from rubric_gen.submission_revision.judging.executor import JudgeExecutor
from rubric_gen.submission_revision.study import _exclusive_study_lease

ROOT=Path(__file__).resolve().parents[2]


def digest(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def configurations(mode):
    if mode=='result20':return [load_experiment(ROOT/'experiments/babel/biomnibench-result20-wiring-control.yaml')]
    names=['biomnibench-dev3-control-da-3-4.yaml'] if mode=='smoke' else [f'biomnibench-dev3-control-{task}.yaml' for task in ('da-3-4','da-11-1')]
    return [load_experiment(ROOT/'experiments/babel'/name) for name in names]


def validate_inputs(experiments):
    for exp in experiments:
        allowed={'da-3-4','da-11-1'} | set(configurations('result20')[0].task_ids)
        if not set(exp.task_ids)<=allowed:raise RuntimeError('outside authorized task population')
        validate_paraphrase_run(Path(exp.dag['paraphrase']['output_dir']),exp)
        for task in exp.task_ids:
            for rep in range(1,exp.replicates+1):
                seed=resolve_seed(Path(exp.dag['seed']['output_dir']),exp.task_dir(task),rep,
                    seed_generator=exp.seed_agent_config(),prompt_profile=exp.protocol['prompt'],benchmark=exp.benchmark)
                if seed.manifest['scoring_identity']['scoring_implementation_sha256']!=JudgeExecutor.scoring_implementation_sha256(exp.benchmark):
                    raise RuntimeError('seed judge execution identity changed')


def check_shared_mount():
    settings=policy()
    target=Path(settings['coordination_dir'])
    while not target.exists():target=target.parent
    fields=subprocess.check_output(['findmnt','--noheadings','--output','FSTYPE,OPTIONS','--target',str(target)],text=True).strip().split(None,1)
    if len(fields)!=2 or fields[0] not in ('nfs','nfs4') or 'local_lock=none' not in fields[1].split(',') or 'nolock' in fields[1].split(','):
        raise RuntimeError('Babel admission requires shared NFS server locking (local_lock=none)')
    return dict(filesystem=fields[0],server_locking=True)



def verify_smoke_outputs():
    """Require all declared current-format outputs before task-scale continuation."""
    sys.path.insert(0,str(ROOT/'scripts/diagnostics'))
    from check_audit_coverage import check
    exp=configurations('smoke')[0]
    coverage=check(Path(exp.dag['revise']['output_dir']),Path(exp.dag['detect']['output_dir']),expected_models=exp.outcome_audit['models'])
    if coverage['assignment_count']!=len(exp.execution_assignments):raise RuntimeError('scientific smoke assignment coverage changed')
    return coverage


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('mode',choices=['smoke','full','result20'])
    parser.add_argument('--recovery',action='store_true')
    parser.add_argument('--workers',type=int)
    parser.add_argument('--audit-workers',type=int)
    args=parser.parse_args()
    for value in (args.workers,args.audit_workers):
        if value is not None and not 1 <= value <= 60:parser.error('workers must be 1–60')
    if not os.environ.get('SLURM_JOB_ID'):raise RuntimeError('launch requires a Slurm allocation')
    os.chdir(ROOT)
    settings=policy()
    shared_mount=check_shared_mount()
    experiments=configurations(args.mode)
    if args.mode!='result20':validate_inputs(experiments)
    else:
        for task in experiments[0].task_ids:
            if not (experiments[0].task_dir(task)/'tests/rubric.txt').is_file():raise RuntimeError('missing Result20 task input')
    for key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY'):
        value=dotenv_values(ROOT/'.env.local').get(key)
        if not value:raise RuntimeError(f'missing {key}')
        os.environ[key]=value
    workers=32 if args.mode=='result20' else 8
    audits=32 if args.mode=='result20' else 8
    workers=args.workers or workers
    audits=args.audit_workers or audits
    output=ROOT/'runs/babel-dev3-20260907'
    output.mkdir(parents=True,exist_ok=True)
    # Same-profile launch ownership prevents two dispatchers racing resume receipts.
    owner=output/('dispatcher-'+args.mode);owner.mkdir(exist_ok=True)
    with _exclusive_study_lease(owner):
        frozen={str(p.relative_to(ROOT)):digest(p) for p in (ROOT/'src').rglob('*.py')}
        for p in [ROOT/'uv.lock',ROOT/'pyproject.toml',ROOT/'config/runtime.json',*Path(__file__).parent.glob('*.py'),Path(__file__).with_name('dev3.sbatch'),*[e.path for e in experiments],ROOT/'scripts/diagnostics/check_audit_coverage.py',ROOT/'scripts/diagnostics/artifact_locations.py']:
            frozen[str(p.relative_to(ROOT))]=digest(p)
        for exp in ([] if args.mode=='result20' else experiments):
            pool=Path(exp.dag['paraphrase']['output_dir'])
            inputs=[pool/'manifest.json']
            for task in exp.task_ids:
                inputs.extend(p for p in (pool/'tasks'/task).glob('variant-*') if p.is_file())
                for rep in range(1,exp.replicates+1):
                    inputs.append(Path(exp.dag['seed']['output_dir'])/'tasks'/task/f'rep-{rep:03d}'/'manifest.json')
            for p in inputs:frozen[str(p.relative_to(ROOT))]=digest(p)
        if args.mode in ('full','result20'):
            smoke=output/'dispatcher-smoke'
            successful=[]
            for p in smoke.glob('*/result.json'):
                result=json.loads(p.read_text())
                if result.get('success') is True and result.get('source_unchanged') and result.get('audit') and not any(result['revision']+result['audit']):successful.append(p)
            if not successful:raise RuntimeError('full dev3 requires a completed scientific smoke; none has run')
            verify_smoke_outputs()
            prior=json.loads((smoke/'runtime-identity.json').read_text())
            compared=prior if args.mode=='full' else {k:v for k,v in prior.items() if k.startswith(('src/','scripts/','config/')) or k in ('uv.lock','pyproject.toml')}
            if any(frozen.get(k)!=v for k,v in compared.items()):
                raise RuntimeError('smoke source no longer matches current runtime')
        identity=owner/'runtime-identity.json'
        if identity.exists():
            if json.loads(identity.read_text())!=frozen:raise RuntimeError('resume source/config identity changed; use a new run namespace')
        else:identity.write_text(json.dumps(frozen,indent=2)+'\n')
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
        receipt=owner/f'{os.environ["SLURM_JOB_ID"]}-{stamp}';receipt.mkdir()
        metadata=dict(job_id=os.environ['SLURM_JOB_ID'],hostname=socket.gethostname(),started_at=stamp,
            source_hashes=frozen,git_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),
            shared_mount=shared_mount,argv=sys.argv,python=sys.executable,policy=settings,workers=workers,audit_workers=audits,
            recovery=args.recovery,resume=True,live_root=os.environ.get('BIOMNIBENCH_LIVE_ROOT'),
            resources={k:os.environ.get(k) for k in ('SLURM_JOB_PARTITION','SLURM_JOB_ACCOUNT','SLURM_CPUS_PER_TASK','SLURM_MEM_PER_NODE','SLURM_JOB_NUM_NODES')},
            resource_request=dict(partition='preempt',account=None,qos='preempt_cpu_qos',cpus=int(os.environ.get("SLURM_CPUS_PER_TASK", "4")),memory='256G',time='2-00:00:00',nodes=1,tasks=1,gpus=0),
            experiments=[dict(config=str(e.path),experiment_id=e.experiment_id,outputs=e.dag,
                paraphrase_manifest_sha256=digest(Path(e.dag['paraphrase']['output_dir'])/'manifest.json') if (Path(e.dag['paraphrase']['output_dir'])/'manifest.json').is_file() else None) for e in experiments])
        (receipt/'launch.json').write_text(json.dumps(metadata,indent=2)+'\n')
        (receipt/'working-tree.diff').write_bytes(subprocess.check_output(['git','diff']))
        stop=threading.Event();children={};guard=threading.Lock()
        def cancel(*_):stop.set()
        signal.signal(signal.SIGTERM,cancel);signal.signal(signal.SIGINT,cancel)
        monitor=Monitor(settings['coordination_dir'],receipt/'metrics.jsonl',[e.dag['revise']['output_dir'] for e in experiments])
        def execute(exp,stage,limit):
            if stop.is_set():return 143
            command=[str(Path(sys.executable).with_name('rubric-gen')),stage,'--experiment',str(exp.path),'--max-concurrency',str(limit)]
            if stage in ('revise','detect'):command.append('--resume')
            label=exp.path.stem+'-'+stage
            (receipt/(label+'-command.json')).write_text(json.dumps(command)+'\n')
            def once(attempt):
                suffix = '' if attempt == 1 else f'-attempt-{attempt}'
                with (receipt/(label+suffix+'.log')).open('x') as log:
                    child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True)
                    with guard:children[child.pid]=child
                    try:return child.wait()
                    finally:
                        with guard:children.pop(child.pid,None)
            def verify_source():
                if any(digest(ROOT/name) != value for name,value in frozen.items()):
                    raise RuntimeError('source changed before native stage resume')
            if stage == 'revise':
                return run_revision_attempts(once, study_root=exp.dag['revise']['output_dir'],
                    receipt=receipt,label=label,stop=stop,verify_source=verify_source)
            return once(1)
        def work():
            if args.mode=='result20':
                exp=experiments[0]
                with ThreadPoolExecutor(max_workers=2) as preparation:
                    prepared=list(preparation.map(lambda stage:execute(exp,stage,workers),('seed','paraphrase')))
                if any(prepared):return dict(preparation=prepared,revision=[1],audit=[])
                validate_inputs(experiments)
                inputs={}
                pool=Path(exp.dag['paraphrase']['output_dir'])
                files=[pool/'manifest.json']
                for task in exp.task_ids:
                    files.extend(p for p in (pool/'tasks'/task).glob('variant-*') if p.is_file())
                    for rep in range(1,exp.replicates+1):files.append(Path(exp.dag['seed']['output_dir'])/'tasks'/task/f'rep-{rep:03d}'/'manifest.json')
                for p in files:inputs[str(p)]=digest(p)
                input_identity=owner/'input-identity.json'
                if input_identity.exists() and json.loads(input_identity.read_text())!=inputs:raise RuntimeError('Result20 input identity changed')
                if not input_identity.exists():input_identity.write_text(json.dumps(inputs,indent=2)+'\n')
            with ThreadPoolExecutor(max_workers=len(experiments)) as pool:
                revision=list(pool.map(lambda e:execute(e,'revise',workers),experiments))
                if any(revision):return dict(revision=revision,audit=[])
                # Parallel dispatch is safe: production's shared audit lease serializes studies.
                audit=list(pool.map(lambda e:execute(e,'detect',audits),experiments))
                return dict(revision=revision,audit=audit)
        with ThreadPoolExecutor(max_workers=1) as owner_pool:
            future=owner_pool.submit(work);cancelled_at=None;next_sample=0
            while not future.done():
                try:
                    if time.monotonic()>=next_sample:
                        monitor.sample();next_sample=time.monotonic()+30
                except Exception as exc:
                    (receipt/"monitor-error.json").write_text(json.dumps(dict(error_type=type(exc).__name__)))
                    stop.set()
                if stop.is_set():
                    if cancelled_at is None:cancelled_at=time.monotonic()
                    with guard:
                        for pid in list(children):
                            try:os.killpg(pid,signal.SIGKILL if time.monotonic()-cancelled_at>120 else signal.SIGTERM)
                            except ProcessLookupError:pass
                stop.wait(5) if not stop.is_set() else time.sleep(1)
            try:result=future.result()
            except Exception as exc:
                result=dict(revision=[1],audit=[],error_type=type(exc).__name__)
        try:monitor.sample()
        except Exception as exc:
            result["monitor_error_type"]=type(exc).__name__;stop.set()
        result['source_unchanged']=all((ROOT/name).is_file() and digest(ROOT/name)==sha for name,sha in frozen.items())
        result['success']=not (stop.is_set() or not result['source_unchanged'] or any(result['revision']+result['audit']))
        (receipt/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        return int(not result['success'])


if __name__=='__main__':raise SystemExit(main())
