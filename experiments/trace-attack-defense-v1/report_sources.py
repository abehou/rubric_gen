"""Read-only verification of frozen W/S/A/RH and native V2 static H records."""
import json,hashlib,os
from pathlib import Path
from collections import defaultdict
from statistics import mean
from prepare import ROOT,BUNDLE,RUN,V2

PANEL=('gpt-5.6-sol','claude-opus-5')
WINDOWS=('full_trajectory','post_update','final_artifact','final_revision')
POOL=Path('/data/user_data/aydanh/rubric_gen/pools/paraphrases/biomnibench/result20-prompt-nofallback-v2-20260910')
OUT=RUN/'report'
PUBLIC=ROOT/'docs/reports/2026-09-10/trace-attack-defense-v1'

def read(p):return json.loads(Path(p).read_text())
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def write(p,value):
 p.parent.mkdir(parents=True,exist_ok=True);p.write_text(json.dumps(value,indent=2,ensure_ascii=False)+'\n')

def verify_row(r,receipts):
 for field in ('state','score_composition'):
  p=Path(r[field+'_path']);assert sha(p)==r[field+'_sha256'],p
  receipts[str(p)]=sha(p)
 state=read(r['state_path']);ev=read(r['score_composition_path']);root=Path(r['state_path']).parent
 assert ev['score']==state['scores'][-1]==r['values']['W_train']
 assert ev['reference_score']==r['values']['W']
 ref=ev['feedback_reference'];w=root/'judgments'/r['submission_id']/ref['rubric_sha256']
 for filename,key in [('score_validation.json','score_validation_sha256'),('evaluation.json','evaluation_sha256')]:
  assert sha(w/filename)==ref[key];receipts[str(w/filename)]=sha(w/filename)
 assert read(w/'score_validation.json')['score']==r['values']['W']
 selected=read(r['rubric_paths'][0]);quality=read(r['quality_path'])
 assert selected['rubric_sha256']==r['selected_rubric_sha256']==ref['rubric_sha256']
 assert selected['model']==quality['model']==r['model']
 assert selected['submission_content_sha256']==quality['submission_content_sha256']==r['submission_sha256']
 assert selected['score']==r['values']['S'] and quality['verdict']['score']==r['values']['A']
 for field in ('task_instruction_sha256','answer_input_sha256','review_input_sha256'):
  # Native quality requests have their own public composition, so compare their
  # own recorded identity when present instead of imposing a different packing.
  assert field in selected
 for path in [r['rubric_paths'][0],r['quality_path']]:receipts[path]=sha(path)
 return selected

def add_v2(rows,condition,receipts):
 held=read(V2/condition/'heldout-records.json')
 rawpaths={str(read(p)['validation_path']):p for p in (V2/condition/'audit/records').glob('*.json')}
 lookup={}
 for record in held:
  assert record['artifact']=='final' and record['model'] in PANEL
  p=rawpaths[record['validation_path']];raw=read(p)
  assert raw['score']==record['score']
  for variant in record['variant_indices']:
   key=(record['assignment_id'],record['model'],variant)
   assert key not in lookup;lookup[key]=(raw,p)
 assert len(lookup)==360
 for r in rows:
  selected=verify_row(r,receipts);scores=[];paths=[]
  for variant in (2,3,4):
   raw,p=lookup[r['assignment_id'],r['model'],variant]
   assert raw['rubric_sha256']==sha(POOL/'tasks'/r['task_id']/f'variant-{variant:03d}.txt')
   for field in ('model','task_id','submission_content_sha256','task_instruction_sha256','answer_input_sha256','review_input_sha256','engine_release_identity','evaluation_implementation_sha256'):
    assert raw[field]==selected[field],(r['assignment_id'],variant,field)
   assert {k:v for k,v in raw['grading_identity'].items() if k!='rendered_rubric_sha256'}=={k:v for k,v in selected['grading_identity'].items() if k!='rendered_rubric_sha256'}
   val=read(raw['validation_path']);evaluation=read(raw['evaluation_path'])
   assert val['score']==evaluation['total_score']==raw['score']
   for field,value in raw['grading_identity'].items():assert val[field]==value
   for field in ('answer_input_sha256','review_input_sha256'):assert val[field]==raw[field]
   for path in (p,Path(raw['validation_path']),Path(raw['evaluation_path'])):receipts[str(path)]=sha(path)
   scores.append(raw['score']);paths.append(str(p))
  r['historical_old_pool_H']=r['values']['H']
  r['values']['H']=mean(scores);r['values']['SH']=r['values']['S']-r['values']['H'];r['values']['HA']=r['values']['H']-r['values']['A']
  r['heldout_values']=scores;r['V2_heldout_paths']=paths;r['heldout_pool']='canonical_v2'
 receipts[str(V2/condition/'heldout-records.json')]=sha(V2/condition/'heldout-records.json')

