"""Provider-free usage and concurrency accounting for the Results40 new20 run."""
from __future__ import annotations

from collections import Counter, defaultdict
import csv
import json
import os
from pathlib import Path
from types import SimpleNamespace

from rubric_gen.detection.costs import request_cost, usage_tokens
from rubric_gen.runtime.agents.costs import RunCost
from rubric_gen.runtime.pricing import PRICING_AS_OF
from rubric_gen.submission_revision.experiment import load_experiment

from make_configs import ROOT, RUN, SHARDS, config_path


REPORT = ROOT / "docs/reports/2026-09-18/trace-v21-execution-verified-provenance-result40"
EVENT_ROOT = Path("/home/aydanh/repos/rubric_gen/runs/.runtime-babel")


def read(path: Path):
    return json.loads(path.read_text())


def write_json(name: str, value: object) -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / name).write_text(json.dumps(value, indent=2, ensure_ascii=False) + "\n")


def write_csv(name: str, rows: list[dict[str, object]]) -> None:
    if not rows:
        return
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (REPORT / name).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        for row in rows:
            writer.writerow({
                key: json.dumps(value, ensure_ascii=False)
                if isinstance(value, (dict, list, tuple)) else value
                for key, value in row.items()
            })


def normalized(provider: str, usage: object):
    return usage_tokens(SimpleNamespace(provider=provider, provider_metadata={"usage": usage}))


def receipt(stage: str, model: str, provider: str, usage: object, path: Path,
            response_id: str | None, **extra) -> dict[str, object]:
    tokens = normalized(provider, usage)
    return {
        "stage": stage,
        "model": model,
        "provider": provider,
        "response_id": response_id,
        "path": str(path),
        "usage_available": tokens is not None,
        **(tokens or {}),
        "usage_based_usd": request_cost(model, **tokens) if tokens else None,
        **extra,
    }


