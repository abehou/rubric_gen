"""Measured API-cost accounting for one locked randomized study."""

from __future__ import annotations

import json
from pathlib import Path

from rubric_gen.biomnibench.agent.costs import RunCost
from rubric_gen.biomnibench.experiments import ExperimentDesign
from rubric_gen.biomnibench.study import study_experiment_relative_path
from rubric_gen.biomnibench.utils.serialization import write_json_atomic
from rubric_gen.malt.model_judge import (
    ModelGeneration,
    ModelJudgeRunner,
    PRICING_AS_OF,
    PRICING_SOURCES,
)


COST_REPORT_SCHEMA_VERSION = 3


def _new_stage(planned_invocations: int) -> dict[str, object]:
    return {
        "planned_stage_invocations": planned_invocations,
        "observed_stage_invocations": 0,
        "fully_priced_stage_invocations": 0,
        "partially_priced_stage_invocations": 0,
        "unpriced_stage_invocations": 0,
        "observed_cost_usd": 0.0,
        "cost_records_by_source": {},
        "unpriced_cost_records": 0,
    }


def _effective_cost(cost: RunCost) -> tuple[float | None, str]:
    if cost.cost_usd is not None:
        return cost.cost_usd, cost.source or "reported"
    if cost.estimated_cost_usd is not None:
        return cost.estimated_cost_usd, cost.source or "estimated"
    return None, cost.source or "unavailable"


def _add_cost_record(stage: dict[str, object], cost: RunCost) -> bool:
    value, source = _effective_cost(cost)
    sources = stage["cost_records_by_source"]
    assert isinstance(sources, dict)
    sources[source] = int(sources.get(source, 0)) + 1
    if value is None:
        stage["unpriced_cost_records"] = int(stage["unpriced_cost_records"]) + 1
        return False
    stage["observed_cost_usd"] = float(stage["observed_cost_usd"]) + value
    return True


def _record_stage_costs(
    stage: dict[str, object],
    costs: list[RunCost],
    *,
    stage_invocations: int,
) -> None:
    if stage_invocations < 0:
        raise ValueError("stage invocations must not be negative")
    priced = [_add_cost_record(stage, cost) for cost in costs]
    if stage_invocations == 0:
        return
    stage["observed_stage_invocations"] = (
        int(stage["observed_stage_invocations"]) + stage_invocations
    )
    if priced and all(priced):
        key = "fully_priced_stage_invocations"
    elif any(priced):
        key = "partially_priced_stage_invocations"
    else:
        key = "unpriced_stage_invocations"
    stage[key] = int(stage[key]) + stage_invocations


def _cost_from_fields(payload: object) -> RunCost:
    if not isinstance(payload, dict):
        return RunCost()
    cost = payload.get("cost_usd")
    estimated = payload.get("estimated_cost_usd")
    return RunCost(
        float(cost) if isinstance(cost, (int, float)) and not isinstance(cost, bool) else None,
        (
            float(estimated)
            if isinstance(estimated, (int, float)) and not isinstance(estimated, bool)
            else None
        ),
        str(payload["cost_source"])
        if isinstance(payload.get("cost_source"), str)
        else None,
    )


def _reported_or_repriced_solver_cost(
    stored: RunCost,
    stream_path: Path,
    *,
    model: str,
    service_tier: str | None,
) -> RunCost:
    """Keep provider-reported dollars; otherwise price raw usage afresh."""

    if stored.cost_usd is not None:
        return stored
    repriced = RunCost.from_stream(
        stream_path,
        model=model,
        service_tier=service_tier,
    )
    if repriced.estimated_cost_usd is not None:
        return repriced
    return stored


def _usage_cost(path: Path) -> RunCost:
    try:
        record = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return RunCost(source="invalid_usage_record")
    if not isinstance(record, dict):
        return RunCost(source="invalid_usage_record")
    provider = record.get("provider")
    model = record.get("requested_model")
    usage = record.get("usage")
    if not isinstance(provider, str) or not isinstance(model, str):
        return RunCost(source="invalid_usage_record")
    generation = ModelGeneration(
        text="cost-report",
        provider=provider,
        requested_model=model,
        effective_model=str(record.get("effective_model") or model),
        response_id="cost-report",
        request_parameters={},
        provider_metadata={"usage": usage},
    )
    tokens = ModelJudgeRunner._usage_tokens(generation)
    if tokens is None:
        return RunCost(source="usage_tokens_unavailable")
    value = ModelJudgeRunner._request_cost(model, **tokens)
    if value is None:
        return RunCost(source="unpriced_model")
    return RunCost(cost_usd=value, source="provider_usage_priced_locally")


