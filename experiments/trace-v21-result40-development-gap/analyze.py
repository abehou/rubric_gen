"""Provider-free S/D/H, uncertainty, usage, and latency analysis."""
from __future__ import annotations

from collections import defaultdict
import csv
from datetime import datetime
import json
import math
from pathlib import Path
from statistics import fmean, median, stdev
from types import SimpleNamespace

from rubric_gen.detection.costs import request_cost, usage_tokens
from rubric_gen.runtime.pricing import PRICING_AS_OF


ROOT = Path(__file__).resolve().parents[2]
BUNDLE = Path(__file__).resolve().parent
RUN = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-result40-development-score-pilot-20260921"
)
BASE_REPORT = (
    ROOT
    / "docs/reports/2026-09-18/"
    "trace-v21-execution-verified-provenance-result40"
)
REPORT = (
    ROOT
    / "docs/reports/2026-09-21/"
    "trace-v21-result40-development-gap"
)
TASKS = ("da-26-4", "da-26-2", "da-17-1", "da-17-5", "da-20-4")
MODELS = ("gpt-5.6-sol", "gemini-3.8-flash")
PANEL_TO_MODEL = {"sol": MODELS[0], "gemini": MODELS[1]}
MODEL_LABEL = {MODELS[0]: "sol", MODELS[1]: "gemini"}
CONDITION_TO_COHORT = {
    "full-static": "static_full",
    "user-simulator-static": "static_user",
    "full-red-team-trace-execution-verified-proactive-provenance": (
        "current_full"
    ),
    "user-simulator-red-team-trace-execution-verified-proactive-provenance": (
        "current_user"
    ),
}
METRICS = ("S", "D", "H", "S_minus_D", "D_minus_H", "S_minus_H")


def read_json(path: Path) -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected a JSON object: {path}")
    return value


def write_json(name: str, value: object) -> None:
    REPORT.mkdir(parents=True, exist_ok=True)
    (REPORT / name).write_text(
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
        encoding="utf-8",
    )


def write_csv(name: str, rows: list[dict[str, object]]) -> None:
    if not rows:
        raise RuntimeError(f"refusing to write empty table: {name}")
    REPORT.mkdir(parents=True, exist_ok=True)
    fields = list(dict.fromkeys(key for row in rows for key in row))
    with (REPORT / name).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def arm_for(condition_id: str) -> str:
    return "User" if condition_id.startswith("user-simulator") else "Full"


def treatment_for(condition_id: str) -> str:
    return "Static" if condition_id.endswith("static") else "RTT"


def descriptive(values: list[float]) -> dict[str, float | int | None]:
    if not values:
        raise RuntimeError("cannot summarize an empty value set")
    sd = stdev(values) if len(values) > 1 else None
    return {
        "n": len(values),
        "mean": fmean(values),
        "sd": sd,
        "se": sd / math.sqrt(len(values)) if sd is not None else None,
        "minimum": min(values),
        "maximum": max(values),
    }


def grouped_means(
    rows: list[dict[str, object]], keys: tuple[str, ...]
) -> list[dict[str, object]]:
    groups: dict[tuple[object, ...], list[dict[str, object]]] = defaultdict(list)
    for row in rows:
        groups[tuple(row[key] for key in keys)].append(row)
    result = []
    for values, members in sorted(groups.items()):
        item = dict(zip(keys, values, strict=True))
        item["n"] = len(members)
        for metric in METRICS:
            item[metric] = fmean(float(row[metric]) for row in members)
        result.append(item)
    return result


def base_model_points() -> dict[tuple[str, int, str, str], dict[str, str]]:
    path = BASE_REPORT / "artifact-values.csv"
    rows = list(csv.DictReader(path.open(encoding="utf-8")))
    selected = {}
    for row in rows:
        if (
            row["population"] != "new20"
            or row["task_id"] not in TASKS
            or row["panel"] not in PANEL_TO_MODEL
        ):
            continue
        key = (
            row["task_id"],
            int(row["replicate"]),
            row["cohort"],
            PANEL_TO_MODEL[row["panel"]],
        )
        if key in selected:
            raise RuntimeError(f"duplicate Result40 S/H point: {key}")
        selected[key] = row
    if len(selected) != 5 * 3 * 4 * 2:
        raise RuntimeError(
            f"expected 120 Result40 Sol/Gemini S/H points, found {len(selected)}"
        )
    return selected


