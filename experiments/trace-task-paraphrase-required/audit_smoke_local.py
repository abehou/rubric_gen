"""Persist one real structured Luna xhigh response before launching the audit."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import os
from pathlib import Path

from dotenv import dotenv_values

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.detection.costs import request_cost, usage_tokens
from rubric_gen.runtime.llm import StructuredRequest, generate_structured


ROOT = Path(__file__).resolve().parents[2]
MODEL = "gpt-5.6-luna"
EFFORT = "xhigh"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.expanduser()
    if not output.is_absolute() or output.is_symlink() or output.exists():
        raise RuntimeError("smoke output must be a new absolute regular path")
    credentials = dotenv_values(ROOT / ".env.local")
    key = os.environ.get("OPENAI_API_KEY") or credentials.get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("configured OPENAI_API_KEY absent")
    os.environ["OPENAI_API_KEY"] = str(key)
    os.environ["RUBRIC_GEN_OPENAI_REASONING_EFFORT"] = EFFORT
    request = StructuredRequest(
        instructions="Return the requested JSON object exactly.",
        evidence='Set the field "route" to "ok".',
        schema_name="local_audit_route_smoke",
        schema={
            "type": "object",
            "properties": {"route": {"type": "string", "enum": ["ok"]}},
            "required": ["route"],
            "additionalProperties": False,
        },
        max_output_tokens=1_024,
    )
    generation = generate_structured(MODEL, request)
    usage = usage_tokens(generation)
    cost = request_cost(MODEL, **usage) if usage is not None else None
    write_json_atomic(output, {
        "kind": "luna-xhigh-structured-audit-route-smoke",
        "time": datetime.now(timezone.utc).isoformat(),
        "model": MODEL,
        "reasoning_effort": EFFORT,
        "response": generation.text,
        "generation": generation.provenance(),
        "usage": usage,
        "observed_api_usd": cost,
    })
    print(f"saved {output}; observed_api_usd={cost}", flush=True)


if __name__ == "__main__":
    main()
