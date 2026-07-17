"""Durable state, manifest, rubric, and event persistence for revisions."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .artifacts import (
    make_read_only,
    read_json_object,
    sha256_file,
    write_json_atomic,
)
from .judge import SCORING_IDENTITY_KEYS
from .models import RevisionState


def extract_scoring_identity(
    payload: dict[str, object],
    *,
    context: str,
) -> dict[str, object]:
    missing = [key for key in SCORING_IDENTITY_KEYS if key not in payload]
    if missing:
        raise RuntimeError(f"{context} lacks scoring identity: {', '.join(missing)}")
    return {key: payload[key] for key in SCORING_IDENTITY_KEYS}


class RevisionStore:
    """Persist and verify one revision experiment's durable control state."""

    def __init__(
        self,
        experiment_dir: Path,
        *,
        rubric_text: str,
        rubric_sha256: str,
        scoring_identity: dict[str, object],
    ) -> None:
        self.experiment_dir = experiment_dir
        self.rubric_text = rubric_text
        self.rubric_sha256 = rubric_sha256
        self.scoring_identity = dict(scoring_identity)

    @property
    def manifest_path(self) -> Path:
        return self.experiment_dir / "manifest.json"

    @property
    def state_path(self) -> Path:
        return self.experiment_dir / "state.json"

    def persist_rubric(self) -> None:
        rubric_path = self.experiment_dir / "rubric" / "r0000.txt"
        if rubric_path.is_file():
            if sha256_file(rubric_path) != self.rubric_sha256:
                raise RuntimeError("persisted optimizer rubric changed")
            return
        if os.path.lexists(rubric_path):
            raise RuntimeError("optimizer rubric path is not a regular file")
        rubric_path.parent.mkdir()
        rubric_path.write_text(self.rubric_text)
        make_read_only(rubric_path)

    def verify_frozen_rubric(self) -> None:
        rubric_path = self.experiment_dir / "rubric" / "r0000.txt"
        if rubric_path.is_symlink() or not rubric_path.is_file():
            raise RuntimeError("persisted optimizer rubric is missing")
        if rubric_path.read_text(encoding="utf-8") != self.rubric_text:
            raise RuntimeError("persisted optimizer rubric changed")

    def write_state(self, state: RevisionState) -> None:
        write_json_atomic(self.state_path, state.as_json())

    def read_state(self) -> RevisionState:
        return RevisionState.from_json(
            read_json_object(self.state_path, "revision state")
        )

    def update_manifest(self, updates: dict[str, object]) -> None:
        manifest = read_json_object(self.manifest_path, "revision manifest")
        manifest.update(updates)
        write_json_atomic(self.manifest_path, manifest)

    def record_session_id(self, session_id: str) -> None:
        if type(session_id) is not str or not session_id.strip():
            raise RuntimeError("solver did not return a persistent session ID")
        manifest = read_json_object(self.manifest_path, "revision manifest")
        previous = manifest.get("session_id")
        if previous not in {None, session_id}:
            raise RuntimeError("solver changed provider session ID")
        self.update_manifest({"session_id": session_id})

    def record_effective_solver_model(
        self,
        state: RevisionState,
        model: str,
    ) -> None:
        if type(model) is not str or not model.strip():
            raise RuntimeError("solver did not report an effective model")
        if state.effective_solver_model not in {None, model}:
            raise RuntimeError("solver changed model during the revision loop")
        state.effective_solver_model = model
        self.update_manifest({"effective_solver_model": model})
        self.write_state(state)

    def verify_scoring_identity(self, validation_path: Path) -> None:
        validation = read_json_object(
            validation_path, "optimizer score validation"
        )
        identity = extract_scoring_identity(
            validation,
            context="optimizer score validation",
        )
        manifest = read_json_object(self.manifest_path, "revision manifest")
        if manifest.get("scoring_identity") != self.scoring_identity:
            raise RuntimeError("optimizer scoring identity changed in the manifest")
        if identity != self.scoring_identity:
            raise RuntimeError("optimizer scoring identity changed during revision")

    def append_event(self, payload: dict[str, object]) -> None:
        events = self.experiment_dir / "events.jsonl"
        with events.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(payload, sort_keys=True, separators=(",", ":")))
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
