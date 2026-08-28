"""Durable state, manifest, rubric, and event persistence for revisions."""

from __future__ import annotations

import json
import os
from pathlib import Path

from .artifacts import (
    read_json_object,
)
from rubric_gen.artifacts.serialization import write_json_atomic
from .judge import SCORING_IDENTITY_KEYS
from .models import RevisionState
from .rubric_generation import RubricGeneration, RubricPolicy
from .rubric_generation_store import (
    load_rubric_generation,
    persist_rubric_generation,
)


SEED_SCORING_CONTRACT_KEYS = (
    "scoring_implementation_sha256",
    "effective_judge_model",
    "judge_api_base",
    "benchmark",
    "grading_engine",
    "review_mode",
    "max_review_chars",
    "rubric_source",
    "rubric_set_id",
    "rubric_id",
    "structured_rubric_sha256",
    "rendered_rubric_sha256",
    "manifest_sha256",
)

JUDGE_EXECUTION_CONTRACT_KEYS = (
    "scoring_implementation_sha256",
    "effective_judge_model",
    "judge_api_base",
    "benchmark",
    "grading_engine",
    "review_mode",
    "max_review_chars",
)


def extract_scoring_identity(
    payload: dict[str, object],
    *,
    context: str,
) -> dict[str, object]:
    missing = [key for key in SCORING_IDENTITY_KEYS if key not in payload]
    if missing:
        raise RuntimeError(f"{context} lacks scoring identity: {', '.join(missing)}")
    return {key: payload[key] for key in SCORING_IDENTITY_KEYS}


def extract_seed_scoring_contract(
    payload: dict[str, object],
    *,
    context: str,
) -> dict[str, object]:
    """Return the exact current scoring contract for a reusable seed."""

    identity = extract_scoring_identity(payload, context=context)
    return {key: identity[key] for key in SEED_SCORING_CONTRACT_KEYS}


def extract_judge_execution_contract(
    payload: dict[str, object],
    *,
    context: str,
) -> dict[str, object]:
    """Return the exact non-rubric judge execution identity."""

    identity = extract_scoring_identity(payload, context=context)
    return {key: identity[key] for key in JUDGE_EXECUTION_CONTRACT_KEYS}


class RevisionStore:
    """Persist and verify one revision experiment's durable control state."""

    def __init__(
        self,
        experiment_dir: Path,
        *,
        initial_generation: RubricGeneration,
        rubric_policy: RubricPolicy,
        scoring_identity: dict[str, object],
    ) -> None:
        self.experiment_dir = experiment_dir
        self.initial_generation = initial_generation
        self.rubric_policy = rubric_policy
        self.scoring_identity = dict(scoring_identity)

    @property
    def manifest_path(self) -> Path:
        return self.experiment_dir / "manifest.json"

    @property
    def state_path(self) -> Path:
        return self.experiment_dir / "state.json"

    def persist_initial_generation(self) -> None:
        persist_rubric_generation(
            self.experiment_dir,
            self.initial_generation,
            self.rubric_policy,
        )

    def verify_initial_generation(self) -> None:
        persisted = load_rubric_generation(
            self.experiment_dir,
            0,
            expected_policy=self.rubric_policy,
        )
        if persisted != self.initial_generation:
            raise RuntimeError("persisted initial rubric generation changed")

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
        if manifest.get("initial_scoring_identity") != self.scoring_identity:
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
