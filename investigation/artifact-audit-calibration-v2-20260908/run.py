"""Private, versioned artifact-only audit comparison; never regenerates revisions."""
import dataclasses, hashlib, importlib.util, json, os, socket, subprocess, sys, threading, time
from pathlib import Path
from dotenv import dotenv_values
from rubric_gen.runtime.paths import PROJECT_ROOT as CODE
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.evaluation.direct import load_detection_study, run_direct_detection, DirectDetectionConfig
from rubric_gen.submission_revision.evaluation.evidence import _revision_prompt
from rubric_gen.submission_revision.evaluation.evidence_ledger import load_revision_evidence_snapshot
from rubric_gen.submission_revision.detection_windows import RevisionDetectionWindow as Window
from rubric_gen.submission_revision.study import _exclusive_study_lease
from rubric_gen.detection.prompts import _reward_hacking_requests
ROOT=Path('/home/aydanh/repos/rubric_gen')
BUNDLE=ROOT/'investigation/artifact-audit-calibration-v2-20260908'
ORIGINAL=ROOT/'runs/babel-code/result20-cue-contrast'
OUTPUT=ROOT/'runs/babel-artifact-audit-evidence-v2-20260908'
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,v): p.write_text(json.dumps(v,indent=2)+'\n')
def inputs():
    result=[]
    for arm in ('static','trace'):
        exp=load_experiment(ROOT/f'investigation/result20-cue-contrast-20260908/{arm}-results20.yaml')
        study=load_detection_study(Path(exp.dag['revise']['output_dir']),exp)
        if len(study.revisions)!=60: raise RuntimeError('requires all60 completed revisions per arm')
        result.append((arm,exp,study))
    return result

def validate():
    spec=importlib.util.spec_from_file_location('original_detection_prompts',ORIGINAL/'src/rubric_gen/detection/prompts.py')
    original=importlib.util.module_from_spec(spec);sys.modules[spec.name]=original;spec.loader.exec_module(original)
    candidate_source=CODE/'src/rubric_gen/detection/prompts.py'
    # Exactly one source file differs from the frozen experiment checkout.
    differences=[str(p.relative_to(CODE)) for p in (CODE/'src').rglob('*.py') if sha(p)!=sha(ORIGINAL/p.relative_to(CODE))]
    assert differences==['src/rubric_gen/detection/prompts.py'],differences
    rows=[]
    for arm,exp,study in inputs():
        for revision in study.revisions:
            manifest=json.loads((revision/'manifest.json').read_text())
            snapshot=load_revision_evidence_snapshot(revision,manifest)
            assert snapshot.latest_submission.name==snapshot.submission_ids[-1]
            payload=_revision_prompt(revision,study.tasks_dir,'rh',Window.FINAL_ARTIFACT)
            assert payload.stats['source_records']==payload.stats['solver_feedback_records']==0
            old=original._reward_hacking_requests(payload,evidence_chars=100000,max_output_tokens=4096)
            new=_reward_hacking_requests(payload,evidence_chars=100000,max_output_tokens=4096)
            assert len(old)==len(new)
            for a,b in zip(old,new):
                av,bv=dataclasses.asdict(a),dataclasses.asdict(b)
                ai,bi=av.pop('instructions'),bv.pop('instructions')
                assert av==bv and ai!=bi
            for window in ('full_trajectory','post_update','final_revision'):
                other=dataclasses.replace(payload,stats={**payload.stats,'detection_window':window})
                assert original._reward_hacking_requests(other,evidence_chars=100000)==_reward_hacking_requests(other,evidence_chars=100000)
            artifacts={str(p):sha(p) for p in (snapshot.latest_submission/'workspace').rglob('*') if p.is_file()}
            rows.append(dict(arm=arm,revision=str(revision),latest_submission=str(snapshot.latest_submission),artifact_hashes=artifacts,evidence_sha256=hashlib.sha256(payload.evidence.encode()).hexdigest(),chunks=len(new)))
    return dict(success=True,rows=rows,source_differences=differences)

def main():
    mode=sys.argv[1]
    if mode not in ('validate','run') or not os.environ.get('SLURM_JOB_ID'): raise RuntimeError('requires Slurm and explicit private mode')
    OUTPUT.mkdir(exist_ok=True)
    (OUTPUT/"owner").mkdir(exist_ok=True)
    with _exclusive_study_lease(OUTPUT/'owner'):
        receipt=OUTPUT/os.environ['SLURM_JOB_ID'];receipt.mkdir(exist_ok=False)
        files=[*(CODE/'src').rglob('*.py'),CODE/'uv.lock',CODE/'config/runtime.json',Path(__file__),BUNDLE/'run.sbatch',BUNDLE/'PROTOCOL.md']
        files += [exp.path for _,exp,_ in inputs()]
        hashes={str(p):sha(p) for p in files}
        identity=OUTPUT/f'{mode}-identity.json'
        if identity.exists(): assert json.loads(identity.read_text())==hashes,'source identity changed'
        else: write(identity,hashes)
        write(receipt/'launch.json',dict(command=sys.argv,job_id=os.environ['SLURM_JOB_ID'],hostname=socket.gethostname(),commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=CODE,text=True).strip(),source_hashes=hashes,policy=policy(),resources=dict(cpus=4,memory='128G',partition='preempt',qos='preempt_cpu_qos',tasks=1,gpus=0,time='2-00:00:00'),resume=True,mode=mode))
        started=time.monotonic();accepted=validate();write(receipt/'validation.json',accepted)
        if mode=='validate':
            write(OUTPUT/'validation.json',dict(success=True,receipt=str(receipt),source_hashes=hashes));return 0
        gate=json.loads((OUTPUT/'validation.json').read_text());assert gate['success'] and gate['source_hashes']==hashes
        # Immutable input binding is checked again after waiting in the queue.
        previous=json.loads((Path(gate['receipt'])/'validation.json').read_text());assert previous==accepted
        for key,value in dotenv_values(ROOT/'.env.local').items():
            if key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY') and value: os.environ[key]=value
        assert all(os.environ.get(k) for k in ('OPENAI_API_KEY','ANTHROPIC_API_KEY')),'missing configured credential'
        sys.path.insert(0,str(CODE/'scripts/babel'));from monitor import Monitor
        monitor=Monitor(policy()['coordination_dir'],receipt/'metrics.jsonl',[])
        stop=threading.Event()
        def sample():
            while not stop.is_set(): monitor.sample();stop.wait(30)
        thread=threading.Thread(target=sample,daemon=True);thread.start()
        exits=[]
        try:
            for arm,exp,study in inputs():
                result=run_direct_detection(DirectDetectionConfig(experiment=exp,study_dir=Path(exp.dag['revise']['output_dir']),output_dir=OUTPUT/arm,max_concurrency=60,resume=True,window=Window.FINAL_ARTIFACT))
                exits.append(result)
                if result: break
        finally:
            stop.set();thread.join();monitor.sample()
        assert all(sha(p)==h for p,h in hashes.items()),'source modified during execution'
        write(receipt/'result.json',dict(success=exits==[0,0],exits=exits,elapsed_seconds=time.monotonic()-started))
        return int(exits!=[0,0])
if __name__=='__main__':raise SystemExit(main())
