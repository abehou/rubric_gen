"""YAML-defined randomized submission-revision experiment DAGs."""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml

from rubric_gen.runtime.agents.models import AgentRunConfig
from rubric_gen.submission_revision.prompts import PromptProfile
from rubric_gen.evidence.protocol import outcome_audit_protocol
from rubric_gen.submission_revision.evolution import RubricEvolution
from rubric_gen.submission_revision.feedback import FeedbackPolicy
from rubric_gen.submission_revision.user_simulator import SimulatedUserConfig
from rubric_gen.benchmarks import Benchmark, get_benchmark
from rubric_gen.artifacts.hashing import sha256_text


EXPERIMENT_SCHEMA_VERSION = 5
EXPERIMENT_KIND = "rubric-gen-randomized-experiment"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,79}\Z")
EXPERIMENT_ID_TOKEN = "{experiment_id}"
_IDENTITY_KEYS = (
    "schema_version",
    "kind",
    "benchmark",
    "tasks_dir",
    "tasks",
    "randomization",
    "conditions",
    "protocol",
    "rubric_paraphrases",
    "outcome_audit",
)


@dataclass(frozen=True)
class Experiment:
    path: Path
    payload: dict[str, Any]

    @property
    def experiment_id(self) -> str:
        return str(self.payload["experiment_id"])

    @property
    def benchmark(self) -> Benchmark:
        return Benchmark(str(self.payload["benchmark"]))

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
    def rubric_paraphrases(self) -> dict[str, object]:
        return self.payload["rubric_paraphrases"]

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

    def feedback_simulator_config(
        self,
        *,
        vllm_endpoints: dict[str, str] | None = None,
    ) -> SimulatedUserConfig | None:
        if FeedbackPolicy(str(self.protocol["feedback_policy"])) is not (
            FeedbackPolicy.SIMULATED_USER
        ):
            return None
        value = self.protocol["feedback_simulator"]
        assert isinstance(value, dict)
        model = str(value["model"])
        return SimulatedUserConfig(
            model=model,
            base_url=(vllm_endpoints or {}).get(model),
            max_output_tokens=value["max_output_tokens"],
            max_aspects=value["max_aspects"],
            max_retries=value["max_retries"],
        )


def load_experiment(path: Path) -> Experiment:
    resolved = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"experiment must be a regular YAML file: {path}")
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("experiment YAML must contain a mapping")
    payload: dict[str, Any] = value
    experiment_id = _validate(payload, resolved)
    payload["experiment_id"] = experiment_id
    payload["tasks_dir"] = str(_resolve_relative(resolved, payload["tasks_dir"]))
    for stage in payload["dag"].values():
        output_dir = str(stage["output_dir"]).replace(
            EXPERIMENT_ID_TOKEN, experiment_id
        )
        stage["output_dir"] = str(_resolve_relative(resolved, output_dir))
    payload["assignments"] = _randomized_assignments(payload)
    return Experiment(resolved, payload)


def _validate(payload: dict[str, Any], path: Path) -> str:
    required = {
        "schema_version", "kind", "benchmark", "tasks_dir", "tasks",
        "randomization", "conditions", "protocol", "rubric_paraphrases",
        "outcome_audit", "dag",
    }
    if set(payload) != required:
        raise ValueError(f"experiment keys must be exactly {sorted(required)}")
    if payload["schema_version"] != EXPERIMENT_SCHEMA_VERSION:
        raise ValueError("unsupported experiment schema version")
    if payload["kind"] != EXPERIMENT_KIND:
        raise ValueError("unsupported experiment kind")
    benchmark = Benchmark(str(payload["benchmark"]))
    contract = get_benchmark(benchmark)
    experiment_id = _derived_experiment_id(payload)
    tasks_dir = _resolve_relative(path, payload["tasks_dir"])
    tasks = payload["tasks"]
    if not isinstance(tasks, list) or not tasks or any(
        not isinstance(item, str) or Path(item).name != item for item in tasks
    ) or len(tasks) != len(set(tasks)):
        raise ValueError("tasks must be unique safe task IDs")
    contract.validate_experiment(tasks_dir, tuple(tasks))
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
    _validate_rubric_paraphrases(payload["rubric_paraphrases"])
    contract.validate_review(payload["protocol"]["review"])
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
    if not isinstance(dag, dict) or set(dag) != {
        "seed", "paraphrase", "revise", "detect"
    }:
        raise ValueError(
            "dag must contain exactly seed, paraphrase, revise, and detect"
        )
    expected_dependencies = {
        "seed": [],
        "paraphrase": [],
        "revise": ["seed", "paraphrase"],
        "detect": ["revise", "paraphrase"],
    }
    for name, dependencies in expected_dependencies.items():
        stage = dag[name]
        expected_keys = {"depends_on", "output_dir"}
        if not isinstance(stage, dict) or set(stage) != expected_keys:
            raise ValueError(f"dag stage {name} requires depends_on and output_dir")
        if stage["depends_on"] != dependencies:
            raise ValueError(f"dag stage {name} has invalid dependencies")
        output_dir = str(stage["output_dir"])
        token_count = output_dir.count(EXPERIMENT_ID_TOKEN)
        if name in {"seed", "paraphrase"} and token_count:
            raise ValueError(
                f"{name} output_dir must not contain {{experiment_id}}"
            )
        if name in {"revise", "detect"} and (
            token_count != 1 or Path(output_dir).name != EXPERIMENT_ID_TOKEN
        ):
            raise ValueError(
                f"dag stage {name} output_dir must end with {{experiment_id}}"
            )
        _resolve_relative(
            path,
            output_dir.replace(EXPERIMENT_ID_TOKEN, experiment_id),
        )
    return experiment_id


