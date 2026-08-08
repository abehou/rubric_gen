"""YAML-defined randomized BiomniBench experiment DAGs."""

from __future__ import annotations

import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from rubric_gen.biomnibench.agent.models import AgentRunConfig
from rubric_gen.biomnibench.agent.prompts import PromptProfile
from rubric_gen.biomnibench.forensics.protocol import outcome_audit_protocol
from rubric_gen.biomnibench.revision.evolution import RubricEvolution
from rubric_gen.biomnibench.revision.feedback import FeedbackPolicy


EXPERIMENT_SCHEMA_VERSION = 1
EXPERIMENT_KIND = "rubric-gen-randomized-experiment"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,79}\Z")


@dataclass(frozen=True)
class Experiment:
    path: Path
    payload: dict[str, Any]

    @property
    def experiment_id(self) -> str:
        return str(self.payload["experiment_id"])

    @property
    def tasks_dir(self) -> Path:
        return Path(str(self.payload["tasks_dir"]))

    @property
    def task_ids(self) -> tuple[str, ...]:
        return tuple(str(value) for value in self.payload["tasks"])

    @property
    def replicates(self) -> int:
        return int(self.payload["randomization"]["replicates"])

    @property
    def assignments(self) -> tuple[dict[str, object], ...]:
        return tuple(self.payload["assignments"])

    @property
    def protocol(self) -> dict[str, object]:
        return self.payload["protocol"]

    @property
    def outcome_audit(self) -> dict[str, object]:
        return self.payload["outcome_audit"]

    @property
    def dag(self) -> dict[str, dict[str, object]]:
        return self.payload["dag"]

    def condition(self, condition_id: str) -> dict[str, object]:
        matches = [
            value for value in self.payload["conditions"]
            if value["condition_id"] == condition_id
        ]
        if len(matches) != 1:
            raise ValueError(f"unknown condition: {condition_id}")
        return matches[0]

    def task_dir(self, task_id: str) -> Path:
        if task_id not in self.task_ids:
            raise ValueError(f"task is not in experiment: {task_id}")
        return self.tasks_dir / task_id

    def agent_config(
        self,
        *,
        quiet: bool = False,
        vllm_endpoints: dict[str, str] | None = None,
    ) -> AgentRunConfig:
        value = self.protocol["solver"]
        provider = str(value["provider"])
        model = str(value["model"])
        base_url = None
        if provider == "vllm":
            base_url = (vllm_endpoints or {}).get(model)
            if base_url is None:
                raise ValueError(
                    f"solver model {model!r} requires a matching --vllm endpoint"
                )
        return AgentRunConfig(
            provider=provider,
            model=model,
            base_url=base_url,
            reasoning_effort=_optional_string(value.get("reasoning_effort")),
            service_tier=_optional_string(value.get("service_tier")),
            executable=_optional_string(value.get("executable")),
            retries=int(value["retries"]),
            timeout_seconds=int(value["timeout_seconds"]),
            quiet=quiet,
        )


def load_experiment(path: Path) -> Experiment:
    resolved = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"experiment must be a regular YAML file: {path}")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("experiment YAML must contain a mapping")
    payload: dict[str, Any] = value
    _validate(payload, resolved)
    payload["tasks_dir"] = str(_resolve_relative(resolved, payload["tasks_dir"]))
    for stage in payload["dag"].values():
        stage["output_dir"] = str(_resolve_relative(resolved, stage["output_dir"]))
    payload["assignments"] = _randomized_assignments(payload)
    return Experiment(resolved, payload)


