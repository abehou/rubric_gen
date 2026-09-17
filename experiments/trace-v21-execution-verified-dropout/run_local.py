"""Run the frozen 54-assignment execution-verified/dropout Dev3 on this Mac."""

from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime, timezone
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import socket
import subprocess
import threading
import time
import uuid

from dotenv import dotenv_values

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.capacity import policy
from rubric_gen.submission_revision.execution_scope import terminal_records
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.study import (
    StudyRunConfig,
    StudyRunner,
    _exclusive_study_lease,
)
from rubric_gen.submission_revision.study_validation import validate_completed_revision
from rubric_gen.submission_revision.task_paraphrase_required import (
    INTERNAL_STAGE_FANOUT,
)


BUNDLE = Path(__file__).resolve().parent
ROOT = BUNDLE.parents[1]
CONFIG = BUNDLE / "dev3.yaml"
RUN_ROOT = ROOT / "runs/trace-v21-execution-verified-dropout-local-mac"
BEHAVIOR_ROOT = RUN_ROOT / "saved-case-behavior/cases"
VERSION = "attack_defense_v2.1_execution_verified"
TASKS = ("da-3-4", "da-11-1", "da-18-1")
RATES = (0.0, 0.3, 0.5)
ARMS = ("full", "user_simulator")
PANEL = ("gpt-5.6-sol", "claude-opus-5")


def _arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-concurrency", type=int, default=18)
    parser.add_argument("--aggregate-concurrency", type=int, default=18)
    parser.add_argument(
        "--dropout-zero-only",
        action="store_true",
        help="Resume only the matched repaired-v2.1 0%% dropout control.",
    )
    return parser.parse_args()


def _load_proposer_credential() -> str:
    if os.environ.get("OPENAI_API_KEY"):
        return "inherited environment"
    path = ROOT / ".env.local"
    value = dotenv_values(path).get("OPENAI_API_KEY") if path.is_file() else None
    if not value:
        raise RuntimeError(
            "the canonical v2.1 structured reviewer requires OPENAI_API_KEY"
        )
    os.environ["OPENAI_API_KEY"] = str(value)
    return str(path.resolve())


def _tree_manifest(root: Path) -> dict[str, object]:
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"input root is not a regular directory: {root}")
    digest = hashlib.sha256()
    rows = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        if path.is_symlink():
            raise RuntimeError(f"input file is a symlink: {path}")
        relative = path.relative_to(root).as_posix()
        file_sha256 = sha256_file(path)
        size = path.stat().st_size
        rows.append({"path": relative, "bytes": size, "sha256": file_sha256})
        digest.update(relative.encode())
        digest.update(b"\0")
        digest.update(file_sha256.encode())
        digest.update(b"\0")
    return {
        "root": str(root.resolve()),
        "files": len(rows),
        "bytes": sum(int(row["bytes"]) for row in rows),
        "tree_sha256": digest.hexdigest(),
        "manifest": rows,
    }


def _hardware() -> dict[str, object]:
    def command(*args: str) -> str | None:
        try:
            return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT).strip()
        except (OSError, subprocess.CalledProcessError):
            return None

    return {
        "platform": platform.platform(),
        "machine": platform.machine(),
        "hostname": socket.gethostname(),
        "hw_memsize": command("sysctl", "-n", "hw.memsize"),
        "hw_ncpu": command("sysctl", "-n", "hw.ncpu"),
        "hw_physicalcpu": command("sysctl", "-n", "hw.physicalcpu"),
        "vm_stat": command("vm_stat"),
        "memory_pressure": command("memory_pressure"),
    }


