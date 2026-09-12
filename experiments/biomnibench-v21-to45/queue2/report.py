"""Reuse the existing complete-cohort outcome and paired-analysis implementation."""
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'experiments/trace-attack-defense-v3'))
import report_dev3_outcomes as outcomes

OUT=ROOT/'docs/reports/2026-09-12/biomnibench-v21-to45/queue2'
control=json.loads((ROOT/'docs/reports/2026-09-12/trace-user-parallel-diagnostics/control-outcomes.json').read_text())
rows={'R0':control['rows']}
coverage={'R0':control['coverage']}
delivery={}
for cell in ('R1','R2'):
    rows[cell]=[];coverage[cell]=[];delivery[cell]=[]
    for task in ('da-3-4','da-11-1','da-18-1'):
        config=ROOT/f'experiments/biomnibench-v21-to45/queue2/configs/{cell}/{task}.yaml'
        exp,cov,values=outcomes.reconstruct(config)
        coverage[cell].append({'task':task,'coverage':cov});rows[cell].extend(values)
        for value in values:
            if value['model']!=outcomes.PANEL[0]:
                continue
            root=Path(value['state_path']).parent
            records=[json.loads(p.read_text()) for p in sorted((root/'trace-defense-reminders').glob('s*.json'))]
            delivery[cell].append({'task':task,'replicate':value['replicate'],'root':str(root),
                'selected':sum(r['selection'] is not None for r in records),
                'corrective_selected':sum(bool(r['selection'] and r['selection']['corrective']) for r in records),
                'appendix_emitted':sum(r['appendix_emitted'] for r in records),
                'appendix_suppressed':sum(r['appendix_suppressed'] for r in records),
                'retained_revisions':value['retained_revisions'],'stop_reason':value['stop_reason']})
summaries={cell:outcomes.summarize(values) for cell,values in rows.items()}
contrasts={};paired=[]
for lhs,rhs in (('R1','R0'),('R2','R0'),('R2','R1')):
    values,summary=outcomes.paired(rows[lhs],rows[rhs]);contrasts[f'{lhs}-{rhs}']=summary
    paired.extend({'contrast':f'{lhs}-{rhs}',**r} for r in values)
OUT.mkdir(parents=True,exist_ok=True)
(OUT/'outcomes.json').write_text(json.dumps({'provider_calls':0,'summaries':summaries,'coverage':coverage,
    'contrasts':contrasts,'paired_rows':paired,'delivery':delivery,'rows':rows},indent=2)+'\n')
flat=[{'variant':cell,'task':r['task_id'],'replicate':r['replicate'],'auditor':r['model'],**outcomes.add_values(r)}
      for cell,values in rows.items() for r in values]
outcomes.write_csv(OUT/'outcomes-per-auditor.csv',flat)
metrics=('W','W_train','S','H','A','W_minus_S','S_minus_H','H_minus_A','W_minus_A',
         'RH_full_trajectory','RH_post_update','RH_final_artifact','RH_final_revision')
lines=['# Queue 2: completed native outcomes','',
    'R0 is the saved v2.1 trace control, not a static baseline. Three task clusters; paired changes are developmental and descriptive. No automatic winner or scale-up is selected here.','',
    '| Variant | '+' | '.join(metrics)+' |','|---|'+'---:|'*len(metrics)]
for cell,summary in summaries.items():
    lines.append('| '+cell+' | '+' | '.join(f"{summary['means'][m]:.2f}" for m in metrics)+' |')
lines+=['','All four RH windows, individual auditors, abstentions, exact coverage and task-level paired contrasts are retained in [JSON](outcomes.json) and [CSV](outcomes-per-auditor.csv).',
        'Actual appendix selection/emission/suppression is separate from learned-rule influence in ordinary simulator feedback. Case review remains necessary before scientific interpretation.','']
(OUT/'outcomes.md').write_text('\n'.join(lines))
print(json.dumps({'assignments':{c:s['assignments'] for c,s in summaries.items()},'provider_calls':0}))
