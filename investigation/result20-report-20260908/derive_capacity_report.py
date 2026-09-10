"""Render the validated four-condition comparison and descriptive exposure reports."""
import hashlib,json,os,socket,subprocess,sys
from pathlib import Path
ROOT=Path('/home/aydanh/repos/rubric_gen');BUNDLE=Path(__file__).parent
REPORT=ROOT/'runs/babel-result20-current-20260908/report-v2'
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 seal=json.loads((BUNDLE/'derive-capacity-seal.json').read_text())
 for n,h in seal.items():assert sha(ROOT/n)==h,n
 receipt=json.loads((REPORT/'combination-receipt.json').read_text());assert receipt['success'] and receipt['source_unchanged'] and receipt['mode']=='combined'
 assert sha(REPORT/'analysis.json')==receipt['analysis_sha256']
 for n,h in receipt['source_seal'].items():assert sha(ROOT/n)==h,n
 commands=[[sys.executable,str(BUNDLE/'plot_results.py'),'--analysis',str(REPORT/'analysis.json'),'--output',str(REPORT/'figures')]]
 for helper in ['policy_exposure','feedback_exposure']:
  commands.append([sys.executable,str(ROOT/f'investigation/babel-overnight-20260907/{helper}.py'),'--analysis',str(REPORT/'analysis.json'),'--output',str(REPORT/helper.replace('_','-'))])
 commands.append([sys.executable,str(BUNDLE/'summarize_recovery_v2.py')])
 output=REPORT/f'derived-job-{os.environ["SLURM_JOB_ID"]}';output.mkdir(exist_ok=False)
 (output/'launch.json').write_text(json.dumps(dict(job=os.environ['SLURM_JOB_ID'],host=socket.gethostname(),commands=commands,source_seal=seal,input_sha256=sha(REPORT/'analysis.json')),indent=2)+'\n')
 exits=[]
 for i,command in enumerate(commands):
  with (output/f'stage-{i}.log').open('w') as log:exits.append(subprocess.run(command,stdout=log,stderr=subprocess.STDOUT).returncode)
  if exits[-1]:break
 unchanged=all(sha(ROOT/n)==h for n,h in seal.items());success=exits==[0,0,0,0] and unchanged
 (output/'result.json').write_text(json.dumps(dict(success=success,exits=exits,source_unchanged=unchanged))+'\n');return int(not success)
if __name__=='__main__':raise SystemExit(main())
