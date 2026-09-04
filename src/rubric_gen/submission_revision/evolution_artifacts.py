"""Blinded artifact-history contracts for rubric evolution."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass

from rubric_gen.artifacts.hashing import sha256_text


_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}")


def _require_sha256(value: object, field: str) -> str:
    if type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None:
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def single_line(value: object, field: str, maximum: int | None = None) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or (maximum is not None and len(value) > maximum)
        or len(value.splitlines()) != 1
        or any(unicodedata.category(char).startswith("C") for char in value)
    ):
        bound = "" if maximum is None else f" of at most {maximum} characters"
        raise ValueError(f"{field} must be printable single-line text{bound}")
    return value


@dataclass(frozen=True)
class BlindedArtifact:
    """Store one artifact once, with a stable blinded ID and hidden source."""

    artifact_id: str
    source_id: str
    content_sha256: str
    content: str

    def __post_init__(self) -> None:
        if type(self.artifact_id) is not str or re.fullmatch(
            r"artifact_[0-9a-f]{16}", self.artifact_id
        ) is None:
            raise ValueError("blinded artifact ID is invalid")
        single_line(self.source_id, "artifact source ID", 500)
        _require_sha256(self.content_sha256, "artifact content_sha256")
        if type(self.content) is not str or not self.content:
            raise ValueError("artifact content must be nonempty text")
        if sha256_text(self.content) != self.content_sha256:
            raise ValueError("artifact content hash is invalid")

    def model_record(self) -> dict[str, str]:
        return {"artifact_id": self.artifact_id, "content": self.content}

    def artifact_record(self) -> dict[str, str]:
        return {
            "artifact_id": self.artifact_id,
            "source_id": self.source_id,
            "content_sha256": self.content_sha256,
            "content": self.content,
        }


@dataclass(frozen=True)
class ArtifactPair:
    """Reference one matched pair of blinded artifacts."""

    pair_id: str
    artifact_ids: tuple[str, str]

    def __post_init__(self) -> None:
        if type(self.pair_id) is not str or re.fullmatch(
            r"pair_[0-9a-f]{16}", self.pair_id
        ) is None:
            raise ValueError("artifact pair ID is invalid")
        if (
            type(self.artifact_ids) is not tuple
            or len(self.artifact_ids) != 2
            or self.artifact_ids[0] >= self.artifact_ids[1]
            or any(
                type(item) is not str
                or re.fullmatch(r"artifact_[0-9a-f]{16}", item) is None
                for item in self.artifact_ids
            )
        ):
            raise ValueError("artifact pair must contain two ordered artifact IDs")
        expected_id = "pair_" + sha256_text("\0".join(self.artifact_ids))[:16]
        if self.pair_id != expected_id:
            raise ValueError("artifact pair ID does not match its artifacts")

    @classmethod
    def create(cls, left_id: str, right_id: str) -> "ArtifactPair":
        left, right = sorted((left_id, right_id))
        artifact_ids = (left, right)
        return cls(
            pair_id="pair_" + sha256_text("\0".join(artifact_ids))[:16],
            artifact_ids=artifact_ids,
        )

    def as_dict(self) -> dict[str, object]:
        return {"pair_id": self.pair_id, "artifact_ids": list(self.artifact_ids)}


@dataclass(frozen=True)
class RedTeamEvidence:
    """Bind one adversarial artifact to its private execution trace."""

    pair_id: str
    observed_artifact_id: str
    adversarial_artifact_id: str
    trajectory_sha256: str
    trajectory_excerpt_sha256: str
    trajectory_excerpt: str
    trajectory_truncated: bool

    def __post_init__(self) -> None:
        pair = ArtifactPair.create(
            self.observed_artifact_id,
            self.adversarial_artifact_id,
        )
        if self.pair_id != pair.pair_id:
            raise ValueError("red-team evidence does not match its artifact pair")
        if self.observed_artifact_id == self.adversarial_artifact_id:
            raise ValueError("red-team evidence needs two distinct artifacts")
        _require_sha256(self.trajectory_sha256, "trajectory_sha256")
        _require_sha256(
            self.trajectory_excerpt_sha256,
            "trajectory_excerpt_sha256",
        )
        if type(self.trajectory_excerpt) is not str or not self.trajectory_excerpt:
            raise ValueError("red-team trajectory excerpt must be nonempty")
        if sha256_text(self.trajectory_excerpt) != self.trajectory_excerpt_sha256:
            raise ValueError("red-team trajectory excerpt hash is invalid")
        if type(self.trajectory_truncated) is not bool:
            raise ValueError("red-team trajectory truncation state must be boolean")

    def model_record(self, *, include_trace: bool) -> dict[str, object]:
        record: dict[str, object] = {
            "pair_id": self.pair_id,
            "observed_artifact_id": self.observed_artifact_id,
            "adversarial_artifact_id": self.adversarial_artifact_id,
        }
        if include_trace:
            record["trajectory_excerpt"] = self.trajectory_excerpt
            record["trajectory_truncated"] = self.trajectory_truncated
        return record

    def artifact_record(self) -> dict[str, object]:
        return {
            **self.model_record(include_trace=True),
            "trajectory_sha256": self.trajectory_sha256,
            "trajectory_excerpt_sha256": self.trajectory_excerpt_sha256,
        }


@dataclass(frozen=True)
class ArtifactHistory:
    """Store each artifact once and only the matched comparison pairs."""

    artifacts: tuple[BlindedArtifact, ...]
    pairs: tuple[ArtifactPair, ...]
    red_team_evidence: tuple[RedTeamEvidence, ...]

    def __post_init__(self) -> None:
        if (
            type(self.artifacts) is not tuple
            or len(self.artifacts) < 1
            or any(not isinstance(item, BlindedArtifact) for item in self.artifacts)
        ):
            raise ValueError("artifact history needs at least one artifact")
        artifact_ids = tuple(item.artifact_id for item in self.artifacts)
        if artifact_ids != tuple(sorted(artifact_ids)) or len(set(artifact_ids)) != len(
            artifact_ids
        ):
            raise ValueError("artifact history IDs must be unique and ordered")
        artifact_id_set = set(artifact_ids)
        hashes = tuple(item.content_sha256 for item in self.artifacts)
        if len(set(hashes)) != len(hashes):
            raise ValueError("artifact history content must be unique")
        if (
            type(self.pairs) is not tuple
            or any(not isinstance(item, ArtifactPair) for item in self.pairs)
            or tuple(item.artifact_ids for item in self.pairs)
            != tuple(sorted(item.artifact_ids for item in self.pairs))
            or len({item.pair_id for item in self.pairs}) != len(self.pairs)
            or any(
                artifact_id not in artifact_id_set
                for pair in self.pairs
                for artifact_id in pair.artifact_ids
            )
        ):
            raise ValueError("artifact history has invalid matched pairs")
        pair_by_id = {item.pair_id: item for item in self.pairs}
        if (
            type(self.red_team_evidence) is not tuple
            or any(
                not isinstance(item, RedTeamEvidence)
                for item in self.red_team_evidence
            )
            or tuple(item.pair_id for item in self.red_team_evidence)
            != tuple(sorted(item.pair_id for item in self.red_team_evidence))
            or len({item.pair_id for item in self.red_team_evidence})
            != len(self.red_team_evidence)
            or any(
                item.pair_id not in pair_by_id
                or set(pair_by_id[item.pair_id].artifact_ids)
                != {
                    item.observed_artifact_id,
                    item.adversarial_artifact_id,
                }
                for item in self.red_team_evidence
            )
        ):
            raise ValueError("artifact history has invalid red-team evidence")

    def model_record(self) -> dict[str, object]:
        return {
            "artifacts": [item.model_record() for item in self.artifacts],
            "pairs": [item.as_dict() for item in self.pairs],
        }

    def artifact_record(self) -> dict[str, object]:
        return {
            "artifacts": [item.artifact_record() for item in self.artifacts],
            "pairs": [item.as_dict() for item in self.pairs],
            "red_team_evidence": [
                item.artifact_record() for item in self.red_team_evidence
            ],
        }

    @property
    def red_team_pair_ids(self) -> tuple[str, ...]:
        return tuple(item.pair_id for item in self.red_team_evidence)

    def red_team_model_records(
        self,
        pair_ids: tuple[str, ...],
        *,
        include_trace: bool,
    ) -> list[dict[str, object]]:
        pair_id_set = set(pair_ids)
        if len(pair_id_set) != len(pair_ids) or any(
            pair_id not in {pair.pair_id for pair in self.pairs}
            for pair_id in pair_ids
        ):
            raise ValueError("red-team evidence request has invalid pair IDs")
        return [
            item.model_record(include_trace=include_trace)
            for item in self.red_team_evidence
            if item.pair_id in pair_id_set
        ]

    def validate_provenance(self, pair_ids: tuple[str, ...]) -> tuple[str, ...]:
        """Validate cited pair IDs without imposing an evidence threshold."""

        pair_by_id = {item.pair_id: item for item in self.pairs}
        if (
            type(pair_ids) is not tuple
            or len(set(pair_ids)) != len(pair_ids)
            or any(item not in pair_by_id for item in pair_ids)
        ):
            raise ValueError("criterion provenance must cite distinct pairs in history")
        return tuple(item.pair_id for item in self.pairs if item.pair_id in pair_ids)


def validate_artifact_history(history: ArtifactHistory) -> ArtifactHistory:
    if not isinstance(history, ArtifactHistory):
        raise ValueError("elicitation requires an ArtifactHistory")
    return history
