"""Private dispatcher for native Result20 recovery after terminal prior ownership."""
import argparse
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

ROOT=Path(__file__).resolve().parents[2]  # Separate immutable launch bundle; producing scientific checkout stays unchanged.
from rubric_gen.runtime.paths import PROJECT_ROOT as CODE_ROOT
sys.path.insert(0,str(CODE_ROOT/'scripts/babel'))
import launch as launcher_helpers
# Imported helpers are frozen locally; smoke artifacts belong to the main run store.
launcher_helpers.ROOT=ROOT
from launch import check_shared_mount, verify_smoke_outputs
from monitor import Monitor
from dotenv import dotenv_values
from rubric_gen.runtime.paths import PROJECT_ROOT as CODE_ROOT
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run
from rubric_gen.submission_revision.seeds import resolve_seed
from rubric_gen.submission_revision.judging.executor import JudgeExecutor
from rubric_gen.submission_revision.study import _exclusive_study_lease


def digest(p):
    with Path(p).open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()


def smoke_gate():
    # Explicit runtime-only upgrade; never rewrite old producer identities.
    original=ROOT/'runs/babel-code/result20-current'
    expected="a536df32734f1749579846d226a3e382de2d4316c5f367e524f5ada49d0abf4b"
    if digest(CODE_ROOT/'src/rubric_gen/runtime/capacity.py')!=expected:raise RuntimeError('unvalidated observer fix')
    proxy='src/rubric_gen/runtime/agents/codex_app_server.py'
    expected_proxy='4c9f30aa278ab8e3d6717ccf97e573436332d2ed4fb6b7c02134e6d3a0f51b01'
    if digest(CODE_ROOT/proxy)!=expected_proxy:raise RuntimeError('unvalidated local-temp runtime')
    receipt=json.loads((ROOT/'runs/babel-result20-current-20260908/proxy-local-smoke-10357429/result.json').read_text())
    if receipt.get('success') is not True or receipt['proxy_sha256']!=expected_proxy:raise RuntimeError('proxy smoke failed')
    fixes={'src/rubric_gen/submission_revision/controller.py': 'b954c36c358a2aca37583880e67be1aad444d640833b15dfbe4f846caf94e3f7', 'src/rubric_gen/submission_revision/controller_recovery.py': 'aa0059b6998b0c0bf93d3ff37b80fd1bf55a7f5dd5c2fa1099fc76ce573e014f'}
    for rel, sha in fixes.items():
        if digest(CODE_ROOT/rel)!=sha:raise RuntimeError('unvalidated checkpoint recovery source: '+rel)
    evidence=json.loads(Path(__file__).with_name('regression.json').read_text())
    if evidence.get('passed')!=84 or evidence.get('source_hashes')!=fixes:raise RuntimeError('checkpoint regression evidence mismatch')
    for path in (original/'src').rglob('*.py'):
        rel=path.relative_to(original)
        if str(rel) in ('src/rubric_gen/runtime/capacity.py',proxy) or str(rel) in fixes:continue
        if digest(path)!=digest(CODE_ROOT/rel):raise RuntimeError(f'scientific source changed: {rel}')
    for rel in ('uv.lock','pyproject.toml','config/runtime.json'):
        if digest(original/rel)!=digest(CODE_ROOT/rel):raise RuntimeError('environment or global policy changed')
    acceptance=ROOT/'runs/babel-result20-current-20260908/checkpoint-validation-10357741/result.json'
    if digest(acceptance)!='124244d90566352b780e419a8cd60c95625df07c7bb6e1c33a4a35f5e84d8a9a':raise RuntimeError('checkpoint acceptance changed')
    actual=json.loads(acceptance.read_text())
    if actual.get('success') is not True or len(actual.get('actual_receipts_verified',[]))!=13:raise RuntimeError('checkpoint acceptance incomplete')
    verify_smoke_outputs()


def config_for(mode,task):
    if CODE_ROOT.resolve()!=(ROOT/'runs/babel-code/result20-checkpoint-recovery').resolve():raise RuntimeError('wrong recovery checkout')
    paths={mode:ROOT/f'runs/babel-code/result20-current/experiments/babel/biomnibench-result20-current-{mode}.yaml' for mode in ('full-static','user-static')}
    paths.update({'user-trace':ROOT/'runs/babel-code/result20-current/experiments/babel/biomnibench-result20-current-user-trace.yaml','full-trace':ROOT/'investigation/result20-full-trace-20260908/experiment.yaml'})
    return load_experiment(paths[mode])


