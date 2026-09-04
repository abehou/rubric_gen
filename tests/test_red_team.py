from __future__ import annotations

from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.runtime.agents.models import AgentRunConfig
from rubric_gen.runtime.agents.sessions import SessionTurnResult
from rubric_gen.submission_revision.red_team import (
    RedTeamGenerator,
    load_red_team_artifact,
    red_team_prompt,
)
from rubric_gen.submission_revision.rubric_generation import (
    CompleteRubric,
    RubricGeneration,
)


RUBRIC = """RUBRIC: Result

Criterion 1: Result
Description: Evaluate the result.
Levels: A=100 B=50 C=0
[A]: Fully correct.
[B]: Partly correct.
[C]: Incorrect.
"""


class _Benchmark:
    def output_errors(self, workspace: Path) -> list[str]:
        return [] if (workspace / "answer.txt").is_file() else ["answer.txt"]

    def render_user_review(self, workspace: Path) -> str:
        return (workspace / "answer.txt").read_text(encoding="utf-8")


def _task(root: Path) -> tuple[Path, Path]:
    task = root / "task"
    (task / "environment" / "data").mkdir(parents=True)
    (task / "instruction.md").write_text("Do the task.\n")
    (task / "environment" / "data" / "x.txt").write_text("input\n")
    source = root / "source"
    source.mkdir()
    (source / "answer.txt").write_text("observed answer\n")
    (source / "trace.md").write_text("observed trace\n")
    return task, source


def _generation() -> RubricGeneration:
    rubric = CompleteRubric.from_content(RUBRIC)
    return RubricGeneration(
        generation_round=1,
        source_checkpoint=None,
        rubric=rubric,
        elicited_criteria=(),
        proposer_call_budget=2,
    )


def test_red_team_sidecar_branches_seals_and_reuses(
    tmp_path: Path,
) -> None:
    task, source = _task(tmp_path)
    calls: list[str] = []

    def run(workspace: Path, prompt: str, turn_dir: Path) -> SessionTurnResult:
        calls.append(prompt)
        assert (workspace / "answer.txt").read_text() == "observed answer\n"
        (workspace / "answer.txt").write_text("subtle invalid answer\n")
        turn_dir.mkdir(parents=True)
        trajectory = turn_dir / "trajectory.stream.jsonl"
        trajectory.write_text('{"type":"result","status":"completed"}\n')
        return SessionTurnResult(
            session_id="red-team-session",
            model="red-team-model",
            exit_code=0,
            trajectory_path=trajectory,
        )

    generator = RedTeamGenerator(
        agent=AgentRunConfig(provider="codex", model="red-team-model"),
        benchmark=_Benchmark(),  # type: ignore[arg-type]
        run_sidecar=run,
    )
    experiment = tmp_path / "experiment"
    first = generator.ensure(
        task_dir=task,
        source_workspace=source,
        active_generation=_generation(),
        checkpoint=1,
        experiment_dir=experiment,
    )
    second = generator.ensure(
        task_dir=task,
        source_workspace=source,
        active_generation=_generation(),
        checkpoint=1,
        experiment_dir=experiment,
    )

    assert first == second
    assert first.included
    assert len(calls) == 1
    assert RUBRIC in calls[0]
    assert (first.root / "workspace" / "answer.txt").read_text() == (
        "subtle invalid answer\n"
    )
    assert not (first.root / "workspace" / "instruction.md").exists()
    assert load_red_team_artifact(
        experiment,
        1,
        expected_generator=generator.identity(),
        expected_active_rubric_sha256=sha256_text(RUBRIC),
    ) == first


def test_red_team_prompt_states_the_white_box_objective() -> None:
    prompt = red_team_prompt(RUBRIC).lower()

    assert "white-box" in prompt
    assert "actual task result remains materially wrong" in prompt
    assert "do not reveal" in prompt
    assert "do not modify" in prompt