def development_model_points() -> tuple[
    dict[tuple[str, int, str, str], dict[str, object]],
    list[dict[str, object]],
]:
    selected = {}
    summaries = []
    for task in TASKS:
        for kind in ("static", "trace"):
            path = RUN / "scores" / task / kind / "summary.json"
            summary = read_json(path)
            summaries.append(summary)
            if (
                summary.get("status") != "completed"
                or summary.get("models") != list(MODELS)
                or summary.get("artifact") != "final"
                or summary.get("rubric_role") != "development"
                or summary.get("planned_semantic_judgment_count") != 12
                or summary.get("successful_semantic_judgment_count") != 12
                or summary.get("failed_semantic_judgment_count") != 0
                or summary.get("missing_models") != []
            ):
                raise RuntimeError(f"development score scope is incomplete: {path}")
            records = summary.get("records")
            if not isinstance(records, list) or len(records) != 12:
                raise RuntimeError(f"development score records changed: {path}")
            for row in records:
                if (
                    not isinstance(row, dict)
                    or row.get("artifact") != "final"
                    or row.get("rubric_roles")
                    != [{"name": "development", "variant_index": 1}]
                    or row.get("generation_bindings") != []
                    or row.get("task_id") != task
                    or row.get("model") not in MODELS
                ):
                    raise RuntimeError(f"invalid development score record: {path}")
                condition_id = str(row["condition_id"])
                key = (
                    task,
                    int(row["replicate"]),
                    condition_id,
                    str(row["model"]),
                )
                if key in selected:
                    raise RuntimeError(f"duplicate development score point: {key}")
                selected[key] = row
    if len(selected) != 120:
        raise RuntimeError(f"expected 120 development scores, found {len(selected)}")
    return selected, summaries


def build_points() -> tuple[
    list[dict[str, object]],
    list[dict[str, object]],
    list[dict[str, object]],
]:
    base = base_model_points()
    development, summaries = development_model_points()
    model_points = []
    for key, d_row in sorted(development.items()):
        task, replicate, condition_id, model = key
        cohort = CONDITION_TO_COHORT.get(condition_id)
        if cohort is None:
            raise RuntimeError(f"unexpected condition: {condition_id}")
        source = base[(task, replicate, cohort, model)]
        s = float(source["S"])
        d = float(d_row["score"])
        h = float(source["H"])
        point = {
            "task_id": task,
            "replicate": replicate,
            "arm": arm_for(condition_id),
            "condition": treatment_for(condition_id),
            "condition_id": condition_id,
            "assignment_id": d_row["assignment_id"],
            "artifact_id": source["artifact_id"],
            "initial_submission_sha256": source["initial_submission_sha256"],
            "model": model,
            "S": s,
            "D": d,
            "H": h,
            "S_minus_D": s - d,
            "D_minus_H": d - h,
            "S_minus_H": s - h,
        }
        if not math.isclose(
            float(point["S_minus_H"]),
            float(point["S_minus_D"]) + float(point["D_minus_H"]),
            abs_tol=1e-12,
        ):
            raise RuntimeError(f"S-H decomposition failed: {key}")
        model_points.append(point)

    groups: dict[tuple[str, int, str, str], list[dict[str, object]]] = defaultdict(list)
    for row in model_points:
        groups[(
            str(row["task_id"]),
            int(row["replicate"]),
            str(row["arm"]),
            str(row["condition"]),
        )].append(row)
    artifact_points = []
    for (task, replicate, arm, condition), members in sorted(groups.items()):
        if {row["model"] for row in members} != set(MODELS):
            raise RuntimeError("artifact does not have the complete Sol+Gemini panel")
        item = {
            "task_id": task,
            "replicate": replicate,
            "arm": arm,
            "condition": condition,
            "condition_id": members[0]["condition_id"],
            "assignment_id": members[0]["assignment_id"],
            "artifact_id": members[0]["artifact_id"],
            "panel": "equal-weight-sol-gemini",
        }
        for metric in METRICS:
            item[metric] = fmean(float(row[metric]) for row in members)
        for row in members:
            label = MODEL_LABEL[str(row["model"])]
            for metric in ("S", "D", "H"):
                item[f"{metric}_{label}"] = row[metric]
        if not math.isclose(
            float(item["S_minus_H"]),
            float(item["S_minus_D"]) + float(item["D_minus_H"]),
            abs_tol=1e-12,
        ):
            raise RuntimeError("panel S-H decomposition failed")
        artifact_points.append(item)
    if len(artifact_points) != 60:
        raise RuntimeError(f"expected 60 artifact points, found {len(artifact_points)}")
    return model_points, artifact_points, summaries


