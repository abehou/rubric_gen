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
    RedTeamEvidence,
)
from rubric_gen.submission_revision.red_team import (
    load_red_team_artifact,
)
from rubric_gen.submission_revision.rubric_generation import RubricPolicy
from rubric_gen.submission_revision.seeds import resolve_seed


RED_TEAM_TRACE_EXCERPT_MAX_BYTES = 32 * 1024
ELICITATION_SEED_REPLICATES = 3
_TRACE_OMISSION = "\n<trajectory_middle_omitted />\n"


@dataclass(frozen=True)
class _Artifact:
    source_id: str
    text: str
    pair_keys: tuple[str, ...] = ()

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
    if (
        type(seed_replicates) is not int
        or seed_replicates != ELICITATION_SEED_REPLICATES
    ):
        raise ValueError("elicitation requires exactly three seed replicates")
    ordinary: list[_Artifact] = []
    adversarial: list[_Artifact] = []
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
            if role not in {"clean", "adversarial"}:
                raise RuntimeError("seed artifact has an invalid elicitation role")
            artifact = _Artifact(
                source_id=f"sealed-seed:rep-{replicate:03d}:{role}",
                text=benchmark.render_user_review(workspace),
            )
            (ordinary if role == "clean" else adversarial).append(artifact)
    if len(ordinary) != seed_replicates:
        raise RuntimeError("each seed replicate must supply one ordinary artifact")
    pair_keys = tuple(
        f"seed-bank-{index:03d}" for index in range(1, len(ordinary) + 1)
    )
    matched_ordinary = tuple(
        _Artifact(
            source_id=artifact.source_id,
            text=artifact.text,
            pair_keys=(pair_key,),
        )
        for artifact, pair_key in zip(ordinary, pair_keys, strict=True)
    )
    if not adversarial:
        return matched_ordinary
    shared_adversarial = adversarial[0]
    return (*matched_ordinary, _Artifact(
        source_id=shared_adversarial.source_id,
        text=shared_adversarial.text,
        pair_keys=pair_keys,
    ))


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
    artifact_id_by_hash = {
        item.content_sha256: item.artifact_id for item in blinded
    }
    pair_members: dict[str, list[str]] = {}
    for artifact in artifacts:
        artifact_id = artifact_id_by_hash[artifact.sha256]
        for pair_key in artifact.pair_keys:
            members = pair_members.setdefault(pair_key, [])
            if artifact_id not in members:
                members.append(artifact_id)
    pairs: list[ArtifactPair] = []
    for pair_key, members in pair_members.items():
        if len(members) == 1:
            continue
        if len(members) != 2:
            raise RuntimeError(f"matched pair has {len(members)} artifacts: {pair_key}")
        pairs.append(ArtifactPair.create(*members))
    unique_pairs = {pair.pair_id: pair for pair in pairs}
    return ArtifactHistory(
        artifacts=blinded,
        pairs=tuple(sorted(unique_pairs.values(), key=lambda item: item.artifact_ids)),
        red_team_evidence=(),
    )


