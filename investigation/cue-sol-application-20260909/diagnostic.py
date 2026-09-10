"""Frozen-candidate model-only application replay; no induction or revisions."""
from pathlib import Path
import dataclasses,hashlib,json,os,socket,sys,time
from concurrent.futures import ThreadPoolExecutor,as_completed
ROOT=Path('/home/aydanh/repos/rubric_gen');B=Path(__file__).parent
PREVIOUS=ROOT/'investigation/cue-sol-supervision-20260909'
sys.path.insert(0,str(PREVIOUS))
import diagnostic as previous
from sol_context import apply_sol
from context import ep,ea
from rubric_gen.submission_revision.evolution_provider import ProviderContract
from rubric_gen.submission_revision.evolution_validation import validate_independently,ValidationStageResult
from rubric_gen.submission_revision.evolution_serialization import canonical_json
from rubric_gen.runtime.capacity import policy
from dotenv import dotenv_values
SOURCE=Path('/data/user_data/aydanh/rubric_gen/runs/cue-sol-supervision-10377039')
read=previous.read;save=previous.save;sha=previous.sha

def prepare(row):
 ctx=apply_sol(previous.prepare(row));folder=SOURCE/f"{row['task']}-{row['replicate']}-sol_quality";saved=read(folder/'result.json');requests={};induction=None;source_files=[folder/'result.json']
 for p in sorted(folder.glob('calls/*/request.json')):
  req=read(p);outputs=sorted(p.parent.glob('output-*.json'));assert len(outputs)==1
  raw=read(outputs[0])['response_text'];source_files.extend([p,outputs[0]])
  if req['stage']=='induction':
   assert induction is None;induction=ep.validated_induction_response(raw,original_rubric=ctx['original'],current_generation=ctx['current'],generation_round=ctx['n'],level_labels=ep.required_level_labels(ctx['original']),induction_gaps=ctx['induction'])
  else:
   assert req['stage']=='validation';e=json.loads(req['evidence']);assert len(e['artifacts'])==1;aid=e['artifacts'][0]['artifact_id'];assert aid not in requests;requests[aid]=(req,raw)
 assert induction and [c.as_dict() for c in induction]==saved['candidates']
 assert set(requests)==set(ctx['artifact_ids'])
 ctx.update(cs=induction,requests=requests,saved=saved,source_files=source_files)
 return ctx

def evaluate(ctx,stage):
 cs=ctx['cs'];payload={**ctx['template'],'candidates':[{'criterion':ep._validation_criterion_record(c.criterion),'replaces':list(c.replaces)} for c in cs],'artifacts':[ctx['artifacts'][a] for a in ctx['artifact_ids']]}
 fallback=canonical_json({'validations':[dict(criterion_id=c.criterion.criterion_id,observable=False,nonredundant=False,reason='Incomplete independent validation',artifact_applications=[dict(artifact_id=a,level=c.criterion.levels[0][0],reason='Incomplete independent validation') for a in ctx['artifact_ids']]) for c in cs]})
 def checked_stage(**kw):
  aid=json.loads(kw['evidence'])['artifacts'][0]['artifact_id'];req,raw=ctx['requests'][aid]
  assert kw['stage']==req['stage'] and kw['evidence']==req['evidence'] and kw['response_schema']==req['schema'] and req['instructions']==ep.validation_instructions()
  return stage(aid,req,raw,kw['validator'])
 v=validate_independently(stage=checked_stage,candidates=cs,artifact_ids=ctx['artifact_ids'],evidence=canonical_json(payload),fallback_text=fallback)
 assert v.fallback_reason is None
 accepted,decisions=ep.admit_candidates(cs,v.value,ctx['pairs'],ctx['current'])
 return dict(task=ctx['row']['task'],replicate=ctx['row']['replicate'],proposed=len(cs),accepted=len(accepted),candidates=[c.as_dict() for c in cs],decisions=[dataclasses.asdict(d) for d in decisions],validations=json.loads(v.raw_text))