OLD_JOBS={'full-static':'10357585','user-static':'10357642','user-trace':'10357630','full-trace':'10357852'}


def old_owner_gate(mode):
    job=OLD_JOBS[mode]
    active=subprocess.check_output(['squeue','--noheader','--user','aydanh','--format=%i'],text=True).splitlines()
    if job in {item.strip() for item in active}:raise RuntimeError('prior scientific owner still present: '+job)
    accounting=subprocess.check_output(['sacct','-n','-P','-j',job,'--format=JobIDRaw,State,ExitCode'],text=True)
    rows=[row.split('|') for row in accounting.splitlines() if row.split('|')[0]==job]
    if len(rows)!=1 or rows[0][1].split()[0] not in {'CANCELLED','TIMEOUT','FAILED','COMPLETED','OUT_OF_MEMORY','NODE_FAIL','PREEMPTED'}:raise RuntimeError('prior job terminal state not established')
    suffix='-checkpoint-recovery' if mode=='full-trace' else '-local-temp-recovery'
    owner=ROOT/f'runs/babel-overnight-20260907/dispatcher-{mode}-result20{suffix}'
    receipts=[p for p in owner.glob('*/launch.json') if json.loads(p.read_text())['job_id']==job]
    if len(receipts)!=1:raise RuntimeError('ambiguous prior ownership')
    launch=json.loads(receipts[0].read_text())
    result_path=receipts[0].parent/'result.json'
    result=json.loads(result_path.read_text()) if result_path.exists() else None
    if result is not None and result.get('source_unchanged') is False:raise RuntimeError('prior source seal failed')
    if any(digest(Path(name))!=sha for name,sha in launch['source_hashes'].items()):raise RuntimeError('prior source files changed')
    return {'job_id':job,'receipt':str(receipts[0]),'result':result,'completion_receipt_missing':result is None,'slurm_terminal_record':rows[0],'source_commit':launch['git_commit'],'current_source_hashes_match':True}


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=list(OLD_JOBS))
    p.add_argument('--workers',type=int,default=60)
    p.add_argument('--audit-workers',type=int,default=60)
    p.add_argument('--recovery',action='store_true')
    a=p.parse_args()
    a.task="result20"
    if not all(1<=n<=60 for n in (a.workers,a.audit_workers)):p.error('workers must be1–60')
    if not os.environ.get('SLURM_JOB_ID'):raise RuntimeError('Slurm allocation required')
    prior=old_owner_gate(a.mode);mount=check_shared_mount();smoke_gate();exp=config_for(a.mode,a.task)
    validate_paraphrase_run(Path(exp.dag['paraphrase']['output_dir']),exp)
    for task in exp.task_ids:
      for rep in range(1,exp.replicates+1):
        seed=resolve_seed(Path(exp.dag['seed']['output_dir']),exp.task_dir(task),rep,seed_generator=exp.seed_agent_config(),prompt_profile=exp.protocol['prompt'],benchmark=exp.benchmark)
        if seed.manifest['scoring_identity']['scoring_implementation_sha256']!=JudgeExecutor.scoring_implementation_sha256(exp.benchmark):raise RuntimeError('seed scoring implementation changed')
    credentials=dotenv_values(ROOT/'.env.local')
    for key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY'):
        if not credentials.get(key):raise RuntimeError(f'missing {key}')
        os.environ[key]=credentials[key]
    owner=ROOT/f'runs/babel-overnight-20260907/dispatcher-{a.mode}-{a.task}-checkpoint-retry';owner.mkdir(parents=True,exist_ok=True)
    workers,audits=(2,2) if a.recovery else (a.workers,a.audit_workers)
    with _exclusive_study_lease(owner):
        inputs=[*CODE_ROOT.joinpath('src').rglob('*.py'),CODE_ROOT/'config/runtime.json',CODE_ROOT/'uv.lock',CODE_ROOT/'pyproject.toml',exp.path,Path(__file__),Path(__file__).with_name('condition.sbatch'),Path(__file__).with_name('regression.json'),CODE_ROOT/'scripts/babel/monitor.py',CODE_ROOT/'scripts/babel/launch.py',CODE_ROOT/'scripts/diagnostics/check_audit_coverage.py',CODE_ROOT/'scripts/diagnostics/artifact_locations.py']
        pool=Path(exp.dag['paraphrase']['output_dir']);inputs.append(pool/'manifest.json')
        inputs.extend(x for task in exp.task_ids for x in (pool/'tasks'/task).glob('variant-*') if x.is_file())
        inputs.extend(Path(exp.dag['seed']['output_dir'])/'tasks'/task/f'rep-{rep:03d}/manifest.json' for task in exp.task_ids for rep in range(1,exp.replicates+1))
        frozen={str(x.resolve()):digest(x) for x in inputs}
        identity=owner/'runtime-identity.json'
        if identity.exists() and json.loads(identity.read_text())!=frozen:raise RuntimeError('condition source/config identity changed; use a new namespace')
        if not identity.exists():identity.write_text(json.dumps(frozen,indent=2)+'\n')
        stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ');receipt=owner/f'{os.environ["SLURM_JOB_ID"]}-{stamp}';receipt.mkdir()
        metadata=dict(job_id=os.environ['SLURM_JOB_ID'],hostname=socket.gethostname(),started_at=stamp,checkout=str(CODE_ROOT),
            git_commit=subprocess.check_output(['git','-C',str(CODE_ROOT),'rev-parse','HEAD'],text=True).strip(),
            dispatcher_commit=subprocess.check_output(['git','-C',str(ROOT),'rev-parse','HEAD'],text=True).strip(),
            shared_helper_commit=subprocess.check_output(['git','-C',str(CODE_ROOT),'rev-parse','HEAD'],text=True).strip(),
            prior_owner=prior,recovery_reason='Prior owner terminal; verified interrupted-model and derived submission-count recovery fixes; unchanged science',config=str(exp.path),experiment_id=exp.experiment_id,outputs=exp.dag,argv=sys.argv,python=sys.executable,source_hashes=frozen,
            policy=policy(),workers=workers,audit_workers=audits,resume=True,recovery=a.recovery,mount=mount,live_root=os.environ.get('BIOMNIBENCH_LIVE_ROOT'),
            resource_request=dict(account=None,partition='preempt',qos='preempt_cpu_qos',cpus=int(os.environ["SLURM_CPUS_PER_TASK"]),memory=f"{os.environ['SLURM_MEM_PER_NODE']}M",nodes=1,tasks=1,gpus=0,time='2-00:00:00'),
            allocated={k:os.environ.get(k) for k in ('SLURM_JOB_PARTITION','SLURM_CPUS_PER_TASK','SLURM_MEM_PER_NODE','SLURM_JOB_NUM_NODES')})
        (receipt/'launch.json').write_text(json.dumps(metadata,indent=2)+'\n')
        (receipt/'working-tree.diff').write_bytes(subprocess.check_output(['git','-C',str(CODE_ROOT),'diff']))
        monitor=Monitor(policy()['coordination_dir'],receipt/'metrics.jsonl',[exp.dag['revise']['output_dir']])
        stop=threading.Event();signal.signal(signal.SIGTERM,lambda *_:stop.set());signal.signal(signal.SIGINT,lambda *_:stop.set())
        exits=[]
        for stage,limit in [('revise',workers),('detect',audits)]:
            if stop.is_set():break
            command=[str(Path(sys.executable).with_name('rubric-gen')),stage,'--experiment',str(exp.path),'--max-concurrency',str(limit),'--resume']
            (receipt/f'{stage}-command.json').write_text(json.dumps(command)+'\n')
            with (receipt/f'{stage}.log').open('w') as log:
                child=subprocess.Popen(command,stdout=log,stderr=subprocess.STDOUT,start_new_session=True,cwd=CODE_ROOT)
                stopped=None;next_sample=0
                try:
                    while child.poll() is None:
                        if time.monotonic()>=next_sample:monitor.sample();next_sample=time.monotonic()+30
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
                exits.append(child.wait())
            if exits[-1]:break
        monitor.sample();unchanged=all(Path(name).is_file() and digest(name)==sha for name,sha in frozen.items())
        result=dict(exits=exits,source_unchanged=unchanged,success=exits==[0,0] and unchanged and not stop.is_set())
        (receipt/'result.json').write_text(json.dumps(result,indent=2)+'\n')
        return int(not result['success'])

if __name__=='__main__':raise SystemExit(main())
