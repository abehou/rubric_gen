from __future__ import annotations
import hashlib,json,os,tempfile
from pathlib import Path
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.experiment import load_experiment
B=Path(__file__).resolve().parent; ROOT=B.parents[1]
RUN=Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20')
SOURCE=Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910/result20/study/biomnibench-da-factorial-r10-d2237f051bbf')
TARGETS={'da-15-2--rep-002--solver-luna--full-red-team-trace','da-14-8--rep-003--solver-luna--user-simulator-red-team-trace'}
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def atomic_replace(path, data):
 fd,tmp=tempfile.mkstemp(prefix='.status-repair-',dir=str(path.parent)); os.close(fd)
 Path(tmp).write_bytes(data); os.replace(tmp,path)
def main():
 if not os.environ.get('SLURM_JOB_ID'): raise RuntimeError('compute-only audit-view repair requires Slurm')
 exp=load_experiment(B/'result20.yaml'); study=Path(str(exp.dag['revise']['output_dir'])); ledger=json.loads((study/'study.json').read_bytes())
 trace=[r for r in ledger['records'] if r.get('condition_id','').endswith('red-team-trace')]
 if len(trace)!=120 or any(r.get('status')!='completed' for r in trace): raise RuntimeError('consumer trace scope incomplete')
 rows=[]; changed=0; files=0
 for r in trace:
  if r['assignment_id'] in TARGETS: continue
  root=study/r['experiment_dir']
  for status in sorted(root.glob('submissions/*/status.json')):
   raw=json.loads(status.read_bytes())
   workspace=raw.get('workspace_dir')
   expected=str(status.parent/'workspace')
   if workspace != expected:
    old=sha(status); raw['workspace_dir']=expected; payload=(json.dumps(raw,ensure_ascii=False,indent=2)+'\n').encode()
    parent_mode=os.stat(status.parent).st_mode; status_mode=os.stat(status).st_mode
    os.chmod(status.parent, parent_mode | 0o200)
    try:
     atomic_replace(status,payload)
     os.chmod(status,status_mode)
    finally:
     os.chmod(status.parent,parent_mode)
    new=sha(status); rows.append({'assignment_id':r['assignment_id'],'path':str(status),'old_sha256':old,'new_sha256':new,'old_workspace_dir':workspace,'new_workspace_dir':expected}); changed+=1
   files+=1
 receipt={'kind':'attack_defense_v2.1_consumer_import_status_path_repair','job':os.environ['SLURM_JOB_ID'],'consumer_experiment_id':exp.experiment_id,'producer_study_root':str(SOURCE),'consumer_study_root':str(study),'imported_assignments':118,'recovered_assignments':2,'status_files_scanned':files,'status_files_rewritten':changed,'rows':rows,'provider_calls':0,'source_run_unchanged':True,'scientific_bytes_unchanged':True,'reason':'strict audit discovery requires status workspace_dir to resolve under the consumer run; only consumer-side hardlink entries were replaced, leaving producer inodes and all public/trajectory/rubric bytes untouched'}
 write_json_atomic(RUN/'consumer-import-status-repair.json',receipt); print(json.dumps({'scanned':files,'rewritten':changed}),flush=True)
if __name__=='__main__':main()
