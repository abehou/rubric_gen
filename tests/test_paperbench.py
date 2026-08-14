from __future__ import annotations

import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rubric_gen.benchmarks import Benchmark, get_benchmark
from rubric_gen.benchmarks.paperbench_code_dev import (
    PAPERBENCH_CODE_DEV,
    PAPERBENCH_CODE_DEV_PROMPT,
)
from rubric_gen.submission_revision.judging.llm_judge import judge_prompt
from rubric_gen.submission_revision.judging.models import JudgeRunConfig, JudgeTarget
from rubric_gen.submission_revision.judging.runner import SubmissionJudgeRunner
from rubric_gen.submission_revision.controller import SubmissionRevisionController
from rubric_gen.submission_revision.artifacts import compact_historical_workspace
from rubric_gen.submission_revision.evolution import _validated_complete_rubric
import rubric_gen.submission_revision.evolution as evolution_module
from rubric_gen.submission_revision.evolution import RubricScoreContext
from rubric_gen.submission_revision.feedback import FeedbackPolicy, render_feedback_prompt
from rubric_gen.submission_revision.prompts import PromptProfile
from rubric_gen.submission_revision.judging.scoring import (
    parse_rubric_levels_strict,
    validate_judge_score,
)
from rubric_gen.paperbench.evidence import render_submission_tree
from rubric_gen.paperbench.loader import (
    PAPERBENCH_DEV_PAPERS,
    PAPERBENCH_REVISION,
    prepare_paperbench_code_dev,
    render_code_dev_rubric,
    validate_paperbench_code_dev_dataset,
)


def _leaf(node_id: str, weight: int, category: str) -> dict[str, object]:
    return {
        "id": node_id,
        "requirements": f"Implement {node_id}.",
        "weight": weight,
        "task_category": category,
        "sub_tasks": [],
    }


def _rubric() -> dict[str, object]:
    return {
        "id": "root",
        "requirements": "Replicate the paper.",
        "weight": 1,
        "sub_tasks": [
            {
                "id": "code",
                "requirements": "Code.",
                "weight": 2,
                "sub_tasks": [
                    _leaf("code-a", 1, "Code Development"),
                    _leaf("code-b", 3, "Code Development"),
                ],
            },
            _leaf("analysis", 8, "Result Analysis"),
        ],
    }


def _source_tree(root: Path) -> Path:
    for paper_id in PAPERBENCH_DEV_PAPERS:
        paper = root / "data" / "papers" / paper_id
        (paper / "assets" / "nested").mkdir(parents=True)
        (paper / "config.yaml").write_text(
            f"id: {paper_id}\ntitle: Test {paper_id}\n"
        )
        (paper / "paper.md").write_text("# Paper\n")
        (paper / "addendum.md").write_text("Use local data.\n")
        (paper / "blacklist.txt").write_text("forbidden.example\n")
        (paper / "rubric.json").write_text(json.dumps(_rubric()))
        (paper / "assets" / "nested" / "input.txt").write_text("asset\n")
    return root


def test_code_dev_rubric_uses_exact_official_binary_weights() -> None:
    rendered, leaf_count, maximum = render_code_dev_rubric(_rubric())

    assert leaf_count == 2
    assert maximum == 4
    assert "Score normalization maximum: 4" in rendered
    assert "Levels: A=1 B=0" in rendered
    assert "Levels: A=3 B=0" in rendered
    assert "partial" not in rendered.lower()
    assert "analysis" not in rendered

    score = validate_judge_score(
        rubric_levels=parse_rubric_levels_strict(rendered),
        evaluation={
            "criteria": {
                "criterion_1": {"level": "B"},
                "criterion_2": {"level": "A"},
            }
        },
        reward={"score": 75},
        normalization_maximum=maximum,
    )
    assert score.raw_score == 3
    assert score.normalized_score == 0.75


