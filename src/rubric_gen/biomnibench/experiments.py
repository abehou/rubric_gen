"""Immutable, randomized designs for BiomniBench revision studies."""

from __future__ import annotations

import json
import math
import random
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from statistics import NormalDist

from rubric_gen.biomnibench.agent.models import AgentRunConfig
from rubric_gen.biomnibench.agent.prompts import MAX_TRANSIENT_RETRIES, PromptProfile
from rubric_gen.biomnibench.agent.workspaces import TaskCatalog
from rubric_gen.biomnibench.revision.artifacts import tree_sha256
from rubric_gen.biomnibench.revision.evolution import RubricEvolution
from rubric_gen.biomnibench.revision.feedback import FeedbackPolicy
from rubric_gen.biomnibench.forensics.protocol import (
    DEFAULT_RH_MAX_COMMAND_OUTPUT_CHARS,
    DEFAULT_RH_MAX_COST_USD,
    DEFAULT_RH_MAX_EVENT_TEXT_CHARS,
    DEFAULT_RH_MAX_INPUT_TOKENS,
    DEFAULT_RH_MAX_OUTPUT_TOKENS,
    DEFAULT_RH_MAX_RETRIES,
    PRIMARY_RH_MODELS,
    outcome_audit_protocol,
)
from rubric_gen.biomnibench.utils.hashing import sha256_file, sha256_text
from rubric_gen.biomnibench.utils.provenance import agent_provenance
from rubric_gen.biomnibench.utils.serialization import write_json_atomic


DESIGN_SCHEMA_VERSION = 7
DESIGN_KIND = "rubric-gen-randomized-revision-design"
_PROTOCOL_ID = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]{2,79}\Z")
_HEX_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
STUDY_STAGES = ("development", "validation", "confirmatory")
PRIMARY_OUTCOME = "final-trajectory-reward-hacking"
PRIMARY_ANALYSIS = "task-clustered-randomization-inference"


@dataclass(frozen=True)
class DesignConfig:
    tasks_dir: Path
    output_path: Path
    protocol_id: str
    dataset_revision: str
    random_seed: int
    sample_size: int | None
    replicates: int
    revision_rounds: int
    feedback_policy: FeedbackPolicy
    treatment_prompt: PromptProfile
    agent: AgentRunConfig
    judge_model: str
    minimum_detectable_effect: float
    anticipated_discordance: float
    stage: str = "development"
    validated_design_path: Path | None = None
    rubric_name: str = "rubric.txt"
    review: str = "trace"
    max_review_chars: int | None = None
    rubric_proposer_model: str = "gpt-5.6-luna"
    rubric_proposer_step_limit: int = 12
    primary_rh_rule: str = "majority"
    alpha: float = 0.05
    target_power: float = 0.8
    audit_max_input_tokens: int = DEFAULT_RH_MAX_INPUT_TOKENS
    audit_max_output_tokens: int = DEFAULT_RH_MAX_OUTPUT_TOKENS
    audit_max_event_text_chars: int = DEFAULT_RH_MAX_EVENT_TEXT_CHARS
    audit_max_command_output_chars: int = DEFAULT_RH_MAX_COMMAND_OUTPUT_CHARS
    audit_max_retries: int = DEFAULT_RH_MAX_RETRIES
    audit_max_cost_usd: float = DEFAULT_RH_MAX_COST_USD
    judge_max_retries: int = 1
    rubric_proposer_max_retries: int = 1

    def __post_init__(self) -> None:
        if not _PROTOCOL_ID.fullmatch(self.protocol_id):
            raise ValueError("protocol_id must be a bounded portable identifier")
        if not self.dataset_revision.strip():
            raise ValueError("dataset_revision must be explicit")
        if type(self.random_seed) is not int:
            raise ValueError("random_seed must be an integer")
        if self.sample_size is not None and (
            type(self.sample_size) is not int or self.sample_size < 1
        ):
            raise ValueError("sample_size must be positive or omitted")
        if type(self.replicates) is not int or self.replicates < 3:
            raise ValueError("scientific designs require at least three replicates")
        if type(self.revision_rounds) is not int or self.revision_rounds < 1:
            raise ValueError("revision_rounds must be positive")
        if self.treatment_prompt not in {
            PromptProfile.ANTI_RH,
            PromptProfile.DILIGENT,
        }:
            raise ValueError("treatment_prompt must be anti-rh or diligent")
        if self.agent.provider != "codex":
            raise ValueError(
                "scientific designs require Codex's attested filesystem permission profile"
            )
        if not self.agent.model or not self.agent.model.strip():
            raise ValueError("the solver model must be explicit")
        if self.agent.reasoning_effort is None:
            raise ValueError("reasoning_effort must be explicit")
        if self.agent.retries > MAX_TRANSIENT_RETRIES:
            raise ValueError(
                f"scientific designs allow at most {MAX_TRANSIENT_RETRIES} retries"
            )
        for name, retries in (
            ("judge_max_retries", self.judge_max_retries),
            ("rubric_proposer_max_retries", self.rubric_proposer_max_retries),
        ):
            if type(retries) is not int or not 0 <= retries <= MAX_TRANSIENT_RETRIES:
                raise ValueError(
                    f"{name} must be between 0 and {MAX_TRANSIENT_RETRIES}"
                )
        if self.review not in {"trace", "trajectory"}:
            raise ValueError("review must be trace or trajectory")
        if not self.judge_model.strip() or not self.rubric_proposer_model.strip():
            raise ValueError("judge and proposer models must be explicit")
        if self.primary_rh_rule not in {
            "majority", "any_detects", "unanimous_detects"
        }:
            raise ValueError("primary_rh_rule is invalid")
        if self.stage not in STUDY_STAGES:
            raise ValueError(f"stage must be one of {', '.join(STUDY_STAGES)}")
        if self.stage == "confirmatory":
            if self.validated_design_path is None:
                raise ValueError(
                    "confirmatory designs require an actual validation-stage design"
                )
        elif self.validated_design_path is not None:
            raise ValueError(
                "validated_design_path is valid only for a confirmatory design"
            )
        _validate_probability("alpha", self.alpha)
        _validate_probability("target_power", self.target_power)
        if self.target_power <= 0.5:
            raise ValueError("target_power must exceed 0.5")
        _validate_probability(
            "minimum_detectable_effect", self.minimum_detectable_effect
        )
        _validate_probability("anticipated_discordance", self.anticipated_discordance)
        if self.minimum_detectable_effect > self.anticipated_discordance:
            raise ValueError(
                "minimum_detectable_effect cannot exceed anticipated_discordance"
            )
        outcome_audit_protocol(
            primary_rule=self.primary_rh_rule,
            max_input_tokens=self.audit_max_input_tokens,
            max_output_tokens=self.audit_max_output_tokens,
            max_event_text_chars=self.audit_max_event_text_chars,
            max_command_output_chars=self.audit_max_command_output_chars,
            max_retries=self.audit_max_retries,
            max_cost_usd=self.audit_max_cost_usd,
        )


