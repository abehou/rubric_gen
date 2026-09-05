"""Generate and resolve immutable, replicate-specific initial submissions."""

from __future__ import annotations

import fcntl
import json
import os
import queue
import secrets
import shutil
import signal
import stat
import sys
import tempfile
from contextlib import contextmanager
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from rubric_gen.benchmarks import (
    SubmissionBenchmark,
    SubmissionBenchmarkId,
    get_submission_benchmark,
)
from rubric_gen.runtime.agents.models import AgentRunConfig, RunPaths
from rubric_gen.submission_revision.prompts import PromptProfile, solver_prompt
from rubric_gen.runtime.agents.runners import AgentRunner
from rubric_gen.submission_revision.experiment import Experiment
from rubric_gen.submission_revision.artifacts import (
    snapshot_solution_workspace,
    make_tree_read_only,
    sha256_file,
    solution_tree_sha256,
    tree_sha256,
)
from rubric_gen.submission_revision.judge import (
    FrozenRubricJudge,
    SCORING_IDENTITY_KEYS,
    SubmissionJudgeConfig,
    resolve_optimizer_rubric,
)
from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.artifacts.serialization import write_json_atomic


SEED_SET_KIND = "rubric-gen-submission-seed-set"
SEED_KIND = "rubric-gen-submission-seed"


@dataclass(frozen=True)
class SeedSetConfig:
    experiment: Experiment
    output_dir: Path
    max_concurrency: int

    def __post_init__(self) -> None:
        if type(self.max_concurrency) is not int or self.max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")


@dataclass(frozen=True)
class ResolvedSeed:
    root: Path
    seed_root: Path
    task_dir: Path
    replicate: int
    submission_dir: Path
    manifest: dict[str, object]

    @property
    def sha256(self) -> str:
        value = self.manifest["seed_sha256"]
        assert isinstance(value, str)
        return value

    @property
    def judgment(self) -> tuple[Path, Path, dict[str, object]]:
        judgment = self.seed_root / "initial_judgment"
        identity = self.manifest["scoring_identity"]
        assert isinstance(identity, dict)
        return (
            judgment / "score_validation.json",
            judgment / "evaluation.json",
            identity,
        )

    @property
    def elicitation_artifacts(self) -> tuple[tuple[str, Path], ...]:
        """Return every structurally valid public artifact in this seed block."""

        primary_role = self.manifest["primary_elicitation_role"]
        attempt = self.manifest["elicitation_attempt"]
        assert isinstance(primary_role, str) and isinstance(attempt, dict)
        artifacts = [(primary_role, self.submission_dir / "workspace")]
        if attempt["included"]:
            role = attempt["role"]
            assert isinstance(role, str)
            artifacts.append((role, self.seed_root / "elicitation_attempt" / "workspace"))
        return tuple(artifacts)


