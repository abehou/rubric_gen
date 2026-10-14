"""Private A-only runner. Invoke only after the user approves the disclosed cost."""
from rubric_gen.runtime.process_environment import install_controlled_process_environment
install_controlled_process_environment()
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
import argparse
import ctypes
import fcntl
import importlib.util
import json
import os
import signal
import sqlite3
import subprocess
import threading
import time
from dotenv import dotenv_values
from rubric_gen.artifacts.serialization import write_json_atomic as write
from rubric_gen.runtime.llm import StructuredRequest, anthropic_schema
from rubric_gen.submission_revision.evaluation.absolute_score import validate_verdict
from prepare import HERE, ROOT, read

def now():
    return datetime.now(timezone.utc).isoformat()

def cost(provider, u):
    if provider == 'openai':
        inp, output = u['input_tokens'], u['output_tokens']
        d = u.get('input_tokens_details') or {}
        cached, created = d.get('cached_tokens', 0), d.get('cache_write_tokens', 0)
        return ((inp - cached - created) * 2 + cached * .20 + created * 2.50 + output * 10) / 1e6
    inp, cached, created = u['input_tokens'], u.get('cache_read_input_tokens', 0), u.get('cache_creation_input_tokens', 0)
    return (inp * .1 + cached * .01 + created * .125 + u['output_tokens'] * .5) / 1e6

def arguments(provider, request, model):
    if provider == 'openai':
        return dict(model=model, input=request.openai_input(model),
                    max_output_tokens=request.max_output_tokens, reasoning={'effort': 'high'},
                    text=request.text_config(), truncation='disabled', store=False, service_tier='default')
    return dict(model=model, max_tokens=request.max_output_tokens,
                messages=request.anthropic_messages(), system=request.anthropic_system(),
                thinking={'type': 'adaptive'}, output_config={'effort': 'high',
                    'format': {'type': 'json_schema', 'schema': anthropic_schema(request.schema)}})

def upper_bound(provider, args):
    size = len(json.dumps(args, ensure_ascii=True).encode()) + 8192
    if size > 100_000:
        raise ValueError('Prepared pilot should stay within short-context pricing')
    limit = args.get('max_output_tokens', args.get('max_tokens'))
    return (size * (2.5 if provider == 'openai' else .125)
            + limit * (10 if provider == 'openai' else .5)) / 1e6

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--provider', choices=['openai', 'anthropic'], required=True)
    opt = parser.parse_args()
    scope = read(HERE / 'scope.json'); provider = opt.provider
    out = ROOT / scope['output']; folder = out / provider
    if not (out / 'verification.json').exists():
        raise RuntimeError('Run prepare.py before any paid execution')
    folder.mkdir(parents=True, exist_ok=True)
    with (folder / '.owner.lock').open('a') as owner:
        fcntl.flock(owner, fcntl.LOCK_EX | fcntl.LOCK_NB)
        execute(scope, provider, out, folder)

