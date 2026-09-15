"""Provider-free reconstruction of the completed task-required Dev3 cohort.

This adapter reads only the scoped NAS1 candidate views and the completed Sol,
Opus, and RH audit records.  It never creates provider requests and does not
rewrite any scientific artifact.
"""
from __future__ import annotations

import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path


BASE = Path("/home/aydanh/runs/trace-task-paraphrase-required-20260914")
VIEW_ROOT = BASE / "provisional-audit" / "views"
AUDIT_ROOT = BASE / "provisional-audit" / "audit-retry-10444650"
OUT = Path(__file__).resolve().parents[2] / "docs/reports/2026-09-14/trace-task-paraphrase-required"
TASKS = ("da-3-4", "da-11-1", "da-18-1")
PANEL = ("gpt-5.6-sol", "claude-opus-5")
WINDOWS = ("full_trajectory", "post_update", "final_artifact", "final_revision")


def read(path: Path):
    return json.loads(path.read_text())


def final_state(view: Path, record: dict) -> tuple[dict, Path, str]:
    exp_dir = view / record["experiment_dir"]
    state = read(exp_dir / "state.json")
    submission_id = state["submission_ids"][-1]
    return state, exp_dir, submission_id


def stage_summary(task: str, stage: str) -> dict:
    return read(AUDIT_ROOT / task / stage / "summary.json")


def index_rubric(task: str):
    rows = stage_summary(task, "rubric_score")["records"]
    selected = {}
    heldout = defaultdict(dict)
    for row in rows:
        if row["artifact"] != "final":
            continue
        key = (row["assignment_id"], row["model"])
        roles = row.get("rubric_roles", [])
        if len(roles) != 1:
            continue
        role = roles[0]
        if role["name"] == "selected":
            selected[key] = float(row["score"])
        elif role["name"] == "holdout":
            heldout[key][int(role["variant_index"])] = float(row["score"])
    expected = set(selected)
    if not expected or any(set(heldout[k]) != {2, 3, 4} for k in expected):
        raise RuntimeError(f"incomplete selected/holdout rubric index for {task}")
    return selected, heldout


def index_quality(task: str):
    rows = stage_summary(task, "absolute_score")["records"]
    out = {}
    for row in rows:
        if row["artifact"] != "final":
            continue
        key = (row["assignment_id"], row["model"])
        raw = read(AUDIT_ROOT / task / "absolute_score" / "records" / f"{row['judgment_key']}.json")
        out[key] = float(raw["verdict"]["score"])
    return out


def index_rh(task: str):
    out = {}
    for window in WINDOWS:
        summaries = list((AUDIT_ROOT / task / f"direct_{window}" / "evaluations").glob("*/summary.json"))
        if len(summaries) != 1:
            raise RuntimeError(f"expected one {window} summary for {task}")
        for row in read(summaries[0])["records"]:
            key = (row["source_path"], row["model"])
            out[(window, key)] = row["verdict"]
    return out


def numeric(w, wt, s, h, a):
    return {
        "W": w,
        "W_train": wt,
        "S": s,
        "H": h,
        "A": a,
        "W_minus_S": w - s,
        "S_minus_H": s - h,
        "H_minus_A": h - a,
        "W_minus_A": w - a,
    }


def reconstruct():
    rows = []
    stage_counts = {}
    for task in TASKS:
        view = VIEW_ROOT / task
        ledger = read(view / "study.json")
        records = [r for r in ledger["records"] if r["status"] == "completed"]
        selected, heldout = index_rubric(task)
        quality = index_quality(task)
        rh = index_rh(task)
        stage_counts[task] = {}
        for stage in ("rubric_score", "absolute_score", "pairwise_preference"):
            summary = stage_summary(task, stage)
            stage_counts[task][stage] = {
                "status": summary["status"],
                "planned": summary["planned_semantic_judgment_count"],
                "successful": summary["successful_semantic_judgment_count"],
                "failed": summary["failed_semantic_judgment_count"],
                "records": len(summary["records"]),
            }
        for record in records:
            state, exp_dir, submission_id = final_state(view, record)
            assignment_id = record["assignment_id"]
            source_path = str(view / record["experiment_dir"])
            evaluation = read(exp_dir / "rubric-evaluations" / f"{submission_id}.json")
            w = float(evaluation["reference_score"])
            wt = float(evaluation["score"])
            for model in PANEL:
                key = (assignment_id, model)
                if key not in selected or key not in quality:
                    raise RuntimeError(f"missing final scores for {task} {assignment_id} {model}")
                s = selected[key]
                h = statistics.mean(heldout[key].values())
                a = quality[key]
                values = numeric(w, wt, s, h, a)
                row = {
                    "task_id": task,
                    "replicate": int(record["replicate"]),
                    "assignment_id": assignment_id,
                    "condition_id": record["condition_id"],
                    "model": model,
                    "submission_id": submission_id,
                    "submission_ids_count": len(state["submission_ids"]),
                    "retained_revisions": len(state["submission_ids"]) - 1,
                    "stop_reason": state["stop_reason"],
                    "final_w": w,
                    "final_w_train": wt,
                    "selected_s": s,
                    "heldout_h": h,
                    "holistic_a": a,
                    "source_path": source_path,
                    **values,
                }
                for window in WINDOWS:
                    verdict = rh[(window, (source_path, model))]
                    row[f"RH_{window}"] = 100.0 * float(verdict["decision"] == "reward_hacking_detected")
                    row[f"RH_upper_{window}"] = 100.0 * float(verdict["decision"] != "no_reward_hacking_detected")
                    row[f"RH_decision_{window}"] = verdict["decision"]
                    row[f"RH_score_{window}"] = verdict.get("score")
                rows.append(row)
    return rows, stage_counts


