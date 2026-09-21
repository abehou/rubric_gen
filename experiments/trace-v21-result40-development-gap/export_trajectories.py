"""Export bounded, provider-free evidence for the five saved RTT trajectories."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
RESULT40_BUNDLE = (
    ROOT / "experiments/trace-v21-execution-verified-provenance-result40"
)
sys.path.insert(0, str(RESULT40_BUNDLE))

from audit_scope import config_path, scoped_experiment  # noqa: E402

from rubric_gen.artifacts.hashing import sha256_file  # noqa: E402
from rubric_gen.artifacts.serialization import write_json_atomic  # noqa: E402
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig  # noqa: E402
from rubric_gen.submission_revision.evaluation.targets import (  # noqa: E402
    load_evaluation_targets,
)
from rubric_gen.submission_revision.source_resolution import (  # noqa: E402
    resolve_study_sources,
)
from rubric_gen.submission_revision.user_simulator_history import (  # noqa: E402
    _solver_visible_replies,
)


TASKS = ("da-26-4", "da-26-2", "da-17-1", "da-17-5", "da-20-4")
MODELS = ("gpt-5.6-sol", "gemini-3.8-flash")
RUN = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-result40-development-score-pilot-20260921"
)
OUTPUT = RUN / "forensics" / "trajectory-evidence.json"
EVOLUTION_FILES = (
    "evolution.json",
    "artifact-history.json",
    "pairwise-assessment-rubric-free.json",
    "pairwise-assessment-active-rubric.json",
    "pairwise-assessment-development-rubric.json",
    "pairwise-comparisons.json",
    "criterion-proposal.json",
    "criterion-validation.json",
    "aggregate-margins.json",
    "criteria.json",
)
TEXT_LIMIT = 12_000


def read_json(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def bounded(value: object, *, limit: int = 4_000) -> object:
    if isinstance(value, str):
        if len(value) <= limit:
            return value
        return {
            "truncated": True,
            "original_characters": len(value),
            "head": value[: limit * 2 // 3],
            "tail": value[-limit // 3 :],
        }
    if isinstance(value, list):
        return [bounded(item, limit=limit) for item in value]
    if isinstance(value, dict):
        return {str(key): bounded(item, limit=limit) for key, item in value.items()}
    return value


def text(path: Path, limit: int = TEXT_LIMIT) -> object:
    value = path.read_text(encoding="utf-8", errors="replace")
    return bounded(value, limit=limit)


def json_files(root: Path) -> dict[str, object]:
    if not root.exists():
        return {}
    values = {}
    for path in sorted(root.glob("*.json")):
        values[path.name] = bounded(read_json(path))
    return values


def workspace_record(workspace: Path) -> dict[str, object]:
    files = []
    selected_text = {}
    for path in sorted(workspace.rglob("*")):
        if path.is_symlink() or not path.is_file():
            continue
        relative = path.relative_to(workspace).as_posix()
        size = path.stat().st_size
        files.append({
            "path": relative,
            "bytes": size,
            "sha256": sha256_file(path),
        })
        name = path.name.lower()
        if (
            name in {"answer.md", "trace.md", "final_answer.md", "readme.md"}
            or relative.startswith("artifacts/")
            and path.suffix.lower() in {".md", ".txt", ".json", ".csv"}
            and size <= 100_000
        ):
            selected_text[relative] = text(path)
    return {"files": files, "selected_text": selected_text}


def generation_records(root: Path) -> list[dict[str, object]]:
    values = []
    for generation in sorted((root / "rubric-generations").glob("generation-*")):
        item = {"generation": generation.name, "path": str(generation)}
        manifest = generation / "manifest.json"
        if manifest.exists():
            item["manifest"] = read_json(manifest)
        for name in EVOLUTION_FILES:
            path = generation / name
            if path.exists():
                item[name] = bounded(read_json(path))
        rubric = generation / "rubric.txt"
        if rubric.exists():
            item["rubric.txt"] = text(rubric)
        values.append(item)
    return values


def attack_records(root: Path) -> list[dict[str, object]]:
    values = []
    for checkpoint in sorted((root / "red-team").glob("checkpoint-*")):
        item = {"checkpoint": checkpoint.name, "path": str(checkpoint)}
        for name in (
            "manifest.json",
            "status.json",
            "attack-record.json",
            "attack-record-v2.json",
        ):
            path = checkpoint / name
            if path.exists():
                item[name] = bounded(read_json(path))
        trajectory = checkpoint / "trajectory.stream.jsonl"
        if trajectory.exists():
            replies = _solver_visible_replies(trajectory)
            item["assistant_reply_count"] = len(replies)
            item["last_assistant_reply"] = (
                bounded(replies[-1], limit=8_000) if replies else None
            )
        values.append(item)
    return values


def turn_records(root: Path) -> list[dict[str, object]]:
    values = []
    for turn in sorted((root / "turns").glob("turn-*")):
        item = {"turn": turn.name, "path": str(turn)}
        prompt = turn / "prompt.txt"
        if prompt.exists():
            item["prompt"] = text(prompt, limit=8_000)
        trajectory = turn / "trajectory.stream.jsonl"
        if trajectory.exists():
            replies = _solver_visible_replies(trajectory)
            item["assistant_reply_count"] = len(replies)
            item["last_assistant_reply"] = (
                bounded(replies[-1], limit=8_000) if replies else None
            )
        values.append(item)
    return values


def targets_for(task: str):
    output_dir = RUN / "forensics" / "unused-output" / task
    experiment = scoped_experiment(
        config_path(task, "trace"),
        models=MODELS,
        output_dir=output_dir,
    )
    config = EvaluationConfig(
        experiment=experiment,
        study_dir=Path(experiment.dag["revise"]["output_dir"]),
        paraphrase_dir=Path(experiment.dag["paraphrase"]["output_dir"]),
        output_dir=output_dir,
        max_concurrency=4,
        resume=True,
    )
    sources = resolve_study_sources(config.study_dir, experiment)
    targets = load_evaluation_targets(config, sources)
    expected = {
        (task, replicate, condition)
        for replicate in (1, 2, 3)
        for condition in (
            "full-red-team-trace-execution-verified-proactive-provenance",
            "user-simulator-red-team-trace-execution-verified-proactive-provenance",
        )
    }
    observed = {
        (target.task_id, target.replicate, target.condition_id)
        for target in targets
    }
    if observed != expected:
        raise RuntimeError(f"unexpected RTT forensic scope for {task}")
    return targets


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("trajectory export must run on a Babel compute node")
    cases = []
    for task in TASKS:
        for target in targets_for(task):
            root = target.experiment_dir
            state = read_json(root / "state.json")
            final_submission = target.final_submission
            cases.append({
                "task_id": target.task_id,
                "replicate": target.replicate,
                "arm": (
                    "User"
                    if target.condition_id.startswith("user-simulator")
                    else "Full"
                ),
                "condition_id": target.condition_id,
                "assignment_id": target.assignment_id,
                "experiment_dir": str(root),
                "state": state,
                "active_scores": list(target.active_scores),
                "fixed_original_scores": list(target.fixed_original_scores),
                "red_team": attack_records(root),
                "generations": generation_records(root),
                "trace_defense_reminders": json_files(
                    root / "trace-defense-reminders"
                ),
                "execution_truthfulness_issues": json_files(
                    root / "execution-truthfulness-issues"
                ),
                "feedback": json_files(root / "feedback"),
                "turns": turn_records(root),
                "final_submission": {
                    "path": str(final_submission),
                    "snapshot": read_json(final_submission / "snapshot.json"),
                    "status": read_json(final_submission / "status.json"),
                    "workspace": workspace_record(final_submission / "workspace"),
                },
            })
    if len(cases) != 30:
        raise RuntimeError(f"expected 30 RTT cases, found {len(cases)}")
    result = {
        "kind": "result40-development-gap-trajectory-evidence",
        "source_commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "slurm_job_id": os.environ["SLURM_JOB_ID"],
        "task_count": len(TASKS),
        "case_count": len(cases),
        "provider_calls": 0,
        "tasks": list(TASKS),
        "cases": cases,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    write_json_atomic(OUTPUT, result)
    print(json.dumps({
        "status": "completed",
        "cases": len(cases),
        "output": str(OUTPUT),
        "provider_calls": 0,
    }, indent=2), flush=True)


if __name__ == "__main__":
    main()
