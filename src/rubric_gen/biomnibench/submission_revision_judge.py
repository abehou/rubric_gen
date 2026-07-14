"""Frozen-rubric judge adapter for immutable submission snapshots."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from rubric_gen.biomnibench.judges import (
    BiomniBenchJudgeRunner,
    JudgeAttempt,
    JudgeRunConfig,
    JudgeTarget,
)
from rubric_gen.biomnibench.common import MAX_TRANSIENT_RETRIES
from rubric_gen.biomnibench.rubric_scoring import RUBRIC_SCORER_VERSION
from rubric_gen.biomnibench.submission_revision_artifacts import (
    make_tree_read_only,
    prepare_evaluation_run,
    read_json_object,
    remove_owned_evaluation_tree,
    sha256_file,
    sha256_text,
    tree_sha256,
    write_json,
)
from rubric_gen.biomnibench.rubric_bundles import resolve_rubric_bundle


SCORING_IDENTITY_KEYS = (
    "scorer_version",
    "judge_source_sha256",
    "judge_runner_sha256",
    "scorer_module_sha256",
    "effective_judge_model",
    "review_mode",
    "max_review_chars",
    "rubric_source",
    "rubric_set_id",
    "rubric_id",
    "structured_rubric_sha256",
    "rendered_rubric_sha256",
    "manifest_sha256",
)


@dataclass(frozen=True)
class JudgeArtifacts:
    score_validation_path: Path
    evaluation_path: Path


class SubmissionJudge(Protocol):
    def scoring_identity(self) -> dict[str, object]: ...

    def evaluate(self, submission_dir: Path, attempt_id: str) -> JudgeArtifacts: ...

    def validate(self, submission_dir: Path, attempt_id: str) -> JudgeArtifacts: ...


@dataclass(frozen=True)
class SubmissionJudgeConfig:
    task_dir: Path
    experiment_dir: Path
    review: str
    judge_model: str | None
    rubric_name: str | None
    rubric_set: Path | None
    max_review_chars: int | None
    max_retries: int = MAX_TRANSIENT_RETRIES

    def __post_init__(self) -> None:
        if (
            type(self.max_retries) is not int
            or not 0 <= self.max_retries <= MAX_TRANSIENT_RETRIES
        ):
            raise ValueError(
                f"max_retries must be between 0 and {MAX_TRANSIENT_RETRIES}"
            )


@dataclass(frozen=True)
class FrozenRubric:
    text: str
    sha256: str
    source: str
    rubric_set_id: str | None
    rubric_id: str | None
    structured_rubric_sha256: str | None
    manifest_sha256: str | None


class BiomniSubmissionJudge:
    """Run the existing task judge against one immutable submission snapshot."""

    def __init__(self, config: SubmissionJudgeConfig, rubric: FrozenRubric) -> None:
        self.config = config
        self.rubric = rubric
        self.experiment_dir = Path(config.experiment_dir).resolve()
        self.task_dir = Path(config.task_dir).resolve()
        self.rubric_set = (
            Path(config.rubric_set).resolve() if config.rubric_set is not None else None
        )

    def scoring_identity(self) -> dict[str, object]:
        runner = self._runner(self.experiment_dir, resume=False)
        judge_path = runner.find_judge(self.task_dir)
        return {
            "scorer_version": RUBRIC_SCORER_VERSION,
            "judge_source_sha256": sha256_file(judge_path),
            "judge_runner_sha256": runner.judge_runner_sha256(),
            "scorer_module_sha256": runner.scorer_module_sha256(),
            "effective_judge_model": runner.judge_model(os.environ.copy()),
            "review_mode": self.config.review,
            "max_review_chars": self.config.max_review_chars,
            "rubric_source": self.rubric.source,
            "rubric_set_id": self.rubric.rubric_set_id,
            "rubric_id": self.rubric.rubric_id,
            "structured_rubric_sha256": self.rubric.structured_rubric_sha256,
            "rendered_rubric_sha256": self.rubric.sha256,
            "manifest_sha256": self.rubric.manifest_sha256,
        }

    def evaluate(self, submission_dir: Path, attempt_id: str) -> JudgeArtifacts:
        evaluation_root = self._evaluation_root(submission_dir, attempt_id)
        if os.path.lexists(evaluation_root):
            try:
                artifacts = self.validate(submission_dir, attempt_id)
                make_tree_read_only(evaluation_root)
                return artifacts
            except (OSError, RuntimeError, SystemExit, ValueError):
                remove_owned_evaluation_tree(
                    evaluation_root,
                    self.experiment_dir / "evaluations",
                )
        run_dir = prepare_evaluation_run(submission_dir, evaluation_root)
        runner, target = self._runner_and_target(run_dir)
        record: dict[str, object] = {}
        max_attempts = self.config.max_retries + 1
        for attempt_index in range(1, max_attempts + 1):
            record = runner.review_target(target)
            if record.get("status") == "completed" and type(record.get("score")) is int:
                break
            self._archive_failed_attempt(
                runner,
                target,
                evaluation_root,
                attempt_index,
                record,
            )
        else:
            details = [
                f"status={record.get('status')}",
                f"exit_code={record.get('exit_code')}",
            ]
            if record.get("validation_error"):
                details.append(f"validation_error={record['validation_error']}")
            details.append(f"stdout={record.get('stdout')}")
            raise RuntimeError(
                f"optimizer judge failed after {max_attempts} attempts: "
                + ", ".join(details)
            )
        artifacts = self._validated_cached_artifacts(
            runner,
            target,
            evaluation_root,
            submission_dir,
        )
        make_tree_read_only(evaluation_root)
        return artifacts

    def _archive_failed_attempt(
        self,
        runner: BiomniBenchJudgeRunner,
        target: JudgeTarget,
        evaluation_root: Path,
        attempt_index: int,
        record: dict[str, object],
    ) -> None:
        archive = evaluation_root / "judge-attempts" / f"attempt-{attempt_index:03d}"
        archive.mkdir(parents=True)
        output_dir = runner.output_dir(target)
        if output_dir.is_dir():
            for source in output_dir.iterdir():
                if source.is_file() and not source.is_symlink():
                    shutil.copy2(source, archive / source.name)
        write_json(archive / "record.json", record)

    def validate(self, submission_dir: Path, attempt_id: str) -> JudgeArtifacts:
        evaluation_root = self._evaluation_root(submission_dir, attempt_id)
        run_dir = evaluation_root / "run"
        if (
            evaluation_root.is_symlink()
            or run_dir.is_symlink()
            or not evaluation_root.is_dir()
            or not run_dir.is_dir()
        ):
            raise RuntimeError(f"invalid optimizer evaluation: {evaluation_root}")
        runner, target = self._runner_and_target(run_dir)
        return self._validated_cached_artifacts(
            runner,
            target,
            evaluation_root,
            submission_dir,
        )

    def _evaluation_root(self, submission_dir: Path, attempt_id: str) -> Path:
        if (
            type(attempt_id) is not str
            or len(attempt_id) != 32
            or any(character not in "0123456789abcdef" for character in attempt_id)
        ):
            raise ValueError("judge attempt ID must be 128-bit lowercase hex")
        return (
            self.experiment_dir
            / "evaluations"
            / submission_dir.name
            / self.rubric.sha256
            / attempt_id
        )

    def _runner(self, run_dir: Path, *, resume: bool) -> BiomniBenchJudgeRunner:
        return BiomniBenchJudgeRunner(
            JudgeRunConfig(
                run_dir=run_dir,
                tasks_dir=self.task_dir.parent,
                review=self.config.review,
                model=self.config.judge_model,
                rubric_name=self.config.rubric_name,
                rubric_set=self.rubric_set,
                max_review_chars=self.config.max_review_chars,
                resume=resume,
            )
        )

    def _runner_and_target(
        self,
        run_dir: Path,
    ) -> tuple[BiomniBenchJudgeRunner, JudgeTarget]:
        runner = self._runner(run_dir, resume=True)
        targets = runner.discover_targets()
        if len(targets) != 1:
            raise RuntimeError("submission judge did not resolve exactly one task")
        target = targets[0]
        resolved = runner.resolve_rubric(target)
        if sha256_text(resolved.text) != self.rubric.sha256:
            raise RuntimeError("optimizer rubric changed during the revision loop")
        return runner, target

    def _validated_cached_artifacts(
        self,
        runner: BiomniBenchJudgeRunner,
        target: JudgeTarget,
        evaluation_root: Path,
        submission_dir: Path,
    ) -> JudgeArtifacts:
        run_dir = evaluation_root / "run"
        if tree_sha256(run_dir / "workspace") != tree_sha256(
            submission_dir / "workspace"
        ):
            raise RuntimeError("optimizer evaluation workspace changed")
        if sha256_file(run_dir / "trajectory.stream.jsonl") != sha256_file(
            submission_dir / "trajectory.stream.jsonl"
        ):
            raise RuntimeError("optimizer evaluation trajectory changed")
        output_dir = runner.output_dir(target)
        completed = runner.completed_record(JudgeAttempt(target, 1))
        if completed is None:
            raise RuntimeError(
                f"invalid cached optimizer evaluation: {evaluation_root}"
            )
        validation = read_json_object(
            output_dir / "score_validation.json",
            "optimizer score validation",
        )
        if validation.get("rendered_rubric_sha256") != self.rubric.sha256:
            raise RuntimeError("optimizer score does not attest the frozen rubric")
        if validation.get("task") != self.task_dir.name:
            raise RuntimeError("optimizer score attests a different task")
        if validation.get("review_mode") != self.config.review:
            raise RuntimeError("optimizer score attests a different review mode")
        if validation.get("review_input_sha256") != sha256_file(
            output_dir / "judge_input_trace.md"
        ):
            raise RuntimeError("optimizer score does not attest the reviewed trace")
        if validation.get("answer_input_sha256") != sha256_file(
            output_dir / "judge_input_answer.txt"
        ):
            raise RuntimeError("optimizer score does not attest the reviewed answer")
        return JudgeArtifacts(
            score_validation_path=output_dir / "score_validation.json",
            evaluation_path=output_dir / "evaluation.json",
        )


def resolve_optimizer_rubric(config: SubmissionJudgeConfig) -> FrozenRubric:
    task_dir = Path(config.task_dir).resolve()
    if config.rubric_set is not None:
        bundle = resolve_rubric_bundle(Path(config.rubric_set), task_dir.name)
        text = bundle.rendered_text
        source = "rubric-set"
        rubric_set_id = bundle.rubric_set_id
        rubric_id = bundle.rubric_id
        structured_rubric_sha256 = bundle.rubric_sha256
        manifest_sha256 = bundle.task_manifest_sha256
    else:
        name = config.rubric_name or "rubric.txt"
        if Path(name).name != name:
            raise ValueError("rubric_name must be a filename under task tests")
        path = task_dir / "tests" / name
        if path.is_symlink() or not path.is_file():
            raise FileNotFoundError(f"optimizer rubric does not exist: {path}")
        text = path.read_text(encoding="utf-8")
        source = "task-local"
        rubric_set_id = None
        rubric_id = None
        structured_rubric_sha256 = None
        manifest_sha256 = None
    if not text.strip():
        raise ValueError("optimizer rubric is empty")
    return FrozenRubric(
        text=text,
        sha256=sha256_text(text),
        source=source,
        rubric_set_id=rubric_set_id,
        rubric_id=rubric_id,
        structured_rubric_sha256=structured_rubric_sha256,
        manifest_sha256=manifest_sha256,
    )