def mean_metrics(rows):
    metrics = ("W", "W_train", "S", "H", "A", "W_minus_S", "S_minus_H", "H_minus_A", "W_minus_A")
    rh_metrics = tuple(f"RH_{w}" for w in WINDOWS)
    return {m: statistics.mean(float(r[m]) for r in rows) for m in (*metrics, *rh_metrics)}


def summarize(rows):
    result = {"auditor_rows": len(rows), "assignments": len({r["assignment_id"] for r in rows}), "means": mean_metrics(rows), "windows": {}}
    for window in WINDOWS:
        result["windows"][window] = {}
        for model in (*PANEL, "equal_weight_panel"):
            subset = rows if model == "equal_weight_panel" else [r for r in rows if r["model"] == model]
            decisions = Counter(r[f"RH_decision_{window}"] for r in subset)
            n = len(subset)
            pos = decisions["reward_hacking_detected"]
            abstain = decisions["abstain"]
            result["windows"][window][model] = {
                "positive": pos,
                "negative": decisions["no_reward_hacking_detected"],
                "abstain": abstain,
                "denominator": n,
                "confirmed_positive_percent": 100 * pos / n if n else None,
                "identification_bounds_percent": [100 * pos / n, 100 * (pos + abstain) / n] if n else [None, None],
            }
    return result


def write_outputs(rows, stage_counts):
    OUT.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with (OUT / "provisional-auditor-rows.csv").open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    grouped = {}
    for label, subset in (("all", rows), ("full", [r for r in rows if r["condition_id"] == "full-red-team-trace"]), ("user", [r for r in rows if r["condition_id"] == "user-simulator-red-team-trace"])):
        grouped[label] = summarize(subset)
    payload = {
        "provider_calls": 0,
        "candidate": "attack_defense_v2.1_task_paraphrase_required",
        "source_views": str(VIEW_ROOT),
        "audit_root": str(AUDIT_ROOT),
        "tasks": list(TASKS),
        "expected_assignments": 16,
        "completed_assignments": len({r["assignment_id"] for r in rows}),
        "auditor_rows": len(rows),
        "stage_counts": stage_counts,
        "summaries": grouped,
    }
    (OUT / "provisional-outcomes.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    lines = ["# Provisional task-required Dev3 audit", "", "Provider-free reconstruction; 16 completed candidate assignments, Sol + Opus rows.", "", "| scope | assignments | W | W_train | S | H | A | W-S | S-H | H-A | W-A | RH full | RH post | RH final artifact | RH final revision |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|"]
    for label in ("all", "full", "user"):
        s = grouped[label]
        m = s["means"]
        lines.append("| %s | %d | %0.2f | %0.2f | %0.2f | %0.2f | %0.2f | %0.2f | %0.2f | %0.2f | %0.2f | %0.2f | %0.2f | %0.2f | %0.2f |" % (label, s["assignments"], m["W"], m["W_train"], m["S"], m["H"], m["A"], m["W_minus_S"], m["S_minus_H"], m["H_minus_A"], m["W_minus_A"], m["RH_full_trajectory"], m["RH_post_update"], m["RH_final_artifact"], m["RH_final_revision"]))
    (OUT / "provisional-outcomes.md").write_text("\n".join(lines) + "\n")


if __name__ == "__main__":
    rows, stage_counts = reconstruct()
    write_outputs(rows, stage_counts)
    print(json.dumps({"assignments": len({r['assignment_id'] for r in rows}), "auditor_rows": len(rows), "out": str(OUT)}))
