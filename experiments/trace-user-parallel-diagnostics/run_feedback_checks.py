"""At most 36 fixed logical simulator requests using the native bounded retries."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import json,os,subprocess,time
from pathlib import Path
from dotenv import dotenv_values
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision import user_feedback_factors as factors
from rubric_gen.submission_revision.user_simulator import SimulatedUserFeedback,SimulatedUserConfig
from rubric_gen.submission_revision.rubric_generation_store import load_rubric_generation
from rubric_gen.runtime.capacity import policy
BUNDLE=Path(__file__).resolve().parent;ROOT=BUNDLE.parents[1]
RUN=Path('/data/user_data/aydanh/rubric_gen/runs/trace-user-parallel-diagnostics-20260912/feedback-checks')
CELLS={'C10':'attack_defense_user_d1g0','C01':'attack_defense_user_d0g1','C11':'attack_defense_user_d1g1'}


def one(cell,item):
    version=CELLS[cell];name=item['case'];source=RUN/'inputs'/f'{name}.json';inputs=json.loads(source.read_text())
    root=Path(inputs['root']);gen=load_rubric_generation(root,inputs['generation_round'])
    sim=SimulatedUserFeedback(SimulatedUserConfig(**inputs['config']))
    selected=inputs['focused_dynamic_check'] if factors.budgeted(version) else None
    args=dict(experiment_id='trace-user-factor-feedback-diagnostic',assignment_id=name,submission_id=item['submission_id'],
        generation_round=gen.generation_round,instruction=inputs['instruction'],generation=gen,
        full_feedback=inputs['full_feedback'],current_artifact=inputs['current_artifact'],
        history=inputs['history'],history_summary=None,trace_version=version,focused_dynamic_check=selected)
    directory=RUN/cell/name;target=directory/'result.json';failure=directory/'terminal-error.json'
    if target.exists():
        record=json.loads(target.read_text());sim.validate(record,**args)
        return dict(cell=cell,case=name,status='completed',reused=True,output=record['output'],attempt_count=record['attempt_count'],result_path=str(target))
    if failure.exists():return dict(cell=cell,case=name,status='failed',reused=True,error=json.loads(failure.read_text()),result_path=str(failure))
    from rubric_gen.submission_revision.evolution_serialization import canonical_json
    request=factors.feedback_request(trace_version=version,focused_dynamic_check=selected,
        instruction=inputs['instruction'],current_artifact=inputs['current_artifact'],
        full_feedback_text=canonical_json(inputs['full_feedback']),history_context=inputs['history_context'],
        max_concerns=sim.config.max_concerns,max_output_tokens=sim.config.max_output_tokens)
    write_json_atomic(directory/'request.json',asdict(request))
    start=time.monotonic()
    try:
        record=sim.generate(**args,failure_dir=directory/'failed-attempts')
        write_json_atomic(target,record)
        result=dict(cell=cell,case=name,status='completed',reused=False,output=record['output'],attempt_count=record['attempt_count'],
                    result_path=str(target),wall_seconds=time.monotonic()-start,provider_metadata=record['feedback_generation']['provider_metadata'])
    except Exception as exc:
        error={'type':type(exc).__name__,'message':str(exc),'wall_seconds':time.monotonic()-start}
        write_json_atomic(failure,error);result=dict(cell=cell,case=name,status='failed',reused=False,error=error,result_path=str(failure))
    write_json_atomic(directory/'timing.json',{'job':os.environ['SLURM_JOB_ID'],'wall_seconds':time.monotonic()-start})
    print(json.dumps({k:result[k] for k in ('cell','case','status','reused')}),flush=True)
    return result


def main():
    if not os.environ.get('SLURM_JOB_ID'):raise RuntimeError('compute only')
    os.environ['OPENAI_API_KEY']=str(dotenv_values('/home/aydanh/repos/rubric_gen/.env.local')['OPENAI_API_KEY'])
    checkpoints=json.loads((BUNDLE/'feedback_checkpoints.json').read_text());assert len(checkpoints)<=12
    def arm(cell):return [one(cell,item) for item in checkpoints]
    start=time.monotonic()
    with ThreadPoolExecutor(max_workers=3) as pool:results=sum(pool.map(arm,CELLS),[])
    record={'job':os.environ['SLURM_JOB_ID'],'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'runtime_policy':policy(),'logical_requests':len(results),'wall_seconds':time.monotonic()-start,'rows':results}
    write_json_atomic(BUNDLE/'feedback-results.json',record)
    print(json.dumps({'logical_requests':len(results),'completed':sum(r['status']=='completed' for r in results)}),flush=True)

if __name__=='__main__':main()
