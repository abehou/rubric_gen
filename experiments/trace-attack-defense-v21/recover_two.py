"""Recover exactly the two v2 structural failures under v2.1."""
from __future__ import annotations
import json, os, subprocess, sys
from pathlib import Path
from dotenv import dotenv_values
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.study import StudyRunConfig, StudyRunner
from rubric_gen.submission_revision.execution_scope import terminal_records
from rubric_gen.submission_revision.study_validation import validate_completed_revision

BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
RUN = Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20')
COMPAT = ROOT/'docs/reports/2026-09-11/trace-attack-defense-v2.1/compatibility-118.json'
TARGETS = {
    'da-15-2--rep-002--solver-luna--full-red-team-trace',
    'da-14-8--rep-003--solver-luna--user-simulator-red-team-trace',
}

def main():
    if not os.environ.get('SLURM_JOB_ID') or int(os.environ.get('SLURM_CPUS_PER_TASK','0')) != 32:
        raise RuntimeError('two-assignment recovery requires one 32-CPU Slurm allocation')
    compat = json.loads(COMPAT.read_bytes())
    if not compat.get('gate', {}).get('passed') or compat.get('compatible_assignments') != 118:
        raise RuntimeError('118-assignment compatibility gate is not passed')
    exp = load_experiment(BUNDLE/'result20.yaml')
    ids = tuple(a.assignment_id for a in exp.execution_assignments if a.assignment_id in TARGETS)
    if set(ids) != TARGETS or len(ids) != 2:
        raise RuntimeError(f'recovery target identity differs: {ids}')
    credentials = dotenv_values('/home/aydanh/repos/rubric_gen/.env.local')
    for key in ('OPENAI_API_KEY','ANTHROPIC_API_KEY'):
        if not credentials.get(key): raise RuntimeError(f'missing credential: {key}')
        os.environ[key] = str(credentials[key])
    study = Path(str(exp.dag['revise']['output_dir']))
    seed = Path(str(exp.dag['seed']['output_dir']))
    paraphrase = Path(str(exp.dag['paraphrase']['output_dir']))
    # The preparation stage only validates/reuses frozen inputs; it cannot call a provider.
    prep = RUN/'input-validation'/'completion.json'
    if not prep.is_file():
        subprocess.run([sys.executable, str(BUNDLE/'prepare.py')], check=True)
    runner = StudyRunner(StudyRunConfig(exp, seed, paraphrase, study, 32,
                                        resume=study.exists(), assignment_ids=ids))
    code = runner.run()
    if code:
        raise RuntimeError('v2.1 two-assignment recovery failed; outputs retained')
    ledger = json.loads((study/'study.json').read_bytes())
    rows = [r for r in ledger['records'] if r['assignment_id'] in TARGETS]
    if len(rows) != 2 or any(r.get('status') != 'completed' for r in rows):
        raise RuntimeError('v2.1 recovery did not complete both assignments')
    by_id = {a.assignment_id:a for a in exp.execution_assignments}
    validation = []
    for row in rows:
        assignment = by_id[row['assignment_id']]
        root = study / row['experiment_dir']
        validate_completed_revision(root, assignment, exp, seed, paraphrase)
        manifest = json.loads((root/'manifest.json').read_bytes())
        validation.append({'assignment_id': row['assignment_id'], 'root': str(root),
                           'manifest_sha256': __import__('hashlib').sha256((root/'manifest.json').read_bytes()).hexdigest(),
                           'implementation_sha256': manifest['rubric_generation_implementation_sha256'],
                           'red_team_trace_version': manifest['red_team_trace_version']})
    write_json_atomic(RUN/'recovery-v21.json', {
        'kind':'attack_defense_v2.1_two_assignment_recovery', 'job':os.environ['SLURM_JOB_ID'],
        'consumer_experiment_id':exp.experiment_id, 'compatibility_receipt':str(COMPAT),
        'targets':sorted(TARGETS), 'completed':2, 'provider_calls_authorized':True,
        'validation':validation, 'source_failures_preserved':True,
        'mechanical_reason':'candidate-local duplicate_criterion_title guard; no scientific prompt or gate change',
    })
    print(json.dumps({'completed':2,'study':str(study),'experiment_id':exp.experiment_id}), flush=True)

if __name__ == '__main__': main()