def paired_rows(
    rows: list[dict[str, object]], *, include_model: bool
) -> list[dict[str, object]]:
    key_fields = ("task_id", "replicate", "arm") + (
        ("model",) if include_model else ()
    )
    paired: dict[tuple[object, ...], dict[str, dict[str, object]]] = defaultdict(dict)
    for row in rows:
        paired[tuple(row[key] for key in key_fields)][str(row["condition"])] = row
    output = []
    for values, members in sorted(paired.items()):
        if set(members) != {"Static", "RTT"}:
            raise RuntimeError(f"unpaired RTT/static artifact: {values}")
        static, rtt = members["Static"], members["RTT"]
        item = dict(zip(key_fields, values, strict=True))
        item["static_assignment_id"] = static["assignment_id"]
        item["rtt_assignment_id"] = rtt["assignment_id"]
        for metric in METRICS:
            item[f"static_{metric}"] = static[metric]
            item[f"rtt_{metric}"] = rtt[metric]
            item[f"delta_{metric}"] = float(rtt[metric]) - float(static[metric])
        output.append(item)
    return output


def uncertainty_rows(
    artifact_points: list[dict[str, object]],
    task_means: list[dict[str, object]],
    paired: list[dict[str, object]],
    paired_task_means: list[dict[str, object]],
) -> list[dict[str, object]]:
    result = []

    def add(
        estimand: str,
        rows: list[dict[str, object]],
        group_fields: tuple[str, ...],
        prefix: str,
    ) -> None:
        groups: dict[tuple[object, ...], list[dict[str, object]]] = defaultdict(list)
        for row in rows:
            groups[tuple(row[key] for key in group_fields)].append(row)
        for values, members in sorted(groups.items()):
            base = {"estimand": estimand, **dict(zip(group_fields, values, strict=True))}
            for metric in METRICS:
                stats = descriptive([float(row[f"{prefix}{metric}"]) for row in members])
                result.append({**base, "metric": metric, **stats})

    add(
        "arm-condition artifact points",
        artifact_points,
        ("arm", "condition"),
        "",
    )
    add(
        "arm-condition task-cluster means",
        task_means,
        ("arm", "condition"),
        "",
    )
    add("paired RTT-static artifact deltas", paired, ("arm",), "delta_")
    add(
        "paired RTT-static task-cluster deltas",
        paired_task_means,
        ("arm",),
        "delta_",
    )
    return result


