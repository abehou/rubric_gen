"""Offline Result50 matrix from complete saved assignments; no API calls."""
from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import mean
import sys

from prepare import HERE, ROOT, OUTPUT

sys.path.insert(0, str(HERE.parent/'healthbench-hard-result20'))
import inspect_solver

METRICS = ('W', 'S', 'H', 'A', 'W-S', 'S-H', 'H-A')
WINDOWS = ('full_trajectory', 'post_update', 'final_revision', 'final_artifact')
ORDER = [(style+'-'+policy, label+' × '+name)
         for style,label in (('full','Full'),('semi','Semi'),('score-only','Score-only'),
                             ('user-simulator','User'))
         for policy,name in (('static','Static'),('red-team-trace','RTT'))]
BATCHES = [
    ('healthbench-hard-challenge20-local-20260926', 'healthbench-hard-factorial-r3-01eb8a5a9277',240),
    ('healthbench-hard-result20-semi-score-20260926', 'healthbench-hard-factorial-r3-ba842ae5e275',240),
    ('healthbench-hard-result50-extension-20261006', 'healthbench-hard-factorial-r3-654d4cc2a2e6',720),
]


def read(path):
    return json.loads(path.read_text())


def collect():
    assert read(OUTPUT/'audit-completion.json')['status'] == 'completed'
    manifest = read(HERE/'manifest50.json')
    tasks = manifest['retained20']+manifest['extension30']
    sources = {t['task_id']:t['source_id'] for t in tasks}
    assert len(sources) == len(set(sources.values())) == 50
    rows = []
    for directory,eid,n in BATCHES:
        root = ROOT/'runs'/directory
        study = root/'studies'/eid
        audit = root/'audits'/eid
        saved = read(study/'study.json')
        assert len(saved['records']) == n and all(r['status']=='completed' for r in saved['records'])
        summaries = {}
        for stage,model in (('rubric_score','gpt-6-luna'),('absolute_score','gpt-6-sol'),
                            ('pairwise_preference','gpt-6-sol')):
            s = read(audit/stage/'summary.json')
            assert s['status']=='completed' and s['models']==[model]
            assert not s['missing_models'] and not s['judge_failures']
            assert s['planned_semantic_judgment_count']==s['successful_semantic_judgment_count']
            assert s['assignment_coverage']['evaluated_assignment_count']==n
            summaries[stage] = {r['assignment_id']:r for r in s['assignments']}
            assert len(summaries[stage])==n
        rh_root = root/'rh-answer-only-v2' if directory == BATCHES[0][0] else audit
        rh = {}
        for window in WINDOWS:
            files = list((rh_root/f'direct_{window}').glob('evaluations/*/summary.json'))
            assert len(files)==1
            s = read(files[0])
            assert s['models']==['gpt-6-luna'] and len(s['records'])==n
            assert all(r['status'] in {'completed','skipped'} and r['model']=='gpt-6-luna'
                       for r in s['records'])
            rh[window] = {r['source_path']:r['verdict'] for r in s['records']}
            assert len(rh[window])==n
        inspect_solver.STUDY = study
        solver = inspect_solver.inspect()
        for r in solver['rows']:
            aid='--'.join([r['task_id'],f"rep-{r['replicate']:03d}",'solver-luna',r['condition_id']])
            rubric = summaries['rubric_score'][aid]['reference_scores']
            absolute = summaries['absolute_score'][aid]['rubric_free_absolute_scores']
            row = {k:r[k] for k in ('task_id','replicate','condition_id','root','stop')}
            row.update(source_id=sources[r['task_id']],assignment_id=aid,run=directory)
            row['rounds'] = [{k:v for k,v in x.items() if k!='answer'} for x in r['rounds']]
            for phase,index in (('initial',0),('final',-1)):
                assert rubric['holdout'][phase]['variant_count']==3
                values = dict(W=r['rounds'][index]['W'], S=rubric['selected'][phase]['mean'],
                              H=rubric['holdout'][phase]['mean'], A=absolute[phase+'_panel_mean'])
                values.update({'W-S':values['W']-values['S'], 'S-H':values['S']-values['H'],
                               'H-A':values['H']-values['A']})
                row[phase]=values
            for window in WINDOWS:
                row[window] = rh[window][str(ROOT/r['root'])]
                assert 0 <= row[window]['score'] <= 10
            rows.append(row)
    assert len(rows)==1200
    assert len({(r['source_id'],r['condition_id'],r['replicate']) for r in rows})==1200
    seed_bytes = {}
    for r in rows:
        key = (r['source_id'],r['replicate'])
        initial = (ROOT/r['rounds'][0]['answer_path']).read_bytes()
        if key in seed_bytes:
            assert initial==seed_bytes[key]
        seed_bytes[key]=initial
    assert len(seed_bytes)==150
    groups = defaultdict(list)
    for r in rows:
        groups[r['condition_id']].append(r)
    assert set(groups)=={c for c,_ in ORDER}
    conditions = {}
    for condition,rr in groups.items():
        assert len(rr)==150 and len({r['source_id'] for r in rr})==50
        assert all(Counter(r['source_id'] for r in rr)[t]==3 for t in sources.values())
        out={phase:{k:mean(r[phase][k] for r in rr) for k in METRICS}
             for phase in ('initial','final')}
        out['W_curve']=[mean(r['rounds'][i]['W'] for r in rr) for i in range(4)]
        for window in WINDOWS:
            out[window]=dict(decisions=dict(Counter(r[window]['decision'] for r in rr)),
                             mean_score=mean(r[window]['score'] for r in rr), total=150)
        conditions[condition]=out
    # Recomputed old20 endpoints must reproduce the published original matrix.
    previous=read(ROOT/'runs'/BATCHES[1][0]/'matrix-analysis.json')
    for condition,_ in ORDER:
        rr=[r for r in groups[condition] if r['run']!=BATCHES[2][0]]
        assert len(rr)==60
        for metric in METRICS:
            assert abs(mean(r['final'][metric] for r in rr)-previous['conditions'][condition]['final'][metric])<1e-8
    return dict(tasks=50,replicates=3,rows=rows,conditions=conditions,
                definition='Unchanged Result20: W online selected-base5.6Luna-low; S selected-base6Luna-high; '
                           'H mean of three heldout paraphrases6Luna-high; A rubric-free6Sol-high. '
                           'Endpoints/gaps0–100, RH intensity0–10; positives/all150 with abstentions listed separately. '
                           'RTT active penalties do not replace selected-base S. '
                           'R3 carries the last saved W only where a no-change turn saved no new answer. '
                           'Natural answer-only-v2 RH evidence; no synthetic red-team sidecars included.',
                provenance=[dict(run=directory,study=eid,assignments=n) for directory,eid,n in BATCHES])


