"""Provider-free counts over complete fixed feedback records; no verdict editing."""
from collections import Counter, defaultdict
import csv,json,os
from pathlib import Path

BUNDLE=Path(__file__).resolve().parent
REPORT=BUNDLE.parents[1]/'docs/reports/2026-09-12/trace-user-public-evidence-firewall'


def main():
    if not os.environ.get('SLURM_JOB_ID'): raise RuntimeError('raw data are compute-only; run this report script through Slurm')
    data=json.loads(Path('/data/user_data/aydanh/rubric_gen/runs/trace-user-public-evidence-firewall-20260912/feedback-checks/feedback-results.json').read_text())
    summaries={}; table=[]; costs=defaultdict(lambda:dict(calls=0,input_tokens=0,output_tokens=0,cached_input_tokens=0,wall_seconds=0))
    for cell in ('P1','P2'):
        rows=[r for r in data['rows'] if r['cell']==cell]
        stages=[s for r in rows for s in r.get('stages',[])]
        attempts=[a for s in stages for a in s['attempts']]
        usage=[]
        for a in attempts:
            metadata=a.get('provider',{}).get('provider_metadata',{})
            usage.append(metadata.get('usage',{}))
        summary={'checkpoints':len(rows),'completed':sum(r['status']=='completed' for r in rows),
            'stages':len(stages),'stage_types':dict(Counter(s['stage'].rsplit('-',1)[-1] for s in stages)),
            'attempts':len(attempts),'attempt_status':dict(Counter(a['status'] for a in attempts)),
            'retries':sum(len(s['attempts'])-1 for s in stages),'first_attempt_valid':sum(s['attempts'][0]['status']=='valid_result' for s in stages),
            'locator_decisions':dict(Counter(s['output']['decision'] for s in stages if s['stage']=='locator')),
            'issue_types':dict(Counter(i['issue_type'] for s in stages if s['stage']=='locator' for i in s['output']['issues'])),
            'verifier_decisions':dict(Counter(s['output']['decision'] for s in stages if s['stage'].endswith('verify'))),
            'renderer_decisions':dict(Counter(s['output']['decision'] for s in stages if s['stage'].endswith('render'))),
            'concerns':sum(len(r.get('output',{}).get('concerns',[])) for r in rows),
            'checkpoint_decisions':dict(Counter(r['output']['decision'] for r in rows if r['status']=='completed')),
            'sum_stage_wall_seconds':sum(a['wall_seconds'] for a in attempts),
            'input_tokens':sum(u['input_tokens'] for u in usage),
            'output_tokens':sum(u['output_tokens'] for u in usage),
            'cached_input_tokens':sum(u.get('input_tokens_details',{}).get('cached_tokens',0) for u in usage)}
        for stage in stages:
            c=costs[cell+'/'+stage['stage'].rsplit('-',1)[-1]]
            for attempt in stage['attempts']:
                u=attempt['provider']['provider_metadata']['usage'];c['calls']+=1
                c['input_tokens']+=u['input_tokens'];c['output_tokens']+=u['output_tokens']
                c['cached_input_tokens']+=u.get('input_tokens_details',{}).get('cached_tokens',0)
                c['wall_seconds']+=attempt['wall_seconds']
        summaries[cell]=summary
        for r in rows:
            table.append(dict(cell=cell,case=r['case'],status=r['status'],
                decision=r.get('output',{}).get('decision'), concerns=len(r.get('output',{}).get('concerns',[])),
                stages=len(r.get('stages',[])),attempts=sum(len(s['attempts']) for s in r.get('stages',[])),
                result_path=r.get('result_path'),wall_seconds=r.get('wall_seconds')))
    REPORT.mkdir(parents=True,exist_ok=True)
    (REPORT/'pipeline-summary.json').write_text(json.dumps({'job':data['job'],'execution_commit':data['commit'],
        'runtime_policy':data['runtime_policy'],'wall_seconds':data['wall_seconds'],'variants':summaries,'cost_by_stage':dict(costs)},indent=2)+'\n')
    with (REPORT/'checkpoint-accounting.csv').open('w') as f:
        writer=csv.DictWriter(f,fieldnames=list(table[0]));writer.writeheader();writer.writerows(table)
    print(json.dumps({k:{x:v for x,v in s.items() if x!='usage_records'} for k,s in summaries.items()},indent=2))

if __name__=='__main__': main()
