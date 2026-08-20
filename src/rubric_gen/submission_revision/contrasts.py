"""Build deterministic blinded contrasts for rubric criterion elicitation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.benchmarks import SubmissionBenchmark
from rubric_gen.submission_revision.evolution import (
    ArtifactContrast,
    validate_contrast_set,
)
from rubric_gen.submission_revision.seeds import resolve_seed


@dataclass(frozen=True)
class _Artifact:
    source_id: str
    text: str

    @property
    def sha256(self) -> str:
        return sha256_text(self.text)


def _sealed_seed_artifacts(
    *,
    seed_set: Path,
    task_dir: Path,
    benchmark: SubmissionBenchmark,
    provider: str,
    requested_model: str,
) -> tuple[_Artifact, _Artifact, _Artifact]:
    values: list[_Artifact] = []
    for replicate in (1, 2, 3):
        seed = resolve_seed(
            seed_set,
            task_dir,
            replicate,
            provider=provider,
            requested_model=requested_model,
        )
        values.append(_Artifact(
            source_id=f"sealed-seed:rep-{replicate:03d}",
            text=benchmark.render_submission(seed.submission_dir / "workspace"),
        ))
    if len({value.sha256 for value in values}) != 3:
        raise RuntimeError(
            "offline elicitation needs three distinct sealed seed artifacts"
        )
    return values[0], values[1], values[2]


def _blind_pair(
    *,
    assignment_id: str,
    generation_round: int,
    pair_id: str,
    left: _Artifact,
    right: _Artifact,
) -> ArtifactContrast:
    material = (
        f"{assignment_id}\n{generation_round}\n{pair_id}\n"
        f"{left.source_id}\n{left.sha256}\n{right.source_id}\n{right.sha256}\n"
    )
    if int(sha256_text(material), 16) % 2:
        left, right = right, left
    return ArtifactContrast(
        pair_id=pair_id,
        artifact_a_id=left.source_id,
        artifact_a_sha256=left.sha256,
        artifact_a=left.text,
        artifact_b_id=right.source_id,
        artifact_b_sha256=right.sha256,
        artifact_b=right.text,
    )


def build_offline_contrasts(
    *,
    seed_set: Path,
    task_dir: Path,
    benchmark: SubmissionBenchmark,
    provider: str,
    requested_model: str,
    assignment_id: str,
    generation_round: int,
) -> tuple[ArtifactContrast, ...]:
    """Return all three pairs from three sealed pre-treatment artifacts."""

    if type(generation_round) is not int or generation_round < 1:
        raise ValueError("generation_round must be a positive integer")
    first, second, third = _sealed_seed_artifacts(
        seed_set=seed_set,
        task_dir=task_dir,
        benchmark=benchmark,
        provider=provider,
        requested_model=requested_model,
    )
    pairs = ((first, second), (first, third), (second, third))
    return validate_contrast_set(tuple(
        _blind_pair(
            assignment_id=assignment_id,
            generation_round=generation_round,
            pair_id=f"pair_{index}",
            left=left,
            right=right,
        )
        for index, (left, right) in enumerate(pairs, start=1)
    ))


def build_online_contrasts(
    *,
    seed_set: Path,
    task_dir: Path,
    experiment_dir: Path,
    benchmark: SubmissionBenchmark,
    provider: str,
    requested_model: str,
    assignment_id: str,
    generation_round: int,
) -> tuple[ArtifactContrast, ...]:
    """Compare the current artifact with three bounded historical anchors."""

    if type(generation_round) is not int or generation_round < 1:
        raise ValueError("generation_round must be a positive integer")
    submissions = experiment_dir / "submissions"

    def live(index: int) -> _Artifact:
        submission_id = f"s{index:03d}"
        workspace = submissions / submission_id / "workspace"
        if workspace.is_symlink() or not workspace.is_dir():
            raise RuntimeError(
                f"online elicitation source is missing: {submission_id}"
            )
        return _Artifact(
            source_id=f"live:{submission_id}",
            text=benchmark.render_submission(workspace),
        )

    current = live(generation_round)
    preferred_indices = (
        generation_round - 1,
        0,
        generation_round // 2,
    )
    candidates: list[_Artifact] = [live(index) for index in preferred_indices]
    candidates.extend(
        live(index) for index in range(generation_round) if index not in preferred_indices
    )
    candidates.extend(_sealed_seed_artifacts(
        seed_set=seed_set,
        task_dir=task_dir,
        benchmark=benchmark,
        provider=provider,
        requested_model=requested_model,
    ))
    anchors: list[_Artifact] = []
    used_hashes = {current.sha256}
    for candidate in candidates:
        if candidate.sha256 in used_hashes:
            continue
        anchors.append(candidate)
        used_hashes.add(candidate.sha256)
        if len(anchors) == 3:
            break
    if len(anchors) != 3:
        raise RuntimeError(
            "online elicitation cannot build three distinct historical contrasts"
        )
    return validate_contrast_set(tuple(
        _blind_pair(
            assignment_id=assignment_id,
            generation_round=generation_round,
            pair_id=f"pair_{index}",
            left=current,
            right=anchor,
        )
        for index, anchor in enumerate(anchors, start=1)
    ))


def build_elicitation_contrasts(
    *,
    online: bool,
    seed_set: Path,
    task_dir: Path,
    experiment_dir: Path,
    benchmark: SubmissionBenchmark,
    provider: str,
    requested_model: str,
    assignment_id: str,
    generation_round: int,
) -> tuple[ArtifactContrast, ...]:
    """Route one policy to its exact three-pair contrast rule."""

    if type(online) is not bool:
        raise ValueError("online must be a boolean")
    arguments = {
        "seed_set": seed_set,
        "task_dir": task_dir,
        "benchmark": benchmark,
        "provider": provider,
        "requested_model": requested_model,
        "assignment_id": assignment_id,
        "generation_round": generation_round,
    }
    if online:
        return build_online_contrasts(
            experiment_dir=experiment_dir,
            **arguments,
        )
    return build_offline_contrasts(**arguments)
