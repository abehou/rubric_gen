"""Linear, true-session self-revision of BiomniBench submissions."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from rubric_gen.biomnibench.common import AgentRunConfig, PROMPT, TaskWorkspace
from rubric_gen.biomnibench.judges import BiomniBenchJudgeRunner, JudgeRunConfig
from rubric_gen.biomnibench.session_drivers import (
    CliSolverSessionDriver,
    SolverSessionDriver,
)
from rubric_gen.biomnibench.submission_feedback import (
    FeedbackPolicy,
    project_feedback,
)
from rubric_gen.biomnibench.task_rubric_compiler import resolve_rubric_bundle


_EXCLUDED_SOLUTION_NAMES = frozenset(
    {
        ".git",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".venv",
        "__pycache__",
        "data",
        "instruction.md",
    }
)


@dataclass(frozen=True)
class JudgeArtifacts:
    score_validation_path: Path
    evaluation_path: Path


class SubmissionJudge(Protocol):
    def evaluate(self, submission_dir: Path) -> JudgeArtifacts: ...


@dataclass(frozen=True)
class SubmissionRevisionConfig:
    task_dir: Path
    experiment_dir: Path
    revision_rounds: int
    agent: AgentRunConfig
    feedback_policy: FeedbackPolicy = FeedbackPolicy.FULL
    review: str = "trajectory"
    judge_model: str | None = None
    rubric_name: str | None = None
    rubric_set: Path | None = None
    max_review_chars: int | None = None

    def __post_init__(self) -> None:
        if type(self.revision_rounds) is not int or self.revision_rounds < 0:
            raise ValueError("revision_rounds must be a non-negative integer")
        if self.review not in {"trace", "trajectory"}:
            raise ValueError("review must be trace or trajectory")
        if self.rubric_name is not None and self.rubric_set is not None:
            raise ValueError("rubric_name and rubric_set are mutually exclusive")
        FeedbackPolicy(self.feedback_policy)


@dataclass(frozen=True)
class RevisionDependencies:
    session: SolverSessionDriver
    judge: SubmissionJudge


@dataclass(frozen=True)
class SubmissionRevisionResult:
    experiment_dir: Path
    session_id: str
    submission_ids: tuple[str, ...]
    scores: tuple[int, ...]


@dataclass(frozen=True)
class _FrozenRubric:
    text: str
    sha256: str


class BiomniSubmissionJudge:
    """Run the existing task judge against one immutable submission snapshot."""

    def __init__(self, config: SubmissionRevisionConfig, rubric: _FrozenRubric) -> None:
        self.config = config
        self.rubric = rubric

    def evaluate(self, submission_dir: Path) -> JudgeArtifacts:
        evaluation_root = (
            Path(self.config.experiment_dir).resolve()
            / "evaluations"
            / submission_dir.name
            / self.rubric.sha256
        )
        run_dir = _prepare_evaluation_run(submission_dir, evaluation_root)
        runner = BiomniBenchJudgeRunner(
            JudgeRunConfig(
                run_dir=run_dir,
                tasks_dir=self.config.task_dir.parent,
                review=self.config.review,
                model=self.config.judge_model,
                rubric_name=self.config.rubric_name,
                rubric_set=self.config.rubric_set,
                max_review_chars=self.config.max_review_chars,
                force=True,
            )
        )
        targets = runner.discover_targets()
        if len(targets) != 1:
            raise RuntimeError("submission judge did not resolve exactly one task")
        target = targets[0]
        resolved = runner.resolve_rubric(target)
        if _sha256_text(resolved.text) != self.rubric.sha256:
            raise RuntimeError("optimizer rubric changed during the revision loop")
        record = runner.review_target(target)
        if record.get("status") != "completed" or type(record.get("score")) is not int:
            raise RuntimeError("optimizer judge did not produce a validated score")
        output_dir = runner.output_dir(target)
        validation = _read_json_object(
            output_dir / "score_validation.json",
            "optimizer score validation",
        )
        if validation.get("rendered_rubric_sha256") != self.rubric.sha256:
            raise RuntimeError("optimizer score does not attest the frozen rubric")
        if validation.get("task") != self.config.task_dir.name:
            raise RuntimeError("optimizer score attests a different task")
        if validation.get("review_mode") != self.config.review:
            raise RuntimeError("optimizer score attests a different review mode")
        if validation.get("review_input_sha256") != _sha256_file(
            output_dir / "judge_input_trace.md"
        ):
            raise RuntimeError("optimizer score does not attest the reviewed trace")
        if validation.get("answer_input_sha256") != _sha256_file(
            output_dir / "judge_input_answer.txt"
        ):
            raise RuntimeError("optimizer score does not attest the reviewed answer")
        _make_tree_read_only(evaluation_root)
        return JudgeArtifacts(
            score_validation_path=output_dir / "score_validation.json",
            evaluation_path=output_dir / "evaluation.json",
        )


class SubmissionRevisionController:
    """Run a fixed-length linear revision conversation for one task."""

    def __init__(
        self,
        config: SubmissionRevisionConfig,
        dependencies: RevisionDependencies | None = None,
    ) -> None:
        self.config = config
        self.experiment_dir = Path(config.experiment_dir).resolve()
        self.task_dir = Path(config.task_dir).resolve()
        self.rubric = _resolve_optimizer_rubric(config, self.task_dir)
        self.instruction_sha256 = _sha256_file(self.task_dir / "instruction.md")
        self.data_sha256 = _tree_sha256(self.task_dir / "environment" / "data")
        self.dependencies = dependencies or RevisionDependencies(
            session=CliSolverSessionDriver(config.agent),
            judge=BiomniSubmissionJudge(config, self.rubric),
        )

    def run(self) -> SubmissionRevisionResult:
        if os.path.lexists(self.experiment_dir):
            raise FileExistsError(
                f"experiment directory already exists: {self.experiment_dir}"
            )
        live_root = Path(tempfile.mkdtemp(prefix="biomnibench-revision-live-"))
        workspace = live_root / "workspace"
        try:
            TaskWorkspace(self.task_dir, workspace).validate()
            self._initialize(workspace)

            trajectories: list[Path] = []
            submission_ids: list[str] = []
            scores: list[int] = []
            session_id = ""
            next_prompt = PROMPT

            for turn_index in range(self.config.revision_rounds + 1):
                turn_dir = self.experiment_dir / "turns" / f"turn-{turn_index:03d}"
                turn_dir.mkdir(parents=True)
                (turn_dir / "prompt.txt").write_text(next_prompt)
                if turn_index == 0:
                    turn = self.dependencies.session.start(
                        workspace,
                        next_prompt,
                        turn_dir,
                    )
                    session_id = turn.session_id
                    self._record_session_id(session_id)
                else:
                    turn = self.dependencies.session.resume(
                        workspace,
                        next_prompt,
                        turn_dir,
                        session_id,
                    )
                    if turn.session_id != session_id:
                        raise RuntimeError("solver resumed a different provider session")
                if turn.exit_code != 0:
                    self._append_event(
                        {
                            "event": "turn_failed",
                            "turn": turn_index,
                            "exit_code": turn.exit_code,
                            "session_id": session_id,
                        }
                    )
                    raise RuntimeError(f"solver turn {turn_index} failed")
                self._verify_live_task_inputs(workspace)
                self._validate_submission_outputs(workspace)
                trajectories.append(turn.trajectory_path)
                self._append_event(
                    {
                        "event": "turn_completed",
                        "turn": turn_index,
                        "session_id": session_id,
                        "trajectory_sha256": _sha256_file(turn.trajectory_path),
                    }
                )
                _make_tree_read_only(turn_dir)

                submission_id = f"s{turn_index:03d}"
                submission_dir = self._snapshot_submission(
                    submission_id,
                    workspace,
                    trajectories,
                    session_id,
                )
                submission_ids.append(submission_id)
                _verify_submission_snapshot(submission_dir)
                self._verify_canonical_task_inputs()
                artifacts = self.dependencies.judge.evaluate(submission_dir)
                self._verify_canonical_task_inputs()
                _verify_submission_snapshot(submission_dir)
                feedback = project_feedback(
                    artifacts.score_validation_path,
                    artifacts.evaluation_path,
                    self.rubric.text,
                    self.rubric.sha256,
                    self.config.feedback_policy,
                )
                feedback_path = (
                    self.experiment_dir / "feedback" / f"{submission_id}.json"
                )
                _write_json(feedback_path, feedback.payload)
                _make_read_only(feedback_path)
                scores.append(feedback.score)
                self._append_event(
                    {
                        "event": "submission_judged",
                        "submission_id": submission_id,
                        "turn": turn_index,
                        "score": feedback.score,
                        "feedback_policy": FeedbackPolicy(
                            self.config.feedback_policy
                        ).value,
                        "feedback_sha256": _sha256_file(feedback_path),
                    }
                )
                next_prompt = feedback.prompt

            self._append_event(
                {
                    "event": "experiment_completed",
                    "session_id": session_id,
                    "submission_count": len(submission_ids),
                    "scores": scores,
                }
            )
            return SubmissionRevisionResult(
                experiment_dir=self.experiment_dir,
                session_id=session_id,
                submission_ids=tuple(submission_ids),
                scores=tuple(scores),
            )
        finally:
            if self.experiment_dir.is_dir():
                self._persist_rubric()
            shutil.rmtree(live_root, ignore_errors=True)

    def _initialize(self, workspace: Path) -> None:
        self.experiment_dir.mkdir(parents=True)
        TaskWorkspace(self.task_dir, workspace).prepare()
        _make_read_only(workspace / "instruction.md")
        _make_tree_read_only(workspace / "data")
        _write_json(
            self.experiment_dir / "manifest.json",
            {
                "schema_version": 1,
                "task_id": self.task_dir.name,
                "task_dir": str(self.task_dir),
                "revision_rounds": self.config.revision_rounds,
                "submission_count": self.config.revision_rounds + 1,
                "provider": self.config.agent.provider,
                "model": self.config.agent.model,
                "sandbox_requested": self.config.agent.sandbox,
                "allow_web": self.config.agent.allow_web,
                "approval_mode": self.config.agent.approval_mode,
                "skip_trust": self.config.agent.skip_trust,
                "feedback_policy": FeedbackPolicy(
                    self.config.feedback_policy
                ).value,
                "review": self.config.review,
                "judge_model": self.config.judge_model,
                "max_review_chars": self.config.max_review_chars,
                "rubric_name": self.config.rubric_name,
                "rubric_set": (
                    str(Path(self.config.rubric_set).resolve())
                    if self.config.rubric_set is not None
                    else None
                ),
                "rubric_sha256": self.rubric.sha256,
                "instruction_sha256": self.instruction_sha256,
                "data_sha256": self.data_sha256,
                "session_id": None,
            },
        )

    def _persist_rubric(self) -> None:
        rubric_path = self.experiment_dir / "rubric" / "r0000.txt"
        if rubric_path.is_file():
            return
        rubric_path.parent.mkdir()
        rubric_path.write_text(self.rubric.text)
        _make_read_only(rubric_path)

    def _record_session_id(self, session_id: str) -> None:
        if type(session_id) is not str or not session_id.strip():
            raise RuntimeError("solver did not return a persistent session ID")
        manifest_path = self.experiment_dir / "manifest.json"
        manifest = json.loads(manifest_path.read_text())
        manifest["session_id"] = session_id
        _write_json(manifest_path, manifest)

    def _validate_submission_outputs(self, workspace: Path) -> None:
        missing = [
            name
            for name in ("trace.md", "answer.txt")
            if not (workspace / name).is_file()
            or (workspace / name).stat().st_size == 0
        ]
        if missing:
            raise RuntimeError(
                "solver submission is missing required outputs: " + ", ".join(missing)
            )

    def _verify_live_task_inputs(self, workspace: Path) -> None:
        if _sha256_file(workspace / "instruction.md") != self.instruction_sha256:
            raise RuntimeError("solver modified the task instruction")
        if _tree_sha256(workspace / "data") != self.data_sha256:
            raise RuntimeError("solver modified the canonical task data")

    def _verify_canonical_task_inputs(self) -> None:
        if _sha256_file(self.task_dir / "instruction.md") != self.instruction_sha256:
            raise RuntimeError("canonical task instruction changed during the experiment")
        if _tree_sha256(self.task_dir / "environment" / "data") != self.data_sha256:
            raise RuntimeError("canonical task data changed during the experiment")

    def _snapshot_submission(
        self,
        submission_id: str,
        workspace: Path,
        trajectories: list[Path],
        session_id: str,
    ) -> Path:
        submission_dir = self.experiment_dir / "submissions" / submission_id
        snapshot_workspace = submission_dir / "workspace"
        submission_dir.mkdir(parents=True)
        _copy_solution_workspace(workspace, snapshot_workspace)
        _make_tree_read_only(snapshot_workspace)

        cumulative = submission_dir / "trajectory.stream.jsonl"
        with cumulative.open("wb") as output:
            for trajectory in trajectories:
                raw = trajectory.read_bytes()
                output.write(raw)
                if raw and not raw.endswith(b"\n"):
                    output.write(b"\n")
        status_path = submission_dir / "status.json"
        _write_json(
            status_path,
            {
                "schema_version": 1,
                "task": self.task_dir.name,
                "task_dir": str(self.task_dir),
                "workspace_dir": str(snapshot_workspace),
                "provider": self.config.agent.provider,
                "session_id": session_id,
                "submission_id": submission_id,
                "exit_code": 0,
            },
        )
        workspace_sha256 = _tree_sha256(snapshot_workspace)
        trajectory_sha256 = _sha256_file(cumulative)
        snapshot_path = submission_dir / "snapshot.json"
        _write_json(
            snapshot_path,
            {
                "schema_version": 1,
                "submission_id": submission_id,
                "session_id": session_id,
                "workspace_sha256": workspace_sha256,
                "trajectory_sha256": trajectory_sha256,
            },
        )
        for path in (cumulative, status_path, snapshot_path):
            _make_read_only(path)
        _make_read_only(submission_dir)
        self._append_event(
            {
                "event": "submission_snapshotted",
                "submission_id": submission_id,
                "workspace_sha256": workspace_sha256,
                "trajectory_sha256": trajectory_sha256,
            }
        )
        return submission_dir

    def _append_event(self, payload: dict[str, object]) -> None:
        events = self.experiment_dir / "events.jsonl"
        with events.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())


def run_submission_revision(
    config: SubmissionRevisionConfig,
) -> SubmissionRevisionResult:
    return SubmissionRevisionController(config).run()


def _resolve_optimizer_rubric(
    config: SubmissionRevisionConfig,
    task_dir: Path,
) -> _FrozenRubric:
    if config.rubric_set is not None:
        text = resolve_rubric_bundle(
            Path(config.rubric_set),
            task_dir.name,
        ).rendered_text
    else:
        name = config.rubric_name or "rubric.txt"
        if Path(name).name != name:
            raise ValueError("rubric_name must be a filename under task tests")
        path = task_dir / "tests" / name
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(f"optimizer rubric does not exist: {path}")
        text = path.read_text(encoding="utf-8")
    if not text.strip():
        raise ValueError("optimizer rubric is empty")
    return _FrozenRubric(text=text, sha256=_sha256_text(text))


def _copy_solution_workspace(source: Path, destination: Path) -> None:
    destination.mkdir()
    for child in sorted(source.iterdir(), key=lambda path: path.name):
        if child.name in _EXCLUDED_SOLUTION_NAMES:
            continue
        _copy_solution_entry(child, destination / child.name)


def _prepare_evaluation_run(submission_dir: Path, evaluation_root: Path) -> Path:
    if os.path.lexists(evaluation_root):
        raise FileExistsError(f"evaluation already exists: {evaluation_root}")
    run_dir = evaluation_root / "run"
    workspace = run_dir / "workspace"
    run_dir.mkdir(parents=True)
    _copy_solution_workspace(submission_dir / "workspace", workspace)
    _make_tree_read_only(workspace)
    shutil.copyfile(
        submission_dir / "trajectory.stream.jsonl",
        run_dir / "trajectory.stream.jsonl",
        follow_symlinks=False,
    )
    source_status = _read_json_object(
        submission_dir / "status.json",
        "submission status",
    )
    source_status["workspace_dir"] = str(workspace)
    _write_json(run_dir / "status.json", source_status)
    return run_dir


def _verify_submission_snapshot(submission_dir: Path) -> None:
    snapshot = _read_json_object(submission_dir / "snapshot.json", "submission snapshot")
    if snapshot.get("submission_id") != submission_dir.name:
        raise RuntimeError("submission snapshot has a mismatched identity")
    if snapshot.get("workspace_sha256") != _tree_sha256(
        submission_dir / "workspace"
    ):
        raise RuntimeError("submission workspace changed after snapshotting")
    if snapshot.get("trajectory_sha256") != _sha256_file(
        submission_dir / "trajectory.stream.jsonl"
    ):
        raise RuntimeError("submission trajectory changed after snapshotting")


def _copy_solution_entry(source: Path, destination: Path) -> None:
    source_stat = os.lstat(source)
    if stat.S_ISLNK(source_stat.st_mode):
        raise RuntimeError(f"solution snapshot contains a symlink: {source}")
    if stat.S_ISDIR(source_stat.st_mode):
        if source.name in _EXCLUDED_SOLUTION_NAMES:
            return
        destination.mkdir()
        for child in sorted(source.iterdir(), key=lambda path: path.name):
            if child.name not in _EXCLUDED_SOLUTION_NAMES:
                _copy_solution_entry(child, destination / child.name)
        return
    if not stat.S_ISREG(source_stat.st_mode):
        raise RuntimeError(f"solution snapshot contains a special file: {source}")
    shutil.copyfile(source, destination, follow_symlinks=False)


def _tree_sha256(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        relative = path.relative_to(root).as_posix()
        path_stat = os.lstat(path)
        if stat.S_ISDIR(path_stat.st_mode):
            continue
        if not stat.S_ISREG(path_stat.st_mode):
            raise RuntimeError(f"snapshot contains a non-regular file: {relative}")
        digest.update(relative.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _make_tree_read_only(root: Path) -> None:
    for path in [*root.rglob("*"), root]:
        _make_read_only(path)


def _make_read_only(path: Path) -> None:
    path.chmod(stat.S_IMODE(os.lstat(path).st_mode) & ~0o222)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )


def _read_json_object(path: Path, context: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{context} is not valid JSON: {path}") from exc
    if type(value) is not dict:
        raise RuntimeError(f"{context} must be a JSON object: {path}")
    return value


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
