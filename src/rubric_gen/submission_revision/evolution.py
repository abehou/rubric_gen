"""Elicit bounded rubric criteria from a blinded artifact history."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.bank_scoring import (
    validate_bank_scoring_structure,
)
from rubric_gen.submission_revision.evolution_artifacts import (
    ArtifactHistory,
    validate_artifact_history,
)
from rubric_gen.submission_revision.evolution_ledger import (
    ProviderLedger,
    RecordedProviderFailure,
)
from rubric_gen.submission_revision.evolution_protocol import (
    abandoned_editor_response,
    criterion_evidence,
    criterion_instructions,
    criterion_schema,
    difference_evidence,
    difference_instructions,
    difference_schema,
    editor_evidence,
    editor_instructions,
    editor_schema,
    required_level_labels,
    validated_criterion_response,
    validated_difference_response,
    validated_editor_response,
)
from rubric_gen.submission_revision.evolution_provider import (
    MAX_SEMANTIC_REVIEW_OUTPUT_TOKENS,
    MAX_SEMANTIC_REVIEW_REQUEST_BYTES,
    PROPOSER_MAX_OUTPUT_TOKENS,
    PROPOSER_MAX_REQUEST_BYTES,
    ProviderContract,
    ProviderOperation,
    StructuredProviderOutput,
    attempt_record,
    failed_attempt_record,
)
from rubric_gen.submission_revision.evolution_serialization import (
    canonical_json,
    canonical_sha256,
)
from rubric_gen.submission_revision.evolution_store import publish_generation
from rubric_gen.submission_revision.rubric_bank import (
    ElicitedCriterion,
    RubricBank,
    RubricBankItem,
    RubricBankPolicy,
    RubricLineage,
    elicited_criterion_capacity,
    render_augmented_rubric,
)
from rubric_gen.submission_revision.rubric_bank_lifecycle import RubricBankGeneration


_LEDGER_SUFFIX = ".provider-attempts.json"
def rubric_generation_implementation_identity() -> dict[str, str]:
    """Return the scoped local-source identity for elicitation and replay."""

    package_root = Path(__file__).parent
    paths = {
        "evolution_sha256": Path(__file__),
        "evolution_artifacts_sha256": package_root / "evolution_artifacts.py",
        "evolution_ledger_sha256": package_root / "evolution_ledger.py",
        "evolution_protocol_sha256": package_root / "evolution_protocol.py",
        "evolution_provider_sha256": package_root / "evolution_provider.py",
        "evolution_serialization_sha256": (
            package_root / "evolution_serialization.py"
        ),
        "evolution_store_sha256": package_root / "evolution_store.py",
        "rubric_bank_sha256": package_root / "rubric_bank.py",
        "rubric_bank_lifecycle_sha256": (
            package_root / "rubric_bank_lifecycle.py"
        ),
        "autorubric_sha256": package_root / "autorubric.py",
        "bank_scoring_sha256": package_root / "bank_scoring.py",
        "artifact_history_builder_sha256": package_root / "contrasts.py",
        "full_rubric_judge_sha256": (
            package_root / "judging" / "full_rubric_judge.py"
        ),
        "judge_models_sha256": package_root / "judging" / "models.py",
        "judge_scoring_sha256": package_root / "judging" / "scoring.py",
        "serialization_sha256": (
            package_root.parent / "artifacts" / "serialization.py"
        ),
        "hashing_sha256": package_root.parent / "artifacts" / "hashing.py",
        "llm_runner_sha256": package_root.parent / "runtime" / "llm.py",
    }
    return {key: sha256_file(path) for key, path in paths.items()}


@dataclass(frozen=True)
class _StageResult:
    raw_text: str
    value: object
    attempts: tuple[dict[str, object], ...]


@dataclass(frozen=True)
class _ProductionResult:
    bank: RubricBank
    difference: _StageResult
    criteria: _StageResult
    editor: _StageResult


class RubricBankProposer:
    """Elicit general missing criteria from a blinded artifact history."""

    def __init__(
        self,
        *,
        benchmark: SubmissionBenchmarkId,
        model: str,
        base_url: str | None,
        semantic_judge_model: str,
        semantic_judge_base_url: str | None,
        semantic_judge_max_calls: int,
        semantic_judge_max_request_bytes: int,
        semantic_judge_max_output_tokens: int,
        max_retries: int = 2,
        service_tier: str | None = None,
        run_proposer: ProviderOperation | None = None,
        run_semantic_reviewer: ProviderOperation | None = None,
    ) -> None:
        if not isinstance(benchmark, SubmissionBenchmarkId):
            raise ValueError("rubric proposer benchmark is invalid")
        if type(semantic_judge_max_calls) is not int or semantic_judge_max_calls < 0:
            raise ValueError("rubric semantic reviewer call cap must be non-negative")
        if (
            type(semantic_judge_max_request_bytes) is not int
            or not 1 <= semantic_judge_max_request_bytes
            <= MAX_SEMANTIC_REVIEW_REQUEST_BYTES
        ):
            raise ValueError("semantic reviewer request-byte cap is invalid")
        if (
            type(semantic_judge_max_output_tokens) is not int
            or not 1 <= semantic_judge_max_output_tokens
            <= MAX_SEMANTIC_REVIEW_OUTPUT_TOKENS
        ):
            raise ValueError("semantic reviewer output-token cap is invalid")
        if type(max_retries) is not int or max_retries < 0:
            raise ValueError("rubric proposer retries must be non-negative")
        self.benchmark = benchmark
        self.semantic_judge_max_calls = semantic_judge_max_calls
        self.max_retries = max_retries
        self.proposer_contract = ProviderContract(
            model=model,
            base_url=base_url,
            max_output_tokens=PROPOSER_MAX_OUTPUT_TOKENS,
            max_request_bytes=PROPOSER_MAX_REQUEST_BYTES,
            service_tier=service_tier,
        )
        self.semantic_reviewer_contract = ProviderContract(
            model=semantic_judge_model,
            base_url=semantic_judge_base_url,
            max_output_tokens=semantic_judge_max_output_tokens,
            max_request_bytes=semantic_judge_max_request_bytes,
            service_tier=service_tier,
        )
        self.run_proposer = run_proposer or self._run_direct_proposer
        self.run_semantic_reviewer = (
            run_semantic_reviewer or self._run_direct_semantic_reviewer
        )

    def elicit_rubric(
        self,
        *,
        instruction: str,
        current_bank: RubricBank,
        policy: RubricBankPolicy,
        generation_round: int,
        output_dir: Path,
        artifact_history: ArtifactHistory,
        source_boundary: int | None = None,
    ) -> RubricBankGeneration:
        """Return the next single rubric after bounded criterion elicitation."""

        if type(instruction) is not str or not instruction.strip():
            raise ValueError("task instruction must be nonempty")
        if not isinstance(current_bank, RubricBank):
            raise ValueError("current_bank must be a RubricBank")
        if type(policy) is not RubricBankPolicy or policy not in {
            RubricBankPolicy.OFFLINE_ELICITATION,
            RubricBankPolicy.ONLINE_ELICITATION,
        }:
            raise ValueError("criterion elicitation requires an elicitation policy")
        if type(generation_round) is not int:
            raise ValueError("generation_round must be an integer")
        if generation_round != current_bank.generation_round + 1:
            raise ValueError("rubric generations must be consecutive")
        if generation_round > self.semantic_judge_max_calls:
            raise RuntimeError("semantic reviewer call schedule is exhausted")
        if policy is RubricBankPolicy.OFFLINE_ELICITATION:
            if generation_round != 1:
                raise ValueError(
                    "offline elicitation has one pre-treatment generation"
                )
            if source_boundary is not None:
                raise ValueError("offline elicitation cannot use a live boundary")
        elif type(source_boundary) is not int or source_boundary != generation_round:
            raise ValueError("online elicitation needs the matching live boundary")
        artifact_history = validate_artifact_history(artifact_history)
        context = self._context(
            instruction=instruction,
            current_bank=current_bank,
            policy=policy,
            generation_round=generation_round,
            source_boundary=source_boundary,
            artifact_history=artifact_history,
        )
        output_dir.mkdir(parents=True, exist_ok=True)
        ledger_path = output_dir / (
            f"bank-{generation_round:04d}{_LEDGER_SUFFIX}"
        )
        ledger = ProviderLedger(
            ledger_path,
            context=context,
            implementation_identity=rubric_generation_implementation_identity(),
        )
        result = self._produce(
            instruction=instruction,
            current_bank=current_bank,
            policy=policy,
            generation_round=generation_round,
            source_boundary=source_boundary,
            artifact_history=artifact_history,
            ledger=ledger,
        )

        generation = RubricBankGeneration(
            bank=result.bank,
            proposer_call_budget=2 * (self.max_retries + 1),
        )
        metadata = self._generation_record(
            context=context,
            ledger_path=ledger_path,
            result=result,
        )
        history_payload = {
            "kind": "blinded-artifact-history",
            **artifact_history.artifact_record(),
        }
        expected_files = {
            "artifact-history.json": canonical_json(history_payload) + "\n",
            "difference-proposal.json": result.difference.raw_text,
            "criterion-proposal.json": result.criteria.raw_text,
            "criterion-edit.json": result.editor.raw_text,
            "generation.json": canonical_json(metadata) + "\n",
        }
        publish_generation(
            output_dir,
            generation_round,
            expected_files,
        )
        ledger.seal()
        return generation


    def _produce(
        self,
        *,
        instruction: str,
        current_bank: RubricBank,
        policy: RubricBankPolicy,
        generation_round: int,
        source_boundary: int | None,
        artifact_history: ArtifactHistory,
        ledger: ProviderLedger,
    ) -> _ProductionResult:
        difference_evidence_value = difference_evidence(
            instruction=instruction,
            current_bank=current_bank,
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
            ledger=ledger,
        )
        assert isinstance(difference.value, dict)
        existing_criterion_count = len(
            current_bank.items[0].elicited_criteria
        )
        remaining = (
            elicited_criterion_capacity(current_bank.specification_anchor)
            - existing_criterion_count
        )
        level_labels = required_level_labels(current_bank.specification_anchor)
        criterion_evidence_value = criterion_evidence(
            instruction=instruction,
            current_bank=current_bank,
            artifact_history=artifact_history,
            difference_response=difference.value,
            remaining_capacity=remaining,
            level_labels=level_labels,
        )
        criteria = self._proposer_stage(
            role="criteria",
            instructions=criterion_instructions(),
            evidence=criterion_evidence_value,
            response_schema=criterion_schema(
                remaining,
                level_labels,
                artifact_history,
            ),
            validator=lambda value: validated_criterion_response(
                value,
                instruction=instruction,
                current_bank=current_bank,
                generation_round=generation_round,
                remaining_capacity=remaining,
                level_labels=level_labels,
                artifact_history=artifact_history,
            ),
            ledger=ledger,
        )
        assert isinstance(criteria.value, tuple)
        editor_evidence_value = editor_evidence(
            instruction=instruction,
            current_bank=current_bank,
            artifact_history=artifact_history,
            difference_response=difference.value,
            proposed_criteria=criteria.value,
        )
        editor = self._editor_stage(
            evidence=editor_evidence_value,
            response_schema=editor_schema(
                criteria.value,
                level_labels,
                artifact_history,
            ),
            validator=lambda value: validated_editor_response(
                value,
                criteria.value,
                instruction=instruction,
                current_bank=current_bank,
                generation_round=generation_round,
                remaining_capacity=remaining,
                level_labels=level_labels,
                artifact_history=artifact_history,
            ),
            source_criteria=criteria.value,
            ledger=ledger,
        )
        ledger.require_consumed()
        assert isinstance(editor.value, dict)
        edited_criteria = editor.value["criteria"]
        assert isinstance(edited_criteria, tuple)
        all_criteria = current_bank.items[0].elicited_criteria + edited_criteria
        next_rubric, criterion_map = render_augmented_rubric(
            current_bank.specification_anchor,
            all_criteria,
        )
        prior_item = current_bank.items[0]
        lineage = (
            RubricLineage.RETAINED
            if next_rubric == prior_item.rubric
            else RubricLineage.REFINED
        )
        bank = RubricBank(
            generation_round=generation_round,
            source_boundary=(
                source_boundary
                if policy is RubricBankPolicy.ONLINE_ELICITATION
                else None
            ),
            specification_anchor=current_bank.specification_anchor,
            specification_anchor_lineage=RubricLineage.RETAINED,
            prior_specification_anchor_sha256=(
                current_bank.specification_anchor.content_sha256
            ),
            items=(RubricBankItem(
                rubric=next_rubric,
                weight=1.0,
                lineage=lineage,
                prior_content_sha256=prior_item.rubric.content_sha256,
                criterion_map=criterion_map,
                elicited_criteria=all_criteria,
            ),),
        )
        bank.validate_lineage(current_bank)
        return _ProductionResult(
            bank=bank,
            difference=difference,
            criteria=criteria,
            editor=editor,
        )

    def _proposer_stage(
        self,
        *,
        role: str,
        instructions: str,
        evidence: str,
        response_schema: dict[str, object],
        validator: Callable[[str], object],
        ledger: ProviderLedger,
    ) -> _StageResult:
        attempts: list[dict[str, object]] = []
        repair: str | None = None
        for attempt in range(1, self.max_retries + 2):
            attempt_evidence = evidence
            if repair is not None:
                attempt_evidence += (
                    "\n\n<repair>\nThe prior response failed validation.\n"
                    + repair
                    + "\nReturn a complete corrected response.\n</repair>"
                )
            request = self.proposer_contract.request_identity(
                role=role,
                instructions=instructions,
                evidence=attempt_evidence,
                response_schema=response_schema,
                implementation_identity=(
                    rubric_generation_implementation_identity()
                ),
            )
            try:
                output = ledger.output(
                    role=role,
                    attempt=attempt,
                    request=request,
                    generate=lambda: self.run_proposer(
                        stage=role,
                        evidence=attempt_evidence,
                        response_schema=response_schema,
                    ),
                    contract=self.proposer_contract,
                )
            except RecordedProviderFailure as exc:
                repair = str(exc)
                attempts.append(failed_attempt_record(attempt, repair))
                continue
            assert isinstance(output, StructuredProviderOutput)
            try:
                value = validator(output.response_text)
            except ValueError as exc:
                repair = str(exc)
                attempts.append(
                    attempt_record(output, attempt=attempt)
                    | {"validation_error": repair}
                )
                continue
            attempts.append(
                attempt_record(output, attempt=attempt)
                | {"validation_error": None}
            )
            return _StageResult(
                raw_text=output.response_text,
                value=value,
                attempts=tuple(attempts),
            )
        ledger.seal_failed_stage()
        raise RuntimeError(
            f"{role} proposer failed after {self.max_retries + 1} calls: "
            f"{repair}"
        )

    def _editor_stage(
        self,
        *,
        evidence: str,
        response_schema: dict[str, object],
        validator: Callable[[str], object],
        source_criteria: tuple[ElicitedCriterion, ...],
        ledger: ProviderLedger,
    ) -> _StageResult:
        if not source_criteria:
            raw_text = canonical_json({"actions": []})
            return _StageResult(raw_text, validator(raw_text), ())

        attempts: list[dict[str, object]] = []
        repair: str | None = None
        for attempt in range(1, self.max_retries + 2):
            attempt_evidence = evidence
            if repair is not None:
                attempt_evidence += (
                    "\n\n<repair>\nThe prior editor response failed validation.\n"
                    + repair
                    + "\nUse distinct support pairs from the supplied full history. "
                    "If no valid repair exists, drop the affected criterion.\n"
                    "Return a complete corrected response.\n</repair>"
                )
            request = self.semantic_reviewer_contract.request_identity(
                role="editor",
                instructions=editor_instructions(),
                evidence=attempt_evidence,
                response_schema=response_schema,
                implementation_identity=(
                    rubric_generation_implementation_identity()
                ),
            )
            try:
                output = ledger.output(
                    role="editor",
                    attempt=attempt,
                    request=request,
                    generate=lambda: self.run_semantic_reviewer(
                        evidence=attempt_evidence,
                        response_schema=response_schema,
                    ),
                    contract=self.semantic_reviewer_contract,
                )
            except RecordedProviderFailure as exc:
                repair = str(exc)
                attempts.append(failed_attempt_record(attempt, repair))
                continue
            assert isinstance(output, StructuredProviderOutput)
            try:
                value = validator(output.response_text)
            except ValueError as exc:
                repair = str(exc)
                attempts.append(
                    attempt_record(output, attempt=attempt)
                    | {"validation_error": repair}
                )
                continue
            attempts.append(
                attempt_record(output, attempt=attempt)
                | {"validation_error": None}
            )
            return _StageResult(
                raw_text=output.response_text,
                value=value,
                attempts=tuple(attempts),
            )

        fallback = abandoned_editor_response(source_criteria, repair)
        return _StageResult(
            raw_text=fallback,
            value=validator(fallback),
            attempts=tuple(attempts),
        )

    def _context(
        self,
        *,
        instruction: str,
        current_bank: RubricBank,
        policy: RubricBankPolicy,
        generation_round: int,
        source_boundary: int | None,
        artifact_history: ArtifactHistory,
    ) -> dict[str, object]:
        return {
            "benchmark": self.benchmark.value,
            "policy": policy.value,
            "generation_round": generation_round,
            "source_boundary": source_boundary,
            "instruction_sha256": sha256_text(instruction),
            "prior_bank_sha256": current_bank.content_sha256,
            "original_rubric_sha256": (
                current_bank.specification_anchor.content_sha256
            ),
            "artifact_history_sha256": canonical_sha256(
                artifact_history.artifact_record()
            ),
            "proposer": self.proposer_contract.record(),
            "semantic_reviewer": self.semantic_reviewer_contract.record(),
            "max_retries": self.max_retries,
        }

    def _generation_record(
        self,
        *,
        context: dict[str, object],
        ledger_path: Path,
        result: _ProductionResult,
    ) -> dict[str, object]:
        return {
            "kind": "criterion-elicitation-generation",
            "implementation_identity": rubric_generation_implementation_identity(),
            "context": context,
            "prior_bank_sha256": context["prior_bank_sha256"],
            "next_bank_sha256": result.bank.content_sha256,
            "original_rubric_sha256": result.bank.specification_anchor.content_sha256,
            "elicited_criterion_ids": [
                item.criterion_id
                for item in result.bank.items[0].elicited_criteria
            ],
            "difference_proposal_sha256": sha256_text(result.difference.raw_text),
            "criterion_proposal_sha256": sha256_text(result.criteria.raw_text),
            "criterion_edit_sha256": sha256_text(result.editor.raw_text),
            "provider_ledger_sha256": sha256_file(ledger_path),
            "proposer_call_budget": 2 * (self.max_retries + 1),
            "difference_stage": list(result.difference.attempts),
            "criterion_stage": list(result.criteria.attempts),
            "criterion_edit_stage": list(result.editor.attempts),
            "scoring_feasibility": validate_bank_scoring_structure(
                result.bank,
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
            else criterion_instructions()
        )
        return self.proposer_contract.generate(
            instructions=instructions,
            evidence=evidence,
            response_schema=response_schema,
            request_context="rubric proposer",
            schema_name=f"rubric_{stage}",
        )

    def _run_direct_semantic_reviewer(
        self,
        *,
        evidence: str,
        response_schema: dict[str, object],
    ) -> StructuredProviderOutput:
        return self.semantic_reviewer_contract.generate(
            instructions=editor_instructions(),
            evidence=evidence,
            response_schema=response_schema,
            request_context="rubric semantic reviewer",
            schema_name="rubric_semantic_review",
        )
