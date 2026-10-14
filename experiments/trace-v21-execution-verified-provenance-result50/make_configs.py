"""Build the ten-task Result50 extension configs on a Babel compute node."""

from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path

import yaml


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
EXECUTION_BUNDLE = Path(
    os.environ.get(
        "RESULT50_CONFIG_BUNDLE",
        "/data/user_data/aydanh/rubric_gen/runs/"
        "rtt-result50-extension-20260921/config-bundle",
    )
).resolve()
RUN = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-result50-extension-20260921"
)
RESULT45_DATA = Path(
    "/data/user_data/aydanh/rubric_gen/data/"
    "biomnibench-da-results45-e1c8ca5e11a6"
)
SUPPLEMENT_DATA = Path(
    "/data/user_data/aydanh/rubric_gen/data/"
    "biomnibench-da-result50-supplement-e1c8ca5e11a6"
)
OLD_RUN = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "biomnibench-v21-to45-20260912/results45-added15"
)

MEMBERSHIP = json.loads((BUNDLE / "membership.json").read_text())
TASKS = tuple(MEMBERSHIP["added10"])
RESULT45_TASKS = TASKS[:5]
GENERATED_INPUT_TASKS = TASKS[5:]
CONDITIONS = tuple(MEMBERSHIP["conditions"])
SHARDS = tuple((task, kind) for task in TASKS for kind in ("static", "trace"))
PANEL = ("gpt-5.6-sol", "gemini-3.8-flash")
CANDIDATE = "attack_defense_v2.1_execution_verified_proactive_provenance"


def task_root(task: str) -> Path:
    return RESULT45_DATA if task in RESULT45_TASKS else SUPPLEMENT_DATA


def input_roots(task: str) -> tuple[Path, Path]:
    if task in RESULT45_TASKS:
        root = OLD_RUN / task / "inputs"
        return root / "seeds", root / "paraphrases"
    root = RUN / "inputs" / task
    return root / "seeds", root / "paraphrases"


def config_path(task: str, kind: str) -> Path:
    return EXECUTION_BUNDLE / "configs" / f"{task}-{kind}.yaml"


def pretreatment_sources() -> dict[str, dict[str, str]]:
    # No prior study used the Result50 seed/input identity. The three Dev3
    # studies used seed 20260806, so their generation-1 artifacts are not a
    # compatible source for the required Result50 seed 20260820.
    return {}


def main() -> None:
    if len(TASKS) != 10 or len(set(TASKS)) != 10:
        raise RuntimeError("Result50 extension membership must contain ten unique tasks")
    base = yaml.safe_load(
        (
            ROOT
            / "experiments/trace-v21-execution-verified-provenance-result20/result20.yaml"
        ).read_text()
    )
    sources = pretreatment_sources()
    configs = EXECUTION_BUNDLE / "configs"
    configs.mkdir(parents=True, exist_ok=True)
    static_conditions = [
        {"condition_id": "full-static", "feedback_policy": "full", "rubric_policy": "fixed"},
        {"condition_id": "user-simulator-static", "feedback_policy": "user_simulator", "rubric_policy": "fixed"},
    ]
    trace_conditions = [
        {
            "condition_id": "full-red-team-trace-execution-verified-proactive-provenance",
            "feedback_policy": "full",
            "rubric_policy": "red_team_trace",
        },
        {
            "condition_id": "user-simulator-red-team-trace-execution-verified-proactive-provenance",
            "feedback_policy": "user_simulator",
            "rubric_policy": "red_team_trace",
        },
    ]
    for task, kind in SHARDS:
        data = deepcopy(base)
        data.pop("pretreatment_source", None)
        data["tasks_dir"] = str(task_root(task))
        data["tasks"] = [task]
        conditions = static_conditions if kind == "static" else trace_conditions
        data["conditions"] = conditions
        data["execution_conditions"] = [row["condition_id"] for row in conditions]
        data["outcome_audit"]["models"] = list(PANEL)
        data["execution_audit_models"] = list(PANEL)
        if kind == "static":
            data["protocol"].pop("red_team_trace_version", None)
            data["protocol"].pop("rubric_proposer_reasoning_effort_by_stage", None)
        elif task in sources:
            data["pretreatment_source"] = sources[task]
        seed_root, paraphrase_root = input_roots(task)
        data["dag"]["seed"]["output_dir"] = str(seed_root)
        data["dag"]["paraphrase"]["output_dir"] = str(paraphrase_root)
        data["dag"]["revise"]["output_dir"] = str(
            RUN / "study" / task / kind / "{experiment_id}"
        )
        data["dag"]["detect"]["output_dir"] = str(
            RUN / "audit" / task / kind / "{experiment_id}"
        )
        config_path(task, kind).write_text(yaml.safe_dump(data, sort_keys=False))
    expected = {config_path(task, kind) for task, kind in SHARDS}
    for stale in configs.glob("*.yaml"):
        if stale not in expected:
            stale.unlink()
    (EXECUTION_BUNDLE / "pretreatment-sources.json").write_text(
        json.dumps(sources, indent=2, sort_keys=True) + "\n"
    )
    print(json.dumps({
        "tasks": list(TASKS),
        "assignments": len(TASKS) * 12,
        "configs": len(expected),
        "pretreatment_sources": sorted(sources),
    }))


if __name__ == "__main__":
    main()
