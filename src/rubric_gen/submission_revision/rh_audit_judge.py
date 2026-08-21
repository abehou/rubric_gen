"""Reward-hacking audit grader with provider-current request contracts."""

from __future__ import annotations

import hashlib
import json
import math
import os
import shutil
import tempfile
from dataclasses import dataclass, fields
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.artifacts import make_tree_read_only
from rubric_gen.submission_revision.judge import (
    FrozenRubric,
    FrozenRubricJudge,
    JudgeArtifacts,
    SubmissionJudgeConfig,
)
from rubric_gen.submission_revision.judging.full_rubric_judge import (
    FULL_RUBRIC_ENGINE_IDENTITY,
    FULL_RUBRIC_REQUEST_TIMEOUT_SECONDS,
    FULL_RUBRIC_SYSTEM_PROMPT,
    FullRubricArtifactRecords,
    FullRubricGeneration,
    FullRubricRunSpec,
    _generate_response as _base_generate_response,
    build_full_rubric_run_spec,
    deterministic_grading_seed,
    full_rubric_payload,
    parse_structured_output,
    records_from_raw_reports,
    structured_output_schema,
)
from rubric_gen.submission_revision.judging.models import (
    JUDGMENT_REPEATS,
    grading_engine_for_benchmark,
)
from rubric_gen.submission_revision.judging.scoring import (
    parse_rubric_levels_strict,
)


@dataclass(frozen=True)
class RhFullRubricRunSpec(FullRubricRunSpec):
    """Use the current audit request contract for each provider."""

    def as_json(self) -> dict[str, object]:
        value = super().as_json()
        if self.provider == "anthropic":
            value["temperature"] = None
        return value


def build_rh_full_rubric_run_spec(
    *,
    rubric_text: str,
    review_text: str,
    answer_text: str,
    requested_model: str,
    api_base: str | None,
    seed: int,
) -> RhFullRubricRunSpec:
    base = build_full_rubric_run_spec(
        rubric_text=rubric_text,
        review_text=review_text,
        answer_text=answer_text,
        requested_model=requested_model,
        api_base=api_base,
        seed=seed,
    )
    return RhFullRubricRunSpec(**{
        field.name: getattr(base, field.name)
        for field in fields(FullRubricRunSpec)
    })


def _request_parameters(
    spec: RhFullRubricRunSpec,
    repeat_index: int,
) -> dict[str, object]:
    execution = spec.as_json()
    provider_seeds = execution["provider_seeds"]
    assert type(provider_seeds) is list
    return {
        "api_base": spec.api_base,
        "temperature": execution["temperature"],
        "provider_seed": provider_seeds[repeat_index],
        "reasoning_effort": execution["reasoning_effort"],
        "provider_storage": execution["provider_storage"],
        "prompt_cache_control": execution["prompt_cache_control"],
        "max_output_tokens": spec.max_output_tokens_per_call,
        "timeout_seconds": FULL_RUBRIC_REQUEST_TIMEOUT_SECONDS,
        "provider_retries": 0,
        "structured_output": "json_schema",
    }


def _generate_response(
    spec: RhFullRubricRunSpec,
    *,
    payload: str,
    schema: dict[str, object],
    repeat_index: int,
) -> FullRubricGeneration:
    if spec.provider != "anthropic":
        return _base_generate_response(
            spec,
            payload=payload,
            schema=schema,
            repeat_index=repeat_index,
        )

    from anthropic import Anthropic

    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError("ANTHROPIC_API_KEY must be set")
    response = Anthropic(
        api_key=api_key,
        timeout=FULL_RUBRIC_REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    ).messages.create(
        model=spec.requested_model,
        max_tokens=spec.max_output_tokens_per_call,
        system=FULL_RUBRIC_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": payload}],
        output_config={
            "effort": "low",
            "format": {"type": "json_schema", "schema": schema},
        },
    )
    text = "\n".join(
        block.text
        for block in response.content
        if getattr(block, "type", None) == "text"
        and type(getattr(block, "text", None)) is str
        and block.text
    )
    return FullRubricGeneration(
        text=text,
        provider="anthropic",
        requested_model=spec.requested_model,
        effective_model=str(getattr(response, "model", spec.requested_model)),
        response_id=getattr(response, "id", None),
        request_parameters=_request_parameters(spec, repeat_index),
        usage=getattr(response, "usage", None),
    )


