"""Paired native/current/new A comparison; writes only the independent pilot report."""
from rubric_gen.runtime.process_environment import install_controlled_process_environment
install_controlled_process_environment()
from collections import defaultdict
from statistics import fmean
from rubric_gen.artifacts.serialization import write_json_atomic as write
from rubric_gen.submission_revision.evaluation.absolute_score import validate_verdict
from prepare import HERE, ROOT, read

def main():
    scope = read(HERE / 'scope.json'); out = ROOT / scope['output']
    rows = []; groups = defaultdict(list)
    for b in read(out / 'baselines.json'):
        row = {k: b[k] for k in ('key', 'task_id', 'replicate', 'condition_id', 'assignment_id')}
        for p, label in [('openai', 'gpt'), ('anthropic', 'claude')]:
            path = out / p / b['key'] / 'result.json'
            if not path.exists(): raise RuntimeError(f'Incomplete {p} A audit: {b["key"]}')
            result = read(path); validate_verdict(result['verdict'])
            assert result['actual_model'] == scope['providers'][p]['model'] and result['effort'] == 'high'
            A = result['verdict']['score']; old = b[label + '_current']
            scores = {**old, 'A': A, 'H-A': old['H'] - A}
            row[label] = dict(current=scores, native_old_A=b[label + '_native_A']['score'],
                              current_old_A=old['A'], new_A=A,
                              delta_native=A-b[label + '_native_A']['score'],
                              delta_current=A-old['A'], explanation=result['verdict']['explanation'])
            groups[(p, b['condition_id'])].append(row[label])
        rows.append(row)
    summary = []
    table = ['# A scoring Dev10 — HealthBench / Luna', '',
             'Diagnostic subset: 10 paired tasks × 3 replicates per condition. New A only; other scores are saved existing values.', '',
             '| Auditor | Condition | N | W | S | H | Native old A | Current old A | New A | W−S | S−H | New H−A | ΔA vs native |',
             '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for (p, c), rs in sorted(groups.items()):
        scores = {k: fmean(r['current'][k] for r in rs) for k in ('W', 'S', 'H', 'A', 'W-S', 'S-H', 'H-A')}
        rec = dict(provider=p, condition=c, n=len(rs), scores=scores,
                   native_old_A=fmean(r['native_old_A'] for r in rs), current_old_A=fmean(r['current_old_A'] for r in rs),
                   delta_native=fmean(r['delta_native'] for r in rs))
        summary.append(rec)
        values = [scores[k] for k in ('W', 'S', 'H')] + [rec['native_old_A'], rec['current_old_A'], scores['A']] + [scores[k] for k in ('W-S', 'S-H', 'H-A')] + [rec['delta_native']]
        table.append(f'| {scope["providers"][p]["model"]} high | {c} | {len(rs)} | ' + ' | '.join(f'{x:.2f}' for x in values) + ' |')
    table += ['', '## Task-level paired changes', '', '| Task | Auditor | Static ΔA vs native | RTT ΔA vs native | RTT−Static new A |', '|---|---|---:|---:|---:|']
    for t in scope['tasks']:
        for label in ('gpt', 'claude'):
            rs = [r for r in rows if r['task_id'] == t['id']]
            static = [r[label] for r in rs if r['condition_id'] == 'score-only-static']
            rtt = [r[label] for r in rs if r['condition_id'] == 'score-only-red-team-trace']
            table.append(f'| {t["id"]} | {label} | {fmean(r["delta_native"] for r in static):.2f} | {fmean(r["delta_native"] for r in rtt):.2f} | {fmean(r["new_A"] for r in rtt)-fmean(r["new_A"] for r in static):.2f} |')
    write(out / 'pilot-rows.json', rows); write(out / 'pilot-summary.json', summary)
    (out / 'COMPARISON.md').write_text('\n'.join(table) + '\n')
    print(out / 'COMPARISON.md')

if __name__ == '__main__':
    main()
