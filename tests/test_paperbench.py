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
from rubric_gen.submission_revision.judging.full_rubric_protocol import (
    full_rubric_payload,
)
from rubric_gen.submission_revision.judging.models import JudgeRunConfig, JudgeTarget
from rubric_gen.submission_revision.judging.runner import SubmissionJudgeRunner
from rubric_gen.submission_revision.controller_scoring import RevisionScorer
from rubric_gen.submission_revision.artifacts import compact_historical_workspace
import rubric_gen.submission_revision.evolution_protocol as protocol_module
from rubric_gen.submission_revision.evolution_artifacts import (
    ArtifactHistory,
    ArtifactPair,
    BlindedArtifact,
)
from rubric_gen.submission_revision.feedback import FeedbackPolicy, render_feedback_prompt
from rubric_gen.submission_revision.prompts import PromptProfile
from rubric_gen.submission_revision.rubric_generation import (
    CompleteRubric,
    ElicitedCriterion,
    RubricGeneration,
    render_augmented_rubric,
)
from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.submission_revision.judging.scoring import (
    parse_rubric_levels_strict,
    validate_judge_score,
)
from rubric_gen.benchmarks.paperbench_code_dev.submission import render_submission_tree
from rubric_gen.benchmarks.paperbench_code_dev.dataset import (
    PAPERBENCH_DEV_PAPERS,
    PAPERBENCH_RESULTS_PAPERS,
    PAPERBENCH_REVISION,
    paperbench_papers,
    prepare_paperbench_code_dataset,
    render_code_dev_rubric,
    validate_paperbench_code_dataset,
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


def _artifact_history(contents: tuple[str, ...]) -> ArtifactHistory:
    artifacts = tuple(
        BlindedArtifact(
            artifact_id=f"artifact_{index:016x}",
            source_id=f"hidden-source-{index}",
            content_sha256=sha256_text(content),
            content=content,
        )
        for index, content in enumerate(contents, start=1)
    )
    return ArtifactHistory(
        artifacts=artifacts,
        pairs=tuple(
            ArtifactPair.create(
                artifacts[left].artifact_id,
                artifacts[right].artifact_id,
            )
            for left in range(len(artifacts))
            for right in range(left + 1, len(artifacts))
        ),
    )


def _source_tree(
    root: Path,
    paper_ids: tuple[str, ...] = PAPERBENCH_DEV_PAPERS,
) -> Path:
    for paper_id in paper_ids:
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
                "criterion_1": {
                    "level_votes": ["B"] * 5,
                    "mean_points": 0.0,
                },
                "criterion_2": {
                    "level_votes": ["A"] * 5,
                    "mean_points": 3.0,
                },
            }
        },
        reward={"score": 75.0},
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


def test_code_dev_rubric_uses_leaf_ids_for_identical_duplicate_ancestry() -> None:
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

    rendered, _, _ = render_code_dev_rubric(rubric)

    assert "Run ten random seeds. [Context: Leaf ID: leaf-a]" in rendered
    assert "Run ten random seeds. [Context: Leaf ID: leaf-b]" in rendered


def test_prepared_dataset_is_reproducible_and_pinned(tmp_path: Path) -> None:
    destination = tmp_path / "prepared"
    prepare_paperbench_code_dataset(
        _source_tree(tmp_path / "source"),
        destination,
        source_split="dev",
        revision=PAPERBENCH_REVISION,
    )

    validate_paperbench_code_dataset(destination, source_split="dev")
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
        validate_paperbench_code_dataset(destination, source_split="dev")


def test_results_paper_set_is_the_exact_official_twenty_paper_set() -> None:
    assert paperbench_papers("dev") == PAPERBENCH_DEV_PAPERS
    assert paperbench_papers("all") == PAPERBENCH_RESULTS_PAPERS
    assert len(PAPERBENCH_DEV_PAPERS) == 3
    assert len(PAPERBENCH_RESULTS_PAPERS) == 20
    assert not set(PAPERBENCH_DEV_PAPERS) & set(PAPERBENCH_RESULTS_PAPERS)


def test_prepared_results_dataset_binds_the_official_all_split(
    tmp_path: Path,
) -> None:
    destination = tmp_path / "prepared-all"
    source = _source_tree(tmp_path / "source-all", PAPERBENCH_RESULTS_PAPERS)
    (source / "data/papers/stochastic-interpolants/config.yaml").write_text(
        "id: stochastic-interpolant\n"
        "title: Stochastic Interpolants with Data-Dependent Couplings\n"
    )
    prepare_paperbench_code_dataset(
        source,
        destination,
        source_split="all",
        revision=PAPERBENCH_REVISION,
    )

    validate_paperbench_code_dataset(destination, source_split="all")
    metadata = json.loads((
        destination / "stochastic-interpolants/tests/paperbench.json"
    ).read_text())
    assert metadata["paper_id"] == "stochastic-interpolants"
    assert metadata["source_config_id"] == "stochastic-interpolant"
    with pytest.raises(ValueError, match="pinned source split"):
        validate_paperbench_code_dataset(destination, source_split="dev")


