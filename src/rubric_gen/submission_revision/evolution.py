"""Induce bounded rubric criteria from blinded pairwise preferences."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import cast

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.evolution_artifacts import (
    ArtifactHistory,
    validate_artifact_history,
)
from rubric_gen.submission_revision.evolution_assessment import (
    AssessmentView,
    AssessmentResult,
    PairComparison,
    assessment_evidence,
    assessment_instructions,
    assessment_schema,
    comparison_record,
    pair_comparisons,
    partition_gaps,
    validated_assessment_response,
    validation_artifact_ids,
    validation_artifact_ids_from_history,
)
from rubric_gen.submission_revision.evolution_protocol import (
    CandidateValidation,
    CriterionCandidate,
    admission_record,
    admit_candidates,
    induction_evidence,
    induction_instructions,
    induction_schema,
    required_level_labels,
    update_criteria,
    validated_induction_response,
    validated_validation_response,
    validation_evidence,
    validation_instructions,
    validation_schema,
)
from rubric_gen.submission_revision.evolution_provider import (
    PROPOSER_MAX_OUTPUT_TOKENS,
    PROPOSER_MAX_REQUEST_BYTES,
    ProviderContract,
    ProviderOperation,
    StructuredProviderOutput,
)
from rubric_gen.submission_revision.evolution_request import (
    validate_evolution_request,
)
from rubric_gen.submission_revision.evolution_serialization import (
    canonical_json,
    canonical_sha256,
    load_json_object,
)
from rubric_gen.submission_revision.generation_scoring import (
    validate_generation_scoring_structure,
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
_STAGE_COUNT = 5


def rubric_generation_implementation_sha256() -> str:
    """Return one hash for the code that creates and checks rubric generations."""

    package_root = Path(__file__).parent
    paths = (
        Path(__file__),
        package_root / "evolution_assessment.py",
        package_root / "evolution_artifacts.py",
        package_root / "evolution_protocol.py",
        package_root / "evolution_provider.py",
        package_root / "evolution_request.py",
        package_root / "evolution_serialization.py",
        package_root / "rubric_generation.py",
        package_root / "rubric_generation_store.py",
        package_root / "pretreatment_rubrics.py",
        package_root / "autorubric.py",
        package_root / "generation_scoring.py",
        package_root / "contrasts.py",
        package_root / "red_team.py",
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
    assessment_rubric_free: _StageResult
    assessment_active_rubric: _StageResult
    assessment_development_rubric: _StageResult
    induction: _StageResult
    validation: _StageResult
    comparisons_text: str
    admissions_text: str
    rubric_free_preference_count: int
    rubric_gap_count: int
    induction_pair_count: int
    validation_pair_count: int
    accepted_candidate_ids: tuple[str, ...]


class RubricProposer:
    """Run pairwise assessment, criterion induction, and validation."""

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
        development_rubric: CompleteRubric,
        current_generation: RubricGeneration,
        policy: RubricPolicy,
        generation_round: int,
        output_dir: Path,
        artifact_history: ArtifactHistory,
        source_checkpoint: int | None = None,
    ) -> RubricGeneration:
        """Return the next rubric after pairwise criterion induction."""

        validate_evolution_request(
            instruction=instruction,
            original_rubric=original_rubric,
            development_rubric=development_rubric,
            current_generation=current_generation,
            policy=policy,
            generation_round=generation_round,
            source_checkpoint=source_checkpoint,
        )
        artifact_history = validate_artifact_history(artifact_history)
        context = self._context(
            instruction=instruction,
            original_rubric=original_rubric,
            development_rubric=development_rubric,
            current_generation=current_generation,
            policy=policy,
            generation_round=generation_round,
            source_checkpoint=source_checkpoint,
            artifact_history=artifact_history,
        )
        try:
            completed = self._load_completed_generation(
                original_rubric=original_rubric,
                development_rubric=development_rubric,
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
            development_rubric=development_rubric,
            current_generation=current_generation,
            policy=policy,
            generation_round=generation_round,
            source_checkpoint=source_checkpoint,
            artifact_history=artifact_history,
        )
        history_payload = {
            "kind": "rubric-induction-evidence",
            **artifact_history.artifact_record(),
        }
        evolution_files = {
            "artifact-history.json": canonical_json(history_payload) + "\n",
            "pairwise-assessment-rubric-free.json": (
                result.assessment_rubric_free.raw_text
            ),
            "pairwise-assessment-active-rubric.json": (
                result.assessment_active_rubric.raw_text
            ),
            "pairwise-assessment-development-rubric.json": (
                result.assessment_development_rubric.raw_text
            ),
            "pairwise-comparisons.json": result.comparisons_text,
            "criterion-proposal.json": result.induction.raw_text,
            "criterion-validation.json": result.validation.raw_text,
            "aggregate-margins.json": result.admissions_text,
            "evolution.json": canonical_json(self._generation_record(
                context=context,
                result=result,
            )) + "\n",
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
        original_rubric: CompleteRubric,
        development_rubric: CompleteRubric,
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
            "kind": "rubric-induction-evidence",
            **artifact_history.artifact_record(),
        }
        if load_json_object(
            (root / "artifact-history.json").read_text(),
            "completed rubric artifact history",
        ) != expected_history:
            raise RuntimeError("completed rubric generation has another history")

        rubric_free_text = (
            root / "pairwise-assessment-rubric-free.json"
        ).read_text()
        active_rubric_text = (
            root / "pairwise-assessment-active-rubric.json"
        ).read_text()
        development_rubric_text = (
            root / "pairwise-assessment-development-rubric.json"
        ).read_text()
        rubric_free_value = validated_assessment_response(
            rubric_free_text,
            artifact_history=artifact_history,
            view=AssessmentView.RUBRIC_FREE,
            current_generation=current_generation,
        )
        active_rubric_value = validated_assessment_response(
            active_rubric_text,
            artifact_history=artifact_history,
            view=AssessmentView.ACTIVE_RUBRIC,
            current_generation=current_generation,
        )
        development_rubric_value = validated_assessment_response(
            development_rubric_text,
            artifact_history=artifact_history,
            view=AssessmentView.DEVELOPMENT_RUBRIC,
            current_generation=current_generation,
        )
        comparisons = pair_comparisons(
            rubric_free_value,
            active_rubric_value,
            development_rubric_value,
            artifact_history,
        )
        induction_gaps, validation_gaps = partition_gaps(
            comparisons,
            priority_induction_pair_ids=artifact_history.red_team_pair_ids,
        )
        expected_comparisons_text = canonical_json(comparison_record(
            comparisons,
            induction_gaps,
            validation_gaps,
        )) + "\n"
        comparisons_text = (root / "pairwise-comparisons.json").read_text()
        if comparisons_text != expected_comparisons_text:
            raise RuntimeError("completed pairwise comparisons changed")

        level_labels = required_level_labels(original_rubric)
        induction_text = (root / "criterion-proposal.json").read_text()
        candidates = validated_induction_response(
            induction_text,
            original_rubric=original_rubric,
            current_generation=current_generation,
            generation_round=generation_round,
            level_labels=level_labels,
            induction_gaps=induction_gaps,
        )
        validation_text = (root / "criterion-validation.json").read_text()
        validations = validated_validation_response(
            validation_text,
            candidates=candidates,
            artifact_ids=validation_artifact_ids(comparisons),
        )
        accepted, admissions = admit_candidates(
            candidates,
            validations,
            comparisons,
            current_generation,
        )
        admissions_text = canonical_json(admission_record(admissions)) + "\n"
        if (root / "aggregate-margins.json").read_text() != admissions_text:
            raise RuntimeError("completed aggregate margin decisions changed")
        active_criteria = update_criteria(current_generation, accepted)
        generation = self._build_generation(
            original_rubric=original_rubric,
            current_generation=current_generation,
            policy=policy,
            generation_round=generation_round,
            source_checkpoint=source_checkpoint,
            active_criteria=active_criteria,
        )
        metadata = load_json_object(
            (root / "evolution.json").read_text(),
            "completed rubric generation",
        )
        results = self._rebuild_stage_results(
            metadata=metadata,
            rubric_free_text=rubric_free_text,
            rubric_free_value=rubric_free_value,
            active_rubric_text=active_rubric_text,
            active_rubric_value=active_rubric_value,
            development_rubric_text=development_rubric_text,
            development_rubric_value=development_rubric_value,
            induction_text=induction_text,
            candidates=candidates,
            validation_text=validation_text,
            validations=validations,
            artifact_history=artifact_history,
            comparisons=comparisons,
            current_generation=current_generation,
            has_pairs=bool(artifact_history.pairs),
            has_induction=bool(induction_gaps),
            has_candidates=bool(candidates),
        )
        result = _ProductionResult(
            generation=generation,
            assessment_rubric_free=results[0],
            assessment_active_rubric=results[1],
            assessment_development_rubric=results[2],
            induction=results[3],
            validation=results[4],
            comparisons_text=comparisons_text,
            admissions_text=admissions_text,
            rubric_free_preference_count=len(comparisons),
            rubric_gap_count=sum(bool(item.gap_views) for item in comparisons),
            induction_pair_count=len(induction_gaps),
            validation_pair_count=len(validation_gaps),
            accepted_candidate_ids=tuple(
                item.criterion.criterion_id for item in accepted
            ),
        )
        if metadata != self._generation_record(context=context, result=result):
            raise RuntimeError("completed rubric generation changed")
        if loaded != generation:
            raise RuntimeError("completed rubric generation content changed")
        return loaded

    def _rebuild_stage_results(
        self,
        *,
        metadata: dict[str, object],
        rubric_free_text: str,
        rubric_free_value: AssessmentResult,
        active_rubric_text: str,
        active_rubric_value: AssessmentResult,
        development_rubric_text: str,
        development_rubric_value: AssessmentResult,
        induction_text: str,
        candidates: tuple[CriterionCandidate, ...],
        validation_text: str,
        validations: tuple[CandidateValidation, ...],
        artifact_history: ArtifactHistory,
        comparisons: tuple[PairComparison, ...],
        current_generation: RubricGeneration,
        has_pairs: bool,
        has_induction: bool,
        has_candidates: bool,
    ) -> tuple[
        _StageResult,
        _StageResult,
        _StageResult,
        _StageResult,
        _StageResult,
    ]:
        specifications = (
            (
                "assessment_rubric_free",
                rubric_free_text,
                rubric_free_value,
                has_pairs,
                self._assessment_fallback(
                    artifact_history,
                    AssessmentView.RUBRIC_FREE,
                    current_generation,
                ),
            ),
            (
                "assessment_active_rubric",
                active_rubric_text,
                active_rubric_value,
                has_pairs,
                self._assessment_fallback(
                    artifact_history,
                    AssessmentView.ACTIVE_RUBRIC,
                    current_generation,
                ),
            ),
            (
                "assessment_development_rubric",
                development_rubric_text,
                development_rubric_value,
                has_pairs,
                self._assessment_fallback(
                    artifact_history,
                    AssessmentView.DEVELOPMENT_RUBRIC,
                    current_generation,
                ),
            ),
            (
                "induction",
                induction_text,
                candidates,
                has_induction,
                canonical_json({"criteria": []}),
            ),
            (
                "validation",
                validation_text,
                validations,
                has_candidates,
                self._validation_fallback(candidates, comparisons),
            ),
        )
        results: list[_StageResult] = []
        for name, raw_text, value, required, fallback_text in specifications:
            count = metadata.get(f"{name}_attempt_count")
            fallback = metadata.get(f"{name}_fallback_reason")
            if (
                type(count) is not int
                or (required and not 1 <= count <= self.max_retries + 1)
                or (not required and count != 0)
                or (
                    fallback is not None
                    and (
                        type(fallback) is not str
                        or not fallback
                        or fallback != " ".join(fallback.split())
                        or raw_text != fallback_text
                    )
                )
                or (not required and fallback is not None)
                or (not required and raw_text != fallback_text)
            ):
                raise RuntimeError(
                    "completed rubric generation has invalid stage attempts"
                )
            results.append(_StageResult(raw_text, value, count, fallback))
        return (results[0], results[1], results[2], results[3], results[4])

    def _produce(
        self,
        *,
        instruction: str,
        original_rubric: CompleteRubric,
        development_rubric: CompleteRubric,
        current_generation: RubricGeneration,
        policy: RubricPolicy,
        generation_round: int,
        source_checkpoint: int | None,
        artifact_history: ArtifactHistory,
    ) -> _ProductionResult:
        if artifact_history.pairs:
            assessment_results = tuple(
                self._stage(
                    stage=stage,
                    evidence=assessment_evidence(
                        instruction=instruction,
                        artifact_history=artifact_history,
                        view=view,
                        rubric=rubric,
                        current_generation=current_generation,
                    ),
                    response_schema=assessment_schema(
                        artifact_history,
                        view=view,
                        current_generation=current_generation,
                    ),
                    validator=lambda text: validated_assessment_response(
                        text,
                        artifact_history=artifact_history,
                        view=view,
                        current_generation=current_generation,
                    ),
                    fallback_text=self._assessment_fallback(
                        artifact_history,
                        view,
                        current_generation,
                    ),
                )
                for stage, view, rubric in (
                    (
                        "assessment_rubric_free",
                        AssessmentView.RUBRIC_FREE,
                        None,
                    ),
                    (
                        "assessment_active_rubric",
                        AssessmentView.ACTIVE_RUBRIC,
                        original_rubric,
                    ),
                    (
                        "assessment_development_rubric",
                        AssessmentView.DEVELOPMENT_RUBRIC,
                        development_rubric,
                    ),
                )
            )
            rubric_free, active_rubric, development_rubric_result = (
                assessment_results
            )
        else:
            empty_results = tuple(
                _StageResult(
                    self._assessment_fallback(
                        artifact_history,
                        view,
                        current_generation,
                    ),
                    AssessmentResult(view, (), ()),
                    0,
                )
                for view in AssessmentView
            )
            rubric_free, active_rubric, development_rubric_result = empty_results

        comparisons = pair_comparisons(
            cast(AssessmentResult, rubric_free.value),
            cast(AssessmentResult, active_rubric.value),
            cast(AssessmentResult, development_rubric_result.value),
            artifact_history,
        )
        induction_gaps, validation_gaps = partition_gaps(
            comparisons,
            priority_induction_pair_ids=artifact_history.red_team_pair_ids,
        )
        comparisons_text = canonical_json(comparison_record(
            comparisons,
            induction_gaps,
            validation_gaps,
        )) + "\n"
        level_labels = required_level_labels(original_rubric)

        if induction_gaps:
            induction = self._stage(
                stage="induction",
                evidence=induction_evidence(
                    instruction=instruction,
                    current_generation=current_generation,
                    artifact_history=artifact_history,
                    induction_gaps=induction_gaps,
                    level_labels=level_labels,
                    include_red_team_trace=policy.uses_red_team_trace,
                ),
                response_schema=induction_schema(
                    level_labels,
                    induction_gaps,
                    current_generation,
                ),
                validator=lambda text: validated_induction_response(
                    text,
                    original_rubric=original_rubric,
                    current_generation=current_generation,
                    generation_round=generation_round,
                    level_labels=level_labels,
                    induction_gaps=induction_gaps,
                ),
                fallback_text=canonical_json({"criteria": []}),
            )
        else:
            induction = _StageResult(canonical_json({"criteria": []}), (), 0)
        candidates = cast(tuple[CriterionCandidate, ...], induction.value)

        if candidates:
            validation = self._stage(
                stage="validation",
                evidence=validation_evidence(
                    instruction=instruction,
                    current_generation=current_generation,
                    artifact_history=artifact_history,
                    candidates=candidates,
                    comparisons=comparisons,
                ),
                response_schema=validation_schema(
                    candidates,
                    validation_artifact_ids(comparisons),
                ),
                validator=lambda text: validated_validation_response(
                    text,
                    candidates=candidates,
                    artifact_ids=validation_artifact_ids(comparisons),
                ),
                fallback_text=self._validation_fallback(
                    candidates,
                    comparisons,
                ),
            )
        else:
            validation = _StageResult(
                canonical_json({"validations": []}),
                (),
                0,
            )
        validations = cast(tuple[CandidateValidation, ...], validation.value)
        accepted, admissions = admit_candidates(
            candidates,
            validations,
            comparisons,
            current_generation,
        )
        admissions_text = canonical_json(admission_record(admissions)) + "\n"
        active_criteria = update_criteria(current_generation, accepted)
        generation = self._build_generation(
            original_rubric=original_rubric,
            current_generation=current_generation,
            policy=policy,
            generation_round=generation_round,
            source_checkpoint=source_checkpoint,
            active_criteria=active_criteria,
        )
        return _ProductionResult(
            generation=generation,
            assessment_rubric_free=rubric_free,
            assessment_active_rubric=active_rubric,
            assessment_development_rubric=development_rubric_result,
            induction=induction,
            validation=validation,
            comparisons_text=comparisons_text,
            admissions_text=admissions_text,
            rubric_free_preference_count=len(comparisons),
            rubric_gap_count=sum(bool(item.gap_views) for item in comparisons),
            induction_pair_count=len(induction_gaps),
            validation_pair_count=len(validation_gaps),
            accepted_candidate_ids=tuple(
                item.criterion.criterion_id for item in accepted
            ),
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
        generation = RubricGeneration(
            generation_round=generation_round,
            source_checkpoint=(
                source_checkpoint if policy.uses_online_evidence else None
            ),
            rubric=render_augmented_rubric(original_rubric, active_criteria),
            elicited_criteria=active_criteria,
            proposer_call_budget=_STAGE_COUNT * (self.max_retries + 1),
        )
        generation.validate_successor(current_generation)
        return generation

    def _stage(
        self,
        *,
        stage: str,
        evidence: str,
        response_schema: dict[str, object],
        validator: Callable[[str], object],
        fallback_text: str,
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
                    stage=stage,
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
                assert isinstance(output, StructuredProviderOutput)
                value = validator(output.response_text)
            except (RuntimeError, ValueError) as exc:
                repair = str(exc) or type(exc).__name__
                continue
            return _StageResult(output.response_text, value, attempt)
        return _StageResult(
            raw_text=fallback_text,
            value=validator(fallback_text),
            attempt_count=attempt_count,
            fallback_reason=" ".join(
                (repair or "invalid structured response").split()
            ),
        )

    @staticmethod
    def _assessment_fallback(
        artifact_history: ArtifactHistory,
        view: AssessmentView,
        current_generation: RubricGeneration,
    ) -> str:
        record: dict[str, object] = {
            "assessments": [
                {
                    "pair_id": pair.pair_id,
                    "assessment_A": "Assessment unavailable.",
                    "assessment_B": "Assessment unavailable.",
                    "preference": "tie",
                    "reason": "No reliable pairwise judgment is available.",
                }
                for pair in artifact_history.pairs
            ]
        }
        if view is not AssessmentView.RUBRIC_FREE:
            record["rubric_scores"] = [
                {
                    "artifact_id": artifact_id,
                    "base_score": 0,
                    "criterion_levels": [
                        {
                            "criterion_id": criterion.criterion_id,
                            "level": criterion.levels[0][0],
                        }
                        for criterion in current_generation.elicited_criteria
                    ],
                    "reason": "Rubric scoring is unavailable.",
                }
                for artifact_id in validation_artifact_ids_from_history(
                    artifact_history
                )
            ]
        return canonical_json(record)

    @staticmethod
    def _validation_fallback(
        candidates: tuple[CriterionCandidate, ...],
        comparisons: tuple[PairComparison, ...],
    ) -> str:
        artifact_ids = validation_artifact_ids(comparisons)
        return canonical_json({
            "validations": [
                {
                    "criterion_id": candidate.criterion.criterion_id,
                    "observable": False,
                    "nonredundant": False,
                    "artifact_applications": [
                        {
                            "artifact_id": artifact_id,
                            "level": candidate.criterion.levels[0][0],
                            "reason": "Candidate validation is unavailable.",
                        }
                        for artifact_id in artifact_ids
                    ],
                    "reason": "The candidate was not validated.",
                }
                for candidate in candidates
            ]
        })

    def _context(
        self,
        *,
        instruction: str,
        original_rubric: CompleteRubric,
        development_rubric: CompleteRubric,
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
            "development_rubric_sha256": development_rubric.content_sha256,
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
        stages = {
            "assessment_rubric_free": result.assessment_rubric_free,
            "assessment_active_rubric": result.assessment_active_rubric,
            "assessment_development_rubric": (
                result.assessment_development_rubric
            ),
            "induction": result.induction,
            "validation": result.validation,
        }
        record: dict[str, object] = {
            "kind": "pairwise-rubric-induction",
            "implementation_sha256": rubric_generation_implementation_sha256(),
            "context": context,
            "prior_generation_sha256": context["prior_generation_sha256"],
            "generation_sha256": result.generation.generation_sha256,
            "original_rubric_sha256": context["original_rubric_sha256"],
            "development_rubric_sha256": context["development_rubric_sha256"],
            "elicited_criterion_ids": [
                item.criterion_id for item in result.generation.elicited_criteria
            ],
            "accepted_candidate_ids": list(result.accepted_candidate_ids),
            "pairwise_comparisons_sha256": sha256_text(
                result.comparisons_text
            ),
            "aggregate_margins_sha256": sha256_text(
                result.admissions_text
            ),
            "rubric_free_preference_count": (
                result.rubric_free_preference_count
            ),
            "rubric_gap_count": result.rubric_gap_count,
            "induction_pair_count": result.induction_pair_count,
            "validation_pair_count": result.validation_pair_count,
            "proposer_call_budget": (
                _STAGE_COUNT * (self.max_retries + 1)
            ),
            "scoring_feasibility": validate_generation_scoring_structure(
                result.generation,
                benchmark=self.benchmark,
            ),
        }
        for name, stage in stages.items():
            record[f"{name}_sha256"] = sha256_text(stage.raw_text)
            record[f"{name}_attempt_count"] = stage.attempt_count
            record[f"{name}_fallback_reason"] = stage.fallback_reason
        return record

    def _run_direct_proposer(
        self,
        *,
        stage: str,
        evidence: str,
        response_schema: dict[str, object],
    ) -> StructuredProviderOutput:
        instructions = {
            "assessment_rubric_free": assessment_instructions(
                AssessmentView.RUBRIC_FREE
            ),
            "assessment_active_rubric": assessment_instructions(
                AssessmentView.ACTIVE_RUBRIC
            ),
            "assessment_development_rubric": assessment_instructions(
                AssessmentView.DEVELOPMENT_RUBRIC
            ),
            "induction": induction_instructions(),
            "validation": validation_instructions(),
        }.get(stage)
        if instructions is None:
            raise ValueError(f"unknown rubric induction stage: {stage}")
        return self.proposer_contract.generate(
            instructions=instructions,
            evidence=evidence,
            response_schema=response_schema,
            request_context="pairwise rubric induction",
            schema_name=f"rubric_{stage}",
        )