def test_prepared_dataset_is_reproducible_and_pinned(tmp_path: Path) -> None:
    destination = tmp_path / "prepared"
    prepare_paperbench_code_dev(
        _source_tree(tmp_path / "source"),
        destination,
        revision=PAPERBENCH_REVISION,
    )

    validate_paperbench_code_dev_dataset(destination)
    assert (
        destination
        / PAPERBENCH_DEV_PAPERS[0]
        / "environment"
        / "data"
        / "assets"
        / "nested"
        / "input.txt"
    ).read_text() == "asset\n"

    rubric = (
        destination / PAPERBENCH_DEV_PAPERS[0] / "tests" / "rubric.txt"
    )
    rubric.write_text(rubric.read_text() + "tampered\n")
    with pytest.raises(ValueError, match="not reproducible"):
        validate_paperbench_code_dev_dataset(destination)


def test_paperbench_evolution_preserves_binary_scoring_contract() -> None:
    current, _, _ = render_code_dev_rubric(_rubric())
    revised = current.replace("Criterion 1: Implement", "Criterion 1: Correctly implement")

    assert _validated_complete_rubric(revised, current_rubric=current) == revised
    with pytest.raises(ValueError, match="exactly A and B"):
        _validated_complete_rubric(
            revised.replace("Levels: A=1 B=0", "Levels: A=1 B=0 C=-1"),
            current_rubric=current,
        )


def test_paperbench_proposer_names_the_exact_fixed_normalization() -> None:
    current, _, maximum = render_code_dev_rubric(_rubric())

    instructions = evolution_module._proposer_instructions(
        current_rubric=current,
        repair_error="complete rubric changed its score normalization directive",
    )

    assert f"`Score normalization maximum: {maximum}`" in instructions
    assert f"A-level points must equal {maximum}" in instructions
    assert "another round value" in instructions


def test_submission_evidence_uses_official_code_dev_file_types(tmp_path: Path) -> None:
    submission = tmp_path / "submission"
    submission.mkdir()
    (submission / "model.py").write_text("print('model')\n")
    (submission / "results.csv").write_text("not code evidence\n")

    rendered = render_submission_tree(tmp_path)

    assert "model.py" in rendered
    assert "results.csv" not in rendered


def test_paperbench_requires_only_native_submission_repository(tmp_path: Path) -> None:
    submission = tmp_path / "submission"
    submission.mkdir()
    (submission / "README.md").write_text("# Replication\n")

    assert PAPERBENCH_CODE_DEV.output_errors(tmp_path) == []
    assert "answer.txt" not in PAPERBENCH_CODE_DEV_PROMPT
    assert "trace.md" not in PAPERBENCH_CODE_DEV_PROMPT


def test_paperbench_contract_owns_native_revision_language() -> None:
    contract = get_benchmark(Benchmark.PAPERBENCH_CODE_DEV)
    prompt = render_feedback_prompt(
        {"schema_version": 1, "policy": "score_only", "score": 50},
        benchmark=contract.benchmark,
    )

    assert contract is PAPERBENCH_CODE_DEV
    assert "./submission" in prompt
    assert "README" in prompt
    assert "trace.md" not in prompt
    assert "answer.txt" not in prompt


def test_paperbench_judge_and_proposer_see_source_not_harness_summaries(
    tmp_path: Path,
) -> None:
    task = tmp_path / "task"
    data = task / "environment" / "data"
    tests = task / "tests"
    data.mkdir(parents=True)
    tests.mkdir()
    (data / "paper.md").write_text("# Source paper\n")
    (data / "addendum.md").write_text("Author guidance.\n")
    workspace = tmp_path / "workspace"
    submission = workspace / "submission"
    submission.mkdir(parents=True)
    (submission / "README.md").write_text("# Replication\n")
    (submission / "model.py").write_text("print('native submission')\n")
    (workspace / "answer.txt").write_text("NON-NATIVE ANSWER\n")
    (workspace / "trace.md").write_text("NON-NATIVE TRACE\n")
    target = JudgeTarget(
        task="paper",
        task_dir=task,
        run_dir=tmp_path / "run",
        workspace_dir=workspace,
        trajectory_path=tmp_path / "trajectory.jsonl",
        output_root=tmp_path / "output",
    )
    runner = SubmissionJudgeRunner(JudgeRunConfig(
        run_dir=target.run_dir,
        tasks_dir=tmp_path,
        benchmark=Benchmark.PAPERBENCH_CODE_DEV,
        review="workspace",
    ))

    judged = runner._workspace_review_text(target)
    proposed = evolution_module._proposer_evidence(
        instruction="TASK",
        current_rubric="RUBRIC",
        current_submission=render_submission_tree(workspace),
        auditor_packet='{"schema_version":3,"inspected":"x","findings":[]}\n',
        score_context=RubricScoreContext(
            score=50,
            raw_score=50,
            selected_levels={"criterion_1": "B"},
            criterion_scores={"criterion_1": 50},
            score_history=(50,),
        ),
        rejected_attempts=(),
    )

    assert "native submission" in judged
    assert "NON-NATIVE ANSWER" not in judged
    assert "NON-NATIVE TRACE" not in judged
    assert "native submission" in proposed
    assert "<current_answer>" not in proposed
    assert "<answer>" not in judge_prompt("RUBRIC", judged, "").evidence


