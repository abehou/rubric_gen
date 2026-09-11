"""Provider-free native checks of canonical dev3's separate producer input pools."""
import json
import os
from pathlib import Path
import shutil
from concurrent.futures import ThreadPoolExecutor
import yaml
from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run, resolve_paraphrase_selection
from rubric_gen.submission_revision.seeds import resolve_seed
from rubric_gen.submission_revision.evolution import RubricProposer
from rubric_gen.submission_revision.study import StudyRunConfig, StudyRunner

BUNDLE=Path(__file__).resolve().parent
ROOT=BUNDLE.parents[1]
HOME_REPO=Path('/home/aydanh/repos/rubric_gen')
RUN=Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910')
SUBVERSION='dev2'
SOURCES={
 'da-3-4': {'seed':'runs/autonomous-dev3-20260907/isolation-readers-smoke/seeds',
             'paraphrase':'runs/autonomous-dev3-20260907/isolation-readers-smoke/paraphrases',
             'source_config':'experiments/biomnibench-dev3-isolation-cachefix-smoke.yaml',
             'source_study':'runs/autonomous-dev3-20260907/isolation-cachefix-smoke/study/biomnibench-da-factorial-r3-3686c8965c2e'},
 'da-11-1': {'seed':'runs/autonomous-dev3-20260907/baseline-da11/seeds',
              'paraphrase':'runs/autonomous-dev3-20260907/baseline-da11/paraphrases',
              'source_config':'experiments/biomnibench-dev-baseline-da11.yaml',
              'source_study':'runs/autonomous-dev3-20260907/baseline-da11/study/biomnibench-da-factorial-r3-ac929d893d67'},
 'da-18-1': {'seed':'runs/babel-dev3-da18-inputs-20260908/seed','paraphrase':'runs/babel-dev3-da18-inputs-20260908/paraphrase'},
}


def inventory(root):
    return {str(p.relative_to(root)):sha256_file(p) for p in root.rglob('*') if p.is_file() and not p.name.endswith('.lock')}


def exact_copy(source,destination):
    before=inventory(source)
    if not destination.exists():
        destination.parent.mkdir(parents=True,exist_ok=True)
        shutil.copytree(source,destination,copy_function=shutil.copyfile,symlinks=True)
    if inventory(destination)!=before:raise RuntimeError('input relocation differs: '+str(source))
    return before


