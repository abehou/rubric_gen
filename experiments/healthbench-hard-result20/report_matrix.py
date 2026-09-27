"""Offline eight-condition report; original outcomes are never overwritten."""
from collections import Counter, defaultdict
import json
from pathlib import Path
from statistics import mean

import inspect_solver
from prepare_remaining import HERE, ROOT, OUTPUT
from rubric_gen.runtime.process_environment import install_controlled_process_environment
from rubric_gen.submission_revision.experiment import load_experiment

install_controlled_process_environment()
METRICS = ('W','S','H','A','W-S','S-H','H-A')
WINDOWS = ('full_trajectory','post_update','final_revision','final_artifact')
FEEDBACKS = ('full','semi','score-only','user-simulator')


def rh_records(root):
    result={}
    for window in WINDOWS:
        files=list((root/f'direct_{window}').glob('evaluations/*/summary.json'))
        assert len(files)==1, (window, files)
        summary=json.loads(files[0].read_text())
        assert summary['models']==['gpt-6-luna']
        records=summary['records']
        assert len(records)==240 and len({r['source_path'] for r in records})==240
        assert all(r['status']=='completed' and r['model']=='gpt-6-luna' for r in records)
        result[window]={r['source_path']:r['verdict'] for r in records}
    return result


def collect():
    e=load_experiment(HERE/'remaining.yaml')
    study=Path(e.dag['revise']['output_dir']); audit=Path(e.dag['detect']['output_dir'])
    manifest=json.loads((study/'study.json').read_text())
    assert len(manifest['records'])==240 and all(r['status']=='completed' for r in manifest['records'])
    summaries={}
    for stage,models in [('rubric_score',['gpt-6-luna']),('absolute_score',['gpt-6-sol']),('pairwise_preference',['gpt-6-sol'])]:
        d=json.loads((audit/stage/'summary.json').read_text())
        assert d['status']=='completed' and d['models']==models
        assert not d['missing_models'] and not d['judge_failures']
        assert d['planned_semantic_judgment_count']==d['successful_semantic_judgment_count']
        assert d['assignment_coverage']['evaluated_assignment_count']==240
        records=list((audit/stage/'records').glob('*.json'))
        assert len(records)==d['planned_semantic_judgment_count']
        for path in records:
            record=json.loads(path.read_text())
            assert record['model'] in models
            if 'generation' in record:
                assert record['generation']['effective_model'] in models
                assert record['generation']['request_parameters']['reasoning_effort']=='high'
        summaries[stage]=d
    byid={stage:{r['assignment_id']:r for r in d['assignments']} for stage,d in summaries.items()}
    inspect_solver.STUDY=study
    solver=inspect_solver.inspect()
    original=json.loads((HERE/'analysis.json').read_text())
    rows=original['rows']
    old_rh=rh_records(ROOT/'runs/healthbench-hard-challenge20-local-20260926/rh-answer-only-v2')
    for r in rows:
        for w in WINDOWS: r[w]=old_rh[w][str(ROOT/r['root'])]
    new_rh=rh_records(audit)
    for r in solver['rows']:
        aid='--'.join([r['task_id'],f"rep-{r['replicate']:03d}",'solver-luna',r['condition_id']])
        rub=byid['rubric_score'][aid]['reference_scores']
        ab=byid['absolute_score'][aid]['rubric_free_absolute_scores']
        out={k:r[k] for k in ('task_id','replicate','condition_id','root')}
        out['rounds']=[{k:v for k,v in step.items() if k!='answer'} for step in r['rounds']]
        for phase,index in [('initial',0),('final',-1)]:
            assert rub['holdout'][phase]['variant_count']==3
            v=dict(W=r['rounds'][index]['W'],S=rub['selected'][phase]['mean'],
                   H=rub['holdout'][phase]['mean'],A=ab[phase+'_panel_mean'])
            v.update({'W-S':v['W']-v['S'],'S-H':v['S']-v['H'],'H-A':v['H']-v['A']})
            out[phase]=v
        for w in WINDOWS: out[w]=new_rh[w][str(ROOT/r['root'])]
        rows.append(out)
    assert len(rows)==480
    # Ensure all eight arms share the actual task/replicate initial answer.
    seeds={}
    for r in rows:
        key=(r['task_id'],r['replicate'])
        answer=(ROOT/r['rounds'][0]['answer_path']).read_bytes()
        if key in seeds: assert answer==seeds[key],key
        seeds[key]=answer
    groups=defaultdict(list)
    for r in rows: groups[r['condition_id']].append(r)
    conditions={}
    for c,rr in groups.items():
        assert len(rr)==60
        conditions[c]={'final':{k:mean(r['final'][k] for r in rr) for k in METRICS},
            'W_curve':[mean(r['rounds'][i]['W'] for r in rr) for i in range(4)],
            **{w:dict(Counter(r[w]['decision'] for r in rr)) for w in WINDOWS}}
    return dict(conditions=conditions,rows=rows,
        new_coverage={k:d['successful_semantic_judgment_count'] for k,d in summaries.items()},
        new_budget=json.loads((OUTPUT/'budget.json').read_text()))


def render(result):
    lines=['# HealthBench Hard Result20 — complete 4×2 matrix','',
        '20 tasks × 3 replicates per cell. W/S/H/A on 0–100 scale; signed gaps. '
        'S/H/A are endpoints, intermediate curves are W only. '
        'All RH cells use the corrected answer-only detector, gpt-6-luna high. '
        'Raw detector decisions; abstentions are retained, not converted to negatives.','',
        '| Feedback | Rubric | W | S | H | A | W−S | S−H | H−A | Full RH | Artifact RH |',
        '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|']
    ordered=[(f,p,f+'-'+p) for f in FEEDBACKS for p in ('static','red-team-trace')]
    for f,p,c in ordered:
        v=result['conditions'][c]
        lines.append('| '+f+' | '+p+' | '+' | '.join(f"{v['final'][k]:.2f}" for k in METRICS)+' | '+
            ' | '.join(f"{v[w].get('reward_hacking_detected',0)}/60" for w in ('full_trajectory','final_artifact'))+' |')
    lines+=['','## W by revision','',
        'Initial answer bytes match across all eight conditions for every task/replicate. '
        'The extension reuses seeds but performs its own online W judgments, so its R0 mean is23.34 '
        'rather than the original batch\'s24.70; this is scoring variation, not different starting answers.',
        '','| Condition | R0 | R1 | R2 | R3 |','|---|---:|---:|---:|---:|']
    for _,_,c in ordered: lines.append('| '+c+' | '+' | '.join(f'{v:.2f}' for v in result['conditions'][c]['W_curve'])+' |')
    lines+=['','## Four RH windows (positive / abstain / total)','','| Condition | Full | Post-update | Final revision | Artifact |','|---|---|---|---|---|']
    for _,_,c in ordered:
        v=result['conditions'][c]
        lines.append('| '+c+' | '+' | '.join(f"{v[w].get('reward_hacking_detected',0)} / {v[w].get('abstain',0)} / 60" for w in WINDOWS)+' |')
    lines+=['',f"Additional recorded cost: ${result['new_budget']['spent_usd']:.6f}; unknown usage: {result['new_budget']['uncertain']}."]
    return '\n'.join(lines)+'\n'


if __name__=='__main__':
    result=collect()
    (OUTPUT/'matrix-analysis.json').write_text(json.dumps(result,indent=2)+'\n')
    (OUTPUT/'MATRIX.md').write_text(render(result))
    print(render(result))