def render(result):
    lines=['# HealthBench Hard Result50 — complete4×2 matrix','',
           '50 tasks ×3replicates per condition;1200 assignments total. Endpoint scores0–100; signed gaps.','',
           '| Condition | W | S | H | A | W−S | S−H | H−A | Full trajectory RH | Final artifact RH |',
           '|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    for condition,label in ORDER:
        v=result['conditions'][condition]
        rh=[]
        for window in ('full_trajectory','final_artifact'):
            count=v[window]['decisions'].get('reward_hacking_detected',0)
            rh.append(f'{count}/150 ({count/150:.1%})')
        lines.append('| '+label+' | '+' | '.join(f"{v['final'][k]:.2f}" for k in METRICS)+' | '+' | '.join(rh)+' |')
    lines+=['','## W by revision','',
            'Initial answer bytes match across all eight conditions for each source-task/replicate. '
            'No-change turns retain the last saved W; intermediate S/H/A were not independently audited.','',
            '| Condition | R0 | R1 | R2 | R3 |','|---|---:|---:|---:|---:|']
    for condition,label in ORDER:
        lines.append('| '+label+' | '+' | '.join(f'{v:.2f}' for v in result['conditions'][condition]['W_curve'])+' |')
    lines+=['','## RH windows: positive / abstain / total; mean intensity0–10','',
            '| Condition | Full | Post-update | Final revision | Artifact | Full mean | Artifact mean |',
            '|---|---|---|---|---|---:|---:|']
    for condition,label in ORDER:
        v=result['conditions'][condition]
        counts=[f"{v[w]['decisions'].get('reward_hacking_detected',0)} / {v[w]['decisions'].get('abstain',0)} /150" for w in WINDOWS]
        lines.append('| '+label+' | '+' | '.join(counts)+f" | {v['full_trajectory']['mean_score']:.2f} | {v['final_artifact']['mean_score']:.2f} |")
    lines+=['',result['definition'],'',
            'Coverage and model validation: audit-completion.json. Original Result20 reports/artifacts are preserved.']
    return '\n'.join(lines)+'\n'


if __name__=='__main__':
    result=collect()
    (OUTPUT/'matrix-analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    (OUTPUT/'MATRIX.md').write_text(render(result))
    print(render(result))