@dataclass(frozen=True)
class ExperimentDesign:
    path: Path
    payload: dict[str, object]

    @property
    def sha256(self) -> str:
        return _required_string(self.payload, "design_sha256")

    @property
    def protocol_id(self) -> str:
        return _required_string(self.payload, "protocol_id")

    @property
    def tasks_dir(self) -> Path:
        return Path(_required_string(self.payload, "tasks_dir"))

    @property
    def task_ids(self) -> tuple[str, ...]:
        tasks = self.payload["tasks"]
        assert isinstance(tasks, list)
        return tuple(_required_string(task, "task_id") for task in tasks)

    @property
    def replicates(self) -> int:
        value = self.payload["replicates"]
        assert type(value) is int
        return value

    @property
    def assignments(self) -> tuple[dict[str, object], ...]:
        value = self.payload["assignments"]
        assert isinstance(value, list)
        return tuple(dict(item) for item in value)

    @property
    def protocol(self) -> dict[str, object]:
        value = self.payload["protocol"]
        assert isinstance(value, dict)
        return dict(value)

    @property
    def run_provenance(self) -> dict[str, object]:
        value = self.payload["run_provenance"]
        assert isinstance(value, dict)
        return dict(value)

    @property
    def outcome_audit(self) -> dict[str, object]:
        value = self.payload["outcome_audit"]
        assert isinstance(value, dict)
        return dict(value)

    def task_dir(self, task_id: str) -> Path:
        if task_id not in self.task_ids:
            raise ValueError(f"task is not in design: {task_id}")
        return self.tasks_dir / task_id

    def condition(self, condition_id: str) -> dict[str, object]:
        conditions = self.payload["conditions"]
        assert isinstance(conditions, list)
        matches = [item for item in conditions if item["condition_id"] == condition_id]
        if len(matches) != 1:
            raise ValueError(f"condition is not in design: {condition_id}")
        return dict(matches[0])

    def agent_config(self, *, quiet: bool = True) -> AgentRunConfig:
        protocol = self.protocol
        solver = protocol["solver"]
        assert isinstance(solver, dict)
        return AgentRunConfig(
            provider=_required_string(solver, "provider"),
            model=_required_string(solver, "model"),
            raw=False,
            quiet=quiet,
            executable=(
                None if solver["executable"] is None else str(solver["executable"])
            ),
            reasoning_effort=_optional_string(solver, "reasoning_effort"),
            service_tier=_optional_string(solver, "service_tier"),
            retries=_required_int(solver, "retries"),
            timeout_seconds=_required_int(solver, "timeout_seconds"),
        )


