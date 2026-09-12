"""Read the completed common canonical control and existing ranking implementation."""
import csv,json,sys
from pathlib import Path
B=Path(__file__).resolve().parent;ROOT=B.parents[1]
sys.path.insert(0,str(ROOT/'experiments/trace-attack-defense-v3'))
import report_dev3_outcomes as outcomes
import artifact_gap_rh_ranking as ranking
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.pretreatment_reuse import source_pool
OUT=ROOT/'docs/reports/2026-09-12/trace-user-parallel-diagnostics'
rows=[];coverage=[];inputs=[]
for task in ('da-3-4','da-11-1','da-18-1'):
 p=ROOT/'experiments/trace-attack-defense-v3/control-v21-compatible'/f'{task}.yaml'
 exp,cov,values=outcomes.reconstruct(p);rows.extend(values);coverage.append({'task':task,'config':str(p),'coverage':cov})
 for cell in ('C10','C01','C11'):
  new=load_experiment(B/'configs'/cell/f'{task}.yaml')
  pool=source_pool(new) # Native existing producer/consumer validation; no mutation/calls.
  assert new.payload["solvers"]==exp.payload["solvers"] and new.protocol['feedback_simulator']==exp.protocol['feedback_simulator']
  assert new.payload["execution_audit_models"]==exp.payload["execution_audit_models"]
  assert new.dag['seed']['output_dir']==exp.dag['seed']['output_dir']
  assert new.dag['paraphrase']['output_dir']==exp.dag['paraphrase']['output_dir']
  inputs.append({'cell':cell,'task':task,'seed_root':exp.dag['seed']['output_dir'],
      'paraphrase_root':exp.dag['paraphrase']['output_dir'],'pretreatment_pool':str(pool),'native_source_compatible':True})
artifact=ranking.aggregate(rows,label='C00-canonical-v2.1');ranks=ranking.analyze(artifact)
(OUT/'control-outcomes.json').write_text(json.dumps({'provider_calls':0,'rows':rows,'coverage':coverage,'inputs':inputs},indent=2)+'\n')
(OUT/'artifact-gap-rh-ranking-summary.json').write_text(json.dumps({'C00':ranks,'challengers':'Not executed: all blocked by fixed feedback diagnostics; no challenger ranks or contrasts.'},indent=2)+'\n')
with (OUT/'artifact-gap-rh-ranking.csv').open('w') as stream:
 w=csv.DictWriter(stream,fieldnames=list(artifact[0]));w.writeheader();w.writerows(artifact)
print(json.dumps({'control_assignments':len(artifact),'auditor_rows':len(rows),'native_source_checks':len(inputs),'provider_calls':0}))
