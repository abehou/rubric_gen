"""Select the prespecified contexts and index their exact stored request locations."""
import hashlib,json,os
from pathlib import Path
assert os.environ.get('SLURM_JOB_ID')
base=Path('/data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909')
p=base/'pair-census-v1/inventory.json';x=json.loads(p.read_text());chosen=[];seen=set()
for c in sorted(x['candidates'],key=lambda c:(c['history'],c['pair_id'])):
 parts=Path(c['history']).parts; exp=parts.index('experiments');key=tuple(parts[exp+1:exp+3])
 if key in seen:continue
 seen.add(key);chosen.append(c)
 if len(chosen)==8:break
anchor=next((c for c in x['candidates'] if c['pair_id']=='pair_c94a2cf8125fe4dc' and c['history'].endswith('generation-0002/artifact-history.json')),None)
if anchor and not any(c['history']==anchor['history'] for c in chosen):chosen.append(anchor)
result={'job_id':os.environ['SLURM_JOB_ID'],'census_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'contexts':[]}
for c in chosen:
 g=Path(c['history']).parent;root=g.parent.parent
 e=json.loads((g/'evolution.json').read_text())
 result['contexts'].append({**c,'generation_files':[p.name for p in g.iterdir()],'root_directories':[p.name for p in root.iterdir() if p.is_dir()],'evolution_keys':list(e),'evolution_metadata':{k:v for k,v in e.items() if k not in ['current_generation','generation','artifact_history'] and len(json.dumps(v))<4000}})
out=base/'pair-context-index-v1';out.mkdir(exist_ok=False);(out/'index.json').write_text(json.dumps(result,indent=2))
Path('/home/aydanh/repos/rubric_gen/docs/reports/2026-09-09/cue-pair-context-index.json').write_text(json.dumps(result,indent=2))
print('contexts',len(chosen),'output',out)