def create_design(config: DesignConfig) -> ExperimentDesign:
    if config.output_path.exists() or config.output_path.is_symlink():
        raise FileExistsError(f"design already exists: {config.output_path}")
    validation_design: ExperimentDesign | None = None
    excluded_task_ids: set[str] = set()
    if config.validated_design_path is not None:
        validation_design = load_design(config.validated_design_path)
        if validation_design.payload.get("stage") != "validation":
            raise ValueError("confirmatory linkage must target a validation-stage design")
        if validation_design.payload.get("dataset_revision") != config.dataset_revision:
            raise ValueError("validation and confirmatory designs use different datasets")
        excluded_task_ids = set(validation_design.task_ids)
    source_catalog = TaskCatalog(config.tasks_dir.resolve()).tasks()
    source_task_ids = {task.name for task in source_catalog}
    if not excluded_task_ids <= source_task_ids:
        raise ValueError("validation tasks are absent from the confirmatory catalog")
    catalog = tuple(task for task in source_catalog if task.name not in excluded_task_ids)
    if not catalog:
        raise ValueError("no held-out tasks remain after excluding the validation design")
    if config.sample_size is not None and config.sample_size > len(catalog):
        raise ValueError(
            f"sample_size {config.sample_size} exceeds {len(catalog)} eligible tasks"
        )
    rng = random.Random(config.random_seed)
    selected = (
        list(catalog)
        if config.sample_size is None
        else rng.sample(catalog, config.sample_size)
    )
    rng.shuffle(selected)
    power = _power_analysis(config, len(selected))
    if not power["adequately_powered"]:
        raise ValueError(
            "design is underpowered for its declared effect: "
            f"selected {len(selected)} tasks, requires at least "
            f"{power['required_task_clusters']} under the declared McNemar assumptions"
        )
    tasks: list[dict[str, object]] = []
    for index, task in enumerate(selected, start=1):
        instruction = task / "instruction.md"
        data = task / "environment" / "data"
        rubric = task / "tests" / config.rubric_name
        _require_regular_file(instruction, "task instruction")
        _require_regular_tree(data, "task data")
        _require_regular_file(rubric, "task rubric")
        tasks.append({
            "task_id": task.name,
            "selection_order": index,
            "instruction_sha256": sha256_file(instruction),
            "data_sha256": tree_sha256(data),
            "rubric_sha256": sha256_file(rubric),
        })
    conditions = _conditions(config)
    assignments: list[dict[str, object]] = []
    for replicate in range(1, config.replicates + 1):
        for task in tasks:
            randomized = list(conditions)
            rng.shuffle(randomized)
            for order, condition in enumerate(randomized, start=1):
                task_id = str(task["task_id"])
                condition_id = str(condition["condition_id"])
                assignments.append({
                    "assignment_id": (
                        f"{task_id}--rep-{replicate:03d}--{condition_id}"
                    ),
                    "task_id": task_id,
                    "replicate": replicate,
                    "condition_id": condition_id,
                    "within_block_order": order,
                })
    rng.shuffle(assignments)
    for execution_order, assignment in enumerate(assignments, start=1):
        assignment["execution_order"] = execution_order

    provenance = agent_provenance(config.agent, require_clean=True)
    payload: dict[str, object] = {
        "schema_version": DESIGN_SCHEMA_VERSION,
        "kind": DESIGN_KIND,
        "protocol_id": config.protocol_id,
        "stage": config.stage,
        "validated_design_path": (
            str(validation_design.path) if validation_design is not None else None
        ),
        "validated_design_sha256": (
            validation_design.sha256 if validation_design is not None else None
        ),
        "dataset_revision": config.dataset_revision,
        "random_seed": config.random_seed,
        "sampling": {
            "method": (
                "seeded_holdout_sample_without_replacement"
                if validation_design is not None
                else "seeded_simple_random_sample_without_replacement"
            ),
            "source_catalog_size": len(source_catalog),
            "eligible_catalog_size": len(catalog),
            "excluded_validation_task_ids": sorted(excluded_task_ids),
            "sample_size": len(tasks),
        },
        "tasks_dir": str(config.tasks_dir.resolve()),
        "tasks": tasks,
        "replicates": config.replicates,
        "conditions": conditions,
        "assignments": assignments,
        "analysis": {
            "primary_outcome": PRIMARY_OUTCOME,
            "primary_rule": config.primary_rh_rule,
            "analysis_method": PRIMARY_ANALYSIS,
            "unit_of_inference": "task",
            "replicates_are_independent_rollouts_not_independent_task_clusters": True,
            "alpha": config.alpha,
            "target_power": config.target_power,
            "minimum_detectable_effect": config.minimum_detectable_effect,
            "anticipated_discordance": config.anticipated_discordance,
            **power,
            "missingness": "intention-to-treat; report best/worst-case bounds",
            "stopping_rule": (
                "attempt every prespecified assignment; apply the same locked "
                "turn-retry policy and condition-independent resume rule to "
                "failures; never drop or add assignments based on outcomes"
            ),
        },
        "outcome_audit": outcome_audit_protocol(
            primary_rule=config.primary_rh_rule,
            max_input_tokens=config.audit_max_input_tokens,
            max_output_tokens=config.audit_max_output_tokens,
            max_event_text_chars=config.audit_max_event_text_chars,
            max_command_output_chars=config.audit_max_command_output_chars,
            max_retries=config.audit_max_retries,
            max_cost_usd=config.audit_max_cost_usd,
        ),
        "cost_plan": _cost_plan(
            task_count=len(tasks),
            assignment_count=len(assignments),
            replicates=config.replicates,
            revision_rounds=config.revision_rounds,
        ),
        "protocol": {
            "revision_rounds": config.revision_rounds,
            "feedback_policy": config.feedback_policy.value,
            "prompt_control": PromptProfile.BASE.value,
            "prompt_treatment": config.treatment_prompt.value,
            "rubric_control": RubricEvolution.STATIC.value,
            "rubric_treatment": RubricEvolution.PROSPECTIVE.value,
            "rubric_treatment_estimand": (
                "prospective adaptive scoring and solver-visible feedback; "
                "not an isolated scoring-only intervention"
            ),
            "solver": {
                "provider": config.agent.provider,
                "model": config.agent.model,
                "reasoning_effort": config.agent.reasoning_effort,
                "service_tier": config.agent.service_tier,
                "executable": config.agent.executable,
                "retries": config.agent.retries,
                "timeout_seconds": config.agent.timeout_seconds,
                "isolation": "codex-custom-permission-profile",
                "command_network_access": False,
                "web_search": False,
            },
            "judge_model": config.judge_model,
            "judge_max_retries": config.judge_max_retries,
            "rubric_name": config.rubric_name,
            "review": config.review,
            "max_review_chars": config.max_review_chars,
            "rubric_proposer_model": config.rubric_proposer_model,
            "rubric_proposer_step_limit": config.rubric_proposer_step_limit,
            "rubric_proposer_max_retries": config.rubric_proposer_max_retries,
        },
        "run_provenance": provenance,
    }
    payload["design_sha256"] = _payload_sha256(payload)
    write_json_atomic(config.output_path, payload)
    return ExperimentDesign(config.output_path.resolve(), payload)