def agent_receipts(paths: list[Path], stage: str) -> tuple[list[dict[str, object]], dict[str, object]]:
    threads: dict[str, dict[str, object]] = {}
    events = Counter()
    for path in paths:
        for line in path.open(errors="replace"):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            events[event.get("type", "unknown")] += 1
            if event.get("type") != "turn.completed" or not isinstance(event.get("usage"), dict):
                continue
            key = str(event.get("thread_id") or path)
            cost = RunCost.from_event(event, model="gpt-5.6-luna")
            item = threads.setdefault(key, {
                "stage": stage,
                "model": "gpt-5.6-luna",
                "thread_id": key,
                "path": str(path),
                "usage": {},
                "estimated_cost_usd": 0.0,
            })
            usage = item["usage"]
            for name, value in event["usage"].items():
                if isinstance(value, int):
                    usage[name] = max(int(usage.get(name, 0)), value)
            if cost.estimated_cost_usd is not None:
                item["estimated_cost_usd"] = max(
                    float(item["estimated_cost_usd"]), cost.estimated_cost_usd
                )
    rows = list(threads.values())
    return rows, {
        "stage": stage,
        "streams": len(paths),
        "threads_with_usage": len(rows),
        "events": dict(events),
        "usage_totals": dict(sum((Counter(row["usage"]) for row in rows), Counter())),
        "usage_based_usd": sum(float(row["estimated_cost_usd"]) for row in rows),
    }


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Results40 NAS cost accounting must run through Slurm")
    studies = []
    audits = []
    roots = []
    for task, kind in SHARDS:
        experiment = load_experiment(config_path(task, kind))
        study = Path(experiment.dag["revise"]["output_dir"])
        audit = Path(experiment.dag["detect"]["output_dir"])
        ledger = read(study / "study.json")
        studies.append(study)
        audits.append(audit)
        roots.extend(study / row["experiment_dir"] for row in ledger["records"])
    if len(roots) != 240:
        raise RuntimeError("expected 240 Results40 new-task assignment roots")
    response_rows: list[dict[str, object]] = []
    failures: list[dict[str, object]] = []
    seen: set[str] = set()

    for root in roots:
        arm = "user" if root.name.startswith("user-simulator") else "full"
        request_roots = (
            root / "trace-defense-requests",
            root / "trace-defense-v2-requests",
        )
        for path in (
            path
            for request_root in request_roots
            for path in request_root.glob("*/attempt-*.json")
        ):
            attempt = read(path)
            output = attempt.get("output")
            if output:
                generation = output["generation"]
                response_id = generation.get("response_id")
                if response_id and response_id in seen:
                    continue
                if response_id:
                    seen.add(response_id)
                response_rows.append(receipt(
                    f"trace_{attempt['stage']}", generation["requested_model"],
                    generation["provider"], generation.get("usage"), path,
                    response_id, status=attempt["status"], arm=arm,
                    wall_seconds=attempt.get("wall_seconds"), native_cost=output.get("cost"),
                ))
            else:
                failures.append({
                    "stage": f"trace_{attempt['stage']}", "path": str(path),
                    "status": attempt["status"], "error_type": attempt.get("error_type"),
                    "wall_seconds": attempt.get("wall_seconds"),
                })
        for path in (root / "judgments").glob("**/usage.json"):
            generation = (read(path).get("call") or {})
            response_id = generation.get("response_id")
            if not response_id or response_id in seen:
                continue
            seen.add(response_id)
            response_rows.append(receipt(
                "optimizer_judge", generation["requested_model"], generation["provider"],
                generation.get("raw_usage"), path, response_id, arm=arm,
            ))
        feedback_paths = list((root / "feedback-generations").glob("**/*.json"))
        feedback_paths += list((root / "feedback-history-summaries").glob("**/*.json"))
        for path in feedback_paths:
            value = read(path)
            generation = (
                value.get("feedback_generation") or value.get("summary_generation")
                or value.get("generation")
            )
            if not isinstance(generation, dict):
                continue
            response_id = generation.get("response_id")
            if not response_id or response_id in seen:
                continue
            seen.add(response_id)
            stage = "simulator_history" if "summary_generation" in value else "simulator"
            response_rows.append(receipt(
                stage, generation["requested_model"], generation["provider"],
                generation.get("usage") or generation.get("provider_metadata", {}).get("usage"),
                path, response_id, arm=arm,
            ))

    imported: set[tuple[str, str]] = set()
    for path in (path for audit in audits for path in audit.glob("*/imported-requests.jsonl")):
        for line in path.open():
            imported.add((path.parent.name, json.loads(line)["key"]))
    for path in (path for audit in audits for path in (audit / "rubric_score/records").glob("*.json")):
        record = read(path)
        usage_path = Path(record["evaluation_path"]).parent / "usage.json"
        generation = read(usage_path)["call"]
        response_id = generation.get("response_id")
        if not response_id or response_id in seen:
            continue
        seen.add(response_id)
        response_rows.append(receipt(
            "audit_rubric", generation["requested_model"], generation["provider"],
            generation.get("raw_usage"), usage_path, response_id,
            reused_exact=("rubric_score", path.stem) in imported,
        ))
    for stage in ("absolute_score", "pairwise_preference"):
        for path in (path for audit in audits for path in (audit / stage / "records").glob("*.json")):
            record = read(path)
            generation = record["generation"]
            response_id = generation.get("response_id")
            if not response_id or response_id in seen:
                continue
            seen.add(response_id)
            response_rows.append(receipt(
                f"audit_{stage}", generation["requested_model"], generation["provider"],
                generation.get("provider_metadata", {}).get("usage"), path, response_id,
                reused_exact=(stage, path.stem) in imported,
            ))
    for path in (path for audit in audits for path in audit.glob("direct_*/evaluations/*/cases/*/*/score.json")):
        stage = f"audit_{next(part for part in path.parts if part.startswith('direct_'))}"
        for item in read(path).get("generations", []):
            generation = item["generation"]
            response_id = generation.get("response_id")
            if not response_id or response_id in seen:
                continue
            seen.add(response_id)
            response_rows.append(receipt(
                stage, generation["requested_model"], generation["provider"],
                generation.get("provider_metadata", {}).get("usage"), path, response_id,
                chunk_stage=item.get("stage"),
            ))

    agent_rows = []
    agent_summaries = []
    for stage, paths in (
        ("attack_sidecar", [path for root in roots for path in (root / "red-team").glob("checkpoint-*/trajectory.stream.jsonl")]),
        ("solver", [path for root in roots for path in (root / "turns").glob("turn-*/trajectory.stream.jsonl")]),
    ):
        rows, summary = agent_receipts(paths, stage)
        agent_rows.extend(rows)
        agent_summaries.append(summary)

    grouped: dict[tuple[str, str], list[dict[str, object]]] = defaultdict(list)
    for row in response_rows:
        grouped[(str(row["stage"]), str(row["model"]))].append(row)
    stage_summary = []
    for (stage, model), rows in sorted(grouped.items()):
        fresh = [row for row in rows if not row.get("reused_exact")]
        stage_summary.append({
            "stage": stage,
            "model": model,
            "saved_responses": len(rows),
            "reused_exact": len(rows) - len(fresh),
            "fresh_saved_responses": len(fresh),
            "usage_available": sum(bool(row["usage_available"]) for row in fresh),
            "input_tokens": sum(int(row.get("input_tokens", 0)) for row in fresh),
            "output_tokens": sum(int(row.get("output_tokens", 0)) for row in fresh),
            "cached_input_tokens": sum(int(row.get("cached_input_tokens", 0)) for row in fresh),
            "cache_write_input_tokens": sum(int(row.get("cache_write_input_tokens", 0)) for row in fresh),
            "usage_based_usd": sum(float(row.get("usage_based_usd") or 0) for row in fresh),
        })

    launches = [read(path) for path in sorted((RUN / "owners").glob("*/launch.json"))]
    job_ids = {str(launch["job_id"]) for launch in launches}
    events = []
    for path in EVENT_ROOT.glob("events-*.jsonl"):
        for line in path.open(errors="replace"):
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if str(event.get("job_id")) in job_ids:
                events.append(event)
    operation_groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    runtime_failures = []
    for event in events:
        if str(event.get("event", "")).startswith("operation_"):
            operation_groups[str(event.get("operation"))].append(event)
        if event.get("event") in {"operation_failed", "audit_stage_failed"}:
            runtime_failures.append({
                key: event.get(key) for key in (
                    "job_id", "event", "operation", "category", "error_type", "time"
                )
            })
    operations = {
        name: {
            "records": len(rows),
            "events": dict(Counter(row["event"] for row in rows)),
            "elapsed_seconds": sum(float(row.get("elapsed_seconds", 0)) for row in rows),
        }
        for name, rows in operation_groups.items()
    }
    maximum_active = Counter()
    active = Counter()
    for event in sorted(events, key=lambda row: float(row.get("time", 0))):
        kind = str(event.get("kind", ""))
        if not kind.startswith("audit-provider-"):
            continue
        provider = kind.removeprefix("audit-provider-")
        if event["event"] == "acquired":
            active[provider] += int(event["slots"])
            maximum_active[provider] = max(maximum_active[provider], active[provider])
        elif event["event"] == "released":
            active[provider] -= int(event["slots"])

    write_csv("cost-stage-summary.csv", stage_summary)
    write_csv("cost-failed-learning-attempts.csv", failures)
    result = {
        "pricing_registry_date": PRICING_AS_OF,
        "stages": stage_summary,
        "agents": agent_summaries,
        "failed_learning_attempts": len(failures),
        "runtime_failures": runtime_failures,
        "operations": operations,
        "audit_maximum_active_by_provider": dict(maximum_active),
        "jobs": sorted(job_ids),
        "response_usage_based_usd": sum(float(row["usage_based_usd"] or 0) for row in response_rows if not row.get("reused_exact")),
        "agent_usage_based_usd": sum(float(row["usage_based_usd"]) for row in agent_summaries),
        "total_identifiable_usage_based_usd": (
            sum(float(row["usage_based_usd"] or 0) for row in response_rows if not row.get("reused_exact"))
            + sum(float(row["usage_based_usd"]) for row in agent_summaries)
        ),
        "limitations": [
            "Usage-based estimates are not provider invoices.",
            "Failed calls without returned usage have unknown cost.",
            "Agent usage is cumulative per saved thread and uses the maximum terminal total.",
            "Reused exact judgments are excluded from fresh cost even though their original historical generation had a cost.",
        ],
    }
    write_json("costs.json", result)
    print(json.dumps({
        "total_identifiable_usage_based_usd": result["total_identifiable_usage_based_usd"],
        "stage_rows": len(stage_summary),
        "runtime_failures": len(runtime_failures),
        "audit_maximum_active_by_provider": dict(maximum_active),
    }), flush=True)


if __name__ == "__main__":
    main()