def execute(ctx,arm,out):
 folder=out/f"{ctx['row']['task']}-{ctx['row']['replicate']}-{arm}";folder.mkdir(exist_ok=False)
 expected=ctx['row']['provider_contract'];record={**expected,'model':'gpt-5.6-sol' if arm=='sol_application' else 'gpt-5.6-luna'};contract=ProviderContract(**{k:record[k] for k in ['model','max_output_tokens','max_request_bytes','service_tier']});assert contract.record()==record
 def stage(aid,req,raw,validator):
  assert req['contract']==expected
  dest=folder/aid;dest.mkdir();save(dest/'request.json',{**req,'contract':record})
  for attempt in range(1,4):
   try:
    output=contract.generate(instructions=req['instructions'],evidence=req['evidence'],response_schema=req['schema'],request_context='cue-sol-application-diagnostic',schema_name='rubric_validation')
    save(dest/f'output-{attempt}.json',dataclasses.asdict(output));contract.validate_output(output);value=validator(output.response_text)
    return ValidationStageResult(output.response_text,value,attempt)
   except Exception as e:
    status=getattr(e,'status_code',None);save(dest/f'failure-{attempt}.json',dict(error_type=type(e).__name__,status_code=status,message=str(e)[:500]))
    if attempt==3 or status in {400,401,403,404,422}:raise
    time.sleep(2**attempt)
 result={**evaluate(ctx,stage),'arm':arm,'model':record['model']};save(folder/'result.json',result);return result

def main():
 assert os.environ.get('SLURM_JOB_ID');mode=sys.argv[1];assert mode in {'validate','run'}
 source=read(SOURCE/'result.json');assert source['success'] and len(source['results'])==18 and source['source_unchanged']
 contexts=[prepare(row) for row in read(PREVIOUS/'inputs.json')['rows']]
 for ctx in contexts:
  replay=evaluate(ctx,lambda aid,req,raw,validator:ValidationStageResult(raw,validator(raw),1))
  for k in ['proposed','accepted','candidates','decisions','validations']:assert canonical_json(replay[k])==canonical_json(ctx['saved'][k]),k
 code=previous.CODE;files=[*code.joinpath('src').rglob('*.py'),code/'config/runtime.json',code/'uv.lock',*PREVIOUS.glob('*.py'),PREVIOUS/'inputs.json',*B.glob('*.py'),SOURCE/'result.json']
 files.extend(p for ctx in contexts for p in ctx['source_files'])
 files.extend(Path('/data/user_data/aydanh/rubric_gen/runs/cue-pair-attribution-20260909/sol-gap-impact-v1')/f"context-{c['row']['context']:02d}.json" for c in contexts)
 identity={str(p):sha(p) for p in files};count=sum(len(c['artifact_ids']) for c in contexts)*2
 if mode=='validate':save(B/'acceptance.json',dict(success=True,job_id=os.environ['SLURM_JOB_ID'],contexts=len(contexts),calls=count,source_hashes=identity));print('native replay passed',len(contexts),'contexts; planned calls',count);return
 acceptance=read(B/'acceptance.json');assert acceptance['success'] and acceptance['source_hashes']==identity
 settings=policy();assert settings['aggregate_concurrency']==60
 out=Path('/data/user_data/aydanh/rubric_gen/runs')/f"cue-sol-application-{os.environ['SLURM_JOB_ID']}";out.mkdir(exist_ok=False)
 save(out/'launch.json',dict(job_id=os.environ['SLURM_JOB_ID'],hostname=socket.gethostname(),command=sys.argv,source_hashes=identity,expected_cells=18,expected_calls=count,policy=settings,cell_workers=4,maximum_native_application_workers_per_cell=4,cpus=int(os.environ['SLURM_CPUS_PER_TASK']),memory_mib=int(os.environ['SLURM_MEM_PER_NODE']),scope='Frozen-candidate independent application model only'))
 key=dotenv_values(ROOT/'.env.local').get('OPENAI_API_KEY');assert key;os.environ['OPENAI_API_KEY']=key
 results=[];failures=[];start=time.monotonic()
 with ThreadPoolExecutor(max_workers=4) as pool:
  futures={pool.submit(execute,c,a,out):(c,a) for c in contexts for a in ['control','sol_application']}
  for future in as_completed(futures):
   ctx,arm=futures[future]
   try:results.append(future.result())
   except Exception as e:failures.append(dict(task=ctx['row']['task'],replicate=ctx['row']['replicate'],arm=arm,error_type=type(e).__name__,message=str(e)[:500]))
   print('complete',len(results),'invalid',len(failures),flush=True)
 assert all(sha(p)==h for p,h in identity.items())
 summary=dict(success=not failures,source_unchanged=True,job_id=os.environ['SLURM_JOB_ID'],output=str(out),elapsed_seconds=time.monotonic()-start,results=results,failures=failures)
 save(out/'result.json',summary)
 if failures:raise SystemExit(1)
if __name__=='__main__':main()
