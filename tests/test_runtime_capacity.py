import multiprocessing as mp
from pathlib import Path
import time
import pytest
from rubric_gen.runtime.capacity import Slots, limited
from rubric_gen.runtime import capacity


def occupy(root, cap, active, peak, ready=None):
    with Slots(Path(root), cap).lease():
        with active.get_lock():
            active.value += 1
            peak.value = max(peak.value, active.value)
        if ready:
            ready.set()
            time.sleep(60)
        else:
            time.sleep(.05)
        with active.get_lock():
            active.value -= 1


@pytest.mark.parametrize("cap",[1,3])
def test_cross_process_pool_never_multiplies_budget(tmp_path,cap):
    ctx = mp.get_context('spawn')
    active, peak = ctx.Value('i', 0), ctx.Value('i', 0)
    jobs = [ctx.Process(target=occupy, args=(str(tmp_path), cap, active, peak)) for _ in range(12)]
    for p in jobs:p.start()
    for p in jobs:
        p.join(20);assert p.exitcode == 0
    assert 1 <= peak.value <= cap
    assert active.value == 0


def test_crashed_owner_releases_kernel_lease(tmp_path):
    ctx = mp.get_context('spawn');ready=ctx.Event()
    active,peak=ctx.Value('i',0),ctx.Value('i',0)
    p=ctx.Process(target=occupy,args=(str(tmp_path),1,active,peak,ready))
    p.start();assert ready.wait(15)
    p.kill();p.join(10)
    with Slots(tmp_path,1).lease():pass


def test_changed_capacity_and_symlinks_reject(tmp_path):
    with Slots(tmp_path / 'pool', 3).lease():pass
    with pytest.raises(RuntimeError,match='split budget'):
        with Slots(tmp_path / 'pool',4).lease():pass
    (tmp_path/'link').symlink_to(tmp_path/'pool',target_is_directory=True)
    with pytest.raises(RuntimeError,match='symlinks'):
        with Slots(tmp_path/'link',3).lease():pass
    with pytest.raises(ValueError):
        with Slots(tmp_path/'pool',3).lease(4):pass


def test_nested_audit_and_provider_do_not_deadlock(tmp_path,monkeypatch):
    monkeypatch.setattr(capacity,'policy',lambda:dict(version=1,aggregate_concurrency=1,audit_studies=1,coordination_dir=str(tmp_path)))
    @limited('request')
    def inner():return 7
    @limited('audit',kind='audit')
    def audit():
        @limited('nested-audit',kind='audit')
        def nested():return inner()
        return nested()
    assert audit()==7
    @limited('outer-request')
    def nested_request():return inner()
    assert nested_request()==7


def test_exception_releases_and_telemetry_has_no_payload(tmp_path,monkeypatch):
    monkeypatch.setattr(capacity,'policy',lambda:dict(version=1,aggregate_concurrency=1,audit_studies=1,coordination_dir=str(tmp_path)))
    @limited('request')
    def fail(payload):raise ValueError(payload)
    with pytest.raises(ValueError):fail('TOP_SECRET_PAYLOAD')
    with capacity.reservation():pass
    logs=''.join(p.read_text() for p in tmp_path.glob('events-*'))
    assert 'TOP_SECRET_PAYLOAD' not in logs
    assert 'operation_failed' in logs


def test_numeric_token_counts_are_not_failed_exit_codes(tmp_path):
    import json
    @limited('token-count')
    def count():return 123
    @limited('stage',returns_exit_code=True)
    def stage():return 1
    assert count()==123 and stage()==1
    root=Path(capacity.policy()['coordination_dir'])
    events=[json.loads(line) for p in root.glob('events-*') for line in p.read_text().splitlines()]
    assert any(e['event']=='operation_completed' and e.get('operation')=='token-count' for e in events)
    assert any(e['event']=='operation_returned_failure' and e.get('operation')=='stage' for e in events)


def test_child_worker_pool_reserves_its_whole_budget(tmp_path,monkeypatch):
    from rubric_gen.benchmarks.harvey_lab.evaluator import HarveyEvaluator
    evaluator=object.__new__(HarveyEvaluator)
    evaluator.max_retries=0
    monkeypatch.setattr(evaluator,'_archive_log',lambda _:None)
    observed=[]
    def fake_execute(*args):
        observed.append(Slots(Path(capacity.policy()['coordination_dir'])/'provider',60).active_count())
    monkeypatch.setattr(evaluator,'_execute',fake_execute)
    evaluator._execute_with_retries(['fake-judge','--parallel','3'],tmp_path,tmp_path/'log',(),
        'judge',operation='fake',transient_errors=())
    assert observed==[3]
    assert Slots(Path(capacity.policy()['coordination_dir'])/'provider',60).active_count()==0


