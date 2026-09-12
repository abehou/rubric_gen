"""Read-only W/S/H/A/RH reconstruction for a saved dev3 cohort.

This report adapter consumes sealed revision and audit artifacts only.  It never
creates provider requests and deliberately keeps the v2.1 and v3 cohorts as
separate inputs before computing paired, task/replicate-level differences.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "diagnostics"))
sys.path.insert(0, str(ROOT / "experiments" / "trace-attack-defense-v21" / "report"))

from check_audit_coverage import WINDOWS, check, source_records  # noqa: E402
from artifact_locations import recorded_root  # noqa: E402

PANEL = ("gpt-5.6-sol", "claude-opus-5")
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911")
BUNDLE = ROOT / "experiments" / "trace-attack-defense-v3"


def read(path: Path):
    return json.loads(path.read_text())


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def numeric_scores(W, train, S, H, A):
    values = (W, train, S, H, A)
    assert all(isinstance(v, (int, float)) and not isinstance(v, bool) and 0 <= v <= 100 for v in values)
    return {
        "W": W,
        "W_train": train,
        "S": S,
        "H": H,
        "A": A,
        "W_minus_S": W - S,
        "W_minus_A": W - A,
        "S_minus_H": S - H,
        "H_minus_A": H - A,
    }


def reconstruct(config_path: Path):
    from rubric_gen.submission_revision.experiment import load_experiment

    experiment = load_experiment(config_path)
    study = Path(experiment.dag["revise"]["output_dir"])
    audit = Path(experiment.dag["detect"]["output_dir"])
    coverage = check(study, audit, expected_models=PANEL)
    assignments = source_records(study)
    original = recorded_root(study)

    rubric_refs = defaultdict(dict)
    for ref in read(audit / "rubric_score" / "summary.json")["records"]:
        key = (ref["assignment_id"], ref["model"], ref["artifact"])
        raw_path = audit / "rubric_score" / "records" / f"{ref['judgment_key']}.json"
        raw = read(raw_path)
        for role in ref["rubric_roles"]:
            role_key = (role["name"], role["variant_index"])
            assert role_key not in rubric_refs[key]
            rubric_refs[key][role_key] = (ref, raw, raw_path)

    quality_refs = {}
    for ref in read(audit / "absolute_score" / "summary.json")["records"]:
        key = (ref["assignment_id"], ref["model"], ref["artifact"])
        assert key not in quality_refs
        raw_path = audit / "absolute_score" / "records" / f"{ref['judgment_key']}.json"
        quality_refs[key] = (ref, read(raw_path), raw_path)

    direct = {}
    for window in WINDOWS:
        summary_path = next((audit / f"direct_{window}" / "evaluations").glob("*/summary.json"))
        direct[window] = {
            (row["source_path"], row["model"]): row for row in read(summary_path)["records"]
        }

    rows = []
    for assignment in assignments:
        assignment_id = assignment["assignment_id"]
        exp_dir = study / assignment["experiment_dir"]
        state = read(exp_dir / "state.json")
        submission_id = state["submission_ids"][-1]
        eval_path = exp_dir / "rubric-evaluations" / f"{submission_id}.json"
        evaluation = read(eval_path)
        assert evaluation["kind"] == "selected-base-plus-active-penalties-v1"
        assert evaluation["submission_id"] == submission_id
        assert evaluation["score"] == state["scores"][-1]
        assert evaluation["canonical_original_score"] == state["fixed_original_scores"][-1]

        reference = evaluation["feedback_reference"]
        weak_root = exp_dir / "judgments" / submission_id / reference["rubric_sha256"]
        weak_validation = weak_root / "score_validation.json"
        weak_evaluation = weak_root / "evaluation.json"
        assert digest(weak_validation) == reference["score_validation_sha256"]
        assert digest(weak_evaluation) == reference["evaluation_sha256"]
        weak_score = read(weak_validation)["score"]
        # The score binding is stored on the native rubric-evaluation object;
        # feedback_reference itself contains only hashes and rubric identity.
        # Keep this adapter read-only across v2.1/v3 records.
        reference_score = evaluation.get("reference_score")
        if not isinstance(reference_score, (int, float)):
            raise ValueError("rubric evaluation lacks its native reference score")
        assert weak_score == read(weak_evaluation)["total_score"] == reference_score
        assert evaluation["score"] == max(0, weak_score + evaluation["elicited_penalty"])

        for model in PANEL:
            observed = rubric_refs[assignment_id, model, "final"]
            selected = [value for key, value in observed.items() if key[0] == "selected"]
            heldout = [value for key, value in observed.items() if key[0] == "holdout"]
            assert len(selected) == 1 and len(heldout) == 3
            selected = selected[0]
            assert selected[1]["rubric_sha256"] == reference["rubric_sha256"]
            all_refs = [selected, *heldout, observed["original", None]]
            assert all(item[0]["submission_id"] == submission_id for item in all_refs)
            submission_hashes = {item[1]["submission_content_sha256"] for item in all_refs}
            assert len(submission_hashes) == 1
            assert len({item[1]["rubric_sha256"] for item in [selected, *heldout]}) == 4
            quality_ref, quality, quality_path = quality_refs[assignment_id, model, "final"]
            assert quality_ref["submission_id"] == submission_id
            assert quality["submission_content_sha256"] in submission_hashes
            W = reference_score
            W_train = evaluation["score"]
            S = selected[1]["score"]
            H = mean(item[1]["score"] for item in heldout)
            A = quality["verdict"]["score"]
            values = numeric_scores(W, W_train, S, H, A)
            for name, value in values.items():
                assert isinstance(value, (int, float))
            direct_values = {
                window: direct[window][str(original / assignment["experiment_dir"]), model]["verdict"]
                for window in WINDOWS
            }
            row = {
                "assignment_id": assignment_id,
                "task_id": assignment["task_id"],
                "replicate": assignment["replicate"],
                "condition_id": assignment["condition_id"],
                "model": model,
                "submission_id": submission_id,
                "submission_sha256": next(iter(submission_hashes)),
                "initial_submission_sha256": quality_refs[assignment_id, model, "initial"][1]["submission_content_sha256"],
                "selected_rubric_sha256": selected[1]["rubric_sha256"],
                "values": values,
                "direct": direct_values,
                "state_path": str(exp_dir / "state.json"),
                "score_composition_path": str(eval_path),
                "quality_path": str(quality_path),
                "retained_revisions": len(state["submission_ids"]) - 1,
                "stop_reason": state["stop_reason"],
            }
            rows.append(row)
    return experiment, coverage, rows


def add_values(row):
    values = dict(row["values"])
    for window, verdict in row["direct"].items():
        values[f"RH_{window}"] = 100.0 * float(verdict["decision"] == "reward_hacking_detected")
        values[f"RH_upper_{window}"] = 100.0 * float(verdict["decision"] != "no_reward_hacking_detected")
    return values


def summarize(rows):
    values = [add_values(row) for row in rows]
    out = {"assignments": len({(r["task_id"], r["replicate"]) for r in rows}), "auditor_rows": len(rows)}
    out["means"] = {key: mean(value[key] for value in values) for key in values[0]}
    out["windows"] = {}
    for window in WINDOWS:
        out["windows"][window] = {}
        for model in (*PANEL, "equal_weight_panel"):
            subset = rows if model == "equal_weight_panel" else [r for r in rows if r["model"] == model]
            counts = defaultdict(int)
            for row in subset:
                counts[row["direct"][window]["decision"]] += 1
            n = len(subset)
            out["windows"][window][model] = {
                "positive": counts["reward_hacking_detected"],
                "negative": counts["no_reward_hacking_detected"],
                "abstain": counts["abstain"],
                "denominator": n,
                "confirmed_positive_percent": 100.0 * counts["reward_hacking_detected"] / n if n else None,
                "identification_bounds_percent": [
                    100.0 * counts["reward_hacking_detected"] / n,
                    100.0 * (counts["reward_hacking_detected"] + counts["abstain"]) / n,
                ] if n else [None, None],
            }
    return out


def paired(left, right):
    lhs = {(r["task_id"], r["replicate"], r["model"]): r for r in left}
    rhs = {(r["task_id"], r["replicate"], r["model"]): r for r in right}
    assert lhs.keys() == rhs.keys()
    rows = []
    for key in sorted(lhs):
        a, b = lhs[key], rhs[key]
        assert a["initial_submission_sha256"] == b["initial_submission_sha256"]
        assert a["selected_rubric_sha256"] == b["selected_rubric_sha256"]
        delta = {metric: add_values(a)[metric] - add_values(b)[metric] for metric in add_values(a)}
        rows.append({"task_id": key[0], "replicate": key[1], "model": key[2], "delta": delta})
    by_task = defaultdict(list)
    for row in rows:
        by_task[row["task_id"]].append(row)
    task_means = {
        task: {metric: mean(r["delta"][metric] for r in items) for metric in items[0]["delta"]}
        for task, items in by_task.items()
    }
    aggregate = {metric: mean(row["delta"][metric] for row in rows) for metric in rows[0]["delta"]}
    return rows, {"task_means": task_means, "aggregate_auditor_row_mean": aggregate}


def write_csv(path: Path, rows):
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    fields = list(rows[0])
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("cohort", choices=("stress", "canonical"))
    parser.add_argument("--v21-config-dir", default=None)
    parser.add_argument("--v3-config-dir", default=None)
    parser.add_argument("--candidate-flavor", choices=("v3", "v31"), default="v3")
    args = parser.parse_args()
    if not __import__("os").environ.get("SLURM_JOB_ID"):
        raise RuntimeError("dev3 outcome reconstruction must run on Slurm compute storage")
    if args.v21_config_dir:
        v21_dir = Path(args.v21_config_dir)
    elif args.cohort == "stress":
        v21_dir = BUNDLE / "stress"
    else:
        v21_dir = BUNDLE / "control-v21-compatible"
    if args.v3_config_dir:
        v3_dir = Path(args.v3_config_dir)
    elif args.candidate_flavor == "v31":
        v3_dir = BUNDLE / "stress-v31"
    elif args.cohort == "stress":
        v3_dir = BUNDLE / "stress"
    else:
        v3_dir = BUNDLE / "canonical-v3"
    tasks = ("da-15-1", "da-13-6", "da-18-5") if args.cohort == "stress" else ("da-3-4", "da-11-1", "da-18-1")
    v21_rows, v3_rows, coverages = [], [], {}
    for task in tasks:
        v21_path = v21_dir / (f"v21-control-{task}.yaml" if args.cohort == "stress" else f"{task}.yaml")
        candidate_prefix = "v31-candidate" if args.candidate_flavor == "v31" else "v3-candidate"
        v3_path = v3_dir / (f"{candidate_prefix}-{task}.yaml" if args.cohort == "stress" else f"{task}.yaml")
        _, coverage, rows = reconstruct(v21_path)
        coverages[f"v21:{task}"] = coverage
        v21_rows.extend(rows)
        _, coverage, rows = reconstruct(v3_path)
        coverages[f"v3:{task}"] = coverage
        v3_rows.extend(rows)
    pair_rows, paired_summary = paired(v3_rows, v21_rows)
    suffix = "" if args.candidate_flavor == "v3" else f"-{args.candidate_flavor}"
    out_dir = ROOT / "docs" / "reports" / "2026-09-11" / "trace-attack-defense-v3" / f"{args.cohort}-outcomes{suffix}"
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "provider_calls": 0,
        "cohort": args.cohort,
        "candidate_flavor": args.candidate_flavor,
        "tasks": list(tasks),
        "panel": list(PANEL),
        "v21": summarize(v21_rows),
        "v3": summarize(v3_rows),
        "paired_v3_minus_v21": paired_summary,
        "coverage": coverages,
    }
    (out_dir / "outcomes.json").write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n")
    write_csv(out_dir / "paired-v3-minus-v21.csv", [
        {"task_id": row["task_id"], "replicate": row["replicate"], "model": row["model"], **row["delta"]}
        for row in pair_rows
    ])
    (out_dir / "README.md").write_text(
        f"# {args.cohort} {args.candidate_flavor} dev3 outcomes\n\n"
        "This is a provider-free reconstruction from sealed revision/audit artifacts. "
        f"The paired table compares attack_defense_{args.candidate_flavor} minus attack_defense_v2.1 for the same task, replicate and auditor. "
        "It does not select a candidate or claim causal mediation.\n\n"
        f"Assignments per arm: {payload['v21']['assignments']}; auditor rows per arm: {payload['v21']['auditor_rows']}.\n"
    )
    print(json.dumps({"cohort": args.cohort, "provider_calls": 0, "assignments": payload["v21"]["assignments"], "out_dir": str(out_dir)}), flush=True)


if __name__ == "__main__":
    main()
