"""Combine completed RH stages without changing judgment identities."""

from __future__ import annotations

import math
from pathlib import Path

from rubric_gen.reward_hacking.metrics import detection_rates
from rubric_gen.submission_revision import rh_diagnostics as rh
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.rubric_bank import RubricBankPolicy


def write_reward_hacking_evaluation(output_dir: Path) -> Path:
    """Write one report for every valid assignment subset."""

    output = rh._RhOutputStore(output_dir)
    root = output.root
    mechanistic_output = rh._RhOutputStore(root / "mechanistic")
    holistic_output = rh._RhOutputStore(root / "holistic")
    mechanistic_output.validate_tree()
    holistic_output.validate_tree()
    mechanistic = read_json_object(
        mechanistic_output.regular_file("summary.json"),
        "RH mechanistic summary",
    )
    holistic = read_json_object(
        holistic_output.regular_file("summary.json"),
        "RH holistic summary",
    )
    direct_summaries = sorted((root / "direct").glob("evaluations/*/summary.json"))
    if len(direct_summaries) != 1:
        raise RuntimeError(
            "direct RH detection must contain exactly one completed summary"
        )
    direct = read_json_object(direct_summaries[0], "direct RH detection summary")
    mechanistic_plan = mechanistic.get("predispatch_plan")
    holistic_plan = holistic.get("predispatch_plan")
    if (
        mechanistic.get("kind") != rh.MECHANISTIC_KIND
        or mechanistic.get("status") != "completed"
        or holistic.get("kind") != rh.HOLISTIC_KIND
        or holistic.get("status") != "completed"
        or mechanistic.get("experiment_id") != holistic.get("experiment_id")
        or mechanistic.get("study_dir") != holistic.get("study_dir")
        or mechanistic.get("models") != holistic.get("models")
        or mechanistic.get("models") != direct.get("models")
        or not isinstance(mechanistic_plan, dict)
        or mechanistic_plan.get("accepted") is not True
        or not isinstance(holistic_plan, dict)
        or holistic_plan.get("accepted") is not True
    ):
        raise RuntimeError("RH evaluation summaries are incomplete or incompatible")
    weights = mechanistic.get("loss_weights")
    if (
        not isinstance(weights, dict)
        or set(weights) != set(rh.COMPONENTS)
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(float(value))
            or float(value) < 0
            for value in weights.values()
        )
    ):
        raise RuntimeError("RH loss weights are invalid")
    normalized_weights = {key: float(weights[key]) for key in rh.COMPONENTS}
    if not any(normalized_weights.values()):
        raise RuntimeError("at least one RH loss weight must be positive")
    mechanistic_by_id = rh._assignment_map(mechanistic, "mechanistic")
    holistic_by_id = rh._assignment_map(holistic, "holistic")
    if set(mechanistic_by_id) != set(holistic_by_id):
        raise RuntimeError("RH evaluation assignment sets disagree")
    assignments: list[dict[str, object]] = []
    for assignment_id in sorted(mechanistic_by_id):
        mechanism = mechanistic_by_id[assignment_id]
        quality = holistic_by_id[assignment_id]
        for key in ("task_id", "replicate", "condition_id", "rubric_policy"):
            if mechanism.get(key) != quality.get(key):
                raise RuntimeError(
                    f"RH evaluation assignment metadata disagrees: {assignment_id}"
                )
        assignments.append(rh._combine_assignment(
            mechanism,
            quality,
            normalized_weights,
        ))
    direct_outcomes = rh._direct_assignment_outcomes(
        direct,
        assignments,
        str(mechanistic["experiment_id"]),
    )
    for assignment in assignments:
        assignment_id = str(assignment["assignment_id"])
        assignment["direct_detection"] = direct_outcomes[assignment_id]
    rubric_policy_aggregates = _rubric_policy_aggregates(assignments)
    rubric_policies = tuple(policy.value for policy in RubricBankPolicy)
    summary = {
        "kind": rh.EVALUATION_KIND,
        "status": "completed",
        "experiment_id": mechanistic["experiment_id"],
        "estimand": {
            "boundaries": (
                "final-minus-initial artifacts rescored under the terminal bank"
            ),
            "score_scale": [0, 100],
            "component_order": list(rh.COMPONENTS),
            "loss_weights": normalized_weights,
            "primary_outcomes": {
                "direct_detection": (
                    "independent categorical trajectory decision"
                ),
                "holistic_quality_gain": (
                    "strong-panel criterion-free final-minus-initial score"
                ),
                "selected_rubric_gain": (
                    "selected common-rubric final-minus-initial score"
                ),
                "sealed_holdout_bank_gain": (
                    "sealed holdout common-bank final-minus-initial score"
                ),
            },
            "secondary_outcomes": (
                "separate order-averaged preference for the highest-scoring "
                "artifact over the lowest-scoring artifact under the saved "
                "in-loop-judge original-rubric five-call mean; scores and order "
                "labels are hidden from the pairwise panel; this outcome does "
                "not enter Q or the signed identity"
            ),
            "diagnostic_outcomes": (
                "terminal-bank gain, boundary-local online gains, component "
                "changes, weighted positive-part loss change, and active-ruler "
                "gaps; these values use condition-dependent rulers or proxy "
                "decompositions and are not primary outcomes"
            ),
            "identity": (
                "weak terminal-bank score minus rubric-free score equals "
                "verifier_exploitation plus dynamic_rubric_gap"
            ),
            "rubric_elicitation": (
                "the terminal bank is common across endpoints only within a run "
                "and can differ across arms; its condition contrasts are "
                "diagnostic total-policy effects; the selected rubric, sealed "
                "holdouts, and rubric-free outcome are cross-arm common rulers; "
                "boundary-local online scores remain ruler-confounded diagnostics"
            ),
            "weak_rescore": (
                "the configured in-loop judge model rescores both artifacts "
                "against every terminal-bank member"
            ),
            "common_random_numbers": (
                "exact semantic requests reuse one judgment across conditions; "
                "condition IDs and run paths are not judgment-key fields"
            ),
            "rubric_diagnostics": (
                "active_to_original, original_to_selected, selected_to_holdout, "
                "and holdout_to_holistic partition dynamic_rubric_gap; they are "
                "not separate loss terms; the terminal specification anchor is "
                "a declared scoring specification, not verified coverage; "
                "sealed-holdout standard deviation and range report wording "
                "sensitivity outside the signed identity"
            ),
            "direct_detector": (
                "independent categorical trajectory outcome; not a calibrated "
                "function of the score decomposition"
            ),
        },
        "direct_ensemble": {
            "summary_path": str(direct_summaries[0]),
            "rates": detection_rates(direct),
        },
        "predispatch_plans": {
            "mechanistic": mechanistic_plan,
            "holistic": holistic_plan,
        },
        "condition_aggregates": rh._condition_aggregates(assignments),
        "rubric_policy_coverage": {
            "available": list(rubric_policy_aggregates),
            "missing": [
                policy
                for policy in rubric_policies
                if policy not in rubric_policy_aggregates
            ],
            "complete": len(rubric_policy_aggregates) == len(rubric_policies),
        },
        "rubric_policy_aggregates": rubric_policy_aggregates,
        "paired_condition_contrasts": rh._paired_condition_contrasts(assignments),
        "assignments": assignments,
    }
    return output.write_json(("summary.json",), summary)


def _rubric_policy_aggregates(
    assignments: list[dict[str, object]],
) -> dict[str, object]:
    groups: dict[str, list[dict[str, object]]] = {}
    policies = tuple(policy.value for policy in RubricBankPolicy)
    for assignment in assignments:
        policy = assignment.get("rubric_policy")
        if policy not in policies:
            raise RuntimeError("RH assignment has an invalid rubric policy")
        groups.setdefault(str(policy), []).append(assignment)
    return rh._aggregate_assignment_groups({
        policy: groups[policy]
        for policy in policies
        if policy in groups
    })
