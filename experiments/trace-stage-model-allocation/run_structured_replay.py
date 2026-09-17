"""Run only the bounded Luna-high structured RTT stage replays.

The frozen Luna-low outputs are controls and are never regenerated.  New calls
keep the saved prompt, evidence, schema, model, and provider fixed; only the
reasoning effort changes from low to high.  Results are persisted one call at a
time so reruns are missing-only.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from copy import deepcopy
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import sys
import time

from dotenv import dotenv_values
import jsonschema

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPOSITORY_ROOT / "src"))

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision import evolution_assessment as assessment
from rubric_gen.submission_revision import evolution_provider
from rubric_gen.submission_revision.evolution_provider import ProviderContract
from rubric_gen.submission_revision.evolution_serialization import (
    canonical_json,
    canonical_sha256,
)


ROOT = _REPOSITORY_ROOT
RUN = ROOT / "runs/trace-stage-model-allocation-20260917"
MANIFEST = RUN / "frozen/manifest.json"
OUTPUT = RUN / "structured-high"
RUNTIME_CONFIG = RUN / "runtime/structured-high.json"
MAX_CONCURRENCY = 4
MAX_PROVIDER_ATTEMPTS = 3


def read(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def unnumber(text: str) -> str:
    return "\n".join(
        re.sub(r"^\[L\d{6}\] ?", "", line) for line in text.splitlines()
    )


def reversed_quality_request(request: dict[str, object]) -> dict[str, object]:
    """Return a fully A/B-reversed quality presentation for order sensitivity."""
    reversed_request = deepcopy(request)
    evidence = json.loads(str(reversed_request["evidence"]))
    old_a = deepcopy(evidence["artifact_A"])
    old_b = deepcopy(evidence["artifact_B"])
    old_a["source_id"] = "artifact_B"
    old_b["source_id"] = "artifact_A"
    evidence["artifact_A"] = old_b
    evidence["artifact_B"] = old_a
    evidence["source_manifest"] = {
        "artifact_A": deepcopy(evidence["artifact_A"]),
        "artifact_B": deepcopy(evidence["artifact_B"]),
    }
    for item in evidence["source_manifest"].values():
        item.pop("numbered_text", None)
        item.pop("artifact_id", None)
        item["native_id"] = (
            evidence["artifact_A"]["artifact_id"]
            if item["source_id"] == "artifact_A"
            else evidence["artifact_B"]["artifact_id"]
        )
        item.pop("source_id", None)
    evidence["visible_difference"] = assessment.pair_text_difference(
        unnumber(evidence["artifact_A"]["numbered_text"]),
        unnumber(evidence["artifact_B"]["numbered_text"]),
    )
    reversed_request["evidence"] = canonical_json(evidence)
    preferred = reversed_request["schema"]["properties"]["preferred_artifact_id"]
    preferred["enum"] = [
        evidence["artifact_A"]["artifact_id"],
        evidence["artifact_B"]["artifact_id"],
        None,
    ]
    sources = reversed_request["response_contract"]["sources"]
    sources["artifact_A"], sources["artifact_B"] = (
        deepcopy(sources["artifact_B"]),
        deepcopy(sources["artifact_A"]),
    )
    return reversed_request


def work_items(manifest: dict[str, object]) -> list[dict[str, object]]:
    items: list[dict[str, object]] = []
    saved_provider = deepcopy(
        manifest["current_pair_quality"][0]["request"]["provider"]
    )

    def add(group: str, identity: str, record: dict[str, object]) -> None:
        request = deepcopy(record["request"])
        # The older forensic export preserved exact public inputs but omitted
        # producer-only provider fields.  The original stage was Luna-low; use
        # the exact provider contract saved by the current Luna-low run.
        request.setdefault("provider", deepcopy(saved_provider))
        items.append({
            "group": group,
            "identity": identity,
            "request": request,
            "control": record,
        })

    for record in manifest["current_pair_quality"]:
        add("current_pair_quality", record["request_sha256"], record)
    for record in manifest["historical_pair_quality"]:
        identity = f"{record['case']}--{record['pair_id']}"
        add("historical_pair_quality", identity, record)
        reverse = deepcopy(record)
        reverse["request"] = reversed_quality_request(record["request"])
        reverse["request_sha256"] = canonical_sha256(reverse["request"])
        reverse["identity_note"] = (
            "High-only reversed-presentation diagnostic derived from the exact frozen "
            "public pair; not a replacement for the original-order paired comparison."
        )
        add("historical_pair_quality_reversed", identity, reverse)
    for group in ("diagnosis", "compilation", "current_application"):
        for record in manifest[group]:
            add(group, record["request_sha256"], record)
    for record in manifest["historical_application"]:
        add(
            "historical_application",
            f"{record['case']}--{record['role']}",
            record,
        )
    return items


def validate_response(request: dict[str, object], value: object) -> None:
    jsonschema.Draft202012Validator(request["schema"]).validate(value)
    if not isinstance(value, dict):
        raise ValueError("structured response is not an object")
    evidence = json.loads(str(request["evidence"]))
    line_counts = {
        source_id: int(source["line_count"])
        for source_id, source in request["response_contract"]["sources"].items()
    }
    ref_fields = {
        "quality": ("decisive_refs",),
        "diagnosis": ("preferred_refs", "rejected_refs"),
        "application": ("public_refs",),
    }.get(request["stage"], ())
    for field in ref_fields:
        for ref in value[field]:
            source_id = ref["source_id"]
            if source_id not in line_counts:
                raise ValueError(f"unknown source ID in {field}: {source_id}")
            if not 1 <= ref["start_line"] <= ref["end_line"] <= line_counts[source_id]:
                raise ValueError(f"out-of-range public reference in {field}: {ref}")
    if request["stage"] == "quality" and value["preferred_artifact_id"] is not None:
        seen = {item["source_id"] for item in value["decisive_refs"]}
        if seen != {"artifact_A", "artifact_B"}:
            raise ValueError("non-null quality preference must cite both artifacts")
    if request["stage"] == "diagnosis" and value["action"] not in {
        "NO_SUPPORTED_RELATION", "PREFERENCE_CONFLICT"
    }:
        if not value["preferred_refs"] or not value["rejected_refs"]:
            raise ValueError("supported diagnosis must cite both artifacts")
    if request["stage"] == "application":
        labels = request["response_contract"]["labels"]
        app, level = value["applicability"], value["level"]
        valid = (
            (app == "applicable" and level in labels)
            or (app == "not_applicable" and level == labels[0])
            or (app == "undecidable" and level is None)
        )
        if not valid:
            raise ValueError("incoherent application applicability/level")
        if app == "applicable" and not value["public_refs"]:
            raise ValueError("applicable judgment must cite the artifact")
    # Accessing the evidence above is deliberate: malformed frozen requests fail
    # locally before any provider call.
    if not isinstance(evidence, dict):
        raise ValueError("request evidence is not an object")


def destination(item: dict[str, object]) -> Path:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(item["identity"]))
    return OUTPUT / str(item["group"]) / safe / "result.json"


def run_one(item: dict[str, object]) -> dict[str, object]:
    target = destination(item)
    if target.is_file():
        saved = read(target)
        if saved.get("status") == "completed":
            return {"target": target.as_posix(), "status": "reused"}
        raise RuntimeError(f"non-completed result requires inspection, not overwrite: {target}")

    prior_failure_path = target.with_name("failure.json")
    prior_failure = read(prior_failure_path) if prior_failure_path.is_file() else None
    request = item["request"]
    provider = request["provider"]
    if provider["model"] != "gpt-5.6-luna" or provider["reasoning_effort"] != "low":
        raise RuntimeError("frozen structured control is not gpt-5.6-luna low")
    contract = ProviderContract(
        model=provider["model"],
        max_output_tokens=provider["max_output_tokens"],
        max_request_bytes=provider["max_request_bytes"],
        service_tier=provider["service_tier"],
        reasoning_effort="high",
    )
    errors = []
    for attempt in range(1, MAX_PROVIDER_ATTEMPTS + 1):
        started = time.monotonic()
        try:
            output = contract.generate(
                instructions=request["prompt"],
                evidence=request["evidence"],
                response_schema=request["schema"],
                request_context=f"Luna-high {item['group']}",
                schema_name=f"rtt_{request['stage']}_high",
            )
            contract.validate_output(output)
            value = json.loads(output.response_text)
            validate_response(request, value)
            elapsed = time.monotonic() - started
            payload = {
                "kind": "trace-stage-luna-high-structured-replay-v1",
                "status": "completed",
                "completed_at": datetime.now(timezone.utc).isoformat(),
                "group": item["group"],
                "identity": item["identity"],
                "frozen_manifest_sha256": sha256_file(MANIFEST),
                "control_request_sha256": canonical_sha256(request),
                "controlled_change": {
                    "model": "gpt-5.6-luna",
                    "control_reasoning_effort": "low",
                    "diagnostic_reasoning_effort": "high",
                    "prompt_evidence_schema_unchanged": True,
                },
                "response": value,
                "response_text": output.response_text,
                "generation": output.generation,
                "cost": output.cost,
                "latency_seconds": elapsed,
                "provider_attempt": attempt,
                "prior_provider_errors": errors,
                "prior_local_failure": prior_failure,
            }
            target.parent.mkdir(parents=True, exist_ok=True)
            write_json_atomic(target, payload)
            return {"target": target.as_posix(), "status": "completed"}
        except Exception as exc:  # retain transport failures without hiding them
            errors.append({
                "attempt": attempt,
                "type": type(exc).__name__,
                "message": str(exc),
                "latency_seconds": time.monotonic() - started,
            })
            if attempt < MAX_PROVIDER_ATTEMPTS:
                time.sleep(2 ** attempt)
    failure = target.with_name("failure.json")
    failure.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(failure, {
        "kind": "trace-stage-luna-high-structured-replay-failure-v1",
        "status": "failed",
        "failed_at": datetime.now(timezone.utc).isoformat(),
        "group": item["group"],
        "identity": item["identity"],
        "control_request_sha256": canonical_sha256(request),
        "errors": errors,
    })
    return {"target": failure.as_posix(), "status": "failed"}


def main() -> None:
    if not MANIFEST.is_file():
        raise RuntimeError("run build_frozen_replay.py first")
    key = dotenv_values(ROOT / ".env.local").get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is unavailable in .env.local")
    os.environ["OPENAI_API_KEY"] = str(key)
    runtime = {
        "version": 1,
        "aggregate_concurrency": MAX_CONCURRENCY,
        "audit_studies": 1,
        "coordination_dir": str((RUN / "runtime/coordination").resolve()),
    }
    RUNTIME_CONFIG.parent.mkdir(parents=True, exist_ok=True)
    if RUNTIME_CONFIG.is_file() and read(RUNTIME_CONFIG) != runtime:
        raise RuntimeError("existing diagnostic runtime policy differs")
    if not RUNTIME_CONFIG.exists():
        write_json_atomic(RUNTIME_CONFIG, runtime)
    os.environ["RUBRIC_GEN_RUNTIME_CONFIG"] = str(RUNTIME_CONFIG.resolve())
    os.environ.setdefault(
        "RUBRIC_GEN_INVOCATION_ID", "trace-stage-luna-high-structured-20260917"
    )
    manifest = read(MANIFEST)
    if not manifest["dev3_remains_paused"]:
        raise RuntimeError("frozen receipt does not attest that Dev3 remains paused")
    items = work_items(manifest)
    results = []
    with ThreadPoolExecutor(max_workers=MAX_CONCURRENCY) as executor:
        futures = {executor.submit(run_one, item): item for item in items}
        for future in as_completed(futures):
            result = future.result()
            results.append(result)
            print(json.dumps(result, sort_keys=True), flush=True)
    counts = {}
    for result in results:
        counts[result["status"]] = counts.get(result["status"], 0) + 1
    receipt = {
        "kind": "trace-stage-luna-high-structured-replay-receipt-v1",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "frozen_manifest_sha256": sha256_file(MANIFEST),
        "model": "gpt-5.6-luna",
        "reasoning_effort": "high",
        "max_concurrency": MAX_CONCURRENCY,
        "total_items": len(items),
        "counts": counts,
        "no_luna_low_calls": True,
        "no_sol_or_opus_calls": True,
    }
    write_json_atomic(OUTPUT / "receipt.json", receipt)
    print(json.dumps(receipt, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
