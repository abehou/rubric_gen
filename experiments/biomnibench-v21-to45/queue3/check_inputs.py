"""Validate current native pretreatment reuse and render saved rule evidence."""
import json
import shutil
import tempfile
from pathlib import Path
from types import SimpleNamespace
from make_configs import ROOT,BUNDLE,CELLS,TASKS
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.pretreatment_reuse import source_pool
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run
from rubric_gen.submission_revision.rubric_generation_store import load_rubric_generation
from rubric_gen.submission_revision.rubric_generation import RubricPolicy
from rubric_gen.submission_revision.seeds import resolve_seed
from rubric_gen.submission_revision.feedback import FeedbackPolicy,ProjectedFeedback,render_revision_prompt
from rubric_gen.submission_revision.controller_scoring import RevisionScorer
from rubric_gen.submission_revision.trace_defense_delivery import append_reminder
OUT=ROOT/'docs/reports/2026-09-12/biomnibench-v21-to45/queue3'
rows=[]
for task in TASKS:
    for cell,condition in CELLS.items():
        e=load_experiment(BUNDLE/f'configs/{cell}/{task}.yaml')
        source=load_experiment(Path(e.pretreatment_source['experiment']))
        pool=source_pool(e)
        assert len(e.payload['conditions'])==8 and e.execution_conditions==(condition,)
        assert len(e.execution_assignments)==3 if hasattr(e,'execution_assignments') else len([a for a in e.assignments if a.condition_id==condition])==3
        for key in ('solvers','outcome_audit','execution_audit_models','randomization'):
            assert e.payload[key]==source.payload[key]
        for key in source.protocol:
            if key!='red_team_trace_version': assert e.protocol[key]==source.protocol[key]
        for stage in ('seed','paraphrase'):
            assert e.dag[stage]['output_dir']==source.dag[stage]['output_dir']
        validate_paraphrase_run(Path(e.dag['paraphrase']['output_dir']),e)
        generations=list(pool.glob('**/generation-0001/manifest.json'))
        assert generations
        for p in generations:load_rubric_generation(p.parents[2],1,expected_policy=RubricPolicy.OFFLINE_ELICITATION)
        seed_records=[]
        for rep in range(1,4):
            resolve_seed(Path(e.dag['seed']['output_dir']),e.task_dir(task),rep,
                seed_generator=e.seed_agent_config(),prompt_profile=e.protocol['prompt'],benchmark=e.benchmark)
            p=Path(e.dag['seed']['output_dir'])/f'tasks/{task}/rep-{rep:03d}/manifest.json'
            seed_records.append({'path':str(p),'seed_sha256':json.loads(p.read_text())['seed_sha256']})
        rows.append({'cell':cell,'task':task,'config':str(BUNDLE/f'configs/{cell}/{task}.yaml'),
            'experiment_id':e.experiment_id,'condition':condition,'selected_assignments':3,
            'source_experiment_id':source.experiment_id,'pool':str(pool),'g1_manifests':[str(p) for p in generations],
            'seeds':seed_records,'paraphrase_root':e.dag['paraphrase']['output_dir']})
# A provider-free counterfactual policy projection, not a historical score-only
# trajectory: use an actually selected v2.1 rule and its real score applications.
controls=json.loads((ROOT/'docs/reports/2026-09-12/trace-user-parallel-diagnostics/control-outcomes.json').read_text())['rows']
example=None
for row in controls:
    root=Path(row['state_path']).parent
    for path in sorted((root/'trace-defense-reminders').glob('s*.json')):
        record=json.loads(path.read_text())
        if record['selection'] is None:continue
        sid=record['submission_id'];ev=json.loads((root/'rubric-evaluations'/f'{sid}.json').read_text())
        generation=load_rubric_generation(root,ev['generation_round'])
        score=root/'judgments'/sid/ev['rubric_sha256']/'score_validation.json'
        config=load_experiment(ROOT/f"experiments/trace-attack-defense-v3/control-v21-compatible/{row['task_id']}.yaml")
        instruction=(config.task_dir(row['task_id'])/'instruction.md').read_text()
        payload={'score':ev['score']}
        prompt=render_revision_prompt(FeedbackPolicy.SCORE_ONLY,payload,task_instruction=instruction,first_revision=sid=='s000')
        with tempfile.TemporaryDirectory() as temp:
            tmp=Path(temp);dest=tmp/'trace-defense-reminders';dest.mkdir()
            for previous in sorted((root/'trace-defense-reminders').glob('s*.json')):
                if previous.name<path.name:shutil.copyfile(previous,dest/previous.name)
            kwargs=dict(generation=generation,score_validation_path=score,root=tmp,submission_id=sid,instruction=instruction,allow_generation=True)
            projected=append_reminder(ProjectedFeedback(ev['score'],payload,prompt),**kwargs)
            native=json.loads((dest/path.name).read_text());(dest/path.name).unlink()
            off=append_reminder(ProjectedFeedback(ev['score'],payload,prompt),**kwargs,delivery_mode='none')
            offrecord=json.loads((dest/path.name).read_text())
            assert native['selection']==record['selection']==offrecord['selection']
            assert native['message_component'] and projected.prompt==prompt+'\n\n'+native['message_component']
            assert off.prompt==prompt and off.payload=={'score':ev['score']}
            example={'kind':'saved-checkpoint native policy projection; not a new trajectory','source':str(path),'score_path':str(score),
                'native_selection':native['selection'],'native_score_only_prompt':projected.prompt,'appendix_off_prompt':off.prompt,
                'source_selection_equal':True,'off_preserves_numeric_ordinary_feedback':True}
        break
    if example:break
assert example
# Retain original stored identities of incompatible older seeds, without rewriting them.
older=[]
for task in TASKS:
    old=Path(f'/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910/dev3/inputs/{task}/seed')
    new=Path(load_experiment(ROOT/f'experiments/trace-attack-defense-v3/control-v21-compatible/{task}.yaml').dag['seed']['output_dir'])
    for rep in range(1,4):
        rel=Path(f'tasks/{task}/rep-{rep:03d}/manifest.json')
        a=json.loads((old/rel).read_text());b=json.loads((new/rel).read_text())
        older.append({'task':task,'replicate':rep,'old_manifest':str(old/rel),'current_manifest':str(new/rel),
            'old_seed_sha256':a['seed_sha256'],'current_seed_sha256':b['seed_sha256'],'same_seed':a['seed_sha256']==b['seed_sha256']})
OUT.mkdir(parents=True,exist_ok=True)
(OUT/'inputs.json').write_text(json.dumps({'provider_calls':0,'checks':rows,'older_seed_comparison':older,'native_score_only_projection':example},indent=2)+'\n')
print(json.dumps({'native_consumer_checks':len(rows),'saved_native_appendix_verified':True,'older_same_seeds':sum(r['same_seed'] for r in older),'provider_calls':0}))
