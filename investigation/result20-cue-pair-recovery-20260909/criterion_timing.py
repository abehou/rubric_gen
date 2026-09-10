import json,os
from pathlib import Path
from rubric_gen.submission_revision.rubric_generation_store import load_rubric_generation
assert os.environ.get('SLURM_JOB_ID')
b=Path('/data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909')
rows=json.loads((b/'comparison-recovered-v3/analysis.json').read_text())['rows'];seen=set();out=[]
for r in rows:
 k=(r['task_id'],r['replicate'])
 if r['analysis_condition'].split('/')[0]!='active' or k not in {('da-15-1',2),('da-10-1',3),('da-15-2',2),('da-15-7',3)} or k in seen:continue
 seen.add(k);root=Path(r['state_path']).parent;records=[]
 for p in sorted((root/'rubric-evaluations').glob('s*.json')):
  e=json.loads(p.read_text());g=load_rubric_generation(root,e['generation_round'])
  records.append(dict(checkpoint=p.stem,evaluation=e,generation=g.artifact_record() if hasattr(g,'artifact_record') else str(g)))
 out.append(dict(task=k[0],replicate=k[1],root=str(root),records=records))
p=b/'criterion-timing-v1';p.mkdir(exist_ok=False);(p/'analysis.json').write_text(json.dumps(out,indent=2))
Path('/home/aydanh/repos/rubric_gen/docs/reports/2026-09-09/cue-criterion-timing.json').write_text(json.dumps(out,indent=2))
print('cases',len(out),'output',p)
