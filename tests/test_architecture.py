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


def test_removed_top_level_benchmark_packages_have_no_callers() -> None:
    legacy_packages = ("biomnibench", "harvey", "malt", "paperbench")
    for package in legacy_packages:
        assert not tuple((SOURCE_ROOT / package).rglob("*.py"))
    for path in SOURCE_ROOT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        for package in legacy_packages:
            assert f"rubric_gen.{package}" not in source


def test_shared_code_does_not_import_concrete_benchmarks() -> None:
    concrete_packages = (
        "rubric_gen.benchmarks.biomnibench_da",
        "rubric_gen.benchmarks.harvey_lab",
        "rubric_gen.benchmarks.malt",
        "rubric_gen.benchmarks.paperbench_code_dev",
    )
    for package in ("runtime", "evidence", "reward_hacking", "submission_revision"):
        for path in (SOURCE_ROOT / package).rglob("*.py"):
            source = path.read_text(encoding="utf-8")
            assert not any(name in source for name in concrete_packages)


def test_runtime_does_not_resolve_benchmarks() -> None:
    for path in (SOURCE_ROOT / "runtime").rglob("*.py"):
        assert "rubric_gen.benchmarks" not in path.read_text(encoding="utf-8")


def test_reward_hacking_does_not_import_workflows_or_benchmarks() -> None:
    forbidden = (
        "rubric_gen.submission_revision",
        "rubric_gen.benchmarks",
    )
    for path in (SOURCE_ROOT / "reward_hacking").rglob("*.py"):
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
        "rubric_gen.reward_hacking",
    )
    for path in (SOURCE_ROOT / "artifacts").rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert not any(name in source for name in forbidden)


def test_judge_attestation_includes_the_selected_benchmark_contract() -> None:
    biomni = JudgeExecutor.judge_runner_sha256(SubmissionBenchmarkId.BIOMNIBENCH_DA)
    paperbench = JudgeExecutor.judge_runner_sha256(SubmissionBenchmarkId.PAPERBENCH_CODE_DEV)

    assert len(biomni) == len(paperbench) == 64
    assert biomni != paperbench
