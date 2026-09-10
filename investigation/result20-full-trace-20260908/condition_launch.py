"""Private dispatcher for the authorized added Result20 full-feedback trace condition."""
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
    root=ROOT/'runs/babel-dev3-20260907/dispatcher-smoke'
    if not any(json.loads(p.read_text()).get('success') is True for p in root.glob('*/result.json')):
        raise RuntimeError('A successful real Babel control smoke is required first')
    verify_smoke_outputs()
    prior=json.loads((root/'runtime-identity.json').read_text())
    # Policy changes are separately identified; shared provider/solver runtime must
    # remain exactly the implementation accepted by the control smoke.
    for name,sha in prior.items():
        if name.startswith('src/rubric_gen/runtime/') or name in ('uv.lock','pyproject.toml','config/runtime.json'):
            if digest(CODE_ROOT/name)!=sha:raise RuntimeError('shared runtime changed since smoke')


def config_for(mode,task):
    profiles={'full-trace':(ROOT/'runs/babel-code/result20-current','full-trace')}
    code,stem=profiles[mode]
    if CODE_ROOT.resolve()!=code.resolve():raise RuntimeError('wrong checkout/PYTHONPATH for condition')
    return load_experiment(Path(__file__).with_name('experiment.yaml'))


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('mode',choices=['full-trace'])
    p.add_argument('--workers',type=int,default=60)
    p.add_argument('--audit-workers',type=int,default=60)
    p.add_argument('--recovery',action='store_true')
    a=p.parse_args()
    a.task="result20"
    if not all(1<=n<=60 for n in (a.workers,a.audit_workers)):p.error('workers must be1–60')
    if not os.environ.get('SLURM_JOB_ID'):raise RuntimeError('Slurm allocation required')
    mount=check_shared_mount();smoke_gate();exp=config_for(a.mode,a.task)
    validate_paraphrase_run(Path(exp.dag['paraphrase']['output_dir']),exp)
    for task in exp.task_ids:
      for rep in range(1,exp.replicates+1):
        seed=resolve_seed(Path(exp.dag['seed']['output_dir']),exp.task_dir(task),rep,seed_generator=exp.seed_agent_config(),prompt_profile=exp.protocol['prompt'],benchmark=exp.benchmark)
        if seed.manifest['scoring_identity']['scoring_implementation_sha256']!=JudgeExecutor.scoring_implementation_sha256(exp.benchmark):raise RuntimeError('seed scoring implementation changed')
    credentials=dotenv_values(ROOT/'.env.local')
    for key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY'):
        if not credentials.get(key):raise RuntimeError(f'missing {key}')
        os.environ[key]=credentials[key]
    owner=ROOT/f'runs/babel-overnight-20260907/dispatcher-{a.mode}-{a.task}';owner.mkdir(parents=True,exist_ok=True)
    workers,audits=(2,2) if a.recovery else (a.workers,a.audit_workers)
    with _exclusive_study_lease(owner):
        inputs=[*CODE_ROOT.joinpath('src').rglob('*.py'),CODE_ROOT/'config/runtime.json',CODE_ROOT/'uv.lock',CODE_ROOT/'pyproject.toml',exp.path,Path(__file__),Path(__file__).with_name('condition.sbatch'),CODE_ROOT/'scripts/babel/monitor.py',CODE_ROOT/'scripts/babel/launch.py',CODE_ROOT/'scripts/diagnostics/check_audit_coverage.py',CODE_ROOT/'scripts/diagnostics/artifact_locations.py']
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
            config=str(exp.path),experiment_id=exp.experiment_id,outputs=exp.dag,argv=sys.argv,python=sys.executable,source_hashes=frozen,
            policy=policy(),workers=workers,audit_workers=audits,resume=True,recovery=a.recovery,mount=mount,live_root=os.environ.get('BIOMNIBENCH_LIVE_ROOT'),
            resource_request=dict(account=None,partition='preempt',qos='preempt_cpu_qos',cpus=int(os.environ["SLURM_CPUS_PER_TASK"]),memory='256G',nodes=1,tasks=1,gpus=0,time='2-00:00:00'),
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
