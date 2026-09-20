"""Provider-free validation for the frozen Semi/Score-only Results20 run."""
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
RUN = Path("/data/user_data/aydanh/rubric_gen/runs/rtt-result20-feedback-policies-20260920")
TASKS = (
    "da-10-1", "da-10-3", "da-12-2", "da-12-4", "da-13-1",
    "da-13-3", "da-13-5", "da-13-6", "da-14-1", "da-14-3",
    "da-14-8", "da-15-1", "da-15-2", "da-15-7", "da-15-8",
    "da-16-1", "da-18-5", "da-18-7", "da-19-1", "da-19-6",
)
CONDITIONS = (
    "semi-static",
    "semi-red-team-trace-execution-verified-proactive-provenance",
    "score-only-static",
    "score-only-red-team-trace-execution-verified-proactive-provenance",
)
PANEL = ("gpt-5.6-sol", "claude-opus-5", "gemini-3.8-flash")
TRACE_VERSION = "attack_defense_v2.1_execution_verified_proactive_provenance"


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
        raise RuntimeError("Results20 feedback validation requires a compute node")

    def forbidden(*_args, **_kwargs):
        raise AssertionError("provider calls are forbidden during input validation")

    RubricProposer._run_direct_proposer = forbidden
    experiment = load_experiment(CONFIG)
    assert tuple(experiment.task_ids) == TASKS
    assert experiment.replicates == 3
    assert len(experiment.execution_assignments) == 240
    assert tuple(experiment.execution_conditions) == CONDITIONS
    assert tuple(experiment.outcome_audit["models"]) == PANEL
    assert experiment.protocol["red_team_trace_version"] == TRACE_VERSION
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
    expected_conditions = {
        "semi-static": ("semi", "fixed"),
        "semi-red-team-trace-execution-verified-proactive-provenance":
            ("semi", "red_team_trace"),
        "score-only-static": ("score_only", "fixed"),
        "score-only-red-team-trace-execution-verified-proactive-provenance":
            ("score_only", "red_team_trace"),
    }
    for condition_id, expected in expected_conditions.items():
        condition = experiment.condition(condition_id)
        assert (condition["feedback_policy"], condition["rubric_policy"]) == expected

    runtime = policy()
    assert runtime["aggregate_concurrency"] == 60
    assert runtime["audit_studies"] == 3
    assert runtime["audit_provider_concurrency"] == {
        "openai": 60, "anthropic": 60, "google": 60,
    }

    seed_root = Path(experiment.dag["seed"]["output_dir"])
    paraphrase_root = Path(experiment.dag["paraphrase"]["output_dir"])
    assert seed_root.is_dir() and not seed_root.is_symlink()
    assert paraphrase_root.is_dir() and not paraphrase_root.is_symlink()
    validate_paraphrase_run(paraphrase_root, experiment)
    assert sha(paraphrase_root / "manifest.json") == (
        "404d8cb9437c4f6d766c40a1c9fade066a0e53aab249c37fc63da990a68bc0e8"
    )

    source_study = Path(experiment.pretreatment_source["study_dir"])
    assert source_study.is_dir() and (source_study / "study.json").is_file()
    temporary_study = Path(os.environ["TMPDIR"]) / "pretreatment-validation"
    runner = StudyRunner(StudyRunConfig(
        experiment, seed_root, paraphrase_root, temporary_study, 4,
        resume=temporary_study.exists(),
    ))
    source_pool = runner.pretreatment_source_root
    source_before = inventory(source_pool)
    assert source_before
    rows = []
    for task in experiment.task_ids:
        selection = resolve_paraphrase_selection(paraphrase_root, experiment, task)
        variants = [
            sha(paraphrase_root / "tasks" / task / f"variant-{variant:03d}.txt")
            for variant in range(5)
        ]
        for replicate in range(1, 4):
            seed = resolve_seed(
                seed_root, experiment.task_dir(task), replicate,
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
                "variant_sha256": variants,
            })
    with ThreadPoolExecutor(max_workers=4) as workers:
        list(workers.map(runner._prepare_pretreatment_rubric, experiment.task_ids))
    assert inventory(source_pool) == source_before
    consumer_pool = inventory(runner.pretreatment_root)
    assert all(consumer_pool.get(name) == digest for name, digest in source_before.items())

    roots = (
        RUN,
        Path("/data/user_data/aydanh/rubric_gen/live/rtt-result20-feedback-policies-20260920"),
        Path("/data/user_data/aydanh/rubric_gen/cache/rtt-result20-feedback-policies-20260920"),
    )
    for root in roots:
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
        "assignments": 240,
        "seed": 20260820,
        "matched_inputs": rows,
        "source_pretreatment_experiment_id": experiment.pretreatment_source["experiment_id"],
        "source_pretreatment_inventory_sha256": hashlib.sha256(
            json.dumps(source_before, sort_keys=True).encode()
        ).hexdigest(),
        "consumer_pretreatment_inventory_sha256": hashlib.sha256(
            json.dumps(consumer_pool, sort_keys=True).encode()
        ).hexdigest(),
        "runtime": runtime,
        "revision_concurrency": 60,
        "internal_fanout": 4,
        "audit_partitions": {"openai": 60, "anthropic": 60, "google": 60},
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
        "assignments": 240,
        "provider_calls": 0,
    }), flush=True)


if __name__ == "__main__":
    main()
