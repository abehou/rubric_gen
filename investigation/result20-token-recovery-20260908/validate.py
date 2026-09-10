import hashlib,json,os,subprocess,sys
from pathlib import Path
ROOT=Path('/home/aydanh/repos/rubric_gen')
OLD=ROOT/'runs/babel-code/result20-capacity-v3'
PARENT=ROOT/'runs/babel-code/result20-telemetry-runtime'
NEW=ROOT/'runs/babel-code/result20-token-runtime'
OUT=ROOT/f'runs/result20-token-validation-{os.environ["SLURM_JOB_ID"]}'
OUT.mkdir(exist_ok=False)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
paths=sorted(p.relative_to(PARENT) for p in (PARENT/'src').rglob('*.py'))
changed=[str(p) for p in paths if sha(PARENT/p)!=sha(NEW/p)]
assert changed==['src/rubric_gen/runtime/capacity.py'],changed
before={str(p):sha(NEW/p) for p in paths}
with (OUT/'tests.log').open('w') as log:
 subprocess.run([sys.executable,'-m','pytest','-q','tests/test_runtime_capacity.py','tests/test_runtime_token_rate.py','tests/test_rubric_evolution.py','tests/test_red_team.py','tests/test_pretreatment_reuse.py'],cwd=NEW,stdout=log,stderr=subprocess.STDOUT,check=True)
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.study_validation import validate_completed_revision
from rubric_gen.submission_revision.study import StudyRunner, StudyRunConfig
from rubric_gen.submission_revision.evolution import RubricProposer, rubric_generation_implementation_sha256
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.runtime.paths import PROJECT_ROOT
assert PROJECT_ROOT.resolve() == NEW.resolve()
# The experiment configuration retains its real, immutable original pathname;
# only the executing code checkout differs. Never rewrite the study identity.
exp = load_experiment(OLD/'experiments/babel/biomnibench-result20-capacity-user-trace.yaml')
assert exp.experiment_id == 'biomnibench-da-factorial-r10-bfbdd0f9833c'
study = Path(exp.dag['revise']['output_dir'])
assert study == ROOT/'runs/babel-result20-capacity-v3-20260908/user-trace/study'/exp.experiment_id
assignments = {a.assignment_id:a for a in exp.execution_assignments}
manifest = json.loads((study/'study.json').read_text())
runner = StudyRunner(StudyRunConfig(experiment=exp,output_dir=study,
    seed_run_dir=Path(exp.dag['seed']['output_dir']),
    paraphrase_run_dir=Path(exp.dag['paraphrase']['output_dir']),max_concurrency=60,resume=True))
# This validator is read-only; do not call run or _start_manifest on owned work.
runner._validate_manifest_identity(manifest,list(exp.assignments))
records = manifest['records']
complete = [r for r in records if r['status']=='completed' and r['assignment_id'] in assignments]
assert len(complete) == 60
verified = []
for record in complete:
    directory = study/record['experiment_dir']
    snapshots = {name:sha(directory/name) for name in ('manifest.json','state.json')}
    validate_completed_revision(directory,assignments[record['assignment_id']],exp,
        Path(exp.dag['seed']['output_dir']),Path(exp.dag['paraphrase']['output_dir']))
    assert snapshots == {name:sha(directory/name) for name in snapshots}
    verified.append(dict(assignment_id=record['assignment_id'],hashes=snapshots))
(OUT/'native-validation.json').write_text(json.dumps(dict(success=True,completed=verified,
    generation_implementation_sha256=rubric_generation_implementation_sha256()),indent=2)+'\n')


assert before=={str(p):sha(NEW/p) for p in paths}
(OUT/'result.json').write_text(json.dumps(dict(success=True,source_commit=subprocess.check_output(['git','-C',str(NEW),'rev-parse','HEAD'],text=True).strip(),source_hashes=before,native_completed=len(verified),changed_files=changed),indent=2)+'\n')
print('Token pacing source/tests/native60 validation passed')
