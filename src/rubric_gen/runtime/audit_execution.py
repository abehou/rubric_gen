"""One study owner and one bounded request executor for independent audit stages."""
from __future__ import annotations

from collections import deque
from concurrent.futures import Future, ThreadPoolExecutor
from contextlib import contextmanager
import fcntl
import os
from pathlib import Path
import threading

from rubric_gen.runtime.capacity import reservation
from rubric_gen.runtime.failures import failure_category


def provider_for(model: str) -> str:
    if model.startswith(('claude', 'anthropic')):
        return 'anthropic'
    if model.startswith(('gemini', 'google')):
        return 'google'
    return 'openai'


@contextmanager
def audit_output_owner(root: Path):
    """Persistent exclusion also covers read-only preparation and publication."""
    root.mkdir(parents=True, exist_ok=True)
    fd = os.open(root / '.audit.lock', os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600)
    try:
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise RuntimeError(f'an audit already owns this output: {root}') from exc
        yield
    finally:
        os.close(fd)


@contextmanager
def audit_owner(root: Path):
    """Standalone audit ownership includes normal global admission."""
    with audit_output_owner(root), reservation('audit'):
        yield


class AuditExecutor:
    """Fair, bounded submission to a single pool; stage coordinators never lease.

    Leave one request worker available to each other configured provider. This
    also applies while it is preparing its next request, so a stuck provider
    cannot fill the pool before another provider's work arrives.
    """
    def __init__(self, workers: int, models: tuple[str, ...]):
        self.workers = workers
        self.providers = tuple(dict.fromkeys(provider_for(m) for m in models))
        self.pool = ThreadPoolExecutor(max_workers=workers)
        self.queues = {}
        self.active = {p: 0 for p in self.providers}
        self.lock = threading.RLock()
        self.drained = threading.Condition(self.lock)
        self.closed = False
        self.blocked = {}
        self.cursor = 0

    def submit(self, function, *args, model: str | None = None):
        if model is None:
            model = args[0].model
        provider = provider_for(model)
        result = Future()
        with self.lock:
            if self.closed:
                raise RuntimeError('audit executor is closed')
            if provider in self.blocked:
                result.set_exception(RuntimeError(f"{provider} dispatch stopped: {self.blocked[provider]}"))
                return result
            owner = getattr(function, '__self__', None)
            config = getattr(owner, 'config', None)
            group = (provider, getattr(function, '__qualname__', str(function)),
                     str(getattr(config, 'output_dir', '')))
            self.queues.setdefault(group, deque()).append((result, function, args))
            self.active.setdefault(provider, 0)
            self._refill()
        return result

    def _refill(self):
        names = tuple(self.queues)
        ceiling = max(1, self.workers - len(self.providers) + 1)
        while sum(self.active.values()) < self.workers:
            ready = [names[(self.cursor+i) % len(names)] for i in range(len(names))
                     if self.queues[names[(self.cursor+i) % len(names)]]
                     and self.active[names[(self.cursor+i) % len(names)][0]] < ceiling]
            if not ready:
                break
            group = ready[0]
            provider = group[0]
            self.cursor = (names.index(group) + 1) % len(names)
            result, function, args = self.queues[group].popleft()
            self.active[provider] += 1
            running = self.pool.submit(function, *args)
            running.add_done_callback(lambda done, p=provider, r=result: self._completed(p, r, done))

    def _completed(self, provider, result, done):
        category = None
        try:
            value = done.result()
            if isinstance(value, dict):
                category = value.get('failure_category')
            result.set_result(value)
        except BaseException as exc:
            category = failure_category(exc)
            result.set_exception(exc)
        finally:
            with self.lock:
                self.active[provider] -= 1
                if category in {'authentication', 'billing', 'configuration'}:
                    self.blocked[provider] = category
                    for group, queue in self.queues.items():
                        if group[0] == provider:
                            while queue:
                                waiting, _, _ = queue.popleft()
                                waiting.set_exception(RuntimeError(f"{provider} dispatch stopped: {category}"))
                self._refill()
                self.drained.notify_all()

    def __enter__(self):
        return self

    def status(self):
        with self.lock:
            return {'request_worker_limit': self.workers,
                    'active_by_provider': dict(self.active),
                    'ready_by_provider': {p: sum(len(q) for g,q in self.queues.items() if g[0] == p)
                                          for p in self.active},
                    'stopped_providers': dict(self.blocked)}

    def __exit__(self, *error):
        # A failed coordinator can leave already accepted work in our queues.
        # Drain those queues while completion callbacks can still refill them.
        with self.drained:
            self.closed = True
            while any(self.active.values()) or any(self.queues.values()):
                self.drained.wait()
        self.pool.shutdown(wait=True)
