"""Provider-free scientific input verification and producer-preserving g1 reuse."""
import hashlib
import json
import os
import shutil
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.evolution import RubricProposer
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run, resolve_paraphrase_selection
from rubric_gen.submission_revision.seeds import resolve_seed
from rubric_gen.submission_revision.study import StudyRunner, StudyRunConfig
from rubric_gen.artifacts.serialization import write_json_atomic

BUNDLE=Path(__file__).resolve().parent
ROOT=BUNDLE.parents[1]
RUN=Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910/result20')
V2=Path('/data/user_data/aydanh/rubric_gen/runs/result20-prompt-nofallback-v2-20260910')

def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()

def inventory(root):
    return {str(p.relative_to(root)):sha(p) for p in root.rglob('*') if p.is_file() and not p.name.endswith('.lock')}

def main():
    if not os.environ.get('SLURM_JOB_ID'):
        raise RuntimeError('Input verification requires compute-node storage access')
    def forbidden(*args,**kwargs):
        raise AssertionError('Provider calls forbidden during frozen input verification')
    RubricProposer._run_direct_proposer=forbidden
    exp=load_experiment(BUNDLE/'result20.yaml')
    assert len(exp.execution_assignments)==120 and len(exp.task_ids)==20 and exp.replicates==3
    source=load_experiment(Path(exp.pretreatment_source['experiment']))
    old_seeds=Path(source.dag['seed']['output_dir']); new_seeds=Path(exp.dag['seed']['output_dir'])
    assert (old_seeds/'manifest.json').is_file() and not old_seeds.is_symlink()
    if not new_seeds.exists():
        new_seeds.parent.mkdir(parents=True,exist_ok=True)
        shutil.copytree(old_seeds,new_seeds,copy_function=shutil.copyfile)
    assert inventory(old_seeds)==inventory(new_seeds), 'frozen seed copy differs'
    new_pool=Path(exp.dag['paraphrase']['output_dir']);old_pool=Path(source.dag['paraphrase']['output_dir'])
    validate_paraphrase_run(new_pool,exp);validate_paraphrase_run(old_pool,source)
    assert sha(new_pool/'manifest.json')=='404d8cb9437c4f6d766c40a1c9fade066a0e53aab249c37fc63da990a68bc0e8'
    receipt=json.loads((V2/'pool-provenance.json').read_text())
    assert receipt['fallback_count']==0 and receipt['rewritten_units']==471
    rows=[]
    for task in exp.task_ids:
        selected=resolve_paraphrase_selection(new_pool,exp,task)
        original=resolve_paraphrase_selection(old_pool,source,task)
        assert selected.optimizer_sha256==original.optimizer_sha256
        assert selected.development_sha256==original.development_sha256
        variants=[]
        for v in range(5):
            path=new_pool/'tasks'/task/f'variant-{v:03d}.txt'
            variants.append({'variant':v,'path':str(path),'sha256':sha(path)})
        for rep in range(1,4):
            seed=resolve_seed(Path(exp.dag['seed']['output_dir']),exp.task_dir(task),rep,
                seed_generator=exp.seed_agent_config(),prompt_profile=exp.protocol['prompt'],benchmark=exp.benchmark)
            oldseed=resolve_seed(Path(source.dag['seed']['output_dir']),source.task_dir(task),rep,
                seed_generator=source.seed_agent_config(),prompt_profile=source.protocol['prompt'],benchmark=source.benchmark)
            assert seed.sha256==oldseed.sha256
            rows.append({'task':task,'replicate':rep,'seed_sha256':seed.sha256,
                         'selected_sha256':selected.optimizer_sha256,'development_sha256':selected.development_sha256,'variants':variants})
    validation_root=RUN/'input-validation'
    runner=StudyRunner(StudyRunConfig(exp,Path(exp.dag['seed']['output_dir']),new_pool,validation_root,4))
    pool=Path(exp.pretreatment_source['study_dir'])/'pretreatment-rubrics'
    before=inventory(pool)
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(runner._prepare_pretreatment_rubric,exp.task_ids))
    assert inventory(pool)==before
    after=inventory(runner.pretreatment_root)
    assert all(after.get(name)==digest for name,digest in before.items())
    g1=[]
    for p in sorted(runner.pretreatment_root.glob('**/generation-0001/manifest.json')):
        m=json.loads(p.read_text());e=p.parent/'evolution.json';metadata=json.loads(e.read_text())
        g1.append({'manifest':str(p),'manifest_sha256':sha(p),'generation_sha256':m['generation_sha256'],
                   'real_producer_implementation_sha256':metadata['implementation_sha256'],'evolution_sha256':sha(e)})
    assert len(g1)==20
    receipts_dir=BUNDLE/'receipts';receipts_dir.mkdir(exist_ok=True)
    existing=[]
    for name in ('completion.json','report-v1-v2.json','pool-provenance.json'):
        path=V2/name
        assert path.is_file()
        existing.append({'path':str(path),'sha256':sha(path)})
        (receipts_dir/('v2-'+name)).write_bytes(path.read_bytes())
    result={'success':True,'provider_calls':0,'job':os.environ['SLURM_JOB_ID'],'experiment_id':exp.experiment_id,
            'config_sha256':sha(exp.path),'matched_inputs':rows,'frozen_g1':g1,'source_pool_unchanged':True,
            'source_pool':str(pool),'source_pool_inventory_sha256':sha_json(before),
            'consumer_pool':str(runner.pretreatment_root),'canonical_v2_receipts':existing,
            'source_hashes':{str(p.relative_to(ROOT)):sha(p) for p in (ROOT/'src').rglob('*.py')}}
    write_json_atomic(receipts_dir/'inputs.json',result)
    print(json.dumps({'success':True,'matched_seeds':len(rows),'frozen_g1':len(g1),'provider_calls':0}),flush=True)

def sha_json(value):
    return hashlib.sha256(json.dumps(value,sort_keys=True).encode()).hexdigest()

if __name__=='__main__':main()
