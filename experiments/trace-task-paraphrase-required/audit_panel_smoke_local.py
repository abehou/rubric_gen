"""Persist one structured smoke response from each matched audit provider."""
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
MODELS = ("gpt-5.6-sol", "claude-opus-5")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--runtime-config", type=Path, required=True)
    parser.add_argument("--path-map", type=Path, required=True)
    parser.add_argument("--model", choices=MODELS)
    args = parser.parse_args()
    output_root = args.output_root.expanduser()
    if not output_root.is_absolute() or output_root.is_symlink() or output_root.exists():
        raise RuntimeError("smoke output root must be a new absolute directory")
    for path in (args.runtime_config, args.path_map):
        if not path.is_absolute() or path.is_symlink() or not path.is_file():
            raise RuntimeError("smoke runtime inputs must be absolute regular files")
    os.environ["RUBRIC_GEN_RUNTIME_CONFIG"] = str(args.runtime_config.resolve())
    os.environ["RUBRIC_GEN_PATH_MAP_FILE"] = str(args.path_map.resolve())
    credentials = dotenv_values(ROOT / ".env.local")
    for name in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        value = os.environ.get(name) or credentials.get(name)
        if not value:
            raise RuntimeError(f"configured {name} absent")
        os.environ[name] = str(value)
    os.environ.pop("RUBRIC_GEN_OPENAI_REASONING_EFFORT", None)
    request = StructuredRequest(
        instructions="Return the requested JSON object exactly.",
        evidence='Set the field "route" to "ok".',
        schema_name="local_matched_audit_route_smoke",
        schema={
            "type": "object",
            "properties": {"route": {"type": "string", "enum": ["ok"]}},
            "required": ["route"],
            "additionalProperties": False,
        },
        max_output_tokens=1_024,
    )
    output_root.mkdir(parents=True)
    for model in ((args.model,) if args.model else MODELS):
        generation = generate_structured(model, request)
        usage = usage_tokens(generation)
        cost = request_cost(model, **usage) if usage is not None else None
        write_json_atomic(output_root / f"{model}.json", {
            "kind": "matched-audit-provider-smoke",
            "time": datetime.now(timezone.utc).isoformat(),
            "model": model,
            "response": generation.text,
            "generation": generation.provenance(),
            "usage": usage,
            "observed_api_usd": cost,
        })
        print(f"{model}: ok; observed_api_usd={cost}", flush=True)


if __name__ == "__main__":
    main()