def _git_source(
    owner: Path, *, bundle: Path = BUNDLE, config: Path = CONFIG,
) -> dict[str, object]:
    commit = subprocess.check_output(
        ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True,
    ).strip()
    status = subprocess.check_output(
        ["git", "status", "--porcelain=v1", "-z"], cwd=ROOT,
    )
    diff = subprocess.check_output(
        ["git", "diff", "--binary", "--no-ext-diff", "HEAD"], cwd=ROOT,
    )
    (owner / "source.patch").write_bytes(diff)
    source_files = sorted({
        *ROOT.joinpath("src/rubric_gen").rglob("*.py"),
        *bundle.glob("*.py"),
        config,
        ROOT / "pyproject.toml",
        ROOT / "uv.lock",
    })
    manifest = [
        {"path": path.relative_to(ROOT).as_posix(), "sha256": sha256_file(path)}
        for path in source_files if path.is_file() and not path.is_symlink()
    ]
    return {
        "commit": commit,
        "dirty": bool(status),
        "status_porcelain_sha256": hashlib.sha256(status).hexdigest(),
        "tracked_diff_sha256": hashlib.sha256(diff).hexdigest(),
        "source_patch": str((owner / "source.patch").resolve()),
        "source_patch_sha256": sha256_file(owner / "source.patch"),
        "source_manifest": manifest,
        "source_manifest_sha256": hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest(),
    }


def _validate_experiment():
    experiment = load_experiment(CONFIG)
    expected = {
        (task, replicate, arm, rate)
        for task in TASKS
        for replicate in range(1, 4)
        for arm in ARMS
        for rate in RATES
    }
    actual = set()
    for assignment in experiment.execution_assignments:
        condition = experiment.condition(assignment.condition_id)
        actual.add((
            assignment.task_id,
            assignment.replicate,
            str(condition["feedback_policy"]),
            float(condition["rubric_dropout_rate"]),
        ))
    if actual != expected or len(experiment.execution_assignments) != 54:
        raise RuntimeError("canonical repaired/dropout Dev3 scope is not exactly 54 assignments")
    if experiment.protocol.get("red_team_trace_version") != VERSION:
        raise RuntimeError("scientific RTT identity changed")
    if experiment.payload["randomization"] != {"seed": 20260806, "replicates": 3}:
        raise RuntimeError("seed or replicate count changed")
    if (experiment.protocol["min_revisions"], experiment.protocol["max_revisions"]) != (5, 10):
        raise RuntimeError("revision stopping bounds changed")
    if tuple(experiment.payload["execution_audit_models"]) != PANEL:
        raise RuntimeError("Sol+Opus audit panel changed")
    if (experiment.seed_agent_config().model != "gpt-5.6-luna"
            or experiment.red_team_agent_config().model != "gpt-5.6-luna"
            or any(experiment.solver_config(item.solver_id).model != "gpt-5.6-luna"
                   for item in experiment.execution_assignments)):
        raise RuntimeError("scientific model route changed")
    output = Path(experiment.dag["revise"]["output_dir"])
    if not output.is_relative_to(RUN_ROOT / "dev3"):
        raise RuntimeError("revision output escaped the dedicated local Dev3 root")
    return experiment


def _validate_saved_cases() -> dict[str, object]:
    paths = {
        "user_rep_001": BEHAVIOR_ROOT / "user-da-11-1-rep-001/result.json",
        "user_rep_002": BEHAVIOR_ROOT / "user-da-11-1-rep-002/result.json",
        "user_rep_003": BEHAVIOR_ROOT / "user-da-11-1-rep-003/followup-3-result.json",
        "full_rep_001": BEHAVIOR_ROOT / "full-da-11-1-rep-001/result.json",
    }
    for path in paths.values():
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"required saved-case result is missing: {path}")
    workspaces = {name: path.parent / "workspace" for name, path in paths.items()}
    rep1_answer = (workspaces["user_rep_001"] / "answer.txt").read_text()
    rep2_answer = (workspaces["user_rep_002"] / "answer.txt").read_text()
    rep3_answer = (workspaces["user_rep_003"] / "answer.txt").read_text()
    rep3_trace = (workspaces["user_rep_003"] / "trace.md").read_text()
    full_answer = (workspaces["full_rep_001"] / "answer.txt").read_text()
    required = {
        "user_rep_001": all(text in rep1_answer for text in (
            "completed successfully", "72,162", "26 directional rows", "0.011899",
            "No other tested edge passed p<0.05",
        )),
        "user_rep_002": all(text in rep2_answer for text in (
            "retained 0 cells", "10 FDR-significant", "TNFSF10-TNFRSF10B",
            "corrected analysis has not been freshly rerun",
        )) and "67,184" not in rep2_answer and "12/12" not in rep2_answer,
        "user_rep_003": all(text in rep3_answer + rep3_trace for text in (
            "18,540", "4,000", "one connected-component",
        )) and not any(text in rep3_trace for text in (
            "3,958", "12,000", "networkx", "greedy_modularity",
        )),
        "full_rep_001": all(text in full_answer for text in (
            "has not been executed", "no statistical significance is claimed",
            "present ranking is descriptive",
        )),
    }
    if not all(required.values()):
        raise RuntimeError(f"saved-case behavior checks are not all satisfied: {required}")
    records = {
        name: {
            "path": str(path.resolve()),
            "sha256": sha256_file(path),
            "estimated_cost_usd": json.loads(path.read_text()).get("estimated_cost_usd"),
        }
        for name, path in paths.items()
    }
    return {"ready": True, "checks": required, "records": records}


