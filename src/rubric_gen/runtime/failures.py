"""Classify operational failures before the existing bounded retry owner acts."""
from __future__ import annotations


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
