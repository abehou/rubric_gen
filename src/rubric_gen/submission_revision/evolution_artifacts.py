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


def single_line(value: object, field: str, maximum: int) -> str:
    if (
        type(value) is not str
        or not value
        or value != value.strip()
        or len(value) > maximum
        or len(value.splitlines()) != 1
        or any(unicodedata.category(char).startswith("C") for char in value)
    ):
        raise ValueError(
            f"{field} must be printable single-line text of at most {maximum} characters"
        )
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
    """Reference one unordered pair of blinded artifacts."""

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
class ArtifactHistory:
    """Store each artifact once and the complete unordered pair graph."""

    artifacts: tuple[BlindedArtifact, ...]
    pairs: tuple[ArtifactPair, ...]

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
        hashes = tuple(item.content_sha256 for item in self.artifacts)
        if len(set(hashes)) != len(hashes):
            raise ValueError("artifact history content must be unique")
        expected_pairs = tuple(
            ArtifactPair.create(artifact_ids[left], artifact_ids[right])
            for left in range(len(artifact_ids))
            for right in range(left + 1, len(artifact_ids))
        )
        if self.pairs != expected_pairs:
            raise ValueError("artifact history must contain the complete pair graph")

    def model_record(self) -> dict[str, object]:
        return {
            "artifacts": [item.model_record() for item in self.artifacts],
            "pairs": [item.as_dict() for item in self.pairs],
        }

    def artifact_record(self) -> dict[str, object]:
        return {
            "artifacts": [item.artifact_record() for item in self.artifacts],
            "pairs": [item.as_dict() for item in self.pairs],
        }

    def validate_support(self, pair_ids: tuple[str, ...]) -> tuple[str, ...]:
        """Reject support that repeats one artifact as a shared hub."""

        pair_by_id = {item.pair_id: item for item in self.pairs}
        if (
            type(pair_ids) is not tuple
            or len(pair_ids) < 2
            or len(set(pair_ids)) != len(pair_ids)
            or any(item not in pair_by_id for item in pair_ids)
        ):
            raise ValueError("criterion needs distinct pairs from this history")
        ordered = tuple(item.pair_id for item in self.pairs if item.pair_id in pair_ids)
        supported = [set(pair_by_id[item].artifact_ids) for item in ordered]
        if len(set().union(*supported)) < 3 or set.intersection(*supported):
            raise ValueError(
                "criterion support must span three artifacts without one shared hub"
            )
        return ordered


def validate_artifact_history(history: ArtifactHistory) -> ArtifactHistory:
    if not isinstance(history, ArtifactHistory):
        raise ValueError("elicitation requires an ArtifactHistory")
    return history
