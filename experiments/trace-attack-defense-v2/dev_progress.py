"""Read-only dev3 execution progress; never requests a judgment."""
from collections import Counter
import json
import os
from pathlib import Path
import sys
from rubric_gen.submission_revision.experiment import load_experiment


def main(subversion):
    bundle = Path(__file__).resolve().parent
    status, stages, errors = Counter(), Counter(), []
    for task in ('da-3-4', 'da-11-1', 'da-18-1'):
        config = load_experiment(bundle/subversion/(task+'.yaml'))
        root = Path(config.dag['revise']['output_dir'])
        manifest = root/'study.json'
        if not manifest.exists():
            continue
        ledger = json.loads(manifest.read_bytes())
        for record in ledger['records']:
            status[record['status']] += 1
            if record['status'] == 'failed':
                errors.append(record)
            directory = root/record['experiment_dir']
            stages['sealed_submissions'] += len(list((directory/'submissions').glob('s*/manifest.json')))
            stages['solver_prompts'] += len(list((directory/'turns').glob('turn-*/prompt.txt')))
            stages['online_generations'] += len(list((directory/'rubric-generations').glob('generation-*/evolution.json')))
            for path in (directory/'rubric-generations').glob('generation-*/evolution.json'):
                if int(path.parent.name.split('-')[-1]) < 2:
                    stages['online_generations'] -= 1
                else:
                    evolution = json.loads(path.read_bytes())
                    stages['online_admitted_rules'] += len(evolution.get('accepted_candidate_ids', []))
    print(json.dumps({'method': subversion, 'status': dict(status), 'stages': dict(stages), 'failed_records': errors}), flush=True)


if __name__ == '__main__':
    if not os.environ.get('SLURM_JOB_ID'):
        raise RuntimeError('compute storage requires Slurm')
    main(sys.argv[1])