def _finalize_stage(stage: dict[str, object]) -> None:
    stage["observed_cost_usd"] = round(float(stage["observed_cost_usd"]), 6)
    stage["unobserved_planned_stage_invocations"] = max(
        int(stage["planned_stage_invocations"])
        - int(stage["observed_stage_invocations"]),
        0,
    )
    sources = stage["cost_records_by_source"]
    assert isinstance(sources, dict)
    stage["cost_records_by_source"] = dict(sorted(sources.items()))


def _evaluation_roots(evaluations: Path) -> tuple[Path, ...]:
    roots: list[Path] = []
    for submission in sorted(evaluations.glob("s*")):
        if submission.is_symlink() or not submission.is_dir():
            continue
        for rubric in sorted(submission.iterdir()):
            if rubric.is_symlink() or not rubric.is_dir():
                continue
            for attempt in sorted(rubric.iterdir()):
                if attempt.is_symlink() or not attempt.is_dir():
                    continue
                roots.append(attempt)
    return tuple(roots)


def _record_optimizer_evaluations(
    stage: dict[str, object], evaluations: Path
) -> None:
    observed_attempts = 0
    for root in _evaluation_roots(evaluations):
        usage_paths = sorted(root.rglob("usage.json"))
        final_usages = [
            path
            for path in usage_paths
            if "judge-attempts" not in path.relative_to(root).parts
        ]
        final_validations = [
            path
            for path in root.rglob("score_validation.json")
            if "judge-attempts" not in path.relative_to(root).parts
        ]
        archived_root = root / "judge-attempts"
        archived_attempts = (
            [
                path
                for path in sorted(archived_root.glob("attempt-*"))
                if not path.is_symlink() and path.is_dir()
            ]
            if archived_root.is_dir() and not archived_root.is_symlink()
            else []
        )
        observed_attempts += len(final_usages) + len(archived_attempts)
        costs = [_usage_cost(path) for path in usage_paths]
        archived_usage_parents = {
            path.parent for path in usage_paths if "judge-attempts" in path.parts
        }
        for attempt in archived_attempts:
            if attempt not in archived_usage_parents:
                costs.append(RunCost(source="failed_optimizer_attempt_without_usage"))
        completed = len(final_usages) == 1 and len(final_validations) == 1
        _record_stage_costs(
            stage,
            costs,
            stage_invocations=1 if completed else 0,
        )
    stage["observed_optimizer_attempts"] = (
        int(stage.get("observed_optimizer_attempts", 0)) + observed_attempts
    )


