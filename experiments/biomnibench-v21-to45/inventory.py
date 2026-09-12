"""Read-only, metadata-only inventory for queue item 1; run on a compute node."""
import json
import os
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
HOME_REPO = Path('/home/aydanh/repos/rubric_gen')
SHARED = Path('/data/user_data/aydanh/rubric_gen')
OUT = ROOT / 'docs/reports/2026-09-12/biomnibench-v21-to45'


def read(path):
    return json.loads(path.read_text()) if path.is_file() else None


def listing(path):
    return sorted(p.name for p in path.iterdir()) if path.is_dir() else None


membership_path = HOME_REPO / 'investigation/biomnibench-results45-20260908/inventory.json'
membership = read(membership_path)
data_root = SHARED / 'data/biomnibench-da-results45-e1c8ca5e11a6'
historical_data = read(HOME_REPO / 'runs/confirmation-data-validated-10372829/result.json')
size_mismatches = []
for item in historical_data['files']:
    path = data_root / item['path']
    actual = path.stat().st_size if path.is_file() else None
    if actual != item['size']:
        size_mismatches.append({'path': str(path), 'expected_bytes': item['size'], 'actual_bytes': actual})

pools = {}
for label, path in {
    'historical_original20': SHARED / 'pools/paraphrases/biomnibench/confirmation-20260909/original20',
    'historical_additional25': SHARED / 'pools/paraphrases/biomnibench/confirmation-20260909/additional25',
    'canonical_v2_result20': SHARED / 'pools/paraphrases/biomnibench/result20-prompt-nofallback-v2-20260910',
}.items():
    manifest = read(path / 'manifest.json')
    tasks = listing(path / 'tasks') or []
    pools[label] = {'path': str(path), 'manifest': manifest, 'tasks': tasks,
                    'variant_text_counts': {task: len(list((path/'tasks'/task).glob('variant-*.txt'))) for task in tasks}}

accounting = read(ROOT / 'docs/reports/2026-09-11/trace-attack-defense-v2.1/accounting.json')
stages = {}
for name, info in accounting['stages'].items():
    payload = read(Path(info['path']))
    stages[name] = {'path': info['path'], 'present': payload is not None,
                    'reported_planned': info['planned_unique'], 'reported_completed': info['completed_unique'],
                    'saved_status_fields': {k: payload[k] for k in ('status', 'planned_judgments', 'completed_judgments', 'failed_judgments', 'coverage', 'assignment_coverage') if payload and k in payload}}

control_root = SHARED / 'runs/trace-attack-defense-v3-20260911/control-v21-compatible'
control = {'path': str(control_root), 'top_level': listing(control_root), 'task_directories': {}}
for task in membership['dev3_excluded']:
    control['task_directories'][task] = {'top_level': listing(control_root/task),
        'study_ids': listing(control_root/task/'study'), 'audit_ids': listing(control_root/task/'audit')}

result = {
    'observed_at': datetime.now().astimezone().isoformat(), 'job_id': os.environ['SLURM_JOB_ID'],
    'hostname': os.uname().nodename, 'provider_calls': 0, 'operation': 'read-only metadata inventory; no content rehashing',
    'membership_source': str(membership_path),
    'membership': {k: membership[k] for k in ('revision', 'selection', 'original20', 'dev3_excluded', 'additional25', 'results45', 'remaining_unselected', 'conditions', 'replicates', 'assignments', 'status')},
    'data': {'path': str(data_root), 'task_directories': listing(data_root),
        'historically_validated_files': len(historical_data['files']), 'size_mismatches': size_mismatches,
        'tasks': {task: {rel: (data_root/task/rel).is_file() for rel in ('instruction.md','task.toml','tests/rubric.txt')} for task in membership['results45']}},
    'paraphrase_pools': pools,
    'seed_locations': {str(path): listing(path) for path in (
        SHARED / 'seeds/biomnibench/confirmation-20260909',
        SHARED / 'runs/trace-attack-defense-v1-20260910/inputs/seeds')},
    'result20': {'completion': read(Path(accounting['completion_path'])), 'stages': stages},
    'canonical_user_control': control,
    'top_level_run_names': listing(SHARED/'runs'),
    'paraphrase_pool_names': listing(SHARED/'pools/paraphrases/biomnibench'),
    'storage_available_bytes': os.statvfs(SHARED).f_bavail * os.statvfs(SHARED).f_frsize,
}
OUT.mkdir(parents=True, exist_ok=True)
(OUT/'inventory.json').write_text(json.dumps(result, indent=2)+'\n')
print(json.dumps({'tasks': len(result['data']['tasks']), 'file_size_mismatches': len(size_mismatches),
    'paraphrase_task_counts': {k: len(v['tasks']) for k,v in pools.items()},
    'result20_summary_files_present': sum(v['present'] for v in stages.values()), 'provider_calls': 0}))
