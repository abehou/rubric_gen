"""Provider-free paired forensic extraction for the v2.1/v3 stress cohort.

The script reads sealed revision records, User-simulator receipts, reminder
receipts, public workspaces and completed Sol+Opus audit records.  It never
creates a provider request and does not relabel endpoint judgments.
"""
from __future__ import annotations

import argparse
import csv
import difflib
import hashlib
import importlib.util
import json
import re
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/stress-iter1")
OUT = ROOT / "docs/reports/2026-09-11/trace-attack-defense-v3"
TASKS = ("da-15-1", "da-13-6", "da-18-5")


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str | None:
    if not path.is_file():
        return None
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def public_text(root: Path, sid: str) -> tuple[str, dict[str, str]]:
    workspace = root / "submissions" / sid / "workspace"
    pieces: list[str] = []
    hashes: dict[str, str] = {}
    for path in sorted(workspace.rglob("*")) if workspace.is_dir() else ():
        if path.is_file():
            rel = str(path.relative_to(workspace))
            hashes[rel] = digest(path) or ""
            if rel in {"answer.txt", "trace.md"}:
                pieces.append(f"\n===== {rel} =====\n")
                pieces.append(path.read_text(encoding="utf-8", errors="replace"))
    return "".join(pieces), hashes


def read_optional(path: Path) -> dict[str, Any]:
    return load_json(path) if path.is_file() else {}


def assignment_root(flavor: str, task: str, replicate: int) -> Path:
    # StudyRunner places assignment directories below the sealed
    # ``study/<experiment_id>/experiments`` root, not directly below the
    # task directory.  Resolve that native layout deterministically.
    matches = sorted((RUN / flavor / task / "study").glob(f"*/experiments/{task}/rep-{replicate:03d}/luna/user-simulator-red-team-trace"))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise RuntimeError(f"ambiguous stress assignment roots for {flavor}/{task}/rep-{replicate}: {matches}")
    # Keep the missing-root path explicit for an incomplete/malformed cohort;
    # callers will preserve that fact instead of inventing evidence.
    return RUN / flavor / task / f"rep-{replicate:03d}" / "luna" / "user-simulator-red-team-trace"


