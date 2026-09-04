from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from rubric_gen.runtime.agents.models import AgentRunConfig
from rubric_gen.submission_revision import contrasts as contrast_module
from rubric_gen.submission_revision.rubric_generation import RubricPolicy


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


def test_offline_history_uses_three_ordinary_and_one_shared_adversarial_seed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(contrast_module, "resolve_seed", _seed_resolver(tmp_path))

    history = contrast_module.build_offline_artifact_history(
        **_arguments(tmp_path),  # type: ignore[arg-type]
    )

    assert {item.source_id for item in history.artifacts} == {
        *(f"sealed-seed:rep-{index:03d}:clean" for index in (1, 2, 3)),
        "sealed-seed:rep-001:adversarial",
    }
    assert len(history.artifacts) == 4
    assert len(history.pairs) == 3
    adversarial_id = next(
        item.artifact_id for item in history.artifacts
        if item.source_id.endswith(":adversarial")
    )
    assert all(adversarial_id in pair.artifact_ids for pair in history.pairs)
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
    assert len(history.pairs) == 2
    assert all(item.source_id.endswith(":clean") for item in history.artifacts)


def test_online_history_includes_seed_and_adjacent_revision_pairs(
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
        "sealed-seed:rep-001:adversarial",
        *(f"live:s{index:03d}" for index in range(6)),
    }
    assert len(history.artifacts) == 10
    assert len(history.pairs) == 9
    assert all("public review:" in item.content for item in history.artifacts)


def test_online_first_update_pairs_only_adjacent_revisions(
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

    assert len(history.artifacts) == 6
    assert len(history.pairs) == 4
    assert len(current_pairs) == 1
    assert any(current_id not in pair.artifact_ids for pair in history.pairs)


def test_online_history_replaces_the_old_initial_current_anchor(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(contrast_module, "resolve_seed", _seed_resolver(tmp_path))
    experiment = tmp_path / "experiment"
    for index in range(4):
        _workspace(experiment / "submissions", f"s{index:03d}", f"live {index}\n")

    second = contrast_module.build_online_artifact_history(
        experiment_dir=experiment,
        source_checkpoint=2,
        **_arguments(tmp_path),  # type: ignore[arg-type]
    )
    third = contrast_module.build_online_artifact_history(
        experiment_dir=experiment,
        source_checkpoint=3,
        **_arguments(tmp_path),  # type: ignore[arg-type]
    )
    second_ids = {
        item.source_id: item.artifact_id for item in second.artifacts
    }
    third_ids = {
        item.source_id: item.artifact_id for item in third.artifacts
    }
    old_anchor = contrast_module.ArtifactPair.create(
        second_ids["live:s000"],
        second_ids["live:s002"],
    )
    new_anchor = contrast_module.ArtifactPair.create(
        third_ids["live:s000"],
        third_ids["live:s003"],
    )
    latest_adjacent = contrast_module.ArtifactPair.create(
        third_ids["live:s002"],
        third_ids["live:s003"],
    )

    assert old_anchor in second.pairs
    assert old_anchor not in third.pairs
    assert new_anchor in third.pairs
    assert latest_adjacent in third.pairs


def test_red_team_history_adds_one_sidecar_pair_and_private_trace(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(contrast_module, "resolve_seed", _seed_resolver(tmp_path))
    experiment = tmp_path / "experiment"
    for index in range(2):
        _workspace(experiment / "submissions", f"s{index:03d}", f"live {index}\n")
    sidecar = _workspace(tmp_path, "sidecar-1", "online attack 1\n")
    (sidecar.parent / "trajectory.stream.jsonl").write_text(
        '{"type":"item.completed","item":{"type":"reasoning","text":"probe"}}\n',
        encoding="utf-8",
    )

    def load_sidecar(*_args, **kwargs):
        assert kwargs["expected_generator"] == {"model": "red-team"}
        return SimpleNamespace(included=True, root=sidecar.parent)

    monkeypatch.setattr(
        contrast_module,
        "load_red_team_artifact",
        load_sidecar,
    )
    history = contrast_module.build_online_artifact_history(
        experiment_dir=experiment,
        source_checkpoint=1,
        red_team_policy=RubricPolicy.RED_TEAM_ARTIFACT,
        red_team_generator_identity={"model": "red-team"},
        **_arguments(tmp_path),  # type: ignore[arg-type]
    )

    assert len(history.artifacts) == 7
    assert len(history.pairs) == 5
    ids_by_source = {
        item.source_id: item.artifact_id for item in history.artifacts
    }
    sidecar_pair = contrast_module.ArtifactPair.create(
        ids_by_source["live:s001"],
        ids_by_source["red-team:s001"],
    )
    assert sidecar_pair in history.pairs
    assert len(history.red_team_evidence) == 1
    evidence = history.red_team_evidence[0]
    assert evidence.pair_id == sidecar_pair.pair_id
    assert evidence.observed_artifact_id == ids_by_source["live:s001"]
    assert evidence.adversarial_artifact_id == ids_by_source["red-team:s001"]
    assert '"text":"probe"' in evidence.trajectory_excerpt
    assert "red-team" not in str(history.model_record())
    assert "trajectory_excerpt" in str(history.artifact_record())


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
