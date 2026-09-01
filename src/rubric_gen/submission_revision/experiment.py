"""YAML-defined randomized submission-revision experiment DAGs."""

from __future__ import annotations

import json
import random
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from rubric_gen.runtime.agents.models import AgentRunConfig
from rubric_gen.runtime.agents.adapters import AgentAdapterRegistry
from rubric_gen.runtime.yaml import load_yaml_strict
from rubric_gen.submission_revision.prompts import PromptProfile
from rubric_gen.submission_revision.evaluation.config import outcome_audit_protocol
from rubric_gen.submission_revision.rubric_generation import CompleteRubric, RubricPolicy
from rubric_gen.submission_revision.feedback import FeedbackPolicy
from rubric_gen.submission_revision.user_simulator import SimulatedUserConfig
from rubric_gen.submission_revision.judging.models import safe_basename
from rubric_gen.benchmarks import SubmissionBenchmarkId, get_submission_benchmark
from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.submission_revision.assignments import ExperimentAssignment
from rubric_gen.submission_revision.detection_windows import (
    MINIMUM_POST_UPDATE_REVISIONS,
)


EXPERIMENT_KIND = "rubric-gen-randomized-experiment"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,79}\Z")
EXPERIMENT_ID_TOKEN = "{experiment_id}"
_RUBRIC_POLICY_SLUGS = {
    RubricPolicy.FIXED: "static",
    RubricPolicy.OFFLINE_ELICITATION: "offline-rubric",
    RubricPolicy.ONLINE_ELICITATION: "online-rubric",
}
_IDENTITY_KEYS = (
    "kind",
    "benchmark",
    "tasks_dir",
    "tasks",
    "randomization",
    "seed_generator",
    "solvers",
    "conditions",
    "assignment_selection",
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
    def benchmark(self) -> SubmissionBenchmarkId:
        return SubmissionBenchmarkId(str(self.payload["benchmark"]))

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
    def assignments(self) -> tuple[ExperimentAssignment, ...]:
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

    @property
    def solver_ids(self) -> tuple[str, ...]:
        return tuple(str(value["solver_id"]) for value in self.payload["solvers"])

    def seed_agent_config(
        self,
        *,
        quiet: bool = False,
    ) -> AgentRunConfig:
        return _agent_run_config(self.payload["seed_generator"], quiet=quiet)

    def solver_config(
        self,
        solver_id: str,
        *,
        quiet: bool = False,
    ) -> AgentRunConfig:
        matches = [
            value for value in self.payload["solvers"]
            if value["solver_id"] == solver_id
        ]
        if len(matches) != 1:
            raise ValueError(f"unknown solver: {solver_id}")
        value = dict(matches[0])
        value.pop("solver_id")
        return _agent_run_config(value, quiet=quiet)

    def feedback_simulator_config(
        self,
        feedback_policy: FeedbackPolicy | str,
    ) -> SimulatedUserConfig | None:
        if FeedbackPolicy(feedback_policy) is not FeedbackPolicy.USER_SIMULATOR:
            return None
        value = self.protocol["feedback_simulator"]
        assert isinstance(value, dict)
        model = value["model"]
        assert isinstance(model, str)
        return SimulatedUserConfig(
            model=model,
            max_output_tokens=value["max_output_tokens"],
            max_concerns=value["max_concerns"],
            max_history_bytes=value["max_history_bytes"],
            max_request_bytes=value["max_request_bytes"],
            max_retries=value["max_retries"],
        )


def _agent_run_config(value: object, *, quiet: bool) -> AgentRunConfig:
    if not isinstance(value, dict):
        raise ValueError("agent configuration must be a mapping")
    provider = value["provider"]
    model = value["model"]
    assert isinstance(provider, str) and isinstance(model, str)
    return AgentRunConfig(
        provider=provider,
        model=model,
        reasoning_effort=_optional_string(value.get("reasoning_effort")),
        service_tier=_optional_string(value.get("service_tier")),
        executable=_optional_string(value.get("executable")),
        retries=value["retries"],
        timeout_seconds=value["timeout_seconds"],
        quiet=quiet,
    )

def load_experiment(path: Path) -> Experiment:
    resolved = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"experiment must be a regular YAML file: {path}")
    value = load_yaml_strict(path.read_text(encoding="utf-8"))
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
        "kind", "benchmark", "tasks_dir", "tasks",
        "randomization", "seed_generator", "solvers", "conditions",
        "assignment_selection", "protocol",
        "rubric_paraphrases", "outcome_audit", "dag",
    }
    if set(payload) != required:
        raise ValueError(f"experiment keys must be exactly {sorted(required)}")
    if payload["kind"] != EXPERIMENT_KIND:
        raise ValueError("unsupported experiment kind")
    benchmark = SubmissionBenchmarkId(str(payload["benchmark"]))
    contract = get_submission_benchmark(benchmark)
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
    if type(randomization["replicates"]) is not int or randomization["replicates"] < 3:
        raise ValueError(
            "criterion elicitation requires at least three replicates"
        )
    _validate_agent(payload["seed_generator"], "seed_generator")
    solvers = payload["solvers"]
    if not isinstance(solvers, list) or not solvers:
        raise ValueError("solvers must be a non-empty list")
    solver_ids: list[str] = []
    for solver in solvers:
        if not isinstance(solver, dict) or "solver_id" not in solver:
            raise ValueError("each solver requires solver_id and agent fields")
        solver_id = solver["solver_id"]
        if type(solver_id) is not str or not _ID.fullmatch(solver_id):
            raise ValueError("solver_id must be a portable identifier")
        _validate_agent(
            {key: value for key, value in solver.items() if key != "solver_id"},
            f"solver {solver_id}",
        )
        solver_ids.append(solver_id)
    if len(solver_ids) != len(set(solver_ids)):
        raise ValueError("solver IDs must be unique")
    conditions = payload["conditions"]
    if not isinstance(conditions, list) or not conditions:
        raise ValueError("conditions must be a non-empty list")
    condition_ids: list[str] = []
    condition_pairs: list[tuple[FeedbackPolicy, RubricPolicy]] = []
    for condition in conditions:
        if not isinstance(condition, dict) or set(condition) != {
            "condition_id", "feedback_policy", "rubric_policy"
        }:
            raise ValueError(
                "each condition requires condition_id, feedback_policy, and "
                "rubric_policy"
            )
        condition_id = condition["condition_id"]
        feedback_policy = condition["feedback_policy"]
        rubric_policy = condition["rubric_policy"]
        if type(condition_id) is not str or not condition_id:
            raise ValueError("condition_id must be a nonempty string")
        if type(feedback_policy) is not str:
            raise ValueError("condition feedback_policy must be a string")
        if type(rubric_policy) is not str:
            raise ValueError("condition rubric_policy must be a string")
        resolved_feedback = FeedbackPolicy(feedback_policy)
        resolved_rubric = RubricPolicy(rubric_policy)
        expected_id = (
            f"{resolved_feedback.value.replace('_', '-')}-"
            f"{_RUBRIC_POLICY_SLUGS[resolved_rubric]}"
        )
        if condition_id != expected_id:
            raise ValueError(
                f"condition_id must be {expected_id!r} for its policies"
            )
        condition_ids.append(condition_id)
        condition_pairs.append((resolved_feedback, resolved_rubric))
    if len(condition_ids) != len(set(condition_ids)) or any(
        not _ID.fullmatch(value) for value in condition_ids
    ):
        raise ValueError("condition IDs must be unique portable identifiers")
    selected_feedback_policies = {
        feedback_policy for feedback_policy, _ in condition_pairs
    }
    selected_rubric_policies = {
        rubric_policy for _, rubric_policy in condition_pairs
    }
    expected_pairs = {
        (feedback_policy, rubric_policy)
        for feedback_policy in selected_feedback_policies
        for rubric_policy in selected_rubric_policies
    }
    if (
        len(condition_pairs) != len(expected_pairs)
        or set(condition_pairs) != expected_pairs
    ):
        raise ValueError(
            "conditions must contain exactly one arm for each selected "
            "feedback-policy and rubric-policy pair"
        )
    _validate_assignment_selection(payload)
    _validate_protocol(payload["protocol"])
    _validate_master_rubrics(
        tasks_dir,
        tuple(tasks),
        str(payload["protocol"]["rubric_name"]),
    )
    _validate_rubric_paraphrases(payload["rubric_paraphrases"])
    contract.validate_review(payload["protocol"]["review"])
    audit = payload["outcome_audit"]
    if not isinstance(audit, dict):
        raise ValueError("outcome_audit must be a mapping")
    required_audit_keys = {
        "models",
        "primary_rule",
        "loss_weights",
        "rubric_score_max_calls",
        "rubric_score_max_request_bytes",
        "rubric_score_max_output_tokens",
        "rubric_free_evaluation_max_calls",
        "rubric_free_evaluation_max_request_bytes",
        "rubric_free_evaluation_max_output_tokens",
    }
    optional_audit_keys = {
        "max_input_tokens",
        "max_output_tokens",
    }
    if not required_audit_keys <= set(audit) or not set(audit) <= (
        required_audit_keys | optional_audit_keys
    ):
        raise ValueError(
            "outcome_audit keys must be exactly the required models, primary_rule, "
            "loss_weights and stage caps, plus supported "
            "input limits"
        )
    audit_models = audit["models"]
    if not isinstance(audit_models, list) or any(
        type(model) is not str for model in audit_models
    ):
        raise ValueError("outcome_audit models must be a list of strings")
    if type(audit["primary_rule"]) is not str:
        raise ValueError("outcome_audit primary_rule must be a string")
    expected_audit = outcome_audit_protocol(
        models=tuple(audit_models),
        primary_rule=audit["primary_rule"],
        loss_weights=audit["loss_weights"],
        max_input_tokens=audit.get("max_input_tokens", 250_000),
        max_output_tokens=audit.get("max_output_tokens", 4_096),
        rubric_score_max_calls=audit["rubric_score_max_calls"],
        rubric_score_max_request_bytes=audit[
            "rubric_score_max_request_bytes"
        ],
        rubric_score_max_output_tokens=audit[
            "rubric_score_max_output_tokens"
        ],
        rubric_free_evaluation_max_calls=audit["rubric_free_evaluation_max_calls"],
        rubric_free_evaluation_max_request_bytes=audit["rubric_free_evaluation_max_request_bytes"],
        rubric_free_evaluation_max_output_tokens=audit["rubric_free_evaluation_max_output_tokens"],
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
        output_value = stage["output_dir"]
        if type(output_value) is not str or not output_value.strip():
            raise ValueError(f"dag stage {name} output_dir must be a nonempty string")
        output_dir = output_value
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
        "count", "selected_variant", "model", "max_retries"
    }:
        raise ValueError(
            "rubric_paraphrases requires count, selected_variant, model, "
            "and max_retries"
        )
    if type(value["count"]) is not int or value["count"] < 2:
        raise ValueError("rubric paraphrase count must be at least two")
    if (
        type(value["selected_variant"]) is not int
        or not 0 <= value["selected_variant"] < value["count"]
    ):
        raise ValueError("selected rubric paraphrase variant is outside the pool")
    if type(value["model"]) is not str or not value["model"].strip():
        raise ValueError("rubric paraphrase model must be nonempty")
    if type(value["max_retries"]) is not int or value["max_retries"] < 0:
        raise ValueError("rubric paraphrase retries must be non-negative")


