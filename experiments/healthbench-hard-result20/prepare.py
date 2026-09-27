"""Materialize reviewed source IDs and the local shared-queue study; no model calls."""
import argparse
import json
from pathlib import Path
import yaml

from rubric_gen.runtime.process_environment import install_controlled_process_environment
from rubric_gen.benchmarks.answer_only.dataset import prepare, HEALTHBENCH_URL

install_controlled_process_environment()
HERE = Path(__file__).resolve().parent
PERSISTENT = HERE.parents[1] / 'runs/healthbench-hard-challenge20-local-20260926'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--source', type=Path, required=True)
    args = parser.parse_args()
    selection = json.loads((HERE / 'selection.json').read_text())
    ids = [r[0] for r in selection['tasks']]
    repo = HERE.parents[1]
    excluded = {json.loads(p.read_text())['source_id']
                for p in (repo / 'data/healthbench-hard').glob('*dev3*/*/tests/source.json')}
    assert len(ids) == len(set(ids)) == 20 and not excluded.intersection(ids)
    rows = [json.loads(x) for x in args.source.read_bytes().split(b'\n') if x.strip()]
    destination = repo / 'data/healthbench-hard/challenge20-20260926'
    if not destination.exists():
        prepare(rows, destination, benchmark='healthbench-hard', subset='result20',
                source=HEALTHBENCH_URL, selected_source_ids=ids)
    manifest = json.loads((destination / 'manifest.json').read_text())
    assert [t['source_id'] for t in manifest['tasks']] == ids
    base = yaml.safe_load((HERE.parent / 'healthbench-hard-local-mac/dev3-v5.yaml').read_text())
    base['tasks_dir'] = str(PERSISTENT / 'tasks')
    base['outcome_audit']['rubric_free_models'] = ['gpt-6-sol']
    base['tasks'] = [t['task_id'] for t in manifest['tasks']]
    for stage,folder in [('seed','seeds'),('paraphrase','paraphrases'),('revise','studies/{experiment_id}'),('detect','audits/{experiment_id}')]:
        base['dag'][stage]['output_dir'] = str(PERSISTENT / folder)
    (HERE / 'local.yaml').write_text(yaml.safe_dump(base,sort_keys=False))
    print(json.dumps({'task_count':20,'source_ids_disjoint_from_dev':True,
                      'dataset':str(destination),'persistent_root':str(PERSISTENT)}))


if __name__ == '__main__':
    main()
