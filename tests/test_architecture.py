from __future__ import annotations

from pathlib import Path

from rubric_gen.benchmarks import SubmissionBenchmarkId, get_submission_benchmark
from rubric_gen.submission_revision.judging.executor import JudgeExecutor


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "rubric_gen"


def test_every_submission_benchmark_has_one_native_contract() -> None:
    contracts = tuple(
        get_submission_benchmark(benchmark) for benchmark in SubmissionBenchmarkId
    )

    assert tuple(contract.benchmark for contract in contracts) == tuple(
        SubmissionBenchmarkId
    )
    assert len({id(contract) for contract in contracts}) == len(SubmissionBenchmarkId)


def test_python_modules_remain_below_giant_file_threshold() -> None:
    for path in SOURCE_ROOT.rglob("*.py"):
        line_count = len(path.read_text(encoding="utf-8").splitlines())
        assert line_count < 1_000, f"{path.relative_to(SOURCE_ROOT)} has {line_count} lines"


def test_removed_top_level_benchmark_packages_have_no_callers() -> None:
    legacy_packages = ("biomnibench", "harvey", "malt", "paperbench")
    for package in legacy_packages:
        assert not tuple((SOURCE_ROOT / package).rglob("*.py"))
    for path in SOURCE_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for package in legacy_packages:
            assert f"rubric_gen.{package}" not in source


def test_old_reward_hacking_paths_are_removed() -> None:
    assert not (SOURCE_ROOT / "reward_hacking").exists()
    revision = SOURCE_ROOT / "submission_revision"
    assert not tuple(revision.glob("rh_*.py"))


def test_shared_code_does_not_import_concrete_benchmarks() -> None:
    concrete_packages = (
        "rubric_gen.benchmarks.biomnibench_da",
        "rubric_gen.benchmarks.harvey_lab",
        "rubric_gen.benchmarks.malt",
        "rubric_gen.benchmarks.paperbench_code_dev",
    )
    for package in ("runtime", "evidence", "detection", "submission_revision"):
        for path in (SOURCE_ROOT / package).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert not any(name in source for name in concrete_packages)


def test_runtime_does_not_resolve_benchmarks() -> None:
    for path in (SOURCE_ROOT / "runtime").rglob("*.py"):
        assert "rubric_gen.benchmarks" not in path.read_text(encoding="utf-8")


def test_detection_does_not_import_workflows_or_benchmarks() -> None:
    forbidden = (
        "rubric_gen.submission_revision",
        "rubric_gen.benchmarks",
    )
    for path in (SOURCE_ROOT / "detection").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not any(name in source for name in forbidden)


def test_benchmarks_do_not_import_submission_workflows() -> None:
    for path in (SOURCE_ROOT / "benchmarks").rglob("*.py"):
        assert "rubric_gen.submission_revision" not in path.read_text(
            encoding="utf-8"
        )


def test_artifact_utilities_do_not_import_runtime_or_workflows() -> None:
    forbidden = (
        "rubric_gen.runtime",
        "rubric_gen.submission_revision",
        "rubric_gen.benchmarks",
        "rubric_gen.detection",
    )
    for path in (SOURCE_ROOT / "artifacts").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not any(name in source for name in forbidden)


def test_judge_attestation_includes_the_selected_benchmark_contract() -> None:
    biomni = JudgeExecutor.scoring_implementation_sha256(
        SubmissionBenchmarkId.BIOMNIBENCH_DA
    )
    paperbench = JudgeExecutor.scoring_implementation_sha256(
        SubmissionBenchmarkId.PAPERBENCH_CODE_DEV
    )

    assert len(biomni) == len(paperbench) == 64
    assert biomni != paperbench


def test_revision_evaluation_modules_remain_focused() -> None:
    package = SOURCE_ROOT / "submission_revision" / "evaluation"
    modules = (
        "jobs.py",
        "targets.py",
        "rubric_score.py",
        "score_execution.py",
        "absolute_score.py",
        "pairwise_preference.py",
        "runner.py",
        "store.py",
    )

    for module in modules:
        line_count = len((package / module).read_text(encoding="utf-8").splitlines())
        assert line_count < 1_000, f"{module} has {line_count} lines"


def test_detection_panel_modules_remain_focused() -> None:
    package = SOURCE_ROOT / "detection"
    modules = (
        "runner.py",
        "costs.py",
        "jobs.py",
        "planning.py",
        "job_runner.py",
    )

    for module in modules:
        source = (package / module).read_text(encoding="utf-8")
        line_count = len(source.splitlines())
        assert line_count < 1_000, f"{module} has {line_count} lines"

    runner_source = (package / "runner.py").read_text(encoding="utf-8")
    assert "class DetectionConfig" not in runner_source
    assert "class PreparedJob" not in runner_source
    assert "def _run_batch" not in runner_source


