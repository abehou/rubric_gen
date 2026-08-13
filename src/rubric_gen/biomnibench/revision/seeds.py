"""Generate and resolve immutable, replicate-specific initial submissions."""

from __future__ import annotations

import json
import os
import queue
import secrets
import shutil
import stat
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from rubric_gen.biomnibench.agent.models import RunPaths
from rubric_gen.biomnibench.agent.prompts import solver_prompt
from rubric_gen.biomnibench.agent.runners import AgentRunner
from rubric_gen.biomnibench.experiment import Experiment
from rubric_gen.biomnibench.revision.artifacts import (
    copy_solution_workspace,
    make_tree_read_only,
    sha256_file,
    solution_tree_sha256,
    tree_sha256,
)
from rubric_gen.biomnibench.revision.judge import (
    BiomniSubmissionJudge,
    SubmissionJudgeConfig,
    resolve_optimizer_rubric,
)
from rubric_gen.biomnibench.utils.hashing import sha256_text
from rubric_gen.biomnibench.utils.progress import TerminalProgress
from rubric_gen.biomnibench.utils.serialization import write_json_atomic


SEED_SET_SCHEMA_VERSION = 3
SEED_SCHEMA_VERSION = 4
SEED_SET_KIND = "rubric-gen-biomnibench-randomized-seed-set"
SEED_KIND = "rubric-gen-biomnibench-randomized-seed"


@dataclass(frozen=True)
class SeedSetConfig:
    experiment: Experiment
    output_dir: Path
    max_concurrency: int
    resume: bool = False
    vllm_endpoints: dict[str, str] = field(default_factory=dict)

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


