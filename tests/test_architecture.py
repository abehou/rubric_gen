from __future__ import annotations

from pathlib import Path

from rubric_gen.benchmarks import Benchmark, get_benchmark
from rubric_gen.submission_revision.judging.executor import JudgeExecutor


SOURCE_ROOT = Path(__file__).resolve().parents[1] / "src" / "rubric_gen"


def test_every_submission_benchmark_has_one_native_contract() -> None:
    contracts = tuple(get_benchmark(benchmark) for benchmark in Benchmark)

    assert tuple(contract.benchmark for contract in contracts) == tuple(Benchmark)
    assert len({id(contract) for contract in contracts}) == len(Benchmark)


def test_removed_benchmark_named_shared_package_has_no_callers() -> None:
    assert not tuple((SOURCE_ROOT / "biomnibench").rglob("*.py"))
    for path in SOURCE_ROOT.rglob("*.py"):
        assert "rubric_gen.biomnibench" not in path.read_text(encoding="utf-8")


def test_shared_workflows_depend_on_contracts_not_paperbench_modules() -> None:
    for package in ("runtime", "evidence", "submission_revision"):
        for path in (SOURCE_ROOT / package).rglob("*.py"):
            assert "rubric_gen.paperbench" not in path.read_text(encoding="utf-8")


def test_judge_attestation_includes_the_selected_benchmark_contract() -> None:
    biomni = JudgeExecutor.judge_runner_sha256(Benchmark.BIOMNIBENCH_DA)
    paperbench = JudgeExecutor.judge_runner_sha256(Benchmark.PAPERBENCH_CODE_DEV)

    assert len(biomni) == len(paperbench) == 64
    assert biomni != paperbench
