import hashlib,json,os,sys
from pathlib import Path
assert os.environ.get('SLURM_JOB_ID')
root=Path('/home/aydanh/repos/rubric_gen');p=Path('/data/user_data/aydanh/rubric_gen/runs')/f'cue-application-check-{sys.argv[1]}';r=json.loads((p/'result.json').read_text());assert r['success'] and r['source_unchanged'] and len(r['results'])==9 and not r['failures'];assert len({(c['task'],c['replicate']) for c in r['results']})==9
baseline_path=p.parent/'cue-sol-application-10377313/result.json';baseline=json.loads(baseline_path.read_text());assert baseline['success'] and baseline['source_unchanged'];controls={(c['task'],c['replicate']):c for c in baseline['results'] if c['arm']=='control'}
def levels(c):return {(v['criterion_id'],a['artifact_id']):a['level'] for v in c['validations']['validations'] for a in v['artifact_applications']}
comparisons=[]
for c in sorted(r['results'],key=lambda c:(c['task'],c['replicate'])):
 control=controls[(c['task'],c['replicate'])];assert c['candidates']==control['candidates'];a=levels(control);b=levels(c);assert a.keys()==b.keys();comparisons.append(dict(task=c['task'],replicate=c['replicate'],accepted=c['accepted'],control_accepted=control['accepted'],applications=len(a),changed_levels=[{'criterion_id':k[0],'artifact_id':k[1],'old':a[k],'new':b[k]} for k in a if a[k]!=b[k]]))
requests=list(p.glob('*/*/request.json'));failures=list(p.glob('*/*/failure-*.json'));assert len(requests)==57
result={**r,'source_sha256':hashlib.sha256((p/'result.json').read_bytes()).hexdigest(),'control_sha256':hashlib.sha256(baseline_path.read_bytes()).hexdigest(),'calls':len(requests),'failed_attempts':len(failures),'application_comparisons':comparisons};out=p/'report-v1';out.mkdir(exist_ok=False);(out/'analysis.json').write_text(json.dumps(result,indent=2));(root/'docs/reports/2026-09-09/cue-application-check-result.json').write_text(json.dumps(result,indent=2));print('cells',len(r['results']),'calls',len(requests),'failed attempts',len(failures))
for c in comparisons:print(c['task'],c['replicate'],'accepted',c['accepted'],'control',c['control_accepted'],'changed',len(c['changed_levels']),'/',c['applications'])
