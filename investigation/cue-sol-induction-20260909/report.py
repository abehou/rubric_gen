from pathlib import Path
import hashlib,json,os,sys
assert os.environ.get('SLURM_JOB_ID')
root=Path('/home/aydanh/repos/rubric_gen');p=Path('/data/user_data/aydanh/rubric_gen/runs')/f'cue-sol-induction-{sys.argv[1]}';r=json.loads((p/'result.json').read_text());assert r['success'] and r['source_unchanged'] and len(r['results'])==4 and not r['failures'];assert len({(c['task'],c['replicate']) for c in r['results']})==4
old_path=root/'runs/cue-citation-diagnostic-10370826/result.json';old=json.loads(old_path.read_text());assert old['success'];controls={(c['task'],c['replicate']):c for c in old['results'] if c['arm']=='control'}
comparison=[]
for c in r['results']:
 b=controls[(c['task'],c['replicate'])];comparison.append({'task':c['task'],'replicate':c['replicate'],'proposed':c['proposed'],'accepted':c['accepted'],'control_proposed':b['proposed'],'control_accepted':b['accepted'],'decisions':[d['reason'] for d in c['decisions']]})
requests=list(p.glob('*/calls/*/request.json'));failures=list(p.glob('*/calls/*/failure-*.json'));result={**r,'source_sha256':hashlib.sha256((p/'result.json').read_bytes()).hexdigest(),'control_sha256':hashlib.sha256(old_path.read_bytes()).hexdigest(),'calls':len(requests),'failed_attempts':len(failures),'comparison':comparison};out=p/'report-v1';out.mkdir(exist_ok=False);(out/'analysis.json').write_text(json.dumps(result,indent=2));(root/'docs/reports/2026-09-09/cue-sol-induction-result.json').write_text(json.dumps(result,indent=2));print('cells',len(r['results']),'calls',len(requests),'failed attempts',len(failures));print(json.dumps(comparison,indent=2))
