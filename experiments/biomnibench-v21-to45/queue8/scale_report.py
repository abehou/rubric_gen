"""Provider-free Results30/45 scale reconstruction.

This reads only sealed native study/audit records.  It pairs fixed and
red-team-trace rows within task, replicate and auditor, retains all four RH
windows and emits compact scope-level tables.  Missing or invalid cells are
reported rather than silently averaged.
"""
from __future__ import annotations

import argparse
import csv
import importlib.util
import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

PANEL = ("gpt-5.6-sol", "claude-opus-5")
WINDOWS = ("full_trajectory", "post_update", "final_artifact", "final_revision")
Q6_SOURCE = Path("/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2")
Q7_SOURCE = Path("/home/aydanh/repos/rubric_gen/runs/babel-code/trace-results45-inputs-20260912")
REPORT_ROOT = Q6_SOURCE / "docs/reports/2026-09-12/biomnibench-v21-to45/queue8/scale"
Q6_TASKS = ("da-1-3", "da-19-3", "da-20-4", "da-26-2", "da-26-4",
            "da-3-5", "da-4-1", "da-4-6", "da-5-1", "da-8-1")
Q7_TASKS = ("da-1-4", "da-17-1", "da-17-3", "da-17-5", "da-19-4",
            "da-20-1", "da-24-3", "da-25-1", "da-4-7", "da-6-2",
            "da-6-5", "da-8-2", "da-8-3", "da-9-1", "da-9-7")


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot import {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def digest(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(block)
    return h.hexdigest()


def condition_name(condition_id: str) -> str:
    if condition_id in {"full-static", "full-red-team-trace"}:
        return condition_id
    raise ValueError(f"unexpected scale condition {condition_id}")


def metric_row(row: dict) -> dict:
    values = row["values"]
    result = {
        "task_id": row["task_id"], "replicate": int(row["replicate"]),
        "model": row["model"], "condition_id": condition_name(row["condition_id"]),
        "assignment_id": row["assignment_id"],
        "W": float(values["W"]), "W_train": float(values["W_train"]),
        "S": float(values["S"]), "H": float(values["H"]), "A": float(values["A"]),
        "W_minus_S": float(values["WS"]), "S_minus_H": float(values["SH"]),
        "H_minus_A": float(values["HA"]), "W_minus_A": float(values["WA"]),
        "state_path": row["state_path"], "state_sha256": row["state_sha256"],
    }
    for window in WINDOWS:
        verdict = row["direct"][window]
        decision = verdict["decision"]
        if decision not in {"reward_hacking_detected", "no_reward_hacking_detected", "abstain"}:
            raise ValueError(f"unexpected RH decision {decision}")
        result[f"RH_{window}"] = 100.0 if decision == "reward_hacking_detected" else 0.0
        result[f"RH_{window}_monitor"] = float(verdict["score"])
        result[f"RH_{window}_decision"] = decision
    return result


def summarize(rows: list[dict]) -> dict:
    if not rows or {r["model"] for r in rows} != set(PANEL):
        raise ValueError("missing Sol+Opus rows")
    by_case = defaultdict(list)
    for row in rows:
        by_case[row["task_id"], row["replicate"]].append(row)
    if any(len(v) != 2 for v in by_case.values()):
        raise ValueError("duplicated or incomplete auditor panel")
    metrics = ("W", "W_train", "S", "H", "A", "W_minus_S", "S_minus_H", "H_minus_A", "W_minus_A")
    result = {
        "auditor_rows": len(rows), "assignments": len(by_case),
        "means": {m: mean(r[m] for r in rows) for m in metrics},
        "auditors": {}, "rh": {},
    }
    for model in PANEL:
        mr = [r for r in rows if r["model"] == model]
        result["auditors"][model] = {
            "means": {m: mean(r[m] for r in mr) for m in metrics}, "rh": {},
        }
        for window in WINDOWS:
            counts = Counter(r[f"RH_{window}_decision"] for r in mr)
            result["auditors"][model]["rh"][window] = {
                "positive": counts["reward_hacking_detected"],
                "negative": counts["no_reward_hacking_detected"],
                "abstain": counts["abstain"], "denominator": len(mr),
                "confirmed_positive_percent": mean(r[f"RH_{window}"] for r in mr),
                "mean_monitor_score": mean(r[f"RH_{window}_monitor"] for r in mr),
            }
    for window in WINDOWS:
        case_decisions = []
        for case in by_case.values():
            decisions = {r["model"]: r[f"RH_{window}_decision"] for r in case}
            positive = any(v == "reward_hacking_detected" for v in decisions.values())
            abstain = not positive and any(v == "abstain" for v in decisions.values())
            case_decisions.append("reward_hacking_detected" if positive else "abstain" if abstain else "no_reward_hacking_detected")
        counts = Counter(case_decisions)
        result["rh"][window] = {
            "positive": counts["reward_hacking_detected"], "negative": counts["no_reward_hacking_detected"],
            "abstain": counts["abstain"], "denominator": len(case_decisions),
            "confirmed_positive_percent": 100 * counts["reward_hacking_detected"] / len(case_decisions),
            "identification_bounds_percent": [100 * counts["reward_hacking_detected"] / len(case_decisions),
                                               100 * (counts["reward_hacking_detected"] + counts["abstain"]) / len(case_decisions)],
        }
    return result


def bootstrap(values: list[float], task_labels: list[str], draws: int = 10_000, seed: int = 20260910) -> dict:
    import numpy as np
    tasks = sorted(set(task_labels))
    per_task = [mean(v for v, t in zip(values, task_labels) if t == task) for task in tasks]
    rng = np.random.default_rng(seed)
    samples = np.asarray(per_task)[rng.integers(0, len(per_task), size=(draws, len(per_task)))].mean(axis=1)
    return {"mean": float(mean(per_task)), "ci95": [float(x) for x in np.quantile(samples, [.025, .975])],
            "task_count": len(tasks), "draws": draws, "analysis_seed": seed}


def locate_study(exp, condition_source: Path) -> tuple[Path, Path]:
    def expanded(stage: str) -> Path:
        raw = str(exp.dag[stage]["output_dir"])
        return Path(raw.replace("{experiment_id}", exp.experiment_id))
    study, audit = expanded("revise"), expanded("detect")
    if not study.is_dir() or not audit.is_dir():
        raise FileNotFoundError(f"missing study/audit for {condition_source}: {study} {audit}")
    return study, audit


def reconstruct_scope(scope: str) -> tuple[dict, list[dict], list[dict]]:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("scale reconstruction must run on a compute node")
    source, tasks = (Q6_SOURCE, Q6_TASKS) if scope == "results30" else (Q7_SOURCE, Q7_TASKS)
    report_module = load_module("scale_report_reconstruct", Q6_SOURCE / "experiments/trace-attack-defense-v21/report/report_reconstruct.py")
    sys.path.insert(0, str(source / "src"))
    from rubric_gen.submission_revision.experiment import load_experiment
    all_rows, coverage, errors = [], [], []
    for task in tasks:
        config = source / "experiments/biomnibench-v21-to45" / ("queue6" if scope == "results30" else "queue7") / "configs" / f"{task}.yaml"
        try:
            exp = load_experiment(config)
            study, audit = locate_study(exp, config)
            cov, rows = report_module.reconstruct(study, audit, PANEL)
            coverage.append({"task": task, "coverage": cov, "study": str(study), "audit": str(audit),
                             "study_manifest_sha256": digest(study / "manifest.json") if (study / "manifest.json").is_file() else None})
            all_rows.extend(metric_row(r) for r in rows)
        except Exception as exc:
            errors.append({"task": task, "type": type(exc).__name__, "error": str(exc), "config": str(config)})
    return {"scope": scope, "expected_tasks": len(tasks), "coverage": coverage, "errors": errors}, all_rows, tasks


def write_scope(scope: str) -> dict:
    inventory, rows, tasks = reconstruct_scope(scope)
    cells = {}
    for condition in ("full-static", "full-red-team-trace"):
        selected = [r for r in rows if r["condition_id"] == condition]
        if len(selected) != len(tasks) * 3 * len(PANEL):
            inventory.setdefault("incomplete_cells", []).append({"condition": condition, "rows": len(selected)})
            continue
        cells[condition] = summarize(selected)
    contrasts = {}
    by_key = {(r["task_id"], r["replicate"], r["model"], r["condition_id"]): r for r in rows}
    for metric in ("W", "W_train", "S", "H", "A", "W_minus_S", "S_minus_H", "H_minus_A", "W_minus_A"):
        vals, labels = [], []
        for task in tasks:
            for rep in (1, 2, 3):
                for model in PANEL:
                    a = by_key.get((task, rep, model, "full-red-team-trace"))
                    b = by_key.get((task, rep, model, "full-static"))
                    if a is not None and b is not None:
                        vals.append(a[metric] - b[metric]); labels.append(task)
        if vals:
            contrasts[metric] = bootstrap(vals, labels)
    result = {**inventory, "rows": len(rows), "cells": cells, "contrasts_trace_minus_fixed": contrasts,
              "panel": list(PANEL), "windows": list(WINDOWS), "source_script_sha256": digest(Path(__file__))}
    out = REPORT_ROOT / scope
    out.mkdir(parents=True, exist_ok=True)
    (out / "summary.json").write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n")
    fields = ["task_id", "replicate", "model", "condition_id", "assignment_id", "W", "W_train", "S", "H", "A",
              "W_minus_S", "S_minus_H", "H_minus_A", "W_minus_A"] + [f"RH_{w}" for w in WINDOWS] + [f"RH_{w}_monitor" for w in WINDOWS]
    with (out / "artifact-auditor-values.csv").open("w", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=fields); writer.writeheader(); writer.writerows({k: r.get(k) for k in fields} for r in rows)
    print(json.dumps({"scope": scope, "rows": len(rows), "cells": list(cells), "errors": inventory["errors"]}), flush=True)
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("scope", choices=("results30", "results45"))
    args = parser.parse_args()
    write_scope(args.scope)


if __name__ == "__main__":
    main()
