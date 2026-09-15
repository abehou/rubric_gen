"""Minimal same-route provider smoke for the provisional Sol/Opus audit.

This deliberately sends one tiny structured request per audit model and writes
only response metadata.  It is an operational gate, not scientific data.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
import time
from pathlib import Path

from dotenv import dotenv_values

from rubric_gen.runtime.llm import StructuredRequest, generate_structured


ROOT = Path(__file__).resolve().parents[2]
OUT = Path("/home/aydanh/runs/trace-task-paraphrase-required-20260914/provisional-audit/route-smoke")
MODELS = ("gpt-5.6-sol", "claude-opus-5")
SCHEMA = {
    "type": "object",
    "properties": {"ok": {"type": "boolean"}},
    "required": ["ok"],
    "additionalProperties": False,
}


def _configure_credentials() -> None:
    values = dotenv_values("/home/aydanh/repos/rubric_gen/.env.local")
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        if not values.get(key):
            raise RuntimeError(f"configured {key} is absent")
        os.environ[key] = str(values[key])


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("route smoke must run on Slurm")
    _configure_credentials()
    OUT.mkdir(parents=True, exist_ok=True)
    rows: list[dict[str, object]] = []
    for model in MODELS:
        started = time.time()
        req = StructuredRequest(
            instructions="Return the requested JSON object.",
            evidence='{"ok": true}',
            schema_name="route_smoke",
            schema=SCHEMA,
            max_output_tokens=16,
        )
        row: dict[str, object] = {
            "model": model,
            "started_at": started,
            "job_id": os.environ["SLURM_JOB_ID"],
            "commit": subprocess.check_output(
                ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
            ).strip(),
        }
        try:
            result = generate_structured(model, req, timeout_seconds=60.0)
            row.update(
                {
                    "status": "success",
                    "provider": result.provider,
                    "effective_model": result.effective_model,
                    "response_id": result.response_id,
                    "response_sha256": hashlib.sha256(result.text.encode()).hexdigest(),
                    "provider_metadata": result.provider_metadata,
                }
            )
        except Exception as exc:  # noqa: BLE001 - preserve operational classification
            row.update(
                {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                    "error": str(exc)[:500],
                }
            )
        row["elapsed_seconds"] = round(time.time() - started, 3)
        rows.append(row)
        print(json.dumps({"model": model, "status": row["status"]}), flush=True)
    receipt = {
        "kind": "provisional-audit-route-smoke",
        "job_id": os.environ["SLURM_JOB_ID"],
        "commit": rows[0]["commit"],
        "models": rows,
        "provider_calls": len(rows),
    }
    (OUT / f"smoke-{os.environ['SLURM_JOB_ID']}.json").write_text(
        json.dumps(receipt, indent=2) + "\n"
    )
    if any(row["status"] != "success" for row in rows):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
