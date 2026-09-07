"""Resume one failed study through the unchanged production controller."""
import sys
sys.dont_write_bytecode=True
import argparse,importlib.util,json,os,hashlib
from pathlib import Path
from datetime import datetime
from dotenv import dotenv_values
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.study import StudyRunner,StudyRunConfig
ROOT=Path(__file__).resolve().parents[2];HERE=Path(__file__).resolve().parent

def sha(p):
    with p.open('rb') as f:return hashlib.file_digest(f,'sha256').hexdigest()

def main():
    p=argparse.ArgumentParser();p.add_argument('tag');p.add_argument('--attempt',type=int,required=True);a=p.parse_args()
    manifest=json.loads((HERE/'manifest.json').read_text());row=next(r for r in manifest['configs'] if r['tag']==a.tag)
    root=Path(row['study']);ledger=json.loads((root/'study.json').read_text());assert ledger['status']=='failed'
    name=f'recovery-{a.tag}-{a.attempt:02d}';launch=HERE/(name+'-launch.json');assert not launch.exists()
    completed=[root/r['experiment_dir'] for r in ledger['records'] if r['status']=='completed']
    protected={str(p):sha(p) for directory in completed+[root/'shared-judgments/judge/entries'] for p in directory.rglob('*') if p.is_file()}
    source={str(p):sha(p) for p in (ROOT/'src').rglob('*.py')}
    launch.write_text(json.dumps(dict(pid=os.getpid(),started_at=datetime.now().astimezone().isoformat(),concurrency=2,
        source_hashes=source,wrapper_sha256=sha(Path(__file__)),protected_files=protected,ledger_before=ledger),indent=2)+'\n')
    spec=importlib.util.spec_from_file_location('bounded_stage_reuse',HERE/'run_stage.py');helper=importlib.util.module_from_spec(spec);spec.loader.exec_module(helper);helper.install_reuse(manifest)
    for key,value in dotenv_values(ROOT/'.env.local').items():
        if key in ['OPENAI_API_KEY','ANTHROPIC_API_KEY'] and value:os.environ[key]=value
    exp=load_experiment(Path(row['config']));assert exp.experiment_id==row['experiment_id']
    status=StudyRunner(StudyRunConfig(exp,Path(exp.dag['seed']['output_dir']),Path(exp.dag['paraphrase']['output_dir']),root,2,True)).run()
    changed=[name for name,h in {**source,**protected}.items() if not Path(name).is_file() or sha(Path(name))!=h]
    result=dict(exit_code=status,protected_files=len(protected),changed=changed,ledger_after=json.loads((root/'study.json').read_text()))
    (HERE/(name+'-result.json')).write_text(json.dumps(result,indent=2)+'\n');assert not changed
    raise SystemExit(status)
if __name__=='__main__':main()
