from __future__ import annotations

import pytest

from rubric_gen.biomnibench.cli import build_parser


def test_cli_exposes_only_core_workflow() -> None:
    parser = build_parser()
    subparsers = next(
        action for action in parser._actions if hasattr(action, "choices") and action.choices
    )
    assert set(subparsers.choices) == {"seed", "revise", "detect", "judge"}


@pytest.mark.parametrize(
    "argv",
    [
        ["revise", "--design", "d", "--seed-dir", "s", "--output-dir", "o", "--dry-run"],
        ["detect", "--run-dir", "r", "--output-dir", "o", "--preflight-only"],
    ],
)
def test_cli_rejects_non_executing_modes(argv: list[str]) -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args(argv)


def test_cli_requires_a_command() -> None:
    with pytest.raises(SystemExit):
        build_parser().parse_args([])
