"""Judge subprocess execution and validated score attestation."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rubric_gen.biomnibench.rubrics.schema import canonical_json, load_json_strict
from rubric_gen.biomnibench.utils.hashing import sha256_file, sha256_text

from .artifacts import (
    JudgeArtifactStore,
    OpenOutputDirectory,
    TargetDirectoryIdentities,
)
from .models import (
    DEFAULT_JUDGE_MODEL,
    SCORE_INPUT_ATTESTATION_KEYS,
    SCORE_VALIDATION_KEYS,
    SCORE_VALIDATION_SCHEMA_VERSION,
    JudgeAttempt,
    JudgeRunConfig,
    JudgeTarget,
    ResolvedRubric,
)
from .scoring import (
    JudgeScoreValidationError,
    RUBRIC_SCORER_VERSION,
    parse_rubric_levels_strict,
    validate_judge_score,
)


class JudgeExecutor:
    """Execute one task judge and validate the exact produced score artifacts."""

    def __init__(
        self,
        config: JudgeRunConfig,
        artifacts: JudgeArtifactStore,
        *,
        validate_target: Callable[[JudgeTarget], None],
        target_identities: Callable[[JudgeTarget], TargetDirectoryIdentities],
        resolve_local_rubric: Callable[[Path], ResolvedRubric],
        judge_runner_sha256: Callable[[], str] | None = None,
        scorer_module_sha256: Callable[[], str] | None = None,
    ) -> None:
        self.config = config
        self.artifacts = artifacts
        self.validate_target = validate_target
        self.target_identities = target_identities
        self.resolve_local_rubric = resolve_local_rubric
        self._judge_runner_sha256 = judge_runner_sha256 or self.judge_runner_sha256
        self._scorer_module_sha256 = (
            scorer_module_sha256 or self.scorer_module_sha256
        )

    def execute_with_output(
        self,
        judge_path: Path,
        rubric: ResolvedRubric | Path,
        output: OpenOutputDirectory,
        review_text: str,
        answer_text: str,
        *,
        attempt: JudgeAttempt,
    ) -> dict[str, Any]:
        self.validate_target(attempt.target)
        self.artifacts.validate_output_directory(output)
        if isinstance(rubric, Path):
            rubric = self.resolve_local_rubric(rubric)
        if judge_path.is_symlink() or not judge_path.is_file():
            raise SystemExit(f"Judge path must be a regular file: {judge_path}")
        judge_source = judge_path.read_bytes()
        env = os.environ.copy()
        effective_judge_model = self.judge_model(env)
        score_input_attestation = self.score_input_attestation(
            attempt=attempt,
            judge_source=judge_source,
            review_text=review_text,
            answer_text=answer_text,
            effective_judge_model=effective_judge_model,
        )
        output_dir = output.path
        reward_path = output_dir / "reward.json"
        evaluation_path = output_dir / "evaluation.json"
        score_validation_path = output_dir / "score_validation.json"
        stdout_path = output_dir / "stdout.txt"
        for stale_name in (
            "reward.json",
            "evaluation.json",
            "score_validation.json",
            "stdout.txt",
        ):
            self.artifacts.unlink_output_file(output, stale_name)

        artifact_snapshots: dict[str, bytes] = {}
        with tempfile.TemporaryDirectory(prefix="biomnibench-judge-") as tmp:
            tmp_dir = Path(tmp)
            tests_dir = tmp_dir / "tests"
            logs_dir = tmp_dir / "logs" / "verifier"
            tests_dir.mkdir(parents=True)
            logs_dir.mkdir(parents=True)
            (tests_dir / "rubric.txt").write_bytes(rubric.text.encode("utf-8"))
            (logs_dir / "trace.md").write_text(review_text)
            (logs_dir / "answer.txt").write_text(answer_text)

            rewritten_judge = tmp_dir / judge_path.name
            rewritten_judge.write_text(
                self.rewrite_judge_paths(
                    judge_source.decode("utf-8"), tests_dir, logs_dir
                )
            )
            env["MODEL_NAME"] = effective_judge_model
            proc = subprocess.run(
                ["uv", "run", str(rewritten_judge)],
                cwd=tmp_dir,
                env=env,
                text=True,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                check=False,
            )
            self.artifacts.write_output_text(output, "stdout.txt", proc.stdout)
            for filename in ("reward.json", "evaluation.json"):
                source = logs_dir / filename
                if source.is_file():
                    artifact_snapshots[filename] = source.read_bytes()
                    self.artifacts.write_output_bytes(
                        output, filename, artifact_snapshots[filename]
                    )

        result = {
            "status": "failed",
            "exit_code": proc.returncode,
            "judge_exit_code": proc.returncode,
            "score": None,
            "reward": str(reward_path),
            "evaluation": str(evaluation_path),
            "stdout": str(stdout_path),
            "score_validation": str(score_validation_path),
        }
        if proc.returncode != 0:
            return result

        try:
            if "reward.json" not in artifact_snapshots:
                raise JudgeScoreValidationError("judge did not produce reward.json")
            if "evaluation.json" not in artifact_snapshots:
                raise JudgeScoreValidationError("judge did not produce evaluation.json")
            validation = self.build_score_validation_from_bytes(
                rubric,
                artifact_snapshots["reward.json"],
                artifact_snapshots["evaluation.json"],
                score_input_attestation,
            )
        except (OSError, UnicodeError, ValueError, JudgeScoreValidationError) as exc:
            return {**result, "exit_code": 2, "validation_error": str(exc)}
        self.artifacts.write_output_text(
            output,
            "score_validation.json",
            json.dumps(validation, indent=2) + "\n",
        )
        return {
            **result,
            "status": "completed",
            "exit_code": 0,
            "score": validation["score"],
        }

    def build_score_validation(
        self,
        rubric: ResolvedRubric,
        reward_path: Path,
        evaluation_path: Path,
        score_input_attestation: dict[str, Any],
    ) -> dict[str, Any]:
        return self.build_score_validation_from_bytes(
            rubric,
            reward_path.read_bytes(),
            evaluation_path.read_bytes(),
            score_input_attestation,
        )

    def build_score_validation_from_bytes(
        self,
        rubric: ResolvedRubric,
        reward_raw: bytes,
        evaluation_raw: bytes,
        score_input_attestation: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            type(score_input_attestation) is not dict
            or set(score_input_attestation) != SCORE_INPUT_ATTESTATION_KEYS
        ):
            raise JudgeScoreValidationError("score input attestation is not exact")
        reward = load_json_strict(reward_raw.decode("utf-8"))
        evaluation = load_json_strict(evaluation_raw.decode("utf-8"))
        validated = validate_judge_score(
            rubric_levels=parse_rubric_levels_strict(rubric.text),
            evaluation=evaluation,
            reward=reward,
        )
        return {
            **score_input_attestation,
            "score": validated.score,
            "raw_score": validated.raw_score,
            "reported_score": validated.reported_score,
            "score_matches_reported": validated.score_matches_reported,
            "selected_levels": validated.selected_levels,
            "criterion_scores": validated.criterion_scores,
            "rubric_source": rubric.source,
            "rubric_set_id": rubric.rubric_set_id,
            "rubric_id": rubric.rubric_id,
            "structured_rubric_sha256": rubric.structured_rubric_sha256,
            "rendered_rubric_sha256": rubric.rendered_rubric_sha256,
            "manifest_sha256": rubric.manifest_sha256,
            "reward_sha256": hashlib.sha256(reward_raw).hexdigest(),
            "evaluation_sha256": hashlib.sha256(evaluation_raw).hexdigest(),
        }

    def valid_score_validation(
        self,
        rubric: ResolvedRubric,
        score_input_attestation: dict[str, Any],
        *,
        output: OpenOutputDirectory,
    ) -> dict[str, Any] | None:
        try:
            validation = load_json_strict(
                self.artifacts.read_output_bytes(
                    output, "score_validation.json"
                ).decode("utf-8")
            )
            if type(validation) is not dict or set(validation) != SCORE_VALIDATION_KEYS:
                return None
            expected_validation = self.build_score_validation_from_bytes(
                rubric,
                self.artifacts.read_output_bytes(output, "reward.json"),
                self.artifacts.read_output_bytes(output, "evaluation.json"),
                score_input_attestation,
            )
            if canonical_json(validation) != canonical_json(expected_validation):
                return None
        except (OSError, UnicodeError, ValueError, JudgeScoreValidationError):
            return None
        return validation

    def score_input_attestation(
        self,
        *,
        attempt: JudgeAttempt,
        judge_source: bytes,
        review_text: str,
        answer_text: str,
        effective_judge_model: str,
    ) -> dict[str, Any]:
        self.validate_target(attempt.target)
        identities = self.target_identities(attempt.target)
        if type(attempt.repeat_index) is not int or attempt.repeat_index < 1:
            raise JudgeScoreValidationError("repeat_index must be a positive integer")
        return {
            "schema_version": SCORE_VALIDATION_SCHEMA_VERSION,
            "scorer_version": RUBRIC_SCORER_VERSION,
            "review_input_sha256": sha256_text(review_text),
            "answer_input_sha256": sha256_text(answer_text),
            "judge_source_sha256": hashlib.sha256(judge_source).hexdigest(),
            "judge_runner_sha256": self._judge_runner_sha256(),
            "scorer_module_sha256": self._scorer_module_sha256(),
            "effective_judge_model": effective_judge_model,
            "review_mode": self.config.review,
            "max_review_chars": self.config.max_review_chars,
            "task": attempt.target.task,
            "run_identity": identities.canonical_run,
            "repeat_index": attempt.repeat_index,
        }

    @staticmethod
    def judge_runner_sha256() -> str:
        module_dir = Path(__file__).parent
        digest = hashlib.sha256()
        for name in ("artifacts.py", "discovery.py", "executor.py", "runner.py"):
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            digest.update((module_dir / name).read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    @staticmethod
    def scorer_module_sha256() -> str:
        return sha256_file(Path(__file__).with_name("scoring.py"))

    def judge_model(self, env: dict[str, str] | None = None) -> str:
        if self.config.model:
            return self.config.model
        if env is not None and env.get("MODEL_NAME"):
            return env["MODEL_NAME"]
        return DEFAULT_JUDGE_MODEL

    @staticmethod
    def rewrite_judge_paths(text: str, tests_dir: Path, logs_dir: Path) -> str:
        tests = tests_dir.as_posix()
        logs = logs_dir.as_posix()
        return (
            text.replace('"/tests/', f'"{tests}/')
            .replace("'/tests/", f"'{tests}/")
            .replace('"/logs/verifier/', f'"{logs}/')
            .replace("'/logs/verifier/", f"'{logs}/")
        )
