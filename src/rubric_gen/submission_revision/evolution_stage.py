"""Bounded proposer invocation, validation repair, and successful-call reuse."""
from collections.abc import Callable
import time
from rubric_gen.submission_revision.evolution_cache import ValidatedProposerCache
from rubric_gen.submission_revision.evolution_provider import ProviderContract, StructuredProviderOutput, RubricProposerProviderError, RubricProposerInputLimitError
from rubric_gen.submission_revision.evolution_validation import ValidationStageResult

PROVIDER_FAILURE_MAX_RETRIES = 3

def maximum_stage_attempts(max_retries: int) -> int:
    return max_retries + 1 + PROVIDER_FAILURE_MAX_RETRIES


def run_stage(
    *,
    max_retries: int,
    contract: ProviderContract,
    run_proposer: Callable[..., StructuredProviderOutput],
    cache: ValidatedProposerCache | None,
    stage: str,
    evidence: str,
    response_schema: dict[str, object],
    validator: Callable[[str], object],
    fallback_text: str,
) -> ValidationStageResult:
    repair: str | None = None
    provider_failures = 0
    attempt_count = 0
    validated_responses = 0
    while validated_responses < max_retries + 1:
        attempt_count += 1
        attempt = attempt_count
        attempt_evidence = evidence
        if repair is not None:
            attempt_evidence += (
                "\n\n<repair>\nThe prior response failed validation.\n"
                + repair
                + "\nReturn a complete corrected response.\n</repair>"
            )
        request = {"stage": stage, "evidence": attempt_evidence, "response_schema": response_schema}
        cached = cache.load(request) if cache is not None else None
        try:
            output = cached or run_proposer(
                stage=stage,
                evidence=attempt_evidence,
                response_schema=response_schema,
            )
        except RubricProposerInputLimitError:
            # Identical input cannot recover through a provider retry.
            raise
        except Exception as exc:
            provider_failures += 1
            status = getattr(exc, "status_code", None)
            code = getattr(exc, "code", None)
            permanent = (status in {400, 401, 403, 404, 422}
                         or code in {"insufficient_quota", "invalid_api_key"})
            if permanent or provider_failures > PROVIDER_FAILURE_MAX_RETRIES:
                raise RubricProposerProviderError(
                    f"Rubric proposer stage {stage} failed after {attempt} "
                    f"attempts ({provider_failures} provider failures; "
                    f"last error: {type(exc).__name__})"
                ) from exc
            time.sleep(min(0.5 * (2 ** (provider_failures - 1)), 8.0))
            continue
        validated_responses += 1
        try:
            contract.validate_output(output)
            assert isinstance(output, StructuredProviderOutput)
            value = validator(output.response_text)
        except (RuntimeError, ValueError) as exc:
            repair = str(exc) or type(exc).__name__
            continue
        if cache is not None and cached is None:
            cache.save(request, output)
        return ValidationStageResult(output.response_text, value, attempt)
    return ValidationStageResult(
        raw_text=fallback_text,
        value=validator(fallback_text),
        attempt_count=attempt_count,
        fallback_reason=" ".join(
            (repair or "invalid structured response").split()
        ),
    )