def _validate_master_rubrics(
    tasks_dir: Path,
    task_ids: tuple[str, ...],
    rubric_name: str,
) -> None:
    """Reject invalid master rubrics before any experiment stage runs."""

    for task_id in task_ids:
        rubric_path = tasks_dir / task_id / "tests" / rubric_name
        if rubric_path.is_symlink() or not rubric_path.is_file():
            raise ValueError(f"master rubric is missing or symlinked: {rubric_path}")
        try:
            CompleteRubric.from_content(rubric_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, ValueError) as exc:
            raise ValueError(f"master rubric is invalid for {task_id}: {exc}") from exc


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
    max_revisions = protocol.get("max_revisions", "invalid")
    experiment_id = f"{benchmark}-factorial-r{max_revisions}-{digest}"
    if not _ID.fullmatch(experiment_id):
        raise ValueError("derived experiment ID is invalid")
    return experiment_id


def _validate_protocol(protocol: object) -> None:
    base_keys = {
        "max_revisions", "min_revisions", "prompt", "feedback_simulator",
        "judge_model",
        "rubric_name", "review", "max_review_chars",
        "rubric_proposer_model",
        "rubric_proposer_max_retries",
    }
    if not isinstance(protocol, dict):
        raise ValueError("protocol must be a mapping")
    if set(protocol) != base_keys:
        raise ValueError(f"protocol keys must be exactly {sorted(base_keys)}")
    if type(protocol["max_revisions"]) is not int or protocol["max_revisions"] < 1:
        raise ValueError("max_revisions must be positive")
    if (
        type(protocol["min_revisions"]) is not int
        or not MINIMUM_POST_UPDATE_REVISIONS
        <= protocol["min_revisions"]
        <= protocol["max_revisions"]
    ):
        raise ValueError(
            "min_revisions must guarantee the post-update detection window and "
            "must not exceed max_revisions"
        )
    if type(protocol["prompt"]) is not str:
        raise ValueError("protocol prompt must be a string")
    PromptProfile(protocol["prompt"])
    if protocol["review"] not in {"trace", "trajectory", "workspace"}:
        raise ValueError("review must be trace, trajectory, or workspace")
    if type(protocol["judge_model"]) is not str or not protocol[
        "judge_model"
    ].strip():
        raise ValueError("judge_model must be a nonempty string")
    safe_basename(protocol["rubric_name"], "rubric_name")
    max_review_chars = protocol["max_review_chars"]
    if max_review_chars is not None and (
        type(max_review_chars) is not int or max_review_chars < 1
    ):
        raise ValueError("max_review_chars must be null or a positive integer")
    if (
        type(protocol["rubric_proposer_model"]) is not str
        or not protocol["rubric_proposer_model"].strip()
    ):
        raise ValueError("rubric_proposer_model must be nonempty")
    if (
        type(protocol["rubric_proposer_max_retries"]) is not int
        or protocol["rubric_proposer_max_retries"] < 0
    ):
        raise ValueError("rubric_proposer_max_retries must be non-negative")
    simulator = protocol["feedback_simulator"]
    simulator_keys = {
        "model",
        "max_output_tokens",
        "max_concerns",
        "max_history_bytes",
        "max_request_bytes",
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
        max_concerns=simulator["max_concerns"],
        max_history_bytes=simulator["max_history_bytes"],
        max_request_bytes=simulator["max_request_bytes"],
        max_retries=simulator["max_retries"],
    )


