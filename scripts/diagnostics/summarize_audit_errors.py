"""Read-only classification of durable audit failures; not a workflow CLI."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys


def classify(record):
    message = record.get("error", "")
    result = {"class": "unclassified", "error_type": record.get("error_type")}
    if "credit balance is too low" in message.lower() or "insufficient_quota" in message:
        return {**result, "class": "billing_quota_or_credit"}
    if "HTTP 429: " in message:
        try:
            payload = json.loads(message.split("HTTP 429: ", 1)[1])["error"]
        except (ValueError, KeyError, TypeError):
            return {**result, "class": "http_429_unclassified"}
        violations = [v for detail in payload.get("details", [])
                      for v in detail.get("violations", [])]
        if violations and all("PerMinute" in v.get("quotaId", "") for v in violations):
            kind = "rate_limit_per_minute"
        else:
            kind = "http_429_unclassified"
        return {**result, "class": kind,
                "quota_ids": sorted({v.get("quotaId", "") for v in violations}),
                "quota_values": sorted({str(v.get("quotaValue", "")) for v in violations})}
    if "User location is not supported" in message:
        return {**result, "class": "unsupported_location"}
    if (record.get("error_type") in {"APIConnectionError", "RemoteProtocolError"}
            or any(s in message for s in ("EOF", "urlopen error", "Remote end closed", "IncompleteRead"))):
        return {**result, "class": "connection_transport"}
    if record.get("error_type") in {"APITimeoutError", "TimeoutError"}:
        return {**result, "class": "timeout"}
    if (record.get("error_type") == "FullRubricJudgeError"
            and message == "rubric-score criterion count does not exactly match the rubric"):
        return {**result, "class": "response_validation"}
    return result


def summarize(root):
    stages = {}
    for stage in sorted(root.glob("direct_*")):
        paths = list(stage.glob("evaluations/*/summary.json"))
        if not paths:
            continue
        if len(paths) != 1:
            raise ValueError(f"Ambiguous summaries in {stage}")
        path = paths[0]
        summary = json.loads(path.read_text())
        records = summary["records"]
        keys = [(r["case_id"], r["model"]) for r in records]
        assert len(keys) == len(set(keys)), "duplicate case/model records"
        failed = []
        for record in records:
            if record["status"] in {"completed", "skipped"}:
                continue
            assert record["status"] == "failed", record["status"]
            failed.append({"case_id": record["case_id"], "model": record["model"],
                           "attempt_count": record.get("attempt_count"),
                           "error_sha256": hashlib.sha256(record.get("error", "").encode()).hexdigest(),
                           **classify(record)})
        counts = Counter((r["model"], r["class"]) for r in failed)
        stages[stage.name] = {
            "source_summary": str(path.resolve()),
            "source_summary_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "summary_status_counts": dict(Counter(r["status"] for r in records)),
            "failures_by_model_and_class": [{"model": m, "class": c, "count": n}
                                            for (m, c), n in sorted(counts.items())],
            "failed_records": failed,
        }
    return {"scope": "Durable direct-stage summary errors; no inference about unpublished stages or prior failed attempts.",
            "stages": stages}


if __name__ == "__main__":
    print(json.dumps(summarize(Path(sys.argv[1])), indent=2))