class SeedSetRunner:
    def __init__(self, config: SeedSetConfig) -> None:
        self.config = config
        self.experiment = config.experiment
        self.protocol = self.experiment.protocol
        self.agent = self.experiment.agent_config(
            quiet=True,
            vllm_endpoints=config.vllm_endpoints
        )

    def run(self) -> int:
        root = self.config.output_dir.resolve()
        existed = os.path.lexists(root)
        if existed and not self.config.resume:
            raise FileExistsError(f"seed output already exists: {root}")
        if existed and (root.is_symlink() or not root.is_dir()):
            raise RuntimeError(f"invalid seed output directory: {root}")
        jobs = self._jobs()
        if not jobs:
            raise ValueError("seed generation selected no task/replicate blocks")
        if not existed:
            root.mkdir(parents=True)
        self._validate_resume_manifest(root, jobs, existed=existed)
        completed, pending = self._resume_partition(root, jobs)
        failures: list[dict[str, object]] = []
        self._write_root_manifest(root, jobs, "running", failures)
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
        self._write_root_manifest(
            root,
            jobs,
            "failed" if failures else "completed",
            failures,
        )
        return int(bool(failures))

    def _jobs(self) -> list[tuple[Path, int]]:
        earliest: dict[tuple[str, int], int] = {}
        for assignment in self.experiment.assignments:
            key = (str(assignment["task_id"]), int(assignment["replicate"]))
            order = int(assignment["execution_order"])
            earliest[key] = min(order, earliest.get(key, order))
        return [
            (self.experiment.task_dir(task_id), replicate)
            for task_id, replicate in sorted(earliest, key=earliest.__getitem__)
        ]

    def _write_root_manifest(
        self,
        root: Path,
        jobs: list[tuple[Path, int]],
        status: str,
        failures: list[dict[str, object]],
    ) -> None:
        manifest = {
            "schema_version": SEED_SET_SCHEMA_VERSION,
            "kind": SEED_SET_KIND,
            "status": status,
            "experiment_path": str(self.experiment.path),
            "experiment_id": self.experiment.experiment_id,
            "blocks": [
                {"task_id": task.name, "replicate": replicate}
                for task, replicate in jobs
            ],
            "max_concurrency": self.config.max_concurrency,
            "failures": failures,
        }
        if self.experiment.seed_submission_source is not None:
            source_dir, source_experiment_id = self.experiment.seed_submission_source
            manifest["submission_source"] = {
                "output_dir": str(source_dir),
                "experiment_id": source_experiment_id,
            }
        write_json_atomic(root / "manifest.json", manifest)

    def _validate_resume_manifest(
        self,
        root: Path,
        jobs: list[tuple[Path, int]],
        *,
        existed: bool,
    ) -> None:
        manifest_path = root / "manifest.json"
        if not existed:
            return
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise RuntimeError("existing seed output has no regular manifest")
        try:
            manifest = json.loads(manifest_path.read_text())
        except json.JSONDecodeError as exc:
            raise RuntimeError("existing seed manifest is invalid") from exc
        expected = {
            "schema_version": SEED_SET_SCHEMA_VERSION,
            "kind": SEED_SET_KIND,
            "experiment_path": str(self.experiment.path),
            "experiment_id": self.experiment.experiment_id,
            "blocks": [
                {"task_id": task.name, "replicate": replicate}
                for task, replicate in jobs
            ],
        }
        if self.experiment.seed_submission_source is not None:
            source_dir, source_experiment_id = self.experiment.seed_submission_source
            expected["submission_source"] = {
                "output_dir": str(source_dir),
                "experiment_id": source_experiment_id,
            }
        for key, value in expected.items():
            if manifest.get(key) != value:
                raise RuntimeError(
                    f"seed resume configuration mismatch for {key}: "
                    f"recorded={manifest.get(key)!r}, requested={value!r}"
                )

    def _resume_partition(
        self,
        root: Path,
        jobs: list[tuple[Path, int]],
    ) -> tuple[list[tuple[Path, int]], list[tuple[Path, int]]]:
        if not self.config.resume:
            return [], jobs
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
            _resolve_task_seed(
                root,
                task,
                replicate,
                experiment_id=self.experiment.experiment_id,
                provider=self.agent.provider,
                requested_model=self.agent.model,
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
        temporary = Path(tempfile.mkdtemp(prefix="biomnibench-seed-"))
        destination = _seed_root(root, task_dir.name, replicate)
        if os.path.lexists(destination):
            raise FileExistsError(f"seed block already exists: {destination}")
        try:
            submission = destination / "submission"
            workspace = submission / "workspace"
            submission.mkdir(parents=True)
            trajectory = submission / "trajectory.stream.jsonl"
            submission_source = self.experiment.seed_submission_source
            if submission_source is None:
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
                    prompt=solver_prompt(benchmark=self.experiment.benchmark),
                    benchmark=self.experiment.benchmark,
                ).run(task_dir.resolve(), paths=paths)
                if exit_code != 0:
                    raise RuntimeError(f"seed solver exited with code {exit_code}")
                copy_solution_workspace(paths.workspace_dir, workspace)
                shutil.copyfile(paths.stream_path, trajectory)
                source_status = json.loads(paths.status_path.read_text())
            else:
                source_dir, source_experiment_id = submission_source
                source = resolve_seed(
                    source_dir,
                    task_dir,
                    replicate,
                    experiment_id=source_experiment_id,
                    provider=self.agent.provider,
                    requested_model=self.agent.model,
                )
                copy_solution_workspace(source.submission_dir / "workspace", workspace)
                shutil.copyfile(
                    source.submission_dir / "trajectory.stream.jsonl", trajectory
                )
                source_status = dict(source.manifest["source_status"])  # type: ignore[arg-type]
                source_status["submission_source"] = {
                    "experiment_id": source_experiment_id,
                    "seed_sha256": source.sha256,
                }
            workspace_sha = solution_tree_sha256(workspace)
            trajectory_sha = sha256_file(trajectory)
            instruction_sha = sha256_file(task_dir / "instruction.md")
            data_sha = tree_sha256(task_dir / "environment" / "data")
            seed_sha = sha256_text(
                f"{self.experiment.experiment_id}\n{task_dir.name}\n{replicate}\n"
                f"{instruction_sha}\n{data_sha}\n{workspace_sha}\n{trajectory_sha}\n"
            )
            write_json_atomic(submission / "status.json", {
                "schema_version": 2,
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
                "schema_version": 2,
                "submission_id": "s000",
                "session_id": None,
                "workspace_sha256": workspace_sha,
                "trajectory_sha256": trajectory_sha,
            })
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
                "schema_version": SEED_SCHEMA_VERSION,
                "kind": SEED_KIND,
                "experiment_id": self.experiment.experiment_id,
                "task_id": task_dir.name,
                "replicate": replicate,
                "provider": self.agent.provider,
                "requested_model": self.agent.model,
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

    def _judge_initial_submission(
        self,
        task_dir: Path,
        submission: Path,
        experiment_dir: Path,
    ):
        judge_config = SubmissionJudgeConfig(
            task_dir=task_dir,
            experiment_dir=experiment_dir,
            review=str(self.protocol["review"]),
            judge_model=str(self.protocol["judge_model"]),
            base_url=self.config.vllm_endpoints.get(
                str(self.protocol["judge_model"])
            ),
            rubric_name=str(self.protocol["rubric_name"]),
            rubric_set=None,
            max_review_chars=self.protocol["max_review_chars"],  # type: ignore[arg-type]
            max_retries=int(self.protocol["judge_max_retries"]),
        )
        rubric = resolve_optimizer_rubric(judge_config)
        judge = BiomniSubmissionJudge(judge_config, rubric)
        return (
            judge.evaluate(submission, secrets.token_hex(16)),
            judge.scoring_identity(),
        )


