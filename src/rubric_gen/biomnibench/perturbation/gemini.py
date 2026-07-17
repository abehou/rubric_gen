"""Gemini implementation of artifact perturbation."""

from __future__ import annotations

from rubric_gen.biomnibench.integrations.gemini import (
    DEFAULT_GEMINI_API_KEY_ENV,
    GEMINI_GENERATE_CONTENT_BASE_URL,
    GeminiClient,
)
from rubric_gen.biomnibench.utils.text import ensure_trailing_newline

from .models import (
    DEFAULT_PERTURBER_MODEL,
    PerturbationRequest,
    PerturbationResult,
)


class GeminiPerturber(GeminiClient):
    def __init__(
        self,
        *,
        model: str = DEFAULT_PERTURBER_MODEL,
        api_key_env: str = DEFAULT_GEMINI_API_KEY_ENV,
        base_url: str = GEMINI_GENERATE_CONTENT_BASE_URL,
        timeout_seconds: int = 600,
    ) -> None:
        super().__init__(
            model=model,
            api_key_env=api_key_env,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )

    def perturb(self, request: PerturbationRequest) -> PerturbationResult:
        trace_md = self.generate_content(
            self.build_artifact_prompt(request, "trace_md")
        ).strip()
        answer_txt = self.generate_content(
            self.build_artifact_prompt(request, "answer_txt")
        ).strip()
        trajectory_stream_jsonl = ensure_trailing_newline(
            self.generate_content(
                self.build_artifact_prompt(request, "trajectory_stream_jsonl")
            ).strip()
        )
        return PerturbationResult(
            level=request.level,
            intent=request.level_intent,
            trace_md=trace_md,
            answer_txt=answer_txt,
            trajectory_stream_jsonl=trajectory_stream_jsonl,
            preserved_claims=(
                "broad final conclusion preserved"
                if request.level != "L5"
                else "final answer intentionally degraded",
            ),
            perturbation_notes=(
                "Generated trace_md, answer_txt, and trajectory_stream_jsonl "
                f"separately for {request.level}.",
            ),
        )

    def build_prompt(self, request: PerturbationRequest) -> str:
        return self.build_artifact_prompt(request, "all")

    def build_artifact_prompt(self, request: PerturbationRequest, artifact: str) -> str:
        artifact_instructions = {
            "trace_md": (
                "Return only the complete perturbed trace.md content as Markdown/plain text. "
                "Do not wrap it in JSON, XML, code fences, or commentary."
            ),
            "answer_txt": (
                "Return only the complete perturbed answer.txt content as plain text. "
                "Do not wrap it in JSON, XML, code fences, or commentary."
            ),
            "trajectory_stream_jsonl": (
                "Return only the complete perturbed trajectory.stream.jsonl content. "
                "Every event line that starts with { must be valid single-line JSON. "
                "Do not wrap it in Markdown fences or commentary."
            ),
            "all": (
                "Return the perturbed artifacts. This compatibility prompt is only "
                "used for prompt inspection."
            ),
        }
        return f"""You are perturbing a saved BiomniBench agent run to create controlled quality variants.

Use only the task instruction and original artifacts below. Do not use any grading rubric, rubric criterion, score,
or hidden evaluator target. Create a generic quality perturbation for the requested level.

Artifact to generate: {artifact}
Output instruction: {artifact_instructions[artifact]}

Level: {request.level}
Level intent: {request.level_intent}

Constraints:
- Preserve the same task identity and local-file setting.
- For L1-L4, preserve the broad final conclusion and final-answer plausibility.
- For L0, make the process more verbose and detailed-looking without adding new concrete evidence.
- For L5, degrade both the process and final answer.
- Keep trace_md, answer_txt, and trajectory_stream_jsonl non-empty.
- Do not mention rubrics, judging, scores, or evaluator criteria.
- trajectory_stream_jsonl should be newline-delimited event text. JSON event lines must remain valid JSON.

<instruction.md>
{request.instruction_md}
</instruction.md>

<original_trace.md>
{request.trace_md}
</original_trace.md>

<original_answer.txt>
{request.answer_txt}
</original_answer.txt>

<original_trajectory.stream.jsonl>
{request.trajectory_stream_jsonl}
</original_trajectory.stream.jsonl>
"""
