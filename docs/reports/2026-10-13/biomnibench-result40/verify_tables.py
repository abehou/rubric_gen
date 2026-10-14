"""Verify the published rows, panel means, averages and rendered table cells."""
import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

HERE = Path(__file__).resolve().parent
summary = json.loads((HERE / 'summary.json').read_text())
rows = json.loads((HERE / 'auditor-rows.json').read_text())
keys = ('W', 'S', 'H', 'A', 'W_minus_S', 'S_minus_H', 'H_minus_A', 'W_minus_A', 'RH_full_trajectory', 'RH_final_artifact')
groups = defaultdict(list)
identities = set()
for row in rows:
    identity = (row['task_id'], row['cohort'], row['replicate'], row['model'])
    assert identity not in identities
    identities.add(identity)
    groups[row['model'], row['cohort']].append(row)
    for gap, left, right in (('W_minus_S', 'W', 'S'), ('S_minus_H', 'S', 'H'), ('H_minus_A', 'H', 'A'), ('W_minus_A', 'W', 'A')):
        assert abs(row[gap] - (row[left] - row[right])) < 1e-9
assert len(rows) == 1920 and len(groups) == 16
assert all(len(group) == 120 for group in groups.values())
assert len({row['task_id'] for row in rows}) == 40
expected_lines = []
for model, panel in summary['after'].items():
    assert len(panel) == 8
    for item in panel:
        group = groups[model, item['cohort']]
        for key in keys[:8]:
            assert abs(item[key] - mean(row[key] for row in group)) < 1e-9
        for window in ('full_trajectory', 'final_artifact'):
            measured = 100 * mean(row['RH_' + window + '_decision'] == 'reward_hacking_detected' for row in group)
            assert abs(item['RH_' + window] - measured) < 1e-9
for item in summary['aggregate']:
    source = [next(value for value in panel if value['cohort'] == item['cohort']) for panel in summary['after'].values()]
    for key in keys:
        assert abs(item[key] - mean(value[key] for value in source)) < 1e-9
for panel in [*summary['after'].values(), summary['aggregate']]:
    for item in panel:
        expected_lines.append('| ' + item['condition'] + ' | ' + ' | '.join(f'{item[key]:.2f}' + ('%' if key.startswith('RH_') else '') for key in keys) + ' |')
for report in (HERE / 'README.md', HERE.parents[1] / '2026-09-18/trace-v21-execution-verified-provenance-result40/comparison-tables.md'):
    lines = [line for line in report.read_text().splitlines() if line.startswith(('| Full ', '| User ', '| Semi ', '| Score-Only '))]
    assert lines == expected_lines, report
verification = json.loads((HERE / 'verification.json').read_text())
assert verification['review_coverage'] == 480 and not verification['missing_review']
assert verification['prior_corrections_preserved']
print('Verified 1,920 unique rows, 16 panel means, eight averages and all 24 rendered rows in both current table locations.')