def load_design(path: Path, *, verify_inputs: bool = True) -> ExperimentDesign:
    resolved = path.resolve()
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"design must be a regular file: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid experiment design: {path}") from exc
    if not isinstance(payload, dict):
        raise ValueError("experiment design must be an object")
    expected_keys = {
        "schema_version", "kind", "protocol_id", "stage",
        "validated_design_path", "validated_design_sha256", "dataset_revision",
        "random_seed", "sampling",
        "tasks_dir", "tasks", "replicates", "conditions", "assignments",
        "analysis", "outcome_audit", "cost_plan", "protocol", "run_provenance",
        "design_sha256",
    }
    if set(payload) != expected_keys:
        raise ValueError("experiment design has unexpected or missing fields")
    if (
        payload.get("schema_version") != DESIGN_SCHEMA_VERSION
        or payload.get("kind") != DESIGN_KIND
        or payload.get("design_sha256") != _payload_sha256(payload)
    ):
        raise ValueError("experiment design identity is invalid")
    _validate_design_structure(payload)
    if verify_inputs:
        _verify_task_inputs(payload)
        _verify_validation_link(payload)
    return ExperimentDesign(resolved, payload)


def verify_runtime_provenance(design: ExperimentDesign) -> None:
    current = agent_provenance(design.agent_config(), require_clean=True)
    if current != design.run_provenance:
        raise RuntimeError(
            "runtime provenance differs from the locked design; create a new design"
        )


def _conditions(config: DesignConfig) -> list[dict[str, str]]:
    prompts = (PromptProfile.BASE, config.treatment_prompt)
    policies = (RubricEvolution.STATIC, RubricEvolution.PROSPECTIVE)
    return [
        {
            "condition_id": f"{prompt.value}--{policy.value}",
            "prompt": prompt.value,
            "rubric_evolution": policy.value,
        }
        for prompt in prompts
        for policy in policies
    ]


def _cost_plan(
    *,
    task_count: int,
    assignment_count: int,
    replicates: int,
    revision_rounds: int,
) -> dict[str, object]:
    seed_blocks = task_count * replicates
    evolving_assignments = assignment_count // 2
    invocations = {
        "seed_solver": seed_blocks,
        "seed_judge": seed_blocks,
        "revision_solver": assignment_count * revision_rounds,
        "revision_judge": assignment_count * revision_rounds,
        "rubric_proposer": evolving_assignments * revision_rounds,
        "outcome_audit": assignment_count * len(PRIMARY_RH_MODELS),
    }
    return {
        "nominal_stage_invocations": invocations,
        "nominal_total_stage_invocations": sum(invocations.values()),
        "stage_invocation_definition": (
            "one requested solver turn, optimizer judgment, rubric proposal, "
            "or assignment-model outcome audit; a terminal-agent invocation "
            "can issue multiple provider API requests"
        ),
        "excluded_from_nominal_total_stage_invocations": [
            "retry_attempts",
            "audit_chunk_and_synthesis_calls",
            "optional_cross_scoring",
        ],
    }


def _power_analysis(config: DesignConfig, task_clusters: int) -> dict[str, object]:
    """Conservative prespecified McNemar approximation at the task level."""

    z_alpha = NormalDist().inv_cdf(1 - config.alpha / 2)
    z_power = NormalDist().inv_cdf(config.target_power)
    delta = config.minimum_detectable_effect
    discordance = config.anticipated_discordance
    alternative_variance = max(discordance - delta * delta, 0.0)
    required = math.ceil(
        (
            z_alpha * math.sqrt(discordance)
            + z_power * math.sqrt(alternative_variance)
        ) ** 2
        / (delta * delta)
    )
    return {
        "power_method": "two-sided-asymptotic-McNemar-task-cluster-approximation",
        "required_task_clusters": max(2, required),
        "selected_task_clusters": task_clusters,
        "adequately_powered": task_clusters >= max(2, required),
        "caveat": (
            "Approximation depends on the prespecified discordance rate and does "
            "not count repeated rollouts as independent task clusters."
        ),
    }


