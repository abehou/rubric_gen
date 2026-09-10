"""Identify realized admissions specifically enabled by the changed rule."""
import hashlib,json,collections
from pathlib import Path
root=Path(__file__).resolve().parents[2]
p=root/'runs/babel-result20-cue-ranking-20260909/comparison-v1/joint-and-exposure-10371561/ranking_trace-exposure.json'
d=json.loads(p.read_text()); enabled=[]
for g in d['generations']:
 for decision in g['decisions']:
  if not decision['accepted']:continue
  decreases=[c for c in decision['margin_checks'] if not c['strict_improvement_required'] and c['prospective_margin']<c['current_margin']]
  if decreases:
   assert all(c['current_margin']>0 and c['prospective_margin']>0 and c['passed'] for c in decreases)
   enabled.append({'assignment':g['assignment'],'generation':g['generation'],'criterion_id':decision['criterion_id'],'decreased_positive_margins':decreases,'generation_path':g['path']})
assignments={e['assignment'] for e in enabled}
census=json.loads((root/'docs/reports/2026-09-09/cue-ranking-mechanism-census.json').read_text())
counts=collections.defaultdict(collections.Counter)
for r in census['rows']:
 assignment=f"{r['task']}--rep-{r['replicate']:03d}--solver-luna--user-simulator-red-team-trace"
 group='realized_changed_rule_admission' if assignment in assignments else 'no_realized_changed_rule_admission'
 counts[group]['auditor_rows']+=1
 counts[group]['new_positive']+=r['transition']=='0->1'
 for arm in ['static','trace','ranking']:counts[group][arm+'_positive']+=r['arms'][arm]['positive']
out={'source_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'enabled_admissions':enabled,'assignment_count':len(assignments),'strata':dict(counts),'limitation':'Within-run admission counterfactual only. Does not replay changed sequential proposer inputs or prove cross-run causal effects. Same seeds do not make hosted model sessions deterministic.'}
report=root/'docs/reports/2026-09-09/cue-ranking-rule-exposure.json';report.write_text(json.dumps(out,indent=2)+'\n')
lines=['# Realized exposure to the changed admission rule','','All accepted online decisions were checked against the former nondecreasing-margin requirement. Seven admissions across six of 60 assignments rely on the new rule; each shrinks an already-positive margin while keeping it positive.','','| Realized exposure | Auditor rows | Original trace RH | Ranking RH | Newly positive |','|---|---:|---:|---:|---:|']
for k,v in counts.items():lines.append(f"| {k} | {v['auditor_rows']} | {v['trace_positive']} | {v['ranking_positive']} | {v['new_positive']} |")
lines+=['','This is evidence against attributing the entire population RH increase directly to newly admitted criteria. Most assignments never used the changed acceptance permission. Hosted solver/proposer/auditor variability remains a competing explanation; frozen seeds and shared artifacts do not freeze provider outputs. Do not retrospectively discard unexposed cases or report an exposed-only treatment effect.','','The new policy still fails its full-population success criteria and must not be promoted. Next inspect actual delivery for the six exposed assignments and align new-positive trajectory evidence in time; then distinguish a policy mechanism failure from run-to-run instability before another revision experiment.']
report.with_suffix('.md').write_text('\n'.join(lines)+'\n');print('\n'.join(lines))
