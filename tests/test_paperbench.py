from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from rubric_gen.benchmarks import SubmissionBenchmarkId, get_submission_benchmark
from rubric_gen.benchmarks.paperbench_code_dev.contract import (
    PAPERBENCH_CODE_DEV,
    PAPERBENCH_CODE_DEV_PROMPT,
)
from rubric_gen.submission_revision.judging.paperbench_judge import paperbench_payload
from rubric_gen.submission_revision.judging.models import JudgeRunConfig, JudgeTarget
from rubric_gen.submission_revision.judging.runner import SubmissionJudgeRunner
from rubric_gen.submission_revision.controller import SubmissionRevisionController
from rubric_gen.submission_revision.artifacts import compact_historical_workspace
from rubric_gen.submission_revision.evolution import _validated_complete_rubric
import rubric_gen.submission_revision.evolution as evolution_module
from rubric_gen.submission_revision.feedback import FeedbackPolicy, render_feedback_prompt
from rubric_gen.submission_revision.prompts import PromptProfile
from rubric_gen.submission_revision.rubric_bank import (
    CompleteRubric,
    RubricBank,
    RubricBankItem,
    RubricBankPolicy,
    RubricLineage,
    identity_criterion_map,
)
from rubric_gen.submission_revision.judging.scoring import (
    parse_rubric_levels_strict,
    validate_judge_score,
)
from rubric_gen.benchmarks.paperbench_code_dev.submission import render_submission_tree
from rubric_gen.benchmarks.paperbench_code_dev.dataset import (
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


def test_code_dev_rubric_qualifies_repeated_leaves_with_parent_context() -> None:
    rubric = {
        "id": "root",
        "requirements": "Replicate the paper.",
        "weight": 1,
        "sub_tasks": [
            {
                "id": "method-a",
                "requirements": "Method A.",
                "weight": 1,
                "sub_tasks": [{
                    **_leaf("leaf-a", 1, "Code Development"),
                    "requirements": "Run ten random seeds.",
                }],
            },
            {
                "id": "method-b",
                "requirements": "Method B.",
                "weight": 1,
                "sub_tasks": [{
                    **_leaf("leaf-b", 1, "Code Development"),
                    "requirements": "Run ten random seeds.",
                }],
            },
        ],
    }

    rendered, leaf_count, maximum = render_code_dev_rubric(rubric)

    assert leaf_count == 2
    assert maximum == 2
    assert (
        "Criterion 1: Run ten random seeds. [Context: Method A.]"
        in rendered
    )
    assert (
        "Criterion 2: Run ten random seeds. [Context: Method B.]"
        in rendered
    )
    CompleteRubric.from_content(rendered)


def test_code_dev_rubric_uses_the_shortest_distinct_ancestor_suffix() -> None:
    def branch(grandparent_id: str) -> dict[str, object]:
        return {
            "id": grandparent_id,
            "requirements": f"Grandparent {grandparent_id}.",
            "weight": 1,
            "sub_tasks": [{
                "id": f"shared-parent-{grandparent_id}",
                "requirements": "Shared immediate parent.",
                "weight": 1,
                "sub_tasks": [{
                    **_leaf(f"leaf-{grandparent_id}", 1, "Code Development"),
                    "requirements": "Run ten random seeds.",
                }],
            }],
        }

    rubric = {
        "id": "root",
        "requirements": "Replicate the paper.",
        "weight": 1,
        "sub_tasks": [branch("A"), branch("B")],
    }

    rendered, _, _ = render_code_dev_rubric(rubric)

    assert (
        "[Context: Grandparent A. > Shared immediate parent.]"
        in rendered
    )
    assert (
        "[Context: Grandparent B. > Shared immediate parent.]"
        in rendered
    )


def test_code_dev_rubric_rejects_duplicates_with_identical_ancestry() -> None:
    rubric = {
        "id": "root",
        "requirements": "Replicate the paper.",
        "weight": 1,
        "sub_tasks": [{
            "id": "method",
            "requirements": "One method.",
            "weight": 1,
            "sub_tasks": [
                {
                    **_leaf("leaf-a", 1, "Code Development"),
                    "requirements": "Run ten random seeds.",
                },
                {
                    **_leaf("leaf-b", 1, "Code Development"),
                    "requirements": "Run ten random seeds.",
                },
            ],
        }],
    }

    with pytest.raises(
        ValueError,
        match="duplicate leaves lack distinct ancestor context",
    ):
        render_code_dev_rubric(rubric)


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

    assert _validated_complete_rubric(
        revised,
        normalization_maximum=4,
        scoring_protocol="paperbench-code-dev",
    ) == revised
    with pytest.raises(ValueError, match="invalid level labels"):
        _validated_complete_rubric(
            revised.replace("Levels: A=1 B=0", "Levels: A=1 B=0 C=-1"),
            normalization_maximum=4,
            scoring_protocol="paperbench-code-dev",
        )


def test_paperbench_split_proposer_preserves_fixed_normalization_contract() -> None:
    current, _, maximum = render_code_dev_rubric(_rubric())

    rubric = CompleteRubric.from_content(current)
    bank = RubricBank(
        generation_round=0,
        source_boundary=None,
        specification_anchor=rubric,
        specification_anchor_lineage=RubricLineage.NEW,
        prior_specification_anchor_sha256=None,
        items=(RubricBankItem(
            rubric,
            1.0,
            RubricLineage.NEW,
            identity_criterion_map(rubric),
        ),),
    )
    anchor_evidence = evolution_module._anchor_proposer_evidence(
        instruction="Replicate the paper.",
        current_bank=bank,
        policy=RubricBankPolicy.NONADAPTIVE_REPLACEMENT,
        current_submission=None,
        trajectory_context="",
        repair_error="complete rubric changed its normalization directive",
        rejected_attempts=(),
    )
    member_evidence = evolution_module._member_proposer_evidence(
        instruction="Replicate the paper.",
        current_bank=bank,
        next_anchor=rubric,
        repair_error=None,
        rejected_attempts=(),
    )

    assert f"Score normalization maximum: {maximum}" in anchor_evidence
    assert "<harness_anchor_contract>" in anchor_evidence
    assert "scoring_protocol: paperbench-code-dev" in anchor_evidence
    assert f"normalization_maximum: {maximum}" in anchor_evidence
    assert (
        "complete rubric changed its normalization directive"
        in anchor_evidence
    )
    assert "<trajectory_blind_member_contract>" in member_evidence
    assert "member_count: 1" in member_evidence
    assert "member_weight: 1.0" in member_evidence
    assert f"Score normalization maximum: {maximum}" in member_evidence
    instructions = " ".join(evolution_module._member_instructions().split())
    assert "copies every normative anchor clause" in instructions
    assert "assigns unit weight" in instructions


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
    assert "not a Git checkout" in PAPERBENCH_CODE_DEV_PROMPT
    assert "Do not run Git commands" in PAPERBENCH_CODE_DEV_PROMPT
    assert "Use $TMPDIR" in PAPERBENCH_CODE_DEV_PROMPT
    assert "literal /tmp" in PAPERBENCH_CODE_DEV_PROMPT
    for guidance in (
        PAPERBENCH_CODE_DEV.recovery_prompt,
        PAPERBENCH_CODE_DEV.output_recovery_prompt,
        PAPERBENCH_CODE_DEV.revision_action,
    ):
        assert "Do not run Git commands" in guidance
        assert "$TMPDIR" in guidance


def test_paperbench_contract_owns_native_revision_language() -> None:
    contract = get_submission_benchmark(SubmissionBenchmarkId.PAPERBENCH_CODE_DEV)
    prompt = render_feedback_prompt(
        {"policy": "score_only", "score": 50, "bank_sha256": "0" * 64},
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
        benchmark=SubmissionBenchmarkId.PAPERBENCH_CODE_DEV,
        review="workspace",
    ))

    judged = runner._workspace_review_text(target)
    current, _, _ = render_code_dev_rubric(_rubric())
    current_rubric = CompleteRubric.from_content(current)
    current_bank = RubricBank(
        generation_round=0,
        source_boundary=None,
        specification_anchor=current_rubric,
        specification_anchor_lineage=RubricLineage.NEW,
        prior_specification_anchor_sha256=None,
        items=(RubricBankItem(
            current_rubric,
            1.0,
            RubricLineage.NEW,
            identity_criterion_map(current_rubric),
        ),),
    )
    proposed = evolution_module._anchor_proposer_evidence(
        instruction="TASK",
        current_bank=current_bank,
        policy=RubricBankPolicy.ADAPTIVE_REPLACEMENT,
        current_submission=render_submission_tree(workspace),
        trajectory_context='{"events":[]}\n',
        repair_error=None,
        rejected_attempts=(),
    )

    assert "native submission" in judged
    assert "NON-NATIVE ANSWER" not in judged
    assert "NON-NATIVE TRACE" not in judged
    assert "native submission" in proposed
    assert "<current_answer>" not in proposed
    payload = json.loads(paperbench_payload("RUBRIC", judged, ""))
    assert payload["rubric_text"] == "RUBRIC"
    assert payload["artifact_evidence"]["workspace_review"] == judged
    assert payload["artifact_evidence"]["final_answer"] is None


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

    rubric_text = (
        "RUBRIC: Implementation\n\n"
        "Scoring protocol: binary pass/fail\n"
        "Score normalization maximum: 100\n\n"
        "Criterion 1: Implementation\n"
        "Description: Evaluate the implementation.\n"
        "Levels: A=100 B=0\n"
        "[A]: Fully implemented.\n"
        "[B]: Not implemented.\n"
    )
    rubric = CompleteRubric.from_content(rubric_text)
    rubric_sha256 = rubric.content_sha256
    bank = RubricBank(
        generation_round=0,
        source_boundary=None,
        specification_anchor=rubric,
        specification_anchor_lineage=RubricLineage.NEW,
        prior_specification_anchor_sha256=None,
        items=(RubricBankItem(
            rubric,
            1.0,
            RubricLineage.NEW,
            identity_criterion_map(rubric),
        ),),
    )
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
        assignment_id="paper--rep-001--base-fixed",
        prompt_profile=PromptProfile.BASE,
        benchmark=SubmissionBenchmarkId.PAPERBENCH_CODE_DEV,
    )
    controller.benchmark = PAPERBENCH_CODE_DEV
    controller.experiment_dir = tmp_path / "experiment"
    controller.simulator_reuse = None
    (controller.experiment_dir / "feedback-generations").mkdir(parents=True)
    controller.task_dir = task
    controller.dependencies = SimpleNamespace(feedback_simulator=Simulator())

    controller._project_boundary_feedback(
        artifacts={
            rubric_sha256: SimpleNamespace(score_validation_path=validation)
        },
        bank=bank,
        submission_id="s000",
        generation_round=0,
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
