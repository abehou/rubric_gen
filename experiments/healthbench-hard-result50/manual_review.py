"""Private, provider-free application of explicit human criterion/RH decisions."""
from collections import Counter, defaultdict
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import re
from statistics import mean

from prepare import ROOT, OUTPUT, HERE
from report_matrix import BATCHES, WINDOWS, ORDER, METRICS
from inspect_sh import evaluation
from inspect_judgment_consistency import rubric_spec


def read(path):
    return json.loads(path.read_text())


def final_judgments():
    matrix = read(OUTPUT / 'matrix-analysis.json')
    rubric_paths = {}
    summaries = {}; indices = {}; cache = {}; specs = {}
    for directory, eid, _ in BATCHES:
        root = ROOT / 'runs' / directory
        folder = root / 'audits' / eid / 'rubric_score'
        summaries[directory] = {r['assignment_id']: r for r in read(folder / 'summary.json')['assignments']}
        indices[directory] = defaultdict(dict)
        for path in (folder / 'records').glob('*.json'):
            r = read(path)
            indices[directory][r['task_id'], r['answer_input_sha256'], r['submission_content_sha256']][r['rubric_sha256']] = r
        for path in (root / 'paraphrases/tasks').glob('*/variant-*.txt'):
            rubric_paths[path.parent.name, hashlib.sha256(path.read_bytes()).hexdigest()] = path
    refs = []
    for row in matrix['rows']:
        answer = ROOT / row['rounds'][-1]['answer_path']
        snap = read(answer.parent.parent / 'snapshot.json')['workspace_sha256']
        records = indices[row['run']][row['task_id'], hashlib.sha256(answer.read_bytes()).hexdigest(), snap]
        base_sha = summaries[row['run']][row['assignment_id']]['reference_scores']['active_local']['initial']['rubric_sha256']
        variants = [(0, base_sha)]
        for v in (2, 3, 4):
            shas = [sha for (task, sha), path in rubric_paths.items()
                    if task == row['task_id'] and path.name == f'variant-{v:03d}.txt']
            assert len(shas) == 1
            variants.append((v, shas[0]))
        for v, sha in variants:
            record = records[sha]
            path = rubric_paths[row['task_id'], sha]
            if sha not in specs:
                maximum, parsed = rubric_spec(path)
                text = path.read_text()
                blocks = re.split(r'\n(?=Criterion \d+:)', '\n' + text)[1:]
                full = {'criterion_' + re.match(r'Criterion (\d+):', block)[1]: block for block in blocks}
                specs[sha] = maximum, parsed, full
            maximum, parsed, full = specs[sha]
            key = record['evaluation_path']
            if key not in cache:
                cache[key] = evaluation(record)
            e = cache[key]
            assert e is not None
            refs.append(dict(task=row['task_id'], condition=row['condition_id'], replicate=row['replicate'],
                             view='S' if v == 0 else 'H' + str(v), assignment=row['assignment_id'],
                             answer=str(answer), evaluation=key, rubric=str(path), maximum=maximum,
                             score=e['total_score'], criteria=e['criteria'], rubric_items=parsed,
                             rubric_blocks=full))
    assert len(refs) == 4800
    return matrix, refs


