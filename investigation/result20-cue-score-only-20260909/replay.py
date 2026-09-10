"""Bounded feedback-only fidelity diagnostic on sealed historical contexts."""
import dataclasses,hashlib,json,os,sys,time,subprocess
from pathlib import Path
from dotenv import dotenv_values
from rubric_gen.benchmarks import get_submission_benchmark
from rubric_gen.submission_revision.feedback import _project_member_feedback,FeedbackPolicy
from rubric_gen.submission_revision.user_simulator import SimulatedUserConfig,SimulatedUserFeedback,_canonical_full_feedback,_feedback_request,_generate_with_hosted_model,_parse_feedback
from rubric_gen.submission_revision.user_simulator_history import build_simulated_user_history
ROOT=Path('/home/aydanh/repos/rubric_gen')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
def main():
 assert os.environ.get('SLURM_JOB_ID')
 mode=sys.argv[1];assert mode in ('validate','run')
 root=next((ROOT/'runs/babel-result20-cue-score-20260909/static/study').glob('*/experiments/*/rep-*/*/*'))
 manifest=json.loads((root/'manifest.json').read_text());cfg=manifest['feedback_simulator'];config=SimulatedUserConfig(**{f.name:cfg[f.name] for f in dataclasses.fields(SimulatedUserConfig)})
 client=SimulatedUserFeedback(config);benchmark=get_submission_benchmark(manifest['benchmark']);requests=[];inputs={}
 rubric_path=root/'rubric-generations/generation-0000/rubric.txt';rubric=rubric_path.read_text();instruction_path=Path(manifest['task_dir'])/'instruction.md'
 for sid in ('s000','s001'):
  record_path=root/f'feedback-generations/{sid}.json';record=json.loads(record_path.read_text())
  validation=next(root.glob(f'judgments/{sid}/*/score_validation.json'));evaluation=validation.with_name('evaluation.json')
  full=_project_member_feedback(validation,evaluation,rubric,sha(rubric_path),FeedbackPolicy.FULL).payload
  text=_canonical_full_feedback(full);assert hashlib.sha256(text.encode()).hexdigest()==record['full_feedback_sha256']
  artifact=benchmark.render_user_review(root/'submissions'/sid/'workspace');assert hashlib.sha256(artifact.encode()).hexdigest()==record['current_artifact_sha256']
  history=build_simulated_user_history(root,benchmark,int(sid[1:]));context,mode_history=client._history_context(experiment_id=manifest['experiment_id'],assignment_id=manifest['assignment_id'],submission_id=sid,history=history,history_summary=None)
  assert hashlib.sha256(context.encode()).hexdigest()==record['history_context']['sha256']
  request=_feedback_request(instruction=instruction_path.read_text(),full_feedback_text=text,current_artifact=artifact,history_context=context,max_concerns=config.max_concerns,max_output_tokens=config.max_output_tokens)
  requests.append((sid,request))
  for p in (record_path,validation,evaluation,rubric_path,instruction_path):inputs[str(p)]=sha(p)
 out=ROOT/'runs/babel-cue-score-only-replay-20260909'/os.environ['SLURM_JOB_ID'];out.mkdir(parents=True,exist_ok=False)
 code=ROOT/'runs/babel-code/result20-cue-score-only'
 source_hashes={str(p):sha(p) for p in (code/'src').rglob('*.py')}
 (out/'provenance.json').write_text(json.dumps(dict(commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=code,text=True).strip(),source_hashes=source_hashes,script_sha256=sha(__file__),job_id=os.environ['SLURM_JOB_ID']),indent=2)+'\n')
 (out/'inputs.json').write_text(json.dumps(dict(mode=mode,inputs=inputs,requests=[dict(checkpoint=sid,request=dataclasses.asdict(req)) for sid,req in requests]),indent=2)+'\n')
 if mode=='run':
  prior=json.loads((ROOT/'runs/babel-cue-score-only-replay-20260909'/sys.argv[2]/'inputs.json').read_text())
  assert prior['inputs']==inputs and prior['requests']==[dict(checkpoint=sid,request=dataclasses.asdict(req)) for sid,req in requests]
  values=dotenv_values(ROOT/'.env.local');os.environ['OPENAI_API_KEY']=values['OPENAI_API_KEY']
  for sid,request in requests:
   for repeat in range(3):
    started=time.monotonic();generated=_generate_with_hosted_model(config,request);output=_parse_feedback(generated.text,max_concerns=config.max_concerns)
    (out/f'{sid}-{repeat}.json').write_text(json.dumps(dict(output=output,generation=dataclasses.asdict(generated),elapsed=time.monotonic()-started),indent=2)+'\n')
 assert all(sha(p)==h for p,h in {**inputs,**source_hashes}.items())
 (out/'result.json').write_text(json.dumps(dict(success=True,mode=mode,contexts=2,calls=6 if mode=='run' else 0))+'\n')
if __name__=='__main__':main()
