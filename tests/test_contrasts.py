from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from rubric_gen.runtime.agents.models import AgentRunConfig
from rubric_gen.submission_revision import contrasts as contrast_module


class _Benchmark:
    benchmark = "biomnibench-da"

    @staticmethod
    def render_user_review(workspace: Path) -> str:
        return (workspace / "review.txt").read_text(encoding="utf-8")

    @staticmethod
    def render_submission(_workspace: Path) -> str:
        raise AssertionError("elicitation must use complete public review evidence")


def _workspace(root: Path, name: str, text: str) -> Path:
    workspace = root / name / "workspace"
    workspace.mkdir(parents=True)
    (workspace / "artifact.txt").write_text(text, encoding="utf-8")
    (workspace / "review.txt").write_text(
        "public review: " + text,
        encoding="utf-8",
    )
    return workspace


def _seed_resolver(root: Path, *, duplicate_attacks: bool = False):
    seeds = {
        replicate: (
            _workspace(root, f"seed-{replicate}", f"seed {replicate}\n"),
            _workspace(root, f"attack-{replicate}", f"attack {replicate}\n"),
        )
        for replicate in (1, 2, 3)
    }

    def resolve_seed(
        _seed_set: Path,
        _task_dir: Path,
        replicate: int,
        *,
        seed_generator: AgentRunConfig,
        prompt_profile: str,
        benchmark: str,
    ) -> SimpleNamespace:
        assert seed_generator.provider == "codex"
        assert seed_generator.model == "gpt-5.6-luna"
        assert prompt_profile == "base"
        assert benchmark == "biomnibench-da"
        clean, adversarial = seeds[replicate]
        if duplicate_attacks:
            adversarial = clean
        return SimpleNamespace(elicitation_artifacts=(
            ("clean", clean),
            ("adversarial", adversarial),
        ))

    return resolve_seed


def _arguments(tmp_path: Path) -> dict[str, object]:
    return {
        "seed_set": tmp_path / "seeds",
        "task_dir": tmp_path / "task",
        "benchmark": _Benchmark(),
        "seed_generator": AgentRunConfig(
            provider="codex",
            model="gpt-5.6-luna",
        ),
        "prompt_profile": "base",
        "seed_replicates": 3,
        "blinding_scope": "shared-task-rubric",
    }


def test_offline_history_uses_three_sealed_artifacts_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(contrast_module, "resolve_seed", _seed_resolver(tmp_path))

    history = contrast_module.build_offline_artifact_history(
        **_arguments(tmp_path),  # type: ignore[arg-type]
    )

    assert {item.source_id for item in history.artifacts} == {
        *(f"sealed-seed:rep-{index:03d}:clean" for index in (1, 2, 3)),
        *(f"sealed-seed:rep-{index:03d}:adversarial" for index in (1, 2, 3)),
    }
    assert len(history.artifacts) == 6
    assert len(history.pairs) == 15
    assert all("public review:" in item.content for item in history.artifacts)
    assert set(history.model_record()) == {"artifacts", "pairs"}
    assert "source_id" not in str(history.model_record())


def test_offline_history_deduplicates_exact_attempt_copies(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        contrast_module,
        "resolve_seed",
        _seed_resolver(tmp_path, duplicate_attacks=True),
    )

    history = contrast_module.build_offline_artifact_history(
        **_arguments(tmp_path),  # type: ignore[arg-type]
    )

    assert len(history.artifacts) == 3
    assert len(history.pairs) == 3
    assert all(item.source_id.endswith(":clean") for item in history.artifacts)


def test_online_history_includes_every_prior_artifact_and_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(contrast_module, "resolve_seed", _seed_resolver(tmp_path))
    experiment = tmp_path / "experiment"
    for index in range(6):
        _workspace(experiment / "submissions", f"s{index:03d}", f"live {index}\n")

    history = contrast_module.build_online_artifact_history(
        experiment_dir=experiment,
        source_checkpoint=5,
        **_arguments(tmp_path),  # type: ignore[arg-type]
    )

    assert {item.source_id for item in history.artifacts} == {
        *(f"sealed-seed:rep-{index:03d}:clean" for index in (1, 2, 3)),
        *(f"sealed-seed:rep-{index:03d}:adversarial" for index in (1, 2, 3)),
        *(f"live:s{index:03d}" for index in range(6)),
    }
    assert len(history.artifacts) == 12
    assert len(history.pairs) == 66
    assert all("public review:" in item.content for item in history.artifacts)


def test_online_first_update_does_not_repeat_current_as_every_pair_hub(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(contrast_module, "resolve_seed", _seed_resolver(tmp_path))
    experiment = tmp_path / "experiment"
    for index in range(2):
        _workspace(experiment / "submissions", f"s{index:03d}", f"live {index}\n")

    history = contrast_module.build_online_artifact_history(
        experiment_dir=experiment,
        source_checkpoint=1,
        **_arguments(tmp_path),  # type: ignore[arg-type]
    )
    current_id = next(
        item.artifact_id for item in history.artifacts if item.source_id == "live:s001"
    )
    current_pairs = [
        pair for pair in history.pairs if current_id in pair.artifact_ids
    ]

    assert len(history.artifacts) == 8
    assert len(history.pairs) == 28
    assert len(current_pairs) == 7
    assert any(current_id not in pair.artifact_ids for pair in history.pairs)


def test_blinded_artifact_ids_stay_stable_as_online_history_grows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(contrast_module, "resolve_seed", _seed_resolver(tmp_path))
    experiment = tmp_path / "experiment"
    for index in range(3):
        _workspace(experiment / "submissions", f"s{index:03d}", f"live {index}\n")
    arguments = _arguments(tmp_path)
    first = contrast_module.build_online_artifact_history(
        experiment_dir=experiment,
        source_checkpoint=1,
        **arguments,  # type: ignore[arg-type]
    )
    second = contrast_module.build_online_artifact_history(
        experiment_dir=experiment,
        source_checkpoint=2,
        **arguments,  # type: ignore[arg-type]
    )

    first_ids = {item.content_sha256: item.artifact_id for item in first.artifacts}
    second_ids = {item.content_sha256: item.artifact_id for item in second.artifacts}
    assert first_ids == {digest: second_ids[digest] for digest in first_ids}
    assert set(first.pairs) < set(second.pairs)
