"""Private saved-input proposer experiment; never revise or alter source evidence."""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import dataclasses,hashlib,json,os,socket,sys,time
from dotenv import dotenv_values
from context import load_context,ep,ea
from rubric_gen.submission_revision.evolution_provider import ProviderContract
from rubric_gen.submission_revision.evolution_validation import validate_independently,ValidationStageResult
from rubric_gen.submission_revision.evolution_serialization import canonical_json
from rubric_gen.runtime.capacity import policy
ROOT=Path('/home/aydanh/repos/rubric_gen');B=Path(__file__).parent;CODE=ROOT/'runs/babel-code/result20-cue-original-audit'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def read(p):return json.loads(Path(p).read_text())
def save(p,d):
 p=Path(p);p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x') as f:json.dump(d,f,indent=2);f.write('\n')
def prepare(row):
 assert sha(row['original_request_record'])==row['request_record_sha256']
 ctx=load_context({'path':row['generation']});record=read(row['original_request_record']);req=record['request'];assert req['stage']=='induction'
 assert record['identity']['context']['generation_round']==ctx['n'] and ctx['n']>=1
 artifacts={};template=None
 for p in (ctx['g'].parents[1]/'rubric-proposer-records').glob('*.json'):
  d=read(p)
  if d['identity']['context']['generation_round']!=ctx['n'] or d['request']['stage']!='validation':continue
  v=json.loads(d['request']['evidence'])
  base={k:x for k,x in v.items() if k!='artifacts'}
  if template is None:template=base
  assert template==base
  for a in v['artifacts']:
   if a['artifact_id'] in artifacts:assert artifacts[a['artifact_id']]==a
   artifacts[a['artifact_id']]=a
 ids=ea.validation_artifact_ids(ctx['pairs']);assert set(ids)==set(artifacts)
 assert template['current_rubric']==ctx['current'].rubric.content
 assert template['task']==json.loads(req['evidence'])['task']
 ctx.update(request=req,template=template,artifacts=artifacts,artifact_ids=ids,row=row)
 return ctx
def run_cell(ctx,arm,out):
 dest=out/f"{ctx['row']['task']}-{ctx['row']['replicate']}-{arm}";dest.mkdir(exist_ok=False)
 contract=ProviderContract(**{k:ctx['row']['provider_contract'][k] for k in ['model','max_output_tokens','max_request_bytes','service_tier']})
 assert contract.record()==ctx['row']['provider_contract']
 def call(stage,evidence,schema,instructions,validator):
  key=hashlib.sha256(canonical_json(dict(stage=stage,evidence=evidence,schema=schema,instructions=instructions,contract=contract.record())).encode()).hexdigest();folder=dest/'calls'/key;folder.mkdir(parents=True,exist_ok=False)
  save(folder/'request.json',dict(stage=stage,evidence=evidence,schema=schema,instructions=instructions,contract=contract.record()))
  for attempt in range(1,4):
   try:
    result=contract.generate(instructions=instructions,evidence=evidence,response_schema=schema,request_context='cue-atomic-criterion-'+stage,schema_name='rubric_'+stage)
    contract.validate_output(result);save(folder/f'output-{attempt}.json',dataclasses.asdict(result));value=validator(result.response_text)
    return ValidationStageResult(result.response_text,value,attempt)
   except Exception as e:
    save(folder/f'failure-{attempt}.json',dict(error_type=type(e).__name__,message=str(e)[:1000]))
    if attempt==3 or getattr(e,'status_code',None) in {401,403}:raise
    time.sleep(2**attempt)
 def parse(text):return ep.validated_induction_response(text,original_rubric=ctx['original'],current_generation=ctx['current'],generation_round=ctx['n'],level_labels=ep.required_level_labels(ctx['original']),induction_gaps=ctx['induction'])
 instructions=ep.induction_instructions()
 if arm=='atomic':instructions+='\n'+(B/'clarification.txt').read_text()
 r=call('induction',ctx['request']['evidence'],ctx['request']['response_schema'],instructions,parse);cs=r.value
 if not cs:
  result=dict(task=ctx['row']['task'],replicate=ctx['row']['replicate'],arm=arm,status='completed',proposed=0,accepted=0,decisions=[],note='no criterion proposed; not behavioral exposure')
 else:
  payload={**ctx['template'],'candidates':[{'criterion':ep._validation_criterion_record(c.criterion),'replaces':list(c.replaces)} for c in cs],'artifacts':[ctx['artifacts'][a] for a in ctx['artifact_ids']]}
  fallback=canonical_json({'validations':[dict(criterion_id=c.criterion.criterion_id,observable=False,nonredundant=False,reason='Incomplete independent validation',artifact_applications=[dict(artifact_id=a,level=c.criterion.levels[0][0],reason='Incomplete independent validation') for a in ctx['artifact_ids']]) for c in cs]})
  def stage(**kw):return call(kw['stage'],kw['evidence'],kw['response_schema'],ep.validation_instructions(),kw['validator'])
  validated=validate_independently(stage=stage,candidates=cs,artifact_ids=ctx['artifact_ids'],evidence=canonical_json(payload),fallback_text=fallback)
  assert validated.fallback_reason is None
  admitted,decisions=ep.admit_candidates(cs,validated.value,ctx['pairs'],ctx['current'])
  result=dict(task=ctx['row']['task'],replicate=ctx['row']['replicate'],arm=arm,status='completed',proposed=len(cs),accepted=len(admitted),candidates=[c.as_dict() for c in cs],decisions=[dataclasses.asdict(d) for d in decisions],validations=json.loads(validated.raw_text))
 save(dest/'result.json',result);return result

