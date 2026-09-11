"""One complete native 18-assignment dev3 iteration; no outcome auditors."""
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from collections import Counter
from dotenv import dotenv_values
from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.study import StudyRunner, StudyRunConfig, _exclusive_study_lease
from rubric_gen.submission_revision.study_validation import validate_completed_revision
from rubric_gen.submission_revision.execution_scope import terminal_records

BUNDLE=Path(__file__).resolve().parent
ROOT=BUNDLE.parents[1]
RUN=Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910')
SUBVERSION='dev2'
ITERATION=1
TASKS=('da-3-4','da-11-1','da-18-1')


def verify_freeze():
    frozen=json.loads((BUNDLE/f'{SUBVERSION}-freeze.json').read_text())
    for name,digest in frozen['files'].items():
        if sha256_file(ROOT/name)!=digest:raise RuntimeError('immutable execution file changed: '+name)
    if subprocess.check_output(['git','status','--porcelain','--',*frozen['files']],cwd=ROOT,text=True).strip():
        raise RuntimeError('execution files are not cleanly committed')
    return frozen,subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip()


def prepare_runner(runner):
    """Use native manifest initialization before native g1 preparation, under its lease."""
    existed = runner.root.exists()
    runner.root.mkdir(parents=True, exist_ok=True)
    with _exclusive_study_lease(runner.root):
        runner._start_manifest(sorted(runner.experiment.assignments, key=lambda a: a.execution_order), existed)
        runner._prepare_pretreatment_rubric(runner.experiment.task_ids[0])


