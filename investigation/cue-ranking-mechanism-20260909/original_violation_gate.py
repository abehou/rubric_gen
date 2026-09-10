"""Provider-free census of candidate delivery exposure on frozen cue trace."""
import json,hashlib,re,collections
from pathlib import Path
root=Path(__file__).resolve().parents[2]
p=root/'runs/babel-result20-cue-ranking-20260909/comparison-v1/joint-and-exposure-10371561/original_trace-exposure.json'
d=json.loads(p.read_text());assert len(d['assignments'])==60
rows=[]
for a in d['assignments']:
 b=Path(a['state_path']).parent
 for f in sorted((b/'rubric-evaluations').glob('s*.json')):
  r=json.loads(f.read_text());g=b/'rubric-generations'/f"generation-{r['generation_round']:04d}"
  criteria=json.loads((g/'criteria.json').read_text());text=(g/'rubric.txt').read_text();parts=re.split(r'(?m)^Criterion (\d+):',text)
  vp=b/'judgments'/f.stem/r['rubric_sha256']/'score_validation.json'
  if not criteria:continue
  assert hashlib.sha256(vp.read_bytes()).hexdigest()==r['score_validation_sha256']
  v=json.loads(vp.read_text());bad=[]
  for c in criteria:
   nums=[parts[i] for i in range(1,len(parts),2) if 'Elicited criterion ID: '+c['criterion_id'] in parts[i+1]];assert len(nums)==1
   k='criterion_'+nums[0]
   if v['criterion_scores'][k]<0:bad.append({'id':c['criterion_id'],'source_generation':c['source_generation'],'requirement':c['requirement'],'score':v['criterion_scores'][k]})
  fp=b/'feedback'/f.name
  if bad:rows.append({'assignment':a['assignment'],'submission':f.stem,'generation':r['generation_round'],'has_feedback':fp.exists(),'violations':bad,'existing_feedback':json.loads(fp.read_text()) if fp.exists() else None,'validation_sha256':r['score_validation_sha256']})
nonterminal=[r for r in rows if r['has_feedback']]
summary={'assignments':60,'assignments_with_candidate_note':len({r['assignment'] for r in nonterminal}),'candidate_note_checkpoints':len(nonterminal),'terminal_violated_checkpoints_excluded':sum(not r['has_feedback'] for r in rows),'notes_with_previously_admitted_violation':sum(any(v['source_generation']<r['generation'] for v in r['violations']) for r in nonterminal),'notes_with_online_violation':sum(any(v['source_generation']>=2 for v in r['violations']) for r in nonterminal)}
out=root/'docs/reports/2026-09-09/cue-active-violation-exposure.json';out.write_text(json.dumps({'source_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'summary':summary,'rows':rows,'limitation':'Potential note exposure, not novel semantic information or evidence of treatment efficacy. Includes retained offline criteria; distinguishes online violations explicitly.'},indent=2)+'\n')
md=['# Active-violation delivery: original rubric-cue exposure gate','','No providers; all60frozen trace assignments included. Judgment hashes and stable criterion IDs checked against native receipts.','','| Measure | Count |','|---|---:|']+[f'| {k} | {v} |' for k,v in summary.items()]
md+=['','The candidate has nonzero nonterminal exposure in the primary branch. Counts alone do not establish useful new information: the saved simulator may already convey a requirement. The JSON retains existing feedback for that comparison. Runtime integration must still verify exact formatting, no note on zero-penalty/terminal checkpoints, unchanged controls, and scoring identity before any launch.']
out.with_suffix('.md').write_text('\n'.join(md)+'\n');print(summary)
