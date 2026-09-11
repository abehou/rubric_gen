"""Cross-process/node admission control on a shared flock-capable filesystem.

Slots are held by open file descriptions, not expiring timestamps or PID guesses.
Every deployment uses the checked-in policy; per-command worker limits cannot
create additional capacity. No payloads or exception messages enter telemetry.
"""
from __future__ import annotations

from contextlib import contextmanager
from functools import wraps
import fcntl
import hashlib
import json
import os
from pathlib import Path
import random
import socket
import threading
import time
import uuid

from rubric_gen.runtime.paths import PROJECT_ROOT

_LOCAL = threading.local()


def policy() -> dict:
    value = json.loads((PROJECT_ROOT / "config/runtime.json").read_text())
    if (set(value) != {"version", "aggregate_concurrency", "audit_studies", "coordination_dir"}
            or value["version"] != 1 or type(value["aggregate_concurrency"]) is not int
            or not 1 <= value["aggregate_concurrency"] <= 60
            or value["audit_studies"] != 1
            or not Path(value["coordination_dir"]).is_absolute()):
        raise RuntimeError("invalid shared runtime capacity policy")
    return value


def _exclusive(fd):
    # NFS blocking-lock wakeups can take tens of seconds. Nonblocking retries
    # retain identical kernel exclusion without that admission/telemetry delay.
    while True:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return
        except BlockingIOError:
            time.sleep(0.02 + random.random() * 0.03)


class Slots:
    def __init__(self, root: Path, capacity: int):
        if type(capacity) is not int or capacity < 1:
            raise ValueError("capacity must be positive")
        self.root = Path(root).absolute()
        self.capacity = capacity

    def _prepare(self):
        for path in (self.root, *self.root.parents):
            if path.is_symlink():
                raise RuntimeError("capacity paths must not contain symlinks")
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.root.stat().st_uid != os.getuid():
            raise RuntimeError("capacity directory belongs to another user")

    def _open(self, name):
        return os.open(self.root / name, os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)

    @contextmanager
    def lease(self, count=1):
        if type(count) is not int or not 1 <= count <= self.capacity:
            raise ValueError("reservation exceeds shared capacity")
        self._prepare()
        # Serialize only policy sealing, not the network-bound slot scan.
        coordinator = self._open("coordinator.lock")
        try:
            _exclusive(coordinator)
            seal = self.root / "capacity.json"
            expected = {"version": 1, "capacity": self.capacity}
            if seal.exists():
                if seal.is_symlink() or json.loads(seal.read_text()) != expected:
                    raise RuntimeError("shared capacity changed; refuse a split budget")
            else:
                fd = os.open(seal, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
                with os.fdopen(fd, "w") as out:
                    json.dump(expected, out); out.flush(); os.fsync(out.fileno())
        finally:
            os.close(coordinator)
        held = []
        try:
            while not held:
                offset = random.randrange(self.capacity)
                for index in range(self.capacity):
                    fd = self._open(f"slot-{(index + offset) % self.capacity:03d}.lock")
                    try:
                        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                    except BlockingIOError:
                        os.close(fd)
                        continue
                    except BaseException:
                        os.close(fd)
                        raise
                    held.append(fd)
                    if len(held) == count:
                        break
                if len(held) != count:
                    for fd in held:
                        os.close(fd)
                    held.clear()
                if not held:
                    time.sleep(0.5 + random.random())
            yield
        finally:
            for fd in held:
                os.close(fd)

    def active_count(self):
        # Sampling is approximate because leases can change during the scan.
        # Never hold the admission coordinator while doing observational I/O:
        # an NFS stall here must not serialize every new provider reservation.
        self._prepare()
        active = 0
        for index in range(self.capacity):
            fd = self._open(f"slot-{index:03d}.lock")
            try:
                try:
                    fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError:
                    active += 1
            finally:
                os.close(fd)
        return active


class _EventJournal:
    """One append descriptor per process; threads serialize without NFS locks."""

    def __init__(self):
        self.lock = threading.Lock()
        self.path = None
        self.fd = None

    def after_fork(self):
        # A child must neither inherit a held thread lock nor write its parent's
        # journal. Closing its descriptor does not close the parent's copy.
        if self.fd is not None:
            os.close(self.fd)
        self.lock = threading.Lock()
        self.path = None
        self.fd = None

    def append(self, path: Path, data: bytes):
        with self.lock:
            if path != self.path:
                path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND | os.O_NOFOLLOW, 0o600)
                if self.fd is not None:
                    os.close(self.fd)
                self.fd, self.path = fd, path
            remaining = memoryview(data)
            while remaining:
                written = os.write(self.fd, remaining)
                if written == 0:
                    raise OSError("runtime event journal write made no progress")
                remaining = remaining[written:]


_EVENT_JOURNAL = _EventJournal()
os.register_at_fork(after_in_child=_EVENT_JOURNAL.after_fork)


def emit(event: str, **fields):
    """Append operational facts only, never prompts, keys or exception messages."""
    root = Path(policy()["coordination_dir"])
    record = dict(event=event, time=time.time(), pid=os.getpid(), host=socket.gethostname(),
                  job_id=os.environ.get("SLURM_JOB_ID"), invocation_id=os.environ.get("RUBRIC_GEN_INVOCATION_ID"), **fields)
    path = root / f"events-{socket.gethostname()}-{os.getpid()}.jsonl"
    # Host/PID filenames have a single process owner. Retaining its descriptor
    # avoids an NFS OPEN/CLOSE and distributed lock cycle for every event.
    # Writes remain synchronous: this does not hide failed or unsaved telemetry.
    _EVENT_JOURNAL.append(path, (json.dumps(record, sort_keys=True) + "\n").encode())


