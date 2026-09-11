"""Provider-free forensic extraction for the v2.1 User calibration cases.

This reads only sealed Result20 records and writes compact evidence tables.  It
does not instantiate providers or call the experiment pipeline.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

RUN = Path("/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20/study/biomnibench-da-factorial-r10-5115fffdd1c0/experiments")
OUT = Path("/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/docs/reports/2026-09-11/trace-attack-defense-v3")
TARGETS = ("da-15-1", "da-13-6", "da-18-5", "da-19-1", "da-15-2", "da-12-4", "da-14-8")
CONTROLS = ("da-14-1", "da-12-2", "da-15-7", "da-19-6")
ALL_TASKS = TARGETS + CONTROLS
STATIC_CASES = Path("/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/docs/reports/2026-09-11/trace-attack-defense-v2.1/case-differences-vs-static.csv")
TASK_GAPS = Path("/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2/docs/reports/2026-09-11/trace-attack-defense-v2.1/task-gap-contributors.csv")


def sha(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as f:
        for block in iter(lambda: f.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def read(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def workspace_text(root: Path, sid: str) -> tuple[str, dict[str, str | None]]:
    w = root / "submissions" / sid / "workspace"
    chunks: list[str] = []
    hashes: dict[str, str | None] = {}
    for name in ("answer.txt", "trace.md"):
        p = w / name
        hashes[name] = sha(p)
        if p.is_file():
            chunks.append(f"\n===== {name} =====\n" + p.read_text(encoding="utf-8", errors="replace"))
    # Include any other scored public files deterministically, while keeping
    # the report compact by recording their hashes rather than whole contents.
    for p in sorted(w.rglob("*")) if w.is_dir() else ():
        if p.is_file() and str(p.relative_to(w)) not in {"answer.txt", "trace.md"}:
            hashes[str(p.relative_to(w))] = sha(p)
    return "".join(chunks), hashes


def concern_rows(output: Any) -> list[dict[str, Any]]:
    if not isinstance(output, dict):
        return []
    return output.get("concerns", []) if isinstance(output.get("concerns"), list) else []


def classify(*, dynamic: dict[str, Any] | None, concerns: list[dict[str, Any]], diff: str, delta_s: float | None, delta_a: float | None, delta_w: float | None) -> tuple[str, str]:
    # This is a reproducible evidence taxonomy, not a causal model.  The
    # report preserves the inputs used for each classification.
    texts = " ".join(str(c.get("feedback", "")) for c in concerns).casefold()
    diff_lower = diff.casefold()
    if delta_s is None or delta_s >= 0:
        return "NO_REGRESSION", "selected quality did not decline on the saved paired row"
    base_terms = ("requirement", "table", "requested", "output", "result", "analysis")
    removal_terms = ("cannot", "unable", "not run", "unavailable", "limitation", "insufficient", "omit", "remove", "deleted")
    if dynamic and dynamic.get("corrective") is False and any(t in texts for t in base_terms):
        return "DYNAMIC_OVERSTEER", "proactive learned reminder co-occurred with a quality decline; inspect preserved-output diff"
    if any(t in diff_lower for t in removal_terms):
        return "VALID_WORK_REMOVED", "saved revision diff contains withdrawal/omission language alongside a selected-quality decline"
    if any(t in texts for t in ("limitation", "cannot complete", "not possible", "not available")):
        return "LIMITATION_OVERUSED", "feedback or revision records a limitation/refusal pattern with a selected-quality decline"
    if any(t in texts for t in ("scope", "subset", "method", "estimator", "cohort")):
        return "METHOD_OR_SCOPE_DRIFT", "feedback/diff references method or scope while selected quality declines"
    if delta_a is not None and delta_a > 0 and delta_s < 0:
        return "WEAK_STRONG_DISAGREEMENT", "A improved while strong selected quality declined"
    return "OTHER_UNCLEAR", "no deterministic primary mechanism signal in saved text; retain for manual review"


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    paired: dict[tuple[str, int], dict[str, Any]] = {}
    with STATIC_CASES.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["arm"] == "user" and row["task_id"] in ALL_TASKS:
                paired[(row["task_id"], int(row["replicate"]))] = row
    task_gap: dict[str, dict[str, Any]] = {}
    with TASK_GAPS.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row["arm"] == "user" and row["task_id"] in ALL_TASKS:
                task_gap[row["task_id"]] = row

    rows: list[dict[str, Any]] = []
    detailed: list[dict[str, Any]] = []
    case_summaries: list[dict[str, Any]] = []
    for task in ALL_TASKS:
        for rep in range(1, 4):
            root = RUN / task / f"rep-{rep:03d}" / "luna" / "user-simulator-red-team-trace"
            if not root.is_dir():
                detailed.append({"task_id": task, "replicate": rep, "missing_root": str(root)})
                continue
            submissions = sorted((root / "submissions").glob("s[0-9][0-9][0-9]"))
            case = paired.get((task, rep), {})
            case_rows: list[dict[str, Any]] = []
            for sp in submissions:
                sid = sp.name
                fb_path = root / "feedback" / f"{sid}.json"
                fg_path = root / "feedback-generations" / f"{sid}.json"
                rem_path = root / "trace-defense-reminders" / f"{sid}.json"
                turn_path = root / "turns" / f"turn-{int(sid[1:]) + 1:03d}" / "prompt.txt"
                before, before_hashes = workspace_text(root, sid)
                next_sid = f"s{int(sid[1:]) + 1:03d}"
                after, after_hashes = workspace_text(root, next_sid) if (root / "submissions" / next_sid).is_dir() else ("", {})
                diff = "".join(__import__("difflib").unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile=sid, tofile=next_sid)) if after else ""
                fb = read(fb_path) if fb_path.is_file() else {}
                fg = read(fg_path) if fg_path.is_file() else {}
                rem = read(rem_path) if rem_path.is_file() else {}
                sel = rem.get("selection") if isinstance(rem, dict) else None
                concerns = concern_rows(fb)
                # The full simulator output is retained by feedback-generations;
                # keeping it in JSON makes the decision auditable without a call.
                row = {
                    "task_id": task, "replicate": rep, "submission_id": sid,
                    "root": str(root), "feedback_path": str(fb_path), "feedback_sha256": sha(fb_path),
                    "feedback_decision": fb.get("decision"), "concern_count": len(concerns),
                    "concerns": concerns, "feedback_generation_path": str(fg_path),
                    "simulator_output": fg.get("output"), "simulator_request": fg.get("feedback_generation", {}).get("request_parameters") if isinstance(fg.get("feedback_generation"), dict) else None,
                    "reminder_path": str(rem_path), "reminder_sha256": sha(rem_path), "selection": sel,
                    "reminder_message": rem.get("message_component", ""), "turn_prompt_path": str(turn_path), "turn_prompt_sha256": sha(turn_path),
                    "before_hashes": before_hashes, "after_hashes": after_hashes,
                    "before_to_after_changed": before_hashes != after_hashes,
                    "diff_excerpt": diff[:8000], "diff_chars": len(diff),
                    "generation_round": fg.get("generation_round"), "generation_sha256": fg.get("generation_sha256"),
                    "delta_W": float(case["delta_W"]) if case.get("delta_W") else None,
                    "delta_S": float(case["delta_S"]) if case.get("delta_S") else None,
                    "delta_H": float(case["delta_H"]) if case.get("delta_H") else None,
                    "delta_A": float(case["delta_A"]) if case.get("delta_A") else None,
                    "delta_W_minus_S": float(case["delta_W_minus_S"]) if case.get("delta_W_minus_S") else None,
                    "delta_W_minus_A": float(case["delta_W_minus_A"]) if case.get("delta_W_minus_A") else None,
                }
                row["primary_mechanism"], row["mechanism_basis"] = classify(dynamic=sel, concerns=concerns, diff=diff, delta_s=row["delta_S"], delta_a=row["delta_A"], delta_w=row["delta_W"])
                case_rows.append(row)
                rows.append({k: row[k] for k in ("task_id", "replicate", "submission_id", "generation_round", "feedback_decision", "concern_count", "selection", "before_to_after_changed", "diff_chars", "delta_W", "delta_S", "delta_A", "delta_W_minus_S", "delta_W_minus_A", "primary_mechanism", "mechanism_basis", "feedback_path", "reminder_path", "turn_prompt_path")})
            selected = [r for r in case_rows if r.get("selection")]
            concerns = sum(int(r.get("concern_count") or 0) for r in case_rows)
            diff_text = "\n".join(str(r.get("diff_excerpt", "")) for r in case_rows).casefold()
            removal_markers = ("unable", "cannot", "not possible", "not available", "omitted", "remove", "deleted", "refusal", "limitation")
            drift_markers = ("subset", "cohort", "method", "estimator", "scope", "proxy")
            case_summaries.append({
                "task_id": task, "replicate": rep, "root": str(root),
                "delta_W": float(case["delta_W"]) if case.get("delta_W") else None,
                "delta_S": float(case["delta_S"]) if case.get("delta_S") else None,
                "delta_H": float(case["delta_H"]) if case.get("delta_H") else None,
                "delta_A": float(case["delta_A"]) if case.get("delta_A") else None,
                "delta_W_minus_S": float(case["delta_W_minus_S"]) if case.get("delta_W_minus_S") else None,
                "delta_W_minus_A": float(case["delta_W_minus_A"]) if case.get("delta_W_minus_A") else None,
                "turn_count": len(case_rows), "concern_count": concerns,
                "dynamic_selected_turn_count": len(selected),
                "proactive_dynamic_turns": [r["submission_id"] for r in selected if not r["selection"].get("corrective")],
                "corrective_dynamic_turns": [r["submission_id"] for r in selected if r["selection"].get("corrective")],
                "dynamic_criterion_ids": [r["selection"].get("criterion_id") for r in selected],
                "max_concerns_seen": max((int(r.get("concern_count") or 0) for r in case_rows), default=0),
                "removal_signal_in_saved_diff": any(marker in diff_text for marker in removal_markers),
                "method_scope_signal_in_saved_diff": any(marker in diff_text for marker in drift_markers),
                "feedback_paths": [r["feedback_path"] for r in case_rows],
                "reminder_paths": [r["reminder_path"] for r in selected],
                "prompt_paths": [r["turn_prompt_path"] for r in selected],
            })
            detailed.append({"task_id": task, "replicate": rep, "root": str(root), "task_gap": task_gap.get(task), "submissions": case_rows})

    (OUT / "user-calibration-forensics.json").write_text(json.dumps({"run_root": str(RUN), "targets": list(TARGETS), "controls": list(CONTROLS), "rows": rows, "case_summaries": case_summaries, "cases": detailed}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    fields = list(rows[0]) if rows else []
    with (OUT / "user-calibration-forensics.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})
    case_fields = list(case_summaries[0]) if case_summaries else []
    with (OUT / "user-calibration-case-summary.csv").open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=case_fields)
        writer.writeheader()
        for row in case_summaries:
            writer.writerow({k: json.dumps(v, ensure_ascii=False) if isinstance(v, (dict, list)) else v for k, v in row.items()})
    (OUT / "user-calibration-case-summary.json").write_text(json.dumps(case_summaries, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["primary_mechanism"]] = counts.get(row["primary_mechanism"], 0) + 1
    report = [
        "# User calibration forensic extraction (v2.1)", "", 
        f"Saved Result20 root: `{RUN}`.",
        "This provider-free extraction reads sealed feedback, simulator-generation receipts, reminder receipts, prompts, public workspaces, and paired v2.1 case scores. It makes no model calls and does not relabel official scores.", "",
        "## Scope", "", f"Target tasks: {', '.join(TARGETS)}. Positive controls: {', '.join(CONTROLS)}. Rows: {len(rows)} turn records across {len(detailed)} task-replicates.", "",
        "## Preliminary evidence taxonomy counts", "", "| classification | turn records |", "|---|---:|",
    ] + [f"| {k} | {v} |" for k, v in sorted(counts.items())] + [
        "", "The machine-readable JSON retains exact paths, hashes, concern text, selected reminder metadata, prompt hashes, before/after workspace hashes, and bounded unified-diff excerpts. The case-summary companion preserves per-task/replicate deltas and dynamic-delivery counts. Classifications are evidence pointers for manual review, not causal estimates.",
    ]
    (OUT / "user-calibration-forensics.md").write_text("\n".join(report) + "\n", encoding="utf-8")
    print(json.dumps({"rows": len(rows), "case_replicates": len(detailed), "classification_counts": counts, "json": str(OUT / 'user-calibration-forensics.json')}, indent=2), flush=True)


if __name__ == "__main__":
    main()
