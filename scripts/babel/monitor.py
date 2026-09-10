"""Linux process/cgroup and runtime-event sampling; no experiment payload reads."""
import collections
import json
import os
import shutil
from pathlib import Path
import time
from rubric_gen.runtime.capacity import Slots, policy


class Monitor:
    def __init__(self, event_root, output, studies):
        self.root=Path(event_root);self.output=Path(output);self.studies=studies
        self.offsets={};self.counts=collections.Counter();self.requests=collections.Counter()
        self.started=time.monotonic();self.peak_rss=0;self.peak_processes=0
        self.cpu_ticks={};self.previous_sample=self.started
        self.baseline_completed=self._assignments()['completed'];self.durations=collections.defaultdict(list);self.waits=[]
        self.job_id=os.environ.get('SLURM_JOB_ID');self.status_codes=collections.Counter()
        self.failure_types=collections.Counter()

    def _assignments(self):
        counts=collections.Counter()
        for root in self.studies:
            p=Path(root)/"study.json"
            if p.exists():
                manifest=json.loads(p.read_text())
                scope=manifest.get("execution_conditions")
                counts.update(row["status"] for row in manifest["records"]
                              if scope is None or row["condition_id"] in scope)
        return counts

    def sample(self):
        table={}
        for p in Path('/proc').glob('[0-9]*/status'):
            try:
                fields=dict(line.split(':',1) for line in p.read_text().splitlines() if ':' in line)
                table[int(p.parent.name)]=(int(fields['PPid']),int(fields.get('VmRSS','0 kB').split()[0]),int(fields.get('Threads','0')))
            except (OSError,ValueError,KeyError):continue
        owned={os.getpid()}
        while True:
            extra={pid for pid,(parent,_,_) in table.items() if parent in owned}-owned
            if not extra:break
            owned.update(extra)
        now=time.monotonic();cpu_delta=0
        current_ticks={}
        for pid in owned:
            try:
                fields=(Path('/proc')/str(pid)/'stat').read_text().rsplit(')',1)[1].split()
                ticks=int(fields[11])+int(fields[12]);current_ticks[pid]=ticks
                cpu_delta+=max(0,ticks-self.cpu_ticks.get(pid,ticks))
            except (OSError,ValueError,IndexError):continue
        cpu_cores=cpu_delta/os.sysconf('SC_CLK_TCK')/max(now-self.previous_sample,.001)
        self.cpu_ticks=current_ticks;self.previous_sample=now
        disk=shutil.disk_usage(self.output.parent)
        rss=sum(table.get(pid,(0,0,0))[1] for pid in owned)
        self.peak_rss=max(self.peak_rss,rss);self.peak_processes=max(self.peak_processes,len(owned))
        for p in self.root.glob('events-*.jsonl'):
            with p.open() as f:
                f.seek(self.offsets.get(p,0))
                while True:
                    start=f.tell();line=f.readline()
                    if not line:break
                    if not line.endswith('\n'):f.seek(start);break
                    event=json.loads(line)
                    if event.get('job_id')!=self.job_id:continue
                    name=event['event'];op=event.get('operation','')
                    self.counts[f'{name}:{op}']+=1
                    if name in ('operation_completed','operation_failed','operation_returned_failure'):
                        self.requests[event['request_key']]+=1
                        self.durations[op].append(event['elapsed_seconds'])
                    if name=='acquired' and event.get('kind')=='provider':self.waits.append(event['wait_seconds'])
                    if event.get('status_code') is not None:self.status_codes[str(event['status_code'])]+=1
                    if name=='operation_failed':self.failure_types[event.get('error_type') or 'unknown']+=1
                self.offsets[p]=f.tell()
        assignments=self._assignments()
        cgroup={}
        try:
            entries=Path('/proc/self/cgroup').read_text().splitlines()
            relative=next(x.split(':',2)[2] for x in entries if x.startswith('0::'))
            root=Path('/sys/fs/cgroup')/relative.lstrip('/')
            for name in ('memory.current','memory.peak','memory.max','memory.events','pids.current','pids.peak'):
                if (root/name).exists():cgroup[name]=(root/name).read_text().strip()
        except (OSError,StopIteration):pass
        active=Slots(self.root/"provider",policy()["aggregate_concurrency"]).active_count()
        elapsed=time.monotonic()-self.started
        def p95(values):return sorted(values)[min(len(values)-1,int(.95*len(values)))] if values else None
        result=dict(sampled_cpu_cores=cpu_cores,disk_free_bytes=disk.free,disk_free_fraction=disk.free/disk.total,provider_wait_p95_seconds=p95(self.waits),operation_p95_seconds={k:p95(v) for k,v in self.durations.items()},
            completed_operations_per_minute={k:self.counts[f'operation_completed:{k}']/max(elapsed,1)*60 for k in self.durations},
            active_audit_studies=Slots(self.root/'audit',1).active_count(),active_provider_slots=active,time=time.time(),elapsed_seconds=elapsed,rss_kib=rss,peak_sampled_rss_kib=self.peak_rss,
            processes=len(owned),peak_processes=self.peak_processes,threads=sum(table.get(p,(0,0,0))[2] for p in owned),
            assignments=dict(assignments),completed_assignments_per_hour=max(0,assignments['completed']-self.baseline_completed)/max(elapsed,1)*3600,
            events=dict(self.counts),repeated_request_attempts=sum(max(0,n-1) for n in self.requests.values()),
            http_failure_statuses=dict(self.status_codes),operation_failure_types=dict(self.failure_types),cgroup=cgroup)
        with self.output.open('a') as f:f.write(json.dumps(result,sort_keys=True)+'\n')
        return result
