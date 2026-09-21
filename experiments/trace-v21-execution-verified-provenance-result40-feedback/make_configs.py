"""Create Semi/Score-only native shards for the Results40 new-task block."""
from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path

import yaml

from rubric_gen.submission_revision.experiment import load_experiment

BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
EXECUTION_BUNDLE = Path(os.environ.get("RESULT40_CONFIG_BUNDLE", BUNDLE)).resolve()
MEMBERSHIP = json.loads((BUNDLE / "membership.json").read_text())
TASKS = tuple(MEMBERSHIP["new20"])
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/rtt-result40-feedback-policies-20260920")
OLD_ROOT = Path("/data/user_data/aydanh/rubric_gen/runs/biomnibench-v21-to45-20260912")
FULL_USER_BUNDLE = Path(
    "/home/aydanh/repos/rubric_gen/runs/babel-code/trace-result40-20260918/"
    "experiments/trace-v21-execution-verified-provenance-result40"
)
FULL_USER_RUN = Path(
    "/data/user_data/aydanh/rubric_gen/runs/rtt-result40-expansion-20260918"
)
CONDITIONS = (
    "semi-static-execution-provenance-high-proposer",
    "semi-red-team-trace-execution-provenance-high-proposer",
    "score-only-static-execution-provenance-high-proposer",
    "score-only-red-team-trace-execution-provenance-high-proposer",
)
SHARDS = tuple((task, kind) for task in TASKS for kind in ("static", "trace"))


def old_task_root(task: str) -> Path:
    block = "results30" if task in TASKS[:10] else "results45-added15"
    return OLD_ROOT / block / task


def source_config(task: str) -> Path:
    queue = "queue6" if task in TASKS[:10] else "queue7"
    return ROOT / "experiments" / "biomnibench-v21-to45" / queue / "configs" / f"{task}.yaml"


def config_path(task: str, kind: str) -> Path:
    return EXECUTION_BUNDLE / "configs" / f"{task}-{kind}.yaml"


def completed_trace_source(task: str) -> dict[str, str]:
    config = FULL_USER_BUNDLE / "configs" / f"{task}-trace.yaml"
    experiment = load_experiment(config)
    return {
        "experiment": str(config),
        "experiment_id": experiment.experiment_id,
        "study_dir": str(
            FULL_USER_RUN / "study" / task / "trace" / experiment.experiment_id
        ),
    }


def main() -> None:
    base = yaml.safe_load((
        ROOT / "experiments/trace-v21-execution-verified-provenance-result20-feedback/result20.yaml"
    ).read_text())
    sources = {task: completed_trace_source(task) for task in TASKS}
    configs = BUNDLE / "configs"
    configs.mkdir(exist_ok=True)
    static_conditions = [
        {
            "condition_id": "semi-static-execution-provenance-high-proposer",
            "feedback_policy": "semi",
            "rubric_policy": "fixed",
        },
        {
            "condition_id": "score-only-static-execution-provenance-high-proposer",
            "feedback_policy": "score_only",
            "rubric_policy": "fixed",
        },
    ]
    trace_conditions = [
        {
            "condition_id": "semi-red-team-trace-execution-provenance-high-proposer",
            "feedback_policy": "semi",
            "rubric_policy": "red_team_trace",
        },
        {
            "condition_id": "score-only-red-team-trace-execution-provenance-high-proposer",
            "feedback_policy": "score_only",
            "rubric_policy": "red_team_trace",
        },
    ]
    for task, kind in SHARDS:
        data = deepcopy(base)
        data.pop("pretreatment_source", None)
        data["tasks"] = [task]
        conditions = static_conditions if kind == "static" else trace_conditions
        data["conditions"] = conditions
        data["execution_conditions"] = [row["condition_id"] for row in conditions]
        data["outcome_audit"]["models"] = ["gpt-5.6-sol", "gemini-3.8-flash"]
        data["execution_audit_models"] = ["gpt-5.6-sol", "gemini-3.8-flash"]
        if kind == "static":
            data["protocol"].pop("red_team_trace_version", None)
            data["protocol"].pop("rubric_proposer_reasoning_effort_by_stage", None)
        old = old_task_root(task)
        data["dag"]["seed"]["output_dir"] = str(old / "inputs/seeds")
        data["dag"]["paraphrase"]["output_dir"] = str(old / "inputs/paraphrases")
        data["dag"]["revise"]["output_dir"] = str(RUN / "study" / task / kind / "{experiment_id}")
        data["dag"]["detect"]["output_dir"] = str(RUN / "audit" / task / kind / "{experiment_id}")
        if kind == "trace":
            data["pretreatment_source"] = sources[task]
        config_path(task, kind).write_text(yaml.safe_dump(data, sort_keys=False))
    for stale in configs.glob("*.yaml"):
        if stale not in {config_path(task, kind) for task, kind in SHARDS}:
            stale.unlink()
    print(json.dumps({
        "tasks": len(TASKS),
        "conditions": list(CONDITIONS),
        "assignments": len(TASKS) * 3 * len(CONDITIONS),
        "native_shards": len(SHARDS),
        "pretreatment_sources": sorted(sources),
    }))


if __name__ == "__main__":
    main()
