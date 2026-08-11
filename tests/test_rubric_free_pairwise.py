from __future__ import annotations

import json
from pathlib import Path

import pytest

from rubric_gen.biomnibench.revision.rubric_free import (
    ORDERINGS,
    QUALITY_DIMENSIONS,
    SCORE_FIELDS,
    SYSTEM_PROMPT,
    PairTarget,
    RubricFreeConfig,
    RubricFreeRunner,
    RubricFreeStudy,
    pair_prompt,
    parse_verdict,
)
from rubric_gen.biomnibench.utils.hashing import sha256_text
from rubric_gen.malt.model_judge import ModelGeneration, ModelRequest


MODELS = ("judge-a", "judge-b", "judge-c")


def _target() -> PairTarget:
    instruction = "Give a safe medical answer."
    initial = "INITIAL RESPONSE"
    final = "FINAL RESPONSE"
    return PairTarget(
        assignment_id="assignment-001",
        task_id="task-001",
        replicate=0,
        condition_id="condition-001",
        experiment_dir=Path("/unused/experiment"),
        instruction=instruction,
        instruction_sha256=sha256_text(instruction),
        initial_answer=initial,
        initial_answer_sha256=sha256_text(initial),
        final_answer=final,
        final_answer_sha256=sha256_text(final),
    )


def _study(tmp_path: Path) -> RubricFreeStudy:
    return RubricFreeStudy(
        source=tmp_path / "study",
        experiment_id="experiment-001",
        targets=(_target(),),
    )


def _verdict(request: ModelRequest) -> dict[str, object]:
    def response_score(name: str) -> int:
        start = request.evidence.index(f"<{name}>") + len(name) + 2
        end = request.evidence.index(f"</{name}>")
        response = request.evidence[start:end]
        return 7 if "FINAL RESPONSE" in response else 3

    result: dict[str, object] = {}
    for response_name in ("response_A", "response_B"):
        score = response_score(response_name)
        result[response_name] = {
            dimension: {
                "score": score,
                "justification": f"{response_name} evidence",
            }
            for dimension in SCORE_FIELDS
        }
    result["comparative_explanation"] = (
        "@response_A and @response_B were compared directly. "
        "The final response is better."
    )
    return result


def _generation(model: str, request: ModelRequest) -> ModelGeneration:
    return ModelGeneration(
        text=json.dumps(_verdict(request)),
        provider="test",
        requested_model=model,
        effective_model=model,
        response_id=f"response-{model}",
        request_parameters={"temperature": 0},
    )


def test_appendix_prompt_and_dimensions_are_exact() -> None:
    assert sha256_text(SYSTEM_PROMPT) == (
        "2fe37d31565ff2a90e0f3bc09cabe77ead328bb1aa8ae3a1f534fa619ff58c63"
    )
    assert QUALITY_DIMENSIONS == (
        "completeness",
        "factual_correctness",
        "conciseness",
        "relevance",
        "safety",
    )
    assert "scientific_validity" not in SYSTEM_PROMPT


def test_pair_prompt_flips_only_the_response_positions() -> None:
    target = _target()
    normal = pair_prompt(target, "initial-first")
    flipped = pair_prompt(target, "final-first")

    assert normal.index("INITIAL RESPONSE") < normal.index("FINAL RESPONSE")
    assert flipped.index("FINAL RESPONSE") < flipped.index("INITIAL RESPONSE")
    for prompt in (normal, flipped):
        assert target.instruction in prompt
        assert "rubric" not in prompt.lower()
        assert "trajectory" not in prompt.lower()


def test_parse_verdict_rejects_non_integer_scores() -> None:
    target = _target()
    request = ModelRequest(
        instructions=SYSTEM_PROMPT,
        evidence=pair_prompt(target, ORDERINGS[0]),
        schema_name="test",
        schema={},
    )
    verdict = _verdict(request)
    verdict["response_A"]["overall"]["score"] = 6.5

    with pytest.raises(ValueError, match="score is invalid"):
        parse_verdict(json.dumps(verdict))


def test_runner_averages_flips_and_resumes_sealed_artifacts(
    tmp_path: Path,
) -> None:
    study = _study(tmp_path)
    output = tmp_path / "output"
    calls: list[tuple[str, ModelRequest]] = []

    def generate(model: str, request: ModelRequest) -> ModelGeneration:
        calls.append((model, request))
        return _generation(model, request)

    config = RubricFreeConfig(
        study_dir=study.source,
        output_dir=output,
        models=MODELS,
        max_concurrency=1,
        max_retries=0,
    )
    assert RubricFreeRunner(
        config,
        load_study=lambda _path: study,
        generate_response=generate,
    ).run() == 0
    assert len(calls) == 6
    assert all(call[1].instructions == SYSTEM_PROMPT for call in calls)

    summary = json.loads((output / "summary.json").read_text())
    assignment = summary["assignments"]["assignment-001"]
    assert summary["status"] == "completed"
    assert summary["totals"] == {
        "jobs": 6,
        "completed": 6,
        "failed": 0,
        "pending": 0,
    }
    assert assignment["panel"]["majority_winner"] == "final"
    assert assignment["panel"]["consensus_winner"] == "final"
    assert assignment["panel"]["mean_score_deltas"]["overall"] == 4.0
    assert all(
        judge["overall_delta"] == 4.0
        for judge in assignment["judges"].values()
    )
    assert all("raw_response" not in record for record in summary["records"])

    resume_calls: list[tuple[str, ModelRequest]] = []
    resume_config = RubricFreeConfig(
        study_dir=study.source,
        output_dir=output,
        models=MODELS,
        max_concurrency=1,
        max_retries=0,
        resume=True,
    )
    assert RubricFreeRunner(
        resume_config,
        load_study=lambda _path: study,
        generate_response=lambda model, request: resume_calls.append(
            (model, request)
        ),
    ).run() == 0
    assert resume_calls == []


def test_resume_rejects_changed_raw_response(tmp_path: Path) -> None:
    study = _study(tmp_path)
    output = tmp_path / "output"
    config = RubricFreeConfig(
        study_dir=study.source,
        output_dir=output,
        models=MODELS,
        max_concurrency=1,
        max_retries=0,
    )
    runner = RubricFreeRunner(
        config,
        load_study=lambda _path: study,
        generate_response=_generation,
    )
    assert runner.run() == 0

    artifact = next((output / "artifacts").rglob("*.json"))
    record = json.loads(artifact.read_text())
    record["raw_response"] += " "
    artifact.write_text(json.dumps(record), encoding="utf-8")

    resume = RubricFreeRunner(
        RubricFreeConfig(
            study_dir=study.source,
            output_dir=output,
            models=MODELS,
            max_concurrency=1,
            max_retries=0,
            resume=True,
        ),
        load_study=lambda _path: study,
        generate_response=_generation,
    )
    with pytest.raises(RuntimeError, match="raw response changed"):
        resume.run()
