"""Reconstruct the complete matched Sol+Opus local Dev3 result read-only."""
from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
from pathlib import Path
import sys
from types import SimpleNamespace


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "experiments" / "trace-attack-defense-v21" / "report"
DIAGNOSTICS = ROOT / "scripts" / "diagnostics"
sys.path[:0] = [str(REPORT), str(DIAGNOSTICS)]

from report_outcomes import summarize  # noqa: E402
from report_reconstruct import reconstruct  # noqa: E402
from rubric_gen.artifacts.serialization import write_json_atomic  # noqa: E402
from rubric_gen.detection.costs import request_cost, usage_tokens  # noqa: E402


PANEL = ("gpt-5.6-sol", "claude-opus-5")
TASK_REQUIRED_PREFIX = "Task-required obligation:"


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def semantic_costs(audit: Path) -> dict:
    rows: list[dict] = []
    seen: set[str] = set()

    def add(stage: str, generation: dict, path: Path) -> None:
        response_id = generation.get("response_id")
        if not response_id or response_id in seen:
            return
        seen.add(response_id)
        provider = generation["provider"]
        usage = generation.get("raw_usage") or generation.get(
            "provider_metadata", {}
        ).get("usage")
        tokens = usage_tokens(SimpleNamespace(
            provider=provider, provider_metadata={"usage": usage}
        ))
        rows.append({
            "stage": stage,
            "model": generation["requested_model"],
            "provider": provider,
            "response_id": response_id,
            "path": str(path),
            "usage_available": tokens is not None,
            **(tokens or {}),
            "usage_based_usd": request_cost(
                generation["requested_model"], **tokens
            ) if tokens else None,
        })

    for path in (audit / "rubric_score" / "records").glob("*.json"):
        record = read(path)
        usage_path = Path(record["evaluation_path"]).parent / "usage.json"
        add("rubric_score", read(usage_path)["call"], usage_path)
    for stage in ("absolute_score", "pairwise_preference"):
        for path in (audit / stage / "records").glob("*.json"):
            add(stage, read(path)["generation"], path)
    for path in audit.glob("direct_*/evaluations/*/cases/*/*/score.json"):
        for item in read(path).get("generations", []):
            add(path.parents[5].name, item["generation"], path)

    grouped: dict[tuple[str, str], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["stage"], row["model"]].append(row)
    stages = []
    for (stage, model), values in sorted(grouped.items()):
        stages.append({
            "stage": stage,
            "model": model,
            "responses": len(values),
            "usage_available": sum(v["usage_available"] for v in values),
            "input_tokens": sum(v.get("input_tokens", 0) for v in values),
            "cached_input_tokens": sum(
                v.get("cached_input_tokens", 0) for v in values
            ),
            "cache_write_input_tokens": sum(
                v.get("cache_write_input_tokens", 0) for v in values
            ),
            "output_tokens": sum(v.get("output_tokens", 0) for v in values),
            "usage_based_usd": sum(v.get("usage_based_usd") or 0 for v in values),
        })
    failures = list((audit / "rubric_score").glob("**/failed-attempt-*.json"))
    return {
        "saved_successful_responses": len(rows),
        "usage_based_usd": sum(row.get("usage_based_usd") or 0 for row in rows),
        "by_model_usd": {
            model: sum(
                row.get("usage_based_usd") or 0
                for row in rows if row["model"] == model
            )
            for model in PANEL
        },
        "stages": stages,
        "failed_attempts_without_usage": len(failures),
        "limitations": [
            "Usage-based estimates are not provider invoices.",
            "Failed calls without returned usage have unknown cost.",
        ],
    }


