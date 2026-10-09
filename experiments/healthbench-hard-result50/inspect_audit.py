"""Read-only compact audit progress, coverage and accounting inspection."""
import json
from collections import Counter
from pathlib import Path
from prepare import OUTPUT


def inspect():
    run = OUTPUT/'audit-run'
    receipts = sorted((run/'invocations').glob('*/receipt.json'))
    receipt = json.loads(receipts[-1].read_text())
    audit = OUTPUT/'audits'/receipt['experiment_id']
    result = {'invocation': receipts[-1].parent.name, 'status': receipt['status'],
              'owner_pid': receipt['pid'], 'budget': json.loads((run/'budget.json').read_text()), 'stages': {}}
    result['budget']['pending_count'] = len(result['budget'].pop('pending'))
    for folder in sorted(audit.glob('*')):
        if not folder.is_dir():
            continue
        entry = {'records': len(list((folder/'records').glob('*.json'))),
                 'summary': (folder/'summary.json').exists()}
        if folder.name.startswith('direct_'):
            entry['records'] = len(list(folder.glob('evaluations/*/cases/*/gpt-6-luna/score.json')))
            entry['summary'] = bool(list(folder.glob('evaluations/*/summary.json')))
        manifest = folder/'manifest.json'
        if manifest.exists():
            data = json.loads(manifest.read_text())
            jobs = data.get('predispatch_plan', {}).get('jobs', [])
            entry['planned_jobs'] = len(jobs)
            if jobs:
                entry['instruments'] = dict(Counter(j.get('instrument', 'rubric') for j in jobs))
        result['stages'][folder.name] = entry
    log = receipts[-1].parent/'detect.log'
    lines = log.read_text().replace('\r', '\n').splitlines()
    result['last_events'] = [line[:700] for line in lines if '[rubric-gen]' in line or 'audit_' in line or 'Traceback' in line or 'Error:' in line][-8:]
    result['last_progress'] = next((line[-500:] for line in reversed(lines) if '/720' in line or 'judgment' in line), '')
    print(json.dumps(result, indent=2), flush=True)


if __name__ == '__main__':
    inspect()
