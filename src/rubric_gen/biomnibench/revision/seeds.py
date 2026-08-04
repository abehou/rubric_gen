"""Generate and resolve immutable initial-submission seeds."""

from __future__ import annotations

import json
import os
import queue
import secrets
import shutil
import stat
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from rubric_gen.biomnibench.agent.models import AgentRunConfig, RunPaths
from rubric_gen.biomnibench.agent.runners import AgentRunner
from rubric_gen.biomnibench.agent.workspaces import TaskCatalog
from rubric_gen.biomnibench.revision.artifacts import (
    copy_solution_workspace,
    make_tree_read_only,
    sha256_file,
    solution_tree_sha256,
    tree_sha256,
)
from rubric_gen.biomnibench.utils.hashing import sha256_text
from rubric_gen.biomnibench.utils.serialization import write_json_atomic
from rubric_gen.biomnibench.utils.progress import TerminalProgress
from rubric_gen.biomnibench.revision.judge import (
    BiomniSubmissionJudge,
    SubmissionJudgeConfig,
    resolve_optimizer_rubric,
)


SEED_SET_KIND = "rubric-gen-biomnibench-judged-seed-set"
SEED_KIND = "rubric-gen-biomnibench-judged-seed"


@dataclass(frozen=True)
class SeedSetConfig:
    tasks_dir: Path
    output_dir: Path
    agent: AgentRunConfig
    top: int
    max_concurrency: int
    judge_model: str | None = None
    rubric_name: str | None = None
    rubric_set: Path | None = None
    review: str = "trace"
    max_review_chars: int | None = None
    resume: bool = False


@dataclass(frozen=True)
class ResolvedSeed:
    root: Path
    task_dir: Path
    submission_dir: Path
    manifest: dict[str, object]

    @property
    def sha256(self) -> str:
        value = self.manifest["seed_sha256"]
        assert isinstance(value, str)
        return value

    @property
    def judgment(self) -> tuple[Path, Path, dict[str, object]]:
        root = self.root / "tasks" / self.task_dir.name / "initial_judgment"
        identity = self.manifest["scoring_identity"]
        assert isinstance(identity, dict)
        return root / "score_validation.json", root / "evaluation.json", identity


