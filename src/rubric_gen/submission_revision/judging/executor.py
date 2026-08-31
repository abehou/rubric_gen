"""Benchmark-fixed subprocess execution and validated score attestation."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import Any

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.rubrics.schema import canonical_json, load_json_strict

from .artifacts import (
    JudgeArtifactStore,
    OpenOutputDirectory,
    TargetDirectoryIdentities,
)
from .models import (
    DEFAULT_JUDGE_MODEL,
    SCORE_INPUT_ATTESTATION_KEYS,
    SCORE_VALIDATION_KEYS,
    JudgeAttempt,
    JudgeRunConfig,
    JudgeTarget,
    GradingEngine,
    ResolvedRubric,
    grading_engine_for_benchmark,
)
from .full_rubric_protocol import (
    FULL_RUBRIC_ENGINE_IDENTITY,
    FULL_RUBRIC_REQUEST_TIMEOUT_SECONDS,
    FullRubricJudgeError,
    FullRubricRunSpec,
    build_full_rubric_run_spec,
    deterministic_grading_seed,
    records_from_report,
    validate_usage_record as validate_full_rubric_usage_record,
)
from .scoring import (
    JudgeScoreValidationError,
    parse_rubric_levels_strict,
    parse_score_normalization_maximum,
    validate_judge_score,
)


JUDGE_SUBPROCESS_TIMEOUT_SECONDS = int(
    FULL_RUBRIC_REQUEST_TIMEOUT_SECONDS + 60
)


class JudgeExecutor:
    """Execute one fixed judge and attest every score input and output."""

    def __init__(
        self,
        config: JudgeRunConfig,
        artifacts: JudgeArtifactStore,
        *,
        validate_target: Callable[[JudgeTarget], None],
        target_identities: Callable[[JudgeTarget], TargetDirectoryIdentities],
        resolve_local_rubric: Callable[[Path], ResolvedRubric],
        scoring_implementation_sha256: Callable[[], str] | None = None,
    ) -> None:
        self.config = config
        self.artifacts = artifacts
        self.validate_target = validate_target
        self.target_identities = target_identities
        self.resolve_local_rubric = resolve_local_rubric
        self._scoring_implementation_sha256 = (
            scoring_implementation_sha256 or self.scoring_implementation_sha256
        )

    @property
    def grading_engine(self) -> GradingEngine:
        """Return the benchmark-fixed engine. No runtime fallback is allowed."""

        return grading_engine_for_benchmark(self.config.benchmark)

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
        expected_name = "full_rubric_judge.py"
        expected_judge = Path(__file__).with_name(expected_name)
        if judge_path.is_symlink() or not judge_path.is_file():
            raise SystemExit(f"Judge path must be a regular file: {judge_path}")
        try:
            if judge_path.resolve(strict=True) != expected_judge.resolve(strict=True):
                raise SystemExit(
                    "Submission grading requires the benchmark-fixed "
                    f"{self.grading_engine.value} judge: {judge_path}"
                )
        except (OSError, RuntimeError) as exc:
            raise SystemExit(f"Invalid judge path: {judge_path}") from exc
        env = os.environ.copy()
        env["LITELLM_LOCAL_MODEL_COST_MAP"] = "True"
        requested_model = self.judge_model(env)
        # Gemini must use the experiment's canonical credential.
        if requested_model.startswith("gemini"):
            env.pop("GOOGLE_API_KEY", None)
        score_input_attestation = self.score_input_attestation(
            attempt=attempt,
            rubric=rubric,
            review_text=review_text,
            answer_text=answer_text,
            effective_judge_model=requested_model,
        )
        output_dir = output.path
        reward_path = output_dir / "reward.json"
        evaluation_path = output_dir / "evaluation.json"
        usage_path = output_dir / "usage.json"
        score_validation_path = output_dir / "score_validation.json"
        stdout_path = output_dir / "stdout.txt"
        for stale_name in (
            "reward.json",
            "evaluation.json",
            "usage.json",
            "score_validation.json",
            "stdout.txt",
        ):
            self.artifacts.unlink_output_file(output, stale_name)

        artifact_snapshots: dict[str, bytes] = {}
        with tempfile.TemporaryDirectory(prefix="submission-judge-") as tmp:
            tmp_dir = Path(tmp)
            inputs_dir = tmp_dir / "inputs"
            logs_dir = tmp_dir / "logs"
            inputs_dir.mkdir()
            logs_dir.mkdir()
            rubric_path = inputs_dir / "rubric.txt"
            review_path = inputs_dir / "review.txt"
            answer_path = inputs_dir / "answer.txt"
            rubric_path.write_bytes(rubric.text.encode("utf-8"))
            review_path.write_text(review_text, encoding="utf-8")
            answer_path.write_text(answer_text, encoding="utf-8")
            execution = score_input_attestation["engine_execution"]
            assert type(execution) is dict
            command = [
                sys.executable,
                str(judge_path),
                "--rubric",
                str(rubric_path),
                "--review",
                str(review_path),
                "--answer",
                str(answer_path),
                "--output-dir",
                str(logs_dir),
                "--model",
                requested_model,
                "--seed",
                str(execution["engine_seed"]),
            ]
            try:
                proc = subprocess.run(
                    command,
                    cwd=tmp_dir,
                    env=env,
                    text=True,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    check=False,
                    timeout=JUDGE_SUBPROCESS_TIMEOUT_SECONDS,
                )
            except subprocess.TimeoutExpired as exc:
                captured = exc.stdout or ""
                if isinstance(captured, bytes):
                    captured = captured.decode(errors="replace")
                proc = subprocess.CompletedProcess(
                    exc.cmd,
                    124,
                    stdout=(
                        captured
                        + f"\n{self.grading_engine.value} judge exceeded the hard "
                        "subprocess timeout "
                        + f"of {JUDGE_SUBPROCESS_TIMEOUT_SECONDS} seconds\n"
                    ),
                )
            self.artifacts.write_output_text(output, "stdout.txt", proc.stdout)
            for filename in ("reward.json", "evaluation.json", "usage.json"):
                source = logs_dir / filename
                if source.is_file():
                    artifact_snapshots[filename] = source.read_bytes()
                    self.artifacts.write_output_bytes(
                        output,
                        filename,
                        artifact_snapshots[filename],
                    )

        result = {
            "status": "failed",
            "exit_code": proc.returncode,
            "judge_exit_code": proc.returncode,
            "score": None,
            "normalized_score": None,
            "reward": str(reward_path),
            "evaluation": str(evaluation_path),
            "usage": str(usage_path),
            "stdout": str(stdout_path),
            "score_validation": str(score_validation_path),
        }
        if proc.returncode != 0:
            return result

        try:
            for filename in ("reward.json", "evaluation.json", "usage.json"):
                if filename not in artifact_snapshots:
                    raise JudgeScoreValidationError(
                        f"{self.grading_engine.value} judge did not produce {filename}"
                    )
            validation = self.build_score_validation_from_bytes(
                rubric,
                artifact_snapshots["reward.json"],
                artifact_snapshots["evaluation.json"],
                artifact_snapshots["usage.json"],
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
            "normalized_score": validation["normalized_score"],
        }

    def build_score_validation(
        self,
        rubric: ResolvedRubric,
        reward_path: Path,
        evaluation_path: Path,
        usage_path: Path,
        score_input_attestation: dict[str, Any],
    ) -> dict[str, Any]:
        return self.build_score_validation_from_bytes(
            rubric,
            reward_path.read_bytes(),
            evaluation_path.read_bytes(),
            usage_path.read_bytes(),
            score_input_attestation,
        )

    def build_score_validation_from_bytes(
        self,
        rubric: ResolvedRubric,
        reward_raw: bytes,
        evaluation_raw: bytes,
        usage_raw: bytes,
        score_input_attestation: dict[str, Any],
    ) -> dict[str, Any]:
        if (
            type(score_input_attestation) is not dict
            or set(score_input_attestation) != SCORE_INPUT_ATTESTATION_KEYS
        ):
            raise JudgeScoreValidationError("score input attestation is not exact")
        reward = load_json_strict(reward_raw.decode("utf-8"))
        evaluation = load_json_strict(evaluation_raw.decode("utf-8"))
        usage = load_json_strict(usage_raw.decode("utf-8"))
        try:
            engine = GradingEngine(score_input_attestation["grading_engine"])
        except (TypeError, ValueError) as exc:
            raise JudgeScoreValidationError("grading engine identity is invalid") from exc
        if engine is not self.grading_engine:
            raise JudgeScoreValidationError(
                "grading engine does not match the benchmark-fixed instrument"
            )
        if score_input_attestation["benchmark"] != self.config.benchmark.value:
            raise JudgeScoreValidationError("score benchmark identity changed")
        execution = score_input_attestation["engine_execution"]
        if type(execution) is not dict:
            raise JudgeScoreValidationError("engine execution attestation is invalid")
        try:
            if type(evaluation) is not dict or set(evaluation) != {
                "total_score",
                "criteria",
                "reasoning",
                "full_rubric_structured",
            }:
                raise JudgeScoreValidationError(
                    "full-rubric structured evaluation record is invalid"
                )
            metadata = evaluation["full_rubric_structured"]
            if type(metadata) is not dict or set(metadata) != {
                "code_identity",
                "execution",
                "raw_report",
            }:
                raise JudgeScoreValidationError(
                    "full-rubric structured metadata is invalid"
                )
            if metadata["code_identity"] != FULL_RUBRIC_ENGINE_IDENTITY:
                raise JudgeScoreValidationError(
                    "full-rubric structured engine identity changed"
                )
            spec = FullRubricRunSpec.from_json(execution)
            if (
                metadata["execution"] != execution
                or spec.requested_model
                != score_input_attestation["effective_judge_model"]
                or spec.rubric_bytes != len(rubric.text.encode("utf-8"))
                or spec.criterion_count
                != len(parse_rubric_levels_strict(rubric.text))
            ):
                raise JudgeScoreValidationError(
                    "full-rubric structured execution contract changed"
                )
            call_usage = usage["call"] if type(usage) is dict else None
            expected_records = records_from_report(
                rubric_text=rubric.text,
                raw_report=metadata["raw_report"],
                spec=spec,
                call_usage=call_usage,
            )
            validate_full_rubric_usage_record(usage, spec)
            rubric_levels = parse_rubric_levels_strict(rubric.text)
            normalization_maximum = parse_score_normalization_maximum(rubric.text)
            converted_score = expected_records.score
            converted_normalized_score = expected_records.normalized_score
            converted_raw_score = expected_records.raw_score
            converted_levels = expected_records.criterion_levels
            converted_criterion_scores = expected_records.criterion_scores
        except (FullRubricJudgeError, TypeError, ValueError, KeyError) as exc:
            raise JudgeScoreValidationError(str(exc)) from exc
        if canonical_json(reward) != canonical_json(expected_records.reward):
            raise JudgeScoreValidationError(
                "reward differs from the authoritative engine report"
            )
        if canonical_json(evaluation) != canonical_json(expected_records.evaluation):
            raise JudgeScoreValidationError(
                "evaluation differs from the authoritative engine report"
            )
        if canonical_json(usage) != canonical_json(expected_records.usage):
            raise JudgeScoreValidationError(
                "usage differs from the authoritative engine report"
            )
        validated = validate_judge_score(
            rubric_levels=rubric_levels,
            evaluation=evaluation,
            reward=reward,
            normalization_maximum=normalization_maximum,
        )
        if (
            validated.score != converted_score
            or validated.normalized_score != converted_normalized_score
            or validated.raw_score != converted_raw_score
            or validated.criterion_levels != converted_levels
            or validated.criterion_scores != converted_criterion_scores
            or not validated.score_matches_reported
        ):
            raise JudgeScoreValidationError(
                "repository score differs from the validated engine selections"
            )
        return {
            **score_input_attestation,
            "score": validated.score,
            "normalized_score": validated.normalized_score,
            "raw_score": validated.raw_score,
            "reported_score": validated.reported_score,
            "score_matches_reported": validated.score_matches_reported,
            "criterion_levels": validated.criterion_levels,
            "criterion_scores": validated.criterion_scores,
            "rubric_source": rubric.source,
            "rubric_set_id": rubric.rubric_set_id,
            "rubric_id": rubric.rubric_id,
            "structured_rubric_sha256": rubric.structured_rubric_sha256,
            "rendered_rubric_sha256": rubric.rendered_rubric_sha256,
            "manifest_sha256": rubric.manifest_sha256,
            "reward_sha256": hashlib.sha256(reward_raw).hexdigest(),
            "evaluation_sha256": hashlib.sha256(evaluation_raw).hexdigest(),
            "usage_sha256": hashlib.sha256(usage_raw).hexdigest(),
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
                    output,
                    "score_validation.json",
                ).decode("utf-8")
            )
            if type(validation) is not dict or set(validation) != SCORE_VALIDATION_KEYS:
                return None
            expected_validation = self.build_score_validation_from_bytes(
                rubric,
                self.artifacts.read_output_bytes(output, "reward.json"),
                self.artifacts.read_output_bytes(output, "evaluation.json"),
                self.artifacts.read_output_bytes(output, "usage.json"),
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
        rubric: ResolvedRubric,
        review_text: str,
        answer_text: str,
        effective_judge_model: str,
    ) -> dict[str, Any]:
        self.validate_target(attempt.target)
        identities = self.target_identities(attempt.target)
        review_sha256 = sha256_text(review_text)
        answer_sha256 = sha256_text(answer_text)
        engine = self.grading_engine
        engine_release = FULL_RUBRIC_ENGINE_IDENTITY["engine"]
        seed = deterministic_grading_seed(
            rubric_sha256=rubric.rendered_rubric_sha256,
            review_sha256=review_sha256,
            answer_sha256=answer_sha256,
            requested_model=effective_judge_model,
            benchmark=self.config.benchmark.value,
            assignment_identity=attempt.target.task,
            grading_engine=engine.value,
            engine_release=str(engine_release),
        )
        try:
            engine_execution = build_full_rubric_run_spec(
                rubric_text=rubric.text,
                review_text=review_text,
                answer_text=answer_text,
                requested_model=effective_judge_model,
                seed=seed,
            ).as_json()
        except (FullRubricJudgeError, ValueError) as exc:
            raise JudgeScoreValidationError(str(exc)) from exc
        return {
            "review_input_sha256": review_sha256,
            "answer_input_sha256": answer_sha256,
            "scoring_implementation_sha256": (
                self._scoring_implementation_sha256()
            ),
            "effective_judge_model": effective_judge_model,
            "benchmark": self.config.benchmark.value,
            "grading_engine": engine.value,
            "engine_execution": engine_execution,
            "review_mode": self.config.review,
            "max_review_chars": self.config.max_review_chars,
            "task": attempt.target.task,
            "run_identity": identities.canonical_run,
        }

    @staticmethod
    def scoring_implementation_sha256(
        benchmark: SubmissionBenchmarkId | str = SubmissionBenchmarkId.BIOMNIBENCH_DA,
    ) -> str:
        resolved = SubmissionBenchmarkId(benchmark)
        module_dir = Path(__file__).parent
        package_dir = module_dir.parents[1]
        sources = [
            (f"judging/{name}", module_dir / name)
            for name in (
                "artifacts.py",
                "discovery.py",
                "executor.py",
                "full_rubric_judge.py",
                "full_rubric_protocol.py",
                "models.py",
                "preflight.py",
                "runner.py",
                "scoring.py",
            )
        ]
        sources.append(
            (
                "submission_revision/autorubric.py",
                module_dir.parent / "autorubric.py",
            )
        )
        sources.extend(
            (
                ("benchmarks/__init__.py", package_dir / "benchmarks" / "__init__.py"),
                ("benchmarks/base.py", package_dir / "benchmarks" / "base.py"),
                ("benchmarks/registry.py", package_dir / "benchmarks" / "registry.py"),
            )
        )
        if resolved is SubmissionBenchmarkId.BIOMNIBENCH_DA:
            sources.append(
                (
                    "benchmarks/biomnibench_da/contract.py",
                    package_dir / "benchmarks" / "biomnibench_da" / "contract.py",
                )
            )
        else:
            sources.extend(
                (
                    (
                        "benchmarks/paperbench_code_dev/contract.py",
                        package_dir / "benchmarks" / "paperbench_code_dev" / "contract.py",
                    ),
                    (
                        "benchmarks/paperbench_code_dev/dataset.py",
                        package_dir / "benchmarks" / "paperbench_code_dev" / "dataset.py",
                    ),
                    (
                        "benchmarks/paperbench_code_dev/submission.py",
                        package_dir / "benchmarks" / "paperbench_code_dev" / "submission.py",
                    ),
                )
            )
        digest = hashlib.sha256()
        for name, path in sources:
            digest.update(name.encode("utf-8"))
            digest.update(b"\0")
            digest.update(path.read_bytes())
            digest.update(b"\0")
        return digest.hexdigest()

    def judge_model(self, env: dict[str, str] | None = None) -> str:
        if self.config.model:
            return self.config.model
        if env is not None and env.get("MODEL_NAME"):
            return env["MODEL_NAME"]
        return DEFAULT_JUDGE_MODEL