def _input_manifest(
    experiment, *, config: Path = CONFIG,
) -> dict[str, object]:
    source = experiment.pretreatment_source
    if source is None:
        raise RuntimeError("compatible generation-1 source is absent")
    source_root = Path(source["study_dir"]) / "pretreatment-rubrics"
    roots = {
        "seeds": Path(experiment.dag["seed"]["output_dir"]),
        "paraphrases": Path(experiment.dag["paraphrase"]["output_dir"]),
        "generation_1_source": source_root,
        **{f"task_{task}": experiment.task_dir(task) for task in TASKS},
    }
    return {
        "config": {"path": str(config), "sha256": sha256_file(config)},
        "pretreatment_experiment": {
            "path": source["experiment"],
            "experiment_id": source["experiment_id"],
            "sha256": sha256_file(Path(source["experiment"])),
        },
        "roots": {name: _tree_manifest(root) for name, root in roots.items()},
    }


def _recover_missing_credential_failures(
    study: Path, invocation: str,
) -> dict[str, object]:
    """Rearm only saved zero-response failures caused by the omitted API key."""

    if not study.is_dir():
        return {"recovered_assignments": 0, "requests": []}
    expected_error = "OPENAI_API_KEY must be set for the attack_defense_v2.1_execution_verified"
    rows: list[dict[str, object]] = []
    with _exclusive_study_lease(study):
        ledger_path = study / "study.json"
        ledger = json.loads(ledger_path.read_text())
        for record in ledger["records"]:
            if (record.get("status") != "failed"
                    or not record.get("automatic_recovery_exhausted")
                    or record.get("error_type") != "RubricProposerProviderError"):
                continue
            experiment_dir = study / record["experiment_dir"]
            request_root = experiment_dir / "trace-defense-v2-requests"
            candidates = []
            for directory in sorted(request_root.glob("*")):
                if not directory.is_dir() or directory.is_symlink() or (directory / "result.json").exists():
                    continue
                attempts = sorted(directory.glob("attempt-*.json"))
                if not attempts:
                    continue
                values = [json.loads(path.read_text()) for path in attempts]
                if not all(
                    value.get("status") == "provider_failure"
                    and value.get("error_type") == "RuntimeError"
                    and value.get("error") == expected_error
                    and "output" not in value
                    for value in values
                ):
                    candidates = []
                    break
                candidates.append((directory, attempts, values))
            if not candidates:
                continue
            archive = (
                study / "execution-attempts" / record["assignment_id"]
                / f"missing-credential-{invocation}"
            )
            archive.mkdir(parents=True, exist_ok=False)
            request_rows = []
            for directory, attempts, values in candidates:
                target = archive / directory.name
                directory.rename(target)
                request_rows.append({
                    "request_key": directory.name,
                    "original_request_dir": str(directory),
                    "archive": str(target),
                    "attempts": [
                        {"path": path.name, "sha256": sha256_file(target / path.name)}
                        for path in attempts
                    ],
                    "attempt_count": len(values),
                    "provider_responses": 0,
                })
            record.update({
                "automatic_recovery_exhausted": False,
                "automatic_attempt_count": 0,
                "next_automatic_action": "explicit resume after archived missing-credential attempts",
                "missing_credential_recovery_archive": str(archive),
            })
            rows.append({
                "assignment_id": record["assignment_id"],
                "requests": request_rows,
            })
        if rows:
            write_json_atomic(ledger_path, ledger)
    return {
        "kind": "execution-verified-missing-credential-recovery-v1",
        "invocation": invocation,
        "recovered_assignments": len(rows),
        "provider_responses_preserved": 0,
        "requests": rows,
        "time": datetime.now(timezone.utc).isoformat(),
    }


