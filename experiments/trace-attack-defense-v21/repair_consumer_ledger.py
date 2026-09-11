from __future__ import annotations
import hashlib,json,os
from pathlib import Path
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.experiment import load_experiment
B=Path(__file__).resolve().parent; ROOT=B.parents[1]
RUN=Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20')
SOURCE=Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910/result20/study/biomnibench-da-factorial-r10-d2237f051bbf')
def sha(p): return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 if not os.environ.get('SLURM_JOB_ID'): raise RuntimeError('compute-only ledger repair requires Slurm')
 exp=load_experiment(B/'result20.yaml'); consumer=Path(str(exp.dag['revise']['output_dir'])); cp=consumer/'study.json'; pre=sha(cp)
 source=json.loads((SOURCE/'study.json').read_bytes()); current=json.loads(cp.read_bytes())
 source_records=source['records']; current_trace=[r for r in current['records'] if r.get('condition_id','').endswith('red-team-trace')]
 if len(source_records)!=240 or len(current_trace)!=120 or any(r.get('status')!='completed' for r in current_trace): raise RuntimeError('unexpected source/current ledger scope')
 source_trace={r['assignment_id']:r for r in source_records if r.get('condition_id','').endswith('red-team-trace')}
 if len(source_trace)!=120: raise RuntimeError('producer trace scope mismatch')
 current_by={r['assignment_id']:r for r in current_trace}
 if set(current_by)!=set(source_trace): raise RuntimeError('consumer trace IDs differ from producer trace IDs')
 rows=[];static=0;trace=0
 for r in source_records:
  if r.get('condition_id','').endswith('red-team-trace'):
   rows.append(current_by[r['assignment_id']]);trace+=1
  else:
   if r.get('status')!='pending': raise RuntimeError('static source row was not pending')
   rows.append(r);static+=1
 out=dict(source)
 out.update({'status':'completed_scope','experiment_path':str((B/'result20.yaml').resolve()),'experiment_id':exp.experiment_id,
   'seed_run_dir':str(Path(str(exp.dag['seed']['output_dir'])).resolve()),'paraphrase_run_dir':str(Path(str(exp.dag['paraphrase']['output_dir'])).resolve()),
   'pretreatment_rubric_root':str((consumer/'pretreatment-rubrics').resolve()),'records':rows,
   'execution_conditions':list(exp.execution_conditions),'started_at':current.get('started_at'),'finished_at':current.get('finished_at'),'max_concurrency_last_invocation':32})
 write_json_atomic(cp,out); post=sha(cp)
 receipt={'kind':'attack_defense_v2.1_consumer_ledger_scope_repair','job':os.environ['SLURM_JOB_ID'],'consumer_experiment_id':exp.experiment_id,
   'producer_study_root':str(SOURCE),'consumer_study_root':str(consumer),'pre_repair_consumer_ledger_sha256':pre,'post_repair_consumer_ledger_sha256':post,
   'producer_ledger_sha256':sha(SOURCE/'study.json'),'total_records':len(rows),'static_pending_preserved':static,'trace_completed':trace,
   'execution_conditions':list(exp.execution_conditions),'provider_calls':0,'mechanical_reason':'native terminal_records requires full assignment ledger plus declared trace execution scope; no tree or judgment bytes changed'}
 write_json_atomic(RUN/'consumer-ledger-repair.json',receipt)
 print(json.dumps({'records':len(rows),'static_pending':static,'trace_completed':trace,'execution_conditions':list(exp.execution_conditions)}),flush=True)
if __name__=='__main__':main()
