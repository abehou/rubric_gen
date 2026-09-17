"""Provider-free census of saved enforcement decisions and actual solver exposure."""
from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
import json
from pathlib import Path


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def census(study):
    ledger = read(study / "study.json")
    rows = []
    for record in ledger["records"]:
        assignment = study / record["experiment_dir"]
        for path in sorted(assignment.glob("rubric-generations/*/evolution.json")):
            enforcement = read(path).get("task_required_enforcement")
            if not enforcement:
                continue
            response = enforcement.get("response") or {}
            sid = enforcement["source_id"].split(":")[-1]
            reminder_path = assignment / "trace-defense-reminders" / f"{sid}.json"
            reminder = read(reminder_path) if reminder_path.exists() else {}
            selection = reminder.get("selection") or {}
            turn = assignment / "turns" / f"turn-{int(sid[1:]) + 1:03d}"
            requirement = response.get("requirement", "")
            attempt_prompts = []
            for prompt in sorted(turn.glob("attempts/*.prompt.txt")):
                stream = prompt.with_name(prompt.name.replace(".prompt.txt", ".trajectory.stream.jsonl"))
                if (requirement and requirement in prompt.read_text(encoding="utf-8")
                        and stream.exists() and stream.stat().st_size > 0):
                    attempt_prompts.append(str(prompt))
            selected = selection.get("category") == 0
            next_sid = f"s{int(sid[1:]) + 1:03d}"
            next_trace = assignment / "submissions" / next_sid / "workspace" / "trace.md"
            rows.append({
                "assignment_id": record["assignment_id"],
                "assignment_status": record["status"],
                "source_submission": sid,
                "evolution_path": str(path),
                "decision": response.get("decision"),
                "requirement": requirement,
                "reason": response.get("reason"),
                "corrective_action": response.get("corrective_action"),
                "selected_category_zero": selected,
                "reminder_exists": reminder_path.exists(),
                "reminder_path": str(reminder_path),
                "skipped": reminder.get("skipped", []),
                "started_attempts_containing_requirement": attempt_prompts,
                "exposure_verified": selected and bool(attempt_prompts),
                "next_trace_path": str(next_trace) if next_trace.exists() else None,
            })
    return {
        "observed_at": datetime.now().astimezone().isoformat(),
        "study": str(study),
        "experiment_id": ledger["experiment_id"],
        "study_status": ledger["status"],
        "assignment_counts": dict(Counter(r["status"] for r in ledger["records"])),
        "decisions": dict(Counter(r["decision"] for r in rows)),
        "correct_selected": sum(r["decision"] == "correct" and r["selected_category_zero"] for r in rows),
        "correct_exposure_verified": sum(r["decision"] == "correct" and r["exposure_verified"] for r in rows),
        "correct_without_reminder_yet": sum(r["decision"] == "correct" and not r["reminder_exists"] for r in rows),
        "correct_with_reminder_but_not_selected": sum(r["decision"] == "correct" and r["reminder_exists"] and not r["selected_category_zero"] for r in rows),
        "limitation": "Exposure is verified against a started solver attempt, not proof of repair or causal score improvement. A terminal checkpoint may have no next solver turn.",
        "records": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    result = census(args.study.resolve())
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps({k: v for k, v in result.items() if k != "records"}, indent=2))
