"""No-provider census of saved criterion admissions; not a causal mediation test."""
import collections, hashlib, json, os
from pathlib import Path
ROOT=Path('/home/aydanh/repos/rubric_gen');BASE=ROOT/'runs/babel-result20-cue-score-first-trace-20260909'
def main():
 assert os.environ.get('SLURM_JOB_ID')
 receipt=next((BASE/'owners/trace-results20').glob('10368826-*/result.json'))
 assert json.loads(receipt.read_text())['success'], 'Require completed native audits before census'
 rows=[];counts=collections.Counter();fallbacks=collections.Counter()
 paths=sorted((BASE/'trace/study').glob('*/experiments/*/rep-*/*/*/state.json'));assert len(paths)==60
 for path in paths:
  revision=path.parent;state=json.loads(path.read_text());manifest=json.loads((revision/'manifest.json').read_text());gens=[]
  for p in sorted((revision/'rubric-generations').glob('generation-*/evolution.json')):
   d=json.loads(p.read_text());cs=json.loads((p.parent/'criteria.json').read_text());accepted=d.get('accepted_candidate_ids',[])
   for k,v in d.items():
    if 'fallback_reason' in k and v:fallbacks[k+': '+str(v)]+=1
   g=dict(round=d['context']['generation_round'],source_checkpoint=d['context']['source_checkpoint'],accepted_ids=accepted,available_ids=[c['criterion_id'] for c in cs],accepted_requirements=[c['requirement'] for c in cs if c['criterion_id'] in accepted],source=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest())
   gens.append(g);counts['generations']+=1;counts['accepted_candidates']+=len(accepted)
  admitted=any(g['accepted_ids'] for g in gens);counts['assignments_with_admissions']+=admitted
  rows.append(dict(task=manifest['task_id'],revision=str(revision),submission_count=len(state['submission_ids']),stop_reason=state['stop_reason'],has_admission=admitted,generations=gens))
 out=BASE/'criterion-admission-census-v1';out.mkdir(exist_ok=False)
 payload=dict(job_id=os.environ['SLURM_JOB_ID'],assignment_count=60,counts=dict(counts),fallbacks=dict(fallbacks),rows=rows,limitation='Admissions and availability only; not proof of concern delivery, criterion relevance, solver compliance or causation.')
 (out/'analysis.json').write_text(json.dumps(payload,indent=2)+'\n')
 text=['# Result20 revised trace: criterion admission census','','All60 completed revision histories; no provider calls. This records criterion admission and availability, not proof that a criterion appeared in simulator feedback or caused an observed RH difference.','','```json',json.dumps(dict(counts),indent=2),'```','','## Per-task assignments with admissions','','| Task | Assignments with admission |','|---|---:|']
 for task in sorted({r['task'] for r in rows}):text.append(f"| {task} | {sum(r['has_admission'] for r in rows if r['task']==task)}/3 |")
 text += ['','All accepted requirement text, generation timing, source hashes and fallbacks are in `runs/babel-result20-cue-score-first-trace-20260909/criterion-admission-census-v1/analysis.json`. Admission is a post-treatment variable; subgroup differences cannot establish a causal mechanism.']
 (ROOT/'docs/reports/2026-09-09/score-first-trace-criterion-admissions.md').write_text('\n'.join(text)+'\n')
if __name__=='__main__':main()
