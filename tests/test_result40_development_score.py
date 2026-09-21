from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from types import SimpleNamespace

import pytest

from rubric_gen.artifacts.hashing import sha256_file


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = (
    ROOT / "experiments/trace-v21-result40-development-gap/run.py"
)
ANALYSIS = (
    ROOT / "experiments/trace-v21-result40-development-gap/analyze.py"
)


def load_script():
    spec = spec_from_file_location("result40_development_gap", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def load_analysis():
    spec = spec_from_file_location("result40_development_gap_analysis", ANALYSIS)
    assert spec is not None and spec.loader is not None
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_development_group_contains_only_variant_one(tmp_path):
    module = load_script()
    rubric = tmp_path / "variant-001.txt"
    rubric.write_text("development")
    target = SimpleNamespace(selection=SimpleNamespace(
        development_path=rubric,
        development_sha256=sha256_file(rubric),
        development_index=1,
    ))

    grouped = module.DevelopmentScoreStage._grouped_rubrics(
        target, "final", module.MODELS
    )

    assert len(grouped.paths) == 2
    assert {model for _, model in grouped.paths} == set(module.MODELS)
    assert {
        (role.name, role.variant_index)
        for roles in grouped.roles.values()
        for role in roles
    } == {("development", 1)}


@pytest.mark.parametrize(
    ("index", "filename"),
    [(0, "variant-001.txt"), (1, "variant-002.txt")],
)
def test_development_group_rejects_any_variant_other_than_one(
    tmp_path, index, filename
):
    module = load_script()
    rubric = tmp_path / filename
    rubric.write_text("development")
    target = SimpleNamespace(selection=SimpleNamespace(
        development_path=rubric,
        development_sha256=sha256_file(rubric),
        development_index=index,
    ))

    with pytest.raises(RuntimeError, match="requires rubric variant 1"):
        module.DevelopmentScoreStage._grouped_rubrics(
            target, "final", module.MODELS
        )


def test_fixed_diagnostic_scope_is_120_judgments():
    module = load_script()
    assert len(module.TASKS) == 5
    assert len(module.KINDS) == 2
    assert len(module.MODELS) == 2
    assert len(module.TASKS) * len(module.KINDS) * 6 * len(module.MODELS) == 120
    assert module.CONDITIONS == {
        "static": ("full-static", "user-simulator-static"),
        "trace": (
            "full-red-team-trace-execution-verified-proactive-provenance",
            "user-simulator-red-team-trace-execution-verified-proactive-provenance",
        ),
    }


def test_analysis_pairs_rtt_minus_static_and_preserves_decomposition():
    module = load_analysis()
    common = {
        "task_id": "da-26-4",
        "replicate": 1,
        "arm": "Full",
        "assignment_id": "assignment",
    }
    rows = [
        {
            **common,
            "condition": "Static",
            "S": 90.0,
            "D": 80.0,
            "H": 70.0,
            "S_minus_D": 10.0,
            "D_minus_H": 10.0,
            "S_minus_H": 20.0,
        },
        {
            **common,
            "condition": "RTT",
            "S": 85.0,
            "D": 82.0,
            "H": 75.0,
            "S_minus_D": 3.0,
            "D_minus_H": 7.0,
            "S_minus_H": 10.0,
        },
    ]

    paired = module.paired_rows(rows, include_model=False)

    assert len(paired) == 1
    assert paired[0]["delta_S"] == -5.0
    assert paired[0]["delta_D"] == 2.0
    assert paired[0]["delta_H"] == 5.0
    assert paired[0]["delta_S_minus_D"] == -7.0
    assert paired[0]["delta_D_minus_H"] == -3.0
    assert paired[0]["delta_S_minus_H"] == -10.0


def test_analysis_uses_only_same_sol_gemini_panel():
    module = load_analysis()
    assert module.MODELS == ("gpt-5.6-sol", "gemini-3.8-flash")
    assert module.PANEL_TO_MODEL == {
        "sol": "gpt-5.6-sol",
        "gemini": "gemini-3.8-flash",
    }
