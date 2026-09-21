"""Provider-free validation for the Semi/Score-only Results40 expansion."""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.paraphrase_validation import validate_paraphrase_run
from rubric_gen.submission_revision.pretreatment_reuse import source_pool
from rubric_gen.submission_revision.seeds import resolve_seed
from rubric_gen.submission_revision.task_paraphrase_required import INTERNAL_STAGE_FANOUT

from make_configs import BUNDLE, CONDITIONS, ROOT, RUN, SHARDS, TASKS, config_path

PANEL = ("gpt-5.6-sol", "gemini-3.8-flash")
CANDIDATE = "attack_defense_v2.1_execution_verified_proactive_provenance"
OLD20 = (
    "da-10-1", "da-10-3", "da-12-2", "da-12-4", "da-13-1",
    "da-13-3", "da-13-5", "da-13-6", "da-14-1", "da-14-3",
    "da-14-8", "da-15-1", "da-15-2", "da-15-7", "da-15-8",
    "da-16-1", "da-18-5", "da-18-7", "da-19-1", "da-19-6",
)
OLD20_FEEDBACK_CONDITIONS = (
    "semi-static-execution-provenance-high-proposer",
    "semi-red-team-trace-execution-provenance-high-proposer",
    "score-only-static-execution-provenance-high-proposer",
    "score-only-red-team-trace-execution-provenance-high-proposer",
)


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _validate_config(
    shard: tuple[str, str],
    shared_inputs: dict[str, object] | None = None,
) -> dict:
    task, kind = shard
    config = config_path(task, kind)
    experiment = load_experiment(config)
    assert experiment.task_ids == (task,)
    assert experiment.replicates == 3
    configured_conditions = (
        (
            "semi-static",
            "score-only-static",
        ) if kind == "static" else (
            "semi-red-team-trace-execution-provenance-high-proposer",
            "score-only-red-team-trace-execution-provenance-high-proposer",
        )
    )
    expected_conditions = tuple(sorted(configured_conditions))
    assert tuple(experiment.execution_conditions) == expected_conditions
    assert len(experiment.execution_assignments) == 6
    assert tuple(experiment.outcome_audit["models"]) == PANEL
    assert tuple(experiment.payload["execution_audit_models"]) == PANEL
    assert experiment.protocol["rubric_proposer_model"] == "gpt-5.6-luna"
    if kind == "trace":
        assert experiment.protocol["red_team_trace_version"] == CANDIDATE
        assert experiment.protocol["rubric_proposer_reasoning_effort_by_stage"] == {"diagnosis": "high"}
    else:
        assert experiment.protocol.get("red_team_trace_version") is None
        assert not experiment.protocol.get("rubric_proposer_reasoning_effort_by_stage")
    assert experiment.protocol["min_revisions"] == 5
    assert experiment.protocol["max_revisions"] == 10
    assert experiment.seed_agent_config().model == "gpt-5.6-luna"
    assert experiment.seed_agent_config().reasoning_effort == "low"
    assert experiment.red_team_agent_config().model == "gpt-5.6-luna"
    assert experiment.red_team_agent_config().reasoning_effort == "low"
    assert all(experiment.solver_config(s).reasoning_effort == "low" for s in experiment.solver_ids)
    assert all("dropout" not in a.condition_id for a in experiment.execution_assignments)
    condition_rows = {row["condition_id"]: row for row in experiment.payload["conditions"]}
    all_condition_rows = {
        "semi-static": {
            "condition_id": "semi-static",
            "feedback_policy": "semi", "rubric_policy": "fixed",
        },
        "semi-red-team-trace-execution-provenance-high-proposer": {
            "condition_id": "semi-red-team-trace-execution-provenance-high-proposer",
            "feedback_policy": "semi", "rubric_policy": "red_team_trace",
        },
        "score-only-static": {
            "condition_id": "score-only-static",
            "feedback_policy": "score_only", "rubric_policy": "fixed",
        },
        "score-only-red-team-trace-execution-provenance-high-proposer": {
            "condition_id": "score-only-red-team-trace-execution-provenance-high-proposer",
            "feedback_policy": "score_only", "rubric_policy": "red_team_trace",
        },
    }
    assert condition_rows == {name: all_condition_rows[name] for name in expected_conditions}
    seed_root = Path(experiment.dag["seed"]["output_dir"])
    paraphrase_root = Path(experiment.dag["paraphrase"]["output_dir"])
    if shared_inputs is None:
        validate_paraphrase_run(paraphrase_root, experiment)
        variants = [
            {
                "variant": index,
                "txt_sha256": sha(paraphrase_root / "tasks" / task / f"variant-{index:03d}.txt"),
                "json_sha256": sha(paraphrase_root / "tasks" / task / f"variant-{index:03d}.json"),
            }
            for index in range(5)
        ]
        seeds = []
        for replicate in range(1, 4):
            seed = resolve_seed(
                seed_root,
                experiment.task_dir(task),
                replicate,
                seed_generator=experiment.seed_agent_config(),
                prompt_profile=experiment.protocol["prompt"],
                benchmark=experiment.benchmark,
            )
            seeds.append({"replicate": replicate, "sha256": seed.sha256})
    else:
        if (
            shared_inputs["task_id"] != task
            or shared_inputs["seed_root"] != str(seed_root)
            or shared_inputs["paraphrase_root"] != str(paraphrase_root)
        ):
            raise RuntimeError(f"static/trace input roots differ for {task}")
        seeds = list(shared_inputs["seeds"])
        variants = list(shared_inputs["variants"])
    pool = source_pool(experiment)
    if kind == "static" and pool is not None:
        raise RuntimeError("static shard unexpectedly has a pretreatment source")
    return {
        "task_id": task,
        "shard": kind,
        "config": str(config),
        "config_sha256": sha(config),
        "experiment_id": experiment.experiment_id,
        "task_instruction_sha256": sha(experiment.task_dir(task) / "instruction.md"),
        "task_rubric_sha256": sha(experiment.task_dir(task) / "tests/rubric.txt"),
        "seed_root": str(seed_root),
        "seeds": seeds,
        "paraphrase_root": str(paraphrase_root),
        "variants": variants,
        "pretreatment_source": str(pool) if pool else None,
        "pretreatment_source_files": sum(1 for p in pool.rglob("*") if p.is_file()) if pool else 0,
    }


