import json
from pathlib import Path
from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.evolution import RubricProposer
from rubric_gen.submission_revision.study import StudyRunConfig, StudyRunner

BUNDLE = Path(__file__).resolve().parent
ROOT = Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/control-v21/input-validation')
TASKS = ('da-3-4', 'da-11-1', 'da-18-1')

def main():
    def forbidden(*args, **kwargs):
        raise AssertionError('provider call during control input validation')
    RubricProposer._run_direct_proposer = forbidden
    rows = []
    for task in TASKS:
        exp = load_experiment(BUNDLE/'control-v21'/f'{task}.yaml')
        if len(exp.execution_assignments) != 3 or any(a.condition_id != 'user-simulator-red-team-trace' for a in exp.execution_assignments):
            raise RuntimeError('invalid User-only scope')
        runner = StudyRunner(StudyRunConfig(exp, Path(exp.dag['seed']['output_dir']), Path(exp.dag['paraphrase']['output_dir']), ROOT/task, 1))
        runner._prepare_pretreatment_rubric(task)
        manifests = sorted(runner.pretreatment_root.glob('**/generation-0001/manifest.json'))
        if len(manifests) != 1:
            raise RuntimeError(f'{task}: expected one validated g1 manifest, found {len(manifests)}')
        rows.append({'task': task, 'experiment_id': exp.experiment_id, 'config_sha256': sha256_file(exp.path), 'g1_manifest': str(manifests[0]), 'g1_sha256': sha256_file(manifests[0])})
    out = BUNDLE/'control-input-validation.json'
    write_json_atomic(out, {'provider_calls': 0, 'tasks': rows, 'validated': True})
    print(json.dumps({'validated': True, 'provider_calls': 0, 'tasks': len(rows)}), flush=True)

if __name__ == '__main__': main()
