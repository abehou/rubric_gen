"""Run bounded Luna-high attack or solver replays on frozen saved cases.

This diagnostic never resumes the paused Dev3.  It creates independent
workspaces, keeps the saved Luna-low outputs as controls, and changes only the
Luna reasoning effort from low to high.
"""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import importlib.util
import json
import os
from pathlib import Path
import sys
import time

from dotenv import dotenv_values

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPOSITORY_ROOT / "src"))

from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.benchmarks.biomnibench_da.contract import BIOMNIBENCH_DA
from rubric_gen.runtime.agents.codex_sessions import CodexSdkSessionDriver
from rubric_gen.runtime.agents.costs import RunCost
from rubric_gen.runtime.agents.models import AgentRunConfig
from rubric_gen.runtime.agents.workspaces import TaskWorkspace
from rubric_gen.submission_revision.task_required_enforcement import _command_records
from rubric_gen.submission_revision.trace_defense_v2_attack import attack_record


ROOT = _REPOSITORY_ROOT
RUN = ROOT / "runs/trace-stage-model-allocation-20260917"
MANIFEST = RUN / "frozen/manifest.json"
RUNTIME_CONFIG = RUN / "runtime/structured-high.json"


def read(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def load_saved_case_module():
    path = ROOT / "experiments/trace-v21-execution-verified-dropout/run_saved_case.py"
    spec = importlib.util.spec_from_file_location("stage_allocation_saved_cases", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


SAVED = load_saved_case_module()


def arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--stage", choices=("attack", "solver"), required=True)
    parser.add_argument("--case", help="optional exact frozen case ID")
    return parser.parse_args()


def configure() -> None:
    key = dotenv_values(ROOT / ".env.local").get("OPENAI_API_KEY")
    if not key:
        raise RuntimeError("OPENAI_API_KEY is unavailable in .env.local")
    os.environ["OPENAI_API_KEY"] = str(key)
    # The app-server child starts with the benchmark workspace as cwd.  Python
    # 3.12 ignores the environment's underscore-prefixed editable .pth file,
    # so make the checked-out src tree explicit for that local child only.
    existing_pythonpath = os.environ.get("PYTHONPATH")
    os.environ["PYTHONPATH"] = os.pathsep.join(
        value for value in (str((ROOT / "src").resolve()), existing_pythonpath)
        if value
    )
    if not RUNTIME_CONFIG.is_file():
        raise RuntimeError("structured replay must create the local runtime policy first")
    os.environ["RUBRIC_GEN_RUNTIME_CONFIG"] = str(RUNTIME_CONFIG.resolve())
    os.environ.setdefault(
        "RUBRIC_GEN_INVOCATION_ID", "trace-stage-luna-high-agent-20260917"
    )


def driver() -> CodexSdkSessionDriver:
    return CodexSdkSessionDriver(
        AgentRunConfig(
            provider="codex",
            model="gpt-5.6-luna",
            reasoning_effort="high",
            quiet=True,
            retries=1,
            timeout_seconds=7200,
        ),
        contract=BIOMNIBENCH_DA,
    )


def run_turn(workspace: Path, prompt: str, turn_dir: Path) -> tuple[dict, float]:
    started = time.monotonic()
    session = driver()
    try:
        result = session.start(workspace, prompt, turn_dir)
        if result.exit_code != 0:
            raise RuntimeError(f"Luna-high diagnostic exited with {result.exit_code}")
    finally:
        session.close()
    return read(turn_dir / "status.json"), time.monotonic() - started


def common_result(
    *, case_id: str, case_root: Path, before: dict, latency: float,
) -> dict[str, object]:
    workspace = case_root / "workspace"
    turn_dir = case_root / "turn-001"
    status = read(turn_dir / "status.json")
    errors = BIOMNIBENCH_DA.output_errors(workspace)
    if errors:
        raise RuntimeError(f"{case_id} output contract failed: {', '.join(errors)}")
    after = SAVED._tree_manifest(workspace)
    commands, parse_errors = _command_records(turn_dir / "trajectory.stream.jsonl")
    cost = RunCost.from_status(turn_dir / "status.json")
    return {
        "case_id": case_id,
        "provider": "codex",
        "model": status.get("model"),
        "reasoning_effort": "high",
        "session_id": status.get("session_id"),
        "exit_code": status.get("exit_code"),
        "latency_seconds": latency,
        "new_commands": commands,
        "trajectory_parse_error_count": parse_errors,
        "changed_outputs": SAVED._changed(before, after),
        "before_manifest": before,
        "after_manifest": after,
        **cost.fields(),
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


def prepare(case_root: Path, task_id: str, source: Path) -> tuple[Path, dict]:
    if case_root.exists():
        turn_dir = case_root / "turn-001"
        attempts = list(turn_dir.glob("attempts/*.trajectory.stream.jsonl"))
        if (turn_dir / "status.json").exists() or attempts:
            raise RuntimeError(
                f"case has a started or uncertain provider turn: {case_root}"
            )
        launch = read(case_root / "launch.json")
        workspace = case_root / "workspace"
        before = SAVED._tree_manifest(workspace)
        if before != launch["before_manifest"]:
            raise RuntimeError(f"pre-turn workspace changed: {case_root}")
        retry_path = case_root / "pre-turn-retry.json"
        if not retry_path.exists():
            write_json_atomic(retry_path, {
                "kind": "trace-stage-agent-pre-turn-retry-v1",
                "reason": (
                    "Prior invocation failed during local Codex app-server "
                    "initialization before a provider thread or turn existed."
                ),
                "provider_call_started": False,
                "workspace_unchanged": True,
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            })
        return workspace, before
    case_root.mkdir(parents=True)
    workspace = case_root / "workspace"
    TaskWorkspace(ROOT / f"data/biomnibench-da/{task_id}", workspace).create()
    SAVED._copy_public_workspace(source, workspace)
    return workspace, SAVED._tree_manifest(workspace)


def run_attack(case: dict[str, object]) -> dict[str, object]:
    case_id = case["case_id"]
    case_root = RUN / "attack-high/cases" / case_id
    result_path = case_root / "result.json"
    if result_path.is_file():
        return read(result_path)
    source = ROOT / case["source_workspace"]
    prompt_path = ROOT / case["prompt_path"]
    prompt = prompt_path.read_text(encoding="utf-8")
    low_record = read(ROOT / case["low_attack_record_path"])
    task_id = case_id.split("--", 1)[0]
    workspace, before = prepare(case_root, task_id, source)
    (case_root / "prompt.txt").write_text(prompt, encoding="utf-8")
    write_json_atomic(case_root / "launch.json", {
        "kind": "trace-stage-luna-high-attack-launch-v1",
        "case_id": case_id,
        "source_workspace": case["source_workspace"],
        "source_public_sha256": case["source_public_sha256"],
        "prompt_source": case["prompt_path"],
        "prompt_sha256": sha256_text(prompt),
        "low_attack_record": case["low_attack_record_path"],
        "low_attack_record_sha256": case["low_attack_record_sha256"],
        "controlled_change": "gpt-5.6-luna reasoning low to high only",
        "before_manifest": before,
        "started_at": datetime.now(timezone.utc).isoformat(),
    })
    status, latency = run_turn(workspace, prompt, case_root / "turn-001")
    result = common_result(
        case_id=case_id, case_root=case_root, before=before, latency=latency,
    )
    record = attack_record(
        case_root / "turn-001/trajectory.stream.jsonl",
        BIOMNIBENCH_DA.render_user_review(source),
        BIOMNIBENCH_DA.render_user_review(workspace),
        source,
        workspace,
        version=low_record["red_team_trace_version"],
    )
    result.update({
        "kind": "trace-stage-luna-high-attack-result-v1",
        "prompt_sha256": sha256_text(prompt),
        "source_public_sha256": case["source_public_sha256"],
        "low_attack_record": case["low_attack_record_path"],
        "high_attack_record": record,
        "status_model": status.get("model"),
    })
    write_json_atomic(result_path, result)
    return result


def run_solver(case: dict[str, object]) -> dict[str, object]:
    case_id = case["case_id"]
    case_root = RUN / "solver-high/cases" / case_id
    result_path = case_root / "result.json"
    if result_path.is_file():
        return read(result_path)
    source = ROOT / case["source_workspace"]
    prompt = case["solver_visible_prompt"]
    if sha256_text(prompt) != case["solver_visible_prompt_sha256"]:
        raise RuntimeError(f"frozen solver prompt changed: {case_id}")
    workspace, before = prepare(case_root, "da-11-1", source)
    (case_root / "prompt.txt").write_text(prompt, encoding="utf-8")
    write_json_atomic(case_root / "launch.json", {
        "kind": "trace-stage-luna-high-solver-launch-v1",
        "case_id": case_id,
        "source_workspace": case["source_workspace"],
        "source_submission": case["source_submission"],
        "ordinary_prompt": case["ordinary_prompt"],
        "ordinary_prompt_sha256": case["ordinary_prompt_sha256"],
        "solver_visible_prompt_sha256": case["solver_visible_prompt_sha256"],
        "issue": case["issue"],
        "expected": case["expected"],
        "low_result": case["low_result_path"],
        "low_result_sha256": case["low_result_sha256"],
        "controlled_change": "gpt-5.6-luna reasoning low to high only",
        "before_manifest": before,
        "started_at": datetime.now(timezone.utc).isoformat(),
    })
    _, latency = run_turn(workspace, prompt, case_root / "turn-001")
    result = common_result(
        case_id=case_id, case_root=case_root, before=before, latency=latency,
    )
    result.update({
        "kind": "trace-stage-luna-high-solver-result-v1",
        "source_submission": case["source_submission"],
        "expected_behavior": case["expected"],
        "issue_delivered": case["issue"],
        "prompt_sha256": sha256_text(prompt),
        "low_result": case["low_result_path"],
        "answer_sha256": sha256_file(workspace / "answer.txt"),
        "trace_sha256": sha256_file(workspace / "trace.md"),
    })
    write_json_atomic(result_path, result)
    return result


def main() -> None:
    args = arguments()
    configure()
    manifest = read(MANIFEST)
    cases = manifest[args.stage]
    if args.case:
        cases = [case for case in cases if case["case_id"] == args.case]
        if not cases:
            raise ValueError(f"unknown frozen {args.stage} case: {args.case}")
    runner = run_attack if args.stage == "attack" else run_solver
    rows = []
    # Intentionally sequential: the 24-GiB Mac can safely run one da-11-1
    # analysis at a time, and seven bounded calls do not justify RAM pressure.
    for case in cases:
        result = runner(case)
        row = {
            "case_id": result["case_id"],
            "status": "completed",
            "latency_seconds": result["latency_seconds"],
            "cost_usd": result.get("cost_usd"),
            "estimated_cost_usd": result.get("estimated_cost_usd"),
            "command_count": len(result["new_commands"]),
        }
        rows.append(row)
        print(json.dumps(row, sort_keys=True), flush=True)
    write_json_atomic(RUN / f"{args.stage}-high/receipt.json", {
        "kind": f"trace-stage-luna-high-{args.stage}-receipt-v1",
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "model": "gpt-5.6-luna",
        "reasoning_effort": "high",
        "concurrency": 1,
        "case_count": len(rows),
        "cases": rows,
        "no_luna_low_calls": True,
        "no_sol_or_opus_calls": True,
    })


if __name__ == "__main__":
    main()