def _validate_old20_feedback_source() -> dict:
    bundle = ROOT / "experiments/trace-v21-execution-verified-provenance-result20-feedback"
    source = bundle / "result20.yaml"
    experiment = load_experiment(source)
    run = Path("/data/user_data/aydanh/rubric_gen/runs/rtt-result20-feedback-policies-20260920")
    receipt = json.loads((run / "revision-completion.json").read_text())
    observed = {
        "receipt_success": receipt.get("success"),
        "receipt_assignment_count": receipt.get("assignment_count"),
        "task_ids": list(experiment.task_ids),
        "execution_conditions": list(experiment.execution_conditions),
    }
    if (
        receipt.get("success") is not True
        or receipt.get("assignment_count") != 240
        or tuple(experiment.task_ids) != OLD20
        or tuple(experiment.execution_conditions) != tuple(sorted(OLD20_FEEDBACK_CONDITIONS))
    ):
        raise RuntimeError(f"completed Results20 Semi/Score-only source changed: {observed}")
    return {
        "config": str(source),
        "config_sha256": sha(source),
        "experiment_id": experiment.experiment_id,
        "study_dir": experiment.dag["revise"]["output_dir"],
        "sol_opus_audit_dir": experiment.dag["detect"]["output_dir"],
        "gemini_audit_dir": str(run / "audit-gemini" / experiment.experiment_id),
        "assignment_count": receipt["assignment_count"],
    }


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("Results40 validation requires a Slurm compute node")
    if len(TASKS) != 20 or set(TASKS) & set(OLD20):
        raise RuntimeError("new20 membership is not a disjoint 20-task block")
    runtime = policy()
    assert runtime["aggregate_concurrency"] == 60
    assert runtime["audit_studies"] == 3
    assert runtime["audit_provider_concurrency"] == {
        "openai": 60,
        "anthropic": 60,
        "google": 60,
    }
    assert INTERNAL_STAGE_FANOUT == 4
    old20_source = _validate_old20_feedback_source()
    prior_receipt_path = (
        ROOT / "experiments/trace-v21-execution-verified-provenance-result40/"
        "receipts/input-validation.json"
    )
    prior_receipt = json.loads(prior_receipt_path.read_text())
    if (
        prior_receipt.get("success") is not True
        or tuple(prior_receipt.get("tasks", ())) != TASKS
        or prior_receipt.get("assignment_count") != 240
        or prior_receipt.get("provider_calls") != 0
    ):
        raise RuntimeError("authoritative Results40 input receipt changed")
    prior_static = {
        row["task_id"]: row
        for row in prior_receipt["input_rows"]
        if row["shard"] == "static"
    }
    if set(prior_static) != set(TASKS):
        raise RuntimeError("authoritative Results40 receipt lacks a task input row")
    static_shards = tuple((task, "static") for task in TASKS)
    with ThreadPoolExecutor(max_workers=4) as workers:
        static_rows = list(workers.map(
            lambda shard: _validate_config(shard, prior_static[shard[0]]),
            static_shards,
        ))
    static_by_task = {row["task_id"]: row for row in static_rows}
    trace_rows = [
        _validate_config((task, "trace"), static_by_task[task])
        for task in TASKS
    ]
    if any(
        row["pretreatment_source"] is None
        or int(row["pretreatment_source_files"]) == 0
        for row in trace_rows
    ):
        raise RuntimeError("every trace shard must reuse completed Results40 pretreatment")
    rows = [
        row
        for task in TASKS
        for row in (static_by_task[task], next(item for item in trace_rows if item["task_id"] == task))
    ]
    if sum(len(load_experiment(config_path(task, kind)).execution_assignments) for task, kind in SHARDS) != 240:
        raise RuntimeError("Results40 new assignment scope is not 240")
    for root in (
        RUN,
        Path("/data/user_data/aydanh/rubric_gen/live/rtt-result40-feedback-policies-20260920"),
        Path("/data/user_data/aydanh/rubric_gen/cache/rtt-result40-feedback-policies-20260920"),
    ):
        root.mkdir(parents=True, exist_ok=True)
        probe = root / f".write-probe-{os.environ['SLURM_JOB_ID']}"
        probe.write_text("ok\n")
        probe.unlink()
    receipt = {
        "success": True,
        "provider_calls": 0,
        "job_id": os.environ["SLURM_JOB_ID"],
        "source_commit": os.environ.get("RESULT40_SOURCE_COMMIT"),
        "tasks": list(TASKS),
        "conditions": list(CONDITIONS),
        "assignment_count": 240,
        "native_shards": 40,
        "randomization_seed": 20260820,
        "input_rows": rows,
        "old20_source": old20_source,
        "reused_input_receipt": {
            "path": str(prior_receipt_path),
            "sha256": sha(prior_receipt_path),
            "job_id": prior_receipt["job_id"],
        },
        "heldout_generation": {
            "new20": "rigorous-V2 prompt source commit 47463ca",
            "old20": "historical original-20 producer prompt; full text unrecovered",
        },
        "runtime": runtime,
        "revision": {
            "shard_workers": 4,
            "assignment_workers_per_shard": 6,
            "maximum_assignment_workers": 24,
            "aggregate_provider_concurrency": 60,
            "internal_fanout": 4,
        },
        "audit": {
            "sol_workers": 60,
            "gemini_workers": 3,
            "openai": 60,
            "anthropic": 60,
            "google": 60,
            "audit_studies": 3,
            "panels": {
                "sol": ["gpt-5.6-sol"],
                "gemini": ["gemini-3.8-flash"],
                "sol_gemini": ["gpt-5.6-sol", "gemini-3.8-flash"],
            },
        },
    }
    write_json_atomic(BUNDLE / "receipts/input-validation.json", receipt)
    write_json_atomic(RUN / "input-validation.json", receipt)
    print(json.dumps({
        "success": True,
        "tasks": len(TASKS),
        "assignments": 240,
        "pretreatment_reused": sum(row["shard"] == "trace" and row["pretreatment_source"] is not None for row in rows),
        "pretreatment_generated": sum(row["shard"] == "trace" and row["pretreatment_source"] is None for row in rows),
    }), flush=True)


if __name__ == "__main__":
    main()