def recompute():
    matrix, refs = final_judgments()
    decisions = read(HERE / 'corrections.json')
    lookup = {(r['task'], r['condition'], r['replicate'], r['view']): r for r in refs}
    updates = defaultdict(dict); changes = []; applied_keys = set()
    for item in decisions['rubric']:
        key = (item['task'], item['condition'], item['replicate'], item['view'])
        ref = lookup[key]; cid = item['criterion']; grade = ref['criteria'][cid]
        assert grade['points'] == item['old_points'], (key, cid, grade, item)
        assert (key, cid) not in applied_keys
        applied_keys.add((key, cid))
        levels = ref['rubric_items'][cid]['levels']
        new_points = levels[item['new_level']]
        assert new_points != grade['points']
        updates[key][cid] = new_points
        changes.append(dict(**item, new_points=new_points, original_reason=grade['reason'],
                            original_level=grade['level'], answer=ref['answer'],
                            evaluation=ref['evaluation'], rubric=ref['rubric'],
                            criterion_text=ref['rubric_blocks'][cid]))
    scores = {}; judgment_changes = []
    for key, ref in lookup.items():
        values = {cid: g['points'] for cid, g in ref['criteria'].items()}
        values.update(updates.get(key, {}))
        score = max(0, min(100, sum(values.values()) * 100 / ref['maximum']))
        if key not in updates:
            assert abs(score - ref['score']) < 1e-8
        scores[key] = score
        if key in updates:
            judgment_changes.append(dict(task=key[0], condition=key[1], replicate=key[2], view=key[3],
                                         old_score=ref['score'], new_score=score,
                                         criterion_changes=len(updates[key])))
    rows = deepcopy(matrix['rows'])
    row_index = {(r['task_id'], r['condition_id'], r['replicate']): r for r in rows}
    rh_changes = []; rh_keys = set()
    for item in decisions['rh']:
        rh_key = item['task'], item['condition'], item['replicate'], item['window']
        assert rh_key not in rh_keys, rh_key
        rh_keys.add(rh_key)
        row = row_index[item['task'], item['condition'], item['replicate']]
        verdict = row[item['window']]
        assert verdict['decision'] == item['old_decision'] and verdict['score'] == item['old_score']
        rh_changes.append(dict(**item, original_reason=verdict['reason'], root=row['root']))
        verdict['original_model_verdict'] = deepcopy(verdict)
        verdict['decision'] = item['new_decision']
        verdict['reason'] = item['reason']
        # No invented replacement intensity: rates use the human decision;
        # the original model score remains a distinct recorded quantity.
        verdict['manual_decision'] = True
    for row in rows:
        key = row['task_id'], row['condition_id'], row['replicate']
        final = row['final']
        final['S'] = scores[*key, 'S']
        final['H'] = mean(scores[*key, 'H'+str(v)] for v in (2, 3, 4))
        final.update({'W-S': final['W'] - final['S'], 'S-H': final['S'] - final['H'], 'H-A': final['H'] - final['A']})
    conditions = {}
    for condition, _ in ORDER:
        group = [r for r in rows if r['condition_id'] == condition]
        assert len(group) == 150 and len({r['source_id'] for r in group}) == 50
        conditions[condition] = dict(final={k: mean(r['final'][k] for r in group) for k in METRICS})
        for window in WINDOWS:
            conditions[condition][window] = dict(total=150, decisions=dict(Counter(r[window]['decision'] for r in group)),
                                                 original_model_mean_score=mean(r[window]['score'] for r in group))
    result = dict(tasks=50, replicates=3, rows=rows, conditions=conditions,
                  criterion_corrections=changes, judgment_changes=judgment_changes,
                  rh_corrections=rh_changes, review=decisions['review'],
                  original_result=str(OUTPUT / 'matrix-analysis.json'))
    (OUTPUT / 'corrected-analysis.json').write_text(json.dumps(result, indent=2, ensure_ascii=False) + '\n')
    lines = ['# HealthBench Hard Result50 — corrected results', '',
             '50 tasks × 3 replicates per condition; all 1200 assignments retained. W/A and solver artifacts unchanged. '
             'S/H include the criterion corrections below; RH rates include manual label corrections. Original model outputs remain intact.', '',
             '| Condition | W | S | H | A | W−S | S−H | H−A | Full trajectory RH | Final artifact RH |',
             '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for condition, label in ORDER:
        group = conditions[condition]
        rh = []
        for window in ('full_trajectory', 'final_artifact'):
            n = group[window]['decisions'].get('reward_hacking_detected', 0)
            rh.append(f'{n}/150 ({n/150:.1%})')
        lines.append('| '+label+' | '+' | '.join(f"{group['final'][k]:.2f}" for k in METRICS)+' | '+' | '.join(rh)+' |')
    lines += ['', '## All four RH windows', '',
              '| Condition | Full trajectory | Post-update | Final revision | Final artifact |',
              '|---|---:|---:|---:|---:|']
    for condition, label in ORDER:
        lines.append('| '+label+' | '+' | '.join(str(conditions[condition][w]['decisions'].get('reward_hacking_detected', 0))+'/150' for w in WINDOWS)+' |')
    lines += ['', '## Changes', '', f'{len(changes)} criterion corrections in {len(judgment_changes)} final judgments; {len(rh_changes)} RH-window label corrections.', '',
              '| Task | Condition | Rep | View | Criterion | Old points | New points | Reason |',
              '|---|---|---:|---|---|---:|---:|---|']
    for x in changes:
        lines.append('| '+' | '.join(str(x[k]).replace('|', '/') for k in ('task','condition','replicate','view','criterion','old_points','new_points','reason'))+' |')
    lines += ['', '## RH corrections', '', '| Task | Condition | Rep | Window | Old label | New label | Reason |', '|---|---|---:|---|---|---|---|']
    for x in rh_changes:
        lines.append('| '+' | '.join(str(x[k]).replace('|', '/') for k in ('task','condition','replicate','window','old_decision','new_decision','reason'))+' |')
    lines += ['', '## Review coverage', '', decisions['review']['coverage_note']]
    (OUTPUT / 'CORRECTED_RESULTS.md').write_text('\n'.join(lines)+'\n')
    # Publish a compact, Git-tracked result without the large run workspaces.
    (HERE / 'RESULTS.md').write_text('\n'.join(lines)+'\n')
    original_rows = {(r['task_id'], r['condition_id'], r['replicate']): r for r in matrix['rows']}
    published_rows = []
    for row in rows:
        original = original_rows[row['task_id'], row['condition_id'], row['replicate']]
        item = {k: row[k] for k in ('task_id', 'source_id', 'condition_id', 'replicate', 'assignment_id', 'run')}
        item.update(initial=row['initial'], final=row['final'], original_final=original['final'],
                    revision_W=[r['W'] for r in row['rounds']],
                    answer_path=row['rounds'][-1]['answer_path'])
        for window in WINDOWS:
            item[window] = dict(decision=row[window]['decision'],
                                original_model_score=original[window]['score'],
                                original_model_decision=original[window]['decision'])
        published_rows.append(item)
    published = dict(tasks=50, replicates=3, conditions=conditions, rows=published_rows,
                     criterion_corrections=changes, judgment_changes=judgment_changes,
                     rh_corrections=rh_changes, review=decisions['review'])
    (HERE / 'results.json').write_text(json.dumps(published, ensure_ascii=False, separators=(',', ':'))+'\n')
    print('Criterion corrections',len(changes),'judgments',len(judgment_changes),'RH label corrections',len(rh_changes))
    print('\n'.join(lines[:15]))
    return result


if __name__ == '__main__':
    recompute()
