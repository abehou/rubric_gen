"""Private loopback-only OpenAI relay with a durable, fail-closed USD ledger.

Workers receive a dummy key; only this process owns the real key. Every billable
request reserves a conservative upper bound, including invisible output tokens.
Unknown/failed usage keeps the reservation as spent. No provider retries here.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import httpx

PRICES = {
    "gpt-5.6-luna": (.20, .02, .25, 1.20),
    "gpt-6-luna": (.10, .01, .125, .50),
    "gpt-6-sol": (2., .20, 2.50, 10.),
}


def upper_bound(payload: dict) -> float:
    model = payload["model"]
    prices = PRICES[model]  # Unapproved model fails before dispatch.
    if payload.get("service_tier") not in (None, "auto", "default"):
        raise ValueError("Only Standard processing is budgeted")
    payload['service_tier'] = 'default'
    if payload.get("previous_response_id") or payload.get("conversation"):
        raise ValueError("Server-side hidden history is not supported by this relay")
    if payload.get("background"):
        raise ValueError("Background generation would escape usage accounting")
    # Hosted billable tools are outside this answer-only experiment.
    if any(t.get("type") not in ("function", "custom") for t in payload.get("tools", [])):
        raise ValueError("Only client-side function/custom tools are permitted")
    body = json.dumps(payload, ensure_ascii=True)
    if '"input_image"' in body or '"input_file"' in body or '"input_audio"' in body:
        raise ValueError("Only text inputs are budgeted")
    # Serialized ASCII bytes bound ordinary text tokens with ample framing margin.
    # Encrypted prior reasoning has unknown expanded size: reserve 2M input tokens.
    input_max = 2_000_000 if '"encrypted_content"' in body else len(body.encode()) + 8192
    output_max = payload.get("max_output_tokens", 128_000)
    if type(output_max) is not int or not 1 <= output_max <= 128_000:
        raise ValueError("Unsupported output token cap")
    payload["max_output_tokens"] = output_max
    long = input_max > 272_000
    return (input_max * prices[2] * (2 if long else 1)
            + output_max * prices[3] * (1.5 if long else 1)) / 1e6


def prepare_payload(path: str, payload: dict) -> float:
    bound = upper_bound(payload)
    if path == '/v1/responses/input_tokens':
        # These generation-only parameters are inserted by upper_bound, not
        # accepted by the count endpoint. Preserve the caller's evidence/schema.
        payload.pop('max_output_tokens', None)
        payload.pop('service_tier', None)
    return bound


def actual_cost(model: str, usage: dict) -> float:
    inp, out = usage["input_tokens"], usage["output_tokens"]
    details = usage.get("input_tokens_details") or {}
    cached = details.get("cached_tokens", 0)
    write = details.get("cache_write_tokens", 0)
    if any(type(n) is not int or n < 0 for n in (inp, out, cached, write)) or cached + write > inp:
        raise ValueError("Invalid usage")
    a, b, c, d = PRICES[model]
    return (((inp-cached-write)*a + cached*b + write*c) * (2 if inp > 272_000 else 1)
            + out*d*(1.5 if inp > 272_000 else 1)) / 1e6


class Ledger:
    def __init__(self, path: Path, limit: float = 30., *, allow_overrun: bool = False):
        self.path, self.limit = path, limit
        self.allow_overrun = allow_overrun
        self.condition = threading.Condition()
        self.state = json.loads(path.read_text()) if path.exists() else {
            "limit_usd": limit, "spent_usd": 0., "pending": {}, "completed": 0,
            "uncertain": 0, "stopped": False,
        }
        if self.state["limit_usd"] != limit:
            raise ValueError("Budget cannot change on resume")
        self.state['allow_overrun'] = allow_overrun
        # A killed relay cannot prove whether these calls were billed.
        self.state["spent_usd"] += sum(self.state["pending"].values())
        self.state["uncertain"] += len(self.state["pending"])
        self.state["pending"] = {}
        self.save()

    def save(self):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(self.state, indent=2) + "\n")
        os.replace(temp, self.path)

    def reserve(self, amount: float) -> str:
        with self.condition:
            while True:
                if self.state["stopped"] or (not self.allow_overrun and self.state["spent_usd"] + amount > self.limit):
                    self.state["stopped"] = True
                    self.save()
                    raise RuntimeError(f"Approved ${self.limit:g} budget cannot fund this request")
                if self.allow_overrun or self.state["spent_usd"] + sum(self.state["pending"].values()) + amount <= self.limit:
                    key = uuid.uuid4().hex
                    self.state["pending"][key] = amount
                    self.save()
                    return key
                self.condition.wait(timeout=1)

    def finish(self, key: str, cost: float | None):
        with self.condition:
            reserved = self.state["pending"].pop(key)
            if cost is None:
                cost = reserved
                self.state["uncertain"] += 1
            if cost > reserved + 1e-9:
                self.state["stopped"] = True
            self.state["spent_usd"] += cost
            self.state["completed"] += 1
            self.save()
            self.condition.notify_all()


def start_proxy(key: str, ledger: Ledger, worker_key: str, port: int = 18765):
    client = httpx.Client(timeout=httpx.Timeout(900, connect=30), trust_env=False)

    class Handler(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def log_message(self, *args):
            pass  # Never log credentials, task content or request headers.

        def error(self, status, message):
            raw = json.dumps({"error": {"message": message, "type": "invalid_request_error"}}).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

        def do_POST(self):
            reservation = None
            cost = None
            try:
                if self.headers.get("Authorization") != "Bearer " + worker_key:
                    return self.error(401, "Local relay authentication required")
                if self.path not in ("/v1/responses", "/v1/responses/input_tokens"):
                    return self.error(403, "Endpoint outside approved experiment")
                length = int(self.headers.get("Content-Length", "0"))
                if not 0 < length < 32_000_000:
                    return self.error(400, "Invalid request size")
                payload = json.loads(self.rfile.read(length))
                try:
                    bound = prepare_payload(self.path, payload)
                except ValueError as exc:
                    return self.error(403, str(exc))
                if self.path == "/v1/responses":
                    reservation = ledger.reserve(bound)
                # All billable traffic stays on the official endpoint. The key
                # received from a worker is ignored, never forwarded.
                with client.stream("POST", "https://api.openai.com" + self.path,
                                   headers={"Authorization": "Bearer " + key,
                                            "Content-Type": "application/json"},
                                   json=payload) as response:
                    self.send_response(response.status_code)
                    self.send_header("Content-Type", response.headers.get("content-type", "application/json"))
                    self.send_header("Connection", "close")
                    self.end_headers()
                    self.close_connection = True
                    if "text/event-stream" in response.headers.get("content-type", ""):
                        for line in response.iter_lines():
                            if line.startswith("data: ") and line != "data: [DONE]":
                                event = json.loads(line[6:])
                                value = event.get("response", {})
                                if value.get("usage"):
                                    cost = actual_cost(payload["model"], value["usage"])
                            self.wfile.write((line + "\n").encode())
                            self.wfile.flush()
                    else:
                        raw = response.read()
                        if response.is_success and self.path == "/v1/responses":
                            value = json.loads(raw)
                            if value.get("usage"):
                                cost = actual_cost(payload["model"], value["usage"])
                        self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception as exc:
                try:
                    self.error(403, f"Budget relay stopped request: {type(exc).__name__}")
                except OSError:
                    pass
            finally:
                if reservation:
                    ledger.finish(reservation, cost)

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server
