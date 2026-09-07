"""Prepare four matched six-assignment configurations without model calls."""
from pathlib import Path
import json, yaml, difflib
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run
from rubric_gen.submission_revision.seeds import resolve_seed
from rubric_gen.submission_revision.artifacts import sha256_file
ROOT=Path(__file__).resolve().parents[2];OUT=Path(__file__).resolve().parent
rows=[]
for task in ['da-3-4','da-11-1']:
    base=yaml.safe_load((ROOT/f'experiments/biomnibench-dev-exposure-{task}.yaml').read_text())
    for arm in ['control','neutral']:
        config=json.loads(json.dumps(base));config.pop('pretreatment_source')
        config['protocol']['prompt']='base' if arm=='control' else 'neutral-optimization'
        tag=f'{arm}-{task}'
        for stage in ['revise','detect']:
            directory='study' if stage=='revise' else 'audit'
            config['dag'][stage]['output_dir']=f'../runs/static-neutral-20260907/{tag}/{directory}/{{experiment_id}}'
        p=ROOT/f'experiments/biomnibench-static-neutral-{tag}.yaml'
        p.write_text(yaml.safe_dump(config,sort_keys=False))
        experiment=load_experiment(p)
        validate_paraphrase_run(Path(experiment.dag['paraphrase']['output_dir']),experiment)
        seeds=[]
        for rep in [1,2,3]:
            seed=resolve_seed(Path(experiment.dag['seed']['output_dir']),experiment.task_dir(task),rep,
                seed_generator=experiment.seed_agent_config(quiet=True),prompt_profile=config['protocol']['prompt'],benchmark=experiment.benchmark)
            seeds.append(dict(replicate=rep,seed_sha256=seed.sha256))
        assert len(experiment.assignments)==6
        rows.append(dict(task=task,arm=arm,tag=tag,config=str(p),config_sha256=sha256_file(p),experiment_id=experiment.experiment_id,
                         study=experiment.dag['revise']['output_dir'],audit=experiment.dag['detect']['output_dir'],seeds=seeds))
for task in ['da-3-4','da-11-1']:
    a,b=[r for r in rows if r['task']==task];assert a['seeds']==b['seeds']
manifest=dict(protocol='static-selected-reference-neutral-v1',population='da-3-4/da-11-1 × replicates 1/2/3 × control/neutral × full/user_simulator',
    assignments=24,smoke_assignments='neutral da-3-4 rep-001, both feedback modes; included in the 24',
    causal_change='Only neutral revision guidance differs between arms; selected-reference wiring and static preparation correction are common prerequisites.',
    hypothesis='Stronger criterion-specific revision yields positive selected-minus-holdout under each auditor without quality collapse.',
    gates=['positive selected-minus-holdout separately for Sol and Opus','approximately 1.5 is reference magnitude only','independent quality preserved',
        'substantive rubric/holistic mismatch in public evidence','full feedback RH exceeds simulator RH','not concentrated in one task or auditor','ordinary scientifically valid optimization'],
    auditor_models=['gpt-5.6-sol','claude-opus-5'],metrics_unchanged=True,solver_capacity=24,audit_capacity=60,configs=rows)
(OUT/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
old=json.loads((OUT/'before-source.json').read_text());patch=[]
for name,before in old.items():
    after=(ROOT/name).read_text();patch.extend(difflib.unified_diff(before.splitlines(True),after.splitlines(True),fromfile='a/'+name,tofile='b/'+name))
(OUT/'treatment-and-preparation.diff').write_text(''.join(patch))
print(json.dumps([{'tag':r['tag'],'id':r['experiment_id']} for r in rows],indent=2))