def _recover_local_module_path_failures(
    study: Path, invocation: str,
) -> dict[str, object]:
    """Rearm response-free app-server starts after fixing the local PYTHONPATH."""

    if not study.is_dir():
        return {"recovered_assignments": 0, "assignment_ids": []}
    marker = (
        "Error while finding module specification for "
        "'rubric_gen.runtime.agents.codex_app_server' "
        "(ModuleNotFoundError: No module named 'rubric_gen')"
    )
    recovered: list[str] = []
    with _exclusive_study_lease(study):
        ledger_path = study / "study.json"
        ledger = json.loads(ledger_path.read_text())
        for record in ledger["records"]:
            if (record.get("status") != "failed"
                    or record.get("error_type") != "CodexProviderHealthError"
                    or marker not in str(record.get("error", ""))):
                continue
            record.update({
                "automatic_recovery_exhausted": False,
                "automatic_attempt_count": 0,
                "next_automatic_action": (
                    "explicit resume with absolute local module search path"
                ),
                "local_module_path_recovery_invocation": invocation,
            })
            recovered.append(str(record["assignment_id"]))
        if recovered:
            write_json_atomic(ledger_path, ledger)
    return {
        "recovered_assignments": len(recovered),
        "assignment_ids": recovered,
        "time": datetime.now(timezone.utc).isoformat(),
    }


_NUMBERED_LINE = re.compile(r"^\[L\d{6}\] ", re.MULTILINE)


def _reconstruct_public_documents(evidence: dict[str, object]):
    from rubric_gen.submission_revision.trace_defense_evidence_v2 import PublicDocument

    documents = {}
    original_order = (
        "task", "selected_rubric", "development_rubric", "artifact",
        "execution_witness", "execution_delta", "prior_issue",
    )
    for source_id in original_order:
        if source_id not in evidence["public_sources"]:
            continue
        source = evidence["public_sources"][source_id]
        numbered = source["numbered_text"]
        text = _NUMBERED_LINE.sub("", numbered)
        documents[source_id] = PublicDocument(source_id, text)
        if documents[source_id].model_record() != source:
            raise RuntimeError(f"saved enforcement evidence changed for {source_id}")
    return documents


