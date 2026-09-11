from pathlib import Path
import yaml

ROOT = Path(__file__).parents[2]
BASE = ROOT / 'experiments/trace-attack-defense-v2/dev2'
OUT = ROOT / 'experiments/trace-attack-defense-v3/control-v21'
RUN = Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/control-v21')
TASKS = ('da-3-4', 'da-11-1', 'da-18-1')
IDS = {
    'da-3-4': 'biomnibench-da-factorial-r10-74544aac853c',
    'da-11-1': 'biomnibench-da-factorial-r10-f40745c90cec',
    'da-18-1': 'biomnibench-da-factorial-r10-6ed1de5b0905',
}

def main():
    OUT.mkdir(parents=True, exist_ok=True)
    for task in TASKS:
        value = yaml.safe_load((BASE / f'{task}.yaml').read_text())
        value['protocol']['red_team_trace_version'] = 'attack_defense_v2.1'
        value['execution_conditions'] = ['user-simulator-red-team-trace']
        value['execution_audit_models'] = ['gpt-5.6-sol', 'claude-opus-5']
        value['dag']['revise']['output_dir'] = str(RUN / task / 'study/{experiment_id}')
        value['dag']['detect']['output_dir'] = str(RUN / task / 'audit/{experiment_id}')
        source_cfg = (BASE / f'{task}.yaml').resolve()
        source_study = Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910/dev3/dev2') / task / 'study' / IDS[task]
        value['pretreatment_source'] = {
            'experiment': str(source_cfg),
            'experiment_id': IDS[task],
            'study_dir': str(source_study),
        }
        (OUT / f'{task}.yaml').write_text(yaml.safe_dump(value, sort_keys=False))

if __name__ == '__main__':
    main()