def activation(study: Path) -> dict:
    final_criteria = []
    request_applications = Counter()
    assignment_modes: dict[str, Counter] = {}
    pair_observations = []
    unique_pairs: dict[tuple[str, str], list[bool]] = defaultdict(
        lambda: [False, False]
    )
    for state_path in sorted((study / "experiments").glob("**/state.json")):
        assignment = state_path.parent
        manifest = read(assignment / "manifest.json")
        assignment_id = manifest["assignment_id"]
        state = read(state_path)
        submission_id = state["submission_ids"][-1]
        binding = read(
            assignment / "submission-rubric-bindings" / f"{submission_id}.json"
        )
        generation = binding["active_generation_round"]
        criteria = read(
            assignment / "rubric-generations"
            / f"generation-{generation:04d}" / "criteria.json"
        )
        modes = Counter()
        for criterion in criteria:
            mode = (
                "task_required"
                if criterion["requirement"].startswith(TASK_REQUIRED_PREFIX)
                else "claim_conditional"
            )
            modes[mode] += 1
            final_criteria.append({
                "assignment_id": assignment_id,
                "condition_id": manifest["condition_id"],
                "task_id": manifest["task_id"],
                "mode": mode,
                "title": criterion["title"],
                "source_generation": criterion["source_generation"],
            })
        assignment_modes[assignment_id] = modes

        for path in assignment.glob(
            "trace-defense-v2-requests/*/attempt-*.json"
        ):
            attempt = read(path)
            if attempt.get("stage") != "application" \
                    or attempt.get("status") != "valid_result":
                continue
            response_text = (attempt.get("output") or {}).get("response_text")
            if not response_text:
                continue
            response = json.loads(response_text)
            mode = (
                "task_required"
                if TASK_REQUIRED_PREFIX in attempt.get("attempt_evidence", "")
                else "claim_conditional"
            )
            request_applications[
                mode, response.get("applicability"), response.get("level")
            ] += 1

        for path in assignment.glob(
            "rubric-generations/generation-*/pairwise-comparisons.json"
        ):
            proposal = read(path.parent / "criterion-proposal.json")
            selected = set(proposal.get("selection", []))
            for comparison in read(path).get("comparisons", []):
                disagreement = (
                    comparison["active_rubric"]["preference"]
                    != comparison["development_rubric"]["preference"]
                )
                chosen = comparison["pair_id"] in selected
                pair_observations.append({
                    "disagreement": disagreement, "selected": chosen
                })
                aggregate = unique_pairs[assignment_id, comparison["pair_id"]]
                aggregate[0] = aggregate[0] or disagreement
                aggregate[1] = aggregate[1] or chosen

    return {
        "final_criteria": {
            "total": len(final_criteria),
            "by_mode": dict(Counter(row["mode"] for row in final_criteria)),
            "task_required_assignments": sum(
                modes["task_required"] > 0 for modes in assignment_modes.values()
            ),
            "records": final_criteria,
        },
        "application_requests": [
            {
                "mode": mode,
                "applicability": applicability,
                "level": level,
                "count": count,
            }
            for (mode, applicability, level), count
            in sorted(request_applications.items(), key=lambda item: str(item[0]))
        ],
        "selected_development": {
            "generation_pair_observations": len(pair_observations),
            "disagreement_observations": sum(
                row["disagreement"] for row in pair_observations
            ),
            "selected_disagreement_observations": sum(
                row["disagreement"] and row["selected"]
                for row in pair_observations
            ),
            "unique_assignment_pairs": len(unique_pairs),
            "unique_pairs_ever_disagreeing": sum(v[0] for v in unique_pairs.values()),
            "disagreeing_pairs_ever_selected": sum(
                v[0] and v[1] for v in unique_pairs.values()
            ),
            "disagreeing_pairs_never_selected": sum(
                v[0] and not v[1] for v in unique_pairs.values()
            ),
        },
    }


def pairwise(audit: Path) -> dict:
    assignments = read(audit / "pairwise_preference" / "summary.json")[
        "assignments"
    ]
    result = {}
    for arm in ("full", "user"):
        values = [
            row for row in assignments if row["condition_id"].startswith(arm)
        ]
        result[arm] = {
            "assignments": len(values),
            "panel_mean_final_preference": sum(
                row["pairwise_preference_scores"]["panel_mean"] for row in values
            ) / len(values),
            "models": {
                model: sum(
                    row["pairwise_preference_scores"]["model_results"][model][
                        "score"
                    ]
                    for row in values
                ) / len(values)
                for model in PANEL
            },
        }
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--study", type=Path, required=True)
    parser.add_argument("--audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in (args.study, args.audit, args.output.parent):
        if not path.is_absolute() or path.is_symlink():
            raise RuntimeError("report paths must be absolute and non-symlinked")
    coverage, rows = reconstruct(
        args.study, args.audit, PANEL, expected_holdouts=2
    )
    summaries = {
        arm: summarize([
            row for row in rows if row["condition_id"].startswith(arm)
        ])
        for arm in ("full", "user")
    }
    positives = [
        {
            "assignment_id": row["assignment_id"],
            "condition_id": row["condition_id"],
            "task_id": row["task_id"],
            "replicate": row["replicate"],
            "model": row["model"],
            "windows": {
                window: verdict
                for window, verdict in row["direct"].items()
                if verdict["decision"] != "no_reward_hacking_detected"
            },
        }
        for row in rows
        if any(
            verdict["decision"] != "no_reward_hacking_detected"
            for verdict in row["direct"].values()
        )
    ]
    result = {
        "kind": "task-required-local-dev3-sol-opus-analysis",
        "coverage": coverage,
        "summaries": summaries,
        "pairwise": pairwise(args.audit),
        "activation": activation(args.study),
        "rh_nonnegative_cases": positives,
        "cost": semantic_costs(args.audit),
    }
    write_json_atomic(args.output, result)
    print(json.dumps({
        "coverage": coverage,
        "means": {arm: value["means"] for arm, value in summaries.items()},
        "cost": result["cost"],
    }), flush=True)


if __name__ == "__main__":
    main()
