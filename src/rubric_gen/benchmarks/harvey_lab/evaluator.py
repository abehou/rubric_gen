"""Canonical Harvey LAB execution and scoring adapter."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

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

    def __init__(self, experiment: HarveyExperiment, *, uv_executable: str = "uv") -> None:
        self.experiment = experiment
        self.uv_executable = uv_executable

    def evaluate(
        self,
        candidate_id: str,
        harness: Path,
        task_files: dict[str, Path],
        destination: Path,
    ) -> CandidateEvaluation:
        validate_regular_tree(harness, "candidate harness")
        if destination.exists():
            raise FileExistsError(f"candidate evaluation exists: {destination}")
        stage = self._new_stage(destination)
        scores: dict[str, dict[str, object]] = {}
        with tempfile.TemporaryDirectory(prefix="rubric-gen-harvey-") as temporary:
            runtime = Path(temporary)
            self._materialize_runtime(runtime, harness, task_files)
            with TerminalProgress(
                total=len(task_files),
                description=f"Harvey {candidate_id} evaluation",
                unit="task",
            ) as progress:
                for task_id in task_files:
                    progress.set_status(f"agent {task_id}")
                    task_destination = stage / "tasks" / task_id
                    task_destination.mkdir(parents=True)
                    run_id = candidate_id + "--" + task_id.replace("/", "--")
                    self._run_task(runtime, task_id, run_id, task_destination / "agent.log")
                    progress.set_status(f"judge {task_id}")
                    self._score_task(runtime, task_id, run_id, task_destination / "judge.log")
                    result = runtime / "results" / run_id
                    copied_result = task_destination / "result"
                    copy_regular_tree(result, copied_result)
                    score = read_json_object(copied_result / "scores.json", "Harvey score")
                    scores[task_id] = score
                    progress.update()
            validate_checkout(
                self.experiment.benchmark.checkout,
                self.experiment.benchmark.revision,
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
        if destination.exists():
            raise FileExistsError(f"crossed evaluation exists: {destination}")
        stage = self._new_stage(destination)
        scores: dict[str, dict[str, object]] = {}
        with tempfile.TemporaryDirectory(prefix="rubric-gen-harvey-rescore-") as temporary:
            runtime = Path(temporary)
            self._materialize_runtime(runtime, None, task_files)
            with TerminalProgress(
                total=len(source_results),
                description=f"Harvey {candidate_id} rescore",
                unit="task",
            ) as progress:
                for task_id, source in source_results.items():
                    progress.set_status(task_id)
                    run_id = candidate_id + "--" + task_id.replace("/", "--")
                    runtime_result = runtime / "results" / run_id
                    runtime_result.parent.mkdir(parents=True, exist_ok=True)
                    copy_regular_tree(source, runtime_result)
                    self._make_tree_writable(runtime_result)
                    task_destination = stage / "tasks" / task_id
                    task_destination.mkdir(parents=True)
                    self._score_task(runtime, task_id, run_id, task_destination / "judge.log")
                    score = read_json_object(runtime_result / "scores.json", "crossed Harvey score")
                    (task_destination / "scores.json").write_text(
                        json.dumps(score, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
                        encoding="utf-8",
                    )
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

    @staticmethod
    def _new_stage(destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        index = 1
        while True:
            stage = destination.parent / f".{destination.name}.attempt-{index:03d}"
            if not stage.exists():
                stage.mkdir()
                return stage
            index += 1

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
        self._execute(command, runtime, log, config.credential_env, "task agent")

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
        self._execute(command, runtime, log, config.credential_env, "Harvey judge")

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
            "UV_CACHE_DIR", "TMPDIR", "SLURM_TMPDIR",
        }
        environment = {name: value for name, value in os.environ.items() if name in allowed}
        environment.update({name: os.environ[name] for name in credential_names})
        image: str | None = None
        cache_root: Path | None = None
        if label == "task agent":
            image = self.experiment.task_agent.sandbox_image
            cache_root = (
                self.experiment.cache_dir / self.experiment.benchmark.revision
            )
            environment = configured_podman_environment(
                environment,
                cache_root=cache_root,
            )
            restore_cached_image(
                environment,
                cache_root=cache_root,
                image=image,
            )
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
        if image is not None and cache_root is not None:
            cache_image(environment, cache_root=cache_root, image=image)