class SeedSetRunner:
    def __init__(self, config: SeedSetConfig) -> None:
        self.config = config

    def run(self) -> int:
        root = self.config.output_dir.resolve()
        if os.path.lexists(root) and not self.config.resume:
            raise FileExistsError(f"seed output already exists: {root}")
        if os.path.lexists(root) and (root.is_symlink() or not root.is_dir()):
            raise RuntimeError(f"invalid seed output directory: {root}")
        tasks = TaskCatalog(self.config.tasks_dir).tasks()
        tasks = tasks if self.config.top == -1 else tasks[: self.config.top]
        if not tasks:
            raise ValueError("seed generation selected no tasks")
        root.mkdir(parents=True, exist_ok=self.config.resume)
        self._validate_resume_manifest(root, tasks)
        completed, pending = self._resume_partition(root, tasks)
        failures: list[dict[str, str]] = []
        self._write_root_manifest(root, tasks, "running", failures)
        with TerminalProgress(
            total=len(tasks),
            description="seed batch",
            unit="task",
            position=0,
        ) as progress:
            for _ in completed:
                progress.update()
            positions: queue.SimpleQueue[int] = queue.SimpleQueue()
            for position in range(1, self.config.max_concurrency + 1):
                positions.put(position)

            def run_with_progress(task: Path) -> None:
                position = positions.get()
                try:
                    with TerminalProgress(
                        total=1,
                        description=f"seed {task.name}",
                        unit="task",
                        position=position,
                        leave=False,
                    ) as child:
                        child.set_status("solver")
                        self._one(root, task, on_stage=child.set_status)
                        child.update()
                finally:
                    positions.put(position)

            with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as pool:
                futures = {
                    pool.submit(run_with_progress, task): task for task in pending
                }
                for future in as_completed(futures):
                    task = futures[future]
                    try:
                        future.result()
                    except (Exception, SystemExit) as exc:
                        failures.append({
                            "task_id": task.name,
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        })
                    finally:
                        progress.update()
        self._write_root_manifest(
            root,
            tasks,
            "failed" if failures else "completed",
            failures,
        )
        return int(bool(failures))

    def _write_root_manifest(
        self,
        root: Path,
        tasks: list[Path],
        status: str,
        failures: list[dict[str, str]],
    ) -> None:
        write_json_atomic(root / "manifest.json", {
            "schema_version": 2,
            "kind": SEED_SET_KIND,
            "status": status,
            "tasks_dir": str(self.config.tasks_dir.resolve()),
            "task_ids": [task.name for task in tasks],
            "provider": self.config.agent.provider,
            "model": self.config.agent.model,
            "max_retries": self.config.agent.retries,
            "prompt": "base",
            "judge_model": self.config.judge_model,
            "rubric_name": self.config.rubric_name,
            "rubric_set": str(self.config.rubric_set.resolve()) if self.config.rubric_set else None,
            "review": self.config.review,
            "max_review_chars": self.config.max_review_chars,
            "failures": failures,
        })

    def _validate_resume_manifest(self, root: Path, tasks: list[Path]) -> None:
        manifest_path = root / "manifest.json"
        if not manifest_path.exists():
            return
        manifest = json.loads(manifest_path.read_text())
        expected = {
            "schema_version": 2,
            "kind": SEED_SET_KIND,
            "tasks_dir": str(self.config.tasks_dir.resolve()),
            "task_ids": [task.name for task in tasks],
            "provider": self.config.agent.provider,
            "model": self.config.agent.model,
            "prompt": "base",
            "judge_model": self.config.judge_model,
            "rubric_name": self.config.rubric_name,
            "rubric_set": str(self.config.rubric_set.resolve()) if self.config.rubric_set else None,
            "review": self.config.review,
            "max_review_chars": self.config.max_review_chars,
        }
        for key, value in expected.items():
            if manifest.get(key) != value:
                raise RuntimeError(
                    f"seed resume configuration mismatch for {key}: "
                    f"recorded={manifest.get(key)!r}, requested={value!r}"
                )

    def _resume_partition(
        self, root: Path, tasks: list[Path]
    ) -> tuple[list[Path], list[Path]]:
        if not self.config.resume:
            return [], tasks
        completed: list[Path] = []
        pending: list[Path] = []
        for task in tasks:
            task_root = root / "tasks" / task.name
            if not os.path.lexists(task_root):
                pending.append(task)
                continue
            if task_root.is_symlink() or not task_root.is_dir():
                raise RuntimeError(f"invalid partial task seed: {task_root}")
            if not (task_root / "manifest.json").is_file():
                _remove_partial_seed(task_root)
                pending.append(task)
                continue
            seed = _resolve_task_seed(root, task)
            if (
                seed.manifest.get("provider") != self.config.agent.provider
                or seed.manifest.get("model") != self.config.agent.model
            ):
                raise RuntimeError(f"seed model mismatch for task {task.name}")
            completed.append(task)
        return completed, pending

    def _one(
        self,
        root: Path,
        task_dir: Path,
        *,
        on_stage: Callable[[str], None] | None = None,
    ) -> None:
        temporary = Path(tempfile.mkdtemp(prefix="biomnibench-seed-"))
        try:
            run_dir = temporary / "run"
            paths = RunPaths(
                provider=self.config.agent.provider,
                run_dir=run_dir,
                workspace_dir=temporary / "workspace",
                prompt_path=run_dir / "prompt.txt",
                policy_path=run_dir / "no-web-policy.toml",
                stream_path=run_dir / "trajectory.stream.jsonl",
                status_path=run_dir / "status.json",
            )
            exit_code, paths = AgentRunner(self.config.agent).run(
                task_dir.resolve(), paths=paths
            )
            if exit_code != 0:
                raise RuntimeError(f"seed solver exited with code {exit_code}")
            destination = root / "tasks" / task_dir.name
            submission = destination / "submission"
            workspace = submission / "workspace"
            submission.mkdir(parents=True)
            copy_solution_workspace(paths.workspace_dir, workspace)
            trajectory = submission / "trajectory.stream.jsonl"
            shutil.copyfile(paths.stream_path, trajectory)
            status = json.loads(paths.status_path.read_text())
            workspace_sha = solution_tree_sha256(workspace)
            trajectory_sha = sha256_file(trajectory)
            instruction_sha = sha256_file(task_dir / "instruction.md")
            data_sha = tree_sha256(task_dir / "environment" / "data")
            seed_sha = sha256_text(
                f"{instruction_sha}\n{data_sha}\n{workspace_sha}\n{trajectory_sha}\n"
            )
            write_json_atomic(submission / "status.json", {
                "schema_version": 1,
                "task": task_dir.name,
                "task_dir": str(task_dir.resolve()),
                "workspace_dir": str(workspace),
                "provider": self.config.agent.provider,
                "session_id": None,
                "submission_id": "s000",
                "exit_code": 0,
            })
            write_json_atomic(submission / "snapshot.json", {
                "schema_version": 1,
                "submission_id": "s000",
                "session_id": None,
                "workspace_sha256": workspace_sha,
                "trajectory_sha256": trajectory_sha,
            })
            if on_stage is not None:
                on_stage("judge")
            judge_work = destination / ".initial-judge-work"
            artifacts, scoring_identity = _judge_initial_submission(
                self.config, task_dir, submission, judge_work
            )
            judgment = destination / "initial_judgment"
            judgment.mkdir()
            score_validation = judgment / "score_validation.json"
            evaluation = judgment / "evaluation.json"
            shutil.copyfile(artifacts.score_validation_path, score_validation)
            shutil.copyfile(artifacts.evaluation_path, evaluation)
            judgment_sha = sha256_text(
                f"{sha256_file(score_validation)}\n{sha256_file(evaluation)}\n"
                f"{json.dumps(scoring_identity, sort_keys=True, separators=(',', ':'))}\n"
            )
            _remove_partial_seed(judge_work)
            write_json_atomic(destination / "manifest.json", {
                "schema_version": 2,
                "kind": SEED_KIND,
                "task_id": task_dir.name,
                "task_dir": str(task_dir.resolve()),
                "provider": self.config.agent.provider,
                "model": self.config.agent.model,
                "max_retries": self.config.agent.retries,
                "prompt": "base",
                "instruction_sha256": instruction_sha,
                "data_sha256": data_sha,
                "workspace_sha256": workspace_sha,
                "trajectory_sha256": trajectory_sha,
                "score_validation_sha256": sha256_file(score_validation),
                "evaluation_sha256": sha256_file(evaluation),
                "scoring_identity": scoring_identity,
                "judgment_sha256": judgment_sha,
                "seed_sha256": sha256_text(f"{seed_sha}{judgment_sha}\n"),
                "source_status": status,
            })
            make_tree_read_only(destination)
        finally:
            shutil.rmtree(temporary, ignore_errors=True)


