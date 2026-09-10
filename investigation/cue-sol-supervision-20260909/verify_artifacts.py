import json,os,hashlib,difflib,re
from pathlib import Path
assert os.environ.get('SLURM_JOB_ID')
root=Path('/home/aydanh/repos/rubric_gen');b=root/'investigation/cue-sol-supervision-20260909';inputs=json.loads((b/'inputs.json').read_text());support=json.loads((root/'docs/reports/2026-09-09/cue-sol-supervision-support.json').read_text());out=[]
for n in [3,7]:
 g=Path(inputs['rows'][n]['generation']);manifest=json.loads((g/'manifest.json').read_text());p=g/'artifact-history.json';assert hashlib.sha256(p.read_bytes()).hexdigest()==manifest['file_sha256s']['artifact-history.json'];h=json.loads(p.read_text());artifacts={a['artifact_id']:a for a in h['artifacts']};rows=[r for r in support['rows'] if r['context']==n and r['arm']=='sol_quality'];ids=set()
 for row in rows:
  for pair in row['pairs']:
   a=pair['pair']['preferred_artifact_id'];z=pair['pair']['rejected_artifact_id'];ids.update([a,z]);out.append({'context':n,'pair_id':pair['pair']['pair_id'],'preferred':a,'rejected':z,'diff':list(difflib.unified_diff(artifacts[a]['content'].splitlines(),artifacts[z]['content'].splitlines(),fromfile=a,tofile=z,n=5))})
 for aid in sorted(ids):
  a=artifacts[aid];assert hashlib.sha256(a['content'].encode()).hexdigest()==a['content_sha256'];lines=a['content'].splitlines();pattern=r'universe|background|G2M|gene.?set|intersection|union|fisher|hypergeom|7005|7,005|180|121' if n==7 else r'AUROC|0\.|mean|median|audit|preliminary';matches=set()
  for i,line in enumerate(lines):
   if re.search(pattern,line,re.I):matches.update(range(max(0,i-3),min(len(lines),i+4)))
  out.append({'context':n,'artifact_id':aid,'content_sha256':a['content_sha256'],'source':str(p),'numbered_excerpts':[f'{i+1}: {lines[i]}' for i in sorted(matches)]})
d={'job_id':os.environ['SLURM_JOB_ID'],'records':out};dest=Path('/data/user_data/aydanh/rubric_gen/runs/cue-sol-supervision-10377039/artifact-verification-v1');dest.mkdir(exist_ok=False);(dest/'evidence.json').write_text(json.dumps(d,indent=2));(root/'docs/reports/2026-09-09/cue-sol-application-artifacts.json').write_text(json.dumps(d,indent=2));print('records',len(out))