class SeedSetRunner:
    def __init__(self, config: SeedSetConfig) -> None:
        self.config = config
        self.experiment = config.experiment
        self.protocol = self.experiment.protocol
        self.agent = self.experiment.seed_agent_config(
            quiet=True,
        )
        self.solver_prompt = solver_prompt(
            str(self.protocol["prompt"]),
            self.experiment.benchmark,
        )
        self.solver_prompt_sha256 = sha256_text(self.solver_prompt)
        self.primary_profile = PromptProfile(str(self.protocol["prompt"]))
        self.primary_elicitation_role = (
            "adversarial"
            if self.primary_profile is PromptProfile.ADVERSARIAL
            else "clean"
        )
        self.attempt_profile = (
            PromptProfile.BASE
            if self.primary_profile is PromptProfile.ADVERSARIAL
            else PromptProfile.ADVERSARIAL
        )
        self.attempt_elicitation_role = (
            "clean"
            if self.primary_elicitation_role == "adversarial"
            else "adversarial"
        )
        self.attempt_prompt = solver_prompt(
            self.attempt_profile,
            self.experiment.benchmark,
        )
        self.attempt_prompt_sha256 = sha256_text(self.attempt_prompt)

    def run(self) -> int:
        root = self.config.output_dir.resolve()
        if os.path.lexists(root) and (root.is_symlink() or not root.is_dir()):
            raise RuntimeError(f"invalid shared seed directory: {root}")
        root.mkdir(parents=True, exist_ok=True)
        with _seed_pool_lease(root):
            return self._run_locked(root)

    def _run_locked(self, root: Path) -> int:
        jobs = self._jobs()
        if not jobs:
            raise ValueError("seed generation selected no task/replicate blocks")
        manifest_path = root / "manifest.json"
        if manifest_path.is_file():
            self._validate_pool_manifest(root)
        else:
            unexpected = [
                path for path in root.iterdir()
                if path.name != ".seed.lock"
            ]
            if unexpected:
                raise RuntimeError(
                    f"unowned files exist in shared seed directory: {root}"
                )
            self._write_pool_manifest(root)
        completed, pending = self._partition(root, jobs)
        failures: list[dict[str, object]] = []
        with TerminalProgress(
            total=len(jobs),
            description="seed blocks",
            unit="block",
            position=0,
        ) as progress:
            for _ in completed:
                progress.update()
            positions: queue.SimpleQueue[int] = queue.SimpleQueue()
            for position in range(1, self.config.max_concurrency + 1):
                positions.put(position)

            def run_with_progress(job: tuple[Path, int]) -> None:
                task, replicate = job
                position = positions.get()
                try:
                    with TerminalProgress(
                        total=1,
                        description=f"seed {task.name} r{replicate:03d}",
                        unit="block",
                        position=position,
                        leave=False,
                    ) as child:
                        child.set_status("solver")
                        self._one(
                            root,
                            task,
                            replicate,
                            on_stage=child.set_status,
                        )
                        child.update()
                finally:
                    positions.put(position)

            with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as pool:
                futures = {
                    pool.submit(run_with_progress, job): job for job in pending
                }
                for future in as_completed(futures):
                    task, replicate = futures[future]
                    try:
                        future.result()
                    except (Exception, SystemExit) as exc:
                        failures.append({
                            "task_id": task.name,
                            "replicate": replicate,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        })
                    finally:
                        progress.update()
        for failure in failures:
            print(
                f"seed failed for {failure['task_id']} replicate "
                f"{failure['replicate']}: {failure['error_type']}: "
                f"{failure['error']}",
                file=sys.stderr,
            )
        return int(bool(failures))

    def _jobs(self) -> list[tuple[Path, int]]:
        return [
            (self.experiment.task_dir(task_id), replicate)
            for task_id in self.experiment.task_ids
            for replicate in range(1, self.experiment.replicates + 1)
        ]

    @staticmethod
    def _write_pool_manifest(root: Path) -> None:
        write_json_atomic(root / "manifest.json", {
            "kind": SEED_SET_KIND,
        })

    @staticmethod
    def _validate_pool_manifest(root: Path) -> None:
        manifest_path = root / "manifest.json"
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise RuntimeError("shared seed directory has no regular manifest")
        try:
            manifest = json.loads(manifest_path.read_text())
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("shared seed manifest is invalid") from exc
        if manifest != {"kind": SEED_SET_KIND}:
            raise RuntimeError("shared seed manifest has invalid fields")

    def _partition(
        self,
        root: Path,
        jobs: list[tuple[Path, int]],
    ) -> tuple[list[tuple[Path, int]], list[tuple[Path, int]]]:
        completed: list[tuple[Path, int]] = []
        pending: list[tuple[Path, int]] = []
        for task, replicate in jobs:
            seed_root = _seed_root(root, task.name, replicate)
            if not os.path.lexists(seed_root):
                pending.append((task, replicate))
                continue
            if seed_root.is_symlink() or not seed_root.is_dir():
                raise RuntimeError(f"invalid partial seed block: {seed_root}")
            if not (seed_root / "manifest.json").is_file():
                _remove_partial_seed(seed_root)
                pending.append((task, replicate))
                continue
            seed = _resolve_task_seed(
                root,
                task,
                replicate,
                seed_generator=seed_generator_identity(self.agent),
                solver_prompt_sha256=self.solver_prompt_sha256,
                primary_profile=self.primary_profile,
                benchmark=self.experiment.benchmark,
            )
            expected_identity = self._initial_judge(
                task,
                seed.seed_root,
            ).scoring_identity()
            if seed.manifest["scoring_identity"] != expected_identity:
                raise RuntimeError(
                    "shared seed scoring identity does not match the current "
                    f"judge for {task.name} replicate {replicate}"
                )
            completed.append((task, replicate))
        return completed, pending

    def _one(
        self,
        root: Path,
        task_dir: Path,
        replicate: int,
        *,
        on_stage: Callable[[str], None] | None = None,
    ) -> None:
        temporary = Path(tempfile.mkdtemp(prefix="submission-seed-"))
        destination = _seed_root(root, task_dir.name, replicate)
        if os.path.lexists(destination):
            raise FileExistsError(f"seed block already exists: {destination}")
        try:
            submission = destination / "submission"
            workspace = submission / "workspace"
            submission.mkdir(parents=True)
            trajectory = submission / "trajectory.stream.jsonl"
            run_dir = temporary / "run"
            paths = RunPaths(
                provider=self.agent.provider,
                run_dir=run_dir,
                workspace_dir=temporary / "workspace",
                prompt_path=run_dir / "prompt.txt",
                policy_path=run_dir / "no-web-policy.toml",
                stream_path=run_dir / "trajectory.stream.jsonl",
                status_path=run_dir / "status.json",
            )
            benchmark = get_submission_benchmark(self.experiment.benchmark)
            exit_code, paths = AgentRunner(
                self.agent,
                prompt=self.solver_prompt,
                output_errors=benchmark.output_errors,
            ).run(task_dir.resolve(), paths=paths)
            if exit_code != 0:
                diagnostics = self._preserve_solver_failure(
                    destination,
                    task_dir.name,
                    replicate,
                    exit_code,
                    paths,
                )
                signal_name = _signal_name(exit_code)
                signal_suffix = f" ({signal_name})" if signal_name else ""
                raise RuntimeError(
                    f"seed solver exited with code {exit_code}{signal_suffix}; "
                    f"diagnostics: {diagnostics}"
                )
            snapshot_solution_workspace(paths.workspace_dir, workspace)
            shutil.copyfile(paths.stream_path, trajectory)
            source_status = json.loads(paths.status_path.read_text())
            workspace_sha = solution_tree_sha256(workspace)
            trajectory_sha = sha256_file(trajectory)
            instruction_sha = sha256_file(task_dir / "instruction.md")
            data_sha = tree_sha256(task_dir / "environment" / "data")
            if on_stage is not None:
                on_stage("elicitation_attempt")
            elicitation_attempt = self._run_elicitation_attempt(
                destination,
                task_dir,
                benchmark,
            )
            elicitation_identity = {
                "primary_role": self.primary_elicitation_role,
                "attempt": elicitation_attempt,
            }
            elicitation_sha = sha256_text(json.dumps(
                elicitation_identity,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ))
            seed_sha = sha256_text(
                f"{self.experiment.experiment_id}\n{task_dir.name}\n{replicate}\n"
                f"{instruction_sha}\n{data_sha}\n{workspace_sha}\n{trajectory_sha}\n"
                f"{self.solver_prompt_sha256}\n{elicitation_sha}\n"
            )
            write_json_atomic(submission / "status.json", {
                "task": task_dir.name,
                "replicate": replicate,
                "experiment_id": self.experiment.experiment_id,
                "workspace_dir": str(workspace),
                "provider": self.agent.provider,
                "session_id": None,
                "submission_id": "s000",
                "exit_code": 0,
            })
            write_json_atomic(submission / "snapshot.json", {
                "submission_id": "s000",
                "session_id": None,
                "workspace_sha256": workspace_sha,
                "trajectory_sha256": trajectory_sha,
            })
            make_tree_read_only(submission)
            if on_stage is not None:
                on_stage("judge")
            judge_work = destination / ".initial-judge-work"
            artifacts, scoring_identity = self._judge_initial_submission(
                task_dir, submission, judge_work
            )
            judgment = destination / "initial_judgment"
            judgment.mkdir()
            score_validation = judgment / "score_validation.json"
            evaluation = judgment / "evaluation.json"
            usage = judgment / "usage.json"
            shutil.copyfile(artifacts.score_validation_path, score_validation)
            shutil.copyfile(artifacts.evaluation_path, evaluation)
            usage_source = artifacts.score_validation_path.with_name("usage.json")
            if not usage_source.is_file():
                raise RuntimeError("initial judge did not persist usage metadata")
            shutil.copyfile(usage_source, usage)
            judgment_sha = sha256_text(
                f"{sha256_file(score_validation)}\n{sha256_file(evaluation)}\n"
                f"{sha256_file(usage)}\n"
                f"{json.dumps(scoring_identity, sort_keys=True, separators=(',', ':'))}\n"
            )
            _remove_partial_seed(judge_work)
            write_json_atomic(destination / "manifest.json", {
                "kind": SEED_KIND,
                "experiment_id": self.experiment.experiment_id,
                "task_id": task_dir.name,
                "replicate": replicate,
                "seed_generator": seed_generator_identity(self.agent),
                "solver_prompt_sha256": self.solver_prompt_sha256,
                "primary_elicitation_role": self.primary_elicitation_role,
                "elicitation_attempt": elicitation_attempt,
                "instruction_sha256": instruction_sha,
                "data_sha256": data_sha,
                "workspace_sha256": workspace_sha,
                "trajectory_sha256": trajectory_sha,
                "score_validation_sha256": sha256_file(score_validation),
                "evaluation_sha256": sha256_file(evaluation),
                "usage_sha256": sha256_file(usage),
                "scoring_identity": scoring_identity,
                "judgment_sha256": judgment_sha,
                "seed_sha256": sha256_text(f"{seed_sha}{judgment_sha}\n"),
                "source_status": source_status,
            })
            make_tree_read_only(destination)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    def _run_elicitation_attempt(
        self,
        destination: Path,
        task_dir: Path,
        benchmark: SubmissionBenchmark,
    ) -> dict[str, object]:
        temporary = Path(tempfile.mkdtemp(prefix="submission-seed-extra-"))
        try:
            run_dir = temporary / "run"
            paths = RunPaths(
                provider=self.agent.provider,
                run_dir=run_dir,
                workspace_dir=temporary / "workspace",
                prompt_path=run_dir / "prompt.txt",
                policy_path=run_dir / "no-web-policy.toml",
                stream_path=run_dir / "trajectory.stream.jsonl",
                status_path=run_dir / "status.json",
            )
            exit_code, paths = AgentRunner(
                self.agent,
                prompt=self.attempt_prompt,
                output_errors=benchmark.output_errors,
            ).run(task_dir.resolve(), paths=paths)
            if not paths.prompt_path.is_file():
                paths.prompt_path.write_text(self.attempt_prompt, encoding="utf-8")
            if not paths.stream_path.is_file() or not paths.status_path.is_file():
                raise RuntimeError(
                    "elicitation attempt did not persist its run records"
                )

            attempt_root = destination / "elicitation_attempt"
            attempt_root.mkdir()
            shutil.copytree(paths.run_dir, attempt_root / "run")
            shutil.copytree(paths.workspace_dir, attempt_root / "workspace")
            persisted_paths = RunPaths(
                provider=paths.provider,
                run_dir=attempt_root / "run",
                workspace_dir=attempt_root / "workspace",
                prompt_path=attempt_root / "run" / paths.prompt_path.name,
                policy_path=attempt_root / "run" / paths.policy_path.name,
                stream_path=attempt_root / "run" / paths.stream_path.name,
                status_path=attempt_root / "run" / paths.status_path.name,
            )
            status = json.loads(persisted_paths.status_path.read_text())
            if "workspace_dir" in status:
                status["workspace_dir"] = str(persisted_paths.workspace_dir)
            if "stderr" in status:
                status["stderr"] = str(persisted_paths.run_dir / "stderr.log")
            write_json_atomic(persisted_paths.status_path, status)

            workspace_sha = solution_tree_sha256(
                persisted_paths.workspace_dir
            )
            included = exit_code == 0 and _public_artifact_is_valid(
                benchmark,
                persisted_paths.workspace_dir,
            )
            return {
                "role": self.attempt_elicitation_role,
                "profile": self.attempt_profile.value,
                "included": included,
                "exit_code": exit_code,
                "prompt_sha256": sha256_file(persisted_paths.prompt_path),
                "workspace_sha256": workspace_sha,
                "trajectory_sha256": sha256_file(persisted_paths.stream_path),
                "status_sha256": sha256_file(persisted_paths.status_path),
            }
        finally:
            shutil.rmtree(temporary, ignore_errors=True)

    @staticmethod
    def _preserve_solver_failure(
        destination: Path,
        task_id: str,
        replicate: int,
        exit_code: int,
        paths: RunPaths,
    ) -> Path:
        diagnostics = destination / "failed_solver"
        diagnostics.mkdir()
        copied: list[str] = []
        for source in (
            paths.prompt_path,
            paths.policy_path,
            paths.stream_path,
            paths.status_path,
            paths.run_dir / "stderr.log",
            paths.output_schema_path,
            paths.output_last_message_path,
        ):
            if source is None or source.is_symlink() or not source.is_file():
                continue
            target = diagnostics / source.name
            shutil.copyfile(source, target)
            copied.append(target.name)
        write_json_atomic(diagnostics / "failure.json", {
            "kind": "rubric-gen-failed-seed-solver",
            "task_id": task_id,
            "replicate": replicate,
            "exit_code": exit_code,
            "signal": _signal_name(exit_code),
            "copied_files": copied,
        })
        return diagnostics

    def _judge_initial_submission(
        self,
        task_dir: Path,
        submission: Path,
        experiment_dir: Path,
    ):
        judge = self._initial_judge(task_dir, experiment_dir)
        return (
            judge.evaluate(submission, secrets.token_hex(16)),
            judge.scoring_identity(),
        )

    def _initial_judge(
        self,
        task_dir: Path,
        experiment_dir: Path,
    ) -> FrozenRubricJudge:
        judge_config = SubmissionJudgeConfig(
            task_dir=task_dir,
            experiment_dir=experiment_dir,
            benchmark=self.experiment.benchmark,
            review=str(self.protocol["review"]),
            judge_model=str(self.protocol["judge_model"]),
            rubric_name=str(self.protocol["rubric_name"]),
            rubric_set=None,
            max_review_chars=self.protocol["max_review_chars"],  # type: ignore[arg-type]
        )
        rubric = resolve_optimizer_rubric(judge_config)
        return FrozenRubricJudge(judge_config, rubric)


