"""Create the five-task combined high-reasoning plus scheduling pilot."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path

import yaml


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
SOURCE = ROOT / "experiments/trace-v21-execution-verified-provenance-result40"
RUN = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-result40-gap-improvement-pilot-20260921"
)
TASKS = ("da-26-4", "da-26-2", "da-17-1", "da-17-5", "da-20-4")
SMOKE_TASK = "da-26-2"
CANDIDATE = (
    "attack_defense_v2.1_execution_verified_proactive_provenance_gap_improvement"
)
STAGE_EFFORTS = {
    "rubric_view": "high",
    "diagnosis": "high",
    "semantic": "high",
}
PANEL = ("gpt-5.6-sol", "gemini-3.8-flash")
CONDITIONS = (
    "full-red-team-trace-gap-improvement",
    "user-simulator-red-team-trace-gap-improvement",
)
PRETREATMENT_SOURCES = {
    "da-17-1": {
        "experiment": (
            "/home/aydanh/repos/rubric_gen/runs/babel-code/"
            "trace-result40-20260918/experiments/"
            "trace-v21-execution-verified-provenance-result40/configs/"
            "da-17-1-trace.yaml"
        ),
        "experiment_id": "biomnibench-da-factorial-r10-fa26b6b04e6a",
        "study_dir": (
            "/data/user_data/aydanh/rubric_gen/runs/"
            "rtt-result40-expansion-20260918/study/da-17-1/trace/"
            "biomnibench-da-factorial-r10-fa26b6b04e6a"
        ),
    },
    "da-17-5": {
        "experiment": (
            "/home/aydanh/repos/rubric_gen/runs/babel-code/"
            "trace-result40-20260918/experiments/"
            "trace-v21-execution-verified-provenance-result40/configs/"
            "da-17-5-trace.yaml"
        ),
        "experiment_id": "biomnibench-da-factorial-r10-52099c5260fd",
        "study_dir": (
            "/data/user_data/aydanh/rubric_gen/runs/"
            "rtt-result40-expansion-20260918/study/da-17-5/trace/"
            "biomnibench-da-factorial-r10-52099c5260fd"
        ),
    },
}


def config_path(task: str) -> Path:
    return BUNDLE / "configs" / f"{task}.yaml"


def main() -> None:
    configs = BUNDLE / "configs"
    configs.mkdir(exist_ok=True)
    for task in TASKS:
        source = SOURCE / "configs" / f"{task}-trace.yaml"
        data = deepcopy(yaml.safe_load(source.read_text()))
        if data["tasks"] != [task]:
            raise RuntimeError(f"source task scope changed: {source}")
        if data["solvers"] != [{
            "solver_id": "luna",
            "provider": "codex",
            "model": "gpt-5.6-luna",
            "reasoning_effort": "low",
            "service_tier": None,
            "executable": None,
            "retries": 1,
            "timeout_seconds": 7200,
        }]:
            raise RuntimeError(f"source solver control changed: {source}")
        data["conditions"] = [
            {
                "condition_id": CONDITIONS[0],
                "feedback_policy": "full",
                "rubric_policy": "red_team_trace",
            },
            {
                "condition_id": CONDITIONS[1],
                "feedback_policy": "user_simulator",
                "rubric_policy": "red_team_trace",
            },
        ]
        data["execution_conditions"] = list(CONDITIONS)
        data["protocol"]["red_team_trace_version"] = CANDIDATE
        data["protocol"]["rubric_proposer_reasoning_effort_by_stage"] = (
            dict(STAGE_EFFORTS)
        )
        data["outcome_audit"]["models"] = list(PANEL)
        data["execution_audit_models"] = list(PANEL)
        if task in PRETREATMENT_SOURCES:
            data["pretreatment_source"] = deepcopy(PRETREATMENT_SOURCES[task])
        data["dag"]["revise"]["output_dir"] = str(
            RUN / "study" / task / "{experiment_id}"
        )
        data["dag"]["detect"]["output_dir"] = str(
            RUN / "audit" / task / "{experiment_id}"
        )
        config_path(task).write_text(yaml.safe_dump(data, sort_keys=False))
    expected = {config_path(task) for task in TASKS}
    for stale in configs.glob("*.yaml"):
        if stale not in expected:
            stale.unlink()


if __name__ == "__main__":
    main()
