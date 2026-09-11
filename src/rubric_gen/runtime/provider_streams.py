"""Consume a single provider stream, accepting only a completed response.

The SDK's HTTP read timeout bounds network inactivity, including while waiting
for headers. Iteration has no total deadline; the judge subprocess separately
bounds a wedged process. SDK clients and streams are closed on every exit.
"""

import httpx


def anthropic_response(*, api_key, timeout, **request):
    from anthropic import Anthropic, APIConnectionError, APITimeoutError

    try:
        with Anthropic(api_key=api_key, timeout=timeout, max_retries=0) as client:
            with client.messages.stream(**request) as stream:
                complete = False
                for event in stream:
                    if event.type == "message_stop":
                        complete = True
                if not complete:
                    raise RuntimeError("Anthropic stream ended without message_stop")
                return stream.get_final_message()
    # SDKs wrap initial request failures, but iteration exposes HTTPX errors.
    # Keep the existing retry/error classification for failures during a stream.
    except httpx.TimeoutException as exc:
        raise APITimeoutError(request=exc.request) from exc
    except httpx.TransportError as exc:
        raise APIConnectionError(request=exc.request) from exc


def openai_response(*, api_key, timeout, **request):
    from openai import OpenAI, APIConnectionError, APITimeoutError

    try:
        with OpenAI(api_key=api_key, timeout=timeout, max_retries=0) as client:
            with client.responses.create(**request, stream=True) as stream:
                response = None
                for event in stream:
                    if event.type in {"response.failed", "response.incomplete", "error"}:
                        raise RuntimeError(f"OpenAI stream failed: {event}")
                    if event.type == "response.completed":
                        response = event.response
                if response is None or response.status != "completed":
                    raise RuntimeError("OpenAI stream ended without a completed response")
                return response
    except httpx.TimeoutException as exc:
        raise APITimeoutError(request=exc.request) from exc
    except httpx.TransportError as exc:
        raise APIConnectionError(request=exc.request) from exc
