from __future__ import annotations

import json
from pathlib import Path

from rubric_gen.biomnibench.cost_report import study_cost_report
from rubric_gen.biomnibench.experiments import ExperimentDesign
from rubric_gen.biomnibench.study import study_experiment_relative_path


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _usage() -> dict[str, object]:
    return {
        "schema_version": 1,
        "provider": "openai",
        "requested_model": "gpt-5.6-luna",
        "effective_model": "gpt-5.6-luna",
        "response_id": "response-test",
        "request_parameters": {},
        "usage": {"input_tokens": 1_000, "output_tokens": 100},
    }


def test_cost_report_separates_stage_invocations_from_api_attempts(
    tmp_path: Path,
) -> None:
    assignment = {
        "assignment_id": "da-1-1--rep-001--base--prospective",
        "task_id": "da-1-1",
        "replicate": 1,
        "condition_id": "base--prospective",
        "execution_order": 1,
    }
    nominal = {
        "seed_solver": 1,
        "seed_judge": 1,
        "revision_solver": 1,
        "revision_judge": 1,
        "rubric_proposer": 1,
        "outcome_audit": 1,
    }
    design = ExperimentDesign(tmp_path / "design.json", {
        "design_sha256": "d" * 64,
        "tasks": [{"task_id": "da-1-1"}],
        "replicates": 1,
        "assignments": [assignment],
        "protocol": {"solver": {"model": "gpt-5.6-luna"}},
        "cost_plan": {
            "nominal_stage_invocations": nominal,
            "nominal_total_stage_invocations": sum(nominal.values()),
        },
    })

    seeds = tmp_path / "seeds"
    seed = seeds / "tasks" / "da-1-1" / "rep-001"
    _write_json(seed / "manifest.json", {
        "source_status": {
            "cost_usd": 0.1,
            "estimated_cost_usd": None,
            "cost_source": "reported",
        }
    })
    _write_json(seed / "initial_judgment" / "usage.json", _usage())

    study = tmp_path / "study"
    experiment = study / study_experiment_relative_path(assignment)
    _write_json(experiment / "turns" / "turn-001" / "status.json", {
        "exit_code": 0,
        "cost_usd": 0.5,
        "estimated_cost_usd": None,
        "cost_source": "reported",
    })
    evaluation_root = (
        experiment
        / "evaluations"
        / "s001"
        / ("a" * 64)
        / ("b" * 32)
    )
    evaluation = (
        evaluation_root
        / "run"
        / "judges"
        / "trace"
        / "da-1-1"
    )
    _write_json(evaluation / "usage.json", _usage())
    _write_json(evaluation / "score_validation.json", {"score": 1})
    failed_judge_attempt = evaluation_root / "judge-attempts" / "attempt-001"
    _write_json(failed_judge_attempt / "record.json", {"status": "failed"})
    _write_json(failed_judge_attempt / "usage.json", _usage())
    _write_json(experiment / "rubric" / "r0001.proposal.json", {
        "proposer_attempt_costs": [
            {
                "cost_usd": 0.2,
                "estimated_cost_usd": None,
                "cost_source": "reported",
            },
            {
                "cost_usd": 0.3,
                "estimated_cost_usd": None,
                "cost_source": "reported",
            },
        ]
    })

    audit = tmp_path / "audit.json"
    _write_json(audit, {
        "cost": {
            "observed_api_usd": 1.2,
            "unverified_failed_request_risk_usd": 0.4,
        },
        "records": [{"status": "completed", "attempt_count": 2}],
    })

    report = study_cost_report(
        design,
        seed_run_dir=seeds,
        study_dir=study,
        audit_summary=audit,
    )

    assert report["schema_version"] == 3
    stages = report["stages"]
    assert isinstance(stages, dict)
    assert stages["revision_solver"]["observed_stage_invocations"] == 1
    assert stages["revision_judge"]["observed_stage_invocations"] == 1
    assert stages["revision_judge"]["observed_optimizer_attempts"] == 2
    assert stages["rubric_proposer"]["observed_stage_invocations"] == 1
    assert stages["rubric_proposer"]["observed_proposer_attempts"] == 2
    assert (
        stages["rubric_proposer"][
            "unobserved_planned_stage_invocations"
        ]
        == 0
    )
    assert stages["outcome_audit"]["observed_stage_invocations"] == 1
    assert stages["outcome_audit"]["observed_provider_requests"] == 2
    assert stages["outcome_audit"]["partially_priced_stage_invocations"] == 1
    assert (
        stages["outcome_audit"]["unverified_failed_request_risk_usd"] == 0.4
    )
    assert report["observed_cost_usd"] == 2.30096
    assert any(
        "not provider API requests" in limitation
        for limitation in report["limitations"]
    )
