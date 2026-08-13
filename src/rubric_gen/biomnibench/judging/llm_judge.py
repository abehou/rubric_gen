# /// script
# dependencies = [
#   "anthropic>=0.40.0",
#   "google-genai>=1.0.0",
#   "openai>=1.66.0",
# ]
# ///
"""Central provider-aware LLM judge used by every BiomniBench task."""

from __future__ import annotations

import fcntl
import hashlib
import json
import os
import re
import stat
import tempfile
import time
from contextlib import AbstractContextManager
from pathlib import Path


_MAX_OUTPUT_TOKENS = 4_096
_OPENAI_TIMEOUT_SECONDS = 300.0
_ANTHROPIC_TIMEOUT_SECONDS = 300.0
_CACHE_GATE_ROOT = (
    Path(tempfile.gettempdir()) / f"rubric-gen-judge-cache-gates-{os.getuid()}"
)


class _PromptCacheGate(AbstractContextManager["_PromptCacheGate"]):
    """Single-flight one cold prefix across concurrent local judge processes."""

    __slots__ = ("_fd", "_locked", "_path", "_ttl_seconds")

    def __init__(
        self,
        *,
        model: str,
        prompt_cache_key: str,
        api_key: str,
        ttl_seconds: float,
    ) -> None:
        scope = hashlib.sha256(api_key.encode("utf-8")).hexdigest()
        digest = hashlib.sha256(
            f"{model}\0{prompt_cache_key}\0{scope}".encode("utf-8")
        ).hexdigest()
        self._path = _CACHE_GATE_ROOT / f"{digest}.lock"
        self._ttl_seconds = ttl_seconds
        self._fd = -1
        self._locked = False

    def __enter__(self) -> "_PromptCacheGate":
        _CACHE_GATE_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
        root = _CACHE_GATE_ROOT.lstat()
        if not stat.S_ISDIR(root.st_mode) or root.st_uid != os.getuid():
            raise RuntimeError("prompt-cache gate root is not a trusted directory")
        os.chmod(_CACHE_GATE_ROOT, 0o700)
        flags = os.O_CREAT | os.O_RDWR
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        self._fd = os.open(self._path, flags, 0o600)
        fcntl.flock(self._fd, fcntl.LOCK_EX)
        self._locked = True
        state = os.fstat(self._fd)
        fresh = (
            state.st_size > 0
            and 0 <= time.time() - state.st_mtime < self._ttl_seconds
        )
        if fresh:
            fcntl.flock(self._fd, fcntl.LOCK_UN)
            self._locked = False
        return self

    def mark_success(self) -> None:
        if not self._locked:
            return
        os.ftruncate(self._fd, 0)
        os.lseek(self._fd, 0, os.SEEK_SET)
        os.write(self._fd, b"warm\n")
        os.fsync(self._fd)

    def __exit__(self, *exc_info: object) -> None:
        if self._fd >= 0:
            if self._locked:
                fcntl.flock(self._fd, fcntl.LOCK_UN)
            os.close(self._fd)
        self._fd = -1
        self._locked = False


def _cache_gate(
    model: str,
    prompt: "JudgePrompt",
    api_key: str,
    *,
    ttl_seconds: float,
) -> _PromptCacheGate:
    return _PromptCacheGate(
        model=model,
        prompt_cache_key=prompt.prompt_cache_key(),
        api_key=api_key,
        ttl_seconds=ttl_seconds,
    )


