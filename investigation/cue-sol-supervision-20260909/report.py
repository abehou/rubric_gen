import hashlib,json,os,sys
from pathlib import Path
assert os.environ.get('SLURM_JOB_ID')
p=Path('/data/user_data/aydanh/rubric_gen/runs')/f'cue-sol-supervision-{sys.argv[1]}';r=json.loads((p/'result.json').read_text());assert r['success'] and len(r['results'])==18 and not r['failures'] and r['source_unchanged'];assert len({(c['task'],c['replicate'],c['arm']) for c in r['results']})==18
out=p/'report-v1';out.mkdir(exist_ok=False)
calls=list(p.glob('*/calls/*/request.json'));failures=list(p.glob('*/calls/*/failure-*.json'));result={**r,'job_id':os.environ['SLURM_JOB_ID'],'source_sha256':hashlib.sha256((p/'result.json').read_bytes()).hexdigest(),'calls':len(calls),'failed_attempt_records':len(failures)}
(out/'analysis.json').write_text(json.dumps(result,indent=2));Path('/home/aydanh/repos/rubric_gen/docs/reports/2026-09-09/cue-sol-supervision-result.json').write_text(json.dumps(result,indent=2));print('cells',len(r['results']),'calls',len(calls),'failed attempts',len(failures))
for c in r['results']:print(c['task'],c['replicate'],c['arm'],'proposed',c['proposed'],'accepted',c['accepted'],[d['reason'] for d in c['decisions']])
