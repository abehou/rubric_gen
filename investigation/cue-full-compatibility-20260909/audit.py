"""Read-only frozen-arm provenance comparison; no providers or result mutation."""
import hashlib,json,os
from pathlib import Path
R=Path('/home/aydanh/repos/rubric_gen')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def objhash(x):return hashlib.sha256(json.dumps(x,sort_keys=True,separators=(',',':')).encode()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
assert os.environ.get('SLURM_JOB_ID')
out=R/'docs/reports/2026-09-09/cue-full-compatibility.json'
assert not out.exists()
paths={'earlier':R/'runs/babel-result20-current-20260908/report-v2/analysis.json','cue':R/'runs/babel-result20-cue-contrast-20260908/comparison-v1/analysis.json'}
analyses={k:read(p) for k,p in paths.items()}
rows={}
for group,d in analyses.items():
 for row in d['rows']:
  if row['model']=='gpt-5.6-sol':rows.setdefault(row['condition_id'] if group=='earlier' else 'cue-'+row['condition_id'],{})[(row['task_id'],row['replicate'])]=row
base=rows['cue-user-simulator-static'];comparisons={}; manifests={};files={}
for label,rs in rows.items():
 if label.startswith('user-'):continue
 assert set(rs)==set(base) and len(rs)==60
 diffs={};rubrics=[];initial=[];mm=[]
 for key,row in sorted(rs.items()):
  p=Path(row['state_path']).with_name('manifest.json');b=Path(base[key]['state_path']).with_name('manifest.json')
  m=read(p);bm=read(b);mm.append(m)
  assert sha(row['state_path'])==row['state_sha256']
  for field in sorted(set(m)|set(bm)):
   if m.get(field)!=bm.get(field):diffs.setdefault(field,[]).append({'task':key[0],'replicate':key[1],'arm':m.get(field),'cue_static':bm.get(field)})
  for field in ['initial_rubric','development_rubric']:
   assert sha(m[field+'_path'])==m[field+'_sha256']
  task=Path(m['task_dir']);assert sha(task/'instruction.md')==m['instruction_sha256'];assert sha(task/'tests'/m['master_rubric_name'])==m['master_rubric_sha256']
  pool=Path(m['initial_rubric_path']).parent
  hashes={f'variant-{i:03d}':sha(pool/f'variant-{i:03d}.txt') for i in range(5)}
  rubrics.append({'task':key[0],'replicate':key[1],'master':m['master_rubric_sha256'],**hashes})
  initial.append({'task':key[0],'replicate':key[1],'seed':m['seed_sha256'],'initial':row['initial_submission_sha256'],'instruction':m['instruction_sha256'],'data':m['data_sha256']})
  files[str(p)] = sha(p)
 comparisons[label]={'assignments':len(rs),'inventory_sha256':objhash(sorted(rs)),'rubrics_sha256':objhash(rubrics),'initial_inputs_sha256':objhash(initial),'field_differences':diffs,'initial_inputs':initial,'rubrics':rubrics,'auditors':sorted({r['model'] for d in analyses.values() for r in d['rows']})}
 manifests[label]=mm
receipts={};source_sets={}
owners=list((R/'runs/babel-overnight-20260907').glob('dispatcher-full*'))+list((R/'runs/babel-result20-cue-contrast-20260908/owners').glob('*'))
for owner in owners:
 for p in owner.glob('*/launch.json'):
  d=read(p);hashes=d.get('source_hashes',{});src={};bad=[]
  for n,h in hashes.items():
   q=Path(n) if Path(n).is_absolute() else Path(d.get('checkout',R))/n
   if '/src/' in str(q):src[str(q).split('/src/',1)[1]]=h
   if not q.is_file() or sha(q)!=h:bad.append(str(q))
  receipts[str(p)]={'sha256':sha(p),'commit':d.get('git_commit'),'mismatches':bad,'source_count':len(src)}
  source_sets[str(p)] = src
cuekey=next(k for k in source_sets if '10365215-' in k);cue=source_sets[cuekey]
source_diffs={k:{n:{'earlier':v.get(n),'cue':cue.get(n)} for n in sorted(set(v)|set(cue)) if v.get(n)!=cue.get(n)} for k,v in source_sets.items()}
result={'job':os.environ['SLURM_JOB_ID'],'script_sha256':sha(__file__),'analysis_hashes':{str(p):sha(p) for p in paths.values()},'comparisons':comparisons,'manifest_hashes':files,'receipts':receipts,'source_differences':source_diffs,'source_hashes':source_sets}
out.write_text(json.dumps(result,indent=2)+'\n');print(json.dumps({'output':str(out),'sha256':sha(out),'arms':{k:{f:v[f] for f in ['assignments','inventory_sha256','rubrics_sha256','initial_inputs_sha256']} for k,v in comparisons.items()},'receipt_mismatches':{k:v['mismatches'] for k,v in receipts.items() if v['mismatches']}}))
