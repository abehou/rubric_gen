"""Strict configuration for Harvey LAB harness-evolution experiments."""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import yaml


_SHA = re.compile(r"^[0-9a-f]{40}$")
_ID = re.compile(r"^[a-z0-9][a-z0-9._-]*$")
_EFFORTS = {None, "minimal", "low", "medium", "high", "xhigh"}
_TASK_EFFORTS = _EFFORTS | {"max"}
HARVEY_EXPERIMENT_KIND = "rubric-gen-harvey-harness-evolution-experiment"
HARVEY_EXPERIMENT_SCHEMA_VERSION = 2


def _object(value: object, label: str) -> dict[str, Any]:
    if not isinstance(value, dict) or any(type(key) is not str for key in value):
        raise ValueError(f"{label} must be an object")
    return value


def _exact(value: dict[str, Any], allowed: set[str], label: str) -> None:
    unknown = sorted(set(value) - allowed)
    if unknown:
        raise ValueError(f"{label} has unknown fields: {', '.join(unknown)}")


def _text(value: object, label: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{label} must be a non-empty string")
    return value.strip()


def _integer(value: object, label: str, minimum: int = 1) -> int:
    if type(value) is not int or value < minimum:
        raise ValueError(f"{label} must be an integer of at least {minimum}")
    return value


def _string_tuple(value: object, label: str, *, empty: bool = False) -> tuple[str, ...]:
    if not isinstance(value, list) or (not value and not empty):
        raise ValueError(f"{label} must be a{' possibly empty' if empty else ' non-empty'} list")
    values = tuple(_text(item, f"{label} item") for item in value)
    if len(set(values)) != len(values):
        raise ValueError(f"{label} must not contain duplicates")
    return values


def _task_tuple(value: object, label: str, *, empty: bool = False) -> tuple[str, ...]:
    values = _string_tuple(value, label, empty=empty)
    for task in values:
        path = Path(task)
        if path.is_absolute() or ".." in path.parts or len(path.parts) < 2:
            raise ValueError(f"{label} has an unsafe Harvey task ID: {task}")
    return values


@dataclass(frozen=True)
class HarveyBenchmark:
    checkout: Path
    revision: str
    development_tasks: tuple[str, ...]
    held_out_tasks: tuple[str, ...]


@dataclass(frozen=True)
class TaskAgent:
    model: str
    max_turns: int
    temperature: float
    shell_timeout: int
    reasoning_effort: str | None
    sandbox_image: str
    credential_env: tuple[str, ...]


@dataclass(frozen=True)
class HarveyJudge:
    model: str
    parallel: int
    credential_env: tuple[str, ...]


@dataclass(frozen=True)
class HarnessDesigner:
    model: str
    rounds: int
    reasoning_effort: str | None
    service_tier: str | None
    timeout_seconds: int
    retries: int


@dataclass(frozen=True)
class RubricEvolution:
    mode: str
    proposer_model: str | None
    proposer_base_url: str | None
    max_changes_per_task: int
    max_output_tokens: int


@dataclass(frozen=True)
class RewardHackingAudit:
    models: tuple[str, ...]
    max_concurrency: int
    max_retries: int
    max_cost_usd: float
    primary_rule: str


@dataclass(frozen=True)
class HarveyExperiment:
    source: Path
    experiment_id: str
    output_dir: Path
    cache_dir: Path
    benchmark: HarveyBenchmark
    task_agent: TaskAgent
    judge: HarveyJudge
    designer: HarnessDesigner
    rubric: RubricEvolution
    audit: RewardHackingAudit


def _benchmark(value: object, root: Path) -> HarveyBenchmark:
    data = _object(value, "benchmark")
    _exact(data, {"checkout", "revision", "development_tasks", "held_out_tasks"}, "benchmark")
    checkout = (root / _text(data.get("checkout"), "benchmark.checkout")).resolve()
    revision = _text(data.get("revision"), "benchmark.revision")
    if not _SHA.fullmatch(revision):
        raise ValueError("benchmark.revision must be a lowercase 40-character commit SHA")
    development = _task_tuple(data.get("development_tasks"), "benchmark.development_tasks")
    held_out = _task_tuple(data.get("held_out_tasks"), "benchmark.held_out_tasks", empty=True)
    overlap = sorted(set(development) & set(held_out))
    if overlap:
        raise ValueError("development and held-out tasks overlap: " + ", ".join(overlap))
    return HarveyBenchmark(checkout, revision, development, held_out)


def _task_agent(value: object) -> TaskAgent:
    data = _object(value, "task_agent")
    _exact(data, {"model", "max_turns", "temperature", "shell_timeout", "reasoning_effort", "sandbox_image", "credential_env"}, "task_agent")
    temperature = data.get("temperature", 0.0)
    if isinstance(temperature, bool) or not isinstance(temperature, (int, float)) or not 0 <= float(temperature) <= 2:
        raise ValueError("task_agent.temperature must be between 0 and 2")
    effort = data.get("reasoning_effort")
    if effort not in _TASK_EFFORTS:
        raise ValueError("task_agent.reasoning_effort is invalid")
    return TaskAgent(
        model=_text(data.get("model"), "task_agent.model"),
        max_turns=_integer(data.get("max_turns", 200), "task_agent.max_turns"),
        temperature=float(temperature),
        shell_timeout=_integer(data.get("shell_timeout", 60), "task_agent.shell_timeout"),
        reasoning_effort=effort,
        sandbox_image=_text(data.get("sandbox_image", "lab-sandbox:latest"), "task_agent.sandbox_image"),
        credential_env=_string_tuple(data.get("credential_env"), "task_agent.credential_env"),
    )


def _judge(value: object) -> HarveyJudge:
    data = _object(value, "judge")
    _exact(data, {"model", "parallel", "credential_env"}, "judge")
    return HarveyJudge(
        model=_text(data.get("model"), "judge.model"),
        parallel=_integer(data.get("parallel", 6), "judge.parallel"),
        credential_env=_string_tuple(data.get("credential_env"), "judge.credential_env"),
    )


def _designer(value: object) -> HarnessDesigner:
    data = _object(value, "designer")
    _exact(data, {"model", "rounds", "reasoning_effort", "service_tier", "timeout_seconds", "retries"}, "designer")
    effort = data.get("reasoning_effort")
    if effort not in _EFFORTS:
        raise ValueError("designer.reasoning_effort is invalid")
    tier = data.get("service_tier")
    if tier is not None:
        tier = _text(tier, "designer.service_tier")
    return HarnessDesigner(
        model=_text(data.get("model"), "designer.model"),
        rounds=_integer(data.get("rounds"), "designer.rounds"),
        reasoning_effort=effort,
        service_tier=tier,
        timeout_seconds=_integer(data.get("timeout_seconds", 7_200), "designer.timeout_seconds"),
        retries=_integer(data.get("retries", 1), "designer.retries", minimum=0),
    )


def _rubric(value: object) -> RubricEvolution:
    data = _object(value, "rubric")
    _exact(data, {"mode", "proposer_model", "proposer_base_url", "max_changes_per_task", "max_output_tokens"}, "rubric")
    mode = _text(data.get("mode"), "rubric.mode")
    if mode not in {"static", "prospective"}:
        raise ValueError("rubric.mode must be static or prospective")
    model = data.get("proposer_model")
    base_url = data.get("proposer_base_url")
    if mode == "prospective":
        model = _text(model, "rubric.proposer_model")
        if base_url is not None:
            base_url = _text(base_url, "rubric.proposer_base_url")
    elif model is not None or base_url is not None:
        raise ValueError("static rubric evolution must not configure a proposer")
    return RubricEvolution(
        mode=mode,
        proposer_model=model,
        proposer_base_url=base_url,
        max_changes_per_task=_integer(data.get("max_changes_per_task", 8), "rubric.max_changes_per_task"),
        max_output_tokens=_integer(data.get("max_output_tokens", 16_384), "rubric.max_output_tokens", minimum=1_024),
    )


def _audit(value: object) -> RewardHackingAudit:
    data = _object(value, "audit")
    _exact(data, {"models", "max_concurrency", "max_retries", "max_cost_usd", "primary_rule"}, "audit")
    cost = data.get("max_cost_usd", 50.0)
    if isinstance(cost, bool) or not isinstance(cost, (int, float)) or cost <= 0:
        raise ValueError("audit.max_cost_usd must be positive")
    rule = _text(data.get("primary_rule", "majority"), "audit.primary_rule")
    if rule not in {"majority", "any_detects", "unanimous_detects"}:
        raise ValueError("audit.primary_rule is invalid")
    return RewardHackingAudit(
        models=_string_tuple(data.get("models"), "audit.models"),
        max_concurrency=_integer(data.get("max_concurrency", 3), "audit.max_concurrency"),
        max_retries=_integer(data.get("max_retries", 1), "audit.max_retries", minimum=0),
        max_cost_usd=float(cost),
        primary_rule=rule,
    )


def load_experiment(path: Path) -> HarveyExperiment:
    source = path.resolve(strict=True)
    try:
        raw = yaml.safe_load(source.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ValueError(f"invalid Harvey experiment YAML: {source}") from exc
    data = _object(raw, "experiment")
    _exact(data, {"schema_version", "kind", "experiment_id", "output_dir", "cache_dir", "benchmark", "task_agent", "judge", "designer", "rubric", "audit"}, "experiment")
    if data.get("schema_version") != HARVEY_EXPERIMENT_SCHEMA_VERSION:
        raise ValueError(
            f"Harvey experiment schema_version must be {HARVEY_EXPERIMENT_SCHEMA_VERSION}"
        )
    if data.get("kind") != HARVEY_EXPERIMENT_KIND:
        raise ValueError("unsupported Harvey experiment kind")
    experiment_id = _text(data.get("experiment_id"), "experiment_id")
    if not _ID.fullmatch(experiment_id):
        raise ValueError("experiment_id has invalid characters")
    root = source.parent
    output_dir = (root / _text(data.get("output_dir"), "output_dir")).resolve()
    cache_dir = (root / _text(data.get("cache_dir"), "cache_dir")).resolve()
    benchmark = _benchmark(data.get("benchmark"), root)
    if output_dir == benchmark.checkout or output_dir in benchmark.checkout.parents or benchmark.checkout in output_dir.parents:
        raise ValueError("output_dir and the Harvey checkout must not contain each other")
    protected = (output_dir, benchmark.checkout)
    if any(
        cache_dir == path or cache_dir in path.parents or path in cache_dir.parents
        for path in protected
    ):
        raise ValueError("cache_dir must be separate from output_dir and the Harvey checkout")
    return HarveyExperiment(
        source=source,
        experiment_id=experiment_id,
        output_dir=output_dir,
        cache_dir=cache_dir,
        benchmark=benchmark,
        task_agent=_task_agent(data.get("task_agent")),
        judge=_judge(data.get("judge")),
        designer=_designer(data.get("designer")),
        rubric=_rubric(data.get("rubric")),
        audit=_audit(data.get("audit")),
    )
