from __future__ import annotations

import json
from pathlib import Path

from rubric_gen.biomnibench.revision.rubric_free import SCORE_FIELDS, SYSTEM_PROMPT
from rubric_gen.biomnibench.revision.rubric_free_tournament import (
    CONDITIONS,
    Finalist,
    MatchTarget,
    TournamentConfig,
    TournamentRunner,
    TournamentStudy,
    pair_prompt,
)
from rubric_gen.biomnibench.utils.hashing import sha256_text
from rubric_gen.malt.model_judge import ModelGeneration, ModelRequest


MODELS = ("judge-a", "judge-b", "judge-c")
RANKS = {
    "base-static": 2,
    "base-prospective": 4,
    "diligent-static": 5,
    "diligent-prospective": 7,
}


def _finalist(feedback: str, condition: str) -> Finalist:
    answer = f"ANSWER {feedback} {condition}"
    trace = f"TRACE {feedback} {condition}"
    return Finalist(
        feedback_id=feedback,
        assignment_id=f"assignment-{feedback}-{condition}",
        condition_id=condition,
        answer=answer,
        answer_sha256=sha256_text(answer),
        trace=trace,
        trace_sha256=sha256_text(trace),
    )


def _study(tmp_path: Path) -> TournamentStudy:
    instruction = "Give a safe medical answer."
    finalists = [
        _finalist(feedback, condition)
        for feedback in ("semi", "full")
        for condition in CONDITIONS
    ]
    targets = []
    for left_index, left in enumerate(finalists):
        for right in finalists[left_index + 1:]:
            targets.append(MatchTarget(
                match_id=f"task-001--rep-001--{left.pool_id}--vs--{right.pool_id}",
                task_id="task-001",
                replicate=1,
                instruction=instruction,
                instruction_sha256=sha256_text(instruction),
                left=left,
                right=right,
            ))
    return TournamentStudy(
        sources=(tmp_path / "semi", tmp_path / "full"),
        experiment_ids=("experiment-semi", "experiment-full"),
        targets=tuple(targets),
    )


def _generation(model: str, request: ModelRequest) -> ModelGeneration:
    verdict: dict[str, object] = {}
    for response_name in ("response_A", "response_B"):
        start = request.evidence.index(f"<{response_name}>") + len(response_name) + 2
        end = request.evidence.index(f"</{response_name}>")
        answer = request.evidence[start:end]
        condition = next(value for value in CONDITIONS if value in answer)
        verdict[response_name] = {
            dimension: {
                "score": RANKS[condition],
                "justification": f"{condition} evidence",
            }
            for dimension in SCORE_FIELDS
        }
    verdict["comparative_explanation"] = "The two responses were compared."
    return ModelGeneration(
        text=json.dumps(verdict),
        provider="test",
        requested_model=model,
        effective_model=model,
        response_id=f"response-{model}",
        request_parameters={"temperature": 0},
    )


def test_tournament_prompt_flips_answer_and_trace_together(tmp_path: Path) -> None:
    target = _study(tmp_path).targets[0]
    normal = pair_prompt(target, "left-first")
    flipped = pair_prompt(target, "right-first")

    assert normal.index(target.left.answer) < normal.index(target.right.answer)
    assert flipped.index(target.right.answer) < flipped.index(target.left.answer)
    assert normal.index(target.left.trace) < normal.index(target.right.trace)
    assert flipped.index(target.right.trace) < flipped.index(target.left.trace)
    for prompt in (normal, flipped):
        assert target.instruction in prompt
        assert prompt.count("<analysis_trace>") == 2
        assert prompt.count("<answer>") == 2
        assert "rubric" not in prompt.lower()
        assert "trajectory.stream.jsonl" not in prompt


def test_tournament_runs_joint_pool_and_reports_controlled_rates(
    tmp_path: Path,
) -> None:
    study = _study(tmp_path)
    output = tmp_path / "output"
    calls: list[tuple[str, ModelRequest]] = []

    def generate(model: str, request: ModelRequest) -> ModelGeneration:
        calls.append((model, request))
        return _generation(model, request)

    runner = TournamentRunner(
        TournamentConfig(
            semi_study_dir=study.sources[0],
            full_study_dir=study.sources[1],
            output_dir=output,
            models=MODELS,
            max_concurrency=1,
            max_retries=0,
        ),
        load_study=lambda _semi, _full: study,
        generate_response=generate,
    )
    assert runner.run() == 0
    assert len(calls) == 168
    assert all(request.instructions == SYSTEM_PROMPT for _model, request in calls)

    summary = json.loads((output / "summary.json").read_text())
    assert summary["totals"] == {
        "jobs": 168,
        "completed": 168,
        "failed": 0,
        "pending": 0,
    }
    assert len(summary["matches"]) == 28
    assert summary["protocol"]["answer_visible_to_judges"] is True
    assert summary["protocol"]["trace_visible_to_judges"] is True
    assert summary["protocol"]["trajectory_visible_to_judges"] is False
    factors = summary["factors"]
    assert factors["marginal"]["rubric.dynamic"]["comparisons"] == 28
    assert factors["controlled"]["dynamic_vs_static"] == {
        "comparisons": 4,
        "wins": 4,
        "ties": 0,
        "losses": 0,
        "half_win_rate": 1.0,
    }
    assert factors["controlled"]["diligent_vs_base"]["half_win_rate"] == 1.0
    assert factors["controlled"]["full_vs_semi"] == {
        "comparisons": 4,
        "wins": 0,
        "ties": 4,
        "losses": 0,
        "half_win_rate": 0.5,
    }

    resumed_calls = []
    assert TournamentRunner(
        TournamentConfig(
            semi_study_dir=study.sources[0],
            full_study_dir=study.sources[1],
            output_dir=output,
            models=MODELS,
            max_concurrency=1,
            max_retries=0,
            resume=True,
        ),
        load_study=lambda _semi, _full: study,
        generate_response=lambda model, request: resumed_calls.append((model, request)),
    ).run() == 0
    assert resumed_calls == []
