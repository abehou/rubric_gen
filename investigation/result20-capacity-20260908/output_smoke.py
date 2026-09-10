"""One non-scientific request to validate the configured larger output allowance."""
import hashlib,json,os,socket,time
from pathlib import Path
from dataclasses import asdict
from dotenv import dotenv_values
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.evolution import RubricProposer
ROOT=Path('/home/aydanh/repos/rubric_gen')
accept=ROOT/'runs/babel-result20-capacity-v3-20260908/input-validation-10358949/result.json';assert json.loads(accept.read_text())['success'] is True
secrets=dotenv_values(ROOT/'.env.local');assert secrets.get('OPENAI_API_KEY');os.environ['OPENAI_API_KEY']=secrets['OPENAI_API_KEY'];del secrets
p=RubricProposer(benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,model='gpt-5.6-luna',max_retries=0);c=p.proposer_contract;assert c.max_output_tokens==65536 and c.max_request_bytes==4194304
out=ROOT/f'runs/babel-result20-capacity-v3-20260908/output-smoke-{os.environ["SLURM_JOB_ID"]}';out.mkdir(parents=True,exist_ok=False);start=time.time()
r=dict(success=False,job=os.environ['SLURM_JOB_ID'],host=socket.gethostname(),contract=c.record(),scope='Single non-scientific output-capacity acceptance;no benchmark payload;excluded from outcomes',script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
try:
 response=c.generate(instructions='For this runtime check, return the required JSON with runtime_ok set to true.',evidence='Runtime check only.',response_schema={'type':'object','properties':{'runtime_ok':{'type':'boolean'}},'required':['runtime_ok'],'additionalProperties':False},request_context='authorized runtime output-capacity check',schema_name='runtime_capacity')
 c.validate_output(response);assert json.loads(response.response_text)=={'runtime_ok':True};assert response.generation['request_parameters']['max_output_tokens']==65536
 (out/'response.json').write_text(json.dumps(asdict(response),indent=2)+'\n');r.update(success=True,effective_model=response.generation['effective_model'])
except Exception as e:r.update(error_type=type(e).__name__,http_status=getattr(e,'status_code',None))
r['seconds']=time.time()-start;(out/'result.json').write_text(json.dumps(r,indent=2)+'\n');print(json.dumps(r));raise SystemExit(0 if r['success'] else 1)
