"""Provider-free synthesis of complete saved cells; no execution or model calls."""
from __future__ import annotations

import csv
import importlib.util
import json
import os
import subprocess
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path
from statistics import mean
from zoneinfo import ZoneInfo

SOURCE = Path(__file__).resolve().parents[3]
ROOT = Path(os.environ.get('RUBRIC_GEN_PROJECT_ROOT', SOURCE))
REPORT = ROOT / 'docs/reports/2026-09-12/biomnibench-v21-to45'
OUT = REPORT / 'queue8'
V21 = ROOT / 'docs/reports/2026-09-11/trace-attack-defense-v2.1'
WINDOWS = ('full_trajectory', 'post_update', 'final_artifact', 'final_revision')
SCORES = ('W', 'W_train', 'S', 'H', 'A', 'W_minus_S', 'S_minus_H', 'H_minus_A', 'W_minus_A')
METRICS = SCORES + tuple('RH_' + w for w in WINDOWS)
PANEL = ('gpt-5.6-sol', 'claude-opus-5')
POLICIES = ('full', 'semi', 'score_only', 'user_simulator')


def read(path):
    return json.loads(path.read_text())


def csv_rows(path):
    with path.open() as f:
        return list(csv.DictReader(f))


def write_csv(path, rows):
    if not rows:
        return
    fields = list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fields)
        writer.writeheader()
        writer.writerows(rows)