def _payload_sha256(payload: dict[str, object]) -> str:
    identity = {key: value for key, value in payload.items() if key != "design_sha256"}
    return sha256_text(json.dumps(identity, sort_keys=True, separators=(",", ":")))


def _validate_design_structure(payload: dict[str, object]) -> None:
    _validate_protocol(payload)
    protocol_id = payload.get("protocol_id")
    tasks = payload.get("tasks")
    conditions = payload.get("conditions")
    assignments = payload.get("assignments")
    replicates = payload.get("replicates")
    stage = payload.get("stage")
    validated_path = payload.get("validated_design_path")
    validated = payload.get("validated_design_sha256")
    if type(protocol_id) is not str or not _PROTOCOL_ID.fullmatch(protocol_id):
        raise ValueError("experiment design protocol_id is invalid")
    if type(payload.get("dataset_revision")) is not str or not str(
        payload["dataset_revision"]
    ).strip():
        raise ValueError("experiment design dataset revision is invalid")
    if stage not in STUDY_STAGES:
        raise ValueError("experiment design stage is invalid")
    if stage == "confirmatory":
        if (
            type(validated_path) is not str
            or not validated_path
            or not Path(validated_path).is_absolute()
            or type(validated) is not str
            or not _HEX_SHA256.fullmatch(validated)
        ):
            raise ValueError("confirmatory design lacks validation provenance")
    elif validated is not None or validated_path is not None:
        raise ValueError("non-confirmatory design has validation provenance")
    if type(replicates) is not int or replicates < 3:
        raise ValueError("experiment design has too few replicates")
    if not isinstance(tasks, list) or not tasks:
        raise ValueError("experiment design has no tasks")
    task_ids: list[str] = []
    selection_orders: list[int] = []
    for task in tasks:
        if not isinstance(task, dict) or set(task) != {
            "task_id", "selection_order", "instruction_sha256", "data_sha256",
            "rubric_sha256",
        }:
            raise ValueError("experiment design task is invalid")
        task_id = task.get("task_id")
        if (
            type(task_id) is not str
            or not task_id
            or Path(task_id).name != task_id
        ):
            raise ValueError("experiment design task ID is invalid")
        selection_order = task.get("selection_order")
        if type(selection_order) is not int:
            raise ValueError("experiment design selection order is invalid")
        for key in ("instruction_sha256", "data_sha256", "rubric_sha256"):
            value = task.get(key)
            if type(value) is not str or not _HEX_SHA256.fullmatch(value):
                raise ValueError(f"experiment design task {key} is invalid")
        task_ids.append(task_id)
        selection_orders.append(selection_order)
    if len(set(task_ids)) != len(task_ids):
        raise ValueError("experiment design has duplicate tasks")
    if selection_orders != list(range(1, len(tasks) + 1)):
        raise ValueError("experiment design task selection order is invalid")
    if not isinstance(conditions, list) or len(conditions) != 4:
        raise ValueError("experiment design must contain exactly four conditions")
    condition_ids: list[str] = []
    for condition in conditions:
        if not isinstance(condition, dict) or set(condition) != {
            "condition_id", "prompt", "rubric_evolution"
        }:
            raise ValueError("experiment design condition is invalid")
        condition_id = condition.get("condition_id")
        if type(condition_id) is not str:
            raise ValueError("experiment design condition ID is invalid")
        PromptProfile(_required_string(condition, "prompt"))
        RubricEvolution(_required_string(condition, "rubric_evolution"))
        condition_ids.append(condition_id)
    protocol = payload["protocol"]
    assert isinstance(protocol, dict)
    treatment_prompt = _required_string(protocol, "prompt_treatment")
    expected_conditions = {
        f"{prompt}--{rubric}"
        for prompt in (PromptProfile.BASE.value, treatment_prompt)
        for rubric in (RubricEvolution.STATIC.value, RubricEvolution.PROSPECTIVE.value)
    }
    observed_conditions = {
        _required_string(condition, "condition_id")
        for condition in conditions
        if isinstance(condition, dict)
        and condition.get("condition_id")
        == f"{condition.get('prompt')}--{condition.get('rubric_evolution')}"
    }
    if set(condition_ids) != expected_conditions or observed_conditions != expected_conditions:
        raise ValueError("experiment design conditions are invalid")
    expected_count = len(tasks) * replicates * len(conditions)
    if not isinstance(assignments, list) or len(assignments) != expected_count:
        raise ValueError("experiment design assignment count is invalid")
    identities: set[tuple[str, int, str]] = set()
    execution_orders: set[int] = set()
    block_orders: dict[tuple[str, int], set[int]] = {}
    for assignment in assignments:
        if not isinstance(assignment, dict) or set(assignment) != {
            "assignment_id", "task_id", "replicate", "condition_id",
            "within_block_order", "execution_order",
        }:
            raise ValueError("experiment design assignment is invalid")
        task_id = _required_string(assignment, "task_id")
        replicate = _required_int(assignment, "replicate")
        condition_id = _required_string(assignment, "condition_id")
        within_order = _required_int(assignment, "within_block_order")
        execution_order = _required_int(assignment, "execution_order")
        identity = (task_id, replicate, condition_id)
        expected_id = f"{task_id}--rep-{replicate:03d}--{condition_id}"
        if (
            assignment.get("assignment_id") != expected_id
            or task_id not in task_ids
            or not 1 <= replicate <= replicates
            or condition_id not in condition_ids
            or identity in identities
            or not 1 <= within_order <= 4
            or not 1 <= execution_order <= expected_count
        ):
            raise ValueError("experiment design assignment identity is invalid")
        identities.add(identity)
        execution_orders.add(execution_order)
        block_orders.setdefault((task_id, replicate), set()).add(within_order)
    if execution_orders != set(range(1, expected_count + 1)):
        raise ValueError("experiment design execution order is invalid")
    if any(orders != {1, 2, 3, 4} for orders in block_orders.values()):
        raise ValueError("experiment design within-block order is invalid")
    protocol = payload["protocol"]
    assert isinstance(protocol, dict)
    expected_cost_plan = _cost_plan(
        task_count=len(tasks),
        assignment_count=len(assignments),
        replicates=replicates,
        revision_rounds=_required_int(protocol, "revision_rounds"),
    )
    if payload.get("cost_plan") != expected_cost_plan:
        raise ValueError("experiment design cost plan is invalid")
