"""Private read-only observation of one explicitly selected study and audit root."""
from collections import Counter
import json
from pathlib import Path
import runpy
import sys


def main():
    if len(sys.argv) != 3:
        raise SystemExit("Supply exactly one study directory and its audit directory")
    study, audit = (Path(arg).resolve() for arg in sys.argv[1:])
    monitor = runpy.run_path(str(Path(__file__).with_name("monitor_results20_v5.py")))
    monitor["main"].__globals__["STUDY"] = study
    monitor["main"]()
    stages = {}
    for name in (
        "direct_full_trajectory", "direct_post_update", "direct_final_artifact",
        "direct_final_revision", "rubric_score", "absolute_score", "pairwise_preference",
    ):
        candidates = (list((audit / name / "evaluations").glob("*/summary.json"))
                      if name.startswith("direct_") else [audit / name / "summary.json"])
        candidates = [path for path in candidates if path.is_file()]
        if not candidates:
            stages[name] = {"summary_present": False}
            continue
        if len(candidates) != 1:
            stages[name] = {"ambiguous_summaries": [str(p) for p in candidates]}
            continue
        value = json.loads(candidates[0].read_text())
        records = value.get("records", [])
        stages[name] = {
            "summary_present": True,
            "status": value.get("status"),
            "models": value.get("models"),
            "records": len(records),
            "records_by_model": dict(Counter(r.get("model") for r in records)),
            "record_status": dict(Counter(r.get("status") for r in records)),
            "planned": value.get("planned_semantic_judgment_count"),
            "successful": value.get("successful_semantic_judgment_count"),
            "failed": value.get("failed_semantic_judgment_count"),
            "missing_models": value.get("missing_models"),
            "assignment_coverage": value.get("assignment_coverage"),
        }
    print(json.dumps({"audit_root": str(audit), "stages": stages}, ensure_ascii=False))


if __name__ == "__main__":
    main()
