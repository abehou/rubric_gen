"""Catalog the existing Result20 comparison without importing or rewriting runs."""
import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
SOURCE = ROOT / "docs/reports/2026-09-11/trace-attack-defense-v2.1"
OUT = ROOT / "docs/reports/2026-09-12/biomnibench-v21-to45/queue5"
COHORTS = ("static_full", "candidate_full", "static_user", "candidate_user")
PANEL = {"gpt-5.6-sol", "claude-opus-5"}


def read(path):
    return json.loads(path.read_text())


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    result = read(SOURCE / "results.json")
    accounting = read(SOURCE / "accounting.json")
    sources = read(SOURCE / "frozen-source-receipts.json")
    assert result["complete"] and accounting["unique_judgments"] == accounting["completed_unique_judgments"] == 3668
    assert sources["V2_static_H_verified"] and sources["unchanged_W_S_A_RH"]
    with (SOURCE / "outcomes-by-auditor.csv").open() as f:
        rows = [r for r in csv.DictReader(f) if r["cohort"] in COHORTS]
    assert len(rows) == 480
    lookup = {(r["cohort"], r["task_id"], int(r["replicate"]), r["model"]): r for r in rows}
    assert len(lookup) == 480
    groups = defaultdict(list)
    for r in rows:
        groups[r["cohort"], r["task_id"], int(r["replicate"])].append(r)
        if r["cohort"].startswith("candidate_"):
            control = lookup[(r["cohort"].replace("candidate_", "static_"), r["task_id"], int(r["replicate"]), r["model"])]
            for field in ("initial_submission_sha256", "selected_rubric_sha256", "heldout_pool"):
                assert r[field] == control[field], (r["task_id"], r["replicate"], field)
            assert r["heldout_pool"] == "canonical_v2"
    catalog = []
    for (cohort, task, rep), values in sorted(groups.items()):
        assert {r["model"] for r in values} == PANEL
        for field in ("state_path", "submission_id", "initial_submission_sha256", "selected_rubric_sha256"):
            assert len({r[field] for r in values}) == 1, field
        policy, arm = cohort.split("_")
        catalog.append(dict(task_id=task, replicate=rep, feedback_arm=arm,
                            rubric_policy="fixed" if policy == "static" else "red_team_trace",
                            scientific_recipe="frozen_fixed" if policy == "static" else "attack_defense_v2.1",
                            source_cohort=cohort, source_state_path=values[0]["state_path"],
                            final_submission_id=values[0]["submission_id"], auditor_rows=2,
                            mission_execution="reused_existing_evidence",
                            if_new_user_selected="replace_in_new_core_comparison_keep_as_history" if cohort == "candidate_user" else "reuse_if_native_inputs_match"))
    assert len(catalog) == 240 and all(n == 60 for n in Counter(r["source_cohort"] for r in catalog).values())
    with (OUT / "existing-result20-assignments.csv").open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(catalog[0])); w.writeheader(); w.writerows(catalog)
    tasks = sorted({r["task_id"] for r in catalog})
    assert len(tasks) == 20 and {r["replicate"] for r in catalog} == {1, 2, 3}
    record = dict(
        purpose="Queue 5 ordinary scale decision; no new execution or provenance transformation",
        source_result=str((SOURCE / "results.json").relative_to(ROOT)),
        source_accounting=str((SOURCE / "accounting.json").relative_to(ROOT)),
        scientific_incumbent="attack_defense_v2.1", full_recipe_ready_for_characterization="attack_defense_v2.1",
        selected_new_user_recipe=None, confirmation_status="await_complete_primary_dev3_comparison_and_nomination",
        new_result20_status="not_launched_no_selected_confirmed_user_recipe",
        provider_calls=0, new_assignments=0, new_audits=0,
        result20_tasks=tasks, replicates=3, result20_randomization_seed=20260820,
        existing_core=dict(assignments=240, trace_assignments=120, fixed_assignments=120,
                           auditor_rows=480, all_reused_in_current_mission=True,
                           trace_unique_required_judgments=3668, trace_unique_completed_judgments=3668,
                           trace_per_arm_including_shared={a: accounting["arms"][a]["required_unique_judgments_including_shared"] for a in ("full", "user")},
                           trace_judgments_shared_between_arms=744,
                           static_judgment_accounting="Separate frozen native sources; 720 V2 H judgments already verified. No invented combined count.",
                           original_trace_production="118 unchanged v2 assignments plus two v2.1 recoveries; all 120 are existing evidence now"),
        possible_new_user_result20=dict(total_assignment_records=240, trace_records=120,
                                        reused_full_fixed=60, reused_user_fixed=60, reused_full_trace=60,
                                        newly_executed_user_trace=60, historical_user_v21_retained_outside_new_core=60,
                                        condition="Only after one nominated User recipe has a coherent independent confirmation"),
        confirmation=dict(tasks=["da-3-4", "da-11-1", "da-18-1"], replicates=3, seed=20260806,
                          new_control_continuations=9, new_candidate_continuations=9,
                          upstream="Reuse actual canonical control s000, selected/development/heldout pool and realized g1 sources from queue-2 native input receipts",
                          continuations="Fresh disjoint native output roots; no importing sampled continuations or selecting favorable results",
                          scope="One independent matched continuation block per selected candidate, at most 18 assignments; development tasks, not untouched validation",
                          prior_satisfying_independent_block_found=False),
        unchanged_definitions=dict(panel=sorted(PANEL), W="weak selected-base", W_train="selected-base plus active learned penalties",
                                   S="strong selected", H="canonical V2 heldout", A="absolute rubric-free quality",
                                   windows=["full_trajectory", "post_update", "final_artifact", "final_revision"],
                                   post_update_baseline_index=2, post_update_first_affected_index=3,
                                   bootstrap=result["analysis"], authoritative_aggregation="equal-weight Sol+Opus; per-auditor and native union retained separately; abstentions remain unresolved"),
        current_practical_interpretation=["W-S near comparator or modestly lower; 0.1-0.5 reduction can be acceptable without statistical significance",
                                          "Preserve S/H/A, keep S-H low, interpret H-A with both components, avoid signed-gap overshooting",
                                          "Genuine RH reduction where comparator has headroom; all windows reported; zero floors do not establish benefit",
                                          "No weighted winner score or newly imposed small-sample threshold"],
        historical_decisions_unchanged=result["decisions"],
        source_verification="Catalog checks saved native keys and existing producer receipts; does not claim a new consumer import or repeat whole-run hashes",
        native_grouping="Keep original studies/audits and actual producer metadata. A future User-only native execution can be compared to those unchanged sources only under supported input matching; no producer-identity adapter is added.",
        next_scale="Full fixed versus Full trace v2.1 may proceed to Results30/45 characterization under item 6 task membership; User remains unresolved",
    )
    (OUT / "scale-decision.json").write_text(json.dumps(record, indent=2) + "\n")
    print(json.dumps(dict(existing_assignments=len(catalog), per_cell=Counter(r["source_cohort"] for r in catalog),
                          new_user_recipe=None, new_assignments=0, provider_calls=0)))


if __name__ == "__main__":
    main()