class JudgePrompt:
    """A stable rubric prefix followed by submission-specific evidence."""

    __slots__ = ("instructions", "evidence")

    def __init__(self, *, instructions: str, evidence: str) -> None:
        if not instructions.strip() or not evidence.strip():
            raise ValueError("judge prompt sections must not be empty")
        self.instructions = instructions
        self.evidence = evidence

    def flat_prompt(self) -> str:
        return self.instructions.rstrip() + "\n\n" + self.evidence.lstrip()

    def openai_input(self) -> list[dict[str, object]]:
        return [
            {
                "role": "developer",
                "content": [{
                    "type": "input_text",
                    "text": self.instructions,
                    "prompt_cache_breakpoint": {"mode": "explicit"},
                }],
            },
            {"role": "user", "content": self.evidence},
        ]

    def prompt_cache_key(self) -> str:
        digest = hashlib.sha256(self.instructions.encode("utf-8")).hexdigest()
        return "biomnibench-judge-" + digest[:40]


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    model_dump = getattr(value, "model_dump", None)
    if callable(model_dump):
        return _jsonable(model_dump())
    to_dict = getattr(value, "to_dict", None)
    if callable(to_dict):
        return _jsonable(to_dict())
    return str(value)


class JudgeGeneration:
    """Provider response plus the exact request and billable-usage metadata.

    This judge is also executed as a standalone task script.  A plain slotted
    class keeps that import path robust even when an embedding loader has not
    inserted the module into ``sys.modules`` before executing it.
    """

    __slots__ = (
        "text",
        "provider",
        "requested_model",
        "effective_model",
        "response_id",
        "request_parameters",
        "usage",
    )

    def __init__(
        self,
        *,
        text: str,
        provider: str,
        requested_model: str,
        effective_model: str,
        response_id: str | None,
        request_parameters: dict[str, object],
        usage: object,
    ) -> None:
        self.text = text
        self.provider = provider
        self.requested_model = requested_model
        self.effective_model = effective_model
        self.response_id = response_id
        self.request_parameters = request_parameters
        self.usage = usage

    def usage_record(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "provider": self.provider,
            "requested_model": self.requested_model,
            "effective_model": self.effective_model,
            "response_id": self.response_id,
            "request_parameters": self.request_parameters,
            "usage": _jsonable(self.usage),
        }


def provider_for_model(model: str, *, base_url: str | None = None) -> str:
    if base_url is not None:
        return "vllm"
    if model.startswith("gemini"):
        return "gemini"
    if model.startswith("claude"):
        return "anthropic"
    if model.startswith(("gpt-", "chatgpt-", "o1", "o3", "o4")):
        return "openai"
    raise ValueError(
        f"cannot infer judge provider from model {model!r}; expected a Gemini, "
        "Claude, GPT, or o-series model"
    )


