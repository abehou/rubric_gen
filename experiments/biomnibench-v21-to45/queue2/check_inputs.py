"""Read the actual shared pretreatment inputs with the native source validator."""
import json
from pathlib import Path
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.pretreatment_reuse import source_pool
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run
from rubric_gen.submission_revision.rubric_generation_store import load_rubric_generation
from rubric_gen.submission_revision.rubric_generation import RubricPolicy
from rubric_gen.submission_revision.seeds import resolve_seed

ROOT=Path(__file__).resolve().parents[3]
rows=[]
for cell in ('R1','R2'):
    for task in ('da-3-4','da-11-1','da-18-1'):
        config=ROOT/f'experiments/biomnibench-v21-to45/queue2/configs/{cell}/{task}.yaml'
        candidate=load_experiment(config)
        control=load_experiment(Path(candidate.pretreatment_source['experiment']))
        pool=source_pool(candidate)
        assert candidate.payload['solvers']==control.payload['solvers']
        assert candidate.protocol['feedback_simulator']==control.protocol['feedback_simulator']
        assert candidate.payload['execution_audit_models']==control.payload['execution_audit_models']
        assert candidate.payload['outcome_audit']==control.payload['outcome_audit']
        for stage in ('seed','paraphrase'):
            assert candidate.dag[stage]['output_dir']==control.dag[stage]['output_dir']
        validate_paraphrase_run(Path(candidate.dag['paraphrase']['output_dir']),candidate)
        generations=list(pool.glob('**/generation-0001/manifest.json'))
        assert generations
        for manifest in generations:
            load_rubric_generation(manifest.parents[2],1,expected_policy=RubricPolicy.OFFLINE_ELICITATION)
        for replicate in range(1,4):
            resolve_seed(Path(candidate.dag['seed']['output_dir']),candidate.task_dir(task),replicate,
                seed_generator=candidate.seed_agent_config(),prompt_profile=candidate.protocol['prompt'],benchmark=candidate.benchmark)
        # Pool entry validation and installation remain native revise work.
        assert pool.is_dir()
        rows.append({'cell':cell,'task':task,'config':str(config),'experiment_id':candidate.experiment_id,
            'source_experiment_id':control.experiment_id,'source_pool':str(pool),
            'seed_root':candidate.dag['seed']['output_dir'],'paraphrase_root':candidate.dag['paraphrase']['output_dir'],
            'native_source_compatible':True,'native_paraphrase_valid':True,
            'seed_manifests_present':[str(p) for p in sorted((Path(candidate.dag['seed']['output_dir'])/'tasks'/task).glob('rep-*/manifest.json'))],
            'g1_generation_records':[str(p) for p in generations]})
        assert len(rows[-1]['seed_manifests_present'])==3
out=ROOT/'docs/reports/2026-09-12/biomnibench-v21-to45/queue2'
out.mkdir(parents=True,exist_ok=True)
(out/'input-reuse.json').write_text(json.dumps({'provider_calls':0,'checks':rows},indent=2)+'\n')
print(json.dumps({'native_input_checks':len(rows),'provider_calls':0}))
evidence=out/'control-evidence.json'
if evidence.exists():
    raw=Path('/data/user_data/aydanh/rubric_gen/runs/biomnibench-v21-to45-20260912/queue2/diagnostics')
    raw.mkdir(parents=True,exist_ok=True)
    (raw/'control-evidence.json').write_bytes(evidence.read_bytes())