def module(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def severity_percentiles(rows, rank):
    """The existing rank is descending; convert each component to high=severe."""
    for metric in ('W_minus_S', 'S_minus_H', 'H_minus_A'):
        ranks = rank.tie_rank({r['key']: float(r[metric]) for r in rows})
        for row in rows:
            row['rank_' + metric] = ranks[row['key']]
            row['severity_percentile_' + metric] = (
                100 * (len(rows) - ranks[row['key']]) / (len(rows) - 1)
                if len(rows) > 1 else 50.0)
    for row in rows:
        row['combined_severity_percentile'] = mean(
            row['severity_percentile_' + m] for m in ('W_minus_S', 'S_minus_H', 'H_minus_A'))


def panel_rows(rows):
    """Validate the small saved table before calculating any complete-cell mean."""
    grouped = defaultdict(list)
    for row in rows:
        grouped[row['task_id'], int(row['replicate'])].append(row)
    if not grouped or any(len(v) != 2 or {r['model'] for r in v} != set(PANEL)
                          for v in grouped.values()):
        raise ValueError('incomplete or duplicated saved auditor panel')
    return grouped


def describe_rows(rows, adapter):
    panel_rows(rows)
    summary = adapter.summarize(rows)
    summary['auditors'] = {m: adapter.summarize([r for r in rows if r['model'] == m]) for m in PANEL}
    return summary


def complete_cells(adapter):
    historical = read(V21 / 'results.json')
    assert historical['complete']
    cells = {}
    for name in ('static_full', 'candidate_full', 'static_user', 'candidate_user'):
        s = historical['cohorts'][name]
        cells['result20:' + name] = dict(scope='Result20', condition=name, tasks=20,
            assignments=s['assignments'], reused=60, new=0, means=s['means'],
            details=s, source=str(V21 / 'results.json'), panel_complete=True)
    control_path = ROOT / 'docs/reports/2026-09-12/trace-user-parallel-diagnostics/control-outcomes.json'
    control = read(control_path)
    summary = describe_rows(control['rows'], adapter)
    cells['canonical:user_simulator-trace'] = dict(scope='canonical dev3', condition='user_simulator-trace',
        tasks=3, assignments=9, reused=9, new=0, means=summary['means'], details=summary,
        rows=control['rows'], required_completed_judgments=sum(c['coverage']['semantic_judgments'] for c in control['coverage']),
        source=str(control_path), panel_complete=True)
    # Historical stress cells retain their own starts; never call them canonical controls.
    for r in csv_rows(REPORT / 'queue4/completed-variants.csv'):
        if r['cohort'] != 'historical_stress':
            continue
        source = ROOT / r['source']
        saved = read(source)
        key = 'v21' if r['variant'] == 'v2.1' else 'v3'
        baseline_file = ROOT / 'docs/reports/2026-09-11/trace-attack-defense-v3/stress-outcomes-v32/artifact-auditor-values.csv'
        baseline = {(x['task_id'], x['replicate'], x['model']): x for x in csv_rows(baseline_file) if x['variant'] == 'v21'}
        deltas = ({(x['task_id'], x['replicate'], x['model']): x
                   for x in csv_rows(source.parent / 'paired-v3-minus-v21.csv')}
                  if r['variant'] != 'v2.1' else None)
        if deltas is not None and deltas.keys() != baseline.keys():
            raise ValueError('historical paired auditor rows differ')
        detail = dict(saved[key])
        detail['auditors'] = {model: {'means': {
            m: mean(float(x[m]) + (float(deltas[k][m]) if deltas else 0)
                    for k, x in baseline.items() if k[2] == model) for m in METRICS}}
            for model in PANEL}
        for m in METRICS:
            if abs(mean(detail['auditors'][a]['means'][m] for a in PANEL) - float(r[m])) > 1e-8:
                raise ValueError('historical mean reconstruction differs')
        detail['auditor_reconstruction'] = 'Saved matched stress v2.1 auditor rows plus saved paired deltas; no new judgment.'
        cells['stress:' + r['variant']] = dict(scope='historical stress', condition=r['variant'],
            tasks=3, assignments=9, reused=9, new=0, means={m: float(r[m]) for m in METRICS},
            required_completed_judgments=int(r['judgments']), details=detail, source=str(source), panel_complete=True)
    status = read(ROOT / 'experiments/biomnibench-v21-to45/status.json')
    q3 = Path(status['queue3']['execution_worktree']) / 'docs/reports/2026-09-12/biomnibench-v21-to45/queue3'
    incomplete = {}
    for condition in [f'{p}-{r}' for p in POLICIES for r in ('fixed', 'trace')] + ['score_only-trace-no-appendix']:
        if condition == 'user_simulator-trace':
            continue
        path = q3 / (condition + '.json')
        packet = read(path) if path.exists() else None
        if not packet or not packet.get('complete'):
            incomplete[condition] = {'source': str(path), 'status': 'no complete audited cell',
                'audited_assignments': packet.get('completed_audited_assignments', 0) if packet else 0,
                'errors': packet.get('errors', []) if packet else []}
            continue
        summary = describe_rows(packet['rows'], adapter)
        if summary['assignments'] != 9:
            raise ValueError('canonical cell scope changed')
        cells['canonical:' + condition] = dict(scope='canonical dev3', condition=condition, tasks=3,
            assignments=9, reused=0, new=9, means=summary['means'], details=summary,
            rows=packet['rows'], source=str(path), panel_complete=True, delivery=packet.get('delivery'),
            native_panel_union=packet.get('native_panel_union'),
            required_completed_judgments=sum(c['coverage']['semantic_judgments'] for c in packet['coverage']))
    q2 = Path(status['queue2']['execution_worktree']) / 'docs/reports/2026-09-12/biomnibench-v21-to45/queue2/outcomes.json'
    if q2.exists():
        packet = read(q2)
        for condition in ('R1', 'R2'):
            summary = describe_rows(packet['rows'][condition], adapter)
            if summary['assignments'] != 9:
                raise ValueError('appendix cell scope changed')
            cells['canonical:' + condition] = dict(scope='canonical dev3', condition=condition,
                tasks=3, assignments=9, reused=0, new=9, means=summary['means'], details=summary,
                rows=packet['rows'][condition], source=str(q2), panel_complete=True,
                required_completed_judgments=sum(c['coverage']['semantic_judgments'] for c in packet['coverage'][condition]))
    else:
        incomplete.update({c: {'status': 'trajectories complete; outcome audit incomplete', 'source': str(q2)} for c in ('R1', 'R2')})
    return cells, incomplete, historical


def rankings(cells, rank):
    groups = defaultdict(list)
    # Already validated descriptive v2.1/stress tables; do not re-read historical trajectories.
    for row in csv_rows(ROOT / 'docs/reports/2026-09-11/trace-attack-defense-v3/artifact-gap-rh-ranking.csv'):
        if row['condition'] == 'canonical-v2.1-user':
            continue  # The exact control is added once from its complete native packet below.
        row['condition'] = {'v2.1-full': 'result20:candidate_full', 'v2.1-user': 'result20:candidate_user'}.get(row['condition'], row['condition'])
        for metric in SCORES:
            row[metric] = float(row[metric])
        for window in WINDOWS:
            k = 'RH_' + window + '_monitor'
            row[k] = float(row[k]) if row[k] else None
            for suffix in ('positive', 'abstain'):
                k = 'RH_' + window + '_' + suffix
                row[k] = row[k] == 'True'
        groups[row['condition']].append(row)
    frozen = read(Path('/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20/report/frozen-cohorts.json'))
    for condition in ('static_full', 'static_user'):
        saved = frozen[condition]
        if len(panel_rows(saved)) != 60 or any(r['heldout_pool'] != 'canonical_v2' for r in saved):
            raise ValueError('frozen static ranking scope or heldouts differ')
        for row in saved:
            for native, name in [('WS', 'W_minus_S'), ('SH', 'S_minus_H'), ('HA', 'H_minus_A'), ('WA', 'W_minus_A')]:
                row['values'][name] = row['values'][native]
        groups['result20:' + condition] = rank.aggregate(saved, label='result20:' + condition)
    for key, cell in cells.items():
        if key.startswith('canonical:') and 'rows' in cell:
            groups[key] = rank.aggregate(cell['rows'], label=key)
    summaries = {}
    for name, rows in groups.items():
        result = rank.analyze(rows)
        severity_percentiles(rows, rank)
        # Affine conversion of equal-weight average ranks; no new weight or raw-gap sum.
        for window in ('final_artifact', 'full_trajectory'):
            result[window]['metrics']['combined_severity_percentile'] = result[window]['metrics'].pop('combined_gap_score')
        summaries[name] = result
    return [r for rows in groups.values() for r in rows], summaries


def metric_table(cells):
    rows = []
    for key, c in cells.items():
        rows.append(dict(cell=key, scope=c['scope'], tasks=c['tasks'], assignments=c['assignments'],
            reused=c['reused'], new=c['new'], judgments=c.get('required_completed_judgments', 'see source accounting'),
            **{m: c['means'][m] for m in METRICS}, source=c['source']))
    return rows


def observe():
    """Small live ledgers/accounting only; no repeated trajectory validation."""
    status = read(ROOT / 'experiments/biomnibench-v21-to45/status.json')
    now = datetime.now(ZoneInfo('America/New_York'))
    found = {}

    def jobs(value, path=''):
        if isinstance(value, dict):
            if isinstance(value.get('job_id'), str) and value['job_id'].isdigit():
                found[value['job_id']] = dict(package=path, **value)
            for k, v in value.items(): jobs(v, path + '/' + k)
        elif isinstance(value, list):
            for i, v in enumerate(value): jobs(v, path + '/' + str(i))
    jobs(status)
    accounting = subprocess.run(['sacct', '-X', '-n', '-P', '-j', ','.join(found),
        '--format=JobID,JobName%60,State,ExitCode,Elapsed,AllocCPUS,TotalCPU'], capture_output=True, text=True)
    accounting.check_returncode()
    current = {}
    for line in accounting.stdout.splitlines():
        parts = line.split('|')
        if len(parts) >= 7:
            current[parts[0]] = dict(zip(('job_id', 'name', 'state', 'exit_code', 'elapsed', 'cpus', 'total_cpu'), parts[:7]))
    records = [dict(**v, accounting=current.get(k, {'state': 'not present in queried accounting'})) for k, v in found.items()]
    base = Path('/data/user_data/aydanh/rubric_gen/runs/biomnibench-v21-to45-20260912')
    cells = []
    for queue, names in [('queue2', ['R1', 'R2']), ('queue3', [f'{p}-{r}' for p in POLICIES for r in ('fixed', 'trace')
                                                          if not (p == 'user_simulator' and r == 'trace')] + ['score_only-trace-no-appendix'])]:
        for cell in names:
            counts = Counter()
            for task in ('da-3-4', 'da-11-1', 'da-18-1'):
                for p in (base / queue / cell / task / 'study').glob('*/study.json'):
                    ledger = read(p); selected = set(ledger.get('execution_conditions', []))
                    for r in ledger['records']:
                        if not selected or r['condition_id'] in selected:
                            counts[r['status']] += 1
            cells.append(dict(queue=queue, cell=cell, expected=9, **counts,
                              not_yet_in_ledger=max(0, 9 - sum(counts.values()))))
    seeds = {}
    for name, expected in [('results30', 30), ('results45-added15', 45)]:
        counts = Counter(p.parents[1].name for p in (base / name).glob('*/inputs/seeds/tasks/*/rep-*/manifest.json'))
        seeds[name] = dict(expected_blocks=expected, sealed_blocks=sum(counts.values()), by_task=dict(counts))
    observed = dict(observed_at=now.isoformat(), mission_started_at=status['mission_started_at'],
        elapsed_hours=(now - datetime.fromisoformat(status['mission_started_at'])).total_seconds() / 3600,
        jobs=records, cells=cells, seeds=seeds, provider_calls=0,
        heldout_authority=status['queue6']['heldout_authority'])
    (OUT / 'observed-status.json').write_text(json.dumps(observed, indent=2) + '\n')
    write_csv(OUT / 'assignment-progress.csv', cells)
    write_csv(OUT / 'job-accounting.csv', [dict(package=r['package'], **r['accounting']) for r in records])
    return observed


def figures(cells):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    colors = {'full': '#1764ab', 'user': '#d85b99'}
    for kind, metrics, titles in [
        ('rh', ['RH_' + w for w in WINDOWS], ['Full trajectory', 'Post update', 'Final artifact', 'Final revision']),
        ('gaps', ['W_minus_S', 'S_minus_H', 'H_minus_A'], ['Weak−strong (W−S)', 'Selected−heldout (S−H)', 'Heldout−holistic (H−A)'])]:
        fig, axes = plt.subplots(1, len(metrics), figsize=(3.7 * len(metrics), 3.6), squeeze=False)
        for ax, metric, title in zip(axes[0], metrics, titles):
            for i, (arm, policy) in enumerate([('full', 'static'), ('full', 'candidate'), ('user', 'static'), ('user', 'candidate')]):
                c = cells[f'result20:{policy}_{arm}']
                ax.bar(i, c['means'][metric], color=colors[arm], alpha=.4 if policy == 'static' else 1,
                       hatch='//' if policy == 'static' else None)
                for model, marker in zip(PANEL, ['o', 'x']):
                    value = c['details']['auditors'][model]['means'][metric]
                    ax.scatter(i, value, color='black', s=22, marker=marker, zorder=3)
            ax.axhline(0, color='#777777', linewidth=.7)
            ax.set_xticks(range(4), ['Full\nfixed', 'Full\nv2.1', 'User\nfixed', 'User\nv2.1'])
            ax.set_title(title); ax.set_ylabel('Confirmed positive (%)' if kind == 'rh' else 'Points')
            ax.spines[['top', 'right']].set_visible(False)
        fig.suptitle('Completed developmental Result20 · 20 tasks × 3 replicates per cell · Sol + Opus')
        fig.text(.5, .015, 'Bars: equal-weight panel; dots/crosses: individual auditors. No confidence intervals or abstention bounds shown.', ha='center', fontsize=8)
        fig.tight_layout(rect=(0, .055, 1, .92))
        for ext in ['png', 'svg']: fig.savefig(OUT / f'result20-{kind}.{ext}', dpi=160)
        plt.close(fig)
    # Honest matrix: only complete-cell means, even when all trajectories have finished.
    labels = [f'{p}-{r}' for p in POLICIES for r in ('fixed', 'trace')] + ['score_only-trace-no-appendix']
    cols = ['Cell', 'Audited', 'W', 'S', 'H', 'A', 'W−S', 'S−H', 'H−A']
    values = []
    for label in labels:
        c = cells.get('canonical:' + label)
        values.append([label, '9/9' if c else 'pending'] +
                      [f"{c['means'][m]:.2f}" if c else '—' for m in ('W', 'S', 'H', 'A', 'W_minus_S', 'S_minus_H', 'H_minus_A')])
    fig, ax = plt.subplots(figsize=(13, 4.4)); ax.axis('off')
    table = ax.table(cellText=values, colLabels=cols, loc='center', cellLoc='center', colWidths=[.31, .09] + [.085] * 7)
    table.auto_set_font_size(False); table.set_fontsize(9); table.scale(1, 1.65)
    for i, label in enumerate(labels, 1):
        if label.startswith('full'):table[i, 0].set_facecolor('#d6e6f5')
        if label.startswith('user'):table[i, 0].set_facecolor('#f6dfeb')
    ax.set_title('Canonical dev3 · 3 tasks × 3 replicates/cell · complete Sol+Opus outcomes only\nWithin-policy trace minus fixed requires both cells; pending is not zero.', pad=18)
    fig.tight_layout();fig.savefig(OUT / 'feedback-policy.png', dpi=160);plt.close(fig)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    rank = module('saved_gap_rank', SOURCE / 'experiments/trace-attack-defense-v3/artifact_gap_rh_ranking.py')
    adapter = module('saved_outcomes', SOURCE / 'experiments/trace-attack-defense-v3/report_dev3_outcomes.py')
    observed = observe()
    cells, incomplete, historical = complete_cells(adapter)
    rows = metric_table(cells)
    write_csv(OUT / 'complete-cells.csv', rows)
    auditor_rows = []
    for key, c in cells.items():
        details = c['details']
        # Stress summaries retain their full source details even if no auditor-means field exists.
        for model, values in details.get('auditors', {}).items():
            if model in PANEL:
                auditor_rows.append(dict(cell=key, auditor=model, **{m: values['means'][m] for m in METRICS}))
    write_csv(OUT / 'complete-cells-by-auditor.csv', auditor_rows)
    ranking_rows, ranking_summary = rankings(cells, rank)
    write_csv(OUT / 'artifact-gap-rh-ranking.csv', ranking_rows)
    (OUT / 'artifact-gap-rh-ranking-summary.json').write_text(json.dumps(ranking_summary, indent=2, allow_nan=False) + '\n')
    contrasts = {k: v for k, v in historical['contrasts'].items() if k.endswith('_minus_static')}
    for policy in POLICIES:
        lhs, rhs = cells.get('canonical:' + policy + '-trace'), cells.get('canonical:' + policy + '-fixed')
        if lhs and rhs:
            paired_rows, summary = adapter.paired(lhs['rows'], rhs['rows'])
            contrasts['canonical:' + policy + ':trace_minus_fixed'] = {'paired_rows': paired_rows, 'summary': summary}
    record = dict(observed_at=datetime.now(ZoneInfo('America/New_York')).isoformat(), provider_calls=0,
        complete_cells=cells, incomplete_cells=incomplete, contrasts=contrasts,
        ranking_scope='Within condition. Final-artifact primary; full-trajectory assignment-level secondary. No pooled analysis.',
        ranking_weights='Equal component severity percentiles; no raw-gap sum. Raw signed gaps telescope to W-A.',
        historical_result20_analysis=historical['analysis'], progress=observed)
    (OUT / 'synthesis.json').write_text(json.dumps(record, indent=2, allow_nan=False) + '\n')
    figures(cells)
    titles = ['W', 'W_train', 'S', 'H', 'A', 'W−S', 'S−H', 'H−A', 'W−A', 'RH full', 'RH post', 'RH artifact', 'RH revision']
    checkpoint = 'Morning checkpoint' if observed['elapsed_hours'] >= 9 else 'Interim checkpoint'
    lines = [f'# {checkpoint}: completed evidence and unfinished work', '', f"Observed {record['observed_at']}; mission elapsed{observed['elapsed_hours']:.2f}h; this analysis made0 provider calls.", '',
        'Only complete intended cells appear below. Historical stress, canonical development and Result20 have different scopes. Reuse/new counts refer to this mission, not their original execution.', '',
        '| Cell | Tasks | Assignments | Reuse/new | ' + ' | '.join(titles) + ' |',
        '|---|---:|---:|---:|' + '---:|' * len(titles)]
    for r in rows:
        lines.append('| ' + r['cell'] + f" | {r['tasks']} | {r['assignments']} | {r['reused']}/{r['new']} | " +
                     ' | '.join(f'{r[m]:.2f}' for m in METRICS) + ' |')
    lines += ['', 'RH means are confirmed-positive percentages over the full auditor denominator. Native panel unions, abstentions and identification bounds remain separate in [synthesis.json](synthesis.json) and the linked original reports. They are not confidence intervals.', '',
        '[Per-auditor values](complete-cells-by-auditor.csv) · [complete table](complete-cells.csv) · [paired contrasts and source detail](synthesis.json)', '',
        '![Result20 RH panels](result20-rh.png)', '![Result20 gap panels](result20-gaps.png)',
        '![Canonical feedback-policy coverage](feedback-policy.png)', '',
        '## Gap rank versus RH rank', '',
        'Signed W−S, S−H and H−A receive average-tie ranks separately within each condition. Each converts to a0–100 severity percentile (larger=larger gap), then the three percentiles are averaged equally. Their raw sum is exactly W−A and is not a new independent metric.', '',
        'Spearman and Kendall tau-b compare this severity ordering with continuous equal-weight Sol+Opus RH monitor scores. Boundary ties receive fractional worst-k membership; overlap is the expected shared fraction at ceil(10/20/25%×n). Missing monitor scores remain missing; abstentions/statuses are retained. Constant variables produce null/undefined correlations, never zero.', '',
        '| Condition | Window | n | Combined Spearman | Kendall |', '|---|---|---:|---:|---:|']
    for name, windows in ranking_summary.items():
        for window, value in windows.items():
            metric = value['metrics']['combined_severity_percentile']
            fmt = lambda x: 'undefined' if x is None else f'{x:.3f}'
            lines.append(f"| {name} | {window} | {value['n']} | {fmt(metric['spearman'])} | {fmt(metric['kendall_tau_b'])} |")
    lines += ['', '[All component correlations, tie-aware overlaps and RH-status groups](artifact-gap-rh-ranking-summary.json) · [artifact rows](artifact-gap-rh-ranking.csv). No condition pooling, weighting search or provider calls. These descriptive associations neither substitute for RH nor establish causal mediation.', '',
        '## Missing cells', '', *[f"- {key}: {value['status']}." for key, value in incomplete.items()], '',
        'See the [mission report](../README.md) and [persisted status](../../../../../../experiments/biomnibench-v21-to45/status.json) for source ownership, failures and safe continuation. This is not a completed30/45-task result.']
    lines += ['', '## Execution progress', '', '[Assignment counts](assignment-progress.csv) · [Slurm accounting](job-accounting.csv) · [exact job commands, sources and observed states](observed-status.json). Unobserved accounting is not treated as completion.', '',
        *[f"- {name}: {v['sealed_blocks']}/{v['expected_blocks']} starting blocks sealed. These are inputs, not treatment-assignment outcomes." for name, v in observed['seeds'].items()], '',
        'Healthy jobs retain their current owners. No new speculative recipe, scale dispatch, model retry or Git operation is performed by this checkpoint script. Missing outcome coverage prevents a full-cell estimate; it does not erase completed records.']
    (OUT / 'README.md').write_text('\n'.join(lines) + '\n')
    print(json.dumps({'complete_cells': list(cells), 'incomplete_cells': list(incomplete), 'ranking_artifacts': len(ranking_rows), 'provider_calls': 0}))


if __name__ == '__main__':
    main()