def resolve_seed(
    seed_set: Path,
    task_dir: Path,
    replicate: int,
    *,
    experiment_id: str,
    provider: str,
    requested_model: str,
) -> ResolvedSeed:
    root = seed_set.resolve()
    if seed_set.is_symlink() or not (root / "manifest.json").is_file():
        raise RuntimeError("seed set is not a regular completed seed set")
    root_manifest = json.loads((root / "manifest.json").read_text())
    if (
        root_manifest.get("schema_version") != SEED_SET_SCHEMA_VERSION
        or root_manifest.get("kind") != SEED_SET_KIND
        or root_manifest.get("status") != "completed"
        or root_manifest.get("experiment_id") != experiment_id
    ):
        raise RuntimeError("seed set does not match the experiment")
    return _resolve_task_seed(
        root,
        task_dir,
        replicate,
        experiment_id=experiment_id,
        provider=provider,
        requested_model=requested_model,
    )


def _resolve_task_seed(
    root: Path,
    task_dir: Path,
    replicate: int,
    *,
    experiment_id: str,
    provider: str,
    requested_model: str,
) -> ResolvedSeed:
    if type(replicate) is not int or replicate < 1:
        raise ValueError("replicate must be a positive integer")
    seed_root = _seed_root(root, task_dir.name, replicate)
    manifest_path = seed_root / "manifest.json"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise RuntimeError(f"missing seed for {task_dir.name} replicate {replicate}")
    manifest = json.loads(manifest_path.read_text())
    if (
        set(manifest) != {
            "schema_version", "kind", "experiment_id", "task_id",
            "replicate", "provider", "requested_model", "instruction_sha256",
            "data_sha256", "workspace_sha256", "trajectory_sha256",
            "score_validation_sha256", "evaluation_sha256", "scoring_identity",
            "usage_sha256",
            "judgment_sha256", "seed_sha256", "source_status",
        }
        or manifest.get("schema_version") != SEED_SCHEMA_VERSION
        or manifest.get("kind") != SEED_KIND
        or manifest.get("experiment_id") != experiment_id
        or manifest.get("task_id") != task_dir.name
        or manifest.get("replicate") != replicate
        or manifest.get("provider") != provider
        or manifest.get("requested_model") != requested_model
        or not isinstance(manifest.get("source_status"), dict)
        or manifest["source_status"].get("exit_code") != 0  # type: ignore[union-attr]
        or manifest["source_status"].get("provider") != provider  # type: ignore[union-attr]
    ):
        raise RuntimeError(f"invalid seed for {task_dir.name} replicate {replicate}")
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
    if not isinstance(identity, dict):
        raise RuntimeError(f"seed integrity check failed for {task_dir.name}")
    judgment_sha = sha256_text(
        f"{score_validation_sha}\n{evaluation_sha}\n{usage_sha}\n"
        f"{json.dumps(identity, sort_keys=True, separators=(',', ':'))}\n"
    )
    solution_sha = sha256_text(
        f"{experiment_id}\n{task_dir.name}\n{replicate}\n"
        f"{instruction_sha}\n{data_sha}\n{workspace_sha}\n{trajectory_sha}\n"
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


def _seed_root(root: Path, task_id: str, replicate: int) -> Path:
    return root / "tasks" / task_id / f"rep-{replicate:03d}"


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
