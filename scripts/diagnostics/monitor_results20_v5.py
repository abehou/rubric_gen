"""Read-only private monitor; no provider requests or experiment writes."""
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[2]
STUDY = ROOT / "runs/studies/20260905-redteam-v5/biomnibench-da-factorial-r10-8ab12c898ae7"


def read(path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def evolution_summary(paths):
    count = admitted = retry_stages = 0
    fallbacks = []
    for path in paths:
        value = read(path)
        if value is None:
            continue
        count += 1
        admitted += len(value.get("accepted_candidate_ids", []))
        for key, item in value.items():
            if key.endswith("_fallback_reason") and item:
                fallbacks.append({"path": str(path.relative_to(STUDY)), "stage": key, "reason": item})
            if key.endswith("_attempt_count") and isinstance(item, int) and item > 1:
                retry_stages += 1
    return {"generations": count, "admitted_criteria": admitted, "retried_stages": retry_stages,
            "fallback_stage_count": len(fallbacks),
            "fallback_generation_count": len({f["path"] for f in fallbacks}),
            "fallback_reason_counts": dict(Counter(f["reason"] for f in fallbacks)),
            "fallback_examples": fallbacks[:3]}


def main():
    study = read(STUDY / "study.json") or {}
    records = study.get("records", [])
    phases = Counter()
    checkpoints = Counter()
    scored = Counter()
    failures = []
    streams = []
    for record in records:
        path = STUDY / record["experiment_dir"]
        state = read(path / "state.json")
        if state:
            phases[state.get("phase", "unknown")] += 1
            checkpoints[len(state.get("submission_ids", [])) - 1] += 1
            scored[max(0, len(state.get("scores", [])) - 1)] += 1
        if record["status"] in {"failed", "invalid"}:
            failures.append({key: record.get(key) for key in
                             ("assignment_id", "status", "error_type", "finished_at")}
                            | {"error": str(record.get("error", ""))[:180]})
        if record["status"] == "running":
            streams.extend(path.glob("turns/turn-*/attempts/*.trajectory.stream.jsonl"))
    latest = max((p.stat().st_mtime for p in streams if p.exists()), default=None)
    online = [p for p in (STUDY / "experiments").glob("*/*/*/*/rubric-generations/generation-*/evolution.json") if int(p.parent.name.rsplit("-", 1)[1]) > 1]
    sidecars = []
    for p in (STUDY / "experiments").glob("*/*/*/*/red-team/*/manifest.json"):
        d = read(p)
        if d:
            sidecars.append(d)
    print(json.dumps({
        "time": datetime.now().astimezone().isoformat(timespec="seconds"),
        "disk_free_GiB": round(shutil.disk_usage(ROOT).free / 2**30, 1),
        "study_status": study.get("status"),
        "invocation_concurrency": study.get("max_concurrency_last_invocation"),
        "assignment_status": dict(Counter(r["status"] for r in records)),
        "phases": dict(phases),
        "saved_solver_revision_snapshots": dict(sorted(checkpoints.items())),
        "scored_revisions": dict(sorted(scored.items())),
        "newest_active_solver_stream_age_seconds": None if latest is None else round(datetime.now().timestamp() - latest, 1),
        "pretreatment": evolution_summary((STUDY / "pretreatment-rubrics").glob("*/*/rubric-generations/generation-0001/evolution.json")),
        "online": evolution_summary(online),
        "sidecar_manifests": len(sidecars),
        "sidecar_inclusion": dict(Counter(str(s.get("included")) for s in sidecars)),
        "failure_type_counts": dict(Counter(f["error_type"] for f in failures)),
        "failed_assignment_examples": failures[:4],
    }, ensure_ascii=False))


if __name__ == "__main__":
    main()
