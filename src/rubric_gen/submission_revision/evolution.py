"""Elicit bounded rubric criteria from a blinded artifact history."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.bank_scoring import (
    validate_bank_scoring_structure,
)
from rubric_gen.submission_revision.evolution_artifacts import (
    ArtifactHistory,
    validate_artifact_history,
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
)
from rubric_gen.submission_revision.evolution_serialization import (
    canonical_json,
    canonical_sha256,
    load_json_object,
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


def rubric_generation_implementation_sha256() -> str:
    """Return one hash for the code that creates and checks rubric generations."""

    package_root = Path(__file__).parent
    paths = (
        Path(__file__),
        package_root / "evolution_artifacts.py",
        package_root / "evolution_protocol.py",
        package_root / "evolution_provider.py",
        package_root / "evolution_serialization.py",
        package_root / "evolution_store.py",
        package_root / "rubric_bank.py",
        package_root / "rubric_bank_lifecycle.py",
        package_root / "autorubric.py",
        package_root / "bank_scoring.py",
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
        try:
            completed = self._load_completed_generation(
                instruction=instruction,
                current_bank=current_bank,
                policy=policy,
                generation_round=generation_round,
                source_boundary=source_boundary,
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
            current_bank=current_bank,
            policy=policy,
            generation_round=generation_round,
            source_boundary=source_boundary,
            artifact_history=artifact_history,
        )

        generation = RubricBankGeneration(
            bank=result.bank,
            proposer_call_budget=2 * (self.max_retries + 1),
        )
        metadata = self._generation_record(
            context=context,
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
        return generation

    def _load_completed_generation(
        self,
        *,
        instruction: str,
        current_bank: RubricBank,
        policy: RubricBankPolicy,
        generation_round: int,
        source_boundary: int | None,
        artifact_history: ArtifactHistory,
        context: dict[str, object],
        output_dir: Path,
    ) -> RubricBankGeneration | None:
        root = output_dir / f"bank-{generation_round:04d}"
        if not root.exists():
            return None
        expected_names = {
            "artifact-history.json",
            "difference-proposal.json",
            "criterion-proposal.json",
            "criterion-edit.json",
            "generation.json",
        }
        if (
            root.is_symlink()
            or not root.is_dir()
            or {path.name for path in root.iterdir()} != expected_names
            or any(path.is_symlink() or not path.is_file() for path in root.iterdir())
        ):
            raise RuntimeError("completed rubric generation is incomplete")
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
        existing_count = len(current_bank.items[0].elicited_criteria)
        remaining = (
            elicited_criterion_capacity(current_bank.specification_anchor)
            - existing_count
        )
        level_labels = required_level_labels(current_bank.specification_anchor)
        criterion_text = (root / "criterion-proposal.json").read_text()
        criterion_value = validated_criterion_response(
            criterion_text,
            instruction=instruction,
            current_bank=current_bank,
            generation_round=generation_round,
            remaining_capacity=remaining,
            level_labels=level_labels,
            artifact_history=artifact_history,
        )
        editor_text = (root / "criterion-edit.json").read_text()
        editor_value = validated_editor_response(
            editor_text,
            criterion_value,
            instruction=instruction,
            current_bank=current_bank,
            generation_round=generation_round,
            remaining_capacity=remaining,
            level_labels=level_labels,
            artifact_history=artifact_history,
        )
        edited_criteria = editor_value["criteria"]
        assert isinstance(edited_criteria, tuple)
        bank = self._build_bank(
            current_bank=current_bank,
            policy=policy,
            generation_round=generation_round,
            source_boundary=source_boundary,
            edited_criteria=edited_criteria,
        )
        metadata = load_json_object(
            (root / "generation.json").read_text(),
            "completed rubric generation",
        )
        counts = (
            metadata.get("difference_attempt_count"),
            metadata.get("criterion_attempt_count"),
            metadata.get("criterion_edit_attempt_count"),
        )
        if (
            any(type(value) is not int for value in counts)
            or not 1 <= counts[0] <= self.max_retries + 1
            or not 1 <= counts[1] <= self.max_retries + 1
            or counts[2]
            not in (
                range(1, self.max_retries + 2)
                if criterion_value
                else (0,)
            )
        ):
            raise RuntimeError("completed rubric generation has invalid attempts")
        difference = _StageResult(difference_text, difference_value, counts[0])
        criteria = _StageResult(criterion_text, criterion_value, counts[1])
        editor = _StageResult(editor_text, editor_value, counts[2])
        result = _ProductionResult(bank, difference, criteria, editor)
        if metadata != self._generation_record(context=context, result=result):
            raise RuntimeError("completed rubric generation changed")
        return RubricBankGeneration(
            bank=bank,
            proposer_call_budget=2 * (self.max_retries + 1),
        )


    def _produce(
        self,
        *,
        instruction: str,
        current_bank: RubricBank,
        policy: RubricBankPolicy,
        generation_round: int,
        source_boundary: int | None,
        artifact_history: ArtifactHistory,
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
        )
        assert isinstance(editor.value, dict)
        edited_criteria = editor.value["criteria"]
        assert isinstance(edited_criteria, tuple)
        bank = self._build_bank(
            current_bank=current_bank,
            policy=policy,
            generation_round=generation_round,
            source_boundary=source_boundary,
            edited_criteria=edited_criteria,
        )
        return _ProductionResult(
            bank=bank,
            difference=difference,
            criteria=criteria,
            editor=editor,
        )

    @staticmethod
    def _build_bank(
        *,
        current_bank: RubricBank,
        policy: RubricBankPolicy,
        generation_round: int,
        source_boundary: int | None,
        edited_criteria: tuple[ElicitedCriterion, ...],
    ) -> RubricBank:
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
        return bank

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
        for attempt in range(1, self.max_retries + 2):
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
    ) -> _StageResult:
        if not source_criteria:
            raw_text = canonical_json({"actions": []})
            return _StageResult(raw_text, validator(raw_text), 0)

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
            try:
                output = self.run_semantic_reviewer(
                    evidence=attempt_evidence,
                    response_schema=response_schema,
                )
                self.semantic_reviewer_contract.validate_output(output)
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

        fallback = abandoned_editor_response(source_criteria, repair)
        return _StageResult(
            raw_text=fallback,
            value=validator(fallback),
            attempt_count=self.max_retries + 1,
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
        result: _ProductionResult,
    ) -> dict[str, object]:
        return {
            "kind": "criterion-elicitation-generation",
            "implementation_sha256": rubric_generation_implementation_sha256(),
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
            "proposer_call_budget": 2 * (self.max_retries + 1),
            "difference_attempt_count": result.difference.attempt_count,
            "criterion_attempt_count": result.criteria.attempt_count,
            "criterion_edit_attempt_count": result.editor.attempt_count,
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
