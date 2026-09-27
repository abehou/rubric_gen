"""Offline descriptive analysis of the completed local Dev3; no model calls."""
from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[2]
RUN = ROOT / 'runs/healthbench-hard-local-mac-20260925-v2'
SID = 'healthbench-hard-factorial-r3-d189fa58c2f7'
STUDY = RUN / 'studies' / SID
AUDIT = RUN / 'audits' / SID


def read(path):
    return json.loads(path.read_text())


def analyze():
    study = read(STUDY / 'study.json')
    assert len(study['records']) == 36
    summaries = {name: read(AUDIT / name / 'summary.json')
                 for name in ['rubric_score', 'absolute_score', 'pairwise_preference']}
    for data in summaries.values():
        assert data['status'] == 'completed'
        assert data['successful_semantic_judgment_count'] == data['planned_semantic_judgment_count']
        assert data['failed_semantic_judgment_count'] == 0 and not data['missing_models']
        assert data['assignment_coverage']['evaluated_assignment_count'] == 36
    rubric = {x['assignment_id']: x for x in summaries['rubric_score']['assignments']}
    absolute = {x['assignment_id']: x for x in summaries['absolute_score']['assignments']}
    rows = []
    for record in study['records']:
        assert record['status'] == 'completed'
        aid = record['assignment_id']
        path = STUDY / record['experiment_dir']
        state = read(path / 'state.json')
        row = {k: record[k] for k in ['assignment_id', 'task_id', 'replicate', 'condition_id']}
        row['path'] = str(path.relative_to(ROOT))
        row['stop_reason'] = state['stop_reason']
        row['snapshots'] = len(state['submission_ids'])
        row['answer_words'] = []
        for phase, sub in [('initial', state['submission_ids'][0]), ('final', state['submission_ids'][-1])]:
            ev = read(path / 'rubric-evaluations' / (sub + '.json'))
            refs = rubric[aid]['reference_scores']
            values = dict(W=ev['reference_score'], W_train=ev['score'],
                          S=refs['selected'][phase]['mean'], H=refs['holdout'][phase]['mean'],
                          A=absolute[aid]['rubric_free_absolute_scores'][phase + '_panel_mean'])
            values.update(WS=values['W']-values['S'], SH=values['S']-values['H'], HA=values['H']-values['A'])
            row[phase] = values
            answer = path / 'submissions' / sub / 'workspace' / 'answer.txt'
            assert answer.is_file()
            row['answer_words'].append(len(answer.read_text().split()))
        row['rubric_changes'] = []
        manifests = [read(p) for p in sorted((path/'rubric-generations').glob('generation-*/manifest.json'))]
        for a,b in zip(manifests, manifests[1:]):
            if a['rubric_sha256'] != b['rubric_sha256']:
                row['rubric_changes'].append(b['generation_round'])
        rows.append(row)
    by_aid = {r['assignment_id']: r for r in rows}
    for window in ['full_trajectory', 'final_artifact', 'post_update', 'final_revision']:
        paths = list((AUDIT / ('direct_' + window)).rglob('summary.json'))
        assert len(paths) == 1
        records = read(paths[0])['records']
        assert len(records) == 36 and all(r['status']=='completed' for r in records)
        for rec in records:
            matches=[r for r in rows if str(ROOT / r['path']) == rec['source_path']]
            assert len(matches)==1
            matches[0][window]=rec['verdict']
    def group(keys):
        groups=defaultdict(list)
        for row in rows:
            groups[tuple(row[k] for k in keys)].append(row)
        result=[]
        for key, items in sorted(groups.items()):
            out=dict(zip(keys,key)); out['n']=len(items)
            for phase in ['initial','final']:
                # Balanced task/replicate cells make this task-equal mean exact.
                out[phase]={k:mean(i[phase][k] for i in items) for k in items[0][phase]}
            for window in ['full_trajectory','final_artifact']:
                out[window]=dict(Counter(i[window]['decision'] for i in items))
            result.append(out)
        return result
    return dict(definitions='W=online selected-base reference; S=independent Luna selected-base audit; H=Luna heldout variant 2; A=Luna rubric-free absolute quality. All 0–100. Signed gaps. Three tasks equally weighted, three replicates within each. No inferential population claim.',
                conditions=group(['condition_id']), tasks=group(['condition_id','task_id']), rows=rows)


if __name__ == '__main__':
    data=analyze()
    Path(__file__).with_name('analysis.json').write_text(json.dumps(data,indent=2)+'\n')
    for row in data['conditions']:
        print(row['condition_id'], {k:round(v,2) for k,v in row['final'].items()})
        print('initial', {k:round(v,2) for k,v in row['initial'].items()})
    for row in data['tasks']:
        print(row['condition_id'],row['task_id'],{k:round(v,2) for k,v in row['final'].items()})
