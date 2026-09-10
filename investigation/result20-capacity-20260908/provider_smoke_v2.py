"""Five provider calls for runtime acceptance only; excluded from scientific outcomes."""
import hashlib,json,os,socket,time
from pathlib import Path
from dataclasses import asdict
from concurrent.futures import ThreadPoolExecutor
from dotenv import dotenv_values
from jsonschema import validate
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.evolution import RubricProposer
from rubric_gen.runtime.capacity import policy
ROOT=Path('/home/aydanh/repos/rubric_gen')
accept=ROOT/'runs/babel-result20-capacity-20260908/input-validation-10358770/result.json'
assert json.loads(accept.read_text())['success'] is True
secrets=dotenv_values(ROOT/'.env.local');assert secrets.get('OPENAI_API_KEY');os.environ['OPENAI_API_KEY']=secrets['OPENAI_API_KEY'];del secrets
out=ROOT/f'runs/babel-result20-capacity-20260908/provider-smoke-{os.environ["SLURM_JOB_ID"]}';out.mkdir(parents=True,exist_ok=False)
diagnostic=json.loads((ROOT/'runs/babel-result20-current-20260908/input-capacity-diagnostic-10358661/diagnosis.json').read_text())
records=diagnostic['cases'][0]['latest_requests'];short=sorted([r for r in records if r['stage']=='validation'],key=lambda r:r['evidence_bytes'])[:4]
large=max([r for r in records if r['stage'].startswith('assessment')],key=lambda r:r['evidence_bytes'])
proposer=RubricProposer(benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,model='gpt-5.6-luna',max_retries=0)
assert proposer.proposer_contract.max_request_bytes==4*1024*1024
started=time.time()
def run(item,padded=False):
 p=Path(item['path']);raw=p.read_bytes();assert hashlib.sha256(raw).hexdigest()==item['sha256'];request=json.loads(raw)['request'];original=request['evidence']
 if padded:
  # JSON trailing whitespace leaves decoded scientific input unchanged. This
  # explicitly labelled transport test is never a scientific measurement.
  request['evidence'] += ' ' * max(0,1150000-len(original.encode()))
  assert json.loads(original)==json.loads(request['evidence'])
 t=time.time();name=('large-' if padded else 'validation-')+p.stem
 try:
  response=proposer.run_proposer(**request);proposer.proposer_contract.validate_output(response)
  value=json.loads(response.response_text);validate(value,request['response_schema'])
  (out/(name+'.json')).write_text(json.dumps(asdict(response),indent=2)+'\n')
  return dict(success=True,stage=request['stage'],seconds=time.time()-t,input_bytes=len(request['evidence'].encode()),source_sha256=item['sha256'],response_file=name+'.json',effective_model=response.generation['effective_model'],padded_transport_probe=padded)
 except Exception as e:
  return dict(success=False,error_type=type(e).__name__,http_status=getattr(e,'status_code',None),seconds=time.time()-t,stage=request['stage'],padded_transport_probe=padded)
with ThreadPoolExecutor(max_workers=4) as pool:results=list(pool.map(run,short))
if all(r['success'] for r in results):results.append(run(large,True))
result=dict(success=len(results)==5 and all(r['success'] for r in results),calls=results,job=os.environ['SLURM_JOB_ID'],host=socket.gethostname(),elapsed_seconds=time.time()-started,policy=policy(),contract=proposer.proposer_contract.record(),scope='Runtime diagnostic only:4 concurrent isolated validation requests and1 oversized equivalent-JSON assessment;not included in RH or outcome data',script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
(out/'result.json').write_text(json.dumps(result,indent=2)+'\n');print(json.dumps(result));raise SystemExit(0 if result['success'] else 1)
