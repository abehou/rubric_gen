"""Read-only request-size/provenance diagnosis; no providers or artifact mutation."""
import hashlib,json,os,socket
from pathlib import Path
from collections import Counter
ROOT=Path('/home/aydanh/repos/rubric_gen')
study=next((ROOT/'runs/babel-result20-current-20260908/user-trace/study').glob('*/study.json'))
data=json.loads(study.read_text());cases=[]
for row in data['records']:
    if row['condition_id'] not in data['execution_conditions'] or row.get('error_type')!='RubricProposerInputLimitError':continue
    root=study.parent/row['experiment_dir'];records=[]
    for p in (root/'rubric-proposer-records').glob('*.json'):
        v=json.loads(p.read_text());c=v['identity']['context'];req=v['request'];e=req['evidence']
        payload=json.JSONDecoder().raw_decode(e)[0]
        records.append(dict(path=str(p),sha256=hashlib.sha256(p.read_bytes()).hexdigest(),generation=c['generation_round'],stage=req['stage'],evidence_bytes=len(e.encode()),schema_bytes=len(json.dumps(req['response_schema'],sort_keys=True,separators=(',',':')).encode()),top_level_bytes={k:len(json.dumps(x,ensure_ascii=False,separators=(',',':')).encode()) for k,x in payload.items()},proposer=c['proposer'],implementation=v['identity']['implementation']))
    latest=max(r['generation'] for r in records)
    cases.append(dict(assignment=row['assignment_id'],error=row['error'],latest_generation=latest,completed_generations=sorted(p.name for p in (root/'rubric-generations').glob('generation-*')),cached_requests=len(records),latest_requests=[r for r in records if r['generation']==latest]))
out=ROOT/f'runs/babel-result20-current-20260908/input-capacity-diagnostic-{os.environ["SLURM_JOB_ID"]}';out.mkdir(exist_ok=False)
result=dict(job_id=os.environ['SLURM_JOB_ID'],host=socket.gethostname(),script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),cases=cases,scope='Read-only current failed-cell cache size and provenance; full input content omitted; no providers')
(out/'diagnosis.json').write_text(json.dumps(result,indent=2)+'\n')
for c in cases:print(c['assignment'],c['error'],[(r['stage'],r['evidence_bytes'],r['top_level_bytes']) for r in c['latest_requests']])