def test_rubric_generation_and_judge_runner_modules_remain_focused() -> None:
    submission_revision = SOURCE_ROOT / "submission_revision"
    modules = (
        submission_revision / "rubric_generation.py",
        submission_revision / "rubric_generation_store.py",
        submission_revision / "judging" / "runner.py",
    )

    for module in modules:
        line_count = len(module.read_text(encoding="utf-8").splitlines())
        assert line_count < 1_000, f"{module.name} has {line_count} lines"

    domain_source = modules[0].read_text(encoding="utf-8")
    assert "rubric_generation_store" not in domain_source


def test_rubric_evolution_modules_remain_focused() -> None:
    package = SOURCE_ROOT / "submission_revision"
    modules = (
        "evolution.py",
        "evolution_assessment.py",
        "evolution_artifacts.py",
        "evolution_protocol.py",
        "evolution_provider.py",
        "evolution_request.py",
        "evolution_serialization.py",
        "rubric_generation_store.py",
    )

    sources = []
    for module in modules:
        source = (package / module).read_text(encoding="utf-8")
        sources.append(source)
        line_count = len(source.splitlines())
        assert line_count < 1_000, f"{module} has {line_count} lines"

    combined = "\n".join(sources)
    assert "MultiRubricProposerOutput" not in combined
    assert "SemanticReviewerOutput" not in combined


def test_revision_controller_modules_remain_focused() -> None:
    package = SOURCE_ROOT / "submission_revision"
    modules = (
        "controller.py",
        "controller_recovery.py",
        "controller_recovery_artifacts.py",
        "controller_scoring.py",
        "controller_setup.py",
        "controller_workspace.py",
    )

    for module in modules:
        source = (package / module).read_text(encoding="utf-8")
        line_count = len(source.splitlines())
        assert line_count < 1_000, f"{module} has {line_count} lines"

    controller = (package / "controller.py").read_text(encoding="utf-8")
    assert "def _run_judge_checkpoint" not in controller
    assert "def _recover_failed_solver_checkpoint" not in controller
    assert "def _snapshot_submission" not in controller


def test_revision_study_modules_remain_focused() -> None:
    package = SOURCE_ROOT / "submission_revision"
    modules = (
        "study.py",
        "study_layout.py",
        "study_validation.py",
        "study_validation_artifacts.py",
        "study_validation_context.py",
    )

    for module in modules:
        source = (package / module).read_text(encoding="utf-8")
        line_count = len(source.splitlines())
        assert line_count < 1_000, f"{module} has {line_count} lines"

    study = (package / "study.py").read_text(encoding="utf-8")
    assert "def validate_completed_revision" not in study
    assert "def resolve_study_experiment" not in study


def test_original_rubric_modules_remain_focused() -> None:
    package = SOURCE_ROOT / "submission_revision"
    runner = (package / "original_rubric.py").read_text(encoding="utf-8")
    inputs = (package / "original_rubric_inputs.py").read_text(encoding="utf-8")
    summary = (package / "original_rubric_summary.py").read_text(encoding="utf-8")

    assert "class OriginalRubricEnsembleConfig" not in runner
    assert "class OriginalRubricEnsembleRunner" not in inputs
    assert "class OriginalRubricEnsembleRunner" not in summary
    assert "def assignment_summaries" not in runner


def test_paraphrase_modules_remain_focused() -> None:
    package = SOURCE_ROOT / "submission_revision"
    workflow = (package / "paraphrases.py").read_text(encoding="utf-8")
    protocol = (package / "paraphrase_protocol.py").read_text(encoding="utf-8")
    validation = (package / "paraphrase_validation.py").read_text(encoding="utf-8")

    assert "class WordingTemplate" not in workflow
    assert "class ParaphraseRunner" not in protocol
    assert "class ParaphraseSelection" not in workflow
    assert "class ParaphraseRunner" not in validation


def test_full_rubric_judge_modules_remain_focused() -> None:
    package = SOURCE_ROOT / "submission_revision" / "judging"
    executor = (package / "full_rubric_judge.py").read_text(encoding="utf-8")
    protocol = (package / "full_rubric_protocol.py").read_text(encoding="utf-8")

    assert "class FullRubricRunSpec" not in executor
    assert "def _generate_response" not in protocol
