"""Provider-free inventory of small numerical contrasts; no inferred gold labels."""
import difflib, hashlib, json, os, re
from pathlib import Path
assert os.environ.get('SLURM_JOB_ID')
base=Path('/data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909')
rows=json.loads((base/'comparison-recovered-v3/analysis.json').read_text())['rows']
roots={str(Path(r['state_path']).parent):r['analysis_condition'] for r in rows if not r['analysis_condition'].startswith('static')}
out=base/'pair-census-v1';out.mkdir(exist_ok=False)
seen={};counts={};candidates=[]
for root,condition in sorted(roots.items()):
 for hp in sorted((Path(root)/'rubric-generations').glob('generation-*/artifact-history.json')):
  raw=hp.read_bytes();h=json.loads(raw);arts={a['artifact_id']:a for a in h['artifacts']}
  ap=hp.parent/'pairwise-assessment-rubric-free.json'
  assessments={a['pair_id']:a for a in json.loads(ap.read_text())['assessments']}
  for pair in h['pairs']:
   ids=pair['artifact_ids'];key=(condition,*sorted(arts[i]['content_sha256'] for i in ids))
   if key in seen:continue
   seen[key]=True;counts[condition]=counts.get(condition,0)+1
   texts=[arts[i]['content'] for i in ids]
   for i,t in zip(ids,texts):assert hashlib.sha256(t.encode()).hexdigest()==arts[i]['content_sha256']
   lines=[t.splitlines() for t in texts];sm=difflib.SequenceMatcher(a=lines[0],b=lines[1],autojunk=False)
   changes=[(tag,i,j,k,l) for tag,i,j,k,l in sm.get_opcodes() if tag!='equal']
   changed=sum(j-i+l-k for _,i,j,k,l in changes)
   if not 0<changed<=4:continue
   diff=[s for _,i,j,k,l in changes for s in lines[0][i:j]+lines[1][k:l]]
   if not any(re.search(r'\d',s) for s in diff):continue
   presentation=ids[::-1] if int(hashlib.sha256(('assessment-order\0'+pair['pair_id']).encode()).hexdigest(),16)%2 else ids
   candidates.append(dict(condition=condition,history=str(hp),history_sha256=hashlib.sha256(raw).hexdigest(),pair_id=pair['pair_id'],A=presentation[0],B=presentation[1],assessment=assessments[pair['pair_id']],diff=list(difflib.unified_diff(lines[0],lines[1],fromfile=ids[0],tofile=ids[1],n=2)),gold_label=None))
result=dict(job_id=os.environ['SLURM_JOB_ID'],roots=len(roots),unique_pairs_by_condition=counts,candidate_count=len(candidates),selection='First occurrence per condition/content-hash pair; <=4 changed lines containing a digit; no RH or quality labels used; candidates require content review, not automated gold labels.',candidates=candidates)
(out/'inventory.json').write_text(json.dumps(result,indent=2))
receipt={k:v for k,v in result.items() if k!='candidates'};receipt['output']=str(out/'inventory.json');receipt['sha256']=hashlib.sha256((out/'inventory.json').read_bytes()).hexdigest()
Path('/home/aydanh/repos/rubric_gen/docs/reports/2026-09-09/cue-pair-census-receipt.json').write_text(json.dumps(receipt,indent=2))
print(json.dumps(receipt,indent=2))