def resolve_seed(
    seed_set: Path,
    task_dir: Path,
    replicate: int,
    *,
    seed_generator: AgentRunConfig,
    prompt_profile: PromptProfile | str,
    benchmark: SubmissionBenchmarkId | str,
) -> ResolvedSeed:
    root = seed_set.resolve()
    if seed_set.is_symlink() or not (root / "manifest.json").is_file():
        raise RuntimeError("seed set is not a regular completed seed set")
    try:
        root_manifest = json.loads((root / "manifest.json").read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("seed set has an invalid manifest") from exc
    if not isinstance(root_manifest, dict):
        raise RuntimeError("seed set manifest must be an object")
    return _resolve_task_seed(
        root,
        task_dir,
        replicate,
        seed_generator=seed_generator_identity(seed_generator),
        solver_prompt_sha256=sha256_text(solver_prompt(prompt_profile, benchmark)),
        primary_profile=PromptProfile(prompt_profile),
        benchmark=SubmissionBenchmarkId(benchmark),
    )


def _resolve_task_seed(
    root: Path,
    task_dir: Path,
    replicate: int,
    *,
    seed_generator: dict[str, object],
    solver_prompt_sha256: str,
    primary_profile: PromptProfile,
    benchmark: SubmissionBenchmarkId,
) -> ResolvedSeed:
    if type(replicate) is not int or replicate < 1:
        raise ValueError("replicate must be a positive integer")
    seed_root = _seed_root(root, task_dir.name, replicate)
    manifest_path = seed_root / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise RuntimeError(f"missing seed for {task_dir.name} replicate {replicate}")
    try:
        manifest = json.loads(manifest_path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(
            f"invalid seed for {task_dir.name} replicate {replicate}"
        ) from exc
    required = {
        "kind", "experiment_id", "task_id", "replicate", "seed_generator",
        "solver_prompt_sha256", "instruction_sha256",
        "primary_elicitation_role", "elicitation_attempt", "data_sha256",
        "workspace_sha256", "trajectory_sha256", "score_validation_sha256",
        "evaluation_sha256", "usage_sha256", "scoring_identity",
        "judgment_sha256", "seed_sha256", "source_status",
    }
    owner = manifest.get("experiment_id") if isinstance(manifest, dict) else None
    if (
        not isinstance(manifest, dict)
        or set(manifest) != required
        or manifest.get("kind") != SEED_KIND
        or type(owner) is not str
        or not owner
        or manifest.get("task_id") != task_dir.name
        or manifest.get("replicate") != replicate
        or manifest.get("seed_generator") != seed_generator
        or type(manifest.get("solver_prompt_sha256")) is not str
        or manifest.get("primary_elicitation_role") not in {"clean", "adversarial"}
        or not isinstance(manifest.get("elicitation_attempt"), dict)
        or not isinstance(manifest.get("source_status"), dict)
        or manifest["source_status"].get("exit_code") != 0  # type: ignore[union-attr]
        or manifest["source_status"].get("provider")  # type: ignore[union-attr]
        != seed_generator["provider"]
    ):
        raise RuntimeError(f"invalid seed for {task_dir.name} replicate {replicate}")
    if manifest["solver_prompt_sha256"] != solver_prompt_sha256:
        raise RuntimeError(
            f"seed solver prompt does not match for {task_dir.name} "
            f"replicate {replicate}"
        )
    expected_primary_role = (
        "adversarial"
        if primary_profile is PromptProfile.ADVERSARIAL
        else "clean"
    )
    expected_attempt_profile = (
        PromptProfile.BASE
        if primary_profile is PromptProfile.ADVERSARIAL
        else PromptProfile.ADVERSARIAL
    )
    expected_attempt_role = (
        "clean" if expected_primary_role == "adversarial" else "adversarial"
    )
    if manifest["primary_elicitation_role"] != expected_primary_role:
        raise RuntimeError(f"seed elicitation role changed for {task_dir.name}")
    attempt = _validate_elicitation_attempt(
        seed_root,
        get_submission_benchmark(benchmark),
        expected_profile=expected_attempt_profile,
        expected_role=expected_attempt_role,
    )
    submission = seed_root / "submission"
    workspace_sha = solution_tree_sha256(submission / "workspace")
    trajectory_sha = sha256_file(submission / "trajectory.stream.jsonl")
    instruction_sha = sha256_file(task_dir / "instruction.md")
    data_sha = tree_sha256(task_dir / "environment" / "data")
    judgment = seed_root / "initial_judgment"
    score_validation_sha = sha256_file(judgment / "score_validation.json")
    evaluation_sha = sha256_file(judgment / "evaluation.json")
    usage_sha = sha256_file(judgment / "usage.json")
    identity = manifest.get("scoring_identity")
    if (
        not isinstance(identity, dict)
        or set(identity) != set(SCORING_IDENTITY_KEYS)
    ):
        raise RuntimeError(f"seed integrity check failed for {task_dir.name}")
    judgment_sha = sha256_text(
        f"{score_validation_sha}\n{evaluation_sha}\n{usage_sha}\n"
        f"{json.dumps(identity, sort_keys=True, separators=(',', ':'))}\n"
    )
    solution_sha = sha256_text(
        f"{owner}\n{task_dir.name}\n{replicate}\n"
        f"{instruction_sha}\n{data_sha}\n{workspace_sha}\n{trajectory_sha}\n"
        f"{solver_prompt_sha256}\n{_elicitation_identity_sha(expected_primary_role, attempt)}\n"
    )
    if (
        manifest.get("instruction_sha256") != instruction_sha
        or manifest.get("data_sha256") != data_sha
        or manifest.get("workspace_sha256") != workspace_sha
        or manifest.get("trajectory_sha256") != trajectory_sha
        or manifest.get("score_validation_sha256") != score_validation_sha
        or manifest.get("evaluation_sha256") != evaluation_sha
        or manifest.get("usage_sha256") != usage_sha
        or manifest.get("judgment_sha256") != judgment_sha
        or manifest.get("seed_sha256") != sha256_text(f"{solution_sha}{judgment_sha}\n")
    ):
        raise RuntimeError(f"seed integrity check failed for {task_dir.name}")
    return ResolvedSeed(
        root,
        seed_root,
        task_dir.resolve(),
        replicate,
        submission,
        manifest,
    )


def seed_generator_identity(agent: AgentRunConfig) -> dict[str, object]:
    if type(agent.model) is not str or not agent.model.strip():
        raise ValueError("seed generator requires an explicit model")
    return {
        "provider": agent.provider,
        "model": agent.model,
        "reasoning_effort": agent.reasoning_effort,
        "service_tier": agent.service_tier,
        "executable": agent.executable,
        "retries": agent.retries,
        "timeout_seconds": agent.timeout_seconds,
    }


def _validate_elicitation_attempt(
    seed_root: Path,
    benchmark: SubmissionBenchmark,
    *,
    expected_profile: PromptProfile,
    expected_role: str,
) -> dict[str, object]:
    manifest = json.loads((seed_root / "manifest.json").read_text())
    attempt = manifest.get("elicitation_attempt")
    required = {
        "role", "profile", "included", "exit_code", "prompt_sha256",
        "workspace_sha256", "trajectory_sha256", "status_sha256",
    }
    if (
        not isinstance(attempt, dict)
        or set(attempt) != required
        or attempt.get("role") != expected_role
        or attempt.get("profile") != expected_profile.value
        or type(attempt.get("included")) is not bool
        or type(attempt.get("exit_code")) is not int
        or any(
            type(attempt.get(field)) is not str
            for field in (
                "prompt_sha256", "workspace_sha256", "trajectory_sha256",
                "status_sha256",
            )
        )
    ):
        raise RuntimeError("seed elicitation attempt has invalid fields")
    root = seed_root / "elicitation_attempt"
    run = root / "run"
    workspace = root / "workspace"
    prompt = run / "prompt.txt"
    trajectory = run / "trajectory.stream.jsonl"
    status_path = run / "status.json"
    if (
        root.is_symlink()
        or not root.is_dir()
        or workspace.is_symlink()
        or not workspace.is_dir()
        or any(path.is_symlink() or not path.is_file() for path in (
            prompt, trajectory, status_path,
        ))
    ):
        raise RuntimeError("seed elicitation attempt is incomplete")
    try:
        status = json.loads(status_path.read_text())
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("seed elicitation attempt status is invalid") from exc
    expected_prompt_sha = sha256_text(
        solver_prompt(expected_profile, benchmark.benchmark)
    )
    structurally_valid = (
        attempt["exit_code"] == 0
        and isinstance(status, dict)
        and status.get("exit_code") == 0
        and _public_artifact_is_valid(benchmark, workspace)
    )
    if (
        attempt["included"] is not structurally_valid
        or attempt["prompt_sha256"] != expected_prompt_sha
        or attempt["prompt_sha256"] != sha256_file(prompt)
        or attempt["workspace_sha256"] != solution_tree_sha256(workspace)
        or attempt["trajectory_sha256"] != sha256_file(trajectory)
        or attempt["status_sha256"] != sha256_file(status_path)
    ):
        raise RuntimeError("seed elicitation attempt failed integrity validation")
    return attempt


def _public_artifact_is_valid(
    benchmark: SubmissionBenchmark,
    workspace: Path,
) -> bool:
    try:
        return (
            not benchmark.output_errors(workspace)
            and bool(benchmark.render_user_review(workspace).strip())
        )
    except (OSError, UnicodeError, ValueError, RuntimeError):
        return False


def _elicitation_identity_sha(
    primary_role: str,
    attempt: dict[str, object],
) -> str:
    return sha256_text(json.dumps(
        {"primary_role": primary_role, "attempt": attempt},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ))


def _seed_root(root: Path, task_id: str, replicate: int) -> Path:
    return root / "tasks" / task_id / f"rep-{replicate:03d}"


@contextmanager
def _seed_pool_lease(root: Path):
    with (root / ".seed.lock").open("a+", encoding="utf-8") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def _signal_name(exit_code: int) -> str | None:
    if exit_code >= 0:
        return None
    try:
        return signal.Signals(-exit_code).name
    except ValueError:
        return f"signal {-exit_code}"


def _remove_partial_seed(root: Path) -> None:
    if not os.path.lexists(root):
        return
    directories = [
        path for path in root.rglob("*") if not path.is_symlink() and path.is_dir()
    ]
    for path in [
        *sorted(directories, key=lambda item: len(item.parts), reverse=True),
        root,
    ]:
        path.chmod(stat.S_IMODE(os.lstat(path).st_mode) | stat.S_IRWXU)
    shutil.rmtree(root)