def _validate_agent(value: object, label: str) -> None:
    agent_keys = {
        "provider",
        "model",
        "reasoning_effort",
        "service_tier",
        "executable",
        "retries",
        "timeout_seconds",
    }
    if not isinstance(value, dict) or set(value) != agent_keys:
        raise ValueError(f"{label} keys must be exactly {sorted(agent_keys)}")
    if type(value["provider"]) is not str or not value["provider"].strip():
        raise ValueError(f"{label} provider must be a nonempty string")
    if value["provider"] not in AgentAdapterRegistry().names:
        raise ValueError(
            f"{label} provider must be one of "
            + ", ".join(AgentAdapterRegistry().names)
        )
    if type(value["model"]) is not str or not value["model"].strip():
        raise ValueError(f"{label} model must be a nonempty string")
    if type(value["retries"]) is not int or value["retries"] < 0:
        raise ValueError(f"{label} retries must be a non-negative integer")
    if type(value["timeout_seconds"]) is not int or value["timeout_seconds"] < 1:
        raise ValueError(f"{label} timeout_seconds must be a positive integer")
    _agent_run_config(
        value,
        quiet=False,
    )


def _randomized_assignments(payload: dict[str, Any]) -> list[ExperimentAssignment]:
    rng = random.Random(payload["randomization"]["seed"])
    candidates: list[tuple[str, int, str, str, int]] = []
    for replicate in range(1, payload["randomization"]["replicates"] + 1):
        for task_id in payload["tasks"]:
            arms = [
                (solver, condition)
                for solver in payload["solvers"]
                for condition in payload["conditions"]
            ]
            rng.shuffle(arms)
            for within_block_order, (solver, condition) in enumerate(arms, start=1):
                condition_id = condition["condition_id"]
                solver_id = solver["solver_id"]
                assert isinstance(condition_id, str) and isinstance(solver_id, str)
                candidates.append(
                    (
                        task_id,
                        replicate,
                        solver_id,
                        condition_id,
                        within_block_order,
                    )
                )
    rng.shuffle(candidates)
    selection = payload["assignment_selection"]
    if selection != "all":
        selected_ids = set(selection)
        candidates = [
            candidate
            for candidate in candidates
            if _assignment_id(*candidate[:4]) in selected_ids
        ]
    return [
        ExperimentAssignment(
            task_id=task_id,
            replicate=replicate,
            solver_id=solver_id,
            condition_id=condition_id,
            within_block_order=within_block_order,
            execution_order=execution_order,
        )
        for execution_order, (
            task_id,
            replicate,
            solver_id,
            condition_id,
            within_block_order,
        ) in enumerate(candidates, start=1)
    ]