def usage_and_latency(
    summaries: list[dict[str, object]],
) -> tuple[dict[str, object], list[dict[str, object]]]:
    timing_by_key = {}
    records = []
    failures = []
    for summary in summaries:
        for timing in summary.get("timings", ()):
            if not isinstance(timing, dict):
                raise RuntimeError("development score timing record is invalid")
            timing_by_key[str(timing["judgment_key"])] = timing
        failures.extend(summary.get("judge_failures", ()))
        records.extend(summary.get("records", ()))
    if failures:
        raise RuntimeError(f"development scoring has terminal failures: {len(failures)}")
    if len(records) != 120 or len({row["judgment_key"] for row in records}) != 120:
        raise RuntimeError("development scoring does not have 120 unique records")
    if set(timing_by_key) != {str(row["judgment_key"]) for row in records}:
        raise RuntimeError("development scoring timing coverage is incomplete")

    usage_rows = []
    for record in records:
        evaluation = Path(str(record["evaluation_path"]))
        usage_path = evaluation.parent / "usage.json"
        usage = read_json(usage_path)
        call = usage.get("call")
        if not isinstance(call, dict):
            raise RuntimeError(f"saved usage call is invalid: {usage_path}")
        provider = str(call["provider"])
        raw_usage = call.get("raw_usage")
        tokens = usage_tokens(
            SimpleNamespace(provider=provider, provider_metadata={"usage": raw_usage})
        )
        cost = request_cost(str(record["model"]), **tokens) if tokens else None
        timing = timing_by_key[str(record["judgment_key"])]
        usage_rows.append({
            "judgment_key": record["judgment_key"],
            "task_id": record["task_id"],
            "replicate": record["replicate"],
            "condition_id": record["condition_id"],
            "model": record["model"],
            "provider": provider,
            "response_id": call.get("response_id"),
            "usage_available": tokens is not None,
            "input_tokens": tokens["input_tokens"] if tokens else None,
            "output_tokens": tokens["output_tokens"] if tokens else None,
            "cached_input_tokens": tokens["cached_input_tokens"] if tokens else None,
            "cache_write_input_tokens": (
                tokens["cache_write_input_tokens"] if tokens else None
            ),
            "usage_based_usd": cost,
            "worker_elapsed_seconds": timing["elapsed_seconds"],
            "reused_before_dispatch": timing["reused_before_dispatch"],
            "usage_path": str(usage_path),
        })

    model_summaries = []
    for model in MODELS:
        rows = [row for row in usage_rows if row["model"] == model]
        elapsed = sorted(float(row["worker_elapsed_seconds"]) for row in rows)
        available = [row for row in rows if row["usage_available"]]
        priced = [row for row in rows if row["usage_based_usd"] is not None]
        p95 = elapsed[max(0, math.ceil(0.95 * len(elapsed)) - 1)]
        model_summaries.append({
            "model": model,
            "judgments": len(rows),
            "responses_with_usage": len(available),
            "input_tokens": sum(int(row["input_tokens"]) for row in available),
            "output_tokens": sum(int(row["output_tokens"]) for row in available),
            "cached_input_tokens": sum(
                int(row["cached_input_tokens"]) for row in available
            ),
            "cache_write_input_tokens": sum(
                int(row["cache_write_input_tokens"]) for row in available
            ),
            "priced_responses": len(priced),
            "usage_based_usd": (
                sum(float(row["usage_based_usd"]) for row in priced)
                if len(priced) == len(rows)
                else None
            ),
            "worker_elapsed_seconds_mean": fmean(elapsed),
            "worker_elapsed_seconds_median": median(elapsed),
            "worker_elapsed_seconds_p95_nearest_rank": p95,
            "worker_elapsed_seconds_minimum": min(elapsed),
            "worker_elapsed_seconds_maximum": max(elapsed),
        })

    launch = read_json(RUN / "launch.json")
    completion = read_json(RUN / "completion.json")
    if (
        launch.get("revision_calls") != 0
        or completion.get("revision_calls") != 0
        or launch.get("evaluation_only") is not True
        or completion.get("status") != "completed"
        or completion.get("judgment_count") != 120
    ):
        raise RuntimeError("diagnostic launch/completion scope changed")
    started = datetime.fromisoformat(str(launch["started_at"]))
    finished = datetime.fromisoformat(str(completion["finished_at"]))
    owner_launches = [
        read_json(path) for path in sorted((RUN / "owners").glob("*/launch.json"))
    ]
    owner_completions = {
        str(value["slurm_job_id"]): value
        for path in sorted((RUN / "owners").glob("*/completion.json"))
        for value in (read_json(path),)
    }
    if not owner_launches:
        raise RuntimeError("diagnostic has no durable owner launch receipt")
    job_ids = sorted({str(value["slurm_job_id"]) for value in owner_launches})
    failed_attempts = sorted(RUN.glob("scores/**/failed-attempt-*.json"))
    attempt_states = sorted(RUN.glob("scores/**/attempt-*.json"))
    accounting = {
        "status": "completed",
        "source_commit": completion["source_commit"],
        "slurm_job_id": completion["slurm_job_id"],
        "slurm_job_ids": job_ids,
        "owner_launch_count": len(owner_launches),
        "owner_completion_count": len(owner_completions),
        "output_root": str(RUN),
        "models": list(MODELS),
        "assignments": 60,
        "planned_semantic_judgments": 120,
        "successful_semantic_judgments": 120,
        "failures": 0,
        "abstentions": 0,
        "revision_calls": 0,
        "max_concurrency": completion["max_concurrency"],
        "saved_before_launch": completion["saved_semantic_judgment_count"],
        "missing_before_launch": completion["missing_semantic_judgment_count"],
        "wall_seconds": (finished - started).total_seconds(),
        "pricing_registry_date": PRICING_AS_OF,
        "model_usage_and_latency": model_summaries,
        "total_known_usage_based_usd": sum(
            float(row["usage_based_usd"])
            for row in usage_rows
            if row["usage_based_usd"] is not None
        ),
        "unpriced_models": sorted({
            str(row["model"])
            for row in usage_rows
            if row["usage_based_usd"] is None
        }),
        "failed_attempt_files": [str(path) for path in failed_attempts],
        "attempt_state_files": [str(path) for path in attempt_states],
        "latency_definition": (
            "per-judgment worker elapsed time after executor provider admission; "
            "includes native local validation, provider call, and native retries"
        ),
        "cost_limitations": (
            "usage-based repository estimates are not invoices; models absent "
            "from the dated pricing registry remain unpriced"
        ),
    }
    return accounting, usage_rows


