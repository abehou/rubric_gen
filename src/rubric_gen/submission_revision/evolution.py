"""Elicit bounded rubric criteria from a blinded artifact history."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.generation_scoring import (
    validate_generation_scoring_structure,
)
from rubric_gen.submission_revision.evolution_artifacts import (
    ArtifactHistory,
    validate_artifact_history,
)
from rubric_gen.submission_revision.evolution_protocol import (
    difference_evidence,
    difference_instructions,
    difference_schema,
    required_level_labels,
    validated_difference_response,
    rubric_evidence,
    rubric_instructions,
    rubric_schema,
    validated_rubric_response,
)
from rubric_gen.submission_revision.evolution_provider import (
    PROPOSER_MAX_OUTPUT_TOKENS,
    PROPOSER_MAX_REQUEST_BYTES,
    ProviderContract,
    ProviderOperation,
    StructuredProviderOutput,
)
from rubric_gen.submission_revision.evolution_serialization import (
    canonical_json,
    canonical_sha256,
    load_json_object,
)
from rubric_gen.submission_revision.rubric_generation import (
    CompleteRubric,
    ElicitedCriterion,
    RubricGeneration,
    RubricPolicy,
    render_augmented_rubric,
)
from rubric_gen.submission_revision.rubric_generation_store import (
    load_rubric_generation,
    persist_rubric_generation,
    rubric_generation_directory,
)


PROVIDER_FAILURE_MAX_RETRIES = 3


def rubric_generation_implementation_sha256() -> str:
    """Return one hash for the code that creates and checks rubric generations."""

    package_root = Path(__file__).parent
    paths = (
        Path(__file__),
        package_root / "evolution_artifacts.py",
        package_root / "evolution_protocol.py",
        package_root / "evolution_provider.py",
        package_root / "evolution_serialization.py",
        package_root / "rubric_generation.py",
        package_root / "rubric_generation_store.py",
        package_root / "pretreatment_rubrics.py",
        package_root / "autorubric.py",
        package_root / "generation_scoring.py",
        package_root / "contrasts.py",
        package_root / "judging" / "full_rubric_judge.py",
        package_root / "judging" / "models.py",
        package_root / "judging" / "scoring.py",
        package_root.parent / "artifacts" / "serialization.py",
        package_root.parent / "artifacts" / "hashing.py",
        package_root.parent / "runtime" / "llm.py",
    )
    digest = hashlib.sha256()
    for path in paths:
        digest.update(str(path.relative_to(package_root.parent)).encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


@dataclass(frozen=True)
class _StageResult:
    raw_text: str
    value: object
    attempt_count: int
    fallback_reason: str | None = None


@dataclass(frozen=True)
class _ProductionResult:
    generation: RubricGeneration
    difference: _StageResult
    rubric: _StageResult


class RubricProposer:
    """Elicit general missing criteria from a blinded artifact history."""

    def __init__(
        self,
        *,
        benchmark: SubmissionBenchmarkId,
        model: str,
        max_retries: int = 2,
        service_tier: str | None = None,
        run_proposer: ProviderOperation | None = None,
    ) -> None:
        if not isinstance(benchmark, SubmissionBenchmarkId):
            raise ValueError("rubric proposer benchmark is invalid")
        if type(max_retries) is not int or max_retries < 0:
            raise ValueError("rubric proposer retries must be non-negative")
        self.benchmark = benchmark
        self.max_retries = max_retries
        self.proposer_contract = ProviderContract(
            model=model,
            max_output_tokens=PROPOSER_MAX_OUTPUT_TOKENS,
            max_request_bytes=PROPOSER_MAX_REQUEST_BYTES,
            service_tier=service_tier,
        )
        self.run_proposer = run_proposer or self._run_direct_proposer

    def elicit_rubric(
        self,
        *,
        instruction: str,
        original_rubric: CompleteRubric,
        current_generation: RubricGeneration,
        policy: RubricPolicy,
        generation_round: int,
        output_dir: Path,
        artifact_history: ArtifactHistory,
        source_checkpoint: int | None = None,
    ) -> RubricGeneration:
        """Return the next single rubric after bounded criterion elicitation."""

        if type(instruction) is not str or not instruction.strip():
            raise ValueError("task instruction must be nonempty")
        if not isinstance(original_rubric, CompleteRubric):
            raise ValueError("original_rubric must be a CompleteRubric")
        if not isinstance(current_generation, RubricGeneration):
            raise ValueError("current_generation must be a RubricGeneration")
        if type(policy) is not RubricPolicy or policy not in {
            RubricPolicy.OFFLINE_ELICITATION,
            RubricPolicy.ONLINE_ELICITATION,
        }:
            raise ValueError("criterion elicitation requires an elicitation policy")
        if type(generation_round) is not int:
            raise ValueError("generation_round must be an integer")
        if generation_round != current_generation.generation_round + 1:
            raise ValueError("rubric generations must be consecutive")
        if policy is RubricPolicy.OFFLINE_ELICITATION:
            if generation_round != 1:
                raise ValueError(
                    "offline elicitation has one pre-treatment generation"
                )
            if source_checkpoint is not None:
                raise ValueError("offline elicitation cannot use a live checkpoint")
        elif generation_round == 1:
            if source_checkpoint is not None:
                raise ValueError(
                    "the pre-treatment online rubric cannot use live evidence"
                )
        elif (
            type(source_checkpoint) is not int
            or source_checkpoint != generation_round - 1
        ):
            raise ValueError(
                "online elicitation needs the preceding live checkpoint"
            )
        artifact_history = validate_artifact_history(artifact_history)
        context = self._context(
            instruction=instruction,
            original_rubric=original_rubric,
            current_generation=current_generation,
            policy=policy,
            generation_round=generation_round,
            source_checkpoint=source_checkpoint,
            artifact_history=artifact_history,
        )
        try:
            completed = self._load_completed_generation(
                instruction=instruction,
                original_rubric=original_rubric,
                current_generation=current_generation,
                policy=policy,
                generation_round=generation_round,
                source_checkpoint=source_checkpoint,
                artifact_history=artifact_history,
                context=context,
                output_dir=output_dir,
            )
        except (UnicodeError, ValueError) as exc:
            raise RuntimeError("completed rubric generation changed") from exc
        if completed is not None:
            return completed
        result = self._produce(
            instruction=instruction,
            original_rubric=original_rubric,
            current_generation=current_generation,
            policy=policy,
            generation_round=generation_round,
            source_checkpoint=source_checkpoint,
            artifact_history=artifact_history,
        )

        metadata = self._generation_record(
            context=context,
            result=result,
        )
        history_payload = {
            "kind": "blinded-artifact-history",
            **artifact_history.artifact_record(),
        }
        evolution_files = {
            "artifact-history.json": canonical_json(history_payload) + "\n",
            "difference-proposal.json": result.difference.raw_text,
            "rubric-proposal.json": result.rubric.raw_text,
            "evolution.json": canonical_json(metadata) + "\n",
        }
        persist_rubric_generation(
            output_dir,
            result.generation,
            policy,
            evolution_files=evolution_files,
        )
        return result.generation

    def _load_completed_generation(
        self,
        *,
        instruction: str,
        original_rubric: CompleteRubric,
        current_generation: RubricGeneration,
        policy: RubricPolicy,
        generation_round: int,
        source_checkpoint: int | None,
        artifact_history: ArtifactHistory,
        context: dict[str, object],
        output_dir: Path,
    ) -> RubricGeneration | None:
        root = rubric_generation_directory(output_dir, generation_round)
        if not root.exists():
            return None
        loaded = load_rubric_generation(
            output_dir,
            generation_round,
            expected_policy=policy,
        )
        expected_history = {
            "kind": "blinded-artifact-history",
            **artifact_history.artifact_record(),
        }
        if load_json_object(
            (root / "artifact-history.json").read_text(),
            "completed rubric artifact history",
        ) != expected_history:
            raise RuntimeError("completed rubric generation has another history")

        difference_text = (root / "difference-proposal.json").read_text()
        difference_value = validated_difference_response(
            difference_text,
            artifact_history=artifact_history,
        )
        level_labels = required_level_labels(original_rubric)
        rubric_text = (root / "rubric-proposal.json").read_text()
        rubric_value = validated_rubric_response(
            rubric_text,
            original_rubric=original_rubric,
            current_generation=current_generation,
            generation_round=generation_round,
            level_labels=level_labels,
            artifact_history=artifact_history,
        )
        generation = self._build_generation(
            original_rubric=original_rubric,
            current_generation=current_generation,
            policy=policy,
            generation_round=generation_round,
            source_checkpoint=source_checkpoint,
            active_criteria=rubric_value,
        )
        metadata = load_json_object(
            (root / "evolution.json").read_text(),
            "completed rubric generation",
        )
        counts = (
            metadata.get("difference_attempt_count"),
            metadata.get("rubric_attempt_count"),
        )
        fallback_reason = metadata.get("rubric_fallback_reason")
        if (
            any(type(value) is not int for value in counts)
            or not 1 <= counts[0] <= self.max_retries + 1
            or not 1 <= counts[1] <= self.max_retries + 1
            or (fallback_reason is not None and type(fallback_reason) is not str)
        ):
            raise RuntimeError("completed rubric generation has invalid attempts")
        difference = _StageResult(difference_text, difference_value, counts[0])
        rubric = _StageResult(
            rubric_text,
            rubric_value,
            counts[1],
            fallback_reason,
        )
        result = _ProductionResult(generation, difference, rubric)
        if metadata != self._generation_record(context=context, result=result):
            raise RuntimeError("completed rubric generation changed")
        if loaded != generation:
            raise RuntimeError("completed rubric generation content changed")
        return loaded


    def _produce(
        self,
        *,
        instruction: str,
        original_rubric: CompleteRubric,
        current_generation: RubricGeneration,
        policy: RubricPolicy,
        generation_round: int,
        source_checkpoint: int | None,
        artifact_history: ArtifactHistory,
    ) -> _ProductionResult:
        difference_evidence_value = difference_evidence(
            instruction=instruction,
            original_rubric=original_rubric,
            current_generation=current_generation,
            artifact_history=artifact_history,
        )
        difference = self._proposer_stage(
            role="differences",
            instructions=difference_instructions(),
            evidence=difference_evidence_value,
            response_schema=difference_schema(artifact_history),
            validator=lambda value: validated_difference_response(
                value,
                artifact_history=artifact_history,
            ),
        )
        assert isinstance(difference.value, dict)
        level_labels = required_level_labels(original_rubric)
        rubric_evidence_value = rubric_evidence(
            instruction=instruction,
            original_rubric=original_rubric,
            current_generation=current_generation,
            artifact_history=artifact_history,
            difference_response=difference.value,
            level_labels=level_labels,
        )
        rubric = self._rubric_stage(
            evidence=rubric_evidence_value,
            response_schema=rubric_schema(
                level_labels,
                artifact_history,
            ),
            validator=lambda value: validated_rubric_response(
                value,
                original_rubric=original_rubric,
                current_generation=current_generation,
                generation_round=generation_round,
                level_labels=level_labels,
                artifact_history=artifact_history,
            ),
            current_generation=current_generation,
        )
        assert isinstance(rubric.value, tuple)
        generation = self._build_generation(
            original_rubric=original_rubric,
            current_generation=current_generation,
            policy=policy,
            generation_round=generation_round,
            source_checkpoint=source_checkpoint,
            active_criteria=rubric.value,
        )
        return _ProductionResult(
            generation=generation,
            difference=difference,
            rubric=rubric,
        )

    def _build_generation(
        self,
        *,
        original_rubric: CompleteRubric,
        current_generation: RubricGeneration,
        policy: RubricPolicy,
        generation_round: int,
        source_checkpoint: int | None,
        active_criteria: tuple[ElicitedCriterion, ...],
    ) -> RubricGeneration:
        next_rubric = render_augmented_rubric(
            original_rubric,
            active_criteria,
        )
        generation = RubricGeneration(
            generation_round=generation_round,
            source_checkpoint=(
                source_checkpoint
                if policy is RubricPolicy.ONLINE_ELICITATION
                else None
            ),
            rubric=next_rubric,
            elicited_criteria=active_criteria,
            proposer_call_budget=2 * (self.max_retries + 1),
        )
        generation.validate_successor(current_generation)
        return generation

    def _proposer_stage(
        self,
        *,
        role: str,
        instructions: str,
        evidence: str,
        response_schema: dict[str, object],
        validator: Callable[[str], object],
    ) -> _StageResult:
        repair: str | None = None
        provider_failures = 0
        attempt_count = 0
        for attempt in range(1, self.max_retries + 2):
            attempt_count = attempt
            attempt_evidence = evidence
            if repair is not None:
                attempt_evidence += (
                    "\n\n<repair>\nThe prior response failed validation.\n"
                    + repair
                    + "\nReturn a complete corrected response.\n</repair>"
                )
            try:
                output = self.run_proposer(
                    stage=role,
                    evidence=attempt_evidence,
                    response_schema=response_schema,
                )
            except Exception as exc:
                repair = str(exc) or type(exc).__name__
                provider_failures += 1
                if provider_failures > PROVIDER_FAILURE_MAX_RETRIES:
                    break
                continue
            try:
                self.proposer_contract.validate_output(output)
            except Exception as exc:
                repair = str(exc) or type(exc).__name__
                continue
            assert isinstance(output, StructuredProviderOutput)
            try:
                value = validator(output.response_text)
            except ValueError as exc:
                repair = str(exc)
                continue
            return _StageResult(
                raw_text=output.response_text,
                value=value,
                attempt_count=attempt,
            )
        raise RuntimeError(
            f"{role} proposer failed after {attempt_count} calls: "
            f"{repair}"
        )

    def _rubric_stage(
        self,
        *,
        evidence: str,
        response_schema: dict[str, object],
        validator: Callable[[str], object],
        current_generation: RubricGeneration,
    ) -> _StageResult:
        repair: str | None = None
        provider_failures = 0
        attempt_count = 0
        for attempt in range(1, self.max_retries + 2):
            attempt_count = attempt
            attempt_evidence = evidence
            if repair is not None:
                attempt_evidence += (
                    "\n\n<repair>\nThe prior rubric response failed validation.\n"
                    + repair
                    + "\nUse only provenance pair IDs from the supplied history.\n"
                    "Return a complete corrected response.\n</repair>"
                )
            try:
                output = self.run_proposer(
                    stage="rubric",
                    evidence=attempt_evidence,
                    response_schema=response_schema,
                )
            except Exception as exc:
                repair = str(exc) or type(exc).__name__
                provider_failures += 1
                if provider_failures > PROVIDER_FAILURE_MAX_RETRIES:
                    break
                continue
            try:
                self.proposer_contract.validate_output(output)
            except Exception as exc:
                repair = str(exc) or type(exc).__name__
                continue
            assert isinstance(output, StructuredProviderOutput)
            try:
                value = validator(output.response_text)
            except ValueError as exc:
                repair = str(exc)
                continue
            return _StageResult(
                raw_text=output.response_text,
                value=value,
                attempt_count=attempt,
            )

        fallback = canonical_json({
            "criteria": [{
                "title": criterion.title,
                "requirement": criterion.requirement,
                "levels": [
                    {
                        "label": label,
                        "points": points,
                        "description": description,
                    }
                    for label, points, description in criterion.levels
                ],
                "provenance_pair_ids": list(criterion.provenance_pair_ids),
            } for criterion in current_generation.elicited_criteria],
        })
        return _StageResult(
            raw_text=fallback,
            value=validator(fallback),
            attempt_count=attempt_count,
            fallback_reason=" ".join(
                (repair or "invalid rubric response").split()
            ),
        )

    def _context(
        self,
        *,
        instruction: str,
        original_rubric: CompleteRubric,
        current_generation: RubricGeneration,
        policy: RubricPolicy,
        generation_round: int,
        source_checkpoint: int | None,
        artifact_history: ArtifactHistory,
    ) -> dict[str, object]:
        return {
            "benchmark": self.benchmark.value,
            "policy": policy.value,
            "generation_round": generation_round,
            "source_checkpoint": source_checkpoint,
            "instruction_sha256": sha256_text(instruction),
            "prior_generation_sha256": current_generation.generation_sha256,
            "original_rubric_sha256": original_rubric.content_sha256,
            "artifact_history_sha256": canonical_sha256(
                artifact_history.artifact_record()
            ),
            "proposer": self.proposer_contract.record(),
            "max_retries": self.max_retries,
            "provider_failure_max_retries": PROVIDER_FAILURE_MAX_RETRIES,
        }

    def _generation_record(
        self,
        *,
        context: dict[str, object],
        result: _ProductionResult,
    ) -> dict[str, object]:
        return {
            "kind": "rubric-elicitation-generation",
            "implementation_sha256": rubric_generation_implementation_sha256(),
            "context": context,
            "prior_generation_sha256": context["prior_generation_sha256"],
            "generation_sha256": result.generation.generation_sha256,
            "original_rubric_sha256": context["original_rubric_sha256"],
            "elicited_criterion_ids": [
                item.criterion_id
                for item in result.generation.elicited_criteria
            ],
            "difference_proposal_sha256": sha256_text(result.difference.raw_text),
            "rubric_proposal_sha256": sha256_text(result.rubric.raw_text),
            "proposer_call_budget": 2 * (self.max_retries + 1),
            "difference_attempt_count": result.difference.attempt_count,
            "rubric_attempt_count": result.rubric.attempt_count,
            "rubric_fallback_reason": result.rubric.fallback_reason,
            "scoring_feasibility": validate_generation_scoring_structure(
                result.generation,
                benchmark=self.benchmark,
            ),
        }

    def _run_direct_proposer(
        self,
        *,
        stage: str,
        evidence: str,
        response_schema: dict[str, object],
    ) -> StructuredProviderOutput:
        instructions = (
            difference_instructions()
            if stage == "differences"
            else rubric_instructions()
        )
        return self.proposer_contract.generate(
            instructions=instructions,
            evidence=evidence,
            response_schema=response_schema,
            request_context="rubric proposer",
            schema_name=f"rubric_{stage}",
        )
