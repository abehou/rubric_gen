from __future__ import annotations
import hashlib,json,os
from pathlib import Path
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.study_validation import validate_completed_revision

def sha(p):
 h=hashlib.sha256()
 with Path(p).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
 return h.hexdigest()
B=Path(__file__).resolve().parent; ROOT=B.parents[1]
RUN=Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20')
SOURCE=Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910/result20/study/biomnibench-da-factorial-r10-d2237f051bbf')
COMPAT=ROOT/'docs/reports/2026-09-11/trace-attack-defense-v2.1/compatibility-118.json'
def main():
 if not os.environ.get('SLURM_JOB_ID'): raise RuntimeError('compute-only validation requires Slurm')
 exp=load_experiment(B/'result20.yaml'); prod_exp=load_experiment(ROOT/'experiments/trace-attack-defense-v2/result20.yaml'); study=Path(str(exp.dag['revise']['output_dir'])); ledger=json.loads((study/'study.json').read_bytes())
 trace=[r for r in ledger['records'] if r.get('condition_id','').endswith('red-team-trace')]
 if len(trace)!=120 or any(r.get('status')!='completed' for r in trace): raise RuntimeError('trace scope is not 120 completed rows')
 byid={a.assignment_id:a for a in exp.execution_assignments}; prod_byid={a.assignment_id:a for a in prod_exp.execution_assignments}; seed=Path(str(exp.dag['seed']['output_dir'])); paraphrase=Path(str(exp.dag['paraphrase']['output_dir'])); prod_seed=Path(str(prod_exp.dag['seed']['output_dir'])); prod_paraphrase=Path(str(prod_exp.dag['paraphrase']['output_dir']))
 producer=json.loads((SOURCE/'study.json').read_bytes());prows={r['assignment_id']:r for r in producer['records'] if r.get('condition_id','').endswith('red-team-trace')}
 failed={a for a,r in prows.items() if r.get('status')!='completed'}
 targets={'da-15-2--rep-002--solver-luna--full-red-team-trace','da-14-8--rep-003--solver-luna--user-simulator-red-team-trace'}
 if failed!=targets: raise RuntimeError(f'producer failure set {failed}')
 rows=[]; imported=recovered=0
 for row in trace:
  aid=row['assignment_id']; root=study/row['experiment_dir']; assignment=byid[aid]
  is_import=aid not in targets
  if not is_import:
   validate_completed_revision(root,assignment,exp,seed,paraphrase)
  m=json.loads((root/'manifest.json').read_bytes()); version=m.get('red_team_trace_version')
  if aid in targets:
   if version!='attack_defense_v2.1' or (root/'consumer-import.json').exists(): raise RuntimeError('recovered identity/sidecar mismatch')
   recovered+=1
  else:
   if version!='attack_defense_v2' or not (root/'consumer-import.json').is_file(): raise RuntimeError('import identity/sidecar mismatch')
   receipt=json.loads((root/'consumer-import.json').read_bytes()); pm=SOURCE/prows[aid]['experiment_dir']/'manifest.json'
   if receipt['producer_manifest_sha256']!=sha(pm) or receipt['producer_manifest_sha256']!=sha(root/'manifest.json'): raise RuntimeError('producer import manifest hash mismatch')
   if __import__('os').stat(pm).st_ino != __import__('os').stat(root/'manifest.json').st_ino: raise RuntimeError('producer output was copied, not hard-linked')
   imported+=1
  rows.append({'assignment_id':aid,'version':version,'root':str(root),'manifest_sha256':sha(root/'manifest.json'),'state_sha256':sha(root/'state.json'),'records':len(list((root/'turns').glob('turn-*'))),'imported':is_import,'validation_mode':'compatibility_receipt' if is_import else 'v21_native_validator'})
 out={'kind':'attack_defense_v2.1_consumer_validation','job':os.environ['SLURM_JOB_ID'],'consumer_experiment_id':exp.experiment_id,'trace_expected':120,'trace_completed':len(trace),'imported_v2':imported,'recovered_v21':recovered,'provider_calls':0,'producer_failures':sorted(targets),'rows':rows,'compatibility_receipt':str(COMPAT)}
 p=RUN/'consumer-validation.json';p.write_text(json.dumps(out,indent=2)+'\n');print(json.dumps({'completed':len(trace),'imported':imported,'recovered':recovered}),flush=True)
if __name__=='__main__':main()