def _validate_rubric_paraphrases(value: object) -> None:
    if not isinstance(value, dict) or set(value) != {
        "count", "model", "max_retries"
    }:
        raise ValueError(
            "rubric_paraphrases requires count, model, and max_retries"
        )
    if type(value["count"]) is not int or value["count"] < 2:
        raise ValueError("rubric paraphrase count must be at least two")
    if type(value["model"]) is not str or not value["model"].strip():
        raise ValueError("rubric paraphrase model must be nonempty")
    if type(value["max_retries"]) is not int or value["max_retries"] < 0:
        raise ValueError("rubric paraphrase retries must be non-negative")


def _derived_experiment_id(payload: dict[str, Any]) -> str:
    """Derive one readable identity from the experiment's semantic YAML."""

    identity = {key: payload[key] for key in _IDENTITY_KEYS}
    digest = sha256_text(json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ))[:12]
    benchmark = str(payload["benchmark"])
    protocol = payload["protocol"]
    if not isinstance(protocol, dict):
        raise ValueError("protocol must be a mapping")
    feedback = str(protocol.get("feedback_policy", "invalid")).replace("_", "-")
    rounds = protocol.get("revision_rounds", "invalid")
    experiment_id = f"{benchmark}-{feedback}-r{rounds}-{digest}"
    if not _ID.fullmatch(experiment_id):
        raise ValueError("derived experiment ID is invalid")
    return experiment_id


def _validate_protocol(protocol: object) -> None:
    base_keys = {
        "revision_rounds", "feedback_policy", "solver", "judge_model",
        "judge_max_retries", "rubric_name", "review", "max_review_chars",
        "rubric_auditor_model", "rubric_auditor_query_limit",
        "rubric_proposer_model",
        "rubric_proposer_max_retries",
    }
    if not isinstance(protocol, dict):
        raise ValueError("protocol must be a mapping")
    feedback_policy = FeedbackPolicy(str(protocol.get("feedback_policy")))
    required = set(base_keys)
    if feedback_policy is FeedbackPolicy.SIMULATED_USER:
        required.add("feedback_simulator")
    if set(protocol) != required:
        raise ValueError(f"protocol keys must be exactly {sorted(required)}")
    if type(protocol["revision_rounds"]) is not int or protocol["revision_rounds"] < 1:
        raise ValueError("revision_rounds must be positive")
    if protocol["review"] not in {"trace", "trajectory", "workspace"}:
        raise ValueError("review must be trace, trajectory, or workspace")
    for name in ("rubric_auditor_model", "rubric_proposer_model"):
        if type(protocol[name]) is not str or not protocol[name].strip():
            raise ValueError(f"{name} must be nonempty")
    if (
        type(protocol["rubric_auditor_query_limit"]) is not int
        or protocol["rubric_auditor_query_limit"] < 1
    ):
        raise ValueError("rubric_auditor_query_limit must be positive")
    if (
        type(protocol["rubric_proposer_max_retries"]) is not int
        or protocol["rubric_proposer_max_retries"] < 0
    ):
        raise ValueError("rubric_proposer_max_retries must be non-negative")
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
    if feedback_policy is FeedbackPolicy.SIMULATED_USER:
        simulator = protocol["feedback_simulator"]
        simulator_keys = {
            "model",
            "max_output_tokens",
            "max_aspects",
            "max_retries",
        }
        if not isinstance(simulator, dict) or set(simulator) != simulator_keys:
            raise ValueError(
                "feedback_simulator keys must be exactly "
                f"{sorted(simulator_keys)}"
            )
        SimulatedUserConfig(
            model=simulator["model"],
            max_output_tokens=simulator["max_output_tokens"],
            max_aspects=simulator["max_aspects"],
            max_retries=simulator["max_retries"],
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