def main():
 assert os.environ.get('SLURM_JOB_ID'),'Compute storage must be inspected through Slurm'
 assert sha(POOL/'manifest.json')=='404d8cb9437c4f6d766c40a1c9fade066a0e53aab249c37fc63da990a68bc0e8'
 frozen=read(ROOT/'docs/reports/2026-09-09/baseline-freeze/results.json');cohorts=defaultdict(list);receipts={}
 for path,digest in frozen['provenance']['sources'].items():
  assert sha(path)==digest;receipts[path]=digest
  for r in read(path)['rows']:
   cid=r['condition_id'].split('/')[-1];label=None
   if 'report-v2' in path and cid=='full-static':label='static_full'
   elif 'cue-contrast' in path and cid=='user-simulator-static':label='static_user'
   elif 'cue-contrast' in path and cid=='user-simulator-red-team-trace':label='original_user'
   elif 'provisional59' in path and cid=='full-red-team-trace':label='original_full'
   if label:
    r['condition_id']=cid;r['cohort']=label;r['heldout_pool']='historical_old_pool'
    verify_row(r,receipts);cohorts[label].append(r)
 witness=Path('/data/user_data/aydanh/rubric_gen/runs/trace-repair-result20-20260909/report-v1/candidate-rows.json')
 assert sha(witness)=='aa02ff228a4a4ee1ee22b7636510be9efc316b142751b65673fada408c78abd9'
 receipts[str(witness)]=sha(witness)
 for r in read(witness):
  label='public_witness_user' if r['condition_id'].startswith('user') else 'public_witness_full'
  r.update(cohort=label,heldout_pool='historical_old_pool');verify_row(r,receipts);cohorts[label].append(r)
 for label,rows in cohorts.items():
  assert len(rows)==(118 if label=='original_full' else 120)
  bykey={(r['task_id'],r['replicate'],r['model']):r for r in rows};assert len(bykey)==len(rows)
  for r in rows:
   audit=Path(r['quality_path']).parents[2]
   # Full frozen official verdicts are checked at their actual native source.
   for window in WINDOWS:
    paths=list((audit/f'direct_{window}/evaluations').glob('*/summary.json'));assert len(paths)==1
    p=paths[0];receipts[str(p)]=sha(p)
    source=str(Path(r['state_path']).parent)
    record=next(x for x in read(p)['records'] if x['source_path']==source and x['model']==r['model'])
    assert record['verdict']==r['direct'][window]
 add_v2(cohorts['static_full'],'full-static',receipts);add_v2(cohorts['static_user'],'user-simulator-static',receipts)
 write(OUT/'frozen-cohorts.json',cohorts)
 write(PUBLIC/'frozen-source-receipts.json',{'provider_calls':0,'source_sha256':sha(__file__),'files':receipts,
  'V2_static_H_verified':True,'unchanged_W_S_A_RH':True,'counts':{k:len(v) for k,v in cohorts.items()}})
 print(json.dumps({'provider_calls':0,'counts':{k:len(v) for k,v in cohorts.items()},
  'static':{label:{**{m:mean(r['values'][m] for r in cohorts[label]) for m in ('W','S','H','A','WS','WA','SH','HA')},
   'RH':100*mean(r['direct']['full_trajectory']['decision']=='reward_hacking_detected' for r in cohorts[label])} for label in ('static_full','static_user')}}),flush=True)

if __name__=='__main__':main()
