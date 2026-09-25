"""Read-only local usage estimate; deduplicate saved copies of provider calls."""
import json
from pathlib import Path
import sys


def snapshot(root):
    hosted = {}
    threads = {}

    def walk(value):
        if isinstance(value, dict):
            identity = value.get('response_id')
            usage = value.get('raw_usage') or value.get('provider_metadata', {}).get('usage')
            if identity and usage and 'input_tokens' in usage:
                hosted[identity] = usage
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    for p in root.rglob('*.json'):
        if any(x in p.parts for x in ['.agent-state', '.codex', 'codex', 'sessions']):
            continue
        if p.name == 'auth.json':
            continue
        try:
            walk(json.loads(p.read_text()))
        except (ValueError, OSError):
            continue
    for p in root.rglob('*.stream.jsonl'):
        thread = None
        for line in p.read_text().splitlines():
            try:
                event = json.loads(line)
            except ValueError:
                continue
            thread = event.get('thread_id', thread)
            usage = event.get('usage')
            if event.get('type') == 'turn.completed' and thread and usage:
                # SDK thread usage is cumulative, including across resumed turns.
                previous = threads.get(thread, {})
                if usage.get('input_tokens', 0) >= previous.get('input_tokens', 0):
                    threads[thread] = usage
    totals = dict(input_tokens=0, cached_input_tokens=0,
                  cache_write_input_tokens=0, output_tokens=0)
    for u in [*hosted.values(), *threads.values()]:
        details = u.get('input_tokens_details', {})
        totals['input_tokens'] += u.get('input_tokens', 0)
        totals['cached_input_tokens'] += u.get('cached_input_tokens', details.get('cached_tokens', 0))
        totals['cache_write_input_tokens'] += u.get('cache_write_input_tokens', details.get('cache_write_tokens', 0))
        totals['output_tokens'] += u.get('output_tokens', 0)
    uncached = max(0, totals['input_tokens'] - totals['cached_input_tokens'] - totals['cache_write_input_tokens'])
    usd = (uncached * .20 + totals['cached_input_tokens'] * .02
           + totals['cache_write_input_tokens'] * .25 + totals['output_tokens'] * 1.20) / 1e6
    return dict(root=str(root), hosted_responses=len(hosted), codex_threads=len(threads),
                **totals, estimated_usd=round(usd, 6),
                caveat='Saved usage only, not a billing invoice; missing failed-call usage is excluded. All calls assumed standard short-context gpt-5.6-luna.')


if __name__ == '__main__':
    print(json.dumps(snapshot(Path(sys.argv[1])), indent=2))
