"""Build deterministic blinded artifact histories for criterion elicitation."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.benchmarks import SubmissionBenchmark
from rubric_gen.runtime.agents.models import AgentRunConfig
from rubric_gen.submission_revision.prompts import PromptProfile
from rubric_gen.submission_revision.evolution_artifacts import (
    ArtifactHistory,
    ArtifactPair,
    BlindedArtifact,
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
    seed_generator: AgentRunConfig,
    prompt_profile: PromptProfile | str,
    seed_replicates: int,
) -> tuple[_Artifact, ...]:
    if type(seed_replicates) is not int or seed_replicates < 3:
        raise ValueError("elicitation seed count must be at least three")
    values: list[_Artifact] = []
    for replicate in range(1, seed_replicates + 1):
        seed = resolve_seed(
            seed_set,
            task_dir,
            replicate,
            seed_generator=seed_generator,
            prompt_profile=prompt_profile,
            benchmark=benchmark.benchmark,
        )
        for role, workspace in seed.elicitation_artifacts:
            values.append(_Artifact(
                source_id=f"sealed-seed:rep-{replicate:03d}:{role}",
                text=benchmark.render_user_review(workspace),
            ))
    return tuple(values)


def _artifact_history(
    *,
    blinding_scope: str,
    artifacts: tuple[_Artifact, ...],
) -> ArtifactHistory:
    if type(blinding_scope) is not str or not blinding_scope.strip():
        raise ValueError("elicitation blinding scope must be nonempty")
    unique_by_hash: dict[str, _Artifact] = {}
    for artifact in artifacts:
        unique_by_hash.setdefault(artifact.sha256, artifact)
    blinded = tuple(sorted(
        (
            BlindedArtifact(
                artifact_id="artifact_" + sha256_text(
                    f"{blinding_scope}\0{digest}"
                )[:16],
                source_id=artifact.source_id,
                content_sha256=digest,
                content=artifact.text,
            )
            for digest, artifact in unique_by_hash.items()
        ),
        key=lambda item: item.artifact_id,
    ))
    artifact_ids = tuple(item.artifact_id for item in blinded)
    pairs = tuple(
        ArtifactPair.create(artifact_ids[left], artifact_ids[right])
        for left in range(len(artifact_ids))
        for right in range(left + 1, len(artifact_ids))
    )
    return ArtifactHistory(artifacts=blinded, pairs=pairs)


def build_offline_artifact_history(
    *,
    seed_set: Path,
    task_dir: Path,
    benchmark: SubmissionBenchmark,
    seed_generator: AgentRunConfig,
    prompt_profile: PromptProfile | str,
    seed_replicates: int,
    blinding_scope: str,
) -> ArtifactHistory:
    """Return the complete graph over three sealed pre-treatment artifacts."""

    return _artifact_history(
        blinding_scope=blinding_scope,
        artifacts=_sealed_seed_artifacts(
            seed_set=seed_set,
            task_dir=task_dir,
            benchmark=benchmark,
            seed_generator=seed_generator,
            prompt_profile=prompt_profile,
            seed_replicates=seed_replicates,
        ),
    )


def build_online_artifact_history(
    *,
    seed_set: Path,
    task_dir: Path,
    experiment_dir: Path,
    benchmark: SubmissionBenchmark,
    seed_generator: AgentRunConfig,
    prompt_profile: PromptProfile | str,
    seed_replicates: int,
    blinding_scope: str,
    source_checkpoint: int,
) -> ArtifactHistory:
    """Return all sealed seeds and all live artifacts through one checkpoint."""

    if type(source_checkpoint) is not int or source_checkpoint < 1:
        raise ValueError("source_checkpoint must be a positive integer")
    submissions = experiment_dir / "submissions"
    live: list[_Artifact] = []
    for index in range(source_checkpoint + 1):
        submission_id = f"s{index:03d}"
        workspace = submissions / submission_id / "workspace"
        if workspace.is_symlink() or not workspace.is_dir():
            raise RuntimeError(f"online elicitation source is missing: {submission_id}")
        live.append(_Artifact(
            source_id=f"live:{submission_id}",
            text=benchmark.render_user_review(workspace),
        ))
    seeds = _sealed_seed_artifacts(
        seed_set=seed_set,
        task_dir=task_dir,
        benchmark=benchmark,
        seed_generator=seed_generator,
        prompt_profile=prompt_profile,
        seed_replicates=seed_replicates,
    )
    return _artifact_history(
        blinding_scope=blinding_scope,
        artifacts=(*seeds, *live),
    )


def build_elicitation_artifact_history(
    *,
    online: bool,
    seed_set: Path,
    task_dir: Path,
    experiment_dir: Path,
    benchmark: SubmissionBenchmark,
    seed_generator: AgentRunConfig,
    prompt_profile: PromptProfile | str,
    seed_replicates: int,
    blinding_scope: str,
    source_checkpoint: int | None,
) -> ArtifactHistory:
    """Route one policy to its complete blinded artifact history."""

    if type(online) is not bool:
        raise ValueError("online must be a boolean")
    arguments = {
        "seed_set": seed_set,
        "task_dir": task_dir,
        "benchmark": benchmark,
        "seed_generator": seed_generator,
        "prompt_profile": prompt_profile,
        "seed_replicates": seed_replicates,
        "blinding_scope": blinding_scope,
    }
    if online:
        if source_checkpoint is None:
            raise ValueError("online elicitation requires a source checkpoint")
        return build_online_artifact_history(
            experiment_dir=experiment_dir,
            source_checkpoint=source_checkpoint,
            **arguments,
        )
    if source_checkpoint is not None:
        raise ValueError("pre-treatment elicitation cannot use a live checkpoint")
    return build_offline_artifact_history(**arguments)
