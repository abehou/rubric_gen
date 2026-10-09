"""In-conversation read-only observer; never starts or changes provider work."""
import json
import os
import time
from datetime import datetime, timezone
from prepare import OUTPUT


def snapshot():
    run = OUTPUT/'audit-run'
    receipt = json.loads(sorted((run/'invocations').glob('*/receipt.json'))[-1].read_text())
    budget = json.loads((run/'budget.json').read_text())
    audit = OUTPUT/'audits'/receipt['experiment_id']
    counts = {p.name: len(list(p.glob('evaluations/*/cases/*/gpt-6-luna/score.json')))
              if p.name.startswith('direct_') else len(list(p.glob('records/*.json')))
              for p in audit.iterdir() if p.is_dir()}
    try:
        os.kill(receipt['pid'], 0)
        live = True
    except ProcessLookupError:
        live = False
    return dict(time_utc=datetime.now(timezone.utc).isoformat(), status=receipt['status'], owner_live=live,
                known_usd=round(budget['known_usage_cost_usd'],6),
                unknown_reserved_usd=round(budget['unknown_usage_reserved_usd'],6), unknown=budget['uncertain'],
                pending=len(budget['pending']), counts=counts, total_saved=sum(counts.values()))


def main():
    while True:
        try:
            state = snapshot()
            print(json.dumps(state), flush=True)
            if state['status'] != 'running' or not state['owner_live']:
                break
        except json.JSONDecodeError:
            time.sleep(1)
            continue
        time.sleep(55)


if __name__ == '__main__':
    main()