@contextmanager
def reservation(kind="provider", count=1):
    # Nested calls in the same synchronous operation consume the outer lease.
    depths = getattr(_LOCAL, "depths", {})
    key = (os.getpid(), kind)
    if depths.get(key):
        yield
        return
    settings = policy()
    capacity = settings["aggregate_concurrency"] if kind == "provider" else settings["audit_studies"]
    root = Path(settings["coordination_dir"]) / kind
    started = time.monotonic()
    lease_id = uuid.uuid4().hex
    emit('waiting', kind=kind, slots=count, lease_id=lease_id)
    with Slots(root, capacity).lease(count):
        depths[key] = 1; _LOCAL.depths = depths
        try:
            emit("acquired", kind=kind, slots=count, lease_id=lease_id,
                 wait_seconds=time.monotonic() - started)
            yield
        finally:
            try:
                emit("released", kind=kind, slots=count, lease_id=lease_id)
            finally:
                depths.pop(key, None)


class SharedTokenWindow:
    """Cross-node rolling-window admission; reservations are never refunded."""
    def __init__(self, root, budget=8_000_000, window=60.0):
        self.root = Path(root)
        self.budget = budget
        self.window = window

    def _update(self, tokens=0, cooldown=0.0):
        if type(tokens) is not int or not 0 <= tokens <= self.budget:
            raise ValueError("request exceeds shared provider token budget")
        with Slots(self.root / "lock", 1).lease():
            now = time.time()
            path = self.root / "window.json"
            if path.is_symlink():
                raise RuntimeError("token window cannot be a symlink")
            state = json.loads(path.read_text()) if path.exists() else {
                "budget": self.budget, "window": self.window,
                "cooldown_until": now + self.window, "entries": []}
            if state['budget'] != self.budget or state['window'] != self.window:
                raise RuntimeError("shared provider token policy changed")
            entries = [(t, n) for t, n in state['entries'] if t > now - self.window]
            state['cooldown_until'] = max(state['cooldown_until'], now + cooldown)
            wait = max(0.0, state['cooldown_until'] - now)
            used = sum(n for _, n in entries)
            if tokens and used + tokens > self.budget:
                remaining = used
                for timestamp, amount in sorted(entries):
                    remaining -= amount
                    if remaining + tokens <= self.budget:
                        wait = max(wait, timestamp + self.window - now + 0.01)
                        break
            if tokens and wait <= 0:
                entries.append((now, tokens))
            state['entries'] = entries
            temporary = self.root / f"window-{uuid.uuid4().hex}.tmp"
            with temporary.open('x') as stream:
                json.dump(state, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, path)
            return wait

    def acquire_delay(self, tokens):
        return self._update(tokens=tokens)

    def cool_down(self, seconds):
        self._update(cooldown=max(self.window, seconds))


_TOKEN_COUNTS = {}
_TOKEN_COUNTS_LOCK = threading.Lock()


def _reset_token_counts_after_fork():
    global _TOKEN_COUNTS, _TOKEN_COUNTS_LOCK
    _TOKEN_COUNTS = {}
    _TOKEN_COUNTS_LOCK = threading.Lock()


os.register_at_fork(after_in_child=_reset_token_counts_after_fork)


def _anthropic_admission(operation, args, kwargs):
    if operation != 'hosted-generation':
        return None, None
    model = args[0] if args else kwargs.get('model')
    request = args[1] if len(args) > 1 else kwargs.get('request_value')
    if not isinstance(model, str) or not model.startswith('claude-'):
        return None, None
    from rubric_gen.runtime.llm import count_input_tokens
    key = hashlib.sha256(repr((model, request)).encode()).hexdigest()
    with _TOKEN_COUNTS_LOCK:
        tokens = _TOKEN_COUNTS.get(key)
    if tokens is None:
        with reservation():
            tokens = count_input_tokens(model, request)
        with _TOKEN_COUNTS_LOCK:
            _TOKEN_COUNTS[key] = tokens
    root = Path(policy()['coordination_dir']) / 'anthropic-input-tokens'
    return SharedTokenWindow(root), tokens


def limited(operation, *, kind="provider", slots=None, returns_exit_code=False):
    def decorate(function):
        @wraps(function)
        def wrapped(*args, **kwargs):
            count = slots(*args, **kwargs) if slots else 1
            token_window, tokens = _anthropic_admission(operation, args, kwargs)
            while True:
                with reservation(kind, count):
                    delay = token_window.acquire_delay(tokens) if token_window else 0
                    if delay <= 0:
                        started = time.monotonic()
                        request_key = hashlib.sha256(repr((operation, args, kwargs)).encode()).hexdigest()
                        emit("operation_started", operation=operation, request_key=request_key)
                        try:
                            result = function(*args, **kwargs)
                        except BaseException as exc:
                            if token_window and getattr(exc, 'status_code', None) == 429:
                                headers = getattr(getattr(exc, 'response', None), 'headers', {})
                                try:
                                    retry_after = float(headers.get('retry-after', 60))
                                except (TypeError, ValueError):
                                    retry_after = 60
                                token_window.cool_down(retry_after)
                            emit("operation_failed", operation=operation, request_key=request_key,
                                 error_type=type(exc).__name__, status_code=getattr(exc, "status_code", None),
                                 elapsed_seconds=time.monotonic() - started)
                            raise
                        failed = (returns_exit_code and type(result) is int and result != 0) or getattr(result, "exit_code", 0) != 0
                        emit("operation_returned_failure" if failed else "operation_completed", operation=operation, request_key=request_key,
                             elapsed_seconds=time.monotonic() - started)
                        return result
                # Do not occupy any global provider slots during rate waits.
                emit("token_wait", operation=operation, wait_seconds=min(delay, 5.0))
                time.sleep(min(delay, 5.0))
        return wrapped
    return decorate