def _smoke_recovered_enforcement(
    experiment, recovery: dict[str, object], owner: Path,
) -> dict[str, object] | None:
    """Run one exact archived enforcement request through its canonical route."""

    if not recovery["requests"]:
        return None
    selected = None
    for row in recovery["requests"]:
        for request in row["requests"]:
            attempt_path = Path(request["archive"]) / "attempt-001.json"
            attempt = json.loads(attempt_path.read_text())
            evidence = json.loads(attempt["attempt_evidence"])
            if "prior_issue" not in evidence["public_sources"]:
                selected = (row, request, attempt, evidence)
                break
        if selected is not None:
            break
    if selected is None:
        raise RuntimeError("no initial enforcement request is available for reviewer smoke")
    row, request_row, attempt, evidence = selected
    from rubric_gen.submission_revision.evolution import RubricProposer
    from rubric_gen.submission_revision.evolution_serialization import canonical_sha256
    from rubric_gen.submission_revision.task_paraphrase_required_stage import TraceStagesV2
    from rubric_gen.submission_revision.task_required_enforced_schema import (
        EnforcementContract,
        enforcement_schema,
    )

    documents = _reconstruct_public_documents(evidence)
    native_ids = {
        source_id: evidence["source_manifest"][source_id]["native_id"]
        for source_id in documents
    }
    validator = EnforcementContract(
        "enforcement",
        enforcement_schema(documents, execution_verified=True),
        documents,
        native_ids,
        execution_verified=True,
        prior_issue=None,
    )
    proposer = RubricProposer(
        benchmark=experiment.benchmark,
        model=str(experiment.protocol["rubric_proposer_model"]),
        service_tier=experiment.seed_agent_config().service_tier,
        max_retries=int(experiment.protocol["rubric_proposer_max_retries"]),
        red_team_trace_version=VERSION,
    )
    request_root = Path(request_row["original_request_dir"]).parent
    stages = TraceStagesV2(proposer, request_root)
    reconstructed = stages.request("enforcement", evidence, validator)
    key = canonical_sha256(reconstructed)
    if key != request_row["request_key"] or key != attempt["request_sha256"]:
        raise RuntimeError("reconstructed enforcement smoke request identity changed")
    launch = {
        "kind": "execution-verified-enforcement-route-smoke-launch-v1",
        "assignment_id": row["assignment_id"],
        "request_key": key,
        "provider": proposer.proposer_contract.provider,
        "model": proposer.proposer_contract.model,
        "archived_zero_response_attempts": request_row["attempt_count"],
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json_atomic(owner / "enforcement-smoke-launch.json", launch)
    value = stages.call("enforcement", evidence, validator)
    if value is None:
        raise RuntimeError("canonical enforcement smoke exhausted its response contract")
    result_path = request_root / key / "result.json"
    result = json.loads(result_path.read_text())
    saved_attempts = [
        json.loads(path.read_text())
        for path in sorted(result_path.parent.glob("attempt-*.json"))
    ]
    successful = next(
        item for item in reversed(saved_attempts)
        if item.get("status") == "valid_result"
    )
    smoke = {
        **launch,
        "status": "passed",
        "decision": value["decision"],
        "prior_issue_status": value["prior_issue_status"],
        "result": str(result_path),
        "result_sha256": sha256_file(result_path),
        "attempt_count": result["attempt_count"],
        "cost": successful["output"]["cost"],
        "generation": successful["output"]["generation"],
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json_atomic(owner / "enforcement-smoke-result.json", smoke)
    return smoke


def _recovery_for_unfinished_smoke(
    current: dict[str, object], owners_root: Path,
) -> dict[str, object]:
    if current["recovered_assignments"]:
        return current
    if any(owners_root.glob("*/enforcement-smoke-result.json")):
        return current
    for path in sorted(
        owners_root.glob("*/missing-credential-recovery.json"), reverse=True,
    ):
        prior = json.loads(path.read_text())
        if prior.get("recovered_assignments"):
            return prior
    return current


def _status(
    study: Path,
    invocation: str,
    assignment_ids: tuple[str, ...] | None = None,
) -> dict[str, object]:
    records = []
    try:
        records = json.loads((study / "study.json").read_text())["records"]
    except (OSError, ValueError, KeyError, TypeError):
        pass
    selected = [
        record for record in records
        if assignment_ids is None or record["assignment_id"] in assignment_ids
    ]
    by_condition: dict[str, Counter] = {}
    for record in selected:
        by_condition.setdefault(record["condition_id"], Counter())[record["status"]] += 1
    return {
        "invocation": invocation,
        "experiment_id": "biomnibench-da-factorial-r10-2f8f9cee1a53",
        "expected": len(assignment_ids) if assignment_ids is not None else 54,
        "statuses": dict(Counter(row["status"] for row in selected)),
        "by_condition": {key: dict(value) for key, value in by_condition.items()},
        "time": datetime.now(timezone.utc).isoformat(),
    }


def main() -> None:
    args = _arguments()
    if not 1 <= args.max_concurrency <= 18:
        raise ValueError("local stage concurrency must be between 1 and 18")
    if not 1 <= args.aggregate_concurrency <= 18:
        raise ValueError("local aggregate provider concurrency must be between 1 and 18")
    if os.environ.get("SLURM_JOB_ID"):
        raise RuntimeError("local Dev3 must not run with a Slurm job identity")
    experiment = _validate_experiment()
    assignment_ids = None
    if args.dropout_zero_only:
        assignment_ids = tuple(
            item.assignment_id for item in experiment.execution_assignments
            if float(experiment.condition(item.condition_id)["rubric_dropout_rate"]) == 0.0
        )
        if len(assignment_ids) != 18:
            raise RuntimeError("matched repaired-v2.1 0% control must contain 18 assignments")
    expected_assignments = len(assignment_ids) if assignment_ids is not None else 54
    proposer_credential_source = _load_proposer_credential()
    behavior = _validate_saved_cases()
    input_manifest = _input_manifest(experiment)

    RUN_ROOT.mkdir(parents=True, exist_ok=True)
    lock_fd = os.open(
        RUN_ROOT / ".dev3-run.lock", os.O_RDWR | os.O_CREAT | os.O_NOFOLLOW, 0o600,
    )
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as error:
        os.close(lock_fd)
        raise RuntimeError("another local execution-verified Dev3 owner is active") from error

    runtime_path = RUN_ROOT / "runtime/dev3-runtime.json"
    write_json_atomic(runtime_path, {
        "version": 1,
        "aggregate_concurrency": args.aggregate_concurrency,
        "audit_studies": 1,
        "coordination_dir": str((RUN_ROOT / "runtime/dev3-coordination").resolve()),
    })
    os.environ["RUBRIC_GEN_RUNTIME_CONFIG"] = str(runtime_path.resolve())
    invocation = (
        "execution-verified-dev3-"
        + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-")
        + uuid.uuid4().hex[:8]
    )
    os.environ["RUBRIC_GEN_INVOCATION_ID"] = invocation
    owner = RUN_ROOT / "dev3/owners" / invocation
    owner.mkdir(parents=True, exist_ok=False)
    source = _git_source(owner)
    study = Path(experiment.dag["revise"]["output_dir"])
    module_path_recovery = _recover_local_module_path_failures(study, invocation)
    write_json_atomic(owner / "local-module-path-recovery.json", module_path_recovery)
    recovery = _recover_missing_credential_failures(study, invocation)
    write_json_atomic(owner / "missing-credential-recovery.json", recovery)
    smoke_recovery = _recovery_for_unfinished_smoke(
        recovery, RUN_ROOT / "dev3/owners",
    )
    smoke = _smoke_recovered_enforcement(experiment, smoke_recovery, owner)
    write_json_atomic(RUN_ROOT / "dev3/saved-case-validation.json", {
        **behavior, "time": datetime.now(timezone.utc).isoformat(), "source": source,
    })
    write_json_atomic(RUN_ROOT / "dev3/input-manifest.json", input_manifest)
    launch = {
        "kind": "execution-verified-dropout-local-dev3-launch-v1",
        "invocation": invocation,
        "pid": os.getpid(),
        "uid": os.getuid(),
        "host": socket.gethostname(),
        "source": source,
        "hardware": _hardware(),
        "runtime": policy(),
        "runtime_config": {"path": str(runtime_path), "sha256": sha256_file(runtime_path)},
        "experiment": str(CONFIG),
        "experiment_id": experiment.experiment_id,
        "config_sha256": sha256_file(CONFIG),
        "study": str(study),
        "stage_max_concurrency": args.max_concurrency,
        "aggregate_provider_concurrency": args.aggregate_concurrency,
        "internal_stage_fanout": INTERNAL_STAGE_FANOUT,
        "audit_studies": 1,
        "expected_assignments": expected_assignments,
        "execution_assignment_ids": list(assignment_ids) if assignment_ids else None,
        "tasks": list(TASKS),
        "rates": list(RATES),
        "arms": list(ARMS),
        "seed": 20260806,
        "resume": study.exists(),
        "rubric_proposer_provider": "openai",
        "rubric_proposer_credential_source": proposer_credential_source,
        "missing_credential_recovery": {
            "recovered_assignments": recovery["recovered_assignments"],
            "receipt": str((owner / "missing-credential-recovery.json").resolve()),
            "receipt_sha256": sha256_file(owner / "missing-credential-recovery.json"),
        },
        "local_module_path_recovery": {
            "recovered_assignments": module_path_recovery["recovered_assignments"],
            "receipt": str((owner / "local-module-path-recovery.json").resolve()),
            "receipt_sha256": sha256_file(owner / "local-module-path-recovery.json"),
        },
        "enforcement_route_smoke": (
            None if smoke is None else {
                "status": smoke["status"],
                "request_key": smoke["request_key"],
                "result_sha256": smoke["result_sha256"],
                "receipt": str((owner / "enforcement-smoke-result.json").resolve()),
                "receipt_sha256": sha256_file(owner / "enforcement-smoke-result.json"),
            }
        ),
        "saved_case_validation_sha256": sha256_file(
            RUN_ROOT / "dev3/saved-case-validation.json"
        ),
        "input_manifest_sha256": sha256_file(RUN_ROOT / "dev3/input-manifest.json"),
        "slurm_job_id": None,
        "started_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json_atomic(owner / "launch.json", launch)
    write_json_atomic(RUN_ROOT / "dev3/latest-launch.json", launch)

    runner = StudyRunner(StudyRunConfig(
        experiment=experiment,
        seed_run_dir=Path(experiment.dag["seed"]["output_dir"]),
        paraphrase_run_dir=Path(experiment.dag["paraphrase"]["output_dir"]),
        output_dir=study,
        max_concurrency=args.max_concurrency,
        resume=study.exists(),
        assignment_ids=assignment_ids,
    ))
    stop = threading.Event()

    def monitor() -> None:
        while not stop.is_set():
            write_json_atomic(
                RUN_ROOT / "dev3/status.json",
                _status(study, invocation, assignment_ids),
            )
            stop.wait(30)

    monitor_thread = threading.Thread(target=monitor, daemon=True)
    monitor_thread.start()
    started = time.monotonic()
    try:
        exit_code = runner.run()
    finally:
        stop.set()
        monitor_thread.join(5)
        write_json_atomic(
            RUN_ROOT / "dev3/status.json",
            _status(study, invocation, assignment_ids),
        )
    write_json_atomic(owner / "revision-exit.json", {
        "exit_code": exit_code,
        "wall_seconds": time.monotonic() - started,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    })
    if exit_code:
        raise RuntimeError("Dev3 has incomplete assignments; successful outputs are retained")

    ledger = json.loads((study / "study.json").read_text())
    completed = terminal_records(experiment, ledger)
    if (len(completed) != expected_assignments
            or any(row["status"] != "completed" for row in completed)):
        raise RuntimeError(
            f"Dev3 completion scope is not {expected_assignments} successful assignments"
        )
    assignments = {item.assignment_id: item for item in experiment.assignments}
    rows = []
    for record in completed:
        path = study / record["experiment_dir"]
        validate_completed_revision(
            path, assignments[record["assignment_id"]], experiment,
            runner.seed_root, runner.paraphrase_root,
        )
        rows.append({"assignment_id": record["assignment_id"], "root": str(path)})
    completion = {
        "kind": "execution-verified-dropout-local-dev3-completion-v1",
        "invocation": invocation,
        "experiment_id": experiment.experiment_id,
        "expected": expected_assignments,
        "completed": len(rows),
        "assignments": rows,
        "source": source,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    write_json_atomic(owner / "completion.json", completion)
    write_json_atomic(RUN_ROOT / "dev3/completion.json", completion)
    print(json.dumps({
        "stage": "execution_verified_dropout_dev3_complete",
        "completed": len(rows),
        "experiment_id": experiment.experiment_id,
    }), flush=True)


if __name__ == "__main__":
    main()