def execute(scope, provider, out, folder):
    role = scope['providers'][provider]; model = role['model']; cap = role['proposed_cap_usd']
    values = dotenv_values(ROOT / '.env.local')
    key = values.get('OPENAI_API_KEY' if provider == 'openai' else 'ANTHROPIC_API_KEY')
    if not key or not key.endswith('iioA' if provider == 'openai' else 'jAAA'):
        raise RuntimeError('Previously authorized credential unavailable')
    db = sqlite3.connect(folder / 'account.sqlite3', check_same_thread=False)
    db.execute('CREATE TABLE IF NOT EXISTS calls (id INTEGER PRIMARY KEY, artifact TEXT, state TEXT, reserved REAL, actual REAL, started TEXT, finished TEXT)')
    db.commit()
    lock = threading.RLock(); stop = threading.Event(); allowed = threading.Event(); allowed.set()
    local = threading.local(); start = time.monotonic()
    def totals():
        with lock:
            known, uncertain, pending = db.execute("SELECT COALESCE(SUM(actual),0), COALESCE(SUM(CASE WHEN state='unknown' THEN reserved ELSE 0 END),0), COALESCE(SUM(CASE WHEN state='inflight' THEN reserved ELSE 0 END),0) FROM calls").fetchone()
        return dict(known_usd=known, unknown_usd=uncertain, pending_usd=pending, cap_usd=cap)
    # This provider's owner lock proves old process calls are no longer live.
    # A saved response resolves known usage; otherwise keep the full reservation.
    for number, artifact in db.execute("SELECT id,artifact FROM calls WHERE state='inflight'").fetchall():
        path = folder / artifact / f'response-{number}.json'
        if path.exists():
            charged = cost(provider, read(path)['response']['usage'])
            db.execute("UPDATE calls SET state='confirmed',actual=?,finished=? WHERE id=?", (charged, now(), number))
        else:
            db.execute("UPDATE calls SET state='unknown',finished=? WHERE id=?", (now(), number))
    db.commit()
    credit = None; receipt = folder / 'credit-reservation.json'
    if provider == 'openai':
        spec = importlib.util.spec_from_file_location('shared_credit', ROOT / 'experiments/openai-credit/budget.py')
        credit = importlib.util.module_from_spec(spec); spec.loader.exec_module(credit)
        if receipt.exists() and not read(receipt)['settled']:
            old = read(receipt); t = totals()
            credit.settle_run(old['id'], t['known_usd'] - old['starting_known'],
                              t['unknown_usd'] - old['starting_unknown'], evidence=str(folder / 'account.sqlite3'))
            write(receipt, {**old, 'settled': True})
    before = totals()
    allocation = cap - before['known_usd'] - before['unknown_usd']
    if allocation <= 0:
        raise RuntimeError('Cumulative provider cap exhausted')
    if credit:
        runid = scope['experiment_id'] + '-openai-' + str(time.time_ns())
        credit.reserve_run(runid, allocation, evidence=str(folder / 'account.sqlite3'))
        write(receipt, dict(id=runid, settled=False, starting_known=before['known_usd'], starting_unknown=before['unknown_usd']))
    def monitor():
        previous = None
        while not stop.is_set():
            try:
                free = int(subprocess.check_output(['/usr/bin/memory_pressure'], text=True).split('System-wide memory free percentage: ')[1].split('%')[0])
                pressure = int(subprocess.check_output(['/usr/sbin/sysctl', '-n', 'kern.memorystatus_vm_pressure_level'], text=True))
                libc = ctypes.CDLL('/usr/lib/libSystem.B.dylib'); libc.mach_host_self.restype = ctypes.c_uint
                ticks = (ctypes.c_uint * 4)(); count = ctypes.c_uint(4); cpu = None
                if libc.host_statistics(libc.mach_host_self(), 3, ticks, ctypes.byref(count)) == 0:
                    current = list(ticks)
                    if previous:
                        delta = [(x - y) % 2**32 for x, y in zip(current, previous)]
                        if sum(delta): cpu = 100 * (1 - delta[2] / sum(delta))
                    previous = current
                if free < 10 or pressure >= 4: allowed.clear()
                else: allowed.set()
                with (folder / 'resources.jsonl').open('a') as f:
                    f.write(json.dumps(dict(timestamp=now(), free_percent=free, memory_pressure=pressure,
                        cpu_busy_percent=cpu, load=os.getloadavg(), process_rss_kib=int(subprocess.check_output(['/bin/ps', '-o', 'rss=', '-p', str(os.getpid())], text=True)), dispatch_allowed=allowed.is_set(), budget=totals())) + '\n')
            except Exception as e:
                with (folder / 'resource-errors.jsonl').open('a') as f: f.write(json.dumps({'time': now(), 'error': str(e)}) + '\n')
            stop.wait(15)
    def worker(b):
        artifact = b['key']; destination = folder / artifact; result = destination / 'result.json'
        if result.exists():
            validate_verdict(read(result)['verdict']); return 'reused'
        request = StructuredRequest(**read(out / 'inputs' / (artifact + '.json'))['request'])
        args = arguments(provider, request, model); reservation = upper_bound(provider, args)
        destination.mkdir(parents=True, exist_ok=True)
        for attempt in range(scope['max_attempts']):
            while not allowed.wait(2):
                if stop.is_set(): return 'interrupted'
            if stop.is_set(): return 'interrupted'
            with lock:
                t = totals()
                if t['known_usd'] + t['unknown_usd'] + t['pending_usd'] + reservation > cap:
                    stop.set(); return 'budget_stopped'
                number = db.execute("INSERT INTO calls(artifact,state,reserved,actual,started) VALUES(?,'inflight',?,0,?)", (artifact, reservation, now())).lastrowid
                db.commit()
            began = time.monotonic(); got_response = False
            try:
                if not hasattr(local, 'client'):
                    if provider == 'openai':
                        from openai import OpenAI
                        local.client = OpenAI(api_key=key, max_retries=0, timeout=scope['timeout_seconds'])
                    else:
                        from anthropic import Anthropic
                        local.client = Anthropic(api_key=key, max_retries=0, timeout=scope['timeout_seconds'])
                response = local.client.responses.create(**args) if provider == 'openai' else local.client.messages.create(**args)
                obj = response.model_dump(mode='json'); got_response = True
                write(destination / f'response-{number}.json', dict(request_parameters=args, response=obj, elapsed_seconds=time.monotonic()-began))
                charged = cost(provider, obj['usage'])
                with lock:
                    db.execute("UPDATE calls SET state='confirmed',actual=?,finished=? WHERE id=?", (charged, now(), number)); db.commit()
                if charged > reservation:
                    stop.set(); raise RuntimeError('Observed billing exceeded per-call bound')
                if obj['model'] != model:
                    stop.set(); raise RuntimeError('Provider model differs from declared auditor')
                text = response.output_text if provider == 'openai' else '\n'.join(block.text for block in response.content if getattr(block, 'type', None) == 'text')
                verdict = json.loads(text); validate_verdict(verdict)
                write(result, dict(verdict=verdict, actual_model=obj['model'], effort='high', response_path=str(destination / f'response-{number}.json')))
                return 'completed'
            except Exception as e:
                with lock:
                    state = db.execute('SELECT state FROM calls WHERE id=?', (number,)).fetchone()[0]
                    if state == 'inflight':
                        rejected = not got_response and getattr(e, 'status_code', None) in (400, 401, 403, 404, 422, 429)
                        db.execute('UPDATE calls SET state=?,finished=? WHERE id=?', ('rejected' if rejected else 'unknown', now(), number)); db.commit()
                write(destination / f'error-{number}.json', dict(type=type(e).__name__, message=str(e), attempt=attempt+1))
                if getattr(e, 'status_code', None) in (400, 401, 403, 404, 422):
                    stop.set(); return 'failed'
                if attempt + 1 < scope['max_attempts']: stop.wait(2)
        return 'failed'
    for sig in (signal.SIGINT, signal.SIGTERM): signal.signal(sig, lambda *_: stop.set())
    monitor_thread = threading.Thread(target=monitor, daemon=True); monitor_thread.start()
    completed = []
    write(folder / 'launch.json', dict(started_at=now(), pid=os.getpid(), provider=provider, model=model, effort='high', workers=role['workers'], cap_usd=cap, source_scope=scope))
    try:
        with ThreadPoolExecutor(max_workers=role['workers']) as pool:
            futures = [pool.submit(worker, b) for b in read(out / 'baselines.json')]
            for f in as_completed(futures):
                completed.append(f.result())
                write(folder / 'status.json', dict(timestamp=now(), finished=len(completed), planned=len(futures), outcomes=completed, budget=totals(), elapsed_seconds=time.monotonic()-start))
    finally:
        # ThreadPoolExecutor waits for every in-flight call before credit settlement.
        stop.set(); monitor_thread.join(timeout=20)
        with lock:
            db.execute("UPDATE calls SET state='unknown',finished=? WHERE state='inflight'", (now(),)); db.commit()
        after = totals()
        if credit:
            credit.settle_run(runid, after['known_usd']-before['known_usd'], after['unknown_usd']-before['unknown_usd'], evidence=str(folder/'account.sqlite3'))
            write(receipt, {**read(receipt), 'settled': True})
        write(folder / 'completion.json', dict(finished_at=now(), outcomes=completed, budget=after, elapsed_seconds=time.monotonic()-start))
        db.close()

if __name__ == '__main__':
    main()
