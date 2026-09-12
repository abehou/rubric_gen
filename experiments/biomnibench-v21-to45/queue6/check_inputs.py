"""Read only the approved added-task inputs; no outcome or provider access."""
import json
from pathlib import Path
from make_configs import ROOT,BUNDLE,TASKS,RUN,SOURCE_POOL
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run

def check(task):
    exp=load_experiment(BUNDLE/'configs'/f'{task}.yaml')
    ref=load_experiment(ROOT/'experiments/trace-attack-defense-v21/result20.yaml')
    assert exp.task_ids==(task,) and len(exp.execution_assignments)==6
    assert exp.replicates==3 and exp.pretreatment_source is None
    for key in ('protocol','solvers','red_team_generator','seed_generator','rubric_paraphrases','randomization','outcome_audit','execution_audit_models'):
        assert exp.payload[key]==ref.payload[key],key
    assert {a.condition_id for a in exp.execution_assignments}=={'full-static','full-red-team-trace'}
    for stage in ('seed','paraphrase','revise','detect'):
        Path(exp.dag[stage]['output_dir']).relative_to(RUN/task)
    instruction=exp.task_dir(task)/'instruction.md'
    assert instruction.is_file() and instruction.stat().st_size>0
    validate_paraphrase_run(SOURCE_POOL,exp)
    files=[]
    for index in (0,1):
        p=SOURCE_POOL/'tasks'/task/f'variant-{index:03d}.json';d=json.loads(p.read_text())
        files.append({'variant_index':index,'path':str(p),'rubric_sha256':d['rubric_sha256'],'master_sha256':d['master_sha256']})
    seed=Path(exp.dag['seed']['output_dir'])
    return {'task':task,'experiment_id':exp.experiment_id,'assignments':6,'instruction_bytes':instruction.stat().st_size,'selected_development_sources':files,'existing_new_seed_manifest':(seed/'manifest.json').is_file()}

if __name__=='__main__':
    rows=[check(task) for task in TASKS]
    out=ROOT/'docs/reports/2026-09-12/biomnibench-v21-to45/queue6/input-inventory.json'
    out.write_text(json.dumps({'provider_calls':0,'tasks':rows,'new_assignments':60},indent=2)+'\n')
    print(json.dumps({'tasks_verified':len(rows),'assignments':sum(r['assignments'] for r in rows),'existing_seed_pools':sum(r['existing_new_seed_manifest'] for r in rows),'provider_calls':0}))
