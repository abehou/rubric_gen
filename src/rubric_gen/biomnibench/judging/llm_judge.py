# /// script
# dependencies = [
#   "anthropic>=0.40.0",
#   "google-genai>=1.0.0",
#   "openai>=1.66.0",
# ]
# ///
"""Central provider-aware LLM judge used by every BiomniBench task."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path


def provider_for_model(model: str) -> str:
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


def generate_response(model: str, prompt: str) -> str:
    provider = provider_for_model(model)
    if provider == "gemini":
        from google import genai

        api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY or GOOGLE_API_KEY must be set")
        # Keep the client alive for the entire request. ``Client.models`` does not
        # retain a strong reference to a temporary Client, so chaining the
        # constructor into ``generate_content`` can close its HTTP client while
        # the request is still in progress.
        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model,
            contents=prompt,
        )
        text = response.text
        if not text:
            raise RuntimeError("Gemini returned an empty response")
        return text
    if provider == "anthropic":
        from anthropic import Anthropic

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY must be set")
        response = Anthropic(api_key=api_key).messages.create(
            model=model,
            max_tokens=8192,
            messages=[{"role": "user", "content": prompt}],
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
        return text

    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY must be set")
    response = OpenAI(api_key=api_key).responses.create(
        model=model,
        input=prompt,
        max_output_tokens=8192,
    )
    return response.output_text or ""


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
    return max(0, min(100, total)), criteria, str(reasoning)


def judge_prompt(rubric: str, trace: str, answer: str) -> str:
    return f"""You are an expert evaluator for a data analysis task.

Evaluate the agent's work using the following rubric:

{rubric}

Here is the agent's analysis trace:
<trace>
{trace or "[No trace file provided]"}
</trace>

Here is the agent's final answer:
<answer>
{answer or "[No answer file provided]"}
</answer>

For every criterion, choose exactly one rubric level based only on the supplied
evidence. Return only one JSON object with this shape:
{{"criteria": {{"criterion_1": {{"level": "A", "reason": "..."}}}},
 "overall_reasoning": "..."}}
Do not calculate or return numerical points."""


def main() -> None:
    rubric = Path("/tests/rubric.txt").read_text(encoding="utf-8")
    trace_path = Path("/logs/verifier/trace.md")
    answer_path = Path("/logs/verifier/answer.txt")
    trace = trace_path.read_text(encoding="utf-8") if trace_path.is_file() else ""
    answer = answer_path.read_text(encoding="utf-8") if answer_path.is_file() else ""
    model = os.getenv("MODEL_NAME", "")
    if not model:
        raise RuntimeError("MODEL_NAME must be set")
    response_text = generate_response(model, judge_prompt(rubric, trace, answer))
    print(f"Raw response (first 1000 chars): {response_text[:1000]}...")
    score, criteria, reasoning = score_response(
        response_text,
        parse_rubric_levels(rubric),
    )
    logs = Path("/logs/verifier")
    logs.mkdir(parents=True, exist_ok=True)
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