def _judge_initial_submission(
    config: SeedSetConfig,
    task_dir: Path,
    submission: Path,
    experiment_dir: Path,
):
    judge_config = SubmissionJudgeConfig(
        task_dir=task_dir,
        experiment_dir=experiment_dir,
        review=config.review,
        judge_model=config.judge_model,
        rubric_name=config.rubric_name,
        rubric_set=config.rubric_set,
        max_review_chars=config.max_review_chars,
        max_retries=config.agent.retries,
    )
    rubric = resolve_optimizer_rubric(judge_config)
    judge = BiomniSubmissionJudge(judge_config, rubric)
    return judge.evaluate(submission, secrets.token_hex(16)), judge.scoring_identity()


def resolve_seed(seed_set: Path, task_dir: Path) -> ResolvedSeed:
    root = seed_set.resolve()
    root_manifest = json.loads((root / "manifest.json").read_text())
    if root_manifest.get("kind") != SEED_SET_KIND:
        raise RuntimeError("seed set has the wrong kind")
    if root_manifest.get("status") != "completed":
        raise RuntimeError("seed set is not completed")
    return _resolve_task_seed(root, task_dir)


def _resolve_task_seed(root: Path, task_dir: Path) -> ResolvedSeed:
    seed_root = root / "tasks" / task_dir.name
    manifest = json.loads((seed_root / "manifest.json").read_text())
    if (manifest.get("schema_version") != 2 or manifest.get("kind") != SEED_KIND
            or manifest.get("task_id") != task_dir.name):
        raise RuntimeError(f"invalid seed for task {task_dir.name}")
    submission = seed_root / "submission"
    workspace_sha = solution_tree_sha256(submission / "workspace")
    trajectory_sha = sha256_file(submission / "trajectory.stream.jsonl")
    instruction_sha = sha256_file(task_dir / "instruction.md")
    data_sha = tree_sha256(task_dir / "environment" / "data")
    judgment = seed_root / "initial_judgment"
    score_validation_sha = sha256_file(judgment / "score_validation.json")
    evaluation_sha = sha256_file(judgment / "evaluation.json")
    identity = manifest.get("scoring_identity")
    if not isinstance(identity, dict):
        raise RuntimeError(f"seed integrity check failed for {task_dir.name}")
    judgment_sha = sha256_text(
        f"{score_validation_sha}\n{evaluation_sha}\n"
        f"{json.dumps(identity, sort_keys=True, separators=(',', ':'))}\n"
    )
    solution_sha = sha256_text(
        f"{instruction_sha}\n{data_sha}\n{workspace_sha}\n{trajectory_sha}\n"
    )
    if (
        manifest.get("instruction_sha256") != instruction_sha
        or manifest.get("data_sha256") != data_sha
        or manifest.get("workspace_sha256") != workspace_sha
        or manifest.get("trajectory_sha256") != trajectory_sha
        or manifest.get("score_validation_sha256") != score_validation_sha
        or manifest.get("evaluation_sha256") != evaluation_sha
        or manifest.get("judgment_sha256") != judgment_sha
        or manifest.get("seed_sha256") != sha256_text(f"{solution_sha}{judgment_sha}\n")
    ):
        raise RuntimeError(f"seed integrity check failed for {task_dir.name}")
    return ResolvedSeed(root, task_dir.resolve(), submission, manifest)


def _remove_partial_seed(root: Path) -> None:
    directories = [
        path for path in root.rglob("*") if not path.is_symlink() and path.is_dir()
    ]
    for path in [
        *sorted(directories, key=lambda item: len(item.parts), reverse=True),
        root,
    ]:
        path.chmod(stat.S_IMODE(os.lstat(path).st_mode) | stat.S_IRWXU)
    shutil.rmtree(root)
