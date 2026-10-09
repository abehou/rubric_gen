"""Offline task/criterion evidence for S-H; never modifies grades or labels."""
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import stat
from statistics import mean

from prepare import HERE, ROOT, OUTPUT
from report_matrix import BATCHES, WINDOWS

STYLES = ('full','semi','score-only','user-simulator')


def read(path):
    return json.loads(path.read_text())


def evaluation(record):
    # The native response journal contains the exact published evaluation.
    # Read it directly: macOS has offloaded some redundant evaluation files.
    path=Path(record['evaluation_path'])
    native=path.parent.parent/(path.parent.name+'.response.json')
    for candidate in (path,native):
        if not candidate.exists() or candidate.stat().st_flags & getattr(stat,'SF_DATALESS',0x40000000):
            continue
        try:
            saved=read(candidate)
        except json.JSONDecodeError:
            continue
        if candidate==path:
            assert abs(saved['total_score']-record['score'])<1e-8
            return saved
        assert saved['identity']['answer_input_sha256']==record['answer_input_sha256']
        assert abs(saved['records']['score']-record['score'])<1e-8
        return saved['records']['evaluation']
    return None


def collect():
    matrix=read(OUTPUT/'matrix-analysis.json')
    rows=matrix['rows']
    summaries={}
    index={}
    variant_files={}
    for directory,eid,n in BATCHES:
        run=ROOT/'runs'/directory
        folder=run/'audits'/eid/'rubric_score'
        summaries[directory]={r['assignment_id']:r for r in read(folder/'summary.json')['assignments']}
        index[directory]=defaultdict(list)
        for path in (folder/'records').glob('*.json'):
            r=read(path)
            index[directory][r['task_id'],r['answer_input_sha256']].append(r)
        for path in (run/'paraphrases/tasks').glob('*/variant-*.txt'):
            variant_files[path.parent.name,hashlib.sha256(path.read_bytes()).hexdigest()]=path
    cells=[]
    disagreements=[]
    unavailable=[]
    for row in rows:
        rr=summaries[row['run']][row['assignment_id']]['reference_scores']
        answer=ROOT/row['rounds'][-1]['answer_path']
        records=index[row['run']][row['task_id'],hashlib.sha256(answer.read_bytes()).hexdigest()]
        snapshot=read(answer.parent.parent/'snapshot.json')['workspace_sha256']
        records=[r for r in records if r['submission_content_sha256']==snapshot]
        # Native records may deduplicate identical answers between assignments.
        by_rubric={r['rubric_sha256']:r for r in records}
        selected_sha=rr['active_local']['initial']['rubric_sha256']
        selected=by_rubric[selected_sha]
        assert abs(selected['score']-row['final']['S'])<1e-8, row['assignment_id']
        selected_eval=evaluation(selected)
        heldout=[]
        for variant in (2,3,4):
            matches=[(sha,p) for (task,sha),p in variant_files.items()
                     if task==row['task_id'] and p.name==f'variant-{variant:03d}.txt']
            assert len(matches)==1
            sha,path=matches[0];record=by_rubric[sha]
            assert abs(record['score']-rr['holdout']['final']['variants'][str(variant)]['mean'])<1e-8, row['assignment_id']
            heldout.append((variant,path,record,evaluation(record)))
        if selected_eval is None or any(e is None for _,_,_,e in heldout):
            unavailable.append(row['assignment_id'])
            continue  # Outcome rows remain included; only unavailable qualitative files are listed.
        allcriteria=selected_eval['criteria']
        for cid,grade in allcriteria.items():
            hgrades=[(variant,path,record,e['criteria'][cid]) for variant,path,record,e in heldout]
            if any(g['points']!=grade['points'] for _,_,_,g in hgrades):
                disagreements.append(dict(task=row['task_id'],condition=row['condition_id'],replicate=row['replicate'],
                    criterion=cid,selected_points=grade['points'],heldout_points=[g['points'] for _,_,_,g in hgrades],
                    selected_reason=grade['reason'],heldout_reasons=[g['reason'] for _,_,_,g in hgrades],
                    selected_score=selected['score'],heldout_scores=[r['score'] for _,_,r,_ in heldout],
                    selected_evaluation=selected['evaluation_path'],heldout_evaluations=[r['evaluation_path'] for _,_,r,_ in heldout],
                    selected_rubric=str(variant_files[row['task_id'],selected_sha]),
                    heldout_rubrics=[str(p) for _,p,_,_ in heldout],answer=str(answer)))
    tasks=sorted({r['task_id'] for r in rows})
    for task in tasks:
        entry=dict(task=task,batch='new30' if any(r['task_id']==task and r['run']==BATCHES[2][0] for r in rows) else 'old20',styles={})
        for style in STYLES:
            arms={p:[r for r in rows if r['task_id']==task and r['condition_id']==style+'-'+p] for p in ('static','red-team-trace')}
            entry['styles'][style]={p:{**{k:mean(r['final'][k] for r in rr) for k in ('S','H','S-H')},
                    'replicate_gaps':[r['final']['S-H'] for r in sorted(rr,key=lambda r:r['replicate'])]}
                    for p,rr in arms.items()}
            entry['styles'][style]['RTT_minus_static']=entry['styles'][style]['red-team-trace']['S-H']-entry['styles'][style]['static']['S-H']
        cells.append(entry)
    batches={}
    for batch in ('old20','new30','all50'):
        batches[batch]={}
        for style in STYLES:
            batches[batch][style]={}
            for policy in ('static','red-team-trace'):
                rr=[r for r in rows if r['condition_id']==style+'-'+policy and (batch=='all50' or (r['run']==BATCHES[2][0])==(batch=='new30'))]
                gaps=[r['final']['S-H'] for r in rr]
                batches[batch][style][policy]=dict(mean=mean(gaps),n=len(gaps),negative=sum(g< -1e-6 for g in gaps),
                    zero=sum(abs(g)<1e-6 for g in gaps),positive=sum(g>1e-6 for g in gaps),
                    near_zero_within_one=sum(abs(g)<=1 for g in gaps))
    return dict(tasks=cells,batches=batches,disagreements=disagreements,
                unavailable_qualitative_artifacts=unavailable)


if __name__=='__main__':
    result=collect()
    (OUTPUT/'sh-task-inspection.json').write_text(json.dumps(result,indent=2)+'\n')
    lines=['# Result50 task-by-task S-H (three-replicate means)','',
           '| Task | Batch | Full Static | Full RTT | Semi Static | Semi RTT | Score-only Static | Score-only RTT | User Static | User RTT |',
           '|---|---|---:|---:|---:|---:|---:|---:|---:|---:|']
    for t in result['tasks']:
        values=[t['styles'][style][policy]['S-H'] for style in STYLES for policy in ('static','red-team-trace')]
        lines.append('| '+t['task']+' | '+t['batch']+' | '+' | '.join(f'{v:.2f}' for v in values)+' |')
    (OUTPUT/'SH_TASK_TABLE.md').write_text('\n'.join(lines)+'\n')
    print('Saved50-task table and',len(result['disagreements']),'criterion-disagreement records; no API calls')
