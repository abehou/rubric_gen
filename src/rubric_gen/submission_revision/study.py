"""Execute a randomized submission-revision study."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import socket
import stat
import sys
import threading
import time
import traceback
from concurrent.futures import ThreadPoolExecutor, as_completed, wait, FIRST_COMPLETED
from contextlib import contextmanager
from dataclasses import dataclass, replace
from openai import APIConnectionError, APIStatusError
from rubric_gen.submission_revision import pretreatment_reuse
from datetime import datetime
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.runtime.agents.codex_sessions import CodexProviderHealthError
from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.runtime.failures import failure_category, retry_after
from rubric_gen.runtime.capacity import emit
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.controller import run_submission_revision
from rubric_gen.submission_revision.contrasts import ELICITATION_SEED_REPLICATES
from rubric_gen.submission_revision.experiment import Experiment
from rubric_gen.submission_revision.feedback import FeedbackPolicy
from rubric_gen.submission_revision.evolution import RubricProposer
from rubric_gen.submission_revision.evolution_provider import RubricProposerProviderError
from rubric_gen.submission_revision.models import SubmissionRevisionConfig
from rubric_gen.submission_revision.pretreatment_rubrics import (
    ensure_pretreatment_rubric,
    shared_pretreatment_rubric_dir,
)
from rubric_gen.submission_revision import paraphrase_validation
from rubric_gen.submission_revision.prompts import PromptProfile
from rubric_gen.submission_revision.rubric_generation import (
    CompleteRubric,
    RubricPolicy,
)
from rubric_gen.benchmarks import get_submission_benchmark
from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.submission_revision import study_layout, study_validation
from rubric_gen.submission_revision.assignments import ExperimentAssignment


STUDY_RUN_KIND = "rubric-gen-randomized-revision-study"
_STUDY_LEASE_NAME = ".study.lock"
_PROVIDER_HEALTH_FAILURE_LIMIT = 3
_PROVIDER_CIRCUIT_COOLDOWN_SECONDS = 30
_ASSIGNMENT_TRANSIENT_ATTEMPTS = 3


def _permanent_provider_failure(error: BaseException) -> bool:
    seen = set()
    while error is not None and id(error) not in seen:
        seen.add(id(error))
        if (getattr(error, "status_code", None) in {400, 401, 403, 404, 422}
                or getattr(error, "code", None) in {"insufficient_quota", "invalid_api_key"}):
            return True
        error = error.__cause__
    return False


def _retryable_assignment_failure(error: BaseException) -> bool:
    if _permanent_provider_failure(error):
        return False
    # These errors have already exhausted their operation owner's configured
    # budget. Re-running the assignment would multiply that budget.
    if isinstance(error, (CodexProviderHealthError, RubricProposerProviderError)):
        return False
    return isinstance(error, APIConnectionError) or (
        isinstance(error, APIStatusError) and error.status_code in {408, 409, 429, 500, 502, 503, 504, 529}
    )


class _ProviderCircuitOpen(RuntimeError):
    pass


class _ProviderCircuit:
    def __init__(self, provider: str) -> None:
        self.provider = provider
        self._failures = 0
        self._reason: str | None = None
        self._reopen_at: float | None = None
        self._permanent = False
        self._lock = threading.Lock()

    def check(self) -> None:
        with self._lock:
            if self._reopen_at is not None and time.monotonic() >= self._reopen_at:
                self._reason = None
                self._failures = 0
                self._reopen_at = None
            if self._reason is not None:
                raise _ProviderCircuitOpen(
                    f"{self.provider} provider circuit is open after "
                    f"{self._failures} transport failures: {self._reason}"
                )

    def wait(self) -> None:
        while True:
            try:
                self.check()
                return
            except _ProviderCircuitOpen:
                if self._permanent:
                    raise
                time.sleep(1)

    def record_success(self) -> None:
        with self._lock:
            if not self._permanent:
                self._failures = 0
                self._reason = None
                self._reopen_at = None

    def record_failure(self, error: BaseException) -> None:
        if (isinstance(error, CodexProviderHealthError)
                and str(error).startswith("Codex app-server start failed after ")):
            return  # Local process startup is not evidence of a provider outage.
        permanent = _permanent_provider_failure(error)
        if not permanent and not (_retryable_assignment_failure(error) or isinstance(error, (CodexProviderHealthError, RubricProposerProviderError))):
            return
        with self._lock:
            if self._permanent:
                return
            self._failures += 1
            if permanent or self._failures >= _PROVIDER_HEALTH_FAILURE_LIMIT:
                self._reason = str(error)
                self._permanent = permanent
                self._reopen_at = None if permanent else time.monotonic() + _PROVIDER_CIRCUIT_COOLDOWN_SECONDS


@dataclass(frozen=True)
class StudyRunConfig:
    experiment: Experiment
    seed_run_dir: Path
    paraphrase_run_dir: Path
    output_dir: Path
    max_concurrency: int
    resume: bool = False
    assignment_ids: tuple[str, ...] | None = None

    def __post_init__(self) -> None:
        if type(self.max_concurrency) is not int or self.max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")
        if self.assignment_ids is not None:
            allowed = {a.assignment_id for a in self.experiment.execution_assignments}
            if (type(self.assignment_ids) is not tuple or not self.assignment_ids
                or len(set(self.assignment_ids)) != len(self.assignment_ids)
                or any(i not in allowed for i in self.assignment_ids)):
                raise ValueError("invocation assignment scope must select unique declared execution assignments")


class _ProgressPositions:
    def __init__(self, count: int) -> None:
        self._available = list(range(1, count + 1))
        self._lock = threading.Lock()

    def acquire(self) -> int:
        with self._lock:
            return self._available.pop(0)

    def release(self, position: int) -> None:
        with self._lock:
            self._available.append(position)
            self._available.sort()


class StudyRunner:
    def __init__(self, config: StudyRunConfig) -> None:
        self.config = config
        self.experiment = config.experiment
        self.root = config.output_dir.resolve()
        self.seed_root = config.seed_run_dir.resolve()
        self.paraphrase_root = config.paraphrase_run_dir.resolve()
        self.pretreatment_root = self.root / "pretreatment-rubrics"
        self.pretreatment_source_root = pretreatment_reuse.source_pool(self.experiment)
        self._manifest_lock = threading.Lock()
        providers = {
            self.experiment.solver_config(assignment.solver_id).provider
            for assignment in self.experiment.assignments
        }
        self._provider_circuits = {
            provider: _ProviderCircuit(provider) for provider in providers
        }

    @property
    def invocation_assignments(self):
        selected = self.config.assignment_ids
        return tuple(a for a in self.experiment.execution_assignments
                     if selected is None or a.assignment_id in selected)

    def run(self) -> int:
        assignments = sorted(
            self.experiment.assignments,
            key=lambda item: item.execution_order,
        )
        paraphrase_validation.validate_paraphrase_run(
            self.paraphrase_root,
            self.experiment,
        )
        existed = os.path.lexists(self.root)
        if existed and not self.config.resume:
            raise FileExistsError(f"study output already exists: {self.root}")
        if existed and (self.root.is_symlink() or not self.root.is_dir()):
            raise RuntimeError(f"study output is not a regular directory: {self.root}")
        if not existed:
            self.root.mkdir(parents=True)
        with _exclusive_study_lease(self.root):
            return self._run_locked(assignments, existed)

    def _run_locked(
        self,
        assignments: list[ExperimentAssignment],
        existed: bool,
    ) -> int:
        manifest = self._start_manifest(assignments, existed)
        pending = self._pending_assignments(manifest, assignments)
        if pending:
            manifest['runtime_phase'] = 'pretreatment'
            manifest['assignment_worker_limit_source'] = 'explicit invocation/profile setting'
            self._write_manifest(manifest)
            self._prepare_pretreatment_rubrics(pending)
        manifest['runtime_phase'] = 'revision'

        self._mark_study_running(manifest)
        if not pending:
            return self._finish_study(manifest)

        positions = _ProgressPositions(self.config.max_concurrency)
        with TerminalProgress(
            total=len(self.invocation_assignments),
            description="randomized study",
            unit="assignment",
            position=0,
        ) as progress:
            for _ in range(len(self.invocation_assignments) - len(pending)):
                progress.update()
            with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as pool:
                waiting = iter(pending)
                active = {}
                def refill():
                    while len(active) < self.config.max_concurrency:
                        assignment = next(waiting, None)
                        if assignment is None:
                            break
                        active[pool.submit(self._execute_assignment, assignment, positions)] = assignment.assignment_id
                refill()
                while active:
                    done, _ = wait(active, return_when=FIRST_COMPLETED)
                    for future in done:
                        active.pop(future)
                        future.result()
                        progress.update()
                    refill()
        return self._finish_study(self._load_manifest())

    def _start_manifest(
        self,
        assignments: list[ExperimentAssignment],
        existed: bool,
    ) -> dict[str, object]:
        if not existed:
            manifest = self._new_manifest(assignments)
            self._write_manifest(manifest)
            return manifest
        manifest = self._load_manifest()
        self._validate_manifest_identity(manifest, assignments)
        completed = [r for r in manifest['records'] if r.get('status') == 'completed'
                     and (self.experiment.execution_conditions is None or r['condition_id'] in self.experiment.execution_conditions)]
        if completed:
            from .source_resolution import resolve_study_sources
            # The full ledger remains authoritative even for a partial resume.
            resolve_study_sources(self.root, self.experiment, require_terminal=False)
        _reclaim_interrupted_records(manifest)
        return manifest

    def _pending_assignments(
        self,
        manifest: dict[str, object],
        assignments: list[ExperimentAssignment],
    ) -> list[ExperimentAssignment]:
        return [
            assignment
            for assignment in assignments
            if (self.experiment.execution_conditions is None
                or assignment.condition_id in self.experiment.execution_conditions)
            if self.config.assignment_ids is None or assignment.assignment_id in self.config.assignment_ids
            if _record_for(manifest, assignment.assignment_id).get("status")
            not in {"completed", "invalid"}
        ]

    def _mark_study_running(self, manifest: dict[str, object]) -> None:
        manifest["status"] = "running"
        manifest["finished_at"] = None
        manifest["max_concurrency_last_invocation"] = self.config.max_concurrency
        if self.experiment.execution_conditions is not None:
            manifest["execution_conditions"] = list(self.experiment.execution_conditions)
        else:
            manifest.pop("execution_conditions", None)
        if self.config.assignment_ids is not None:
            manifest["execution_assignment_ids"] = list(self.config.assignment_ids)
        else:
            manifest.pop("execution_assignment_ids", None)
        self._write_manifest(manifest)

    def _finish_study(self, manifest: dict[str, object]) -> int:
        scope = self.experiment.execution_conditions
        selected = [r for r in _records(manifest) if scope is None or r["condition_id"] in scope]
        if self.config.assignment_ids is not None:
            selected = [r for r in selected if r["assignment_id"] in self.config.assignment_ids]
        statuses = {str(record["status"]) for record in selected}
        successful = statuses == {"completed"}
        manifest["status"] = ("completed" if successful else "failed") + ("_scope" if scope or self.config.assignment_ids else "")
        manifest["finished_at"] = _now()
        manifest["runtime_phase"] = "complete" if successful else "incomplete"
        self._write_manifest(manifest)
        _report_noncompleted_records({"records": selected})
        return int(not successful)

    def _execute_assignment(
        self,
        assignment: ExperimentAssignment,
        positions: _ProgressPositions,
    ) -> None:
        position = positions.acquire()
        assignment_id = assignment.assignment_id
        provider = self.experiment.solver_config(assignment.solver_id).provider
        circuit = self._provider_circuits[provider]
        try:
            for attempt in range(_ASSIGNMENT_TRANSIENT_ATTEMPTS):
                try:
                    circuit.wait()
                    saved = _record_for(self._load_manifest(), assignment_id)
                    if saved.get('automatic_recovery_exhausted'):
                        return
                    self._mark_assignment_running(assignment_id)
                    experiment_dir = self._experiment_dir(assignment)
                    revision = self._revision_config(
                        assignment,
                        resume=os.path.lexists(experiment_dir),
                    )
                    run_submission_revision(
                        replace(revision, progress_position=position),
                        judgment_reuse_root=self.root / "shared-judgments",
                    )
                    study_validation.validate_completed_revision(
                        experiment_dir, assignment, self.experiment,
                        self.seed_root, self.paraphrase_root,
                    )
                    self._mark_assignment_completed(assignment_id)
                    circuit.record_success()
                    break
                except (Exception, SystemExit) as exc:
                    circuit.record_failure(exc)
                    self._mark_assignment_failed(assignment_id, exc)
                    if not _retryable_assignment_failure(exc) or attempt + 1 == _ASSIGNMENT_TRANSIENT_ATTEMPTS:
                        break
                    delay = retry_after(exc, attempt + 1)
                    emit('retry_wait', operation='assignment', assignment_id=assignment_id,
                         category=failure_category(exc), wait_seconds=delay)
                    time.sleep(delay)
        finally:
            positions.release(position)

    def _mark_assignment_running(self, assignment_id: str) -> None:
        with self._manifest_lock:
            manifest = self._load_manifest()
            record = _record_for(manifest, assignment_id)
            if record.get("status") == "failed":
                self._archive_assignment_failure(record)
            record.update(
                {
                    "status": "running",
                    "started_at": _now(),
                    "finished_at": None,
                    "hostname": socket.gethostname(),
                    "pid": os.getpid(),
                    "attempt_count": int(record.get("attempt_count", 0)) + 1,
                    "automatic_attempt_count": int(record.get("automatic_attempt_count", 0)) + 1,
                }
            )
            for key in ("error_type", "error", "traceback"):
                record.pop(key, None)
            self._write_manifest(manifest)

    def _mark_assignment_completed(self, assignment_id: str) -> None:
        with self._manifest_lock:
            manifest = self._load_manifest()
            _record_for(manifest, assignment_id).update(
                {"status": "completed", "finished_at": _now()}
            )
            self._write_manifest(manifest)
        emit('assignment_completed', assignment_id=assignment_id)

    def _mark_assignment_failed(
        self,
        assignment_id: str,
        error: BaseException,
    ) -> None:
        with self._manifest_lock:
            manifest = self._load_manifest()
            record = _record_for(manifest, assignment_id)
            exhausted = (isinstance(error, (CodexProviderHealthError, RubricProposerProviderError))
                         or (_retryable_assignment_failure(error) and
                             int(record.get('automatic_attempt_count', 0)) >= _ASSIGNMENT_TRANSIENT_ATTEMPTS))
            record.update(
                {
                    "status": "failed",
                    "finished_at": _now(),
                    "error_type": type(error).__name__,
                    "error": str(error),
                    "traceback": traceback.format_exc(),
                    "failure_category": failure_category(error),
                    "automatic_recovery_exhausted": exhausted,
                    "next_automatic_action": 'none: operation budget exhausted' if exhausted else 'bounded retry if transient; otherwise repair source/config',
                }
            )
            self._archive_assignment_failure(record)
            self._write_manifest(manifest)

    def _archive_assignment_failure(self, record: dict[str, object]) -> None:
        raw = json.dumps(record, sort_keys=True).encode()
        digest = hashlib.sha256(raw).hexdigest()[:16]
        root = self.root / "execution-attempts" / str(record["assignment_id"])
        if root.is_symlink() or root.parent.is_symlink():
            raise RuntimeError("assignment failure archive is a symlink")
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"attempt-{int(record.get('attempt_count', 0)):03d}-{digest}.json"
        if path.is_symlink():
            raise RuntimeError("saved assignment failure is a symlink")
        if path.exists():
            if read_json_object(path, "failed assignment attempt") != record:
                raise RuntimeError("saved assignment failure changed")
            return
        write_json_atomic(path, record)

    def _prepare_pretreatment_rubrics(
        self,
        assignments: list[ExperimentAssignment],
    ) -> None:
        """Compile one shared seed-learned rubric for each pending task."""

        task_ids = tuple(sorted({
            assignment.task_id for assignment in assignments
            if RubricPolicy(self.experiment.condition(assignment.condition_id)["rubric_policy"])
            is not RubricPolicy.FIXED
        }))
        if not task_ids:
            return
        worker_count = min(self.config.max_concurrency, len(task_ids))
        with ThreadPoolExecutor(max_workers=worker_count) as pool:
            futures = [
                pool.submit(self._prepare_pretreatment_rubric, task_id)
                for task_id in task_ids
            ]
            for future in as_completed(futures):
                future.result()

    def _prepare_pretreatment_rubric(self, task_id: str) -> None:
        protocol = self.experiment.protocol
        selection = paraphrase_validation.resolve_paraphrase_selection(
            self.paraphrase_root,
            self.experiment,
            task_id,
        )
        rubric = CompleteRubric.from_content(
            selection.optimizer_path.read_text(encoding="utf-8")
        )
        development_rubric = CompleteRubric.from_content(
            selection.development_path.read_text(encoding="utf-8")
        )
        if rubric.content_sha256 != sha256_file(selection.optimizer_path):
            raise RuntimeError("selected rubric changed during pre-treatment setup")
        if (
            development_rubric.content_sha256
            != sha256_file(selection.development_path)
        ):
            raise RuntimeError(
                "development rubric changed during pre-treatment setup"
            )
        seed_agent = self.experiment.seed_agent_config(quiet=True)
        proposer = RubricProposer(
            benchmark=self.experiment.benchmark,
            model=str(protocol["rubric_proposer_model"]),
            service_tier=seed_agent.service_tier,
            max_retries=int(protocol["rubric_proposer_max_retries"]),
        )
        operation = ensure_pretreatment_rubric
        if self.pretreatment_source_root is not None:
            from rubric_gen.submission_revision.pretreatment_rubrics import validate_pretreatment_rubric
            source = shared_pretreatment_rubric_dir(
                self.pretreatment_source_root, task_id,
                rubric.content_sha256, development_rubric.content_sha256,
            )
            validate_pretreatment_rubric(
                root=source, experiment_id=pretreatment_reuse.scope_id(self.experiment),
                task_dir=self.experiment.task_dir(task_id),
                benchmark=get_submission_benchmark(self.experiment.benchmark),
                initial_rubric=rubric, development_rubric=development_rubric,
                seed_set=self.seed_root, seed_generator=seed_agent,
                prompt_profile=PromptProfile(str(protocol["prompt"])),
                seed_replicates=ELICITATION_SEED_REPLICATES, proposer=proposer,
            )
            destination = shared_pretreatment_rubric_dir(
                self.pretreatment_root, task_id,
                rubric.content_sha256, development_rubric.content_sha256,
            )
            pretreatment_reuse.copy_pool_entry(source, destination)
            operation = validate_pretreatment_rubric
        operation(
            root=shared_pretreatment_rubric_dir(
                self.pretreatment_root,
                task_id,
                rubric.content_sha256,
                development_rubric.content_sha256,
            ),
            experiment_id=pretreatment_reuse.scope_id(self.experiment),
            task_dir=self.experiment.task_dir(task_id),
            benchmark=get_submission_benchmark(self.experiment.benchmark),
            initial_rubric=rubric,
            development_rubric=development_rubric,
            seed_set=self.seed_root,
            seed_generator=seed_agent,
            prompt_profile=PromptProfile(str(protocol["prompt"])),
            seed_replicates=ELICITATION_SEED_REPLICATES,
            proposer=proposer,
        )

    def _revision_config(
        self,
        assignment: ExperimentAssignment,
        *,
        resume: bool,
    ) -> SubmissionRevisionConfig:
        protocol = self.experiment.protocol
        solver_id = assignment.solver_id
        condition = self.experiment.condition(assignment.condition_id)
        feedback_policy = FeedbackPolicy(str(condition["feedback_policy"]))
        selection = paraphrase_validation.resolve_paraphrase_selection(
            self.paraphrase_root,
            self.experiment,
            assignment.task_id,
        )
        max_review_chars = protocol["max_review_chars"]
        if max_review_chars is not None and type(max_review_chars) is not int:
            raise RuntimeError("experiment max_review_chars is invalid")
        return SubmissionRevisionConfig(
            task_dir=self.experiment.task_dir(assignment.task_id),
            experiment_dir=self._experiment_dir(assignment),
            max_revisions=int(protocol["max_revisions"]),
            min_revisions=int(protocol["min_revisions"]),
            seed_run_dir=self.seed_root,
            pretreatment_rubric_dir=shared_pretreatment_rubric_dir(
                self.pretreatment_root,
                assignment.task_id,
                sha256_file(selection.optimizer_path),
                sha256_file(selection.development_path),
            ),
            agent=self.experiment.solver_config(
                solver_id,
                quiet=True,
            ),
            seed_agent=self.experiment.seed_agent_config(quiet=True),
            red_team_agent=self.experiment.red_team_agent_config(quiet=True),
            solver_id=solver_id,
            experiment_id=self.experiment.experiment_id,
            assignment_id=assignment.assignment_id,
            condition_id=assignment.condition_id,
            replicate=assignment.replicate,
            elicitation_seed_replicates=ELICITATION_SEED_REPLICATES,
            execution_order=assignment.execution_order,
            optimizer_rubric_path=selection.optimizer_path,
            development_rubric_path=selection.development_path,
            master_rubric_name=str(protocol["rubric_name"]),
            benchmark=self.experiment.benchmark,
            rubric_proposer_max_retries=int(protocol["rubric_proposer_max_retries"]),
            feedback_policy=feedback_policy,
            feedback_simulator=self.experiment.feedback_simulator_config(
                feedback_policy,
            ),
            prompt_profile=PromptProfile(str(protocol["prompt"])),
            rubric_policy=RubricPolicy(str(condition["rubric_policy"])),
            red_team_trace_version=protocol.get("red_team_trace_version"),
            rubric_proposer_model=str(protocol["rubric_proposer_model"]),
            review=str(protocol["review"]),
            judge_model=str(protocol["judge_model"]),
            max_review_chars=max_review_chars,
            resume=resume,
            show_progress=True,
        )

    def _experiment_dir(self, assignment: ExperimentAssignment) -> Path:
        return self.root / study_layout.study_experiment_relative_path(assignment)

    def _new_manifest(
        self,
        assignments: list[ExperimentAssignment],
    ) -> dict[str, object]:
        return {
            "kind": STUDY_RUN_KIND,
            "status": "pending",
            "experiment_path": str(self.experiment.path),
            "experiment_id": self.experiment.experiment_id,
            "seed_run_dir": str(self.seed_root),
            "paraphrase_run_dir": str(self.paraphrase_root),
            "pretreatment_rubric_root": str(self.pretreatment_root),
            "started_at": _now(),
            "finished_at": None,
            "max_concurrency_last_invocation": self.config.max_concurrency,
            "records": [self._new_record(item) for item in assignments],
        }

    def _new_record(self, assignment: ExperimentAssignment) -> dict[str, object]:
        return {
            **assignment.record_identity(),
            "status": "pending",
            "attempt_count": 0,
            "started_at": None,
            "finished_at": None,
        }

    def _load_manifest(self) -> dict[str, object]:
        return read_json_object(self.root / "study.json", "study manifest")

    def _write_manifest(self, manifest: dict[str, object]) -> None:
        write_json_atomic(self.root / "study.json", manifest)

    def _validate_manifest_identity(
        self,
        manifest: dict[str, object],
        assignments: list[ExperimentAssignment],
    ) -> None:
        expected_identity = {
            "kind": STUDY_RUN_KIND,
            "experiment_path": str(self.experiment.path),
            "experiment_id": self.experiment.experiment_id,
            "seed_run_dir": str(self.seed_root),
            "paraphrase_run_dir": str(self.paraphrase_root),
            "pretreatment_rubric_root": str(self.pretreatment_root),
        }
        if any(manifest.get(key) != value for key, value in expected_identity.items()):
            raise RuntimeError("study resume identity differs from the experiment")
        records = _records(manifest)
        if [record.get("assignment_id") for record in records] != [
            item.assignment_id for item in assignments
        ]:
            raise RuntimeError("study assignment ledger differs from the experiment")
        for record, assignment in zip(records, assignments, strict=True):
            study_layout.resolve_study_experiment(self.root, record, assignment)


@contextmanager
def _exclusive_study_lease(root: Path):
    """Hold the one-writer lease for a study invocation."""

    lock_path = root / _STUDY_LEASE_NAME
    flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock_path, flags, 0o664)
    locked = False
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError(f"study lease is not a regular file: {lock_path}")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
            locked = True
        except BlockingIOError:
            os.lseek(descriptor, 0, os.SEEK_SET)
            owner = os.read(descriptor, 4096).decode("utf-8", errors="replace").strip()
            detail = f": {owner}" if owner else ""
            raise RuntimeError(f"study already has an active invocation{detail}") from None
        owner = json.dumps(
            {
                "hostname": socket.gethostname(),
                "pid": os.getpid(),
                "started_at": _now(),
            },
            sort_keys=True,
        ).encode("utf-8")
        os.ftruncate(descriptor, 0)
        os.lseek(descriptor, 0, os.SEEK_SET)
        os.write(descriptor, owner + b"\n")
        os.fsync(descriptor)
        yield
    finally:
        if locked:
            fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def _reclaim_interrupted_records(manifest: dict[str, object]) -> int:
    reclaimed = 0
    for record in _records(manifest):
        if record.get("status") != "running":
            continue
        owner_hostname = record.get("hostname")
        owner_pid = record.get("pid")
        record.update(
            {
                "status": "failed",
                "finished_at": _now(),
                "error_type": "InterruptedStudyInvocation",
                "error": (
                    "reclaimed assignment from interrupted study invocation "
                    f"on {owner_hostname} pid {owner_pid}"
                ),
            }
        )
        record.pop("traceback", None)
        reclaimed += 1
    return reclaimed


def _report_noncompleted_records(manifest: dict[str, object]) -> None:
    for record in _records(manifest):
        status = str(record.get("status"))
        if status == "completed":
            continue
        print(
            f"assignment {status}: {record.get('assignment_id')}: "
            f"{record.get('error_type')}: {record.get('error')}",
            file=sys.stderr,
        )


def _records(manifest: dict[str, object]) -> list[dict[str, object]]:
    records = manifest.get("records")
    if not isinstance(records, list) or any(not isinstance(item, dict) for item in records):
        raise RuntimeError("study manifest records are invalid")
    return records


def _record_for(manifest: dict[str, object], assignment_id: str) -> dict[str, object]:
    matches = [
        item for item in _records(manifest) if item.get("assignment_id") == assignment_id
    ]
    if len(matches) != 1:
        raise RuntimeError(f"study record is missing or duplicated: {assignment_id}")
    return matches[0]


def _now() -> str:
    return datetime.now().astimezone().isoformat()