def grade_rh_full_rubric(
    *,
    rubric_text: str,
    review_text: str,
    answer_text: str,
    requested_model: str,
    api_base: str | None,
    seed: int,
) -> FullRubricArtifactRecords:
    """Run five audit calls with the current provider request contracts."""

    spec = build_rh_full_rubric_run_spec(
        rubric_text=rubric_text,
        review_text=review_text,
        answer_text=answer_text,
        requested_model=requested_model,
        api_base=api_base,
        seed=seed,
    )
    rubric_levels = parse_rubric_levels_strict(rubric_text)
    schema = structured_output_schema(rubric_levels)
    payload = full_rubric_payload(rubric_text, review_text, answer_text)
    reports: list[dict[str, object]] = []
    usage: list[dict[str, object]] = []
    for repeat_index in range(JUDGMENT_REPEATS):
        generation = _generate_response(
            spec,
            payload=payload,
            schema=schema,
            repeat_index=repeat_index,
        )
        reports.append(parse_structured_output(generation.text, rubric_levels))
        usage.append(generation.usage_record())
    expected_parameters = [
        _request_parameters(spec, index)
        for index in range(JUDGMENT_REPEATS)
    ]
    if any(
        call.get("request_parameters") != expected
        for call, expected in zip(usage, expected_parameters, strict=True)
    ):
        raise RuntimeError("RH full-rubric provider request contract changed")
    return records_from_raw_reports(
        rubric_text=rubric_text,
        raw_reports=reports,
        spec=spec,
        call_usage=usage,
    )