def _validate(payload: dict[str, Any], path: Path) -> None:
    required = {
        "schema_version", "kind", "experiment_id", "tasks_dir", "tasks",
        "randomization", "conditions", "protocol", "outcome_audit", "dag",
    }
    if set(payload) != required:
        raise ValueError(f"experiment keys must be exactly {sorted(required)}")
    if payload["schema_version"] != EXPERIMENT_SCHEMA_VERSION:
        raise ValueError("unsupported experiment schema version")
    if payload["kind"] != EXPERIMENT_KIND:
        raise ValueError("unsupported experiment kind")
    if not isinstance(payload["experiment_id"], str) or not _ID.fullmatch(payload["experiment_id"]):
        raise ValueError("experiment_id is invalid")
    tasks_dir = _resolve_relative(path, payload["tasks_dir"])
    tasks = payload["tasks"]
    if not isinstance(tasks, list) or not tasks or any(
        not isinstance(item, str) or Path(item).name != item for item in tasks
    ) or len(tasks) != len(set(tasks)):
        raise ValueError("tasks must be unique safe task IDs")
    for task_id in tasks:
        task = tasks_dir / task_id
        for required_path in (
            task / "instruction.md", task / "environment" / "data",
            task / "tests" / "rubric.txt",
        ):
            if required_path.is_symlink() or not required_path.exists():
                raise ValueError(f"task input is missing or symlinked: {required_path}")
    randomization = payload["randomization"]
    if not isinstance(randomization, dict) or set(randomization) != {"seed", "replicates"}:
        raise ValueError("randomization requires seed and replicates")
    if type(randomization["seed"]) is not int:
        raise ValueError("randomization seed must be an integer")
    if type(randomization["replicates"]) is not int or randomization["replicates"] < 1:
        raise ValueError("replicates must be positive")
    conditions = payload["conditions"]
    if not isinstance(conditions, list) or not conditions:
        raise ValueError("conditions must be a non-empty list")
    condition_ids: list[str] = []
    for condition in conditions:
        if not isinstance(condition, dict) or set(condition) != {
            "condition_id", "prompt", "rubric_evolution"
        }:
            raise ValueError("each condition requires condition_id, prompt, and rubric_evolution")
        condition_ids.append(str(condition["condition_id"]))
        PromptProfile(str(condition["prompt"]))
        RubricEvolution(str(condition["rubric_evolution"]))
    if len(condition_ids) != len(set(condition_ids)) or any(
        not _ID.fullmatch(value) for value in condition_ids
    ):
        raise ValueError("condition IDs must be unique portable identifiers")
    _validate_protocol(payload["protocol"])
    audit = payload["outcome_audit"]
    if not isinstance(audit, dict):
        raise ValueError("outcome_audit must be a mapping")
    expected_audit = outcome_audit_protocol(
        models=tuple(str(model) for model in audit.get("models", ())),
        primary_rule=str(audit.get("primary_rule")),
        max_input_tokens=int(audit.get("max_input_tokens", 250_000)),
        max_output_tokens=int(audit.get("max_output_tokens", 4_096)),
        max_event_text_chars=int(audit.get("max_event_text_chars", 65_536)),
        max_command_output_chars=int(audit.get("max_command_output_chars", 2_048)),
        max_retries=int(audit.get("max_retries", 1)),
        max_cost_usd=float(audit.get("max_cost_usd", 1_500.0)),
    )
    # The YAML is concise; stable detector mechanics are supplied by the implementation.
    payload["outcome_audit"] = expected_audit
    dag = payload["dag"]
    if not isinstance(dag, dict) or set(dag) != {"seed", "revise", "detect"}:
        raise ValueError("dag must contain exactly seed, revise, and detect")
    expected_dependencies = {"seed": [], "revise": ["seed"], "detect": ["revise"]}
    for name, dependencies in expected_dependencies.items():
        stage = dag[name]
        if not isinstance(stage, dict) or set(stage) != {"depends_on", "output_dir"}:
            raise ValueError(f"dag stage {name} requires depends_on and output_dir")
        if stage["depends_on"] != dependencies:
            raise ValueError(f"dag stage {name} has invalid dependencies")
        _resolve_relative(path, stage["output_dir"])


def _validate_protocol(protocol: object) -> None:
    required = {
        "revision_rounds", "feedback_policy", "solver", "judge_model",
        "judge_max_retries", "rubric_name", "review", "max_review_chars",
        "rubric_proposer_model", "rubric_proposer_step_limit",
        "rubric_proposer_max_retries",
    }
    if not isinstance(protocol, dict) or set(protocol) != required:
        raise ValueError(f"protocol keys must be exactly {sorted(required)}")
    if type(protocol["revision_rounds"]) is not int or protocol["revision_rounds"] < 1:
        raise ValueError("revision_rounds must be positive")
    FeedbackPolicy(str(protocol["feedback_policy"]))
    if protocol["review"] not in {"trace", "trajectory"}:
        raise ValueError("review must be trace or trajectory")
    solver = protocol["solver"]
    if not isinstance(solver, dict):
        raise ValueError("solver must be a mapping")
    AgentRunConfig(
        provider=str(solver.get("provider")), model=str(solver.get("model")),
        reasoning_effort=_optional_string(solver.get("reasoning_effort")),
        service_tier=_optional_string(solver.get("service_tier")),
        executable=_optional_string(solver.get("executable")),
        retries=int(solver.get("retries", 1)),
        timeout_seconds=int(solver.get("timeout_seconds", 7_200)),
    )


def _randomized_assignments(payload: dict[str, Any]) -> list[dict[str, object]]:
    rng = random.Random(payload["randomization"]["seed"])
    assignments: list[dict[str, object]] = []
    for replicate in range(1, payload["randomization"]["replicates"] + 1):
        for task_id in payload["tasks"]:
            conditions = list(payload["conditions"])
            rng.shuffle(conditions)
            for within_block_order, condition in enumerate(conditions, start=1):
                condition_id = str(condition["condition_id"])
                assignments.append({
                    "assignment_id": f"{task_id}--rep-{replicate:03d}--{condition_id}",
                    "task_id": task_id,
                    "replicate": replicate,
                    "condition_id": condition_id,
                    "within_block_order": within_block_order,
                })
    rng.shuffle(assignments)
    for execution_order, assignment in enumerate(assignments, start=1):
        assignment["execution_order"] = execution_order
    return assignments


def _resolve_relative(experiment_path: Path, value: object) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("experiment paths must be non-empty strings")
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (experiment_path.parent / path).resolve()


def _optional_string(value: object) -> str | None:
    return None if value is None else str(value)