def main():
 assert os.environ.get('SLURM_JOB_ID'),'Slurm required'
 mode=sys.argv[1];assert mode in {'validate','run'}
 inputs=read(B/'inputs.json');contexts=[prepare(r) for r in inputs['rows']]
 files=[*CODE.joinpath('src').rglob('*.py'),CODE/'uv.lock',CODE/'config/runtime.json',B/'inputs.json',B/'context.py',B/'diagnostic.py',B/'clarification.txt']
 identity={str(p):sha(p) for p in files}
 if mode=='validate':
  save(B/'acceptance-v2.json',dict(success=True,job_id=os.environ['SLURM_JOB_ID'],source_hashes=identity,cases=[dict(task=c['row']['task'],artifacts=len(c['artifact_ids'])) for c in contexts]));print('Saved source/native-control validation passed');return
 acceptance=read(B/'acceptance-v2.json');assert acceptance['success'] and acceptance['source_hashes']==identity
 out=Path("/data/user_data/aydanh/rubric_gen/runs")/f"cue-atomic-criterion-{os.environ['SLURM_JOB_ID']}";out.mkdir(exist_ok=False)
 save(out/'launch.json',dict(job_id=os.environ['SLURM_JOB_ID'],hostname=socket.gethostname(),command=sys.argv,source_hashes=identity,policy=policy(),resources=dict(cpus=int(os.environ['SLURM_CPUS_PER_TASK']),memory_mib=int(os.environ['SLURM_MEM_PER_NODE']),partition='preempt',qos='preempt_cpu_qos',account=None),scope=inputs['scope']))
 key=dotenv_values(ROOT/'.env.local').get('OPENAI_API_KEY');assert key;os.environ['OPENAI_API_KEY']=key
 jobs=[(c,a) for c in contexts for a in ['control','atomic']];results=[];failures=[]
 with ThreadPoolExecutor(max_workers=4) as pool:
  futures=[pool.submit(run_cell,c,a,out) for c,a in jobs]
  for (c,a),f in zip(jobs,futures,strict=True):
   try:results.append(f.result())
   except Exception as e:failures.append(dict(task=c['row']['task'],arm=a,error_type=type(e).__name__,message=str(e)[:1000]))
 assert all(sha(p)==h for p,h in identity.items())
 save(out/'result.json',dict(success=not failures,results=results,failures=failures,source_unchanged=True));print('completed cells',len(results),'invalid cells',len(failures))
 if failures:raise SystemExit(1)
if __name__=='__main__':main()