def generate_response(
    model: str,
    prompt: JudgePrompt,
    criterion_ids: tuple[str, ...] = (),
    *,
    max_output_tokens: int = _MAX_OUTPUT_TOKENS,
) -> JudgeGeneration:
    base_url = os.getenv("VLLM_BASE_URL")
    provider = provider_for_model(model, base_url=base_url)
    if provider == "vllm":
        from openai import OpenAI

        assert base_url is not None
        response = OpenAI(
            base_url=base_url.rstrip("/") + "/",
            api_key=os.getenv("VLLM_API_KEY", "EMPTY"),
            timeout=_OPENAI_TIMEOUT_SECONDS,
            max_retries=0,
        ).chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": prompt.instructions},
                {"role": "user", "content": prompt.evidence},
            ],
            max_tokens=max_output_tokens,
            temperature=0,
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "biomnibench_judge_evaluation",
                    "strict": True,
                    "schema": _openai_text_format(criterion_ids)["schema"],
                },
            },
        )
        text = response.choices[0].message.content or ""
        if not text:
            raise RuntimeError("vLLM returned an empty judge response")
        return JudgeGeneration(
            text=text,
            provider="vllm",
            requested_model=model,
            effective_model=str(getattr(response, "model", model)),
            response_id=getattr(response, "id", None),
            request_parameters={
                "base_url": base_url.rstrip("/") + "/",
                "max_tokens": max_output_tokens,
                "temperature": 0,
                "client_timeout_seconds": _OPENAI_TIMEOUT_SECONDS,
                "client_max_retries": 0,
                "response_format": "json_schema",
            },
            usage=getattr(response, "usage", None),
        )
    if provider == "gemini":
        from google import genai

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY must be set")
        from google.genai import types

        # Keep the client alive for the entire request. ``Client.models`` does not
        # retain a strong reference to a temporary Client, so chaining the
        # constructor into ``generate_content`` can close its HTTP client while
        # the request is still in progress. An attempts value of zero disables
        # SDK retrying (the initial request is still made once).
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                retry_options=types.HttpRetryOptions(attempts=0)
            ),
        )

        with _cache_gate(model, prompt, api_key, ttl_seconds=60.0) as cache_gate:
            response = client.models.generate_content(
                model=model,
                contents=prompt.flat_prompt(),
                config=types.GenerateContentConfig(
                    max_output_tokens=max_output_tokens,
                    thinking_config=types.ThinkingConfig(thinking_level="low"),
                ),
            )
            text = response.text
            if not text:
                raise RuntimeError("Gemini returned an empty response")
            cache_gate.mark_success()
        return JudgeGeneration(
            text=text,
            provider="google",
            requested_model=model,
            effective_model=str(getattr(response, "model_version", model)),
            response_id=getattr(response, "response_id", None),
            request_parameters={
                "max_output_tokens": max_output_tokens,
                "thinking_level": "low",
                "client_max_retries": 0,
                "prompt_cache": "implicit-stable-rubric-prefix",
                "prompt_cache_singleflight": "host-local-cold-prefix",
            },
            usage=getattr(response, "usage_metadata", None),
        )
    if provider == "anthropic":
        from anthropic import Anthropic

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY must be set")
        with _cache_gate(model, prompt, api_key, ttl_seconds=240.0) as cache_gate:
            response = Anthropic(
                api_key=api_key,
                timeout=_ANTHROPIC_TIMEOUT_SECONDS,
                max_retries=0,
            ).messages.create(
                model=model,
                max_tokens=max_output_tokens,
                system=[{
                    "type": "text",
                    "text": prompt.instructions,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=[{"role": "user", "content": prompt.evidence}],
                output_config={"effort": "low"},
            )
            text = "\n".join(
                block.text
                for block in response.content
                if getattr(block, "type", None) == "text"
                and isinstance(getattr(block, "text", None), str)
                and block.text
            )
            if not text:
                raise RuntimeError(
                    "Anthropic returned no text "
                    f"(stop_reason={getattr(response, 'stop_reason', None)!r})"
                )
            cache_gate.mark_success()
        return JudgeGeneration(
            text=text,
            provider="anthropic",
            requested_model=model,
            effective_model=str(getattr(response, "model", model)),
            response_id=getattr(response, "id", None),
            request_parameters={
                "max_output_tokens": max_output_tokens,
                "effort": "low",
                "client_timeout_seconds": _ANTHROPIC_TIMEOUT_SECONDS,
                "client_max_retries": 0,
                "prompt_cache": {"mode": "explicit", "ttl": "5m"},
                "prompt_cache_singleflight": "host-local-cold-prefix",
            },
            usage=getattr(response, "usage", None),
        )

    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY must be set")
    # BiomniBench owns retry policy. Hidden SDK retries multiply the outer
    # retry loop and can turn one failed judgment into an hours-long stall.
    client = OpenAI(
        api_key=api_key,
        timeout=_OPENAI_TIMEOUT_SECONDS,
        max_retries=0,
    )
    with _cache_gate(model, prompt, api_key, ttl_seconds=1_500.0) as cache_gate:
        response = client.responses.create(
            model=model,
            input=prompt.openai_input(),
            max_output_tokens=max_output_tokens,
            reasoning={"effort": "none"},
            text={
                "format": _openai_text_format(criterion_ids),
                "verbosity": "low",
            },
            prompt_cache_options={"mode": "explicit", "ttl": "30m"},
            prompt_cache_key=prompt.prompt_cache_key(),
        )
        status = getattr(response, "status", None)
        if status == "incomplete":
            details = getattr(response, "incomplete_details", None)
            reason = getattr(details, "reason", None) or "unknown"
            raise RuntimeError(
                "OpenAI returned an incomplete judge response "
                f"(reason={reason}, max_output_tokens={max_output_tokens})"
            )
        if status not in {None, "completed"}:
            error = getattr(response, "error", None)
            raise RuntimeError(
                f"OpenAI judge response failed (status={status}, error={error!r})"
            )
        text = response.output_text or ""
        if not text:
            raise RuntimeError("OpenAI returned an empty judge response")
        cache_gate.mark_success()
    return JudgeGeneration(
        text=text,
        provider="openai",
        requested_model=model,
        effective_model=str(getattr(response, "model", model)),
        response_id=getattr(response, "id", None),
        request_parameters={
            "max_output_tokens": max_output_tokens,
            "reasoning_effort": "none",
            "text_verbosity": "low",
            "client_timeout_seconds": _OPENAI_TIMEOUT_SECONDS,
            "client_max_retries": 0,
            "prompt_cache": {"mode": "explicit", "ttl": "30m"},
            "prompt_cache_key": prompt.prompt_cache_key(),
            "prompt_cache_singleflight": "host-local-cold-prefix",
        },
        usage=getattr(response, "usage", None),
    )


def _openai_text_format(criterion_ids: tuple[str, ...]) -> dict[str, object]:
    if not criterion_ids:
        raise ValueError("judge rubric must contain at least one criterion")
    if len(set(criterion_ids)) != len(criterion_ids):
        raise ValueError("judge rubric criterion IDs must be unique")
    criterion_schema = {
        "type": "object",
        "properties": {
            "level": {"type": "string"},
            "reason": {"type": "string"},
        },
        "required": ["level", "reason"],
        "additionalProperties": False,
    }
    return {
        "type": "json_schema",
        "name": "biomnibench_judge_evaluation",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "criteria": {
                    "type": "object",
                    "properties": {
                        criterion_id: criterion_schema
                        for criterion_id in criterion_ids
                    },
                    "required": list(criterion_ids),
                    "additionalProperties": False,
                },
                "overall_reasoning": {"type": "string"},
            },
            "required": ["criteria", "overall_reasoning"],
            "additionalProperties": False,
        },
    }


