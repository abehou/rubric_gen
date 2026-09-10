"""Non-scientific Babel acceptance: saved inputs and 60-way shared admission.

No credentials are loaded and no workflow/provider command is invoked.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import multiprocessing as mp
from pathlib import Path
import tempfile
import time
from rubric_gen.runtime import capacity


def workers(root, active, peak, completed, release):
    capacity.policy=lambda:dict(version=1,aggregate_concurrency=60,audit_studies=1,coordination_dir=root)
    def operation(index):
        label=('solver','audit-request','recovery')[index%3]
        @capacity.limited(label)
        def fake():
            with active.get_lock():
                active.value+=1;peak.value=max(peak.value,active.value)
                if active.value==60:release.set()
            if not release.wait(90):raise RuntimeError('failed to saturate 60 slots')
            time.sleep(.05)
            with active.get_lock():active.value-=1;completed.value+=1
        fake()
    with ThreadPoolExecutor(max_workers=24) as pool:list(pool.map(operation,range(24)))


def main():
    from launch import configurations, validate_inputs, ROOT
    validate_inputs(configurations('full'))
    print('Fixed dev3 inputs validated; testing shared capacity.',flush=True)
    started=time.monotonic()
    ctx=mp.get_context('spawn')
    active,peak,completed=(ctx.Value('i',0) for _ in range(3));release=ctx.Event()
    # Use the actual shared filesystem, with an isolated test namespace.
    with tempfile.TemporaryDirectory(prefix='babel-capacity-check-',dir=ROOT/'runs') as directory:
        jobs=[ctx.Process(target=workers,args=(directory,active,peak,completed,release)) for _ in range(3)]
        try:
            for p in jobs:p.start()
            for p in jobs:
                p.join(120)
                if p.exitcode!=0:raise RuntimeError(f'capacity smoke process failed: exit={p.exitcode}, active={active.value}, peak={peak.value}, completed={completed.value}')
            assert peak.value==60 and active.value==0 and completed.value==72
            assert capacity.Slots(Path(directory)/'provider',60).active_count()==0
            result=dict(elapsed_seconds=round(time.monotonic()-started,3),active_after=0,inputs='valid',processes=3,submitted=72,peak_active=peak.value,completed=completed.value,provider_calls=0)
            print(json.dumps(result),flush=True)
        finally:
            for p in jobs:
                if p.is_alive():p.kill();p.join()


if __name__=='__main__':main()
