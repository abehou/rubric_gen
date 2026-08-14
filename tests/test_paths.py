from pathlib import Path

import pytest

from rubric_gen.runtime.paths import (
    PROJECT_ROOT,
    directory_component,
    resolve_project_path,
)
from rubric_gen.artifacts.serialization import write_json_atomic


@pytest.mark.parametrize("value", ["bad\npath", "bad\tpath", "bad\x7fpath"])
def test_resolve_project_path_rejects_control_characters(value: str) -> None:
    with pytest.raises(ValueError, match="control characters"):
        resolve_project_path(value)


def test_resolve_project_path_accepts_normal_absolute_path(tmp_path: Path) -> None:
    assert resolve_project_path(tmp_path) == tmp_path


def test_resolve_project_path_uses_repository_root() -> None:
    repository_root = Path(__file__).resolve().parents[1]

    assert PROJECT_ROOT == repository_root
    assert (
        resolve_project_path("experiment_preflight.yaml")
        == repository_root / "experiment_preflight.yaml"
    )


def test_directory_component_is_stable_and_bounded() -> None:
    value = "model/" + "x" * 100
    first = directory_component(value)

    assert first == directory_component(value)
    assert len(first) == 48
    assert "/" not in first


def test_write_json_atomic_replaces_content_without_leaking_temp_files(
    tmp_path: Path,
) -> None:
    target = tmp_path / "state.json"
    target.write_text('{"old": true}\n')

    write_json_atomic(target, {"new": True})

    assert target.read_text() == '{\n  "new": true\n}\n'
    assert list(tmp_path.iterdir()) == [target]
