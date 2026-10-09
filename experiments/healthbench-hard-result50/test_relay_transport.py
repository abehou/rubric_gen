"""Offline regression for the failed run's relay transport classification."""
from io import BytesIO
import importlib.util
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import httpx


ROOT = Path(__file__).resolve().parents[2]
spec = importlib.util.spec_from_file_location(
    'result50_relay_test',
    ROOT / 'runs/healthbench-hard-result50-extension-20261006/budget_proxy.py',
)
relay = importlib.util.module_from_spec(spec)
spec.loader.exec_module(relay)


class FakeServer:
    def __init__(self, address, handler):
        self.handler = handler

    def serve_forever(self):
        pass


class FakeLedger:
    def __init__(self, failure=None):
        self.failure = failure
        self.finished = []

    def reserve(self, bound):
        if self.failure is not None:
            raise self.failure
        return 'reserved'

    def finish(self, key, cost):
        self.finished.append((key, cost))


class RelayTransportTest(unittest.TestCase):
    def invoke(self, failure, ledger=None, path='/v1/responses'):
        ledger = ledger or FakeLedger()
        with patch.object(relay, 'ThreadingHTTPServer', FakeServer), \
                patch.object(relay.httpx, 'Client') as client:
            client.return_value.stream.side_effect = failure
            server = relay.start_proxy('fake-provider-key', ledger, 'fake-worker-key')
            handler = object.__new__(server.handler)
            payload = json.dumps({'model': 'gpt-5.6-luna', 'input': 'test'}).encode()
            handler.headers = {'Authorization': 'Bearer fake-worker-key',
                               'Content-Length': str(len(payload))}
            handler.path = path
            handler.rfile = BytesIO(payload)
            errors = []
            handler.error = lambda status, message: errors.append((status, message))
            handler.do_POST()
            return errors, ledger.finished, client.return_value.stream.call_count

    def test_transport_is_retryable_and_keeps_unknown_usage(self):
        for failure in (httpx.ReadError('network'), httpx.ConnectError('network'),
                        httpx.ReadTimeout('network')):
            with self.subTest(failure=type(failure).__name__):
                errors, finished, calls = self.invoke(failure)
                self.assertEqual(errors[0][0], 502)
                self.assertEqual(finished, [('reserved', None)])
                self.assertEqual(calls, 1)

    def test_budget_denial_stays_permanent_without_dispatch(self):
        errors, finished, calls = self.invoke(
            None, ledger=FakeLedger(RuntimeError('Approved budget cannot fund request')))
        self.assertEqual(errors[0][0], 403)
        self.assertEqual(finished, [])
        self.assertEqual(calls, 0)

    def test_unapproved_endpoint_stays_blocked(self):
        errors, finished, calls = self.invoke(None, path='/v1/unapproved')
        self.assertEqual(errors[0][0], 403)
        self.assertEqual(finished, [])
        self.assertEqual(calls, 0)


if __name__ == '__main__':
    unittest.main()