def _composite_sha256(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        payload = path.read_bytes()
        digest.update(path.name.encode("utf-8"))
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


class RhAuditRubricJudge:
    """Score immutable snapshots without changing the sealed revision judge."""

    def __init__(self, config: SubmissionJudgeConfig, rubric: FrozenRubric) -> None:
        self.config = config
        self.rubric = rubric
        self.experiment_dir = Path(config.experiment_dir).resolve()
        self.task_dir = Path(config.task_dir).resolve()
        self._review_delegate = FrozenRubricJudge(config, rubric)

    def scoring_identity(self) -> dict[str, object]:
        model = self.config.judge_model
        if type(model) is not str or not model.strip():
            raise ValueError("RH audit judge model must be explicit")
        source = Path(__file__).resolve()
        base_judge = source.parent / "judging" / "full_rubric_judge.py"
        review_adapter = source.parent / "judge.py"
        return {
            "judge_source_sha256": sha256_file(source),
            "judge_runner_sha256": _composite_sha256((
                source,
                review_adapter,
                base_judge,
            )),
            "scorer_module_sha256": sha256_file(base_judge),
            "effective_judge_model": model,
            "judge_api_base": self.config.base_url,
            "benchmark": self.config.benchmark.value,
            "grading_engine": grading_engine_for_benchmark(
                self.config.benchmark
            ).value,
            "review_mode": self.config.review,
            "max_review_chars": self.config.max_review_chars,
            "rubric_source": self.rubric.source,
            "rubric_set_id": self.rubric.rubric_set_id,
            "rubric_id": self.rubric.rubric_id,
            "structured_rubric_sha256": self.rubric.structured_rubric_sha256,
            "rendered_rubric_sha256": self.rubric.sha256,
            "manifest_sha256": self.rubric.manifest_sha256,
        }

    def review_inputs(self, submission_dir: Path) -> tuple[str, str]:
        return self._review_delegate.review_inputs(submission_dir)

    def evaluate(self, submission_dir: Path, attempt_id: str) -> JudgeArtifacts:
        root = self._evaluation_root(submission_dir, attempt_id)
        if root.exists():
            try:
                return self.validate(submission_dir, attempt_id)
            except (OSError, RuntimeError, ValueError):
                self._archive_existing(root, "invalid")
        review_text, answer_text = self.review_inputs(submission_dir)
        identity = self.scoring_identity()
        model = str(identity["effective_judge_model"])
        seed = deterministic_grading_seed(
            rubric_sha256=self.rubric.sha256,
            review_sha256=sha256_text(review_text),
            answer_sha256=sha256_text(answer_text),
            requested_model=model,
            api_base=self.config.base_url,
            benchmark=self.config.benchmark.value,
            assignment_identity=self.task_dir.name,
            grading_engine=str(identity["grading_engine"]),
            engine_release=str(FULL_RUBRIC_ENGINE_IDENTITY["engine"]),
            repeat_index=1,
        )
        last_error: Exception | None = None
        records: FullRubricArtifactRecords | None = None
        for provider_attempt in range(1, self.config.max_retries + 2):
            try:
                records = grade_rh_full_rubric(
                    rubric_text=self.rubric.text,
                    review_text=review_text,
                    answer_text=answer_text,
                    requested_model=model,
                    api_base=self.config.base_url,
                    seed=seed,
                )
                break
            except Exception as exc:
                last_error = exc
                self._write_failure(root.parent, provider_attempt, exc)
        if records is None:
            raise RuntimeError(
                "RH audit rubric judge failed after "
                f"{self.config.max_retries + 1} attempts: {last_error}"
            ) from last_error
        self._publish(
            root=root,
            records=records,
            scoring_identity=identity,
            review_text=review_text,
            answer_text=answer_text,
        )
        return self.validate(submission_dir, attempt_id)

    def validate(self, submission_dir: Path, attempt_id: str) -> JudgeArtifacts:
        root = self._evaluation_root(submission_dir, attempt_id)
        if root.is_symlink() or not root.is_dir():
            raise RuntimeError(f"invalid RH audit evaluation: {root}")
        expected_files = {
            "evaluation.json",
            "metadata.json",
            "reward.json",
            "score_validation.json",
            "usage.json",
        }
        if {path.name for path in root.iterdir()} != expected_files:
            raise RuntimeError("RH audit evaluation files changed")
        metadata = self._read_json(root / "metadata.json")
        if set(metadata) != {
            "kind",
            "scoring_identity",
            "review_input_sha256",
            "answer_input_sha256",
            "engine_execution",
            "artifacts",
        } or metadata.get("kind") != "rubric-gen-rh-audit-rubric-judgment":
            raise RuntimeError("RH audit metadata changed")
        review_text, answer_text = self.review_inputs(submission_dir)
        if (
            metadata.get("scoring_identity") != self.scoring_identity()
            or metadata.get("review_input_sha256") != sha256_text(review_text)
            or metadata.get("answer_input_sha256") != sha256_text(answer_text)
        ):
            raise RuntimeError("RH audit dispatch identity changed")
        artifacts = metadata.get("artifacts")
        expected_artifacts = {
            "evaluation_sha256": root / "evaluation.json",
            "reward_sha256": root / "reward.json",
            "score_validation_sha256": root / "score_validation.json",
            "usage_sha256": root / "usage.json",
        }
        if not isinstance(artifacts, dict) or set(artifacts) != set(expected_artifacts):
            raise RuntimeError("RH audit artifact manifest changed")
        for name, path in expected_artifacts.items():
            if path.is_symlink() or not path.is_file() or artifacts[name] != sha256_file(path):
                raise RuntimeError("RH audit artifact changed")
        validation = self._read_json(root / "score_validation.json")
        identity = self.scoring_identity()
        if any(validation.get(key) != value for key, value in identity.items()):
            raise RuntimeError("RH audit validation identity changed")
        if (
            validation.get("review_input_sha256") != sha256_text(review_text)
            or validation.get("answer_input_sha256") != sha256_text(answer_text)
            or validation.get("engine_execution") != metadata["engine_execution"]
            or validation.get("rendered_rubric_sha256") != self.rubric.sha256
        ):
            raise RuntimeError("RH audit validation dispatch changed")
        score = validation.get("score")
        if (
            isinstance(score, bool)
            or not isinstance(score, (int, float))
            or not math.isfinite(float(score))
            or not 0 <= float(score) <= 100
        ):
            raise RuntimeError("RH audit validation score changed")
        return JudgeArtifacts(
            score_validation_path=root / "score_validation.json",
            evaluation_path=root / "evaluation.json",
        )

    def _publish(
        self,
        *,
        root: Path,
        records: FullRubricArtifactRecords,
        scoring_identity: dict[str, object],
        review_text: str,
        answer_text: str,
    ) -> None:
        root.parent.mkdir(parents=True, exist_ok=True)
        pending = Path(tempfile.mkdtemp(prefix=".pending-", dir=root.parent))
        try:
            write_json_atomic(pending / "reward.json", records.reward)
            write_json_atomic(pending / "evaluation.json", records.evaluation)
            write_json_atomic(pending / "usage.json", records.usage)
            execution = records.evaluation["full_rubric_structured"]["execution"]
            validation = {
                **scoring_identity,
                "review_input_sha256": sha256_text(review_text),
                "answer_input_sha256": sha256_text(answer_text),
                "engine_execution": execution,
                "score": records.score,
                "normalized_score": records.normalized_score,
                "raw_score": records.raw_score,
                "rendered_rubric_sha256": self.rubric.sha256,
            }
            write_json_atomic(pending / "score_validation.json", validation)
            metadata = {
                "kind": "rubric-gen-rh-audit-rubric-judgment",
                "scoring_identity": scoring_identity,
                "review_input_sha256": sha256_text(review_text),
                "answer_input_sha256": sha256_text(answer_text),
                "engine_execution": execution,
                "artifacts": {
                    "evaluation_sha256": sha256_file(pending / "evaluation.json"),
                    "reward_sha256": sha256_file(pending / "reward.json"),
                    "score_validation_sha256": sha256_file(
                        pending / "score_validation.json"
                    ),
                    "usage_sha256": sha256_file(pending / "usage.json"),
                },
            }
            write_json_atomic(pending / "metadata.json", metadata)
            pending.replace(root)
            make_tree_read_only(root)
        except Exception:
            shutil.rmtree(pending, ignore_errors=True)
            raise

    def _evaluation_root(self, submission_dir: Path, attempt_id: str) -> Path:
        if (
            type(attempt_id) is not str
            or len(attempt_id) != 32
            or any(character not in "0123456789abcdef" for character in attempt_id)
        ):
            raise ValueError("judge attempt ID must be 128-bit lowercase hex")
        if submission_dir.name in {"", ".", ".."}:
            raise ValueError("submission directory name is invalid")
        return (
            self.experiment_dir
            / "evaluations"
            / submission_dir.name
            / self.rubric.sha256
            / attempt_id
        )

    @staticmethod
    def _read_json(path: Path) -> dict[str, object]:
        if path.is_symlink() or not path.is_file():
            raise RuntimeError(f"RH audit file is invalid: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise RuntimeError(f"RH audit file is not an object: {path}")
        return value

    @staticmethod
    def _archive_existing(root: Path, label: str) -> None:
        index = 1
        while root.with_name(f"{root.name}.{label}-{index:03d}").exists():
            index += 1
        root.replace(root.with_name(f"{root.name}.{label}-{index:03d}"))

    @staticmethod
    def _write_failure(parent: Path, attempt: int, error: Exception) -> None:
        parent.mkdir(parents=True, exist_ok=True)
        write_json_atomic(parent / f"failed-attempt-{attempt:03d}.json", {
            "kind": "rubric-gen-rh-audit-rubric-failure",
            "attempt": attempt,
            "error_type": type(error).__name__,
            "error": str(error),
        })
