"""Provider-free inventory for the formal Sol+Opus gap-pilot audit."""

from __future__ import annotations

import json
import os
from pathlib import Path

from rubric_gen.submission_revision.experiment import load_experiment

from audit_sol_opus import (
    PROVIDERS,
    audit_dir,
    clean_commit,
    planned_scopes,
    validate_revision,
)
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


def inventory() -> dict[str, object]:
    sys_path = str(ROOT / "scripts/diagnostics")
    import sys

    sys.path.insert(0, sys_path)
    from check_audit_coverage import check

    tasks = {}
    for task in TASKS:
        validate_revision(task)
        experiment = load_experiment(config_path(task))
        study = Path(experiment.dag["revise"]["output_dir"])
        historical = Path(experiment.dag["detect"]["output_dir"])
        material = provider_material(historical)
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
            }
        else:
            if material:
                raise RuntimeError(
                    f"unexpected partial historical audit requires review: {task}"
                )
            historical_state = {"panel": [], "provider_material": 0}
        supplements = {}
        for provider, (model, _credential) in PROVIDERS.items():
            root = audit_dir(task, provider, experiment.experiment_id)
            supplements[provider] = {
                "model": model,
                "audit_dir": str(root),
                "exists": root.exists(),
                "provider_material": len(provider_material(root)),
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