def load_outcome_rows(cohort: str) -> dict[tuple[str, str, int], dict[str, Any]]:
    """Load paired score/RH rows from the report adapter when available."""
    report = OUT / f"{cohort}-outcomes" / "outcomes.json"
    if not report.is_file():
        return {}
    # The report summary is intentionally aggregate; reconstruct row-level
    # values with the same read-only adapter to retain task/replicate pairing.
    path = BUNDLE / "report_dev3_outcomes.py"
    spec = importlib.util.spec_from_file_location("trace_v3_outcomes", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    out: dict[tuple[str, str, int], dict[str, Any]] = {}
    dirs = {
        "v21": BUNDLE / "stress",
        "v3": BUNDLE / "stress",
    }
    for flavor, prefix in (("v21", "v21-control"), ("v3", "v3-candidate")):
        for task in TASKS:
            cfg = dirs[flavor] / f"{prefix}-{task}.yaml"
            _, _, rows = module.reconstruct(cfg)
            grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                grouped[(row["task_id"], int(row["replicate"]))].append(row)
            for key, values in grouped.items():
                # Same score values are present for both auditors; RH retains
                # individual decisions for the paired audit evidence.
                first = values[0]
                row = {"values": dict(first["values"]), "direct": {}}
                for window in first["direct"]:
                    row["direct"][window] = {
                        "decisions": [v["direct"][window]["decision"] for v in values],
                        "scores": [v["direct"][window].get("score") for v in values],
                    }
                out[(flavor, key[0], key[1])] = row
    return out


def scan_application_states(root: Path) -> Counter[str]:
    counts: Counter[str] = Counter()
    for path in root.rglob("*.json"):
        try:
            value = load_json(path)
        except Exception:
            continue
        if isinstance(value, dict):
            applicability = value.get("applicability")
            if isinstance(applicability, str):
                counts[applicability] += 1
            # Preserve explicit native rejection reasons when present.
            for key in ("rejection_reason", "reason", "status", "decision"):
                item = value.get(key)
                if isinstance(item, str) and any(token in item.casefold() for token in ("undecidable", "support", "margin", "semantic", "redundant", "duplicate")):
                    counts[f"reason:{item}"] += 1
    return counts


def classify_case(delta: dict[str, Any], turns: list[dict[str, Any]]) -> tuple[str, str]:
    if delta.get("S") is None or float(delta["S"]) >= 0:
        return "NO_REGRESSION", "paired selected-rubric score did not decline"
    all_text = " ".join(
        str(c.get("feedback", ""))
        for turn in turns
        for c in turn.get("concerns", [])
        if isinstance(c, dict)
    ).casefold()
    diff = "\n".join(str(turn.get("diff_excerpt", "")) for turn in turns).casefold()
    selected = [t for t in turns if t.get("selection")]
    if selected and any(not t["selection"].get("corrective", False) for t in selected):
        return "DYNAMIC_OVERSTEER", "a proactive selected rule competed with User concerns on a paired S decline"
    if any(term in diff for term in ("cannot", "unable", "not run", "unavailable", "omit", "remove", "deleted", "refusal")):
        return "VALID_WORK_REMOVED", "paired public-work diff contains withdrawal/omission language"
    if any(term in all_text for term in ("limitation", "cannot complete", "not possible", "not available")):
        return "LIMITATION_OVERUSED", "User concern or revision contains an explicit limitation/refusal signal"
    if any(term in (all_text + diff) for term in ("subset", "cohort", "method", "estimator", "scope")):
        return "METHOD_OR_SCOPE_DRIFT", "saved concern/diff names a method, estimator, subset or scope change"
    if delta.get("A") is not None and float(delta["A"]) > 0:
        return "WEAK_STRONG_DISAGREEMENT", "A improved while selected strong score declined"
    return "OTHER_UNCLEAR", "no deterministic primary mechanism signal"


def collect_case(flavor: str, task: str, replicate: int) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    root = assignment_root(flavor, task, replicate)
    state = read_optional(root / "state.json")
    turns: list[dict[str, Any]] = []
    submissions = sorted((root / "submissions").glob("s[0-9][0-9][0-9]"))
    for submission in submissions:
        sid = submission.name
        next_sid = f"s{int(sid[1:]) + 1:03d}"
        before, before_hashes = public_text(root, sid)
        after, after_hashes = public_text(root, next_sid) if (root / "submissions" / next_sid).is_dir() else ("", {})
        diff = "".join(difflib.unified_diff(before.splitlines(keepends=True), after.splitlines(keepends=True), fromfile=sid, tofile=next_sid)) if after else ""
        feedback_path = root / "feedback" / f"{sid}.json"
        generation_path = root / "feedback-generations" / f"{sid}.json"
        reminder_path = root / "trace-defense-reminders" / f"{sid}.json"
        feedback = read_optional(feedback_path)
        generation = read_optional(generation_path)
        reminder = read_optional(reminder_path)
        output = generation.get("output") if isinstance(generation.get("output"), dict) else {}
        turns.append({
            "submission_id": sid,
            "feedback_path": str(feedback_path),
            "feedback_sha256": digest(feedback_path),
            "feedback_decision": feedback.get("decision"),
            "concerns": output.get("concerns", []) if isinstance(output, dict) else [],
            "generation_path": str(generation_path),
            "generation_sha256": digest(generation_path),
            "trace_v3_context": generation.get("trace_v3_context"),
            "reminder_path": str(reminder_path),
            "reminder_sha256": digest(reminder_path),
            "selection": reminder.get("selection"),
            "emitted": reminder.get("emitted"),
            "concern_origin": reminder.get("concern_origin"),
            "omission_reason": reminder.get("omission_reason"),
            "solver_prompt_path": str(root / "turns" / f"turn-{int(sid[1:]) + 1:03d}" / "prompt.txt"),
            "before_hashes": before_hashes,
            "after_hashes": after_hashes,
            "diff_excerpt": diff[:6000],
            "diff_chars": len(diff),
        })
    return {"task_id": task, "replicate": replicate, "flavor": flavor, "root": str(root), "state_path": str(root / "state.json"), "state_sha256": digest(root / "state.json"), "state": state, "application_state_counts": dict(scan_application_states(root))}, turns


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(OUT / "stress-user-forensics.json"))
    args = parser.parse_args()
    outcome_rows = load_outcome_rows("stress")
    cases: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    mechanisms: Counter[str] = Counter()
    origins: Counter[str] = Counter()
    omission: Counter[str] = Counter()
    for task in TASKS:
        for replicate in range(1, 4):
            collected: dict[str, Any] = {}
            turn_data: dict[str, list[dict[str, Any]]] = {}
            for flavor in ("v21-control", "v3-candidate"):
                case, turns = collect_case(flavor, task, replicate)
                collected[flavor] = case
                turn_data[flavor] = turns
                for turn in turns:
                    if turn.get("concern_origin"):
                        origins[str(turn["concern_origin"])] += 1
                    if turn.get("omission_reason"):
                        omission[str(turn["omission_reason"])] += 1
            v21 = outcome_rows.get(("v21", task, replicate), {}).get("values", {})
            v3 = outcome_rows.get(("v3", task, replicate), {}).get("values", {})
            delta = {key: (v3.get(key) - v21.get(key)) if key in v3 and key in v21 else None for key in ("W", "W_train", "S", "H", "A", "W_minus_S", "W_minus_A", "S_minus_H", "H_minus_A")}
            label, basis = classify_case(delta, turn_data["v3-candidate"])
            mechanisms[label] += 1
            rows.append({"task_id": task, "replicate": replicate, **delta, "primary_mechanism": label, "mechanism_basis": basis, "v3_selected_turns": sum(bool(t.get("selection")) for t in turn_data["v3-candidate"]), "v3_emitted_turns": sum(bool(t.get("emitted")) for t in turn_data["v3-candidate"]), "v3_concern_count": sum(len(t.get("concerns", [])) for t in turn_data["v3-candidate"]), "v21_concern_count": sum(len(t.get("concerns", [])) for t in turn_data["v21-control"]), "v3_application_states": collected["v3-candidate"]["application_state_counts"]})
            cases.append({"task_id": task, "replicate": replicate, "delta": delta, "primary_mechanism": label, "mechanism_basis": basis, "v21": {"case": collected["v21-control"], "turns": turn_data["v21-control"]}, "v3": {"case": collected["v3-candidate"], "turns": turn_data["v3-candidate"]}})
    payload = {"provider_calls": 0, "run_root": str(RUN), "tasks": list(TASKS), "outcome_rows_available": len(outcome_rows), "mechanism_counts": dict(mechanisms), "concern_origins": dict(origins), "omission_reasons": dict(omission), "rows": rows, "cases": cases}
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    csv_path = out.with_suffix(".csv")
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        fields = list(rows[0]) if rows else ["task_id", "replicate"]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({key: json.dumps(value, ensure_ascii=False) if isinstance(value, (dict, list)) else value for key, value in row.items()})
    print(json.dumps({"provider_calls": 0, "cases": len(cases), "outcome_rows": len(outcome_rows), "mechanism_counts": dict(mechanisms), "json": str(out), "csv": str(csv_path)}, indent=2), flush=True)


if __name__ == "__main__":
    main()
