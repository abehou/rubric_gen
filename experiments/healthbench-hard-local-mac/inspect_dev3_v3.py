"""Inspect saved Dev3 answers and score disagreements without provider calls."""

from collections import Counter, defaultdict
import argparse
from difflib import unified_diff
import hashlib
import json
from pathlib import Path
from statistics import mean

from analyze_dev3_v3 import analyze, CONFIG, read


def inspect(config: Path = CONFIG):
    result = analyze(config)
    run = Path(result["run_dir"])
    study = run / "studies" / result["experiment_id"]
    audit = run / "audits" / result["experiment_id"]
    records = [read(p) for p in (audit / "rubric_score/records").glob("*.json")]
    index = {(r["task_id"], r["rubric_sha256"], r["answer_input_sha256"]): r for r in records}
    by_assignment = {r["assignment_id"]: r for r in result["assignments"]}
    rows = []
    for r in sorted(read(study / "study.json")["records"], key=lambda r: r["assignment_id"]):
        root = study / r["experiment_dir"]
        state = read(root / "state.json")
        row = dict(by_assignment[r["assignment_id"]])
        row["stop_reason"] = state["stop_reason"]
        row["rounds"] = []
        previous = ""
        for sid in state["submission_ids"]:
            answer_path = root / "submissions" / sid / "workspace/answer.txt"
            answer = answer_path.read_text()
            score = read(root / "rubric-evaluations" / (sid + ".json"))
            rubric_hash = score["feedback_reference"]["rubric_sha256"]
            judgment_path = root / "judgments" / sid / rubric_hash / "evaluation.json"
            judgment = read(judgment_path)
            record = index.get((r["task_id"], rubric_hash, hashlib.sha256(answer.encode()).hexdigest()))
            independent = read(Path(record["evaluation_path"])) if record else None
            row["rounds"].append({
                "sid": sid, "answer_path": str(answer_path), "answer": answer,
                "word_count": len(answer.split()), "W": score["reference_score"],
                "active_composite": score["score"], "active_judge": score["judge_score"],
                "elicited_penalty": score["elicited_penalty"],
                "W_criteria": judgment["criteria"], "W_reasoning": judgment["reasoning"],
                "W_evaluation_path": str(judgment_path),
                "S": independent["total_score"] if independent else None,
                "S_criteria": independent["criteria"] if independent else None,
                "S_evaluation_path": record["evaluation_path"] if record else None,
                "diff": "".join(unified_diff(previous.splitlines(True), answer.splitlines(True), fromfile="previous", tofile=sid)) if previous else "",
            })
            previous = answer
        row["accepted_criteria"] = []
        for path in sorted((root / "rubric-generations").glob("*/evolution.json")):
            e = read(path)
            for c in read(path.parent / "criteria.json"):
                if c["criterion_id"] in e["accepted_candidate_ids"]:
                    row["accepted_criteria"].append({"generation": path.parent.name, **c})
        rows.append(row)
    groups = defaultdict(list)
    for row in rows:
        groups[(row["task_id"], row["condition_id"])].append(row)
    return {
        "experiment_id": result["experiment_id"],
        "task_conditions": [{"task": t, "condition": c,
            "initial": {k: mean(r["initial"][k] for r in rs) for k in ("W", "S", "H", "A")},
            "final": {k: mean(r["final"][k] for r in rs) for k in ("W", "S", "H", "A")},
            "W_curve": [mean(r["W_curve"][i] for r in rs) for i in range(4)],
            "mean_words": [mean(r["rounds"][min(i,len(r["rounds"])-1)]["word_count"] for r in rs) for i in range(4)]
        } for (t,c),rs in groups.items()],
        "final_W_vs_S": dict(Counter("W<S" if r["final"]["W"] < r["final"]["S"] else "W>S" if r["final"]["W"] > r["final"]["S"] else "equal" for r in rows)),
        "stops": dict(Counter(r["stop_reason"] for r in rows)),
        "assignments": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, default=CONFIG)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = inspect(args.experiment)
    dest = args.output
    dest.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps({k:v for k,v in result.items() if k != "assignments"}, indent=2))
