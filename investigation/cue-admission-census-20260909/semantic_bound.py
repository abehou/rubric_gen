"""Hypothetical bound only: retain every non-semantic native gate."""
from pathlib import Path
from dataclasses import replace
import hashlib,json,os,sys
assert os.environ.get('SLURM_JOB_ID')
ROOT=Path('/home/aydanh/repos/rubric_gen');sys.path.insert(0,str(ROOT/'investigation/cue-citation-diagnostic-20260909'))
from context import load_context,ep
receipt=json.loads((ROOT/'docs/reports/2026-09-09/cue-admission-census.json').read_text());src=Path(receipt['analysis_path']);assert hashlib.sha256(src.read_bytes()).hexdigest()==receipt['analysis_sha256'];source=json.loads(src.read_text());rows=[]
for row in source['rows']:
 if row['context']['policy']!='red_team_trace' or not any(d['reason']=='semantic_validation_failed' for d in row['decisions']):continue
 x=load_context({'path':row['path']});old,ds=ep.admit_candidates(x['candidates'],x['validations'],x['pairs'],x['current']);old_ids={c.criterion.criterion_id for c in old}
 changed=tuple(replace(v,nonredundant=True) if v.observable and not v.nonredundant else v for v in x['validations'])
 new,nd=ep.admit_candidates(x['candidates'],changed,x['pairs'],x['current']);new_ids={c.criterion.criterion_id for c in new}
 rows.append({'path':row['path'],'task':row['task'],'replicate':row['replicate'],'generation':x['n'],'hypothetical_only':True,'old_ids':sorted(old_ids),'new_ids':sorted(new_ids-old_ids),'lost_ids':sorted(old_ids-new_ids),'decisions':[d.as_dict() for d in nd]})
result={'job_id':os.environ['SLURM_JOB_ID'],'scope':'Upper bound assuming every observable nonredundancy veto resolves favorably; no runtime/gate changes','contexts':len(rows),'potential_new_criteria':sum(len(r['new_ids']) for r in rows),'potential_new_contexts':sum(bool(r['new_ids']) for r in rows),'lost_existing':sum(len(r['lost_ids']) for r in rows),'rows':rows}
out=Path('/data/user_data/aydanh/rubric_gen/runs')/f"cue-semantic-bound-{os.environ['SLURM_JOB_ID']}";out.mkdir(exist_ok=False);(out/'analysis.json').write_text(json.dumps(result,indent=2));(ROOT/'docs/reports/2026-09-09/cue-semantic-bound.json').write_text(json.dumps(result,indent=2));print(json.dumps({k:v for k,v in result.items() if k!='rows'}))
