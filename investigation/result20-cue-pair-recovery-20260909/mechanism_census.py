import json,collections,os,hashlib
from pathlib import Path
assert os.environ.get('SLURM_JOB_ID')
b=Path('/data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909')
p=b/'comparison-recovered-v3/analysis.json';a=json.loads(p.read_text());d=json.loads((b/'delivery-recovered-v1/analysis.json').read_text())
notes=collections.defaultdict(list)
for r in d['rows']:
 if r['requirements']:notes[r['assignment_id']].append(r['checkpoint'])
idx={}
for r in a['rows']:idx[r['analysis_condition'].split('/')[0],r['task_id'],r['replicate'],r['model']]=r
rows=[]
for key,r in idx.items():
 if key[0]!='active':continue
 old=idx[('trace',*key[1:])];static=idx[('static',*key[1:])]
 decision=lambda x:x['direct']['full_trajectory']['decision']
 rows.append(dict(task=r['task_id'],replicate=r['replicate'],model=r['model'],old=decision(old),new=decision(r),static=decision(static),note_checkpoints=notes[r['assignment_id']],gap_changes={k:r['values'][k]-old['values'][k] for k in ['WS','WA','A']},state_path=r['state_path'],verdict=r['direct']['full_trajectory']))
trans=collections.Counter((r['old'],r['new'],bool(r['note_checkpoints'])) for r in rows)
new=[r for r in rows if r['new']=='reward_hacking_detected' and r['old']!='reward_hacking_detected']
summary=dict(transitions=[dict(old=k[0],new=k[1],exposed=k[2],auditor_rows=v) for k,v in sorted(trans.items())],new_positive_rows=len(new),new_positive_without_notes=sum(not r['note_checkpoints'] for r in new),new_positive_with_notes=sum(bool(r['note_checkpoints']) for r in new))
result=dict(summary=summary,rows=rows,analysis_sha256=hashlib.sha256(p.read_bytes()).hexdigest(),warning='Exposure is post-treatment; descriptive association cannot establish causal attribution. No exclusions or outcome-conditioned reruns.')
out=b/'mechanism-census-v1';out.mkdir(exist_ok=False);(out/'analysis.json').write_text(json.dumps(result,indent=2))
report=Path('/home/aydanh/repos/rubric_gen/docs/reports/2026-09-09/cue-active-mechanism-census.json');report.write_text(json.dumps(result,indent=2))
print(json.dumps(summary,indent=2))
