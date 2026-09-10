import hashlib,json,os,sys
from pathlib import Path
assert os.environ.get('SLURM_JOB_ID')
root=Path('/home/aydanh/repos/rubric_gen');p=Path('/data/user_data/aydanh/rubric_gen/runs')/f'cue-sol-conditional-{sys.argv[1]}';r=json.loads((p/'result.json').read_text());assert r['success'] and r['source_unchanged'] and len(r['results'])==4 and not r['failures'];assert len({(c['task'],c['replicate'],c['arm']) for c in r['results']})==4
old=json.loads((p.parent/'cue-sol-induction-10377844/result.json').read_text());historical={(c['task'],c['replicate']):c for c in old['results'] if c['arm']=='sol_induction'}
def levels(c):return {(v['criterion_id'],a['artifact_id']):a['level'] for v in c['validations']['validations'] for a in v['artifact_applications']}
comparisons=[]
for c in sorted(r['results'],key=lambda c:(c['task'],c['replicate'],c['arm'])):
 original=historical[(c['task'],c['replicate'])];a=levels(original);b=levels(c);assert a.keys()==b.keys();comparisons.append(dict(task=c['task'],replicate=c['replicate'],arm=c['arm'],accepted=c['accepted'],historical_accepted=original['accepted'],applications=len(a),changed_levels=[{'criterion_id':k[0],'artifact_id':k[1],'old':a[k],'new':b[k]} for k in a if a[k]!=b[k]]))
requests=list(p.glob('*/*/request.json'));failures=list(p.glob('*/*/failure-*.json'));assert len(requests)==json.loads((p/'launch.json').read_text())['expected_calls']
result={**r,'source_sha256':hashlib.sha256((p/'result.json').read_bytes()).hexdigest(),'calls':len(requests),'failed_attempts':len(failures),'application_comparisons':comparisons};out=p/'report-v1';out.mkdir(exist_ok=False);(out/'analysis.json').write_text(json.dumps(result,indent=2));(root/'docs/reports/2026-09-09/cue-sol-conditional-result.json').write_text(json.dumps(result,indent=2));print('cells',len(r['results']),'calls',len(requests),'failed attempts',len(failures))
for c in comparisons:print(c['task'],c['replicate'],c['arm'],'accepted',c['accepted'],'changed',len(c['changed_levels']),'/',c['applications'])