def _assignment_id(
    task_id: str,
    replicate: int,
    solver_id: str,
    condition_id: str,
) -> str:
    return (
        f"{task_id}--rep-{replicate:03d}--solver-{solver_id}--{condition_id}"
    )


def _validate_assignment_selection(payload: dict[str, Any]) -> None:
    """Require either the complete design or exact existing assignment IDs."""

    selection = payload["assignment_selection"]
    if selection == "all":
        return
    if (
        not isinstance(selection, list)
        or not selection
        or any(type(item) is not str for item in selection)
        or len(selection) != len(set(selection))
    ):
        raise ValueError(
            "assignment_selection must be 'all' or unique assignment IDs"
        )
    valid_ids = {
        f"{task_id}--rep-{replicate:03d}--solver-{solver['solver_id']}--"
        f"{condition['condition_id']}"
        for replicate in range(1, payload["randomization"]["replicates"] + 1)
        for task_id in payload["tasks"]
        for solver in payload["solvers"]
        for condition in payload["conditions"]
    }
    unknown = sorted(set(selection) - valid_ids)
    if unknown:
        raise ValueError(
            f"assignment_selection contains unknown assignment IDs: {unknown!r}"
        )


def _resolve_relative(experiment_path: Path, value: object) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("experiment paths must be non-empty strings")
    path = Path(value).expanduser()
    return path.resolve() if path.is_absolute() else (experiment_path.parent / path).resolve()


def _optional_string(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or not value.strip():
        raise ValueError("optional string values must be null or nonempty strings")
    return value
