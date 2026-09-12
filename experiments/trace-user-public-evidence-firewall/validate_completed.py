"""Provider-free final replay and compact packet export; never dispatch models."""
import json, os
from pathlib import Path
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.user_simulator import SimulatedUserFeedback, SimulatedUserConfig
from rubric_gen.submission_revision.rubric_generation_store import load_rubric_generation
from run_feedback_checks import BUNDLE, ROOT, RUN, CELLS


def no_calls(*args,**kwargs):raise AssertionError('provider calls forbidden during final validation')


def main():
    assert os.environ.get('SLURM_JOB_ID')
    data=json.loads((BUNDLE/'feedback-results.json').read_text())
    assert len(data['rows'])==24 and all(r['status']=='completed' for r in data['rows'])
    checked=[]
    for row in data['rows']:
        inputs=json.loads(Path(row['source']).read_text());record=json.loads(Path(row['result_path']).read_text())
        sim=SimulatedUserFeedback(SimulatedUserConfig(**inputs['config']),generator=no_calls)
        gen=load_rubric_generation(Path(inputs['root']),inputs['generation_round'])
        out=sim.validate(record,experiment_id='trace-user-firewall-feedback-diagnostic',assignment_id=row['case'],
            submission_id=inputs['submission_id'],generation_round=gen.generation_round,instruction=inputs['instruction'],
            generation=gen,full_feedback=inputs['full_feedback'],current_artifact=inputs['current_artifact'],
            history=inputs['history'],history_summary=None,trace_version=CELLS[row['cell']])
        assert out==row['output']
        public_stages=0
        for s in record['firewall_generation']['stages']:
            if s['identity']['stage']=='locator':continue
            e=json.loads(s['identity']['request']['evidence'])
            assert set(e) in ({'public_sources','candidate'}, {'public_sources','candidate','public_verification'})
            assert {d['source_id'] for d in e['public_sources']}=={'task','artifact','history'}
            assert set(e['candidate'])=={'issue_type','public_refs'}
            public_stages+=1
        checked.append({'cell':row['cell'],'case':row['case'],'native_replay':'unchanged',
                        'public_stage_allowlists_validated':public_stages,'result_path':row['result_path']})
    # This is an archive copy, not a new producer identity or a repaired response.
    archive=RUN/'feedback-results.json'
    if archive.exists():assert json.loads(archive.read_text())==data
    else:write_json_atomic(archive,data)
    report=ROOT/'docs/reports/2026-09-12/trace-user-public-evidence-firewall'
    write_json_atomic(report/'completed-replay.json',{'job':os.environ['SLURM_JOB_ID'],'provider_calls':0,
        'checkpoints':len(checked),'stage_count':sum(1+v['public_stage_allowlists_validated'] for v in checked),
        'archive_copy':str(archive),'rows':checked})
    print(json.dumps({'checkpoints_replayed':len(checked),'provider_calls':0,'archive':str(archive)}))

if __name__=='__main__': main()
