"""Generate only missing canonical da-18-1 inputs, with immutable provenance."""
import hashlib,json,os,signal,socket,subprocess,sys,time
from pathlib import Path
import yaml
from dotenv import dotenv_values
from rubric_gen.runtime.paths import PROJECT_ROOT as CODE
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.seeds import resolve_seed
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run
from rubric_gen.submission_revision.study import _exclusive_study_lease
ROOT=Path('/home/aydanh/repos/rubric_gen');BUNDLE=Path(__file__).parent
sys.path.insert(0,str(CODE/'scripts/babel'))
from monitor import Monitor

def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 assert os.environ.get('SLURM_JOB_ID'),'Slurm required'
 assert subprocess.check_output(['git','rev-parse','HEAD'],cwd=CODE,text=True).strip()=='5270c4aafcac67adc2ff67f63b9595112d16202a'
 config=BUNDLE/'experiment.yaml';canonical=ROOT/'experiments/biomnibench-dev3.yaml'
 x=yaml.safe_load(config.read_text());y=yaml.safe_load(canonical.read_text())
 assert x['tasks']==['da-18-1'] and y['tasks']==['da-3-4','da-11-1','da-18-1']
 for key in set(y)-{'tasks','tasks_dir','dag'}:assert x[key]==y[key],key
 assert x['randomization']=={'seed':20260806,'replicates':3}
 exp=load_experiment(config);p=policy();assert p['aggregate_concurrency']==60
 out=ROOT/'runs/babel-dev3-da18-inputs-20260908';out.mkdir(exist_ok=True)
 with _exclusive_study_lease(out):
  receipt=out/f'job-{os.environ["SLURM_JOB_ID"]}';receipt.mkdir(exist_ok=False)
  inputs=[*CODE.joinpath('src').rglob('*.py'),CODE/'uv.lock',CODE/'config/runtime.json',canonical,config,Path(__file__),BUNDLE/'inputs.sbatch',*exp.task_dir('da-18-1').rglob('*')]
  seals={str(q.resolve()):sha(q) for q in inputs if q.is_file()}
  commands=[[str(Path(sys.executable).with_name('rubric-gen')),stage,'--experiment',str(config),'--max-concurrency','60'] for stage in ['seed','paraphrase']]
  metadata={'job':os.environ['SLURM_JOB_ID'],'host':socket.gethostname(),'source_commit':'5270c4aafcac67adc2ff67f63b9595112d16202a','config':str(config),'commands':commands,'source_hashes':seals,'policy':p,'resources':{k:os.environ.get(k) for k in ['SLURM_CPUS_PER_TASK','SLURM_MEM_PER_NODE','SLURM_JOB_PARTITION']},'scope':'Missing canonical da-18-1 inputs only;3replicates,5variants;no revise/detect;existing two-task pools untouched','resume':'Current seed/paraphrase native reuse only;no restart or metadata rewriting'}
  (receipt/'launch.json').write_text(json.dumps(metadata,indent=2)+'\n')
  credentials=dotenv_values(ROOT/'.env.local');assert credentials.get('OPENAI_API_KEY');os.environ['OPENAI_API_KEY']=credentials['OPENAI_API_KEY']
  monitor=Monitor(p['coordination_dir'],receipt/'metrics.jsonl',[]);stop=[]
  signal.signal(signal.SIGTERM,lambda *_:stop.append(True));signal.signal(signal.SIGINT,lambda *_:stop.append(True))
  exits=[];start=time.time();error=None
  try:
   for command in commands:
    if stop:break
    with (receipt/f'{command[1]}.log').open('w') as log:
     child=subprocess.Popen(command,cwd=CODE,stdout=log,stderr=subprocess.STDOUT,start_new_session=True);next_sample=0;stopping=None
     try:
      while child.poll() is None:
       if time.monotonic()>=next_sample:monitor.sample();next_sample=time.monotonic()+30
       if stop:
        stopping=stopping or time.monotonic()
        try:os.killpg(child.pid,signal.SIGKILL if time.monotonic()-stopping>120 else signal.SIGTERM)
        except ProcessLookupError:pass
       time.sleep(1)
     finally:
      if child.poll() is None:
       os.killpg(child.pid,signal.SIGTERM)
       try:child.wait(timeout=120)
       except subprocess.TimeoutExpired:os.killpg(child.pid,signal.SIGKILL);child.wait()
     exits.append(child.wait())
    if exits[-1]:break
   if exits==[0,0]:
    validate_paraphrase_run(Path(exp.dag['paraphrase']['output_dir']),exp)
    for rep in range(1,4):resolve_seed(Path(exp.dag['seed']['output_dir']),exp.task_dir('da-18-1'),rep,seed_generator=exp.seed_agent_config(),prompt_profile=exp.protocol['prompt'],benchmark=exp.benchmark)
  except Exception as e:error={'class':type(e).__name__,'message':str(e)[:1000]}
  unchanged=all(sha(n)==h for n,h in seals.items());success=exits==[0,0] and not error and unchanged and not stop
  (receipt/'result.json').write_text(json.dumps({'success':success,'exits':exits,'error':error,'source_unchanged':unchanged,'elapsed_seconds':time.time()-start})+'\n')
  return int(not success)
if __name__=='__main__':raise SystemExit(main())
