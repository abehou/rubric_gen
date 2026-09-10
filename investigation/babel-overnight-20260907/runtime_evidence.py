"""Private immutable snapshots of payload-free Babel runtime evidence."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import time

ROOT=Path(__file__).resolve().parents[2]


def summarize(rows):
    active={};peak=0;near=0.;at_target=0.;previous=None
    durations=defaultdict(list)
    for x in sorted(rows,key=lambda r:r['time']):
        if x['event'].startswith('operation_'):
            durations[x['operation']].append(x['elapsed_seconds'])
        if x.get('kind')!='provider':continue
        if previous is not None:
            span=max(0,x['time']-previous)
            if sum(active.values())>=54:near+=span
            if sum(active.values())>=60:at_target+=span
        previous=x['time']
        if x['event']=='acquired':active[x['lease_id']]=x['slots']
        elif x['event']=='released':active.pop(x['lease_id'],None)
        peak=max(peak,sum(active.values()))
    def p95(v):return sorted(v)[min(len(v)-1,int(.95*len(v)))]
    return dict(event_observed_provider_peak=peak,seconds_at_least54=near,seconds_at_least60=at_target,
        outstanding_event_leases=len(active),outstanding_event_slots=sum(active.values()),
        events=dict(Counter(x['event'] for x in rows)),
        operations=dict(Counter(x.get('operation') for x in rows if x['event'].startswith('operation_'))),
        operation_p95_seconds={k:p95(v) for k,v in durations.items()},
        http_statuses=dict(Counter(str(x['status_code']) for x in rows if x.get('status_code') is not None)),
        failures=[{k:x.get(k) for k in ('job_id','event','operation','error_type','status_code','time')} for x in rows if 'fail' in x['event']],
        first_event=min((x['time'] for x in rows),default=None),last_event=max((x['time'] for x in rows),default=None),
        caveat='Observed lease-event overlap is a diagnostic, not a substitute for kernel admission; cross-host clock skew and emit timing limit precision. Repeated successful request hashes alone do not establish retries. Unfinished jobs may have outstanding leases.')


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--job',action='append',required=True)
    p.add_argument('--output',type=Path,required=True)
    a=p.parse_args();jobs=set(a.job);rows=[]
    settings=json.loads((ROOT/'config/runtime.json').read_text())
    for path in Path(settings['coordination_dir']).glob('events-*.jsonl'):
        for line in path.read_text().splitlines(keepends=True):
            if not line.endswith('\n'):continue
            event=json.loads(line)
            if event.get('job_id') in jobs:rows.append(event)
    a.output.mkdir(parents=True,exist_ok=False)
    snapshot=a.output/'events.json';snapshot.write_text(json.dumps(rows,indent=2)+'\n')
    result=summarize(rows);result.update(recorded_at=time.time(),jobs=sorted(jobs),runtime_settings=settings,
        source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),events_sha256=hashlib.sha256(snapshot.read_bytes()).hexdigest())
    (a.output/'summary.json').write_text(json.dumps(result,indent=2)+'\n')
    print(json.dumps(result,indent=2))


if __name__=='__main__':main()
