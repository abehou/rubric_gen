"""Private read-only audit progress view; counts do not replace the completion gate."""
from collections import Counter
from datetime import datetime
import json
from pathlib import Path
import sys

from summarize_audit_errors import classify

MODELS = {"gpt-5.6-sol", "claude-opus-5", "gemini-3.8-flash"}
WINDOWS = ("full_trajectory", "post_update", "final_artifact", "final_revision")


def monitor(study, audit):
    errors = []

    def read(path):
        if not path.exists():
            return None
        try:
            return json.loads(path.read_text())
        except (OSError, ValueError) as exc:
            errors.append({"path": str(path), "error_type": type(exc).__name__})
            return None

    ledger = read(study / "study.json")
    assignments = ledger["records"]
    completed = sum(r["status"] == "completed" for r in assignments)
    result = {"time": datetime.now().astimezone().isoformat(),
              "study_completed": completed, "stages": {}}
    for window in WINDOWS:
        name = "direct_" + window
        root = audit / name
        paths = list(root.glob("evaluations/*/cases/*/*/score.json"))
        records = [r for p in paths if (r := read(p)) is not None]
        summaries = list(root.glob("evaluations/*/summary.json"))
        summary = read(summaries[0]) if len(summaries) == 1 else None
        result["stages"][name] = {
            "planned": completed * len(MODELS),
            "saved_successes": sum(r.get("status") == "completed" for r in records),
            "saved_by_model": dict(Counter(r.get("model") for r in records
                                           if r.get("status") == "completed")),
            "summary_present": summary is not None,
            "summary_failed": (sum(r["status"] not in {"completed", "skipped"}
                                   for r in summary["records"]) if summary else None),
            "ambiguous_summaries": len(summaries) > 1,
        }
    for name, instrument in (("rubric_score", None), ("absolute_score", "absolute"),
                             ("pairwise_preference", "pairwise")):
        root = audit / name
        manifest = read(root / "manifest.json")
        summary = read(root / "summary.json")
        paths = list((root / "records").glob("*.json"))
        records = [r for p in paths if (r := read(p)) is not None]
        jobs = manifest.get("predispatch_plan", {}).get("jobs", []) if manifest else []
        planned = sum(instrument is None or j.get("instrument") == instrument for j in jobs)
        result["stages"][name] = {
            "planned": planned if manifest else None,
            "saved_records": len(records),
            "saved_by_model": dict(Counter(r.get("model") for r in records)),
            "summary_present": summary is not None,
            "summary_status": summary.get("status") if summary else None,
            "summary_failed": summary.get("failed_semantic_judgment_count") if summary else None,
        }
        if name == "rubric_score":
            failed_attempts = []
            attempt_counts = Counter()
            models_by_key = {j["semantic_key"]: j["model"] for j in jobs}
            for path in root.glob("artifacts/*/evaluations/*/*/failed-attempt-*.json"):
                failure = read(path)
                if failure is None:
                    continue
                key = path.relative_to(root).parts[1]
                attempt_counts[key] += 1
                failed_attempts.append((models_by_key.get(key, "unknown"), classify(failure)["class"]))
            saved_keys = {p.stem for p in paths}
            failure_counts = Counter(failed_attempts)
            result["stages"][name]["attempt_history"] = {
                "failed_attempts": len(failed_attempts),
                "by_model_and_class": [{"model": m, "class": c, "count": n}
                                       for (m, c), n in sorted(failure_counts.items())],
                "jobs_with_failed_attempts": len(attempt_counts),
                "subsequently_saved_jobs": sum(k in saved_keys for k in attempt_counts),
                "unsaved_jobs_by_recorded_attempt_count": dict(Counter(
                    n for k, n in attempt_counts.items() if k not in saved_keys)),
                "note": "Unfinished jobs can still recover; attempt errors are not terminal stage failures.",
            }
    result["read_errors"] = errors
    return result


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Supply study and audit directories")
    print(json.dumps(monitor(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())))
