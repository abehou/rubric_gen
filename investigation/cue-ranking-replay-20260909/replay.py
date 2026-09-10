from pathlib import Path
import sys,json,os,hashlib
from dataclasses import replace
ROOT=Path('/home/aydanh/repos/rubric_gen')
sys.path.insert(0,str(ROOT/'investigation/cue-citation-diagnostic-20260909'))
from context import load_context,ep
original=ep._aggregate_margin_checks

def revised(**kwargs):
 checks=original(**kwargs)
 return tuple(replace(c,passed=c.passed or (not c.strict_improvement_required and c.current_margin>0 and c.prospective_margin>0)) for c in checks)

def main():
 assert os.environ.get('SLURM_JOB_ID')
 src=ROOT/'docs/reports/2026-09-09/cue-margin-failure-screen.json';data=json.loads(src.read_text());paths=sorted({r['path'] for r in data['rows']});rows=[]
 for path in paths:
  ep._aggregate_margin_checks=original
  x=load_context({'path':path}) # reproduces saved original decisions and hashes
  olda,oldd=ep.admit_candidates(x['candidates'],x['validations'],x['pairs'],x['current'])
  ep._aggregate_margin_checks=revised
  newa,newd=ep.admit_candidates(x['candidates'],x['validations'],x['pairs'],x['current'])
  for old,new in zip(oldd,newd,strict=True):
   for c in new.margin_checks:
    if c.passed:
     assert c.prospective_margin>c.current_margin if c.strict_improvement_required else (c.prospective_margin>=c.current_margin or c.current_margin>0 and c.prospective_margin>0)
   rows.append(dict(path=path,old=old.as_dict(),new=new.as_dict()))
 ep._aggregate_margin_checks=original
 out=ROOT/f'runs/cue-ranking-replay-{os.environ["SLURM_JOB_ID"]}';out.mkdir(exist_ok=False)
 payload=dict(job_id=os.environ['SLURM_JOB_ID'],source_sha256=hashlib.sha256(src.read_bytes()).hexdigest(),script_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),generations=len(paths),rows=rows)
 (out/'result.json').write_text(json.dumps(payload,indent=2)+'\n');print('generations',len(paths),'decisions',len(rows),'changed',sum(r['old']!=r['new'] for r in rows))
if __name__=='__main__':main()
