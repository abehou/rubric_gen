"""Validate a telemetry-only source against native completed work, without mutation."""
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OLD = ROOT / 'runs/babel-code/result20-capacity-v3'
NEW = ROOT / 'runs/babel-code/result20-telemetry-runtime'
OUT = ROOT / f'runs/result20-telemetry-acceptance-{os.environ["SLURM_JOB_ID"]}'
OUT.mkdir(exist_ok=False)
def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

paths = sorted(p.relative_to(OLD) for p in (OLD / 'src').rglob('*.py'))
assert paths == sorted(p.relative_to(NEW) for p in (NEW / 'src').rglob('*.py'))
changed = [str(p) for p in paths if sha(OLD/p) != sha(NEW/p)]
assert changed == ['src/rubric_gen/runtime/capacity.py'], changed
accepted = json.loads((ROOT/'investigation/telemetry-journal-20260908/acceptance.json').read_text())
assert accepted['success'] and accepted['passed_tests'] == 112
assert sha(NEW/changed[0]) == accepted['source_hashes'][changed[0]]
for rel in ('uv.lock', 'pyproject.toml', 'config/runtime.json',
            'experiments/babel/biomnibench-result20-capacity-user-trace.yaml'):
    assert sha(NEW/rel) == sha(OLD/rel), rel
before = {str(p):sha(NEW/p) for p in paths}
source_commit = subprocess.check_output(['git','-C',str(NEW),'rev-parse','HEAD'],text=True).strip()
tests = ['test_runtime_capacity.py','test_babel_runtime_evidence.py','test_babel_launcher.py',
         'test_architecture.py','test_rubric_evolution.py','test_red_team.py','test_pretreatment_reuse.py']
command = [sys.executable,'-m','pytest','-q',*[f'tests/{t}' for t in tests],f'--junitxml={OUT/"tests.xml"}']
(OUT/'launch.json').write_text(json.dumps(dict(job_id=os.environ['SLURM_JOB_ID'],
    host=socket.gethostname(),source_commit=source_commit,source_hashes=before,
    changed_source_files=changed,command=command),indent=2)+'\n')
with (OUT/'tests.log').open('w') as log:
    subprocess.run(command,cwd=NEW,stdout=log,stderr=subprocess.STDOUT,check=True)

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
assert len(complete) >= 58
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

from dotenv import dotenv_values
credentials = dotenv_values(ROOT/'.env.local')
assert credentials.get('OPENAI_API_KEY')
os.environ['OPENAI_API_KEY'] = credentials['OPENAI_API_KEY']
del credentials
contract = RubricProposer(benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,
    model='gpt-5.6-luna',max_retries=0).proposer_contract
def probe(index):
    started = time.monotonic()
    response = contract.generate(instructions='Return the required JSON with runtime_ok true.',
        evidence='Non-scientific telemetry runtime check.',
        response_schema={'type':'object','properties':{'runtime_ok':{'type':'boolean'}},
                         'required':['runtime_ok'],'additionalProperties':False},
        request_context='authorized telemetry runtime check',schema_name='runtime_telemetry')
    contract.validate_output(response)
    assert json.loads(response.response_text) == {'runtime_ok':True}
    (OUT/f'probe-{index}.json').write_text(json.dumps(asdict(response),indent=2)+'\n')
    return dict(effective_model=response.generation['effective_model'],seconds=time.monotonic()-started)
result = dict(success=False,source_commit=source_commit,native_completed=len(verified),
              contract=contract.record(),scope='Two non-scientific provider calls under shared60; no experiment cell launched or restarted')
try:
    with ThreadPoolExecutor(max_workers=2) as pool:
        result['calls'] = list(pool.map(probe,range(2)))
    result['source_unchanged'] = before == {str(p):sha(NEW/p) for p in paths}
    result['success'] = result['source_unchanged']
except Exception as exc:
    result.update(error_type=type(exc).__name__,http_status=getattr(exc,'status_code',None))
(OUT/'result.json').write_text(json.dumps(result,indent=2)+'\n')
raise SystemExit(0 if result['success'] else 1)
