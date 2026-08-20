from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from rubric_gen.submission_revision import contrasts as contrast_module


class _Benchmark:
    @staticmethod
    def render_submission(workspace: Path) -> str:
        return (workspace / "artifact.txt").read_text(encoding="utf-8")


def _workspace(root: Path, name: str, text: str) -> Path:
    workspace = root / name / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "artifact.txt").write_text(text, encoding="utf-8")
    return workspace


def _seed_resolver(root: Path):
    seeds = {
        replicate: _workspace(root, f"seed-{replicate}", f"seed {replicate}\n")
        for replicate in (1, 2, 3)
    }

    def resolve_seed(
        _seed_set: Path,
        _task_dir: Path,
        replicate: int,
        *,
        provider: str,
        requested_model: str,
    ) -> SimpleNamespace:
        assert provider == "codex"
        assert requested_model == "gpt-5.6-luna"
        return SimpleNamespace(submission_dir=seeds[replicate].parent)

    return resolve_seed


def test_offline_contrasts_use_all_three_sealed_pairs_and_hide_sources(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        contrast_module,
        "resolve_seed",
        _seed_resolver(tmp_path),
    )

    contrasts = contrast_module.build_offline_contrasts(
        seed_set=tmp_path / "seeds",
        task_dir=tmp_path / "task",
        benchmark=_Benchmark(),  # type: ignore[arg-type]
        provider="codex",
        requested_model="gpt-5.6-luna",
        assignment_id="assignment-1",
        generation_round=2,
    )

    source_pairs = {
        frozenset((item.artifact_a_id, item.artifact_b_id))
        for item in contrasts
    }
    assert source_pairs == {
        frozenset(("sealed-seed:rep-001", "sealed-seed:rep-002")),
        frozenset(("sealed-seed:rep-001", "sealed-seed:rep-003")),
        frozenset(("sealed-seed:rep-002", "sealed-seed:rep-003")),
    }
    assert [item.pair_id for item in contrasts] == [
        "pair_1",
        "pair_2",
        "pair_3",
    ]
    assert all(
        set(item.model_record()) == {"pair_id", "artifact_a", "artifact_b"}
        for item in contrasts
    )


def test_online_contrasts_use_previous_initial_and_midpoint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        contrast_module,
        "resolve_seed",
        _seed_resolver(tmp_path),
    )
    experiment = tmp_path / "experiment"
    for index in range(6):
        _workspace(
            experiment / "submissions",
            f"s{index:03d}",
            f"live {index}\n",
        )

    contrasts = contrast_module.build_online_contrasts(
        seed_set=tmp_path / "seeds",
        task_dir=tmp_path / "task",
        experiment_dir=experiment,
        benchmark=_Benchmark(),  # type: ignore[arg-type]
        provider="codex",
        requested_model="gpt-5.6-luna",
        assignment_id="assignment-1",
        generation_round=5,
    )

    source_pairs = [
        {item.artifact_a_id, item.artifact_b_id} for item in contrasts
    ]
    assert source_pairs == [
        {"live:s005", "live:s004"},
        {"live:s005", "live:s000"},
        {"live:s005", "live:s002"},
    ]


def test_online_first_update_uses_sealed_sources_to_fill_history(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        contrast_module,
        "resolve_seed",
        _seed_resolver(tmp_path),
    )
    experiment = tmp_path / "experiment"
    for index in range(2):
        _workspace(
            experiment / "submissions",
            f"s{index:03d}",
            f"live {index}\n",
        )

    contrasts = contrast_module.build_online_contrasts(
        seed_set=tmp_path / "seeds",
        task_dir=tmp_path / "task",
        experiment_dir=experiment,
        benchmark=_Benchmark(),  # type: ignore[arg-type]
        provider="codex",
        requested_model="gpt-5.6-luna",
        assignment_id="assignment-1",
        generation_round=1,
    )

    other_sources = []
    for item in contrasts:
        sources = {item.artifact_a_id, item.artifact_b_id}
        assert "live:s001" in sources
        other_sources.append(next(iter(sources - {"live:s001"})))
    assert other_sources == [
        "live:s000",
        "sealed-seed:rep-001",
        "sealed-seed:rep-002",
    ]


def test_blinded_pair_order_is_deterministic(tmp_path: Path) -> None:
    left = contrast_module._Artifact("left", "left text\n")
    right = contrast_module._Artifact("right", "right text\n")
    first = contrast_module._blind_pair(
        assignment_id="assignment-1",
        generation_round=1,
        pair_id="pair_1",
        left=left,
        right=right,
    )
    second = contrast_module._blind_pair(
        assignment_id="assignment-1",
        generation_round=1,
        pair_id="pair_1",
        left=left,
        right=right,
    )

    assert first == second
    assert {first.artifact_a_id, first.artifact_b_id} == {"left", "right"}
