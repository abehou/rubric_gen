"""Private read-only simulator exposure audit after complete outcome reconstruction."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
from statistics import mean


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def exposure(rows):
    cases = {}
    for row in rows:
        path = Path(row['state_path'])
        key = (row['analysis_condition'], row['assignment_id'])
        assert digest(path) == row['state_sha256'], 'state changed since complete analysis'
        if key in cases:
            continue
        root = path.parent
        feedback = []
        for p in sorted((root / 'feedback').glob('*.json')):
            value = json.loads(p.read_text())
            if 'decision' not in value or 'concerns' not in value:
                continue
            feedback.append(dict(checkpoint=p.stem, decision=value['decision'],
                concern_count=len(value['concerns']),
                concern_characters=sum(len(c['feedback']) for c in value['concerns']),
                categories=[c['category'] for c in value['concerns']],
                concern_hashes=[hashlib.sha256(c['feedback'].encode()).hexdigest() for c in value['concerns']],
                absolute_app_mentions=sum('/app/' in c['feedback'] for c in value['concerns']),
                path=str(p), sha256=digest(p)))
        if not feedback:
            continue
        cases[key] = dict(condition=key[0], assignment_id=key[1], task=row['task_id'], replicate=row['replicate'],
            retained_revisions=row['retained_revisions'], attempted_turns=row['attempted_turns'],
            stop_reason=row['stop_reason'], feedback=feedback)
    groups = defaultdict(list)
    for case in cases.values():
        groups[case['condition']].append(case)
    summaries = {}
    for condition, group in groups.items():
        turns = [f for case in group for f in case['feedback']]
        summaries[condition] = dict(assignments=len(group), feedback_turns=len(turns),
            decisions=dict(Counter(f['decision'] for f in turns)),
            concern_count_distribution=dict(Counter(f['concern_count'] for f in turns)),
            mean_concern_characters_per_turn=mean(f['concern_characters'] for f in turns),
            categories=dict(Counter(c for f in turns for c in f['categories'])),
            absolute_app_mentions=sum(f['absolute_app_mentions'] for f in turns),
            exact_repeated_concerns=sum(sum(n-1 for n in Counter(h for f in case['feedback'] for h in f['concern_hashes']).values()) for case in group),
            stop_reasons=dict(Counter(case['stop_reason'] for case in group)),
            mean_attempted_turns=mean(case['attempted_turns'] for case in group),
            mean_retained_revisions=mean(case['retained_revisions'] for case in group))
    return dict(assignments=list(cases.values()), conditions=summaries,
        caution='Text length and item count do not measure independent substantive demands. /app mentions are screening counts, not adjudicated invalid demands or RH. Inspect linked feedback and trajectories before causal interpretation.')


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--analysis', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    source = json.loads(a.analysis.read_text())
    result = exposure(source['rows'])
    result['analysis_sha256'] = digest(a.analysis)
    result['source_sha256'] = digest(Path(__file__))
    a.output.mkdir(parents=True, exist_ok=False)
    (a.output / 'feedback-exposure.json').write_text(json.dumps(result, indent=2)+'\n')
    print(json.dumps(result['conditions'], indent=2))


if __name__ == '__main__':
    main()
