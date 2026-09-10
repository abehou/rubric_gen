from pathlib import Path
import json,os,copy,yaml,hashlib
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.study import StudyRunner,StudyRunConfig
from rubric_gen.submission_revision.evolution import RubricProposer
ROOT=Path('/home/aydanh/repos/rubric_gen');job=os.environ['SLURM_JOB_ID'];out=ROOT/f'runs/cue-frozen-integrated-{job}';out.mkdir(exist_ok=False)
source_yaml=ROOT/'investigation/result20-cue-contrast-20260908/trace-results20.yaml';source=load_experiment(source_yaml)
study=ROOT/'runs/babel-result20-cue-contrast-20260908/trace/study/biomnibench-da-factorial-r10-f0203f5d69f3'
payload=yaml.safe_load(source_yaml.read_text());payload['pretreatment_source']=dict(experiment=str(source_yaml),study_dir=str(study),experiment_id=source.experiment_id)
config=out/'consumer.yaml';config.write_text(yaml.safe_dump(payload,sort_keys=False));consumer=load_experiment(config)
def forbidden(*a,**kw):raise AssertionError('provider call forbidden in input integration')
RubricProposer._run_direct_proposer=forbidden
runner=StudyRunner(StudyRunConfig(consumer,Path(consumer.dag['seed']['output_dir']),Path(consumer.dag['paraphrase']['output_dir']),out/'consumer',60))
for task in consumer.task_ids:runner._prepare_pretreatment_rubric(task)
receipts=list((out/'consumer/pretreatment-input-receipts').glob('*.json'));assert len(receipts)==20
before={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (out/'consumer').rglob('*') if p.is_file()}
for task in consumer.task_ids:runner._prepare_pretreatment_rubric(task)
assert before=={str(p):hashlib.sha256(p.read_bytes()).hexdigest() for p in (out/'consumer').rglob('*') if p.is_file()}
(out/'result.json').write_text(json.dumps(dict(job_id=job,tasks=20,resume_unchanged=True,consumer_experiment_id=consumer.experiment_id,receipts=[str(p) for p in receipts]),indent=2)+'\n');print('20 inputs installed and revalidated; no providers; unchanged resume')