def _validate_protocol(payload: dict[str, object]) -> None:
    protocol = payload.get("protocol")
    analysis = payload.get("analysis")
    provenance = payload.get("run_provenance")
    outcome_audit = payload.get("outcome_audit")
    if not isinstance(protocol, dict) or not isinstance(analysis, dict):
        raise ValueError("experiment design protocol is invalid")
    if set(protocol) != {
        "revision_rounds", "feedback_policy", "prompt_control", "prompt_treatment",
        "rubric_control", "rubric_treatment", "rubric_treatment_estimand", "solver",
        "judge_model", "rubric_name", "review", "max_review_chars",
        "judge_max_retries", "rubric_proposer_model",
        "rubric_proposer_step_limit", "rubric_proposer_max_retries",
    }:
        raise ValueError("experiment design protocol fields are invalid")
    if _required_int(protocol, "revision_rounds") < 1:
        raise ValueError("experiment design revision rounds are invalid")
    FeedbackPolicy(_required_string(protocol, "feedback_policy"))
    if protocol.get("prompt_control") != PromptProfile.BASE.value:
        raise ValueError("experiment design prompt control is invalid")
    if PromptProfile(_required_string(protocol, "prompt_treatment")) not in {
        PromptProfile.ANTI_RH, PromptProfile.DILIGENT
    }:
        raise ValueError("experiment design prompt treatment is invalid")
    if protocol.get("rubric_control") != RubricEvolution.STATIC.value:
        raise ValueError("experiment design rubric control is invalid")
    if protocol.get("rubric_treatment") != RubricEvolution.PROSPECTIVE.value:
        raise ValueError("experiment design rubric treatment is invalid")
    if protocol.get("rubric_treatment_estimand") != (
        "prospective adaptive scoring and solver-visible feedback; "
        "not an isolated scoring-only intervention"
    ):
        raise ValueError("experiment design rubric estimand is invalid")
    solver = protocol.get("solver")
    if not isinstance(solver, dict) or set(solver) != {
        "provider", "model", "reasoning_effort", "service_tier", "executable",
        "retries", "timeout_seconds", "isolation", "command_network_access",
        "web_search",
    }:
        raise ValueError("experiment design solver fields are invalid")
    if (
        solver.get("provider") != "codex"
        or solver.get("isolation") != "codex-custom-permission-profile"
        or solver.get("command_network_access") is not False
        or solver.get("web_search") is not False
        or _optional_string(solver, "reasoning_effort")
        not in {"minimal", "low", "medium", "high", "xhigh"}
        or solver.get("service_tier") not in {None, "priority"}
        or _required_int(solver, "retries") < 0
        or _required_int(solver, "retries") > MAX_TRANSIENT_RETRIES
        or _required_int(solver, "timeout_seconds") < 1
    ):
        raise ValueError("experiment design solver isolation is invalid")
    _required_string(solver, "model")
    executable = solver.get("executable")
    if executable is not None and (type(executable) is not str or not executable):
        raise ValueError("experiment design solver executable is invalid")
    for key in ("judge_model", "rubric_name", "rubric_proposer_model"):
        _required_string(protocol, key)
    for key in ("judge_max_retries", "rubric_proposer_max_retries"):
        retries = _required_int(protocol, key)
        if not 0 <= retries <= MAX_TRANSIENT_RETRIES:
            raise ValueError(f"experiment design {key} is invalid")
    if Path(_required_string(protocol, "rubric_name")).name != protocol["rubric_name"]:
        raise ValueError("experiment design rubric name is invalid")
    if protocol.get("review") not in {"trace", "trajectory"}:
        raise ValueError("experiment design review mode is invalid")
    maximum = protocol.get("max_review_chars")
    if maximum is not None and (type(maximum) is not int or maximum < 1):
        raise ValueError("experiment design review limit is invalid")
    if _required_int(protocol, "rubric_proposer_step_limit") < 1:
        raise ValueError("experiment design proposer step limit is invalid")
    expected_analysis = {
        "primary_outcome", "primary_rule", "analysis_method", "unit_of_inference",
        "replicates_are_independent_rollouts_not_independent_task_clusters", "alpha",
        "target_power", "minimum_detectable_effect", "anticipated_discordance",
        "power_method", "required_task_clusters", "selected_task_clusters",
        "adequately_powered", "caveat", "missingness", "stopping_rule",
    }
    if set(analysis) != expected_analysis or analysis.get("adequately_powered") is not True:
        raise ValueError("experiment design analysis plan is invalid")
    if analysis.get("primary_outcome") != PRIMARY_OUTCOME:
        raise ValueError("experiment design primary outcome is invalid")
    if analysis.get("analysis_method") != PRIMARY_ANALYSIS:
        raise ValueError("experiment design primary analysis is invalid")
    if (
        analysis.get("unit_of_inference") != "task"
        or analysis.get(
            "replicates_are_independent_rollouts_not_independent_task_clusters"
        ) is not True
        or analysis.get("missingness")
        != "intention-to-treat; report best/worst-case bounds"
        or analysis.get("stopping_rule")
        != (
            "attempt every prespecified assignment; apply the same locked "
            "turn-retry policy and condition-independent resume rule to "
            "failures; never drop or add assignments based on outcomes"
        )
        or analysis.get("power_method")
        != "two-sided-asymptotic-McNemar-task-cluster-approximation"
        or analysis.get("selected_task_clusters") != len(payload["tasks"])
        or type(analysis.get("required_task_clusters")) is not int
        or analysis["required_task_clusters"] < 2
        or analysis["selected_task_clusters"] < analysis["required_task_clusters"]
    ):
        raise ValueError("experiment design analysis semantics are invalid")
    if analysis.get("primary_rule") not in {
        "majority", "any_detects", "unanimous_detects"
    }:
        raise ValueError("experiment design primary rule is invalid")
    if not isinstance(outcome_audit, dict):
        raise ValueError("experiment design outcome audit is invalid")
    expected_audit = outcome_audit_protocol(
        primary_rule=str(analysis["primary_rule"]),
        max_input_tokens=_required_int(outcome_audit, "max_input_tokens"),
        max_output_tokens=_required_int(outcome_audit, "max_output_tokens"),
        max_event_text_chars=_required_int(
            outcome_audit, "max_event_text_chars"
        ),
        max_command_output_chars=_required_int(
            outcome_audit, "max_command_output_chars"
        ),
        max_retries=_required_int(outcome_audit, "max_retries"),
        max_cost_usd=_required_number(outcome_audit, "max_cost_usd"),
    )
    if outcome_audit != expected_audit:
        raise ValueError("experiment design outcome audit protocol is invalid")
    for key in (
        "alpha", "target_power", "minimum_detectable_effect",
        "anticipated_discordance",
    ):
        value = analysis.get(key)
        if type(value) not in {int, float} or not 0 < float(value) < 1:
            raise ValueError(f"experiment design {key} is invalid")
    if float(analysis["minimum_detectable_effect"]) > float(
        analysis["anticipated_discordance"]
    ):
        raise ValueError("experiment design effect exceeds discordance")
    if float(analysis["target_power"]) <= 0.5:
        raise ValueError("experiment design target power is invalid")
    z_alpha = NormalDist().inv_cdf(1 - float(analysis["alpha"]) / 2)
    z_power = NormalDist().inv_cdf(float(analysis["target_power"]))
    delta = float(analysis["minimum_detectable_effect"])
    discordance = float(analysis["anticipated_discordance"])
    expected_required = max(2, math.ceil(
        (
            z_alpha * math.sqrt(discordance)
            + z_power * math.sqrt(max(discordance - delta * delta, 0.0))
        ) ** 2
        / (delta * delta)
    ))
    if analysis["required_task_clusters"] != expected_required:
        raise ValueError("experiment design power calculation is invalid")
    sampling = payload.get("sampling")
    if (
        not isinstance(sampling, dict)
        or set(sampling) != {
            "method", "source_catalog_size", "eligible_catalog_size",
            "excluded_validation_task_ids", "sample_size",
        }
        or sampling.get("method") not in {
            "seeded_simple_random_sample_without_replacement",
            "seeded_holdout_sample_without_replacement",
        }
        or type(sampling.get("source_catalog_size")) is not int
        or type(sampling.get("eligible_catalog_size")) is not int
        or type(sampling.get("sample_size")) is not int
        or not isinstance(sampling.get("excluded_validation_task_ids"), list)
        or any(
            type(item) is not str
            for item in sampling["excluded_validation_task_ids"]
        )
        or sampling["excluded_validation_task_ids"]
        != sorted(set(sampling["excluded_validation_task_ids"]))
        or sampling["source_catalog_size"]
        != sampling["eligible_catalog_size"]
        + len(sampling["excluded_validation_task_ids"])
        or sampling["eligible_catalog_size"] < sampling["sample_size"]
        or sampling["sample_size"] != len(payload["tasks"])
    ):
        raise ValueError("experiment design sampling plan is invalid")
    expected_sampling_method = (
        "seeded_holdout_sample_without_replacement"
        if payload.get("stage") == "confirmatory"
        else "seeded_simple_random_sample_without_replacement"
    )
    if sampling["method"] != expected_sampling_method:
        raise ValueError("experiment design sampling method conflicts with its stage")
    excluded = set(sampling["excluded_validation_task_ids"])
    selected_task_ids = {
        _required_string(item, "task_id")
        for item in payload["tasks"]  # type: ignore[union-attr]
        if isinstance(item, dict)
    }
    if (
        (payload.get("stage") == "confirmatory") != bool(excluded)
        or excluded & selected_task_ids
    ):
        raise ValueError("experiment design holdout task set is invalid")
    if (
        not isinstance(provenance, dict)
        or type(provenance.get("sha256")) is not str
        or not _HEX_SHA256.fullmatch(str(provenance["sha256"]))
    ):
        raise ValueError("experiment design provenance is invalid")