def test_paperbench_evolution_preserves_binary_scoring_contract() -> None:
    current, _, _ = render_code_dev_rubric(_rubric())
    original = CompleteRubric.from_content(current)
    criterion = ElicitedCriterion.create(
        title="Reproducible execution",
        requirement="The implementation must include a reproducible execution path.",
        level_descriptions=(
            ("A", "A reproducible execution path is implemented."),
            ("B", "No reproducible execution path is implemented."),
        ),
        support_pair_ids=(
            "pair_0000000000000001",
            "pair_0000000000000002",
        ),
        source_generation=1,
    )

    revised = render_augmented_rubric(original, (criterion,))
    levels = parse_rubric_levels_strict(revised.content)
    assert sum(values["A"] for values in levels.values()) == 4
    assert list(levels.values())[-1] == {"A": 0, "B": -1}
    assert "Score normalization maximum: 4" in revised.content
    assert all(set(values) == {"A", "B"} for values in levels.values())
    assert "Implement code-a." in revised.content
    assert "Reproducible execution" in revised.content


def test_paperbench_elicitation_uses_blinded_history_and_penalties() -> None:
    current, _, maximum = render_code_dev_rubric(_rubric())

    rubric = CompleteRubric.from_content(current)
    generation = RubricGeneration(
        generation_round=0,
        source_checkpoint=None,
        rubric=rubric,
        elicited_criteria=(),
        proposer_call_budget=0,
    )
    history = _artifact_history(
        tuple(f"artifact {index}" for index in range(1, 5))
    )
    difference_evidence = protocol_module.difference_evidence(
        instruction="Replicate the paper.",
        original_rubric=rubric,
        current_generation=generation,
        artifact_history=history,
    )
    criterion_evidence = protocol_module.criterion_evidence(
        instruction="Replicate the paper.",
        original_rubric=rubric,
        current_generation=generation,
        artifact_history=history,
        difference_response={
            "pairs": [
                {"pair_id": pair.pair_id, "differences": []}
                for pair in history.pairs
            ]
        },
        remaining_capacity=5,
        level_labels=("A", "B"),
    )

    assert f"Score normalization maximum: {maximum}" in difference_evidence
    assert "hidden-source-1" not in difference_evidence
    assert '"blinded_pair_graph"' in criterion_evidence
    assert '"program_owned_penalty_points_per_criterion":1' in criterion_evidence
    instructions = " ".join(protocol_module.criterion_instructions().split())
    assert "at least three artifacts" in instructions
    assert "Each new criterion is penalty-only" in instructions
    assert "Do not choose points or weights" in instructions


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
        {"policy": "score_only", "score": 50, "generation_sha256": "0" * 64},
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
    current_generation = RubricGeneration(
        generation_round=0,
        source_checkpoint=None,
        rubric=current_rubric,
        elicited_criteria=(),
        proposer_call_budget=0,
    )
    native_submission = render_submission_tree(workspace)
    history = _artifact_history(
        (native_submission, "reference 1", "reference 2", "reference 3")
    )
    proposed = protocol_module.difference_evidence(
        instruction="TASK",
        original_rubric=current_rubric,
        current_generation=current_generation,
        artifact_history=history,
    )

    assert "native submission" in judged
    assert "NON-NATIVE ANSWER" not in judged
    assert "NON-NATIVE TRACE" not in judged
    assert "native submission" in proposed
    assert "hidden-source-1" not in proposed
    payload = json.loads(full_rubric_payload("RUBRIC", judged, ""))
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
    generation = RubricGeneration(
        generation_round=0,
        source_checkpoint=None,
        rubric=rubric,
        elicited_criteria=(),
        proposer_call_budget=0,
    )
    validation = tmp_path / "score-validation.json"
    validation.write_text(json.dumps({
        "score": 100.0,
        "normalized_score": 1.0,
        "raw_score": 100.0,
        "criterion_level_votes": {"criterion_1": ["A"] * 5},
        "criterion_scores": {"criterion_1": 100.0},
        "rendered_rubric_sha256": rubric_sha256,
    }))
    captured: dict[str, object] = {}

    class Simulator:
        def generate(self, **kwargs):
            captured.update(kwargs)
            return {"sealed": True}

        def validate(self, *_args, **_kwargs):
            return "Please improve the implementation evidence."

    scorer = object.__new__(RevisionScorer)
    scorer.config = SimpleNamespace(
        feedback_policy=FeedbackPolicy.USER_SIMULATOR,
        experiment_id="paperbench-simulated-user-test",
        assignment_id="paper--rep-001--base-fixed",
        prompt_profile=PromptProfile.BASE,
        benchmark=SubmissionBenchmarkId.PAPERBENCH_CODE_DEV,
    )
    scorer.benchmark = PAPERBENCH_CODE_DEV
    scorer.experiment_dir = tmp_path / "experiment"
    (scorer.experiment_dir / "feedback-generations").mkdir(parents=True)
    scorer.task_dir = task
    scorer.dependencies = SimpleNamespace(feedback_simulator=Simulator())

    scorer.project_checkpoint_feedback(
        artifacts=SimpleNamespace(
            score_validation_path=validation,
            evaluation_path=validation,
        ),
        generation=generation,
        submission_id="s000",
        generation_round=0,
            submission_dir=submission_dir,
            allow_generation=True,
            fixed_original_score=100.0,
            fixed_original_artifacts=SimpleNamespace(
                score_validation_path=validation,
                evaluation_path=validation,
            ),
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
