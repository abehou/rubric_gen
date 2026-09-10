"""Synthetic two-node shared admission check: no credentials, datasets or API calls."""
from concurrent.futures import ThreadPoolExecutor
import fcntl
import json
import os
from pathlib import Path
import socket
import time
from rubric_gen.runtime import capacity

root=Path(__file__).resolve().parents[2]/'runs/babel-overnight-20260907'/('cross-node-'+os.environ['SLURM_JOB_ID'])
root.mkdir(parents=True,exist_ok=True)
rank=int(os.environ['SLURM_PROCID'])
capacity.policy=lambda:dict(version=1,aggregate_concurrency=60,audit_studies=1,coordination_dir=str(root/'slots'))

def counter(delta):
    # Lock the data inode itself: a separate lock file does not invalidate the
    # NFS client's cached counter data on another host.
    with (root/'counter.json').open('a+') as stream:
        capacity._exclusive(stream.fileno())
        stream.seek(0);raw=stream.read()
        state=json.loads(raw) if raw else dict(active=0,peak=0,completed=0,hosts=[])
        state['active']+=delta
        state['peak']=max(state['peak'],state['active'])
        if delta<0:state['completed']+=1
        state['hosts']=sorted(set(state['hosts'])|{socket.gethostname()})
        assert 0<=state['active']<=60, state
        if delta:
            stream.seek(0);stream.truncate();stream.write(json.dumps(state))
            stream.flush();os.fsync(stream.fileno())
        return state


def fake(index):
    @capacity.limited(('solver','audit-request','recovery')[index%3])
    def body():
        counter(1)
        try:
            deadline=time.monotonic()+120
            while counter(0)['peak']<60:
                if time.monotonic()>deadline:raise RuntimeError('did not saturate shared60')
                time.sleep(.1)
            time.sleep(.2)
        finally:counter(-1)
    body()

started=time.monotonic()
with ThreadPoolExecutor(max_workers=40) as pool:list(pool.map(fake,range(40)))
result=dict(rank=rank,hostname=socket.gethostname(),provider_calls=0,completed=40,elapsed_seconds=time.monotonic()-started)
(root/f'rank-{rank}.json').write_text(json.dumps(result,indent=2)+'\n')
if rank==0:
    deadline=time.monotonic()+120
    while (state:=counter(0))['completed']<80:
        if time.monotonic()>deadline:raise RuntimeError('second node did not finish')
        time.sleep(.2)
    assert {k:state[k] for k in ('active','peak','completed')}==dict(active=0,peak=60,completed=80),state
    assert capacity.Slots(root/'slots/provider',60).active_count()==0
    assert len(state['hosts'])==2
    result.update(success=True,aggregate=state,nodes=state['hosts'])
    (root/'result.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result),flush=True)
