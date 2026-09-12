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
from statistics import mean
from typing import Any

BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
RUNS = {
    "v31": Path("/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/stress-iter2"),
    "v32": Path("/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/stress-iter3"),
}
RUN = RUNS["v31"]
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
    for rel in ("answer.txt", "trace.md"):
        path = workspace / rel
        if path.is_file():
            hashes[rel] = digest(path) or ""
            pieces.append(f"\n===== {rel} =====\n")
            pieces.append(path.read_text(encoding="utf-8", errors="replace"))
    return "".join(pieces), hashes


def read_optional(path: Path) -> dict[str, Any]:
    return load_json(path) if path.is_file() else {}


def assignment_root(flavor: str, task: str, replicate: int) -> Path:
    # StudyRunner places assignment directories below the sealed
    # ``study/<experiment_id>/experiments`` root, not directly below the
    # task directory.  Resolve that native layout deterministically.
    flavor_run = RUN.parent / "stress-iter1" if flavor == "v21-control" else RUN
    matches = sorted((flavor_run / flavor / task / "study").glob(f"*/experiments/{task}/rep-{replicate:03d}/luna/user-simulator-red-team-trace"))
    if len(matches) == 1:
        return matches[0]
    if len(matches) > 1:
        raise RuntimeError(f"ambiguous stress assignment roots for {flavor}/{task}/rep-{replicate}: {matches}")
    # Keep the missing-root path explicit for an incomplete/malformed cohort;
    # callers will preserve that fact instead of inventing evidence.
    raise FileNotFoundError(f"missing sealed assignment: {flavor}/{task}/{replicate}")


def load_outcome_rows(cohort: str, candidate_flavor: str) -> dict[tuple[str, str, int], dict[str, Any]]:
    """Load paired score/RH rows from the report adapter when available."""
    report = OUT / f"{cohort}-outcomes-{candidate_flavor}" / "outcomes.json"
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
        "v3": BUNDLE / f"stress-{candidate_flavor}",
    }
    for flavor, prefix in (("v21", "v21-control"), ("v3", f"{candidate_flavor}-candidate")):
        for task in TASKS:
            cfg = dirs[flavor] / f"{prefix}-{task}.yaml"
            _, _, rows = module.reconstruct(cfg)
            grouped: dict[tuple[str, int], list[dict[str, Any]]] = defaultdict(list)
            for row in rows:
                grouped[(row["task_id"], int(row["replicate"]))].append(row)
            for key, values in grouped.items():
                # Strong/heldout/holistic scores differ by auditor. Preserve
                # the complete panel and average at assignment level.
                first = values[0]
                assert len(values) == 2 and {v["model"] for v in values} == set(module.PANEL)
                row = {"values": {metric: mean(v["values"][metric] for v in values) for metric in first["values"]}, "direct": {}}
                for window in first["direct"]:
                    row["direct"][window] = {
                        "decisions": [v["direct"][window]["decision"] for v in values],
                        "scores": [v["direct"][window].get("score") for v in values],
                    }
                out[(flavor, key[0], key[1])] = row
    return out


