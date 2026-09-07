"""Private read-only treatment-delivery summary; does not estimate RH outcomes."""
from collections import Counter, defaultdict
from datetime import datetime
import json
from pathlib import Path
from statistics import mean
import sys


def read(path):
    return json.loads(path.read_text())


def summarize(study):
    ledger = read(study / "study.json")
    records = ledger["records"]
    assert len(records) == 240 and len({r["assignment_id"] for r in records}) == 240
    assert all(r["status"] == "completed" for r in records)
    rows = []
    for record in records:
        root = study / record["experiment_dir"]
        state = read(root / "state.json")
        submissions = len(state["submission_ids"])
        assert state["phase"] == "completed" and submissions == state["next_turn_index"]
        assert state["stop_reason"] in {"no_change", "max_revisions"}
        # s000 is a reused seed. A terminal no-change call creates no submission.
        turns = submissions - (state["stop_reason"] == "max_revisions")
        assert 5 <= turns <= 10
        generations = sorted((root / "rubric-generations").glob("generation-*"))
        assert [int(p.name.split("-")[-1]) for p in generations] == list(range(len(generations)))
        admitted = changed = retried = 0
        fallbacks = []
        for previous, current in zip(generations[1:], generations[2:]):
            evolution = read(current / "evolution.json")
            admitted += len(evolution["accepted_candidate_ids"])
            changed += (previous / "rubric.txt").read_bytes() != (current / "rubric.txt").read_bytes()
            retried += sum(isinstance(value, int) and value > 1
                           for key, value in evolution.items() if key.endswith("_attempt_count"))
            reasons = {k: v for k, v in evolution.items() if k.endswith("_fallback_reason") and v}
            if reasons:
                fallbacks.append({"generation": current.name, "reasons": reasons})
        sidecars = []
        for path in sorted((root / "red-team").glob("checkpoint-*/manifest.json")):
            manifest = read(path)
            status = read(path.parent / "status.json")
            assert manifest["included"] == status["included"]
            sidecars.append({"checkpoint": manifest["checkpoint"],
                             "included": manifest["included"], "exit_code": status["exit_code"]})
        assert len(sidecars) == len(generations) - 2
        rows.append({**{k: record[k] for k in ("assignment_id", "condition_id", "task_id", "replicate")},
                     "solver_turns": turns, "saved_submissions_including_seed": submissions,
                     "stop_reason": state["stop_reason"],
                     "online_generations": len(generations) - 2,
                     "admitted_criteria": admitted, "rubric_text_changes": changed,
                     "retried_stages": retried, "fallbacks": fallbacks,
                     "included_sidecars": sum(s["included"] for s in sidecars),
                     "excluded_sidecars": [s for s in sidecars if not s["included"]]})
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["condition_id"]].append(row)
    conditions = {}
    for condition, members in sorted(grouped.items()):
        assert len(members) == 60 and len({r["task_id"] for r in members}) == 20
        conditions[condition] = {
            "assignments": len(members),
            "solver_turns_mean": mean(r["solver_turns"] for r in members),
            "solver_turns_distribution": dict(sorted(Counter(r["solver_turns"] for r in members).items())),
            "stop_reasons": dict(Counter(r["stop_reason"] for r in members)),
            **{k: sum(r[k] for r in members) for k in
               ("online_generations", "admitted_criteria", "rubric_text_changes", "retried_stages", "included_sidecars")},
            "assignments_with_rubric_text_changes": sum(r["rubric_text_changes"] > 0 for r in members),
            "fallback_generations": sum(len(r["fallbacks"]) for r in members),
            "assignments_with_fallbacks": sum(bool(r["fallbacks"]) for r in members),
            "excluded_sidecars": sum(len(r["excluded_sidecars"]) for r in members),
        }
    return {"created_at": datetime.now().astimezone().isoformat(), "study": str(study.resolve()),
            "scope": "Online treatment delivery only; original generation 0 and shared generation 1 excluded. Not an RH outcome analysis.",
            "conditions": conditions, "assignments": rows}


if __name__ == "__main__":
    print(json.dumps(summarize(Path(sys.argv[1])), indent=2))
