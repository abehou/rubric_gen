"""Bind human read-only case annotations to sealed natural trajectory evidence."""
import os
from collections import Counter
from report_sources import OUT, PUBLIC, read, sha, write
from report_pipeline import table


def strings(value):
    if isinstance(value, str):
        yield value
    elif isinstance(value, list):
        for child in value:
            yield from strings(child)
    elif isinstance(value, dict):
        for child in value.values():
            yield from strings(child)


def main():
    assert os.environ.get('SLURM_JOB_ID')
    index = read(PUBLIC / 'RH-positive-case-index.json')
    annotations = read(PUBLIC / 'RH-review-annotations.json')
    assert {r['assignment_id'] for r in annotations} == {r['assignment_id'] for r in index}
    assert len(annotations) == len(index)
    by_id = {r['assignment_id']: r for r in index}
    rows = []
    for note in annotations:
        entry = by_id[note['assignment_id']]
        assert sha(entry['packet_path']) == entry['packet_sha256']
        packet = read(entry['packet_path'])
        anchors = []
        for i in note['anchor_events']:
            event = packet['events'][i]
            assert event['kind'] != 'reasoning'
            anchors.append({'event_index': i, 'turn': event['turn'], 'kind': event['kind'],
                            'source': event['source'], 'source_line': event['source_line'],
                            'source_sha256': packet['sources'][event['source']]})
        witnesses = []
        for quote in note['evidence_quotes']:
            matches = []
            for anchor in anchors:
                event = packet['events'][anchor['event_index']]
                if any(quote in s for s in strings(event)):
                    matches.append(anchor)
            assert matches, (note['assignment_id'], quote)
            witnesses.append({'quote': quote, 'anchors': matches})
        turn = note['first_verified_turn']
        assert turn is None or turn in {a['turn'] for a in anchors}
        rules = [{k: c[k] for k in ('criterion_id', 'admission_generation', 'requirement',
                  'first_verbatim_requirement_in_prompt')} for c in packet['rules']]
        exposures = [c['first_verbatim_requirement_in_prompt'] for c in rules
                     if c['first_verbatim_requirement_in_prompt'] is not None]
        reminders = [{'turn': r['solver_turn'], 'selection': r['selection']}
                     for r in packet['reminders'] if r['selection']]
        rows.append({**entry, **note, 'witnesses': witnesses, 'anchors': anchors,
                     'admitted_rules': rules, 'reminders': reminders,
                     'first_any_verbatim_rule_exposure': min(exposures, default=None),
                     'verified_event_before_structural_intervention': None if turn is None else turn < 1,
                     'official_verdicts_unchanged': True})
    write(PUBLIC / 'RH-positive-reviewed-cases.json', rows)
    table('RH-positive-reviewed-cases.csv', rows)
    summary = {'reviewed_positive_assignments': len(rows), 'provider_calls': 0,
               'classifications': dict(Counter(r['classification'] for r in rows)),
               'verified_first_turns': {a: dict(Counter(str(r['first_verified_turn']) for r in rows
                   if r['arm'] == a)) for a in ('full', 'user')},
               'official_verdicts_replaced': 0,
               'note': 'Human forensic descriptions are evidence interpretations, not new outcome judgments. '
                       'No official positive, negative, or abstaining cell is removed.'}
    write(PUBLIC / 'RH-case-review-summary.json', summary)
    lines = ['# Full-trajectory positive cases: saved-evidence review', '',
             'All 18 assignments positive under at least one frozen auditor are retained. '
             'The notes below distinguish directly observed mismatches from unresolved auditor/context disagreements. '
             'They do not replace verdicts or generate a corrected RH endpoint. Event indices are zero-based '
             'within the hashed inspection packet; source line numbers are one-based in the native stream.', '',
             'The earliest possible online intervention was before turn 1 for every case. '
             'All six User-positive assignments had no admitted offline or online rule and no focused reminder. '
             'No verified event in this reviewed subset precedes that structural opportunity; this does not '
             'show that a useful rule was available or that it would have prevented the event. '
             'A verbatim rule in ordinary Full feedback is exposure even when no focused reminder selects it.', '']
    for r in sorted(rows, key=lambda x: (x['arm'], x['assignment_id'])):
        verdicts = '; '.join(f"{m}: {v['decision']} ({v['score']})" for m, v in r['official_verdicts'].items())
        lines += [f"## {r['arm'].title()} {r['task_id']} / rep-{r['replicate']:03d}", '', verdicts, '',
                  f"**First verified event:** {r['first_verified_turn'] if r['first_verified_turn'] is not None else 'unresolved / not verified'}. "
                  f"**First focused reminder:** {r['first_focused_reminder_turn'] or 'none'}. "
                  f"**First verbatim admitted-rule exposure:** {r['first_any_verbatim_rule_exposure'] or 'none'}.", '',
                  r['finding'], '', r['subsequent_behavior'], '', r['timing_caveat'], '']
        if r['admitted_rules']:
            lines += ['Admitted coverage (availability is not proof that the rule covers the alleged event):', '']
            for c in r['admitted_rules']:
                lines += [f"- `{c['criterion_id']}`, g{c['admission_generation']}, first exposure turn {c['first_verbatim_requirement_in_prompt']}: {c['requirement']}"]
            lines += ['']
        for w in r['witnesses']:
            anchors = ', '.join(f"event {a['event_index']} / turn {a['turn']} / line {a['source_line']}" for a in w['anchors'])
            lines += [f"- Literal witness: `{w['quote']}` ({anchors})."]
        lines += ['', f"Raw packet: `{r['packet_path']}` (SHA-256 `{r['packet_sha256']}`). "
                  'The JSON/CSV companion records native stream paths, source line numbers and hashes for every anchor.', '']
    (PUBLIC / 'RH-case-review.md').write_text('\n'.join(lines))
    print(summary, flush=True)


if __name__ == '__main__':
    main()
