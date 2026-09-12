"""Exactly the prior twelve checkpoints for each of P1/P2. No solver calls."""
from concurrent.futures import ThreadPoolExecutor
import json, os, subprocess, time
from pathlib import Path
from dotenv import dotenv_values
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.submission_revision.evolution_serialization import canonical_json
from rubric_gen.submission_revision import user_public_firewall as firewall
from rubric_gen.submission_revision.user_simulator import SimulatedUserConfig, SimulatedUserFeedback
from rubric_gen.submission_revision.rubric_generation_store import load_rubric_generation
from rubric_gen.runtime.capacity import policy
BUNDLE=Path(__file__).resolve().parent; ROOT=BUNDLE.parents[1]
SOURCE=Path('/data/user_data/aydanh/rubric_gen/runs/trace-user-parallel-diagnostics-20260912/feedback-checks/inputs')
RUN=Path('/data/user_data/aydanh/rubric_gen/runs/trace-user-public-evidence-firewall-20260912/feedback-checks')
CELLS={'P1':'attack_defense_user_public_p1','P2':'attack_defense_user_public_p2'}


def one(cell, item):
    source=SOURCE/(item['case']+'.json'); inputs=json.loads(source.read_text())
    # Same already-verified bytes and fixed checkpoint population; no new evidence.
    if not inputs['original_source_binding_verified']:
        raise RuntimeError('original source binding unavailable')
    original=json.loads(Path(inputs['feedback_generation_path']).read_text())
    for key, text in [('current_artifact_sha256',inputs['current_artifact']),
                      ('full_feedback_sha256',canonical_json(inputs['full_feedback'])),
                      ('history_sha256',canonical_json(inputs['history']))]:
        if original[key] != sha256_text(text):
            raise RuntimeError('saved input differs from original feedback receipt: '+key)
    if original['history_context']['sha256'] != sha256_text(inputs['history_context']):
        raise RuntimeError('saved public history context differs')
    gen=load_rubric_generation(Path(inputs['root']),inputs['generation_round'])
    simulator=SimulatedUserFeedback(SimulatedUserConfig(**inputs['config']))
    args=dict(experiment_id='trace-user-firewall-feedback-diagnostic',assignment_id=item['case'],
        submission_id=item['submission_id'], generation_round=gen.generation_round,
        instruction=inputs['instruction'],generation=gen,full_feedback=inputs['full_feedback'],
        current_artifact=inputs['current_artifact'],history=inputs['history'],history_summary=None,
        trace_version=CELLS[cell])
    directory=RUN/cell/item['case']; target=directory/'result.json'; failure=directory/'terminal-error.json'
    start=time.monotonic(); reused=target.exists()
    try:
        if reused:
            record=json.loads(target.read_text()); simulator.validate(record,**args)
        elif failure.exists():
            return dict(cell=cell,case=item['case'],status='failed',reused=True,error=json.loads(failure.read_text()))
        else:
            record=simulator.generate(**args,failure_dir=directory/'failed-attempts')
            write_json_atomic(target,record)
        stages=record['firewall_generation']['stages']
        result=dict(cell=cell,case=item['case'],status='completed',reused=reused,source=str(source),result_path=str(target),
            output=record['output'],stages=[{
                'stage':stage['identity']['stage'],'request':stage['identity']['request'],
                'output':stage['output'],'source_bindings':stage['source_bindings'],
                'attempts':[{k:v for k,v in a.items() if k not in ('identity','request')} for a in stage['attempts']]
            } for stage in stages])
        # Large raw requests stay on compute storage; compact local results retain
        # exact outputs/provenance plus a request path and source bindings.
        for stage in result['stages']:
            stage['request_path']=str(directory/'failed-attempts'/'firewall-stages'/stage['stage']/'result.json')
            del stage['request']
    except Exception as exc:
        error={'type':type(exc).__name__,'message':str(exc)}
        write_json_atomic(failure,error)
        result=dict(cell=cell,case=item['case'],status='failed',reused=False,error=error,source=str(source))
    result['wall_seconds']=time.monotonic()-start
    write_json_atomic(directory/'timing.json',{'job':os.environ['SLURM_JOB_ID'],'wall_seconds':result['wall_seconds']})
    print(json.dumps({k:result[k] for k in ('cell','case','status','reused')}),flush=True)
    return result


def main():
    if not os.environ.get('SLURM_JOB_ID'): raise RuntimeError('compute only')
    os.environ['OPENAI_API_KEY']=str(dotenv_values('/home/aydanh/repos/rubric_gen/.env.local')['OPENAI_API_KEY'])
    fixed=json.loads((ROOT/'experiments/trace-user-parallel-diagnostics/feedback_checkpoints.json').read_text())
    assert len(fixed)==12
    def arm(cell): return [one(cell,item) for item in fixed]
    start=time.monotonic()
    with ThreadPoolExecutor(max_workers=2) as pool: results=sum(pool.map(arm,CELLS),[])
    record={'job':os.environ['SLURM_JOB_ID'],'commit':subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,text=True).strip(),
            'runtime_policy':policy(),'logical_checkpoints':len(results),'wall_seconds':time.monotonic()-start,'rows':results}
    write_json_atomic(BUNDLE/'feedback-results.json',record)
    print(json.dumps({'logical_checkpoints':len(results),'completed':sum(r['status']=='completed' for r in results)}),flush=True)

if __name__=='__main__': main()