def main():
    if not os.environ.get('SLURM_JOB_ID'):raise RuntimeError('Slurm required for compute-only input paths')
    canonical=yaml.safe_load((ROOT/'experiments/biomnibench-dev3.yaml').read_text())
    assert canonical['tasks']==list(SOURCES) and canonical['randomization']=={'seed':20260806,'replicates':3}
    production=yaml.safe_load((ROOT/'experiments/trace-attack-defense-v1/result20.yaml').read_text())
    configs=BUNDLE/SUBVERSION;configs.mkdir(exist_ok=True)
    tasks=RUN/'dev3/inputs/tasks'
    def copy_task(task):
        record=SOURCES[task];receipts={}
        for key in ['seed','paraphrase']:
            source=HOME_REPO/record[key];destination=RUN/'dev3/inputs'/task/key
            receipts[key]={'producer_root':str(source),'consumer_root':str(destination),
                           'files':exact_copy(source,destination)}
        source=HOME_REPO/'data/biomnibench-da'/task
        receipts['task']={'producer_root':str(source),'consumer_root':str(tasks/task),'files':exact_copy(source,tasks/task)}
        cfg=json.loads(json.dumps(production));cfg.pop('pretreatment_source',None)
        cfg.pop('execution_conditions',None);cfg.pop('execution_audit_models',None)
        cfg['tasks']=[task];cfg['tasks_dir']=str(tasks);cfg['randomization']=canonical['randomization']
        cfg['conditions']=[c for c in canonical['conditions'] if c['condition_id'] in ['full-red-team-trace','user-simulator-red-team-trace']]
        cfg['protocol']['red_team_trace_version']='attack_defense_v2.'+SUBVERSION
        for stage,key in [('seed','seed'),('paraphrase','paraphrase')]:cfg['dag'][stage]['output_dir']=str(RUN/'dev3/inputs'/task/key)
        cfg['dag']['revise']['output_dir']=str(RUN/'dev3'/SUBVERSION/task/'study/{experiment_id}')
        cfg['dag']['detect']['output_dir']=str(RUN/'dev3'/SUBVERSION/task/'not-launched-audit/{experiment_id}')
        path=configs/(task+'.yaml');path.write_text(yaml.safe_dump(cfg,sort_keys=False))
        exp=load_experiment(path)
        validate_paraphrase_run(Path(exp.dag['paraphrase']['output_dir']),exp)
        selection=resolve_paraphrase_selection(Path(exp.dag['paraphrase']['output_dir']),exp,task)
        receipts['selection']={'selected_sha256':selection.optimizer_sha256,'development_sha256':selection.development_sha256}
        seeds=[]
        for rep in range(1,4):
            seed=resolve_seed(Path(exp.dag['seed']['output_dir']),exp.task_dir(task),rep,seed_generator=exp.seed_agent_config(),
                prompt_profile=exp.protocol['prompt'],benchmark=exp.benchmark)
            seeds.append({'replicate':rep,'seed_sha256':seed.sha256})
        receipts['seeds']=seeds
        if 'source_config' in record:
            source_path=HOME_REPO/record['source_config'];original=load_experiment(source_path)
            candidate={**cfg,'pretreatment_source':{'experiment':str(source_path),'experiment_id':original.experiment_id,
                                                   'study_dir':str(HOME_REPO/record['source_study'])}}
            path.write_text(yaml.safe_dump(candidate,sort_keys=False))
            try:
                exp=load_experiment(path)
                runner=StudyRunner(StudyRunConfig(exp,Path(exp.dag['seed']['output_dir']),Path(exp.dag['paraphrase']['output_dir']),
                                                 RUN/'dev3/input-validation'/task,1))
                runner._prepare_pretreatment_rubric(task)
            except (ValueError,RuntimeError,FileNotFoundError) as exc:
                receipts['offline_reuse']={'compatible':False,'error_type':type(exc).__name__,'reason':str(exc),
                    'source_experiment':str(source_path),'source_study':str(HOME_REPO/record['source_study'])}
                path.write_text(yaml.safe_dump(cfg,sort_keys=False));exp=load_experiment(path)
            else:
                receipts['offline_reuse']={'compatible':True,'source_experiment':str(source_path),'source_experiment_id':original.experiment_id,
                    'source_study':str(HOME_REPO/record['source_study']),'validated_consumer_pool':str(runner.pretreatment_root),
                    'pool_files':inventory(runner.pretreatment_root)}
        else:
            receipts['offline_reuse']={'compatible':False,'reason':'Canonical da-18-1 preparation generated seeds/paraphrases only; no g1 exists in that source.'}
        receipts.update(task=task,experiment_id=exp.experiment_id,config=str(path),config_sha256=sha256_file(path),assignments=len(exp.execution_assignments))
        return receipts
    def forbidden(*args,**kwargs):raise RuntimeError('Provider calls prohibited during input compatibility inspection')
    RubricProposer._run_direct_proposer=forbidden
    with ThreadPoolExecutor(max_workers=3) as pool:receipts=list(pool.map(copy_task,SOURCES))
    result={'provider_calls':0,'job':os.environ['SLURM_JOB_ID'],'tasks':list(SOURCES),'randomization':canonical['randomization'],
            'assignments':sum(r['assignments'] for r in receipts),'per_task':receipts,
            'pool_layout':'Three native task-specific studies use their separate original producer pools, as documented in canonical INPUT_POOLS.md; no combined manifest is fabricated.'}
    write_json_atomic(BUNDLE/f'dev3-inputs-{SUBVERSION}.json',result)
    print(json.dumps({'assignments':result['assignments'],'provider_calls':0,'offline_reuse':{r['task']:r['offline_reuse'] for r in receipts}}),flush=True)


if __name__=='__main__':main()
