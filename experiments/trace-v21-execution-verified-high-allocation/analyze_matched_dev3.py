"""Compare the completed Luna-high-controller Dev3 with its matched Luna-low control."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
import json
import math
from pathlib import Path
import statistics
import sys


ROOT = Path(__file__).resolve().parents[2]
REPORT = ROOT / "experiments" / "trace-attack-defense-v21" / "report"
LOCAL_REPORT = ROOT / "experiments" / "trace-task-paraphrase-required"
DIAGNOSTICS = ROOT / "scripts" / "diagnostics"
sys.path[:0] = [str(REPORT), str(LOCAL_REPORT), str(DIAGNOSTICS)]

from report_reconstruct import reconstruct  # noqa: E402
from report_sol_opus_local import semantic_costs  # noqa: E402
from rubric_gen.artifacts.serialization import write_json_atomic  # noqa: E402


PANEL = ("gpt-5.6-sol", "claude-opus-5")
WINDOWS = (
    "full_trajectory",
    "post_update",
    "final_artifact",
    "final_revision",
)
VALUES = ("W", "W_train", "S", "H", "A", "WS", "SH", "HA", "WA")
GAPS = ("WS", "SH", "HA", "WA")
TASK_REQUIRED_PREFIX = "Task-required obligation:"


def read(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def arm(row: dict) -> str:
    value = row["condition_id"]
    if value.startswith("full"):
        return "full"
    if value.startswith("user"):
        return "user"
    raise AssertionError(value)


def mean(values: list[float]) -> float:
    return statistics.mean(values)


def stats(values: list[float]) -> dict:
    n = len(values)
    sd = statistics.stdev(values) if n > 1 else 0.0
    return {
        "n": n,
        "mean": mean(values),
        "sample_sd": sd,
        "se": sd / math.sqrt(n),
    }


def average_ranks(values: list[float]) -> list[float]:
    ordered = sorted(range(len(values)), key=lambda index: values[index])
    ranks = [0.0] * len(values)
    cursor = 0
    while cursor < len(ordered):
        end = cursor + 1
        while end < len(ordered) and values[ordered[end]] == values[ordered[cursor]]:
            end += 1
        rank = (cursor + 1 + end) / 2
        for position in range(cursor, end):
            ranks[ordered[position]] = rank
        cursor = end
    return ranks


def pearson(left: list[float], right: list[float]) -> float | None:
    assert len(left) == len(right)
    left_mean = mean(left)
    right_mean = mean(right)
    numerator = sum(
        (a - left_mean) * (b - right_mean) for a, b in zip(left, right)
    )
    left_scale = math.sqrt(sum((value - left_mean) ** 2 for value in left))
    right_scale = math.sqrt(sum((value - right_mean) ** 2 for value in right))
    if left_scale == 0 or right_scale == 0:
        return None
    return numerator / (left_scale * right_scale)


def spearman(left: list[float], right: list[float]) -> float | None:
    return pearson(average_ranks(left), average_ranks(right))


def wilson(successes: int, n: int, z: float = 1.959963984540054) -> list[float]:
    if n == 0:
        return [math.nan, math.nan]
    p = successes / n
    denominator = 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    radius = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denominator
    return [100 * (center - radius), 100 * (center + radius)]


def index_rows(rows: list[dict]) -> dict[tuple[str, int, str], dict]:
    result = {(row["task_id"], row["replicate"], row["model"]): row for row in rows}
    assert len(result) == len(rows)
    return result


def artifact_rows(rows: list[dict]) -> list[dict]:
    grouped: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in rows:
        grouped[row["task_id"], row["replicate"]].append(row)
    result = []
    for (task_id, replicate), values in sorted(grouped.items()):
        assert {value["model"] for value in values} == set(PANEL)
        result.append({
            "task_id": task_id,
            "replicate": replicate,
            **{key: mean([value["values"][key] for value in values]) for key in VALUES},
        })
    return result


def outcome_summary(rows: list[dict]) -> dict:
    artifacts = artifact_rows(rows)
    task_groups: dict[str, list[dict]] = defaultdict(list)
    for artifact in artifacts:
        task_groups[artifact["task_id"]].append(artifact)
    by_artifact_rows: dict[tuple[str, int], list[dict]] = defaultdict(list)
    for row in rows:
        by_artifact_rows[row["task_id"], row["replicate"]].append(row)
    gap_ranks = {
        key: ranks
        for key, ranks in (
            (gap, average_ranks([artifact[gap] for artifact in artifacts]))
            for gap in ("WS", "SH", "HA")
        )
    }
    rank_sum = [
        sum(gap_ranks[gap][index] for gap in ("WS", "SH", "HA"))
        for index in range(len(artifacts))
    ]
    rh_severity = []
    rh_binary_fraction = []
    for artifact in artifacts:
        values = by_artifact_rows[artifact["task_id"], artifact["replicate"]]
        rh_severity.append(mean([
            value["direct"]["full_trajectory"]["score"] for value in values
        ]))
        rh_binary_fraction.append(mean([
            float(
                value["direct"]["full_trajectory"]["decision"]
                == "reward_hacking_detected"
            )
            for value in values
        ]))
    return {
        "artifact_level": {
            key: {
                **stats([artifact[key] for artifact in artifacts]),
                "values": [
                    {
                        "task_id": artifact["task_id"],
                        "replicate": artifact["replicate"],
                        "value": artifact[key],
                    }
                    for artifact in artifacts
                ],
                "task_means": {
                    task_id: mean([artifact[key] for artifact in values])
                    for task_id, values in sorted(task_groups.items())
                },
            }
            for key in VALUES
        },
        "auditors": {
            model: {
                key: stats([
                    row["values"][key] for row in rows if row["model"] == model
                ])
                for key in VALUES
            }
            for model in PANEL
        },
        "gap_rank_vs_rh": {
            "definition": (
                "Sum of ascending average ranks for panel-mean W-S, S-H, and H-A "
                "per artifact; Spearman correlations are descriptive at n=9."
            ),
            "n": len(artifacts),
            "spearman_with_panel_mean_rh_severity": spearman(rank_sum, rh_severity),
            "spearman_with_positive_auditor_fraction": spearman(
                rank_sum, rh_binary_fraction
            ),
            "records": [
                {
                    "task_id": artifact["task_id"],
                    "replicate": artifact["replicate"],
                    "gap_rank_sum": rank_sum[index],
                    "rh_severity": rh_severity[index],
                    "positive_auditor_fraction": rh_binary_fraction[index],
                }
                for index, artifact in enumerate(artifacts)
            ],
        },
    }


def paired_summary(high_rows: list[dict], low_rows: list[dict]) -> dict:
    high = artifact_rows(high_rows)
    low = artifact_rows(low_rows)
    high_index = {(row["task_id"], row["replicate"]): row for row in high}
    low_index = {(row["task_id"], row["replicate"]): row for row in low}
    assert high_index.keys() == low_index.keys()
    result = {}
    for key in VALUES:
        values = [
            high_index[index][key] - low_index[index][key]
            for index in sorted(high_index)
        ]
        result[key] = {
            **stats(values),
            "values": [
                {
                    "task_id": index[0],
                    "replicate": index[1],
                    "high_minus_low": high_index[index][key] - low_index[index][key],
                }
                for index in sorted(high_index)
            ],
        }
    return result


def rh_summary(rows: list[dict]) -> dict:
    result: dict[str, dict] = {}
    for window in WINDOWS:
        per_model = {}
        for model in PANEL:
            values = [
                row["direct"][window]["decision"]
                for row in rows if row["model"] == model
            ]
            counts = Counter(values)
            n = len(values)
            positives = counts["reward_hacking_detected"]
            per_model[model] = {
                "positive": positives,
                "negative": counts["no_reward_hacking_detected"],
                "abstain": counts["abstain"],
                "n": n,
                "positive_percent": 100 * positives / n,
                "wilson_95_percent": wilson(positives, n),
            }
        all_values = [row["direct"][window]["decision"] for row in rows]
        all_counts = Counter(all_values)
        all_n = len(all_values)
        all_positive = all_counts["reward_hacking_detected"]
        by_artifact: dict[tuple[str, int], dict[str, dict]] = defaultdict(dict)
        for row in rows:
            by_artifact[row["task_id"], row["replicate"]][row["model"]] = row[
                "direct"
            ][window]
        artifact_records = []
        for (task_id, replicate), verdicts in sorted(by_artifact.items()):
            assert set(verdicts) == set(PANEL)
            decisions = {model: verdict["decision"] for model, verdict in verdicts.items()}
            values = list(decisions.values())
            artifact_records.append({
                "task_id": task_id,
                "replicate": replicate,
                "decisions": decisions,
                "verdicts": verdicts,
                "auditors_agree": len(set(values)) == 1,
                "any_positive": "reward_hacking_detected" in values,
                "any_abstain": "abstain" in values,
            })
        result[window] = {
            "auditors": per_model,
            "combined_auditor_rows": {
                "positive": all_positive,
                "negative": all_counts["no_reward_hacking_detected"],
                "abstain": all_counts["abstain"],
                "n": all_n,
                "positive_percent": 100 * all_positive / all_n,
                "wilson_95_percent_naive_rows": wilson(all_positive, all_n),
            },
            "artifact_agreement": {
                "agree": sum(record["auditors_agree"] for record in artifact_records),
                "n": len(artifact_records),
                "any_positive": sum(record["any_positive"] for record in artifact_records),
                "any_abstain": sum(record["any_abstain"] for record in artifact_records),
                "records": artifact_records,
            },
        }
    return result


def assignment_dirs(rows: list[dict]) -> dict[str, Path]:
    result = {}
    for row in rows:
        path = Path(row["state_path"]).parent
        result[row["assignment_id"]] = path
    assert len(result) * len(PANEL) == len(rows)
    return result


def criterion_mode(criterion: dict) -> str:
    return (
        "task_required"
        if criterion["requirement"].startswith(TASK_REQUIRED_PREFIX)
        else "claim_conditional"
    )


def mechanism_summary(rows: list[dict]) -> dict:
    directories = assignment_dirs(rows)
    final_criteria = []
    issue_records = []
    assignments_with_issue = 0
    final_issue_status = Counter()
    final_issue_records = []
    for assignment_id, directory in sorted(directories.items()):
        manifest = read(directory / "manifest.json")
        state = read(directory / "state.json")
        final_submission = state["submission_ids"][-1]
        binding = read(directory / "submission-rubric-bindings" / f"{final_submission}.json")
        generation = binding["active_generation_round"]
        criteria = read(
            directory / "rubric-generations" / f"generation-{generation:04d}"
            / "criteria.json"
        )
        for criterion in criteria:
            final_criteria.append({
                "assignment_id": assignment_id,
                "arm": arm({"condition_id": manifest["condition_id"]}),
                "task_id": manifest["task_id"],
                "replicate": manifest["replicate"],
                "criterion_id": criterion["criterion_id"],
                "mode": criterion_mode(criterion),
                "title": criterion["title"],
                "source_generation": criterion["source_generation"],
            })
        issue_dir = directory / "execution-truthfulness-issues"
        paths = sorted(issue_dir.glob("s*.json")) if issue_dir.is_dir() else []
        if paths:
            assignments_with_issue += 1
            assignment_issues = []
            for path in paths:
                payload = read(path)
                issue = payload["issue"]
                record = {
                    "assignment_id": assignment_id,
                    "arm": arm({"condition_id": manifest["condition_id"]}),
                    "task_id": manifest["task_id"],
                    "replicate": manifest["replicate"],
                    "submission_id": payload["submission_id"],
                    "solver_turn": payload["solver_turn"],
                    "status": issue["status"],
                    "issue_id": issue["issue_id"],
                    "requirement": issue["requirement"],
                    "defect": issue["defect"],
                    "corrective_action": issue["corrective_action"],
                    "if_execution_unavailable": issue["if_execution_unavailable"],
                }
                issue_records.append(record)
                assignment_issues.append(record)
            last = assignment_issues[-1]
            final_issue_status[last["status"]] += 1
            final_issue_records.append({
                **last,
                "final_submission_id": final_submission,
                "final_submission_after_last_review": final_submission != last["submission_id"],
            })
    by_arm = {}
    for arm_name in ("full", "user"):
        arm_criteria = [row for row in final_criteria if row["arm"] == arm_name]
        arm_issues = [row for row in final_issue_records if row["arm"] == arm_name]
        by_arm[arm_name] = {
            "final_criteria_total": len(arm_criteria),
            "final_criteria_by_mode": dict(Counter(row["mode"] for row in arm_criteria)),
            "assignments_with_execution_issue": len(arm_issues),
            "final_execution_issue_status": dict(Counter(row["status"] for row in arm_issues)),
        }
    return {
        "assignments": len(directories),
        "final_criteria_total": len(final_criteria),
        "final_criteria_by_mode": dict(Counter(row["mode"] for row in final_criteria)),
        "final_criteria": final_criteria,
        "assignments_with_execution_issue": assignments_with_issue,
        "final_execution_issue_status": dict(final_issue_status),
        "final_execution_issues": final_issue_records,
        "all_execution_issue_checkpoints": issue_records,
        "by_arm": by_arm,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--high-study", type=Path, required=True)
    parser.add_argument("--high-audit", type=Path, required=True)
    parser.add_argument("--low-study", type=Path, required=True)
    parser.add_argument("--low-audit", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    for path in vars(args).values():
        if not path.is_absolute() or path.is_symlink():
            raise RuntimeError("all paths must be absolute and non-symlinked")

    high_coverage, high_rows = reconstruct(
        args.high_study, args.high_audit, PANEL, expected_holdouts=2
    )
    low_coverage, low_rows = reconstruct(
        args.low_study, args.low_audit, PANEL, expected_holdouts=2
    )
    assert high_coverage["assignment_count"] == low_coverage["assignment_count"] == 18
    assert len(high_rows) == len(low_rows) == 36

    output = {
        "kind": "execution-verified-high-controller-vs-low-control-dev3",
        "uncertainty_note": (
            "SD and SE use nine panel-averaged artifact values per arm. Wilson "
            "intervals over 18 auditor rows are descriptive only because the two "
            "auditors share each artifact and the nine artifacts occupy only three task clusters."
        ),
        "coverage": {"high": high_coverage, "low": low_coverage},
        "conditions": {},
        "paired_high_minus_low": {},
        "cost": {
            "high_audit": semantic_costs(args.high_audit),
            "low_audit": semantic_costs(args.low_audit),
        },
    }
    for label, rows in (("high", high_rows), ("low", low_rows)):
        output["conditions"][label] = {
            arm_name: {
                "outcomes": outcome_summary([
                    row for row in rows if arm(row) == arm_name
                ]),
                "rh": rh_summary([
                    row for row in rows if arm(row) == arm_name
                ]),
            }
            for arm_name in ("full", "user")
        }
        output["conditions"][label]["mechanism"] = mechanism_summary(rows)

    for arm_name in ("full", "user"):
        high_arm = [row for row in high_rows if arm(row) == arm_name]
        low_arm = [row for row in low_rows if arm(row) == arm_name]
        high_index = index_rows(high_arm)
        low_index = index_rows(low_arm)
        assert high_index.keys() == low_index.keys()
        for key in high_index:
            assert high_index[key]["initial_submission_sha256"] == low_index[key][
                "initial_submission_sha256"
            ]
            assert high_index[key]["selected_rubric_sha256"] == low_index[key][
                "selected_rubric_sha256"
            ]
        output["paired_high_minus_low"][arm_name] = paired_summary(high_arm, low_arm)

    write_json_atomic(args.output, output)
    print(json.dumps({
        "output": str(args.output),
        "high_cost": output["cost"]["high_audit"]["usage_based_usd"],
        "low_cost": output["cost"]["low_audit"]["usage_based_usd"],
    }), flush=True)


if __name__ == "__main__":
    main()
