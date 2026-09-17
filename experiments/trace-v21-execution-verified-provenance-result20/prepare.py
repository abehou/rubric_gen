"""Provider-free validation of frozen Results20 inputs and execution settings."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.evolution import RubricProposer
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.paraphrase_validation import (
    resolve_paraphrase_selection,
    validate_paraphrase_run,
)
from rubric_gen.submission_revision.seeds import resolve_seed
from rubric_gen.submission_revision.study import StudyRunConfig, StudyRunner
from rubric_gen.submission_revision.task_paraphrase_required import INTERNAL_STAGE_FANOUT

BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
CONFIG = BUNDLE / "result20.yaml"
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/rtt-result20-next")
TASKS = (
    "da-10-1", "da-10-3", "da-12-2", "da-12-4", "da-13-1",
    "da-13-3", "da-13-5", "da-13-6", "da-14-1", "da-14-3",
    "da-14-8", "da-15-1", "da-15-2", "da-15-7", "da-15-8",
    "da-16-1", "da-18-5", "da-18-7", "da-19-1", "da-19-6",
)
CONDITIONS = (
    "full-red-team-trace-execution-verified-proactive-provenance",
    "user-simulator-red-team-trace-execution-verified-proactive-provenance",
)
PANEL = ("gpt-5.6-sol", "claude-opus-5")


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inventory(root: Path) -> dict[str, str]:
    return {
        str(path.relative_to(root)): sha(path)
        for path in root.rglob("*")
        if path.is_file() and not path.name.endswith(".lock")
    }


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Results20 input validation requires a Slurm compute node")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("provider calls are forbidden during input validation")

    RubricProposer._run_direct_proposer = forbidden
    experiment = load_experiment(CONFIG)
    assert tuple(experiment.task_ids) == TASKS
    assert experiment.replicates == 3 and len(experiment.execution_assignments) == 120
    assert tuple(experiment.execution_conditions) == CONDITIONS
    assert tuple(experiment.outcome_audit["models"]) == PANEL
    assert experiment.protocol["red_team_trace_version"] == (
        "attack_defense_v2.1_execution_verified_proactive_provenance"
    )
    assert experiment.protocol["rubric_proposer_model"] == "gpt-5.6-luna"
    assert experiment.protocol["rubric_proposer_reasoning_effort_by_stage"] == {
        "diagnosis": "high"
    }
    assert experiment.seed_agent_config().reasoning_effort == "low"
    assert experiment.red_team_agent_config().reasoning_effort == "low"
    assert all(
        experiment.solver_config(solver_id).reasoning_effort == "low"
        for solver_id in experiment.solver_ids
    )
    assert INTERNAL_STAGE_FANOUT == 4

    runtime = policy()
    assert runtime["aggregate_concurrency"] == 60
    assert runtime["audit_studies"] == 1
    assert runtime["audit_provider_concurrency"] == {
        "openai": 60, "anthropic": 60,
    }

    seed_root = Path(experiment.dag["seed"]["output_dir"])
    paraphrase_root = Path(experiment.dag["paraphrase"]["output_dir"])
    assert seed_root.is_dir() and not seed_root.is_symlink()
    assert paraphrase_root.is_dir() and not paraphrase_root.is_symlink()
    validate_paraphrase_run(paraphrase_root, experiment)

    source_study = Path(experiment.pretreatment_source["study_dir"])
    assert source_study.is_dir() and (source_study / "study.json").is_file()
    study = Path(experiment.dag["revise"]["output_dir"])
    runner = StudyRunner(StudyRunConfig(
        experiment, seed_root, paraphrase_root, study, 60, resume=study.exists(),
    ))
    source_pool = runner.pretreatment_source_root
    assert source_pool == source_study / "pretreatment-rubrics"
    source_before = inventory(source_pool)
    assert source_before

    rows = []
    for task in experiment.task_ids:
        selection = resolve_paraphrase_selection(paraphrase_root, experiment, task)
        variants = [
            {
                "variant": variant,
                "sha256": sha(paraphrase_root / "tasks" / task / f"variant-{variant:03d}.txt"),
            }
            for variant in range(5)
        ]
        for replicate in range(1, 4):
            seed = resolve_seed(
                seed_root,
                experiment.task_dir(task),
                replicate,
                seed_generator=experiment.seed_agent_config(),
                prompt_profile=experiment.protocol["prompt"],
                benchmark=experiment.benchmark,
            )
            rows.append({
                "task_id": task,
                "replicate": replicate,
                "seed_sha256": seed.sha256,
                "selected_sha256": selection.optimizer_sha256,
                "development_sha256": selection.development_sha256,
                "variants": variants,
            })

    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(runner._prepare_pretreatment_rubric, experiment.task_ids))
    assert inventory(source_pool) == source_before
    consumer_pool = inventory(runner.pretreatment_root)
    assert all(consumer_pool.get(name) == digest for name, digest in source_before.items())

    for root in (
        RUN,
        Path("/data/user_data/aydanh/rubric_gen/live/rtt-result20-next"),
        Path("/data/user_data/aydanh/rubric_gen/cache/rtt-result20-next"),
    ):
        root.mkdir(parents=True, exist_ok=True)
        probe = root / f".write-probe-{os.environ['SLURM_JOB_ID']}"
        probe.write_text("ok\n")
        probe.unlink()

    receipt = {
        "success": True,
        "provider_calls": 0,
        "job_id": os.environ["SLURM_JOB_ID"],
        "experiment_id": experiment.experiment_id,
        "config_sha256": sha(CONFIG),
        "tasks": list(TASKS),
        "conditions": list(CONDITIONS),
        "assignments": 120,
        "seed": 20260820,
        "matched_inputs": rows,
        "source_pretreatment_experiment_id": experiment.pretreatment_source[
            "experiment_id"
        ],
        "source_pretreatment_inventory_sha256": hashlib.sha256(
            json.dumps(source_before, sort_keys=True).encode()
        ).hexdigest(),
        "consumer_pretreatment_inventory_sha256": hashlib.sha256(
            json.dumps(consumer_pool, sort_keys=True).encode()
        ).hexdigest(),
        "runtime": runtime,
        "revision_concurrency": 60,
        "internal_fanout": 4,
        "audit_concurrency": {"openai": 60, "anthropic": 60, "total": 120},
    }
    receipt_dir = RUN / "receipts"
    receipt_dir.mkdir(parents=True, exist_ok=True)
    write_json_atomic(receipt_dir / "input-validation.json", receipt)
    local = BUNDLE / "receipts"
    local.mkdir(exist_ok=True)
    write_json_atomic(local / "input-validation.json", receipt)
    print(json.dumps({
        "success": True,
        "experiment_id": experiment.experiment_id,
        "assignments": 120,
        "provider_calls": 0,
    }), flush=True)


if __name__ == "__main__":
    main()
