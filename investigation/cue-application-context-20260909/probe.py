"""Fixed criterion-application context diagnostic; no admission or outcome scoring."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import dataclasses,hashlib,json,os,socket,sys,time
from dotenv import dotenv_values
from rubric_gen.submission_revision.evolution_provider import ProviderContract
from rubric_gen.submission_revision.evolution_serialization import canonical_json
from rubric_gen.runtime.capacity import policy
ROOT=Path('/home/aydanh/repos/rubric_gen');B=Path(__file__).parent;SOURCE=ROOT/'runs/cue-validation-repeat-10370858';CODE=ROOT/'runs/babel-code/result20-cue-contrast'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def save(p,x):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x') as f:json.dump(x,f,indent=2);f.write('\n')
def sources():
 assert read(SOURCE/'result.json')['success']
 rows=[]
 for p in sorted(SOURCE.glob('*/calls/*/request.json')):
  x=read(p);assert x['stage']=='validation'
  ev=json.loads(x['evidence']);assert len(ev['artifacts'])==1 and ev['current_rubric']
  assert set(ev)=={'task','current_rubric','current_active_criteria','candidates','artifacts'}
  rows.append((p,x,ev))
 assert len(rows)==44 and len({p.parents[2].name for p,_,_ in rows})==4
 return rows

def main():
 assert os.environ.get('SLURM_JOB_ID');mode=sys.argv[1];assert mode in {'validate','run'}
 rows=sources();files=[*CODE.joinpath('src').rglob('*.py'),CODE/'uv.lock',CODE/'config/runtime.json',Path(__file__),SOURCE/'result.json',*[p for p,_,_ in rows]];identity={str(p):sha(p) for p in files}
 for p,x,ev in rows:
  control=canonical_json(ev);assert control==x['evidence']
  changed={k:v for k,v in ev.items() if k!='current_rubric'}
  assert len(changed)==len(ev)-1 and all(changed[k]==ev[k] for k in changed)
 if mode=='validate':save(B/'acceptance.json',dict(success=True,job_id=os.environ['SLURM_JOB_ID'],source_hashes=identity,requests=len(rows),sole_difference='current_rubric field omitted in isolated arm'));print('44 exact saved validation requests verified');return
 a=read(B/'acceptance.json');assert a['source_hashes']==identity
 out=ROOT/f"runs/cue-application-context-{os.environ['SLURM_JOB_ID']}";out.mkdir(exist_ok=False)
 save(out/'launch.json',dict(job_id=os.environ['SLURM_JOB_ID'],hostname=socket.gethostname(),source_hashes=identity,policy=policy(),resources=dict(cpus=4,memory='8G',partition='preempt',qos='preempt_cpu_qos',account=None),scope='Only criterion levels/reasons are interpretable in isolated arm; no semantic/admission/outcome claims'))
 key=dotenv_values(ROOT/'.env.local').get('OPENAI_API_KEY');assert key;os.environ['OPENAI_API_KEY']=key
 def execute(p,x,ev,arm):
  folder=out/p.parents[2].name/p.parent.name/arm;folder.mkdir(parents=True,exist_ok=False)
  evidence=x['evidence'] if arm=='control' else canonical_json({k:v for k,v in ev.items() if k!='current_rubric'})
  contract=ProviderContract(**{k:x['contract'][k] for k in ['model','max_output_tokens','max_request_bytes','service_tier']});assert contract.record()==x['contract']
  save(folder/'request.json',{**x,'evidence':evidence,'source_request':str(p),'source_sha256':sha(p),'arm':arm})
  for attempt in range(1,4):
   try:
    r=contract.generate(instructions=x['instructions'],evidence=evidence,response_schema=x['schema'],request_context='cue-application-context-diagnostic',schema_name='rubric_validation');contract.validate_output(r);save(folder/f'output-{attempt}.json',dataclasses.asdict(r));v=json.loads(r.response_text)
    expected=[c['criterion']['criterion_id'] for c in ev['candidates']];assert [c['criterion_id'] for c in v['validations']]==expected
    for c in v['validations']:
     assert len(c['artifact_applications'])==1 and c['artifact_applications'][0]['artifact_id']==ev['artifacts'][0]['artifact_id']
     candidate=next(t['criterion'] for t in ev['candidates'] if t['criterion']['criterion_id']==c['criterion_id']);assert c['artifact_applications'][0]['level'] in [t['label'] for t in candidate['levels']]
    value=dict(source_request=str(p),arm=arm,context=p.parents[2].name,verdict=v,attempts=attempt);save(folder/'result.json',value);return value
   except Exception as e:
    save(folder/f'failure-{attempt}.json',dict(error_type=type(e).__name__,message=str(e)[:1000]))
    if attempt==3 or getattr(e,'status_code',None) in {401,403}:raise
    time.sleep(2**attempt)
 jobs=[(p,x,ev,arm) for p,x,ev in rows for arm in ['control','isolated']];results=[];failures=[]
 with ThreadPoolExecutor(max_workers=16) as pool:
  futures=[pool.submit(execute,*j) for j in jobs]
  for job,f in zip(jobs,futures,strict=True):
   try:results.append(f.result())
   except Exception as e:failures.append(dict(source=str(job[0]),arm=job[3],error_type=type(e).__name__,message=str(e)[:1000]))
 assert all(sha(p)==h for p,h in identity.items())
 save(out/'result.json',dict(success=not failures,source_unchanged=True,results=results,failures=failures));print('completed',len(results),'failed',len(failures))
 if failures:raise SystemExit(1)
if __name__=='__main__':main()