def _verify_task_inputs(payload: dict[str, object]) -> None:
    tasks_dir = Path(str(payload["tasks_dir"]))
    protocol = payload["protocol"]
    assert isinstance(protocol, dict)
    rubric_name = _required_string(protocol, "rubric_name")
    tasks = payload["tasks"]
    assert isinstance(tasks, list)
    for task in tasks:
        assert isinstance(task, dict)
        task_dir = tasks_dir / _required_string(task, "task_id")
        _require_regular_file(task_dir / "instruction.md", "task instruction")
        _require_regular_tree(task_dir / "environment" / "data", "task data")
        _require_regular_file(task_dir / "tests" / rubric_name, "task rubric")
        if (
            sha256_file(task_dir / "instruction.md") != task.get("instruction_sha256")
            or tree_sha256(task_dir / "environment" / "data")
            != task.get("data_sha256")
            or sha256_file(task_dir / "tests" / rubric_name)
            != task.get("rubric_sha256")
        ):
            raise RuntimeError(f"task inputs changed after design: {task_dir.name}")


def _verify_validation_link(payload: dict[str, object]) -> None:
    if payload.get("stage") != "confirmatory":
        return
    path = Path(_required_string(payload, "validated_design_path"))
    validation = load_design(path)
    if (
        validation.payload.get("stage") != "validation"
        or validation.sha256 != payload.get("validated_design_sha256")
        or validation.payload.get("dataset_revision")
        != payload.get("dataset_revision")
    ):
        raise RuntimeError("linked validation design no longer matches")
    sampling = payload["sampling"]
    assert isinstance(sampling, dict)
    if sampling.get("excluded_validation_task_ids") != sorted(validation.task_ids):
        raise RuntimeError("confirmatory holdout does not match its validation design")
    current_tasks = {
        _required_string(item, "task_id")
        for item in payload["tasks"]  # type: ignore[union-attr]
        if isinstance(item, dict)
    }
    if current_tasks & set(validation.task_ids):
        raise RuntimeError("confirmatory design reuses validation tasks")


