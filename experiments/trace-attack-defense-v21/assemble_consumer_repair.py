"""Assemble a v2.1 consumer cohort from 118 sealed v2 assignments + 2 recoveries."""
from __future__ import annotations
import hashlib, json, os, shutil, subprocess
from pathlib import Path
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.experiment import load_experiment

BUNDLE=Path(__file__).resolve().parent
ROOT=BUNDLE.parents[1]
SOURCE=Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910/result20/study/biomnibench-da-factorial-r10-d2237f051bbf')
RUN=Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20')
TARGETS={'da-15-2--rep-002--solver-luna--full-red-team-trace','da-14-8--rep-003--solver-luna--user-simulator-red-team-trace'}

def sha(path):
 h=hashlib.sha256();
 with Path(path).open('rb') as f:
  for b in iter(lambda:f.read(1024*1024),b''): h.update(b)
 return h.hexdigest()

def main():
 if not os.environ.get('SLURM_JOB_ID'): raise RuntimeError('consumer assembly requires Slurm')
 exp=load_experiment(BUNDLE/'result20.yaml')
 consumer=Path(str(exp.dag['revise']['output_dir']))
 recovery_ledger=json.loads((consumer/'study.json').read_bytes())
 all_recovery_records=recovery_ledger['records']
 extra_completed=[r['assignment_id'] for r in all_recovery_records if r.get('status')=='completed' and r['assignment_id'] not in TARGETS]
 if extra_completed:
  raise RuntimeError(f'recovery ledger has unexpected completed assignments: {extra_completed}')
 recovery_rows={r['assignment_id']:r for r in all_recovery_records if r['assignment_id'] in TARGETS}
 if set(recovery_rows)!=TARGETS or any(r.get('status')!='completed' for r in recovery_rows.values()):
  raise RuntimeError('recovery ledger does not contain exactly the two completed targets')
 source_ledger=json.loads((SOURCE/'study.json').read_bytes())
 source_trace_records=[r for r in source_ledger['records'] if r.get('condition_id','').endswith('red-team-trace')]
 source_rows={r['assignment_id']:r for r in source_trace_records}
 if len(source_rows)!=120: raise RuntimeError(f'producer trace ledger is not Result20 scope: {len(source_rows)}')
 failed={a for a,r in source_rows.items() if r.get('status')!='completed'}
 if failed!=TARGETS or sum(r.get('status')=='completed' for r in source_rows.values())!=118:
  raise RuntimeError(f'producer failure set changed: {sorted(failed)}')
 consumer.mkdir(parents=True,exist_ok=True)
 imported=[]
 for assignment in exp.execution_assignments:
  aid=assignment.assignment_id
  if aid in TARGETS: continue
  row=source_rows[aid]
  if row.get('status')!='completed': raise RuntimeError(f'unexpected noncompleted producer row: {aid}')
  src=SOURCE/row['experiment_dir']; dst=consumer/row['experiment_dir']
  if dst.exists(): raise RuntimeError(f'consumer destination already exists: {dst}')
  dst.parent.mkdir(parents=True,exist_ok=True)
  shutil.copytree(src,dst,copy_function=os.link,symlinks=False)
  manifest=dst/'manifest.json'
  receipt={'kind':'v2_to_v21_assignment_import',
      'producer_experiment_id':source_ledger['experiment_id'], 'producer_trace_version':'attack_defense_v2',
      'consumer_experiment_id':exp.experiment_id, 'consumer_trace_version':'attack_defense_v2.1',
      'producer_manifest_sha256':sha(manifest)}
  write_json_atomic(dst/'consumer-import.json',receipt)
  imported.append({'assignment_id':aid,'experiment_dir':row['experiment_dir'],'producer_manifest_sha256':receipt['producer_manifest_sha256']})
 records=[]
 for assignment in exp.execution_assignments:
  aid=assignment.assignment_id
  records.append(recovery_rows[aid] if aid in TARGETS else source_rows[aid])
 if len(records)!=120 or any(r.get('status')!='completed' for r in records): raise RuntimeError('merged ledger is not complete')
 # Keep only the consumer ledger at this path; producer study.json remains untouched.
 ledger={'kind':source_ledger['kind'],'status':'completed_scope','experiment_path':str((BUNDLE/'result20.yaml').resolve()),
     'experiment_id':exp.experiment_id,'seed_run_dir':str(Path(str(exp.dag['seed']['output_dir'])).resolve()),
     'paraphrase_run_dir':str(Path(str(exp.dag['paraphrase']['output_dir'])).resolve()),
     'pretreatment_rubric_root':str((consumer/'pretreatment-rubrics').resolve()),
     'started_at':recovery_ledger.get('started_at'),'finished_at':recovery_ledger.get('finished_at'),'max_concurrency_last_invocation':32,
     'records':records}
 (consumer/'pretreatment-rubrics').mkdir(parents=True,exist_ok=True)
 write_json_atomic(consumer/'study.json',ledger)
 receipt={'kind':'attack_defense_v2.1_consumer_cohort','consumer_experiment_id':exp.experiment_id,
   'consumer_version':'attack_defense_v2.1','producer_experiment_id':source_ledger['experiment_id'],'producer_version':'attack_defense_v2',
   'producer_study_root':str(SOURCE),'consumer_study_root':str(consumer),'source_ledger_sha256':sha(SOURCE/'study.json'),
   'recovery_ledger_sha256':sha(consumer/'study.json'),'imported_completed_assignments':len(imported),'recovered_assignments':sorted(TARGETS),
   'total_completed_assignments':len(records),'hardlinked_producer_outputs':True,'provider_calls':0,'imports':imported,
   'consumer_code_commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
   'mechanical_patch':'candidate-local duplicate_criterion_title guard only'}
 write_json_atomic(RUN/'consumer-cohort.json',receipt)
 print(json.dumps({'consumer_study':str(consumer),'completed':len(records),'imported':len(imported),'recovered':2,'experiment_id':exp.experiment_id}),flush=True)
if __name__=='__main__': main()