def _trace_excerpt(path: Path) -> tuple[str, bool]:
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("red-team trajectory is missing")
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise RuntimeError("red-team trajectory is invalid UTF-8") from exc
    if not text:
        raise RuntimeError("red-team trajectory is empty")
    raw = text.encode("utf-8")
    if len(raw) <= RED_TEAM_TRACE_EXCERPT_MAX_BYTES:
        return text, False
    marker = _TRACE_OMISSION.encode("utf-8")
    available = RED_TEAM_TRACE_EXCERPT_MAX_BYTES - len(marker)
    prefix = raw[: available // 2].decode("utf-8", errors="ignore")
    suffix = raw[-(available - available // 2):].decode(
        "utf-8",
        errors="ignore",
    )
    excerpt = prefix + _TRACE_OMISSION + suffix
    if len(excerpt.encode("utf-8")) > RED_TEAM_TRACE_EXCERPT_MAX_BYTES:
        raise AssertionError("red-team trajectory excerpt exceeds its byte limit")
    return excerpt, True


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
    """Return matched sealed pre-treatment artifact pairs."""

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
    red_team_policy: RubricPolicy | None = None,
    red_team_generator_identity: dict[str, object] | None = None,
) -> ArtifactHistory:
    """Return matched seed, revision, and optional sidecar pairs."""

    if type(source_checkpoint) is not int or source_checkpoint < 1:
        raise ValueError("source_checkpoint must be a positive integer")
    submissions = experiment_dir / "submissions"
    if red_team_policy not in {
        None,
        RubricPolicy.RED_TEAM_ARTIFACT,
        RubricPolicy.RED_TEAM_TRACE,
    }:
        raise ValueError("online history has an invalid red-team policy")
    include_red_team = red_team_policy is not None
    if include_red_team != (red_team_generator_identity is not None):
        raise ValueError(
            "red-team identity is required exactly when sidecars are included"
        )
    live: list[_Artifact] = []
    red_team_sources: list[tuple[_Artifact, _Artifact, Path]] = []
    for index in range(source_checkpoint + 1):
        submission_id = f"s{index:03d}"
        workspace = submissions / submission_id / "workspace"
        if workspace.is_symlink() or not workspace.is_dir():
            raise RuntimeError(f"online elicitation source is missing: {submission_id}")
        pair_keys: list[str] = []
        if index > 0:
            pair_keys.append(f"revision-{index - 1:03d}-{index:03d}")
        if index < source_checkpoint:
            pair_keys.append(f"revision-{index:03d}-{index + 1:03d}")
        if (
            source_checkpoint > 1
            and index in {0, source_checkpoint}
        ):
            pair_keys.append(f"initial-current-{source_checkpoint:03d}")
        if include_red_team and index >= 1:
            pair_keys.append(f"red-team-{index:03d}")
        observed = _Artifact(
            source_id=f"live:{submission_id}",
            text=benchmark.render_user_review(workspace),
            pair_keys=tuple(pair_keys),
        )
        live.append(observed)
        if include_red_team and index >= 1:
            sidecar = load_red_team_artifact(
                experiment_dir,
                index,
                expected_generator=red_team_generator_identity,
                expected_source_artifact_sha256=sha256_text(
                    benchmark.render_user_review(workspace)
                ),
            )
            if sidecar.included:
                adversarial = _Artifact(
                    source_id=f"red-team:{submission_id}",
                    text=benchmark.render_user_review(sidecar.root / "workspace"),
                    pair_keys=(f"red-team-{index:03d}",),
                )
                live.append(adversarial)
                red_team_sources.append((
                    observed,
                    adversarial,
                    sidecar.root / "trajectory.stream.jsonl",
                ))
    seeds = _sealed_seed_artifacts(
        seed_set=seed_set,
        task_dir=task_dir,
        benchmark=benchmark,
        seed_generator=seed_generator,
        prompt_profile=prompt_profile,
        seed_replicates=seed_replicates,
    )
    history = _artifact_history(
        blinding_scope=blinding_scope,
        artifacts=(*seeds, *live),
    )
    artifact_id_by_hash = {
        item.content_sha256: item.artifact_id for item in history.artifacts
    }
    pair_ids = {item.pair_id for item in history.pairs}
    evidence: list[RedTeamEvidence] = []
    for observed, adversarial, trajectory_path in red_team_sources:
        if observed.sha256 == adversarial.sha256:
            continue
        pair = ArtifactPair.create(
            artifact_id_by_hash[observed.sha256],
            artifact_id_by_hash[adversarial.sha256],
        )
        if pair.pair_id not in pair_ids:
            raise RuntimeError("red-team evidence has no matched artifact pair")
        full_trajectory = trajectory_path.read_text(encoding="utf-8")
        excerpt, truncated = _trace_excerpt(trajectory_path)
        evidence.append(RedTeamEvidence(
            pair_id=pair.pair_id,
            observed_artifact_id=artifact_id_by_hash[observed.sha256],
            adversarial_artifact_id=artifact_id_by_hash[adversarial.sha256],
            trajectory_sha256=sha256_text(full_trajectory),
            trajectory_excerpt_sha256=sha256_text(excerpt),
            trajectory_excerpt=excerpt,
            trajectory_truncated=truncated,
        ))
    return ArtifactHistory(
        artifacts=history.artifacts,
        pairs=history.pairs,
        red_team_evidence=tuple(sorted(evidence, key=lambda item: item.pair_id)),
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
    red_team_policy: RubricPolicy | None = None,
    red_team_generator_identity: dict[str, object] | None = None,
) -> ArtifactHistory:
    """Route one policy to its matched blinded artifact history."""

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
            red_team_policy=red_team_policy,
            red_team_generator_identity=red_team_generator_identity,
            **arguments,
        )
    if red_team_policy is not None or red_team_generator_identity is not None:
        raise ValueError("offline artifact history cannot include online sidecars")
    if source_checkpoint is not None:
        raise ValueError("pre-treatment elicitation cannot use a live checkpoint")
    return build_offline_artifact_history(**arguments)