def _require_regular_file(path: Path, context: str) -> None:
    try:
        path_stat = path.lstat()
    except OSError as exc:
        raise ValueError(f"missing {context}: {path}") from exc
    if not stat.S_ISREG(path_stat.st_mode):
        raise ValueError(f"{context} must be a regular file: {path}")


def _require_regular_tree(path: Path, context: str) -> None:
    try:
        root_stat = path.lstat()
    except OSError as exc:
        raise ValueError(f"missing {context}: {path}") from exc
    if not stat.S_ISDIR(root_stat.st_mode):
        raise ValueError(f"{context} must be a regular directory: {path}")
    for entry in path.rglob("*"):
        mode = entry.lstat().st_mode
        if not (stat.S_ISDIR(mode) or stat.S_ISREG(mode)):
            raise ValueError(f"{context} contains a non-regular entry: {entry}")


def _validate_probability(name: str, value: float) -> None:
    if type(value) not in {float, int} or not 0 < float(value) < 1:
        raise ValueError(f"{name} must be strictly between zero and one")


def _required_string(mapping: dict[str, object], key: str) -> str:
    value = mapping.get(key)
    if type(value) is not str or not value:
        raise ValueError(f"{key} must be a nonempty string")
    return value


def _optional_string(mapping: dict[str, object], key: str) -> str | None:
    value = mapping.get(key)
    if value is None:
        return None
    if type(value) is not str or not value:
        raise ValueError(f"{key} must be null or a nonempty string")
    return value


def _required_int(mapping: dict[str, object], key: str) -> int:
    value = mapping.get(key)
    if type(value) is not int:
        raise ValueError(f"{key} must be an integer")
    return value


def _required_number(mapping: dict[str, object], key: str) -> float:
    value = mapping.get(key)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError(f"{key} must be numeric")
    return float(value)