def study_cost_report(
    design: ExperimentDesign,
    *,
    seed_run_dir: Path | None = None,
    study_dir: Path | None = None,
    audit_summary: Path | None = None,
    output_path: Path | None = None,
) -> dict[str, object]:
    plan = design.payload.get("cost_plan")
    if not isinstance(plan, dict) or not isinstance(
        plan.get("nominal_stage_invocations"), dict
    ):
        raise ValueError("design has no valid cost plan")
    invocations = plan["nominal_stage_invocations"]
    assert isinstance(invocations, dict)
    stages = {
        name: _new_stage(int(planned))
        for name, planned in invocations.items()
    }
    solver = design.protocol["solver"]
    assert isinstance(solver, dict)
    solver_model = str(solver["model"])
    solver_service_tier = (
        str(solver["service_tier"])
        if isinstance(solver.get("service_tier"), str)
        else None
    )

    if seed_run_dir is not None:
        seed_root = seed_run_dir.resolve()
        for task_id in design.task_ids:
            for replicate in range(1, design.replicates + 1):
                root = seed_root / "tasks" / task_id / f"rep-{replicate:03d}"
                try:
                    manifest = json.loads((root / "manifest.json").read_text())
                except (OSError, json.JSONDecodeError):
                    continue
                _record_stage_costs(
                    stages["seed_solver"],
                    [_reported_or_repriced_solver_cost(
                        _cost_from_fields(manifest.get("source_status")),
                        root / "submission" / "trajectory.stream.jsonl",
                        model=solver_model,
                        service_tier=solver_service_tier,
                    )],
                    stage_invocations=1,
                )
                usage = root / "initial_judgment" / "usage.json"
                _record_stage_costs(
                    stages["seed_judge"],
                    [_usage_cost(usage)],
                    stage_invocations=1,
                )

    if study_dir is not None:
        study_root = study_dir.resolve()
        for assignment in design.assignments:
            experiment = study_root / study_experiment_relative_path(assignment)
            successful_turns: list[tuple[int, Path]] = []
            turns_root = experiment / "turns"
            if turns_root.is_dir():
                for turn in turns_root.glob("turn-*"):
                    try:
                        index = int(turn.name.removeprefix("turn-"))
                        status = json.loads((turn / "status.json").read_text())
                    except (ValueError, OSError, json.JSONDecodeError):
                        continue
                    if isinstance(status, dict) and status.get("exit_code") == 0:
                        successful_turns.append((index, turn))
            if successful_turns:
                final_index, final_turn = max(successful_turns)
                cost = _reported_or_repriced_solver_cost(
                    RunCost.from_status(final_turn / "status.json"),
                    final_turn / "trajectory.stream.jsonl",
                    model=solver_model,
                    service_tier=solver_service_tier,
                )
                _record_stage_costs(
                    stages["revision_solver"],
                    [cost],
                    stage_invocations=final_index,
                )
            evaluations = experiment / "evaluations"
            if evaluations.is_dir():
                _record_optimizer_evaluations(
                    stages["revision_judge"], evaluations
                )
            rubric_root = experiment / "rubric"
            if rubric_root.is_dir():
                for proposal_path in rubric_root.glob("r*.proposal.json"):
                    try:
                        proposal = json.loads(proposal_path.read_text())
                    except (OSError, json.JSONDecodeError):
                        continue
                    costs = proposal.get("proposer_attempt_costs")
                    if not isinstance(costs, list):
                        continue
                    _record_stage_costs(
                        stages["rubric_proposer"],
                        [_cost_from_fields(cost) for cost in costs],
                        stage_invocations=1,
                    )
                    stages["rubric_proposer"]["observed_proposer_attempts"] = (
                        int(
                            stages["rubric_proposer"].get(
                                "observed_proposer_attempts", 0
                            )
                        )
                        + len(costs)
                    )

    if audit_summary is not None and audit_summary.is_file():
        summary = json.loads(audit_summary.read_text(encoding="utf-8"))
        cost = summary.get("cost") if isinstance(summary, dict) else None
        records = summary.get("records") if isinstance(summary, dict) else None
        observed = cost.get("observed_api_usd") if isinstance(cost, dict) else None
        covered = 0
        api_attempts = 0
        if isinstance(records, list):
            for record in records:
                if not isinstance(record, dict):
                    continue
                covered += 1
                attempts = record.get("attempt_count", 0)
                if type(attempts) is int and attempts >= 0:
                    api_attempts += attempts
        audit_costs = [RunCost(
            cost_usd=float(observed)
            if isinstance(observed, (int, float)) and not isinstance(observed, bool)
            else None,
            source="audit_summary_provider_usage",
        )]
        risk: object = None
        if isinstance(cost, dict):
            risk = cost.get("unverified_failed_request_risk_usd")
            if (
                isinstance(risk, (int, float))
                and not isinstance(risk, bool)
                and float(risk) > 0
            ):
                audit_costs.append(
                    RunCost(source="unverified_failed_audit_request")
                )
        _record_stage_costs(
            stages["outcome_audit"],
            audit_costs,
            stage_invocations=covered,
        )
        stages["outcome_audit"]["observed_provider_requests"] = api_attempts
        if isinstance(risk, (int, float)) and not isinstance(risk, bool):
            stages["outcome_audit"][
                "unverified_failed_request_risk_usd"
            ] = float(risk)

    for stage in stages.values():
        _finalize_stage(stage)
    observed_total = round(
        sum(float(stage["observed_cost_usd"]) for stage in stages.values()), 6
    )
    result: dict[str, object] = {
        "schema_version": COST_REPORT_SCHEMA_VERSION,
        "kind": "rubric-gen-biomnibench-study-cost-report",
        "design_sha256": design.sha256,
        "pricing_as_of": PRICING_AS_OF,
        "pricing_sources": PRICING_SOURCES,
        "observed_cost_usd": observed_total,
        "stages": stages,
        "limitations": [
            "Stage invocations are not provider API requests; Codex solver and proposer invocations can contain multiple internal model requests.",
            "Codex solver estimates are lower bounds because cumulative CLI usage does not expose per-request long-context price multipliers.",
            "Failed optimizer requests without provider usage metadata cannot be priced.",
            "Unobserved planned invocations are not assigned a fabricated dollar estimate.",
        ],
    }
    if output_path is not None:
        write_json_atomic(output_path, result)
    return result
