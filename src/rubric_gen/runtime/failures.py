"""Classify operational failures before the existing bounded retry owner acts."""
from __future__ import annotations

import os


REPAIRED_PROVIDER_FAILURES_ENV = "RUBRIC_GEN_REPAIRED_PROVIDER_FAILURES"
_REPAIRABLE_PROVIDER_FAILURES = frozenset({"authentication", "billing"})
_PERSISTED_BILLING_MARKERS = (
    "billing_hard_limit_reached",
    "credit_balance_exhausted",
    "credit_balance_too_low",
    "insufficient_quota",
)


def retry_repaired_provider_failure(category: object) -> bool:
    """Allow an explicit resume to spend only the remaining attempt budget.

    Authentication and billing failures are normally terminal because blindly
    retrying them cannot help.  After the external condition is independently
    repaired, an operator may name that exact category.  Existing attempts stay
    immutable and the normal loop advances to the next numbered attempt.
    """
    raw = os.environ.get(REPAIRED_PROVIDER_FAILURES_ENV)
    if raw is None:
        return False
    requested = {item.strip() for item in raw.split(",") if item.strip()}
    invalid = requested - _REPAIRABLE_PROVIDER_FAILURES
    if not requested or invalid:
        allowed = ", ".join(sorted(_REPAIRABLE_PROVIDER_FAILURES))
        raise RuntimeError(
            f"{REPAIRED_PROVIDER_FAILURES_ENV} must name a comma-separated "
            f"subset of: {allowed}"
        )
    return category in requested


def persisted_provider_failure_category(record: object) -> object:
    """Recover an exact provider category from an older saved error payload.

    Some historical OpenAI 429 records were labeled ``transient_provider``
    even though their immutable error text retained the billing error code.
    This read-only normalization is used only by the explicit repair resume.
    """

    if not isinstance(record, dict):
        return None
    error = record.get("error")
    if isinstance(error, str):
        normalized = error.lower()
        if any(marker in normalized for marker in _PERSISTED_BILLING_MARKERS):
            return "billing"
    return record.get("category", record.get("failure_category"))


def failure_category(error: BaseException) -> str:
    seen = set()
    current = error
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        status = getattr(current, 'status_code', None)
        code = getattr(current, 'code', None)
        body = getattr(current, 'body', None)
        if isinstance(body, dict):
            detail = body.get('error', body)
            if isinstance(detail, dict):
                code = detail.get('code', code)
        if code in {'insufficient_quota', 'billing_hard_limit_reached', 'credit_balance_too_low'}:
            return 'billing'
        if status in {401, 403}:
            return 'authentication'
        if status in {400, 404, 422}:
            return 'configuration'
        if status in {408, 409, 429, 500, 502, 503, 504, 529}:
            return 'transient_provider'
        if type(current).__name__ in {'APITimeoutError', 'APIConnectionError', 'TimeoutException',
                                     'ConnectError', 'ReadTimeout', 'ConnectionError', 'TimeoutError',
                                     'IncompleteProviderResponse', 'IncompleteRead', 'RemoteDisconnected'}:
            return 'transient_connection'
        current = current.__cause__
    return 'structural'


def retry_after(error: BaseException, attempt: int) -> float:
    headers = getattr(getattr(error, 'response', None), 'headers', {})
    value = headers.get('retry-after')
    if value is not None:
        try:
            return max(0.0, float(value))
        except (ValueError, TypeError):
            from email.utils import parsedate_to_datetime
            from datetime import datetime, timezone
            try:
                return max(0.0, (parsedate_to_datetime(value) - datetime.now(timezone.utc)).total_seconds())
            except (ValueError, TypeError):
                pass
    return min(2 ** (attempt - 1), 8)
