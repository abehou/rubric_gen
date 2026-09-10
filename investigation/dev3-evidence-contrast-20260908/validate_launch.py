"""No-provider native input/config/source acceptance for a prepared policy arm."""
import hashlib, importlib.util, json, os, subprocess
from pathlib import Path
import yaml
from rubric_gen.runtime.paths import PROJECT_ROOT
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.seeds import resolve_seed
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run
ROOT=Path('/home/aydanh/repos/rubric_gen'); BUNDLE=Path(__file__).parent
assert os.environ.get('SLURM_JOB_ID')
def sha(p):return hashlib.sha256(Path(p).read_bytes()).hexdigest()
prior=ROOT/'runs/dev3-evidence-contrast-check-10363823/result.json'
checked=json.loads(prior.read_text());assert checked['test_exit']==0 and checked['source_unchanged'] and checked['non_induction_ast_equal']
for p,h in checked['source_hashes'].items():assert sha(p)==h
commit=subprocess.check_output(['git','rev-parse','HEAD'],cwd=PROJECT_ROOT,text=True).strip();assert commit.startswith('59fb4d0')
rows=[]
for task in ['da-3-4','da-11-1','da-18-1']:
    p=BUNDLE/f'contrast-{task}.yaml'; old=ROOT/f'investigation/dev3-evidence-sidecar-20260908/evidence-{task}.yaml'
    a=yaml.safe_load(p.read_text());b=yaml.safe_load(old.read_text())
    for stage in ('revise','detect'):
        assert a['dag'][stage]['output_dir']!=b['dag'][stage]['output_dir']
        a['dag'][stage]['output_dir']=b['dag'][stage]['output_dir']
    assert a==b,'Scientific configuration changed'
    exp=load_experiment(p);assert len(exp.execution_assignments)==3 and exp.replicates==3
    for rep in range(1,4):resolve_seed(Path(exp.dag['seed']['output_dir']),exp.task_dir(task),rep,seed_generator=exp.seed_agent_config(),prompt_profile=exp.protocol['prompt'],benchmark=exp.benchmark)
    validate_paraphrase_run(Path(exp.dag['paraphrase']['output_dir']),exp)
    rows.append(dict(task=task,config=str(p),config_sha256=sha(p),native_seed_count=3,native_paraphrases_valid=True))
receipt=dict(success=True,arm='contrast',commit=commit,inputs=rows,source_hashes=checked['source_hashes'],prior_validation_sha256=sha(prior),job=os.environ['SLURM_JOB_ID'])
out=ROOT/f'runs/dev3-evidence-contrast-launchcheck-{os.environ["SLURM_JOB_ID"]}';out.mkdir(exist_ok=False)
# The acceptance file authorizes no launch by itself; the scientific decision remains separate.
acceptance=BUNDLE/'acceptance.json';assert not acceptance.exists();acceptance.write_text(json.dumps(receipt,indent=2)+'\n')
try:
    spec=importlib.util.spec_from_file_location('contrast_launcher',BUNDLE/'condition_launch.py');module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    for task in ('da-3-4','da-11-1','da-18-1'):assert len(module.gate('contrast',task)[0].execution_assignments)==3
    for arm,task in [('control','da-11-1'),('contrast','new-task')]:
        try:module.gate(arm,task)
        except ValueError:pass
        else:raise AssertionError('Invalid scope accepted')
    original=module.sha
    for fragment,reason in [('/src/','source changed'),('contrast-da-11-1.yaml','config changed')]:
        module.sha=lambda p,fragment=fragment:'0'*64 if fragment in str(p) else original(p)
        try:module.gate('contrast','da-11-1')
        except RuntimeError as e:assert reason in str(e)
        else:raise AssertionError('Changed identity accepted')
        finally:module.sha=original
    for p,h in checked['source_hashes'].items():assert sha(p)==h
except BaseException:
    receipt['success']=False;acceptance.write_text(json.dumps(receipt,indent=2)+'\n');raise
(out/'result.json').write_text(json.dumps(dict(success=True,acceptance_sha256=sha(acceptance),launcher_sha256=sha(BUNDLE/'condition_launch.py'),sbatch_sha256=sha(BUNDLE/'condition.sbatch'),job=os.environ['SLURM_JOB_ID']),indent=2)+'\n')
print('Three native task pools and matched configs validated; source/config/scope rejection checks passed.')
