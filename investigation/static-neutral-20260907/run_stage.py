"""Bounded development dispatcher using current production workflows and exact caches."""
import sys
sys.dont_write_bytecode=True
import argparse, importlib.util, json, os, subprocess, tarfile
from pathlib import Path
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from dotenv import dotenv_values
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.study import StudyRunConfig, StudyRunner, _ProgressPositions, _exclusive_study_lease
from rubric_gen.submission_revision.artifacts import sha256_file
from rubric_gen.submission_revision.judgment_reuse import ExactJudgmentReuseStore
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent

def module(name,path):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m

def install_reuse(manifest):
    m=module('bounded_revision_reuse',ROOT/'investigation/autonomous-dev3-20260907/exposure-calibration/run_revision.py')
    m.SOURCES += [Path(r['study'])/'shared-judgments/judge' for r in manifest['configs']]
    m.SOURCES += [ROOT/'runs/selected-reference-wiring-smoke-20260907-attempt02/reuse/judge']
    for task,identity in [('da-3-4','biomnibench-da-factorial-r10-f1268754291f'),('da-11-1','biomnibench-da-factorial-r10-ac19f8be2fe3')]:
        m.SOURCES.append(ROOT/f'runs/autonomous-dev3-20260907/exposure-{task}/study/{identity}/shared-judgments/judge')
    ExactJudgmentReuseStore.resolve=m.resolve

def main():
    p=argparse.ArgumentParser();p.add_argument('stage',choices=['smoke','revise']);p.add_argument('--attempt',type=int,required=True);a=p.parse_args()
    manifest=json.loads((HERE/'manifest.json').read_text());install_reuse(manifest)
    env=dotenv_values(ROOT/'.env.local')
    for key in ['OPENAI_API_KEY','ANTHROPIC_API_KEY']:
        if env.get(key):os.environ[key]=env[key]
    source={str(p.relative_to(ROOT)):sha256_file(p) for p in (ROOT/'src').rglob('*.py')}
    tag=f'{a.stage}-{a.attempt:02d}'
    launch=HERE/f'{tag}-launch.json';assert not launch.exists()
    launch.write_text(json.dumps(dict(pid=os.getpid(),started_at=datetime.now().astimezone().isoformat(),source_hashes=source,
        script_sha256=sha256_file(Path(__file__)),manifest_sha256=sha256_file(HERE/'manifest.json'),
        concurrency=2 if a.stage=='smoke' else 24,argv=sys.argv),indent=2)+'\n')
    (HERE/f'{tag}-working-tree.diff').write_bytes(subprocess.check_output(['git','diff'],cwd=ROOT))
    with tarfile.open(HERE/f'{tag}-source.tar.gz','x:gz') as archive:
        archive.add(ROOT/'src',arcname='src',filter=lambda info:None if '__pycache__' in info.name else info)
        for r in manifest['configs']:archive.add(r['config'],arcname='experiments/'+Path(r['config']).name)
    def runner(row):
        exp=load_experiment(Path(row['config']));assert exp.experiment_id==row['experiment_id']
        study=Path(row['study'])
        return StudyRunner(StudyRunConfig(exp,Path(exp.dag['seed']['output_dir']),Path(exp.dag['paraphrase']['output_dir']),study,6,study.exists()))
    results=[]
    if a.stage=='smoke':
        row=next(r for r in manifest['configs'] if r['tag']=='neutral-da-3-4');run=runner(row)
        run.root.mkdir(parents=True,exist_ok=True)
        with _exclusive_study_lease(run.root):
            assignments=list(run.experiment.assignments)
            if not (run.root/'study.json').exists():run._write_manifest(run._new_manifest(assignments))
            selected=[x for x in assignments if x.replicate==1]
            done={r['assignment_id'] for r in run._load_manifest()['records'] if r['status']=='completed'}
            positions=_ProgressPositions(2)
            with ThreadPoolExecutor(max_workers=2) as pool:
                list(pool.map(lambda x:run._execute_assignment(x,positions),[x for x in selected if x.assignment_id not in done]))
            records=run._load_manifest()['records'];results=[r for r in records if r['replicate']==1]
            success=all(r['status']=='completed' for r in results)
    else:
        def execute(row):
            try:return dict(tag=row['tag'],exit_code=runner(row).run())
            except Exception as exc:return dict(tag=row['tag'],exit_code=1,error_type=type(exc).__name__,error=str(exc))
        with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(execute,manifest['configs']))
        success=all(r['exit_code']==0 for r in results)
    assert all(sha256_file(ROOT/p)==h for p,h in source.items())
    (HERE/f'{tag}-result.json').write_text(json.dumps(dict(success=success,results=results),indent=2)+'\n')
    raise SystemExit(0 if success else 1)
if __name__=='__main__':main()
