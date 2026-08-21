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
from rubric_gen.runtime.agents.policy import MAX_TRANSIENT_RETRIES
from rubric_gen.runtime.yaml import load_yaml_strict
from rubric_gen.submission_revision.prompts import PromptProfile
from rubric_gen.reward_hacking.protocol import outcome_audit_protocol
from rubric_gen.submission_revision.rubric_bank import CompleteRubric, RubricBankPolicy
from rubric_gen.submission_revision.evolution import (
    MAX_SEMANTIC_REVIEW_OUTPUT_TOKENS,
    MAX_SEMANTIC_REVIEW_REQUEST_BYTES,
)
from rubric_gen.submission_revision.feedback import FeedbackPolicy
from rubric_gen.submission_revision.user_simulator import SimulatedUserConfig
from rubric_gen.submission_revision.judging.models import safe_basename
from rubric_gen.benchmarks import SubmissionBenchmarkId, get_submission_benchmark
from rubric_gen.artifacts.hashing import sha256_text


EXPERIMENT_KIND = "rubric-gen-randomized-experiment"
_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,79}\Z")
EXPERIMENT_ID_TOKEN = "{experiment_id}"
_RUBRIC_POLICY_SLUGS = {
    RubricBankPolicy.FIXED: "static",
    RubricBankPolicy.OFFLINE_ELICITATION: "offline-rubric",
    RubricBankPolicy.ONLINE_ELICITATION: "online-rubric",
}
_IDENTITY_KEYS = (
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
        provider = value["provider"]
        model = value["model"]
        assert isinstance(provider, str) and isinstance(model, str)
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
            retries=value["retries"],
            timeout_seconds=value["timeout_seconds"],
            quiet=quiet,
        )

    def feedback_simulator_config(
        self,
        feedback_policy: FeedbackPolicy | str,
        *,
        vllm_endpoints: dict[str, str] | None = None,
    ) -> SimulatedUserConfig | None:
        if FeedbackPolicy(feedback_policy) is not FeedbackPolicy.USER_SIMULATOR:
            return None
        value = self.protocol["feedback_simulator"]
        assert isinstance(value, dict)
        model = value["model"]
        assert isinstance(model, str)
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
        "randomization", "conditions", "protocol", "rubric_paraphrases",
        "outcome_audit", "dag",
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
    conditions = payload["conditions"]
    if not isinstance(conditions, list) or not conditions:
        raise ValueError("conditions must be a non-empty list")
    condition_ids: list[str] = []
    condition_pairs: list[tuple[FeedbackPolicy, RubricBankPolicy]] = []
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
        resolved_rubric = RubricBankPolicy(rubric_policy)
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
    expected_pairs = {
        (feedback_policy, rubric_policy)
        for feedback_policy in FeedbackPolicy
        for rubric_policy in RubricBankPolicy
    }
    if (
        len(condition_pairs) != len(expected_pairs)
        or set(condition_pairs) != expected_pairs
    ):
        raise ValueError(
            "conditions must contain exactly one arm for each feedback-policy "
            "and rubric-policy pair"
        )
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
        "direct_detector_max_cost_usd",
        "mechanistic_max_calls",
        "mechanistic_max_request_bytes",
        "mechanistic_max_output_tokens",
        "holistic_max_calls",
        "holistic_max_request_bytes",
        "holistic_max_output_tokens",
    }
    optional_audit_keys = {
        "max_input_tokens",
        "max_output_tokens",
        "max_event_text_chars",
        "max_command_output_chars",
        "max_retries",
    }
    if not required_audit_keys <= set(audit) or not set(audit) <= (
        required_audit_keys | optional_audit_keys
    ):
        raise ValueError(
            "outcome_audit keys must be exactly the required models, primary_rule, "
            "loss_weights, direct detector budget, and stage caps, plus supported "
            "input limits"
        )
    audit_models = audit["models"]
    if not isinstance(audit_models, list) or any(
        type(model) is not str for model in audit_models
    ):
        raise ValueError("outcome_audit models must be a list of strings")
    if type(audit["primary_rule"]) is not str:
        raise ValueError("outcome_audit primary_rule must be a string")
    protocol = payload["protocol"]
    semantic_judge_model = protocol["rubric_semantic_judge_model"]
    if semantic_judge_model in audit_models:
        raise ValueError(
            "rubric semantic judge must differ from every outcome-audit model"
        )
    expected_audit = outcome_audit_protocol(
        models=tuple(audit_models),
        primary_rule=audit["primary_rule"],
        loss_weights=audit["loss_weights"],
        max_input_tokens=audit.get("max_input_tokens", 250_000),
        max_output_tokens=audit.get("max_output_tokens", 4_096),
        max_event_text_chars=audit.get("max_event_text_chars", 65_536),
        max_command_output_chars=audit.get("max_command_output_chars", 2_048),
        max_retries=audit.get("max_retries", 1),
        direct_detector_max_cost_usd=audit[
            "direct_detector_max_cost_usd"
        ],
        mechanistic_max_calls=audit["mechanistic_max_calls"],
        mechanistic_max_request_bytes=audit[
            "mechanistic_max_request_bytes"
        ],
        mechanistic_max_output_tokens=audit[
            "mechanistic_max_output_tokens"
        ],
        holistic_max_calls=audit["holistic_max_calls"],
        holistic_max_request_bytes=audit["holistic_max_request_bytes"],
        holistic_max_output_tokens=audit["holistic_max_output_tokens"],
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
    rounds = protocol.get("revision_rounds", "invalid")
    experiment_id = f"{benchmark}-factorial-r{rounds}-{digest}"
    if not _ID.fullmatch(experiment_id):
        raise ValueError("derived experiment ID is invalid")
    return experiment_id


def _validate_protocol(protocol: object) -> None:
    base_keys = {
        "revision_rounds", "prompt", "feedback_simulator", "solver",
        "judge_model",
        "judge_max_retries", "rubric_name", "review", "max_review_chars",
        "rubric_proposer_model",
        "rubric_proposer_max_retries",
        "rubric_semantic_judge_model",
        "rubric_semantic_judge_max_calls_per_assignment",
        "rubric_semantic_judge_max_request_bytes_per_call",
        "rubric_semantic_judge_max_output_tokens_per_call",
    }
    if not isinstance(protocol, dict):
        raise ValueError("protocol must be a mapping")
    if set(protocol) != base_keys:
        raise ValueError(f"protocol keys must be exactly {sorted(base_keys)}")
    if type(protocol["revision_rounds"]) is not int or protocol["revision_rounds"] < 1:
        raise ValueError("revision_rounds must be positive")
    if type(protocol["prompt"]) is not str:
        raise ValueError("protocol prompt must be a string")
    PromptProfile(protocol["prompt"])
    if protocol["review"] not in {"trace", "trajectory", "workspace"}:
        raise ValueError("review must be trace, trajectory, or workspace")
    if type(protocol["judge_model"]) is not str or not protocol[
        "judge_model"
    ].strip():
        raise ValueError("judge_model must be a nonempty string")
    if (
        type(protocol["judge_max_retries"]) is not int
        or not 0 <= protocol["judge_max_retries"] <= MAX_TRANSIENT_RETRIES
    ):
        raise ValueError(
            "judge_max_retries must be between 0 and "
            f"{MAX_TRANSIENT_RETRIES}"
        )
    safe_basename(protocol["rubric_name"], "rubric_name")
    max_review_chars = protocol["max_review_chars"]
    if max_review_chars is not None and (
        type(max_review_chars) is not int or max_review_chars < 1
    ):
        raise ValueError("max_review_chars must be null or a positive integer")
    for name in ("rubric_proposer_model", "rubric_semantic_judge_model"):
        if type(protocol[name]) is not str or not protocol[name].strip():
            raise ValueError(f"{name} must be nonempty")
    if (
        type(protocol["rubric_semantic_judge_max_calls_per_assignment"]) is not int
        or protocol["rubric_semantic_judge_max_calls_per_assignment"]
        != max(0, protocol["revision_rounds"] - 1)
    ):
        raise ValueError(
            "rubric semantic reviewer call cap must equal revision_rounds minus one"
        )
    if (
        type(protocol["rubric_semantic_judge_max_request_bytes_per_call"])
        is not int
        or not 1
        <= protocol["rubric_semantic_judge_max_request_bytes_per_call"]
        <= MAX_SEMANTIC_REVIEW_REQUEST_BYTES
    ):
        raise ValueError("rubric semantic judge request-byte cap is invalid")
    if (
        type(protocol["rubric_semantic_judge_max_output_tokens_per_call"])
        is not int
        or not 1
        <= protocol["rubric_semantic_judge_max_output_tokens_per_call"]
        <= MAX_SEMANTIC_REVIEW_OUTPUT_TOKENS
    ):
        raise ValueError("rubric semantic judge output-token cap is invalid")
    if (
        type(protocol["rubric_proposer_max_retries"]) is not int
        or protocol["rubric_proposer_max_retries"] < 0
    ):
        raise ValueError("rubric_proposer_max_retries must be non-negative")
    solver = protocol["solver"]
    solver_keys = {
        "provider",
        "model",
        "reasoning_effort",
        "service_tier",
        "executable",
        "retries",
        "timeout_seconds",
    }
    if not isinstance(solver, dict) or set(solver) != solver_keys:
        raise ValueError(f"solver keys must be exactly {sorted(solver_keys)}")
    if type(solver["provider"]) is not str or not solver["provider"].strip():
        raise ValueError("solver provider must be a nonempty string")
    if solver["provider"] not in AgentAdapterRegistry().names:
        raise ValueError(
            "solver provider must be one of "
            + ", ".join(AgentAdapterRegistry().names)
        )
    if type(solver["model"]) is not str or not solver["model"].strip():
        raise ValueError("solver model must be a nonempty string")
    if type(solver["retries"]) is not int or solver["retries"] < 0:
        raise ValueError("solver retries must be a non-negative integer")
    if type(solver["timeout_seconds"]) is not int or solver["timeout_seconds"] < 1:
        raise ValueError("solver timeout_seconds must be a positive integer")
    AgentRunConfig(
        provider=solver["provider"], model=solver["model"],
        reasoning_effort=_optional_string(solver["reasoning_effort"]),
        service_tier=_optional_string(solver["service_tier"]),
        executable=_optional_string(solver["executable"]),
        retries=solver["retries"],
        timeout_seconds=solver["timeout_seconds"],
    )
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
                condition_id = condition["condition_id"]
                assert isinstance(condition_id, str)
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
    if value is None:
        return None
    if type(value) is not str or not value.strip():
        raise ValueError("optional string values must be null or nonempty strings")
    return value