def collect_learning(root: Path) -> dict[str, Any]:
    """Count native generation appearances and request-unique outcomes separately."""
    counts = Counter()
    reasons = Counter()
    generation_rows = []
    for path in sorted((root / "rubric-generations").glob("generation-*/manifest.json")):
        manifest = load_json(path)
        number = manifest["generation_round"]
        if number < 2:
            continue
        directory = path.parent
        proposal = load_json(directory / "criterion-proposal.json")
        validation = load_json(directory / "criterion-validation.json")
        admission = load_json(directory / "aggregate-margins.json")
        counts["online_updates"] += 1
        counts["online_proposals"] += len(proposal["criteria"])
        counts["online_admissions"] += len(admission["accepted_candidate_ids"])
        decisions = Counter("accepted" if d["accepted"] else d["reason"] for d in admission["decisions"])
        reasons.update(decisions)
        for d in proposal.get("diagnoses", []):
            response = d.get("response")
            counts["diagnosis:" + (response["action"] if response else "unavailable")] += 1
        for review in validation.get("reviews", []):
            counts["candidate_reviews"] += 1
            counts["required_applications_appearances"] += len(review["applications"])
            for app in review["applications"]:
                value = app.get("response")
                counts["application_appearance:" + (value["applicability"] if value else "contract_unavailable")] += 1
        for item in validation.get("ineligibility", []):
            reasons[item["stage"] + ":" + item["reason"]] += 1
        generation_rows.append({"generation": number, "path": str(directory),
            "proposed": len(proposal["criteria"]), "admitted_ids": admission["accepted_candidate_ids"],
            "native_decisions": admission["decisions"], "ineligibility": validation.get("ineligibility", [])})
    for path in sorted((root / "red-team").glob("checkpoint-*/attack-record-v2.json")):
        record = load_json(path)
        counts["sidecars"] += 1
        counts["nonidentical_sidecars"] += bool(record["public_nonidentical"])
    request_counts = Counter()
    for path in sorted((root / "trace-defense-v2-requests").glob("*/result.json")):
        result = load_json(path)
        stage, outcome = result["request"]["stage"], result["outcome"]
        request_counts[stage + ":" + outcome["status"]] += 1
        value = outcome.get("value")
        if stage == "application" and value:
            request_counts["application:" + value["applicability"]] += 1
        for name, amount in result.get("accounting", {}).items():
            request_counts["accounting:" + name] += amount
    return {"counts": dict(counts), "native_and_ineligibility_reasons": dict(reasons),
            "request_unique_counts": dict(request_counts), "generations": generation_rows}


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
    state = load_json(root / "state.json")
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
        raw_concerns = output.get("concerns", [])
        effective_concerns = feedback.get("concerns", [])
        prompt_path = root / "turns" / f"turn-{int(sid[1:]) + 1:03d}" / "prompt.txt"
        turns.append({
            "submission_id": sid,
            "feedback_path": str(feedback_path),
            "feedback_sha256": digest(feedback_path),
            "feedback_decision": feedback.get("decision"),
            "concerns": raw_concerns,
            "effective_concerns": effective_concerns,
            "raw_decision": output.get("decision"),
            "raw_proactive_only_revise": bool(output.get("decision") == "revise" and raw_concerns and all(c.get("origin") == "dynamic_proactive" for c in raw_concerns)),
            "effective_proactive_only_revise": bool(feedback.get("decision") == "revise" and raw_concerns and all(c.get("origin") == "dynamic_proactive" for c in raw_concerns)),
            "has_solver_prompt": prompt_path.is_file(),
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
    return {"task_id": task, "replicate": replicate, "flavor": flavor, "root": str(root), "state_path": str(root / "state.json"), "state_sha256": digest(root / "state.json"), "state": state, "learning": collect_learning(root)}, turns


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--candidate-flavor", choices=("v31", "v32"), default="v31")
    parser.add_argument("--out", default=None)
    args = parser.parse_args()
    global RUN
    RUN = RUNS[args.candidate_flavor]
    candidate_name = f"{args.candidate_flavor}-candidate"
    outcome_rows = load_outcome_rows("stress", args.candidate_flavor)
    cases: list[dict[str, Any]] = []
    rows: list[dict[str, Any]] = []
    mechanisms: Counter[str] = Counter()
    origins: Counter[str] = Counter()
    raw_origins: Counter[str] = Counter()
    omission: Counter[str] = Counter()
    for task in TASKS:
        for replicate in range(1, 4):
            collected: dict[str, Any] = {}
            turn_data: dict[str, list[dict[str, Any]]] = {}
            for flavor in ("v21-control", candidate_name):
                case, turns = collect_case(flavor, task, replicate)
                collected[flavor] = case
                turn_data[flavor] = turns
                for turn in turns:
                    for concern in turn.get("concerns", []):
                        raw_origins[f"{flavor}:{concern.get('origin', 'legacy_unlabeled')}"] += 1
                    if turn.get("concern_origin"):
                        origins[str(turn["concern_origin"])] += 1
                    if turn.get("omission_reason"):
                        omission[str(turn["omission_reason"])] += 1
            v21 = outcome_rows.get(("v21", task, replicate), {}).get("values", {})
            v3 = outcome_rows.get(("v3", task, replicate), {}).get("values", {})
            delta = {key: (v3.get(key) - v21.get(key)) if key in v3 and key in v21 else None for key in ("W", "W_train", "S", "H", "A", "W_minus_S", "W_minus_A", "S_minus_H", "H_minus_A")}
            label, basis = classify_case(delta, turn_data[candidate_name])
            mechanisms[label] += 1
            rows.append({"task_id": task, "replicate": replicate, **delta, "primary_mechanism": label, "mechanism_basis": basis, "v3_selected_turns": sum(bool(t.get("selection")) for t in turn_data[candidate_name]), "v3_emitted_turns": sum(bool(t.get("emitted")) for t in turn_data[candidate_name]), "v3_concern_count": sum(len(t.get("concerns", [])) for t in turn_data[candidate_name]), "v3_raw_proactive_only_revisions": sum(t["raw_proactive_only_revise"] for t in turn_data[candidate_name]), "v3_effective_proactive_only_revisions": sum(t["effective_proactive_only_revise"] for t in turn_data[candidate_name]), "v21_concern_count": sum(len(t.get("concerns", [])) for t in turn_data["v21-control"]), "v3_application_states": collected[candidate_name]["learning"]["counts"]})
            cases.append({"task_id": task, "replicate": replicate, "delta": delta, "primary_mechanism": label, "mechanism_basis": basis, "v21": {"case": collected["v21-control"], "turns": turn_data["v21-control"]}, "v3": {"case": collected[candidate_name], "turns": turn_data[candidate_name]}})
    payload = {"provider_calls": 0, "run_root": str(RUN), "tasks": list(TASKS), "outcome_rows_available": len(outcome_rows), "mechanism_counts": dict(mechanisms), "concern_origins": dict(origins), "raw_concern_origins": dict(raw_origins), "classification_status": "automated triage only; primary mechanisms require manual public-evidence review", "omission_reasons": dict(omission), "rows": rows, "cases": cases}
    out = Path(args.out) if args.out else OUT / f"stress-{args.candidate_flavor}-user-forensics.json"
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
