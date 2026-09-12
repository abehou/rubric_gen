"""Provider-free closing tables from saved stress forensic/audit exports."""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path
from statistics import mean

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "docs/reports/2026-09-11/trace-attack-defense-v3"


def write_csv(name, rows):
    with (OUT / name).open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def main():
    cases = json.loads((OUT / "stress-v32-user-forensics.json").read_text())["cases"]
    summary = {"provider_calls": 0, "source": "stress-v32-user-forensics.json",
        "execution_commit": "d164a9a9a081c725465ca9cb031f816b51425add",
        "decision": "stop_after_third_unsatisfactory_stress_iteration",
        "canonical_candidate_launched": False, "result20_launched": False,
        "counting": "Request-unique counts deduplicate within native assignment caches; generation appearances include reuse. Origins are model tags, not verified provenance or compliance."}
    accounting, deliveries, native = [], [], []
    for flavor in ("v21", "v3"):
        counts, reasons, requests, delivery = Counter(), Counter(), Counter(), Counter()
        assignments_proposed = assignments_admitted = 0
        for case in cases:
            arm = case[flavor]
            record = arm["case"]
            learning = record["learning"]
            counts.update(learning["counts"])
            reasons.update(learning["native_and_ineligibility_reasons"])
            requests.update(learning["request_unique_counts"])
            assignments_proposed += learning["counts"].get("online_proposals", 0) > 0
            assignments_admitted += learning["counts"].get("online_admissions", 0) > 0
            first_generation = None
            for generation in learning["generations"]:
                if generation["admitted_ids"] and first_generation is None:
                    first_generation = generation["generation"]
                for decision in generation["native_decisions"]:
                    failed = next((m for m in decision["margin_checks"] if not m["passed"]), None)
                    native.append({"variant": flavor, "task_id": case["task_id"],
                        "replicate": case["replicate"], "generation": generation["generation"],
                        "criterion_id": decision["criterion_id"], "accepted": decision["accepted"],
                        "reason": decision["reason"], "first_failed_margin": json.dumps(failed),
                        "source": generation["path"] + "/aggregate-margins.json"})
            first_emission = None
            for turn in arm["turns"]:
                selection = turn["selection"]
                shown = turn["has_solver_prompt"]
                delivery["scored_feedback_records"] += turn["feedback_decision"] is not None
                delivery["solver_prompt_receipts"] += shown
                delivery["raw_proactive_only_revise"] += bool(turn["raw_proactive_only_revise"])
                delivery["effective_proactive_only_revise"] += bool(turn["effective_proactive_only_revise"])
                for concern in turn["concerns"]:
                    delivery["raw_origin:" + concern.get("origin", "legacy_unlabeled")] += 1
                if selection:
                    online = selection["source_generation"] >= 2
                    mode = "corrective" if selection["corrective"] else "proactive"
                    delivery["selected"] += 1
                    delivery["selected:" + mode] += 1
                    delivery["selected:" + ("online" if online else "offline")] += 1
                    emitted = bool(turn["emitted"] and shown) if flavor == "v3" else bool(shown)
                    channel = "tag_matched_emitted" if flavor == "v3" else "separate_reminder_prompt_receipts"
                    delivery[channel] += emitted
                    delivery[channel + ":online"] += emitted and online
                    if emitted and online and first_emission is None:
                        first_emission = int(turn["submission_id"][1:]) + 1
                    if flavor == "v3" and not turn["emitted"]:
                        delivery["omitted:" + str(turn["omission_reason"])] += 1
                    deliveries.append({"variant": flavor, "task_id": case["task_id"],
                        "replicate": case["replicate"], "submission_id": turn["submission_id"],
                        "criterion_id": selection["criterion_id"], "source_generation": selection["source_generation"],
                        "mode": mode, "points": selection["points"], "requirement": selection["requirement"],
                        "has_solver_prompt": shown, "emitted": turn["emitted"] if flavor == "v3" else None,
                        "channel": "simulator_concern" if flavor == "v3" else "separate_reminder",
                        "origin": turn["concern_origin"],
                        "omission_reason": turn["omission_reason"] if flavor == "v3" else None, "reminder_path": turn["reminder_path"],
                        "solver_prompt_path": turn["solver_prompt_path"]})
            accounting.append({"variant": flavor, "task_id": case["task_id"], "replicate": case["replicate"],
                "retained_revisions": len(record["state"]["submission_ids"]) - 1,
                "solver_prompt_receipts": sum(t["has_solver_prompt"] for t in arm["turns"]),
                "stop_reason": record["state"]["stop_reason"],
                "online_proposals": learning["counts"].get("online_proposals", 0),
                "online_admissions": learning["counts"].get("online_admissions", 0),
                "first_online_admission_generation": first_generation,
                "first_recorded_online_delivery_turn": first_emission,
                "delivery_channel": "tag_matched_simulator_concern" if flavor == "v3" else "separate_reminder",
                "reasons": json.dumps(learning["native_and_ineligibility_reasons"], sort_keys=True),
                "state_path": record["state_path"], "state_sha256": record["state_sha256"]})
        summary[flavor] = {"assignments": len(cases), "assignments_with_online_proposal": assignments_proposed,
            "assignments_with_online_admission": assignments_admitted,
            "generation_appearances": dict(counts), "native_and_ineligibility_reasons": dict(reasons),
            "request_unique": dict(requests), "delivery": dict(delivery),
            "retained_revisions": sum(r["retained_revisions"] for r in accounting if r["variant"] == flavor)}
    rows = list(csv.DictReader((OUT / "stress-outcomes-v32/artifact-auditor-values.csv").open()))
    metric_names = ("W", "W_train", "S", "H", "A", "W_minus_S", "S_minus_H", "H_minus_A", "W_minus_A")
    summary["individual_auditor_means"] = {}
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["variant"], row["task_id"], row["replicate"]].append(row)
    summary["mean_absolute_panel_artifact_gap"] = {
        variant: {metric: mean(abs(mean(float(r[metric]) for r in group))
            for key, group in grouped.items() if key[0] == variant)
            for metric in ("W_minus_S", "W_minus_A")} for variant in ("v21", "v32")}
    for variant in ("v21", "v32"):
        for model in ("gpt-5.6-sol", "claude-opus-5"):
            subset = [r for r in rows if r["variant"] == variant and r["model"] == model]
            summary["individual_auditor_means"][variant + ":" + model] = {
                m: mean(float(r[m]) for r in subset) for m in metric_names}
    summary["narrower_WS_with_A_loss_at_least_5"] = [
        {"task_id": c["task_id"], "replicate": c["replicate"], "delta": c["delta"]}
        for c in cases if c["delta"]["W_minus_S"] < 0 and c["delta"]["A"] <= -5]
    write_csv("stress-v32-case-accounting.csv", accounting)
    write_csv("stress-v32-delivery.csv", deliveries)
    write_csv("stress-v32-native-decisions.csv", native)
    (OUT / "stress-v32-mechanism-summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps({f: {k: summary[f][k] for k in ("assignments_with_online_admission", "delivery", "retained_revisions")} for f in ("v21", "v3")}, indent=2))


if __name__ == "__main__":
    main()