def test_stalled_monitor_does_not_hold_admission_coordinator(tmp_path, monkeypatch):
    import threading
    pool = Slots(tmp_path, 1)
    with pool.lease():
        pass
    monitoring = Slots(tmp_path, 1)
    original_open = monitoring._open
    sampling = threading.Event()
    release_sample = threading.Event()
    admitted = threading.Event()

    def delayed_open(name):
        if name.startswith("slot-"):
            sampling.set()
            assert release_sample.wait(10)
        return original_open(name)

    monkeypatch.setattr(monitoring, "_open", delayed_open)
    def reserve():
        with pool.lease():
            admitted.set()

    monitor = threading.Thread(target=monitoring.active_count)
    worker = threading.Thread(target=reserve)
    monitor.start()
    try:
        assert sampling.wait(3)
        worker.start()
        assert admitted.wait(3), "observational I/O blocked provider admission"
    finally:
        release_sample.set()
        monitor.join(5)
        if worker.ident is not None:
            worker.join(5)
    assert not monitor.is_alive() and not worker.is_alive()


def test_threaded_events_reuse_one_descriptor_without_distributed_locks(tmp_path, monkeypatch):
    import json
    import os
    from concurrent.futures import ThreadPoolExecutor

    opened = []
    original_open = os.open

    def tracked_open(path, flags, mode=0o777):
        if Path(path).name.startswith('events-'):
            opened.append(str(path))
        return original_open(path, flags, mode)

    def unexpected_lock(fd):
        raise AssertionError('process-owned telemetry must not acquire an NFS lock')

    monkeypatch.setattr(os, 'open', tracked_open)
    monkeypatch.setattr(capacity, '_exclusive', unexpected_lock)
    def emit_many(worker):
        for sequence in range(10):
            capacity.emit('test', worker=worker, sequence=sequence)
    with ThreadPoolExecutor(max_workers=60) as pool:
        list(pool.map(emit_many, range(60)))
    assert len(opened) == 1
    path = Path(opened[0])
    assert path.stat().st_mode & 0o777 == 0o600
    rows = [json.loads(line) for line in path.read_text().splitlines()]
    assert len(rows) == 600
    assert {(r['worker'], r['sequence']) for r in rows} == {
        (w, s) for w in range(60) for s in range(10)
    }
    for worker in range(60):
        assert [r['sequence'] for r in rows if r['worker'] == worker] == list(range(10))


def test_event_journal_retries_partial_writes(tmp_path, monkeypatch):
    import json
    import os
    original_write = os.write
    monkeypatch.setattr(os, 'write', lambda fd, data: original_write(fd, data[:7]))
    capacity.emit('partial-write', number=42)
    root = Path(capacity.policy()['coordination_dir'])
    rows = [json.loads(line) for p in root.glob('events-*') for line in p.read_text().splitlines()]
    assert len(rows) == 1 and rows[0]['number'] == 42


def test_forked_event_writer_does_not_inherit_parent_lock_or_journal(tmp_path):
    import json
    import os
    capacity.emit('parent-before-fork')
    ctx = mp.get_context('fork')
    child = ctx.Process(target=capacity.emit, args=('child-event',))
    with capacity._EVENT_JOURNAL.lock:
        child.start()
        child.join(10)
        if child.is_alive():
            child.kill()
            child.join(5)
            pytest.fail('child inherited the parent journal lock')
    assert child.exitcode == 0
    capacity.emit('parent-after-fork')
    root = Path(capacity.policy()['coordination_dir'])
    journals = {p.name: [json.loads(line) for line in p.read_text().splitlines()]
                for p in root.glob('events-*')}
    assert len(journals) == 2
    assert sorted(len(rows) for rows in journals.values()) == [1, 2]
    for name, rows in journals.items():
        assert all(f"-{r['pid']}.jsonl" in name for r in rows)
    assert sum(r['pid'] == os.getpid() for rows in journals.values() for r in rows) == 2