def main() -> None:
    model_points, artifact_points, summaries = build_points()
    arm_condition_means = grouped_means(
        artifact_points, ("arm", "condition")
    )
    task_means = grouped_means(
        artifact_points, ("arm", "condition", "task_id")
    )
    paired = paired_rows(artifact_points, include_model=False)
    model_paired = paired_rows(model_points, include_model=True)
    paired_task_groups: dict[
        tuple[str, str], list[dict[str, object]]
    ] = defaultdict(list)
    for row in paired:
        paired_task_groups[(str(row["arm"]), str(row["task_id"]))].append(row)
    paired_task_means = []
    for (arm, task), members in sorted(paired_task_groups.items()):
        item: dict[str, object] = {
            "arm": arm,
            "task_id": task,
            "n": len(members),
        }
        for metric in METRICS:
            item[f"delta_{metric}"] = fmean(
                float(row[f"delta_{metric}"]) for row in members
            )
        paired_task_means.append(item)
    paired_arm_means = []
    by_arm: dict[str, list[dict[str, object]]] = defaultdict(list)
    for row in paired:
        by_arm[str(row["arm"])].append(row)
    for arm, members in sorted(by_arm.items()):
        item: dict[str, object] = {"arm": arm, "n": len(members)}
        for metric in METRICS:
            item[f"delta_{metric}"] = fmean(
                float(row[f"delta_{metric}"]) for row in members
            )
        paired_arm_means.append(item)
    uncertainty = uncertainty_rows(
        artifact_points, task_means, paired, paired_task_means
    )
    accounting, usage_rows = usage_and_latency(summaries)

    write_csv("model-points.csv", model_points)
    write_csv("artifact-points.csv", artifact_points)
    write_csv("arm-condition-means.csv", arm_condition_means)
    write_csv("task-means.csv", task_means)
    write_csv("paired-rtt-static-differences.csv", paired)
    write_csv("model-paired-rtt-static-differences.csv", model_paired)
    write_csv("paired-task-means.csv", paired_task_means)
    write_csv("uncertainty.csv", uncertainty)
    write_csv("usage-and-latency.csv", usage_rows)
    write_json("accounting.json", accounting)
    write_json("analysis.json", {
        "complete": True,
        "question": "S-H = (S-D) + (D-H) for five Result40 mechanism tasks",
        "panel": "equal-weight gpt-5.6-sol plus gemini-3.8-flash",
        "tasks": list(TASKS),
        "coverage": accounting,
        "arm_condition_means": arm_condition_means,
        "task_means": task_means,
        "paired_rtt_static_means": paired_arm_means,
        "paired_task_means": paired_task_means,
        "uncertainty": uncertainty,
        "definitions": {
            "S": "saved final artifact under selected rubric variant 0",
            "D": "same saved final artifact under development rubric variant 1",
            "H": "same saved final artifact under rigorous held-out rubrics",
            "differences": "signed score points; paired treatment differences are RTT minus static",
            "sd_se": "sample SD and descriptive SE; task-cluster rows use five task means",
        },
    })
    print(json.dumps({
        "artifact_points": len(artifact_points),
        "model_points": len(model_points),
        "judgments": accounting["successful_semantic_judgments"],
        "failures": accounting["failures"],
        "revision_calls": accounting["revision_calls"],
        "report": str(REPORT),
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
