"""Provider-free inventory for the formal Sol+Opus gap-pilot audit."""

from __future__ import annotations

import json
import os
from pathlib import Path
from collections import Counter

from rubric_gen.submission_revision.experiment import load_experiment

from audit_sol_opus import (
    PROVIDERS,
    audit_dir,
    clean_commit,
    planned_scopes,
    validate_revision,
)


STAGE_EXPECTED_PER_MODEL = {
    "absolute_score": 9,
    "pairwise_preference": 6,
    "rubric_score": 55,
    "direct_full_trajectory": 6,
    "direct_post_update": 6,
    "direct_final_artifact": 6,
    "direct_final_revision": 6,
}
from make_configs import (
    PANEL as HISTORICAL_PANEL,
    ROOT,
    SMOKE_TASK,
    TASKS,
    config_path,
)


def provider_material(root: Path) -> list[str]:
    if not root.exists():
        return []
    values = []
    for path in root.rglob("*.json"):
        relative = path.relative_to(root)
        if (
            path.name == "score.json"
            or path.parent.name == "records"
            or path.name.startswith("attempt-")
            or (
                "artifacts" in relative.parts
                and path.name
                in {"evaluation.json", "score_validation.json", "result.json"}
            )
        ):
            values.append(str(relative))
    return sorted(values)


def saved_model_counts(root: Path) -> dict[str, dict[str, int]]:
    """Count only published judgments, never failed/request attempt files."""

    counts: Counter[tuple[str, str]] = Counter()
    for stage in ("absolute_score", "pairwise_preference", "rubric_score"):
        for path in sorted((root / stage / "records").glob("*.json")):
            record = json.loads(path.read_text())
            model = record.get("model")
            if not isinstance(model, str) or not model:
                raise RuntimeError(f"saved record has no model: {path}")
            counts[(model, stage)] += 1
    for stage in (
        "direct_full_trajectory",
        "direct_post_update",
        "direct_final_artifact",
        "direct_final_revision",
    ):
        evaluations = root / stage / "evaluations"
        for path in sorted(evaluations.glob("*/cases/*/*/score.json")):
            record = json.loads(path.read_text())
            model = record.get("model")
            if not isinstance(model, str) or not model:
                raise RuntimeError(f"saved direct score has no model: {path}")
            counts[(model, stage)] += 1
    result: dict[str, dict[str, int]] = {}
    for (model, stage), count in sorted(counts.items()):
        result.setdefault(model, {})[stage] = count
    return result


def model_coverage(
    counts: dict[str, dict[str, int]],
    model: str,
) -> dict[str, object]:
    saved = counts.get(model, {})
    stages = {}
    for stage, expected in STAGE_EXPECTED_PER_MODEL.items():
        observed = int(saved.get(stage, 0))
        if observed > expected:
            raise RuntimeError(
                f"saved {model} {stage} count exceeds plan: {observed}>{expected}"
            )
        stages[stage] = {
            "expected": expected,
            "saved": observed,
            "missing": expected - observed,
        }
    return {
        "expected": sum(STAGE_EXPECTED_PER_MODEL.values()),
        "saved": sum(int(row["saved"]) for row in stages.values()),
        "missing": sum(int(row["missing"]) for row in stages.values()),
        "stages": stages,
    }


def inventory() -> dict[str, object]:
    sys_path = str(ROOT / "scripts/diagnostics")
    import sys

    sys.path.insert(0, sys_path)
    from check_audit_coverage import check

    tasks = {}
    historical_sol_missing = 0
    opus_missing = 0
    sol_recovery_tasks = []
    for task in TASKS:
        validate_revision(task)
        experiment = load_experiment(config_path(task))
        study = Path(experiment.dag["revise"]["output_dir"])
        historical = Path(experiment.dag["detect"]["output_dir"])
        material = provider_material(historical)
        historical_counts = saved_model_counts(historical)
        sol_coverage = model_coverage(historical_counts, "gpt-5.6-sol")
        historical_sol_missing += int(sol_coverage["missing"])
        if int(sol_coverage["missing"]):
            sol_recovery_tasks.append(task)
        if task == SMOKE_TASK:
            coverage = check(
                study, historical, expected_models=HISTORICAL_PANEL
            )
            if coverage.get("assignment_count") != 6:
                raise RuntimeError("historical smoke audit is not complete")
            historical_state = {
                "panel": list(HISTORICAL_PANEL),
                "coverage": coverage,
                "reuse_model": "gpt-5.6-sol",
                "excluded_historical_model": "gemini-3.8-flash",
                "models": {
                    model: model_coverage(historical_counts, model)
                    for model in HISTORICAL_PANEL
                },
            }
        else:
            historical_state = {
                "panel": list(HISTORICAL_PANEL),
                "provider_material": len(material),
                "models": {
                    model: model_coverage(historical_counts, model)
                    for model in HISTORICAL_PANEL
                },
                "reuse_model": "gpt-5.6-sol",
                "excluded_historical_model": "gemini-3.8-flash",
            }
        supplements = {}
        for provider, (model, _credential) in PROVIDERS.items():
            root = audit_dir(task, provider, experiment.experiment_id)
            counts = saved_model_counts(root)
            coverage = model_coverage(counts, model)
            if provider == "opus":
                opus_missing += int(coverage["missing"])
            supplements[provider] = {
                "model": model,
                "audit_dir": str(root),
                "exists": root.exists(),
                "provider_material": len(provider_material(root)),
                "coverage": coverage,
                "required": (task, provider) in planned_scopes(),
            }
        tasks[task] = {
            "revision_assignments": 6,
            "historical_audit_dir": str(historical),
            "historical": historical_state,
            "supplements": supplements,
        }
    return {
        "source_commit": clean_commit(),
        "provider_calls": 0,
        "main_panel": ["gpt-5.6-sol", "claude-opus-5"],
        "historical_gemini_in_main_panel": False,
        "planned_missing_scopes": [list(scope) for scope in planned_scopes()],
        "planned_missing_scope_count": len(planned_scopes()),
        "priority": "finish Opus before credit-blocked Sol",
        "planned_opus_missing_judgments": opus_missing,
        "planned_historical_sol_recovery_tasks": sol_recovery_tasks,
        "planned_historical_sol_missing_judgments": historical_sol_missing,
        "sol_dispatch_paused_for_openai_credit": True,
        "new_gemini_calls": 0,
        "maximum_parallel_audit_owners": 3,
        "per_scope_max_concurrency": 60,
        "tasks": tasks,
    }


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("audit inventory must run through Slurm")
    print(json.dumps(inventory()), flush=True)


if __name__ == "__main__":
    main()