def parse_rubric_levels(rubric: str) -> dict[str, dict[str, int]]:
    levels_by_criterion: dict[str, dict[str, int]] = {}
    parts = re.split(r"^Criterion\s+(\d+)\s*:", rubric, flags=re.MULTILINE)
    for index in range(1, len(parts), 2):
        number = parts[index].strip()
        body = parts[index + 1] if index + 1 < len(parts) else ""
        levels: dict[str, int] = {}
        header = re.search(r"Levels:\s*((?:[A-Z]=-?\d+\s*)+)", body)
        if header:
            levels = {
                match.group(1): int(match.group(2))
                for match in re.finditer(r"([A-Z])=(-?\d+)", header.group(1))
            }
        if not levels:
            levels = {
                match.group(1): int(match.group(2))
                for match in re.finditer(
                    r"\[([A-Z])\]\s*\(\s*(-?\d+)\s*points?\s*\)", body
                )
            }
        if levels:
            levels_by_criterion[f"criterion_{number}"] = levels
    return levels_by_criterion


def parse_score_normalization_maximum(rubric: str) -> int | None:
    matches = re.findall(
        r"^[ \t]*Score normalization maximum:[ \t]*([1-9]\d*)[ \t]*$",
        rubric,
        flags=re.MULTILINE,
    )
    if len(matches) > 1:
        raise ValueError("rubric contains multiple score normalization directives")
    return int(matches[0]) if matches else None


def extract_json_object(text: str) -> dict[str, object]:
    start = text.find("{")
    if start < 0:
        raise ValueError("judge response contains no JSON object")
    depth = 0
    in_string = False
    escaped = False
    for index, character in enumerate(text[start:], start):
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            continue
        if character == '"':
            in_string = True
        elif character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth == 0:
                value = json.loads(text[start : index + 1])
                if type(value) is not dict:
                    raise ValueError("judge response JSON must be an object")
                return value
    raise ValueError("judge response contains an incomplete JSON object")


