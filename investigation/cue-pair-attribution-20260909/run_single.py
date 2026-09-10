"""Matched stage-only diagnostic; inputs must pass provider-free preparation."""
import dataclasses,hashlib,json,os,socket,time
from concurrent.futures import ThreadPoolExecutor,as_completed
from pathlib import Path
from dotenv import dotenv_values
from transforms import preferred_ids
from rubric_gen.submission_revision.evolution_provider import ProviderContract
from rubric_gen.runtime.capacity import policy
assert os.environ.get('SLURM_JOB_ID')
ROOT=Path('/home/aydanh/repos/rubric_gen');BASE=Path('/data/user_data/aydanh/rubric_gen/runs/cue-pair-attribution-20260909');INPUT=BASE/'single-pair-inputs-v1'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,x):
 with p.open('x') as f:json.dump(x,f,indent=2)
a=read(INPUT/'acceptance.json');assert a['success'] and a['calls']==20
jobs=[]
for r in a['requests']:
 p=Path(r['path']);assert sha(p)==r['sha256'];x=read(p)
 assert sha(Path(x['source_cache']))==x['source_sha256']
 for cell in x['cells']:
  contract=ProviderContract(**{k:cell['contract'][k] for k in ['model','max_output_tokens','max_request_bytes','service_tier']})
  assert contract.record()==cell['contract'];jobs.append((x,cell,contract))
settings=policy();assert settings['aggregate_concurrency']==60
out=BASE/f"single-calls-{os.environ['SLURM_JOB_ID']}";out.mkdir(exist_ok=False)
code=ROOT/'runs/babel-code/result20-cue-original-audit'
identity={str(p):sha(p) for p in [*code.joinpath('src').rglob('*.py'),code/'config/runtime.json',Path(__file__),Path(__file__).with_name('transforms.py')]}
save(out/'launch.json',dict(job_id=os.environ['SLURM_JOB_ID'],hostname=socket.gethostname(),policy=settings,local_workers=4,source_hashes=identity,input_receipt_sha256=sha(INPUT/'acceptance.json'),cpus=1,memory='4G',scope='Induction pair-assessment only; no revision or outcome audits'))
key=dotenv_values(ROOT/'.env.local').get('OPENAI_API_KEY');assert key;os.environ['OPENAI_API_KEY']=key
start=time.monotonic()
def execute(x,cell,contract):
 folder=out/f"context-{x['context']:02d}-{cell['arm']}-{cell['order']}";folder.mkdir(exist_ok=False);save(folder/'request.json',cell)
 for attempt in range(1,4):
  try:
   result=contract.generate(instructions=cell['instructions'],evidence=cell['evidence'],response_schema=cell['schema'],request_context='cue-single-pair-diagnostic',schema_name='rubric_assessment_rubric_free')
   save(folder/f'output-{attempt}.json',dataclasses.asdict(result));contract.validate_output(result)
   response=json.loads(result.response_text);prefs=preferred_ids(cell['evidence'],response)
   record=dict(context=x['context'],arm=cell['arm'],order=cell['order'],preferences=prefs,attempts=attempt,output=str(folder),discovery_anchor=x['discovery_anchor'])
   save(folder/'result.json',record);return record
  except Exception as e:
   status=getattr(e,'status_code',None);save(folder/f'failure-{attempt}.json',dict(error_type=type(e).__name__,status_code=status))
   if attempt==3 or status in {400,401,403,404,422}:raise
   time.sleep(2**attempt)
results=[];failures=[]
with ThreadPoolExecutor(max_workers=4) as pool:
 futures={pool.submit(execute,*j):j for j in jobs}
 for f in as_completed(futures):
  x,c,_=futures[f]
  try:results.append(f.result())
  except Exception as e:failures.append(dict(context=x['context'],arm=c['arm'],order=c['order'],error_type=type(e).__name__))
  print('finished',len(results),'failed',len(failures),flush=True)
assert all(sha(Path(p))==h for p,h in identity.items())
summary=dict(success=not failures,job_id=os.environ['SLURM_JOB_ID'],elapsed_seconds=time.monotonic()-start,results=results,failures=failures,output=str(out))
save(out/'result.json',summary);save(ROOT/f"docs/reports/2026-09-09/cue-pair-attribution-{os.environ['SLURM_JOB_ID']}.json",summary)
if failures:raise SystemExit(1)
