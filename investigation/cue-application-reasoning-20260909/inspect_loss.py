"""Read-only fixed filtering contrast; no provider calls."""
import json,hashlib,os
from pathlib import Path
assert os.environ.get('SLURM_JOB_ID')
root=Path('/data/user_data/aydanh/rubric_gen/runs/cue-application-reasoning-10378006')
folder=root/'da-15-1-rep-002-high_reasoning'
ids=['artifact_6871a95fd2755c8f','artifact_8442669919b645a5','artifact_a9eaa02ddac1f735','artifact_f85bcdd9c4ed261e']
records=[]
for aid in ids:
 p=folder/aid/'request.json';r=json.loads(p.read_text());e=json.loads(r['evidence']);assert len(e['artifacts'])==1 and e['artifacts'][0]['artifact_id']==aid
 a=e['artifacts'][0];records.append({'artifact_id':aid,'request_sha256':hashlib.sha256(p.read_bytes()).hexdigest(),'artifact':a})
out=root/'filtering-inspection-v1';out.mkdir(exist_ok=False);result={'job_id':os.environ['SLURM_JOB_ID'],'records':records};(out/'analysis.json').write_text(json.dumps(result,indent=2))
# Only the focused requested evidence, not a whole run copy.
Path('/home/aydanh/repos/rubric_gen/docs/reports/2026-09-09/cue-reasoning-filtering-evidence.json').write_text(json.dumps(result,indent=2))
print('verified filtering artifacts',len(records))
