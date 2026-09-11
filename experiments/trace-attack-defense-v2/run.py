"""Execute exactly one committed attack_defense_v2 cohort and its frozen audit panel."""
import argparse
import importlib.util
import json
import os
import socket
import subprocess
import sys
import threading
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from dotenv import dotenv_values
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.study import StudyRunConfig, StudyRunner
from rubric_gen.submission_revision.study_validation import validate_completed_revision
from rubric_gen.submission_revision.execution_scope import terminal_records
from prepare import BUNDLE,ROOT,RUN,sha

PANEL=('gpt-5.6-sol','claude-opus-5')

def check_shared_mount():
    target=Path(policy()['coordination_dir'])
    while not target.exists():target=target.parent
    fields=subprocess.check_output(['findmnt','--noheadings','--output','FSTYPE,OPTIONS','--target',str(target)],text=True).strip().split(None,1)
    if len(fields)!=2 or fields[0] not in ('nfs','nfs4') or 'local_lock=none' not in fields[1].split(',') or 'nolock' in fields[1].split(','):
        raise RuntimeError('Babel admission requires shared NFS server locking (local_lock=none)')
    return {'filesystem':fields[0],'server_locking':True}

def start_progress_receipt(exp,owner):
    """Expose only compact saved-state counts to the login node; no provider work."""
    expected={a.assignment_id for a in exp.execution_assignments}
    def monitor():
        while True:
            try:
                ledger=json.loads((Path(exp.dag['revise']['output_dir'])/'study.json').read_text())
                rows=[r for r in ledger['records'] if r['assignment_id'] in expected]
                result={'job':os.environ['SLURM_JOB_ID'],'owner':str(owner),'time':datetime.now(timezone.utc).isoformat(),
                        'expected':len(expected),'statuses':dict(Counter(r['status'] for r in rows))}
                write_json_atomic(BUNDLE/'status.json',result)
            except (OSError,ValueError,KeyError):
                pass  # An incomplete observation is not an experiment failure.
            time.sleep(30)
    threading.Thread(target=monitor,name='saved-state-progress',daemon=True).start()

def verify_freeze():
    frozen=json.loads((BUNDLE/'execution-freeze.json').read_text())
    for name,digest in frozen['files'].items():
        if sha(ROOT/name)!=digest:
            raise RuntimeError('immutable execution source/config changed: '+name)
    commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()
    # The snapshot commits the freeze receipt itself; all registered execution files must also be clean.
    dirty=subprocess.check_output(['git','status','--porcelain','--',*frozen['files']],cwd=ROOT,text=True)
    if dirty.strip():raise RuntimeError('execution files are not committed cleanly')
    return frozen,commit

def smoke_assignments(exp):
    selected=tuple(a.assignment_id for a in exp.execution_assignments if a.task_id=='da-10-1' and a.replicate==1)
    if len(selected)!=2:raise RuntimeError('counted smoke identity is incomplete')
    return selected

def smoke_integrity(exp,study,ids):
    ledger=json.loads((study/'study.json').read_text())
    by_id={r['assignment_id']:r for r in ledger['records']}
    rows=[]
    for a in exp.execution_assignments:
        if a.assignment_id not in ids:continue
        r=by_id[a.assignment_id]
        if r['status']!='completed':raise RuntimeError('counted smoke is not complete: '+a.assignment_id)
        root=study/r['experiment_dir']
        validate_completed_revision(root,a,exp,Path(exp.dag['seed']['output_dir']),Path(exp.dag['paraphrase']['output_dir']))
        binding=json.loads((root/'submission-rubric-bindings/s000.json').read_text())
        if binding['active_generation_round']!=2 or binding['source_checkpoint']!=0 or binding['solver_turn']!=1:
            raise RuntimeError('first-defense schedule is incorrect')
        rows.append({'assignment_id':a.assignment_id,'experiment_dir':str(root),'s000_binding_sha256':binding['binding_sha256']})
    result={'passed':True,'execution_only':True,'assignments':rows,'no_endpoint_selection':True,'experiment_id':exp.experiment_id}
    write_json_atomic(RUN/'smoke-integrity.json',result)
    return result

def install_reuse():
    spec=importlib.util.spec_from_file_location('attack_defense_exact_reuse',BUNDLE/'audit_reuse.py')
    reuse=importlib.util.module_from_spec(spec);spec.loader.exec_module(reuse)
    baseline=json.loads((ROOT/'docs/reports/2026-09-09/baseline-freeze/results.json').read_text())
    sources=set()
    for path,digest in baseline['provenance']['sources'].items():
        if sha(path)!=digest:raise RuntimeError('frozen comparison report changed: '+path)
        for row in json.loads(Path(path).read_text())['rows']:
            sources.add(Path(row['quality_path']).parents[2])
    # V2 static H records have their own native keys and public-byte provenance.
    v2=Path('/data/user_data/aydanh/rubric_gen/runs/result20-prompt-nofallback-v2-20260910')
    sources.update([v2/'full-static',v2/'user-simulator-static'])
    reuse.SOURCES=sorted(sources);reuse.install()
    return [str(p) for p in sorted(sources)]

