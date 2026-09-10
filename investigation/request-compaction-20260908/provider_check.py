"""One matched pair of request-format calibration calls; not scientific outcomes."""
import hashlib,json,os,subprocess,time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from dotenv import dotenv_values
import jsonschema
from rubric_gen.submission_revision.evolution_assessment import assessment_instructions,AssessmentView
from rubric_gen.submission_revision.evolution_provider import ProviderContract
from rubric_gen.submission_revision.evolution_serialization import canonical_json
root=Path.cwd(); out=root/f'runs/request-compaction-provider-{os.environ["SLURM_JOB_ID"]}';out.mkdir(exist_ok=False)
source={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (root/'src').rglob('*.py')}
key=dotenv_values(root/'.env.local').get('OPENAI_API_KEY');assert key,'missing configured key';os.environ['OPENAI_API_KEY']=key
candidates=[]
for p in (root/'runs/babel-result20-capacity-v3-20260908/user-trace/study').glob('*/experiments/da-16-1/rep-001/luna/*/rubric-proposer-records/*.json'):
 v=json.loads(p.read_text());r=v['request']
 if r['stage']!='assessment_development_rubric':continue
 try:payload=json.loads(r['evidence'])
 except json.JSONDecodeError:continue
 if 'pairs' in payload and 'artifacts' not in payload:candidates.append((len(r['evidence'].encode()),str(p),v,payload))
_,name,v,payload=max(candidates,key=lambda x:(x[0],x[1])); original=v['request']['evidence'];table={};compact=json.loads(json.dumps(payload))
for pair in compact['pairs']:
 for side in ['artifact_A','artifact_B']:
  record=pair[side];aid=record['artifact_id'];assert aid not in table or table[aid]==record;table[aid]=record;pair[side]={'artifact_id':aid}
compact['artifacts']=[table[x] for x in sorted(table)]
for old,new in zip(payload['pairs'],compact['pairs'],strict=True):
 assert {**new,'artifact_A':table[new['artifact_A']['artifact_id']],'artifact_B':table[new['artifact_B']['artifact_id']]}==old
new_instruction=assessment_instructions(AssessmentView.DEVELOPMENT_RUBRIC)
old_instruction=new_instruction.replace('The artifacts table contains each complete artifact once; artifact_A and artifact_B\nreference that table by artifact_id.\n','')
params=v['output']['generation']['request_parameters'];model=v['output']['generation']['requested_model'];assert model=='gpt-5.6-luna'
contract=ProviderContract(model=model,max_output_tokens=65536,max_request_bytes=4*1024*1024,service_tier=params.get('service_tier'))
metadata=dict(job=os.environ['SLURM_JOB_ID'],source_commit=subprocess.check_output(['git','rev-parse','HEAD'],text=True).strip(),source_hashes=source,input=name,input_sha256=hashlib.sha256(Path(name).read_bytes()).hexdigest(),contract=contract.record(),purpose='Two concurrent diagnostic calls, original versus deduplicated format; schema validity only, not scientific acceptance or statistically established speedup.')
(out/'launch.json').write_text(json.dumps(metadata,indent=2)+'\n')
def run(args):
 label,instructions,evidence=args;start=time.monotonic();record=dict(label=label,evidence_bytes=len(evidence.encode()))
 try:
  response=contract.generate(instructions=instructions,evidence=evidence,response_schema=v['request']['response_schema'],request_context='request compaction calibration',schema_name='rubric_assessment_development_rubric')
  value=json.loads(response.response_text);jsonschema.validate(value,v['request']['response_schema'])
  record.update(success=True,generation=response.generation,response_sha256=hashlib.sha256(response.response_text.encode()).hexdigest())
 except Exception as exc:record.update(success=False,error_class=type(exc).__name__,http_status=getattr(exc,'status_code',None))
 record['seconds']=time.monotonic()-start;(out/f'{label}.json').write_text(json.dumps(record,indent=2)+'\n');return record
with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(run,[('original',old_instruction,original),('compact',new_instruction,canonical_json(compact))]))
unchanged=all(hashlib.sha256(Path(p).read_bytes()).hexdigest()==h for p,h in source.items())
(out/'result.json').write_text(json.dumps(dict(results=results,source_unchanged=unchanged),indent=2)+'\n')
print(json.dumps(dict(results=[{k:r[k] for k in ['label','success','evidence_bytes','seconds']} for r in results],source_unchanged=unchanged)))