def score_response(
    response_text: str,
    rubric_levels: dict[str, dict[str, int]],
    normalization_maximum: int | None = None,
) -> tuple[int, dict[str, object], str]:
    result = extract_json_object(response_text)
    raw_criteria = result.get("criteria")
    if type(raw_criteria) is not dict:
        raise ValueError("judge response criteria must be an object")
    criteria: dict[str, object] = {}
    total = 0
    for criterion, allowed in rubric_levels.items():
        raw = raw_criteria.get(criterion)
        if type(raw) is not dict:
            raise ValueError(f"judge response is missing {criterion}")
        level = raw.get("level")
        if type(level) is not str or level.strip().upper() not in allowed:
            raise ValueError(f"judge response has an invalid level for {criterion}")
        normalized_level = level.strip().upper()
        score = allowed[normalized_level]
        criteria[criterion] = {
            "level": normalized_level,
            "score": score,
            "reason": raw.get("reason", ""),
        }
        total += score
    reasoning = result.get("overall_reasoning", result.get("reasoning", ""))
    score = (
        round(total * 100 / normalization_maximum)
        if normalization_maximum is not None
        else total
    )
    return max(0, min(100, score)), criteria, str(reasoning)


def judge_prompt(rubric: str, trace: str, answer: str) -> JudgePrompt:
    instructions = f"""You are an expert evaluator for a scientific agent task.

Evaluate the agent's work using the following rubric:

{rubric}

For every criterion, choose exactly one rubric level based only on the supplied
evidence. Return only one JSON object with this shape:
{{"criteria": {{"criterion_1": {{"level": "A", "reason": "..."}}}},
 "overall_reasoning": "..."}}
Do not calculate or return numerical points. Keep each criterion reason under
15 words and overall_reasoning under 100 words. Completeness and valid JSON are
more important than elaboration."""

    evidence = f"""Here is the evidence selected by the evaluation harness:
<submission_evidence>
{trace or "[No trace file provided]"}
</submission_evidence>"""
    if answer:
        evidence += f"""

Here is the agent's final answer:
<answer>
{answer}
</answer>"""
    return JudgePrompt(instructions=instructions, evidence=evidence)


def main() -> None:
    rubric = Path("/tests/rubric.txt").read_text(encoding="utf-8")
    trace_path = Path("/logs/verifier/trace.md")
    answer_path = Path("/logs/verifier/answer.txt")
    trace = trace_path.read_text(encoding="utf-8") if trace_path.is_file() else ""
    answer = answer_path.read_text(encoding="utf-8") if answer_path.is_file() else ""
    model = os.getenv("MODEL_NAME", "")
    if not model:
        raise RuntimeError("MODEL_NAME must be set")
    rubric_levels = parse_rubric_levels(rubric)
    normalization_maximum = parse_score_normalization_maximum(rubric)
    max_output_tokens = min(
        32_768,
        max(_MAX_OUTPUT_TOKENS, len(rubric_levels) * 128),
    )
    generation = generate_response(
        model,
        judge_prompt(rubric, trace, answer),
        tuple(rubric_levels),
        max_output_tokens=max_output_tokens,
    )
    response_text = generation.text
    print(f"Raw response (first 1000 chars): {response_text[:1000]}...")
    score, criteria, reasoning = score_response(
        response_text,
        rubric_levels,
        normalization_maximum,
    )
    logs = Path("/logs/verifier")
    logs.mkdir(parents=True, exist_ok=True)
    (logs / "usage.json").write_text(
        json.dumps(generation.usage_record(), indent=2), encoding="utf-8"
    )
    (logs / "reward.json").write_text(
        json.dumps({"score": score}, indent=2), encoding="utf-8"
    )
    (logs / "evaluation.json").write_text(
        json.dumps(
            {"total_score": score, "criteria": criteria, "reasoning": reasoning},
            indent=2,
        ),
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