def run_audit(exp,owner):
    from rubric_gen.submission_revision.commands import run_detect
    reused=install_reuse();write_json_atomic(owner/'audit-reuse-sources.json',{'sources':reused,'rule':'exact native semantic keys and validation only'})
    args=SimpleNamespace(experiment=str(exp.path),study_dir=None,max_concurrency=32,resume=True)
    for attempt in range(1,4):
        verify_freeze()
        print(json.dumps({'stage':'audit','attempt':attempt,'time':datetime.now(timezone.utc).isoformat()}),flush=True)
        try:code=run_detect(args)
        except Exception as exc:
            write_json_atomic(owner/f'audit-failure-{attempt}.json',{'type':type(exc).__name__,'message':str(exc)})
            # Structural/provenance exceptions never authorize fresh scientific calls.
            raise
        write_json_atomic(owner/f'audit-attempt-{attempt}.json',{'exit_code':code})
        if code==0:return
        # Native completed request validation and resume preserve successes. No revision stage is called here.
        if attempt==3:raise RuntimeError('authoritative audits incomplete after bounded audit-only recovery')
    raise AssertionError('unreachable')

def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('mode',choices=['execute','audit']);args=parser.parse_args()
    if not os.environ.get('SLURM_JOB_ID') or int(os.environ.get('SLURM_CPUS_PER_TASK','0'))!=32:
        raise RuntimeError('production requires one 32-CPU Slurm allocation')
    frozen,commit=verify_freeze()
    exp=load_experiment(BUNDLE/'result20.yaml')
    if len(exp.execution_assignments)!=120 or tuple(exp.outcome_audit['models'])!=PANEL:
        raise RuntimeError('production population/panel differs from the approved recipe')
    runtime=policy()
    if runtime['aggregate_concurrency']!=60 or runtime['audit_studies']!=1:
        raise RuntimeError('shared capacity settings changed')
    shared_mount=check_shared_mount()
    credentials=dotenv_values('/home/aydanh/repos/rubric_gen/.env.local')
    for key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY'):
        if not credentials.get(key):raise RuntimeError('configured credential unavailable: '+key)
        os.environ[key]=str(credentials[key])
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    owner=RUN/'owners'/f'{os.environ["SLURM_JOB_ID"]}-{stamp}';owner.mkdir(parents=True)
    write_json_atomic(owner/'launch.json',{'commit':commit,'freeze_sha256':sha(BUNDLE/'execution-freeze.json'),
        'job':os.environ['SLURM_JOB_ID'],'host':socket.gethostname(),'time':stamp,'mode':args.mode,
        'experiment_id':exp.experiment_id,'config_sha256':sha(exp.path),'resources':runtime,
        'cpus':32,'assignment_workers':32,'learning_workers_per_assignment':4,'shared_mount':shared_mount,
        'python':sys.executable,'outputs':exp.dag,'command':sys.argv})
    study=Path(exp.dag['revise']['output_dir']);seed=Path(exp.dag['seed']['output_dir']);paraphrase=Path(exp.dag['paraphrase']['output_dir'])
    start_progress_receipt(exp,owner)
    if args.mode=='execute':
        ids=smoke_assignments(exp)
        if not (RUN/'smoke-integrity.json').is_file():
            print(json.dumps({'stage':'counted_smoke','assignments':ids}),flush=True)
            code=StudyRunner(StudyRunConfig(exp,seed,paraphrase,study,32,resume=study.exists(),assignment_ids=ids)).run()
            if code:raise RuntimeError('counted smoke has execution failures; results retained')
        smoke_integrity(exp,study,ids)
        verify_freeze()
        print(json.dumps({'stage':'complete_120','reuse_smoke':True}),flush=True)
        code=StudyRunner(StudyRunConfig(exp,seed,paraphrase,study,32,resume=True)).run()
        if code:raise RuntimeError('trace cohort has execution failures; successful assignments retained')
    ledger=json.loads((study/'study.json').read_text())
    rows=terminal_records(exp,ledger)
    if len(rows)!=120 or any(r['status']!='completed' for r in rows):
        raise RuntimeError('auditing requires the complete 120-assignment cohort')
    run_audit(exp,owner)
    sys.path.insert(0,str(ROOT/'scripts/diagnostics'))
    from check_audit_coverage import check
    coverage=check(study,Path(exp.dag['detect']['output_dir']),expected_models=PANEL)
    if coverage['assignment_count']!=120:raise RuntimeError('cohort audit coverage mismatch')
    verify_freeze()
    write_json_atomic(owner/'coverage.json',coverage)
    write_json_atomic(RUN/'completion.json',{'success':True,'commit':commit,'owner':str(owner),'coverage':coverage,'experiment_id':exp.experiment_id})
    print(json.dumps({'stage':'complete','coverage':coverage}),flush=True)

if __name__=='__main__':main()