def test_paperbench_simulated_user_sees_native_submission_tree(
    tmp_path: Path,
) -> None:
    task = tmp_path / "task"
    task.mkdir()
    (task / "instruction.md").write_text("Implement the paper.\n")
    submission_dir = tmp_path / "submission-record"
    workspace = submission_dir / "workspace"
    submission = workspace / "submission"
    submission.mkdir(parents=True)
    (submission / "README.md").write_text("# Replication\n")
    (submission / "model.py").write_text("print('native source')\n")
    (workspace / "answer.txt").write_text("NON-NATIVE ANSWER\n")

    rubric_text = "Criterion 1: Implementation\nLevels: A=100 B=0\n"
    rubric_sha256 = hashlib.sha256(rubric_text.encode()).hexdigest()
    validation = tmp_path / "score-validation.json"
    validation.write_text(json.dumps({
        "score": 100,
        "normalized_score": 1.0,
        "raw_score": 100,
        "selected_levels": {"criterion_1": "A"},
        "criterion_scores": {"criterion_1": 100},
        "rendered_rubric_sha256": rubric_sha256,
    }))
    captured: dict[str, object] = {}

    class Simulator:
        def generate(self, **kwargs):
            captured.update(kwargs)
            return {"sealed": True}

        def validate(self, *_args, **_kwargs):
            return "Please improve the implementation evidence."

    controller = object.__new__(SubmissionRevisionController)
    controller.config = SimpleNamespace(
        feedback_policy=FeedbackPolicy.SIMULATED_USER,
        experiment_id="paperbench-simulated-user-test",
        assignment_id="paper--rep-001--base-static",
        prompt_profile=PromptProfile.BASE,
        benchmark=Benchmark.PAPERBENCH_CODE_DEV,
    )
    controller.benchmark = PAPERBENCH_CODE_DEV
    controller.experiment_dir = tmp_path / "experiment"
    (controller.experiment_dir / "feedback-generations").mkdir(parents=True)
    controller.task_dir = task
    controller.dependencies = SimpleNamespace(feedback_simulator=Simulator())

    controller._project_boundary_feedback(
        artifacts=SimpleNamespace(score_validation_path=validation),
        rubric=SimpleNamespace(text=rubric_text, sha256=rubric_sha256),
        submission_id="s000",
        rubric_version=0,
        submission_dir=submission_dir,
        allow_generation=True,
    )

    rendered = str(captured["current_submission"])
    assert "## File: README.md" in rendered
    assert "## File: model.py" in rendered
    assert "native source" in rendered
    assert "NON-NATIVE ANSWER" not in rendered


def test_paperbench_historical_compaction_preserves_source_repository(
    tmp_path: Path,
) -> None:
    submission = tmp_path / "submission"
    submission.mkdir()
    (submission / "README.md").write_text("# Replication\n")
    (submission / "model.py").write_text("pass\n")
    (tmp_path / "answer.txt").write_text("remove me\n")

    compact_historical_workspace(
        tmp_path,
        retained_names=frozenset({"submission"}),
    )

    assert (submission / "model.py").read_text() == "pass\n"
    assert not (tmp_path / "answer.txt").exists()
