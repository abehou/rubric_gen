"""Canonical Harvey LAB execution and scoring adapter."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
import json
import os
import shutil
import subprocess
import tempfile
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import TypeVar

from rubric_gen.runtime.progress import TerminalProgress
from rubric_gen.benchmarks.harvey_lab.artifacts import (
    copy_regular_tree,
    make_tree_read_only,
    read_json_object,
    task_path,
    validate_checkout,
    validate_regular_tree,
    validate_task,
)
from rubric_gen.benchmarks.harvey_lab.config import HarveyExperiment
from rubric_gen.benchmarks.harvey_lab.podman import (
    cache_image,
    configured_podman_environment,
    restore_cached_image,
)
from rubric_gen.benchmarks.harvey_lab.runtime import (
    ensure_runtime_directory,
    ensure_runtime_root,
)


_TRANSIENT_PROVIDER_ERRORS = (
    "apiconnectionerror",
    "apitimeouterror",
    "connection reset by peer",
    "httpx.connecterror",
    "httpx.readtimeout",
    "httpx.remoteprotocolerror",
    "internalservererror",
    "overloaded_error",
    "ratelimiterror",
    "rate_limit_error",
    "serviceunavailableerror",
    "temporarily unavailable",
)
_TRANSIENT_TASK_AGENT_ERRORS = (
    *_TRANSIENT_PROVIDER_ERRORS,
    "invalid_prompt",
)
_TRANSIENT_JUDGE_ERRORS = (
    *_TRANSIENT_PROVIDER_ERRORS,
    "grammar compilation timed out.",
    "judge response truncated (stop_reason=max_tokens",
)

_Input = TypeVar("_Input")
_Output = TypeVar("_Output")


def _bounded_map(
    items: Iterable[_Input],
    operation: Callable[[_Input], _Output],
    max_workers: int,
) -> Iterator[_Output]:
    """Run one active window and stop scheduling after the first failure."""
    remaining = iter(items)
    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {}
        for _ in range(max_workers):
            try:
                item = next(remaining)
            except StopIteration:
                break
            futures[pool.submit(operation, item)] = item

        while futures:
            future = next(as_completed(futures))
            del futures[future]
            result = future.result()
            yield result
            try:
                item = next(remaining)
            except StopIteration:
                continue
            futures[pool.submit(operation, item)] = item


@dataclass(frozen=True)
class CandidateEvaluation:
    candidate_id: str
    task_scores: dict[str, dict[str, object]]
    mean_criterion_pass: float
    mean_all_pass: float


def aggregate_scores(
    candidate_id: str, scores: dict[str, dict[str, object]]
) -> CandidateEvaluation:
    fractions = []
    all_pass = []
    for task_id, score in scores.items():
        passed, count = score.get("n_passed"), score.get("n_criteria")
        if type(passed) is not int or type(count) is not int or count < 1 or not 0 <= passed <= count:
            raise ValueError(f"invalid Harvey score for {candidate_id} on {task_id}")
        fractions.append(passed / count)
        all_pass.append(1.0 if score.get("all_pass") is True else 0.0)
    if not fractions:
        raise ValueError(f"candidate {candidate_id} has no task scores")
    return CandidateEvaluation(
        candidate_id=candidate_id,
        task_scores=scores,
        mean_criterion_pass=sum(fractions) / len(fractions),
        mean_all_pass=sum(all_pass) / len(all_pass),
    )


class HarveyEvaluator:
    """Run candidate code in a temporary Harvey tree with controller-owned scoring."""

    def __init__(
        self,
        experiment: HarveyExperiment,
        *,
        runtime_root: Path,
        uv_executable: str = "uv",
        max_concurrency: int = 1,
        max_retries: int = 3,
    ) -> None:
        if type(max_concurrency) is not int or max_concurrency < 1:
            raise ValueError("Harvey max_concurrency must be a positive integer")
        if type(max_retries) is not int or max_retries < 0:
            raise ValueError("Harvey max_retries must be a non-negative integer")
        self.experiment = experiment
        self.runtime_root = runtime_root
        self.uv_executable = uv_executable
        self.max_concurrency = max_concurrency
        self.max_retries = max_retries
        self._podman_lock = threading.Lock()
        self._podman_environment: dict[str, str] | None = None

    def evaluate(
        self,
        candidate_id: str,
        harness: Path,
        task_files: dict[str, Path],
        destination: Path,
    ) -> CandidateEvaluation:
        validate_regular_tree(harness, "candidate harness")
        if os.path.lexists(destination):
            raise FileExistsError(f"candidate evaluation exists: {destination}")
        stage = self._open_stage(destination)
        scores: dict[str, dict[str, object]] = {}
        with tempfile.TemporaryDirectory(
            prefix="rubric-gen-harvey-",
            dir=ensure_runtime_root(self.runtime_root),
        ) as temporary:
            runtime = Path(temporary)
            self._materialize_runtime(runtime, harness, task_files)

            def evaluate_task(task_id: str) -> tuple[str, dict[str, object]]:
                task_destination = stage / "tasks" / task_id
                task_destination.mkdir(parents=True, exist_ok=True)
                agent_result = task_destination / "agent-result"
                completed = self._completed_result_score(
                    task_destination / "result",
                    task_id,
                )
                if completed is not None:
                    if os.path.lexists(agent_result):
                        self._remove_owned_tree(agent_result)
                    return task_id, completed
                run_id = candidate_id + "--" + task_id.replace("/", "--")
                runtime_result = runtime / "results" / run_id
                if os.path.lexists(agent_result):
                    self._validate_agent_result(agent_result, task_id)
                    copy_regular_tree(agent_result, runtime_result)
                    self._make_tree_writable(runtime_result)
                else:
                    self._run_task(
                        runtime,
                        task_id,
                        run_id,
                        task_destination / "agent.log",
                    )
                    self._validate_agent_result(runtime_result, task_id)
                    self._publish_tree(runtime_result, agent_result)
                self._score_task(runtime, task_id, run_id, task_destination / "judge.log")
                copied_result = task_destination / "result"
                self._publish_tree(runtime_result, copied_result)
                score = read_json_object(copied_result / "scores.json", "Harvey score")
                aggregate_scores(candidate_id, {task_id: score})
                self._remove_owned_tree(agent_result)
                return task_id, score

            with TerminalProgress(
                total=len(task_files),
                description=f"Harvey {candidate_id} evaluation",
                unit="task",
            ) as progress:
                workers = min(self.max_concurrency, len(task_files))
                for task_id, score in _bounded_map(
                    task_files,
                    evaluate_task,
                    workers,
                ):
                    progress.set_status(task_id)
                    scores[task_id] = score
                    progress.update()
            validate_checkout(
                self.experiment.benchmark.checkout,
                self.experiment.benchmark.revision,
                (
                    *self.experiment.benchmark.development_tasks,
                    *self.experiment.benchmark.held_out_tasks,
                ),
            )
        evaluation = aggregate_scores(candidate_id, scores)
        (stage / "summary.json").write_text(
            json.dumps(
                {
                    "kind": "harvey-candidate-evaluation",
                    "candidate_id": candidate_id,
                    "mean_criterion_pass": evaluation.mean_criterion_pass,
                    "mean_all_pass": evaluation.mean_all_pass,
                    "tasks": scores,
                },
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        make_tree_read_only(stage)
        os.replace(stage, destination)
        return evaluation

    def rescore(
        self,
        candidate_id: str,
        source_results: dict[str, Path],
        task_files: dict[str, Path],
        destination: Path,
    ) -> CandidateEvaluation:
        if set(source_results) != set(task_files):
            raise ValueError("crossed scoring needs one stored result per active task")
        if os.path.lexists(destination):
            raise FileExistsError(f"crossed evaluation exists: {destination}")
        stage = self._open_stage(destination)
        scores: dict[str, dict[str, object]] = {}
        with tempfile.TemporaryDirectory(
            prefix="rubric-gen-harvey-rescore-",
            dir=ensure_runtime_root(self.runtime_root),
        ) as temporary:
            runtime = Path(temporary)
            self._materialize_runtime(runtime, None, task_files)

            def rescore_task(
                item: tuple[str, Path],
            ) -> tuple[str, dict[str, object]]:
                task_id, source = item
                task_destination = stage / "tasks" / task_id
                task_destination.mkdir(parents=True, exist_ok=True)
                score_path = task_destination / "scores.json"
                if os.path.lexists(score_path):
                    score = read_json_object(score_path, "crossed Harvey score")
                    aggregate_scores(candidate_id, {task_id: score})
                    return task_id, score
                run_id = candidate_id + "--" + task_id.replace("/", "--")
                runtime_result = runtime / "results" / run_id
                runtime_result.parent.mkdir(parents=True, exist_ok=True)
                copy_regular_tree(source, runtime_result)
                self._make_tree_writable(runtime_result)
                self._score_task(runtime, task_id, run_id, task_destination / "judge.log")
                score = read_json_object(runtime_result / "scores.json", "crossed Harvey score")
                aggregate_scores(candidate_id, {task_id: score})
                pending = task_destination / ".scores.json.pending"
                pending.write_text(
                    json.dumps(score, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )
                os.replace(pending, score_path)
                return task_id, score

            with TerminalProgress(
                total=len(source_results),
                description=f"Harvey {candidate_id} rescore",
                unit="task",
            ) as progress:
                workers = min(self.max_concurrency, len(source_results))
                for task_id, score in _bounded_map(
                    source_results.items(),
                    rescore_task,
                    workers,
                ):
                    progress.set_status(task_id)
                    scores[task_id] = score
                    progress.update()
        evaluation = aggregate_scores(candidate_id, scores)
        (stage / "summary.json").write_text(
            json.dumps(
                {
                    "kind": "harvey-crossed-evaluation",
                    "candidate_id": candidate_id,
                    "mean_criterion_pass": evaluation.mean_criterion_pass,
                    "mean_all_pass": evaluation.mean_all_pass,
                    "tasks": scores,
                },
                indent=2,
                sort_keys=True,
                ensure_ascii=False,
            )
            + "\n",
            encoding="utf-8",
        )
        make_tree_read_only(stage)
        os.replace(stage, destination)
        return evaluation

    def _open_stage(self, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        index = 1
        latest: Path | None = None
        while True:
            stage = destination.parent / f".{destination.name}.attempt-{index:03d}"
            if not os.path.lexists(stage):
                break
            validate_regular_tree(stage, "partial Harvey evaluation")
            latest = stage
            index += 1
        if latest is not None:
            self._make_tree_writable(latest)
            return latest
        stage.mkdir()
        return stage

    @staticmethod
    def _completed_result_score(
        result: Path,
        task_id: str,
    ) -> dict[str, object] | None:
        if not os.path.lexists(result):
            return None
        validate_regular_tree(result, f"completed Harvey result for {task_id}")
        read_json_object(result / "metrics.json", "Harvey metrics")
        transcript = result / "transcript.jsonl"
        if transcript.is_symlink() or not transcript.is_file():
            raise ValueError(f"Harvey result lacks a regular transcript: {result}")
        score = read_json_object(result / "scores.json", "Harvey score")
        aggregate_scores("checkpoint", {task_id: score})
        return score

    @staticmethod
    def _validate_agent_result(result: Path, task_id: str) -> None:
        validate_regular_tree(result, f"Harvey agent result for {task_id}")
        read_json_object(result / "metrics.json", "Harvey metrics")
        transcript = result / "transcript.jsonl"
        if transcript.is_symlink() or not transcript.is_file():
            raise ValueError(f"Harvey agent result lacks a regular transcript: {result}")

    @classmethod
    def _publish_tree(cls, source: Path, destination: Path) -> None:
        pending = destination.with_name(f".{destination.name}.pending")
        if os.path.lexists(pending):
            cls._remove_owned_tree(pending)
        copy_regular_tree(source, pending)
        os.replace(pending, destination)

    @classmethod
    def _remove_owned_tree(cls, path: Path) -> None:
        validate_regular_tree(path, "owned Harvey checkpoint")
        cls._make_tree_writable(path)
        shutil.rmtree(path)

    @staticmethod
    def _make_tree_writable(root: Path) -> None:
        for path in root.rglob("*"):
            path.chmod(path.stat().st_mode | 0o700)
        root.chmod(root.stat().st_mode | 0o700)

    def _materialize_runtime(
        self,
        runtime: Path,
        harness: Path | None,
        task_files: dict[str, Path],
    ) -> None:
        checkout = self.experiment.benchmark.checkout
        for name in ("evaluation", "sandbox", "utils"):
            copy_regular_tree(checkout / name, runtime / name)
        if harness is not None:
            copy_regular_tree(harness, runtime / "harness")
        for task_id, active_file in task_files.items():
            source_dir = task_path(checkout / "tasks", task_id)
            destination_dir = task_path(runtime / "tasks", task_id)
            destination_dir.parent.mkdir(parents=True, exist_ok=True)
            copy_regular_tree(source_dir, destination_dir)
            active = validate_task(active_file)
            source = validate_task(source_dir / "task.json")
            docs_relative = source.get("docs_dir", "documents")
            if type(docs_relative) is not str or not docs_relative:
                raise ValueError(f"task {task_id} has an invalid docs_dir")
            source_docs = (source_dir / docs_relative).resolve()
            if not source_docs.is_dir():
                raise ValueError(f"task {task_id} documents do not exist: {source_docs}")
            try:
                source_docs.relative_to(source_dir.resolve())
            except ValueError:
                local_docs = destination_dir / "documents"
                if local_docs.exists():
                    shutil.rmtree(local_docs)
                copy_regular_tree(source_docs, local_docs)
                active = {**active, "docs_dir": "documents"}
            (destination_dir / "task.json").write_text(
                json.dumps(active, indent=2, ensure_ascii=False) + "\n",
                encoding="utf-8",
            )

    def _run_task(self, runtime: Path, task_id: str, run_id: str, log: Path) -> None:
        config = self.experiment.task_agent
        command = [
            self.uv_executable,
            "run",
            "--project",
            str(self.experiment.benchmark.checkout),
            "python",
            "-m",
            "harness.run",
            "--model",
            config.model,
            "--task",
            task_id,
            "--run-id",
            run_id,
            "--max-turns",
            str(config.max_turns),
            "--temperature",
            str(config.temperature),
            "--shell-timeout",
            str(config.shell_timeout),
            "--sandbox-image",
            config.sandbox_image,
        ]
        if config.reasoning_effort is not None:
            command.extend(["--reasoning-effort", config.reasoning_effort])
        runtime_result = runtime / "results" / run_id

        def reset_result() -> None:
            if os.path.lexists(runtime_result):
                self._remove_owned_tree(runtime_result)

        self._execute_with_retries(
            command,
            runtime,
            log,
            config.credential_env,
            "task agent",
            operation=f"task agent for {task_id}",
            transient_errors=_TRANSIENT_TASK_AGENT_ERRORS,
            before_retry=reset_result,
        )

    def _score_task(self, runtime: Path, task_id: str, run_id: str, log: Path) -> None:
        config = self.experiment.judge
        command = [
            self.uv_executable,
            "run",
            "--project",
            str(self.experiment.benchmark.checkout),
            "python",
            "-m",
            "evaluation.run_eval",
            "--run-id",
            run_id,
            "--task",
            task_id,
            "--judge-model",
            config.model,
            "--parallel",
            str(config.parallel),
        ]
        score_path = runtime / "results" / run_id / "scores.json"

        def clear_score() -> None:
            if os.path.lexists(score_path):
                if score_path.is_symlink() or not score_path.is_file():
                    raise ValueError(
                        f"Harvey score output is not a regular file: {score_path}"
                    )
                score_path.unlink()

        clear_score()
        self._execute_with_retries(
            command,
            runtime,
            log,
            config.credential_env,
            "Harvey judge",
            operation=f"judge for {task_id}",
            transient_errors=_TRANSIENT_JUDGE_ERRORS,
            before_retry=clear_score,
        )

    def _execute_with_retries(
        self,
        command: list[str],
        runtime: Path,
        log: Path,
        credential_names: tuple[str, ...],
        label: str,
        *,
        operation: str,
        transient_errors: tuple[str, ...],
        before_retry: Callable[[], None] | None = None,
    ) -> None:
        for attempt in range(self.max_retries + 1):
            self._archive_log(log)
            try:
                self._execute(command, runtime, log, credential_names, label)
                return
            except RuntimeError:
                if (
                    attempt == self.max_retries
                    or not self._is_transient_failure(log, transient_errors)
                ):
                    raise
                if before_retry is not None:
                    before_retry()
                print(
                    f"Retrying Harvey {operation} after a transient failure "
                    f"({attempt + 1}/{self.max_retries})",
                    flush=True,
                )

    @staticmethod
    def _is_transient_failure(log: Path, messages: tuple[str, ...]) -> bool:
        try:
            output = log.read_text(encoding="utf-8", errors="replace").casefold()
        except OSError:
            return False
        return any(message in output for message in messages)

    @staticmethod
    def _archive_log(log: Path) -> None:
        if not log.exists():
            return
        index = 1
        while True:
            archived = log.with_name(f"{log.stem}.failed-{index:03d}{log.suffix}")
            if not archived.exists():
                os.replace(log, archived)
                return
            index += 1

    def _execute(
        self,
        command: list[str],
        runtime: Path,
        log: Path,
        credential_names: tuple[str, ...],
        label: str,
    ) -> None:
        missing = [name for name in credential_names if not os.environ.get(name)]
        if missing:
            raise RuntimeError(f"{label} credentials are not set: {', '.join(missing)}")
        allowed = {
            "PATH", "LANG", "LANGUAGE", "LC_ALL", "SSL_CERT_FILE", "SSL_CERT_DIR",
            "NODE_EXTRA_CA_CERTS", "HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "ALL_PROXY",
            "UV_CACHE_DIR",
        }
        environment = {name: value for name, value in os.environ.items() if name in allowed}
        environment["TMPDIR"] = str(
            ensure_runtime_directory(self.runtime_root, "tmp")
        )
        environment.update({name: os.environ[name] for name in credential_names})
        if label == "task agent":
            self._execute_task_agent(command, runtime, log, environment)
            return
        self._run_command(command, runtime, log, environment, label)

    def _execute_task_agent(
        self,
        command: list[str],
        runtime: Path,
        log: Path,
        environment: dict[str, str],
    ) -> None:
        image = self.experiment.task_agent.sandbox_image
        cache_root = self.experiment.cache_dir / self.experiment.benchmark.revision
        with self._podman_lock:
            if self._podman_environment is None:
                configured = configured_podman_environment(
                    environment,
                    cache_root=cache_root,
                    runtime_root=self.runtime_root,
                )
                if restore_cached_image(
                    configured,
                    cache_root=cache_root,
                    image=image,
                ):
                    cache_image(configured, cache_root=cache_root, image=image)
                    self._podman_environment = configured
                else:
                    self._run_command(
                        command,
                        runtime,
                        log,
                        configured,
                        "task agent",
                    )
                    cache_image(configured, cache_root=cache_root, image=image)
                    self._podman_environment = configured
                    return
            task_environment = dict(self._podman_environment)
        self._run_command(
            command,
            runtime,
            log,
            task_environment,
            "task agent",
        )

    @staticmethod
    def _run_command(
        command: list[str],
        runtime: Path,
        log: Path,
        environment: dict[str, str],
        label: str,
    ) -> None:
        environment["PWD"] = str(runtime)
        log.parent.mkdir(parents=True, exist_ok=True)
        with log.open("w", encoding="utf-8") as stream:
            result = subprocess.run(
                command,
                cwd=runtime,
                env=environment,
                stdin=subprocess.DEVNULL,
                stdout=stream,
                stderr=subprocess.STDOUT,
                text=True,
            )
        if result.returncode != 0:
            raise RuntimeError(f"{label} failed with exit code {result.returncode}; see {log}")
