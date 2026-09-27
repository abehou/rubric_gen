"""Prepare the authorized Semi/Score-only extension without provider calls.

Use an isolated source snapshot so the two original Result20 solver/sidecar
prompts can be retained without overwriting the later v6 working-tree changes.
All other source, including the corrected RH detector, comes from this checkout.
"""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile

import yaml
from rubric_gen.runtime.process_environment import controlled_process_environment

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
OUTPUT = ROOT / 'runs/healthbench-hard-result20-semi-score-20260926'
RESTORED = ('src/rubric_gen/benchmarks/answer_only/contract.py',
            'src/rubric_gen/submission_revision/red_team.py')


def main():
    if (OUTPUT / 'invocations').exists():
        raise FileExistsError(f'Cannot change source after launch: {OUTPUT}')
    OUTPUT.mkdir(parents=True, exist_ok=True)
    source = OUTPUT / 'runtime-source'
    shutil.copytree(ROOT / 'src', source / 'src',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc'), dirs_exist_ok=True)
    with tarfile.open(ROOT / 'output/healthbench-result20-preparation/source.tar.gz') as archive:
        for name in RESTORED:
            (source / name).write_bytes(archive.extractfile(name).read())
    payload = yaml.safe_load((HERE / 'local.yaml').read_text())
    original_study = 'healthbench-hard-factorial-r3-01eb8a5a9277'
    payload['pretreatment_source'] = {
        'experiment': str(HERE / 'local.yaml'),
        'study_dir': str(ROOT / 'runs/healthbench-hard-challenge20-local-20260926/studies' / original_study),
        'experiment_id': original_study,
    }
    payload['conditions'] = [
        {'condition_id': f'{policy.replace("_", "-")}-{label}', 'feedback_policy': policy, 'rubric_policy': rubric}
        for policy in ('semi', 'score_only')
        for label, rubric in (('static', 'fixed'), ('red-team-trace', 'red_team_trace'))
    ]
    for stage, folder in (('revise', 'studies/{experiment_id}'), ('detect', 'audits/{experiment_id}')):
        payload['dag'][stage]['output_dir'] = str(OUTPUT / folder)
    config = HERE / 'remaining.yaml'
    config.write_text(yaml.safe_dump(payload, sort_keys=False))
    shutil.copy2(config, OUTPUT / 'experiment.yaml')
    env = controlled_process_environment()
    env.update(PYTHONPATH=str(source / 'src'), RUBRIC_GEN_PROJECT_ROOT=str(ROOT))
    # Native input validation and sealed pool copying only. Source reuse makes
    # generation impossible here; no seed, paraphrase, or proposer is dispatched.
    check = '''
from pathlib import Path
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.study import StudyRunner, StudyRunConfig
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run
from rubric_gen.runtime.process_environment import install_controlled_process_environment
install_controlled_process_environment()
import sys
e=load_experiment(Path(sys.argv[1]))
assert len(e.assignments)==240
validate_paraphrase_run(Path(e.dag['paraphrase']['output_dir']), e)
r=StudyRunner(StudyRunConfig(e,Path(e.dag['seed']['output_dir']),Path(e.dag['paraphrase']['output_dir']),Path(e.dag['revise']['output_dir']),6,True))
assert r.pretreatment_source_root is not None
for task in e.task_ids:
    r._prepare_pretreatment_rubric(task)
if not (r.root/'study.json').exists():
    r._write_manifest(r._new_manifest(sorted(e.assignments,key=lambda a:a.execution_order)))
print(e.experiment_id, '240 assignments; 20 reused pretreatments validated; no API calls')
'''
    subprocess.run([sys.executable, '-c', check, str(config)], cwd=ROOT, env=env, check=True)
    (OUTPUT / 'preparation.json').write_text(json.dumps({
        'restored_original_result20_files': RESTORED,
        'other_source': 'current checkout, including RH answer-only guidance',
        'scope': 'Semi/Score-only x Static/RTT, same 20 tasks, 3 replicates, 3 rounds',
        'source_study': original_study,
        'git_head': subprocess.check_output(['git','rev-parse','HEAD'],cwd=ROOT,env=env,text=True).strip(),
    }, indent=2)+'\n')
    (OUTPUT / 'source.diff').write_bytes(subprocess.check_output(['git','diff','--binary'],cwd=ROOT,env=env))


if __name__ == '__main__':
    main()
