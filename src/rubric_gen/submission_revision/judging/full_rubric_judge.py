"""Execute bounded whole-artifact full-rubric judge requests."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from rubric_gen.submission_revision.judging import full_rubric_protocol as protocol
from rubric_gen.submission_revision.judging.models import JUDGMENT_REPEATS
from rubric_gen.submission_revision.judging.scoring import parse_rubric_levels_strict


def _generate_response(
    spec: protocol.FullRubricRunSpec,
    *,
    payload: str,
    schema: dict[str, object],
    repeat_index: int,
) -> protocol.FullRubricGeneration:
    request_parameters = protocol.request_parameters(spec)[repeat_index]
    if spec.provider == "vllm":
        from openai import OpenAI

        assert spec.api_base is not None
        response = OpenAI(
            base_url=spec.api_base.rstrip("/") + "/",
            api_key=os.getenv("VLLM_API_KEY", "EMPTY"),
            timeout=protocol.FULL_RUBRIC_REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        ).chat.completions.create(
            model=spec.requested_model,
            messages=[
                {"role": "system", "content": protocol.FULL_RUBRIC_SYSTEM_PROMPT},
                {"role": "user", "content": payload},
            ],
            max_tokens=spec.max_output_tokens_per_call,
            temperature=0.0,
            seed=spec.repeat_seeds[repeat_index],
            response_format={
                "type": "json_schema",
                "json_schema": {
                    "name": "full_rubric_structured_evaluation",
                    "strict": True,
                    "schema": schema,
                },
            },
        )
        text = response.choices[0].message.content or ""
        return protocol.FullRubricGeneration(
            text=text,
            provider="vllm",
            requested_model=spec.requested_model,
            effective_model=str(getattr(response, "model", spec.requested_model)),
            response_id=getattr(response, "id", None),
            request_parameters=request_parameters,
            usage=getattr(response, "usage", None),
        )

    if spec.provider == "google":
        from google import genai
        from google.genai import types

        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise RuntimeError("GEMINI_API_KEY must be set")
        client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(
                timeout=round(protocol.FULL_RUBRIC_REQUEST_TIMEOUT_SECONDS * 1_000),
                retry_options=types.HttpRetryOptions(attempts=0)
            ),
        )
        response = client.models.generate_content(
            model=spec.requested_model,
            contents=payload,
            config=types.GenerateContentConfig(
                system_instruction=protocol.FULL_RUBRIC_SYSTEM_PROMPT,
                temperature=0.0,
                seed=spec.repeat_seeds[repeat_index],
                max_output_tokens=spec.max_output_tokens_per_call,
                response_mime_type="application/json",
                response_json_schema=schema,
                thinking_config=types.ThinkingConfig(thinking_level="low"),
            ),
        )
        return protocol.FullRubricGeneration(
            text=response.text or "",
            provider="google",
            requested_model=spec.requested_model,
            effective_model=str(getattr(response, "model_version", spec.requested_model)),
            response_id=getattr(response, "response_id", None),
            request_parameters=request_parameters,
            usage=getattr(response, "usage_metadata", None),
        )

    if spec.provider == "anthropic":
        from anthropic import Anthropic

        api_key = os.getenv("ANTHROPIC_API_KEY")
        if not api_key:
            raise RuntimeError("ANTHROPIC_API_KEY must be set")
        response = Anthropic(
            api_key=api_key,
            timeout=protocol.FULL_RUBRIC_REQUEST_TIMEOUT_SECONDS,
            max_retries=0,
        ).messages.create(
            model=spec.requested_model,
            max_tokens=spec.max_output_tokens_per_call,
            temperature=0.0,
            system=protocol.FULL_RUBRIC_SYSTEM_PROMPT,
            messages=[{"role": "user", "content": payload}],
            output_config={
                "effort": "low",
                "format": {"type": "json_schema", "schema": schema},
            },
        )
        text = "\n".join(
            block.text
            for block in response.content
            if getattr(block, "type", None) == "text"
            and type(getattr(block, "text", None)) is str
            and block.text
        )
        return protocol.FullRubricGeneration(
            text=text,
            provider="anthropic",
            requested_model=spec.requested_model,
            effective_model=str(getattr(response, "model", spec.requested_model)),
            response_id=getattr(response, "id", None),
            request_parameters=request_parameters,
            usage=getattr(response, "usage", None),
        )

    from openai import OpenAI

    api_key = os.getenv("OPENAI_API_KEY")
    if not api_key:
        raise RuntimeError("OPENAI_API_KEY must be set")
    request: dict[str, object] = {
        "model": spec.requested_model,
        "input": [
            {"role": "developer", "content": protocol.FULL_RUBRIC_SYSTEM_PROMPT},
            {"role": "user", "content": payload},
        ],
        "max_output_tokens": spec.max_output_tokens_per_call,
        "temperature": 0.0,
        "store": False,
        "text": {
            "format": {
                "type": "json_schema",
                "name": "full_rubric_structured_evaluation",
                "strict": True,
                "schema": schema,
            },
            "verbosity": "low",
        },
    }
    if spec.requested_model.startswith("gpt-5.6"):
        request["reasoning"] = {"effort": "none"}
    response = OpenAI(
        api_key=api_key,
        timeout=protocol.FULL_RUBRIC_REQUEST_TIMEOUT_SECONDS,
        max_retries=0,
    ).responses.create(**request)
    status = getattr(response, "status", None)
    if status == "incomplete":
        raise RuntimeError("OpenAI returned an incomplete FullRubric response")
    if status not in {None, "completed"}:
        raise RuntimeError(f"OpenAI FullRubric response failed with status {status}")
    return protocol.FullRubricGeneration(
        text=response.output_text or "",
        provider="openai",
        requested_model=spec.requested_model,
        effective_model=str(getattr(response, "model", spec.requested_model)),
        response_id=getattr(response, "id", None),
        request_parameters=request_parameters,
        usage=getattr(response, "usage", None),
    )


def grade_full_rubric(
    *,
    rubric_text: str,
    review_text: str,
    answer_text: str,
    requested_model: str,
    api_base: str | None,
    seed: int,
) -> protocol.FullRubricArtifactRecords:
    """Run exactly five bounded full-artifact calls and preserve every report."""

    spec = protocol.build_full_rubric_run_spec(
        rubric_text=rubric_text,
        review_text=review_text,
        answer_text=answer_text,
        requested_model=requested_model,
        api_base=api_base,
        seed=seed,
    )
    rubric_levels = parse_rubric_levels_strict(rubric_text)
    schema = protocol.structured_output_schema(rubric_levels)
    payload = protocol.full_rubric_payload(rubric_text, review_text, answer_text)
    reports = []
    usage = []
    for repeat_index in range(JUDGMENT_REPEATS):
        generation = _generate_response(
            spec,
            payload=payload,
            schema=schema,
            repeat_index=repeat_index,
        )
        reports.append(protocol.parse_structured_output(generation.text, rubric_levels))
        usage.append(generation.usage_record())
    return protocol.records_from_raw_reports(
        rubric_text=rubric_text,
        raw_reports=reports,
        spec=spec,
        call_usage=usage,
    )


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, allow_nan=False, indent=2) + "\n",
        encoding="utf-8",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rubric", type=Path, required=True)
    parser.add_argument("--review", type=Path, required=True)
    parser.add_argument("--answer", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--api-base")
    parser.add_argument("--seed", type=int, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    records = grade_full_rubric(
        rubric_text=args.rubric.read_text(encoding="utf-8"),
        review_text=args.review.read_text(encoding="utf-8"),
        answer_text=args.answer.read_text(encoding="utf-8"),
        requested_model=args.model,
        api_base=args.api_base,
        seed=args.seed,
    )
    args.output_dir.mkdir(parents=True, exist_ok=True)
    _write_json(args.output_dir / "reward.json", records.reward)
    _write_json(args.output_dir / "evaluation.json", records.evaluation)
    _write_json(args.output_dir / "usage.json", records.usage)
    print(
        "FullRubric structured judge completed "
        f"{JUDGMENT_REPEATS} repeats; score={records.score}; "
        f"stddev={records.dispersion['score_stddev']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
