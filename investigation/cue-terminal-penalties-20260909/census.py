from pathlib import Path
import json,hashlib,os
ROOT=Path('/home/aydanh/repos/rubric_gen')
b=ROOT/'runs/babel-result20-cue-contrast-20260908/trace/study/biomnibench-da-factorial-r10-f0203f5d69f3/experiments'
rows=[];hashes={}
def read(p):
 hashes[str(p)]=hashlib.sha256(p.read_bytes()).hexdigest();return json.loads(p.read_text())
for p in sorted(b.glob('*/rep-*/luna/user-simulator-red-team-trace/state.json')):
 st=read(p);d=p.parent;ss=st['submission_ids'];seq=[]
 for s in ss:
  ev=read(d/'rubric-evaluations'/f'{s}.json');seq.append(dict(submission=s,penalty=ev['elicited_penalty'],reference_score=ev['reference_score'],train_score=ev['score'],generation_round=ev['generation_round']))
 last=seq[-1];prev=seq[-2] if len(seq)>1 else None
 rows.append(dict(task=p.parents[3].name,replicate=p.parents[2].name,path=str(d),stop_reason=st['stop_reason'],sequence=seq,final_penalty=last['penalty']<0,previous_penalty=prev['penalty']<0 if prev else None,new_final_penalty=last['penalty']<0 and prev is not None and prev['penalty']==0))
assert len(rows)==60
out=ROOT/f'runs/cue-terminal-penalties-{os.environ["SLURM_JOB_ID"]}';out.mkdir(exist_ok=False)
value=dict(job_id=os.environ['SLURM_JOB_ID'],assignments=len(rows),final_penalties=sum(r['final_penalty'] for r in rows),new_final_penalties=sum(r['new_final_penalty'] for r in rows),rows=rows,source_hashes=hashes)
(out/'result.json').write_text(json.dumps(value,indent=2)+'\n')
print(json.dumps({k:v for k,v in value.items() if k not in ['rows','source_hashes']}))
