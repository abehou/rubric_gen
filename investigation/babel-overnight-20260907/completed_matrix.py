"""Private read-only, deduplicated checkpoint of already native-validated Babel cohorts."""
import argparse
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from analyze_babel import aggregate, digest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    root = HERE.parents[1]
    reports = root / 'runs/babel-overnight-20260907'
    rows = {}
    sources = []
    definitions = None
    analysis_sha = digest(HERE / 'analyze_babel.py')
    for path in sorted(reports.glob('analysis-*/analysis.json')):
        report = json.loads(path.read_text())
        if 'input_reports' in report:
            continue
        assert report['analysis_source_sha256'] == analysis_sha, 'analysis definition drift'
        if definitions is None:
            definitions = report['definitions']
        assert report['definitions'] == definitions
        assert report['coverage'], 'missing native coverage'
        sources.append(dict(path=str(path.resolve()), sha256=digest(path)))
        for row in report['rows']:
            key = (row['state_path'], row['model'])
            if key in rows:
                left = {k: v for k, v in rows[key].items() if k not in ('analysis_condition', 'matrix_cohort')}
                right = {k: v for k, v in row.items() if k != 'analysis_condition'}
                assert left == right, 'duplicate native records disagree'
                continue
            for field, sha in [('state_path', 'state_sha256'), ('score_composition_path', 'score_composition_sha256')]:
                assert digest(Path(row[field])) == row[sha], 'saved artifact changed'
            parts = Path(row['state_path']).relative_to(root / 'runs').parts
            assert parts[0].startswith('babel-dev3-'), 'non-Babel cohort'
            value = dict(row)
            value['matrix_cohort'] = parts[0]
            value['analysis_condition'] = '/'.join((parts[0], row['task_id'], row['condition_id']))
            rows[key] = value
    panel = ['gpt-5.6-sol', 'claude-opus-5']
    by_assignment = {}
    for row in rows.values():
        by_assignment.setdefault(row['state_path'], set()).add(row['model'])
    assert all(models == set(panel) for models in by_assignment.values()), 'incomplete panel'
    values = list(rows.values())
    conditions, distributions = aggregate(values, panel)
    payload = dict(unique_assignments=len(by_assignment), unique_auditor_rows=len(values),
                   conditions=conditions, monitor_distributions=distributions,
                   definitions=definitions, source_reports=sources,
                   source_sha256=digest(Path(__file__)), analysis_source_sha256=analysis_sha,
                   rows=values,
                   limitations='Descriptive development checkpoint, not a pooled scientific comparison. Tasks remain separate. Native coverage was validated under each frozen source; this does not fabricate cross-version resume compatibility. No imputation for deferred Gemini. Full-panel union retains abstention bounds. Current incomplete cohorts excluded. Uncertainty and criterion exposure require original reports.')
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output / 'matrix.json').write_text(json.dumps(payload, indent=2) + '\n')
    lines = ['# Completed Babel dev3 conditions', '',
             f'{len(by_assignment)} unique assignments; {len(values)} unique Sol/Opus auditor rows. Repeated native reports are deduplicated by state path and auditor after exact record/hash consistency checks.', '',
             payload['limitations'], '',
             'All scores are on the frozen 0–100 scale. RH columns show panel-union identification bounds, not averaged auditor rates. W_train is final composed reward; equality with W does not rule out earlier penalties.', '']
    for task in ['da-3-4', 'da-11-1']:
        lines += [f'## {task}', '', '|Cohort / condition|n|W|S|H|A|W-S|S-H|H-A|W-A|Full RH|Post RH|Final RH|Final revision RH|',
                  '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|---|---|---|']
        for key, value in sorted(conditions.items()):
            if f'/{task}/' not in key or not key.endswith('/matched-panel'):
                continue
            metric = value['metrics']
            label = key.removesuffix('/matched-panel').replace(f'/{task}/', ' / ')
            cells = [label, str(value['assignments'])]
            cells += [f"{metric[k]['mean']:.2f}" for k in ['W', 'S', 'H', 'A', 'WS', 'SH', 'HA', 'WA']]
            for k in ['RH_full_trajectory', 'RH_post_update', 'RH_final_artifact', 'RH_final_revision']:
                bounds = metric[k]['identification_bounds']
                cells.append(f'{bounds[0]:.3f}' if bounds[0] == bounds[1] else f'{bounds[0]:.3f}–{bounds[1]:.3f}')
            lines.append('|' + '|'.join(cells) + '|')
        lines.append('')
    lines += ['Detailed JSON includes each auditor, all monitor distributions, W_train, revision behavior, source paths/hashes and original uncertainty definitions. Interpret quality guardrails against the predeclared matched control, not against whichever row looks favorable.', '']
    (args.output / 'matrix.md').write_text('\n'.join(lines))
    print(json.dumps(dict(unique_assignments=len(by_assignment), auditor_rows=len(values), source_reports=len(sources), output=str(args.output))))


if __name__ == '__main__':
    main()