def main():
    if not os.environ.get('SLURM_JOB_ID') or int(os.environ.get('SLURM_CPUS_PER_TASK','0'))!=32:
        raise RuntimeError('dev3 requires a 32-CPU Slurm allocation')
    frozen,commit=verify_freeze()
    phase_path=RUN/'phase-a'/f'{SUBVERSION}-001/result.json'
    phase=json.loads(phase_path.read_text())
    if not phase['gate_passed'] or phase['method']!='attack_defense_v2.'+SUBVERSION:
        raise RuntimeError('the current recipe has not passed Phase A')
    runtime=policy()
    if runtime['aggregate_concurrency']!=60 or runtime['audit_studies']!=1:
        raise RuntimeError('shared capacity policy differs')
    key=dotenv_values('/home/aydanh/repos/rubric_gen/.env.local').get('OPENAI_API_KEY')
    if not key:raise RuntimeError('configured OpenAI credential absent')
    os.environ['OPENAI_API_KEY']=key
    cohort=RUN/'dev3'/SUBVERSION
    owner=cohort/'owners'/os.environ['SLURM_JOB_ID'];owner.mkdir(parents=True,exist_ok=True)
    experiments=[load_experiment(BUNDLE/SUBVERSION/(task+'.yaml')) for task in TASKS]
    expected={(t,r,c) for t in TASKS for r in range(1,4) for c in ['full-red-team-trace','user-simulator-red-team-trace']}
    actual={(a.task_id,a.replicate,a.condition_id) for e in experiments for a in e.execution_assignments}
    if actual!=expected or sum(len(e.execution_assignments) for e in experiments)!=18:
        raise RuntimeError('dev3 cohort differs from the complete canonical 18')
    for e in experiments:
        if e.payload['randomization']!={'seed':20260806,'replicates':3} or e.protocol['max_revisions']!=10 or e.protocol['min_revisions']!=5:
            raise RuntimeError('dev3 randomization/revision boundary changed')
    write_json_atomic(owner/'launch.json',{'method':'attack_defense_v2.'+SUBVERSION,'full_dev3_iteration':ITERATION,
        'commit':commit,'job':os.environ['SLURM_JOB_ID'],'host':socket.gethostname(),'runtime':runtime,
        'allocated_cpus':32,'assignment_workers_maximum':18,'workers_per_native_task_study':6,'learning_fanout':4,
        'phase_a_receipt':str(phase_path),'phase_a_sha256':sha256_file(phase_path),'python':sys.executable,
        'time':datetime.now(timezone.utc).isoformat(),'config_sha256s':{str(e.path):sha256_file(e.path) for e in experiments},
        'expected_assignments':18,'outcome_audits':False,'frozen_files':frozen['files']})
    runners=[StudyRunner(StudyRunConfig(e,Path(e.dag['seed']['output_dir']),Path(e.dag['paraphrase']['output_dir']),
        Path(e.dag['revise']['output_dir']),6,resume=Path(e.dag['revise']['output_dir']).exists())) for e in experiments]
    # Native preparation creates only missing dev3 g1. All tasks finish this barrier before any solver revision.
    with ThreadPoolExecutor(max_workers=3) as pool:
        list(pool.map(prepare_runner,runners))
    g1=[]
    for runner in runners:
        for p in runner.pretreatment_root.glob('**/generation-0001/manifest.json'):
            d=json.loads(p.read_text())
            g1.append({'task':runner.experiment.task_ids[0],'manifest':str(p),'manifest_sha256':sha256_file(p),
                       'generation_sha256':d['generation_sha256'],'files':{str(x.relative_to(p.parent)):sha256_file(x) for x in p.parent.rglob('*') if x.is_file()}})
    if len(g1)!=3:raise RuntimeError('dev3 requires exactly three frozen g1 inputs')
    g1_path=cohort/'frozen-g1.json'
    if g1_path.exists() and json.loads(g1_path.read_text())!=g1:raise RuntimeError('dev3 g1 changed')
    write_json_atomic(g1_path,g1)
    print(json.dumps({'stage':'g1_frozen','count':3,'generation_hashes':[r['generation_sha256'] for r in g1]}),flush=True)
    # _prepare above owns the initial study directory; native resume validates it.
    runners=[StudyRunner(StudyRunConfig(r.experiment,r.seed_root,r.paraphrase_root,r.root,6,resume=True)) for r in runners]
    stop=threading.Event()
    def monitor():
        while not stop.is_set():
            rows=[]
            for runner in runners:
                try:rows.extend(json.loads((runner.root/'study.json').read_text())['records'])
                except (OSError,ValueError,KeyError):pass
            write_json_atomic(BUNDLE/f'{SUBVERSION}-status.json',{'job':os.environ['SLURM_JOB_ID'],'expected':18,
                'statuses':dict(Counter(r['status'] for r in rows)),'time':datetime.now(timezone.utc).isoformat()})
            stop.wait(30)
    threading.Thread(target=monitor,daemon=True).start()
    start=time.monotonic()
    try:
        with ThreadPoolExecutor(max_workers=3) as pool:exits=list(pool.map(lambda r:r.run(),runners))
    finally:stop.set()
    write_json_atomic(owner/'revision-exits.json',{'exits':exits,'wall_seconds':time.monotonic()-start})
    if any(exits):raise RuntimeError('dev3 has incomplete assignments; compatible successes and failures retained')
    rows=[]
    for runner in runners:
        ledger=json.loads((runner.root/'study.json').read_text())
        completed=terminal_records(runner.experiment,ledger)
        if len(completed)!=6 or any(r['status']!='completed' for r in completed):raise RuntimeError('native task-study coverage incomplete')
        assignments={a.assignment_id:a for a in runner.experiment.execution_assignments}
        for record in completed:
            path=runner.root/record['experiment_dir']
            validate_completed_revision(path,assignments[record['assignment_id']],runner.experiment,runner.seed_root,runner.paraphrase_root)
            rows.append({'assignment_id':record['assignment_id'],'root':str(path),'experiment_id':runner.experiment.experiment_id})
    verify_freeze()
    write_json_atomic(cohort/'completion.json',{'method':'attack_defense_v2.'+SUBVERSION,'iteration':ITERATION,'commit':commit,
        'job':os.environ['SLURM_JOB_ID'],'completed':len(rows),'expected':18,'assignments':rows,'audits_launched':0})
    print(json.dumps({'stage':'dev3_complete','assignments':len(rows),'outcome_audits':0}),flush=True)


if __name__=='__main__':main()
