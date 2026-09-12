"""Read-only canonical feedback-cell inventory; no provider calls."""
import json
from collections import Counter
from pathlib import Path
import yaml
ROOT=Path(__file__).resolve().parents[3]
TASKS={'da-3-4','da-11-1','da-18-1'}
roots={}
for p in (ROOT/'experiments').rglob('*.yaml'):
    try:
        d=yaml.safe_load(p.read_text())
        if not isinstance(d,dict) or d.get('benchmark')!='biomnibench-da': continue
        tasks=d.get('tasks',[])
        if not tasks or not set(tasks)<=TASKS: continue
        raw=d.get('dag',{}).get('revise',{}).get('output_dir','')
        if not raw: continue
        base=Path(raw.split('{experiment_id}')[0])
        if not base.is_absolute(): base=ROOT/base
        key=str(base)
        roots.setdefault(key,{'configs':[],'studies':[]})['configs'].append(str(p.relative_to(ROOT)))
        if not Path(raw).is_absolute():
            legacy=Path('/home/aydanh/repos/rubric_gen')/raw.split('{experiment_id}')[0]
            roots.setdefault(str(legacy),{'configs':[],'studies':[]})['configs'].append(str(p.relative_to(ROOT)))
    except (OSError,ValueError,yaml.YAMLError): continue
for key,r in roots.items():
    root=Path(key)
    ledgers=([root/'study.json'] if (root/'study.json').is_file() else sorted(root.glob('*/study.json')))
    for p in ledgers:
        d=json.loads(p.read_text())
        records=d.get('records',[])
        if isinstance(records,dict): records=list(records.values())
        rows=Counter((a.get('task_id'),a.get('condition_id'),a.get('status')) for a in records)
        r['studies'].append({'path':str(p),'experiment_id':d.get('experiment_id'),'status':d.get('status'),
            'counts':[{'task':k[0],'condition':k[1],'status':k[2],'count':v} for k,v in sorted(rows.items(),key=str)],
            'seed_root':d.get('seed_run_dir'),'paraphrase_root':d.get('paraphrase_run_dir'),'recorded_experiment_path':d.get('experiment_path')})
out=ROOT/'docs/reports/2026-09-12/biomnibench-v21-to45/queue3/inventory.json'
out.write_text(json.dumps({'provider_calls':0,'roots':roots},indent=2)+'\n')
for key,r in roots.items():
    if r['studies']:
        print(json.dumps({'root':key,'studies':[{'status':s['status'],'counts':s['counts']} for s in r['studies']]}),flush=True)
print(json.dumps({'searched_roots':len(roots),'existing_studies':sum(len(r['studies']) for r in roots.values())}))
