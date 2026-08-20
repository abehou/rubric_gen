"""Artifact-backed reuse for identical in-loop judge requests."""

from __future__ import annotations

import fcntl
import json
import math
import os
import re
import shutil
import stat
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from numbers import Real

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.artifacts import (
    make_read_only,
    read_json_object,
    sha256_file,
)
from rubric_gen.submission_revision.judge import (
    SCORING_IDENTITY_KEYS,
    JudgeArtifacts,
)


_SHA256 = re.compile(r"[0-9a-f]{64}\Z")
_CANONICAL_FILES = (
    "score_validation.json",
    "evaluation.json",
    "reward.json",
    "usage.json",
    "judge_input_trace.md",
    "judge_input_answer.txt",
)
_REQUEST_KEYS = {
    "kind",
    "task_id",
    "replicate",
    "rubric_sha256",
    "review_text_sha256",
    "answer_text_sha256",
    "scoring_identity",
}
_RECORD_KEYS = {
    "kind",
    "request_sha256",
    "request",
    "producer",
    "artifacts",
}
_PRODUCER_KEYS = {
    "assignment_id",
    "condition_id",
    "replicate",
    "submission_id",
    "rubric_sha256",
    "judge_attempt_id",
}
_ALIAS_KEYS = {
    "kind",
    "assignment_id",
    "replicate",
    "submission_id",
    "rubric_sha256",
    "request_sha256",
    "canonical_entry",
    "canonical_record_sha256",
    "score_validation_sha256",
    "evaluation_sha256",
}


@dataclass(frozen=True)
class ReusedJudgment:
    """Return one canonical judgment and its content identity."""

    artifacts: JudgeArtifacts
    request_sha256: str
    canonical_entry: str
    canonical_record_sha256: str


@dataclass(frozen=True)
class ReusedSimulatorGeneration:
    """Return one canonical simulated-user result and its identity."""

    semantic_generation: dict[str, object]
    request_sha256: str
    canonical_entry: str
    canonical_record_sha256: str


def exact_judgment_request(
    *,
    task_id: str,
    replicate: int,
    rubric_sha256: str,
    review_text: str,
    answer_text: str,
    scoring_identity: Mapping[str, object],
) -> dict[str, object]:
    """Build the condition-blind identity of one semantic judge request."""

    if type(task_id) is not str or not task_id or Path(task_id).name != task_id:
        raise ValueError("exact judgment request has an invalid task ID")
    if type(replicate) is not int or replicate < 1:
        raise ValueError("exact judgment request has an invalid replicate")
    if type(rubric_sha256) is not str or _SHA256.fullmatch(rubric_sha256) is None:
        raise ValueError("exact judgment request has an invalid rubric hash")
    if type(review_text) is not str or type(answer_text) is not str:
        raise ValueError("exact judgment request inputs must be text")
    if set(scoring_identity) != set(SCORING_IDENTITY_KEYS):
        raise ValueError("exact judgment request has an incomplete scoring identity")
    if scoring_identity["rendered_rubric_sha256"] != rubric_sha256:
        raise ValueError("exact judgment request scoring identity has another rubric")
    return {
        "kind": "exact-semantic-judge-request",
        "task_id": task_id,
        "replicate": replicate,
        "rubric_sha256": rubric_sha256,
        "review_text_sha256": sha256_text(review_text),
        "answer_text_sha256": sha256_text(answer_text),
        "scoring_identity": dict(scoring_identity),
    }


def exact_simulator_request(
    *,
    experiment_id: str,
    task_id: str,
    replicate: int,
    instruction: str,
    bank_sha256: str,
    current_submission: str,
    simulator_identity: Mapping[str, object],
) -> dict[str, object]:
    """Build the condition-blind identity of one simulated-user pipeline."""

    if any(type(value) is not str or not value for value in (experiment_id, task_id)):
        raise ValueError("exact simulator request has an invalid study identity")
    if type(replicate) is not int or replicate < 1:
        raise ValueError("exact simulator request has an invalid replicate")
    if type(bank_sha256) is not str or _SHA256.fullmatch(bank_sha256) is None:
        raise ValueError("exact simulator request has an invalid bank hash")
    if type(instruction) is not str or type(current_submission) is not str:
        raise ValueError("exact simulator request inputs must be text")
    if not isinstance(simulator_identity, Mapping) or not simulator_identity:
        raise ValueError("exact simulator request has no simulator identity")
    return {
        "kind": "exact-simulated-user-request",
        "experiment_id": experiment_id,
        "task_id": task_id,
        "replicate": replicate,
        "instruction_sha256": sha256_text(instruction),
        "bank_sha256": bank_sha256,
        "current_submission_sha256": sha256_text(current_submission),
        "simulator": dict(simulator_identity),
    }


class ExactJudgmentReuseStore:
    """Publish one canonical artifact set for each exact request identity."""

    def __init__(self, root: Path) -> None:
        self.root = Path(os.path.abspath(root.expanduser()))
        _reject_symlink_components(self.root)
        if os.path.lexists(self.root) and (
            self.root.is_symlink() or not self.root.is_dir()
        ):
            raise RuntimeError("shared judgment reuse root is invalid")
        self.entries = self.root / "entries"
        self.locks = self.root / "locks"

    def resolve(
        self,
        *,
        request: dict[str, object],
        producer: dict[str, object],
        generate: Callable[[], JudgeArtifacts],
    ) -> ReusedJudgment:
        """Return a validated canonical result, or publish exactly one result."""

        request_text = self._canonical_request_text(request)
        request_sha256 = sha256_text(request_text)
        _reject_symlink_components(self.root)
        self.entries.mkdir(parents=True, exist_ok=True)
        self.locks.mkdir(parents=True, exist_ok=True)
        _require_directory(self.root, "shared judgment reuse root")
        _require_directory(self.entries, "shared judgment entry root")
        _require_directory(self.locks, "shared judgment lock root")
        with self._request_lock(request_sha256):
            destination = self.entries / request_sha256
            if not os.path.lexists(destination):
                source = generate()
                self._publish(
                    destination=destination,
                    request=request,
                    request_sha256=request_sha256,
                    producer=producer,
                    source=source,
                )
            return self._load(destination, request)

    def load(
        self,
        *,
        request_sha256: str,
        expected_request: dict[str, object],
    ) -> ReusedJudgment:
        """Load one existing canonical result without provider dispatch."""

        if _SHA256.fullmatch(request_sha256) is None:
            raise RuntimeError("shared judgment request hash is invalid")
        expected_sha256 = self.request_sha256(expected_request)
        if request_sha256 != expected_sha256:
            raise RuntimeError("shared judgment alias names another request")
        _reject_symlink_components(self.root)
        _require_directory(self.entries, "shared judgment entry root")
        destination = self.entries / request_sha256
        result = self._load(destination, expected_request)
        if result.request_sha256 != request_sha256:
            raise RuntimeError("shared judgment entry name differs from its request")
        return result

    def persist_alias(
        self,
        *,
        experiment_dir: Path,
        assignment_id: str,
        replicate: int,
        submission_id: str,
        rubric_sha256: str,
        reused: ReusedJudgment,
    ) -> Path:
        """Persist and validate one assignment-local canonical-artifact alias."""

        alias = {
            "kind": "exact-semantic-judgment-alias",
            "assignment_id": assignment_id,
            "replicate": replicate,
            "submission_id": submission_id,
            "rubric_sha256": rubric_sha256,
            "request_sha256": reused.request_sha256,
            "canonical_entry": reused.canonical_entry,
            "canonical_record_sha256": reused.canonical_record_sha256,
            "score_validation_sha256": sha256_file(
                reused.artifacts.score_validation_path
            ),
            "evaluation_sha256": sha256_file(reused.artifacts.evaluation_path),
        }
        path = experiment_dir / "judgment-aliases" / submission_id / (
            reused.request_sha256 + ".json"
        )
        _reject_symlink_components(experiment_dir)
        _reject_symlink_components(path.parent)
        if path.is_symlink():
            raise RuntimeError("judgment alias is a symbolic link")
        if path.is_file():
            if read_json_object(path, "judgment alias") != alias:
                raise RuntimeError("stored judgment alias changed")
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        _reject_symlink_components(path.parent)
        _require_directory(path.parent, "judgment alias directory")
        write_json_atomic(path, alias)
        make_read_only(path)
        return path

    def validate_alias(
        self,
        path: Path,
        *,
        assignment_id: str,
        replicate: int,
        submission_id: str,
        rubric_sha256: str,
        expected_request: dict[str, object],
    ) -> ReusedJudgment:
        """Validate an alias and return its canonical artifact paths."""

        _reject_symlink_components(path)
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("judgment alias is not a regular file")
        alias = read_json_object(path, "judgment alias")
        if not isinstance(alias, dict) or set(alias) != _ALIAS_KEYS:
            raise RuntimeError("judgment alias has invalid fields")
        if (
            alias.get("kind") != "exact-semantic-judgment-alias"
            or alias.get("assignment_id") != assignment_id
            or alias.get("replicate") != replicate
            or alias.get("submission_id") != submission_id
            or alias.get("rubric_sha256") != rubric_sha256
            or type(alias.get("request_sha256")) is not str
            or _SHA256.fullmatch(alias["request_sha256"]) is None
        ):
            raise RuntimeError("judgment alias has the wrong identity")
        reused = self.load(
            request_sha256=alias["request_sha256"],
            expected_request=expected_request,
        )
        if (
            alias.get("canonical_entry") != reused.canonical_entry
            or alias.get("canonical_record_sha256")
            != reused.canonical_record_sha256
            or alias.get("score_validation_sha256")
            != sha256_file(reused.artifacts.score_validation_path)
            or alias.get("evaluation_sha256")
            != sha256_file(reused.artifacts.evaluation_path)
        ):
            raise RuntimeError("judgment alias differs from its canonical artifacts")
        return reused

    @staticmethod
    def _canonical_request_text(request: object) -> str:
        if not isinstance(request, dict) or set(request) != _REQUEST_KEYS:
            raise ValueError("exact judgment request has invalid fields")
        return json.dumps(
            request,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"

    @classmethod
    def request_sha256(cls, request: dict[str, object]) -> str:
        """Return the canonical exact-request hash."""

        return sha256_text(cls._canonical_request_text(request))

    def _publish(
        self,
        *,
        destination: Path,
        request: dict[str, object],
        request_sha256: str,
        producer: dict[str, object],
        source: JudgeArtifacts,
    ) -> None:
        if not isinstance(producer, dict) or set(producer) != _PRODUCER_KEYS:
            raise RuntimeError("shared judgment producer has invalid fields")
        if (
            any(
                type(producer[key]) is not str or not producer[key]
                for key in ("assignment_id", "condition_id", "submission_id")
            )
            or producer.get("replicate") != request["replicate"]
            or producer.get("rubric_sha256") != request["rubric_sha256"]
            or type(producer.get("judge_attempt_id")) is not str
            or re.fullmatch(r"[0-9a-f]{32}", producer["judge_attempt_id"]) is None
        ):
            raise RuntimeError("shared judgment producer identity is invalid")
        source_root = source.score_validation_path.parent
        _reject_symlink_components(source_root)
        if source.evaluation_path.parent != source_root:
            raise RuntimeError("judge artifacts do not share one output directory")
        stage = Path(tempfile.mkdtemp(prefix=f".{request_sha256}.", dir=self.entries))
        try:
            hashes: dict[str, str] = {}
            for name in _CANONICAL_FILES:
                source_path = source_root / name
                if source_path.is_symlink() or not source_path.is_file():
                    raise RuntimeError(f"judge output lacks canonical artifact {name}")
                target = stage / name
                shutil.copyfile(source_path, target)
                hashes[name] = sha256_file(target)
            record = {
                "kind": "exact-semantic-judgment",
                "request_sha256": request_sha256,
                "request": request,
                "producer": producer,
                "artifacts": hashes,
            }
            write_json_atomic(stage / "record.json", record)
            self._validate_entry(stage, request, require_canonical_name=False)
            for path in stage.iterdir():
                make_read_only(path)
                _fsync_file(path)
            os.chmod(stage, 0o555)
            _fsync_directory(stage)
            os.rename(stage, destination)
            _fsync_directory(self.entries)
        except Exception:
            if stage.exists():
                os.chmod(stage, 0o700)
                for path in stage.iterdir():
                    try:
                        os.chmod(path, 0o600)
                    except OSError:
                        pass
                shutil.rmtree(stage)
            raise

    def _load(
        self,
        destination: Path,
        request: dict[str, object],
    ) -> ReusedJudgment:
        record = self._validate_entry(destination, request)
        return ReusedJudgment(
            artifacts=JudgeArtifacts(
                destination / "score_validation.json",
                destination / "evaluation.json",
            ),
            request_sha256=record["request_sha256"],
            canonical_entry=destination.name,
            canonical_record_sha256=sha256_file(destination / "record.json"),
        )

    def _validate_entry(
        self,
        destination: Path,
        request: dict[str, object],
        *,
        require_canonical_name: bool = True,
    ) -> dict[str, object]:
        self._validate_entry_shape(destination)
        record = read_json_object(destination / "record.json", "shared judgment")
        request_text = self._canonical_request_text(request)
        request_sha256 = sha256_text(request_text)
        artifacts = record.get("artifacts") if isinstance(record, dict) else None
        if (
            not isinstance(record, dict)
            or set(record) != _RECORD_KEYS
            or record.get("kind") != "exact-semantic-judgment"
            or record.get("request_sha256") != request_sha256
            or (require_canonical_name and destination.name != request_sha256)
            or record.get("request") != request
            or not isinstance(record.get("producer"), dict)
            or set(record["producer"]) != _PRODUCER_KEYS
            or any(
                type(record["producer"].get(key)) is not str
                or not record["producer"][key]
                for key in ("assignment_id", "condition_id", "submission_id")
            )
            or record["producer"].get("replicate") != request["replicate"]
            or record["producer"].get("rubric_sha256")
            != request["rubric_sha256"]
            or type(record["producer"].get("judge_attempt_id")) is not str
            or re.fullmatch(
                r"[0-9a-f]{32}", record["producer"]["judge_attempt_id"]
            ) is None
            or not isinstance(artifacts, dict)
            or set(artifacts) != set(_CANONICAL_FILES)
            or any(
                artifacts[name] != sha256_file(destination / name)
                for name in _CANONICAL_FILES
            )
        ):
            raise RuntimeError("shared judgment entry has invalid provenance")
        validation = read_json_object(
            destination / "score_validation.json",
            "shared score validation",
        )
        scoring_identity = request["scoring_identity"]
        assert isinstance(scoring_identity, dict)
        if (
            validation.get("task") != request["task_id"]
            or validation.get("rendered_rubric_sha256") != request["rubric_sha256"]
            or validation.get("review_input_sha256")
            != request["review_text_sha256"]
            or validation.get("answer_input_sha256")
            != request["answer_text_sha256"]
            or any(
                validation.get(key) != scoring_identity[key]
                for key in SCORING_IDENTITY_KEYS
            )
            or validation.get("reward_sha256") != artifacts["reward.json"]
            or validation.get("evaluation_sha256") != artifacts["evaluation.json"]
            or validation.get("usage_sha256") != artifacts["usage.json"]
            or sha256_file(destination / "judge_input_trace.md")
            != request["review_text_sha256"]
            or sha256_file(destination / "judge_input_answer.txt")
            != request["answer_text_sha256"]
            or isinstance(validation.get("score"), bool)
            or not isinstance(validation.get("score"), Real)
            or not math.isfinite(float(validation["score"]))
            or not 0 <= float(validation["score"]) <= 100
        ):
            raise RuntimeError("shared judgment score validation changed")
        return record

    def _validate_entry_shape(self, destination: Path) -> None:
        _reject_symlink_components(self.root)
        _require_directory(self.entries, "shared judgment entry root")
        _reject_symlink_components(destination)
        expected_names = {"record.json", *_CANONICAL_FILES}
        if (
            destination.is_symlink()
            or not destination.is_dir()
            or {path.name for path in destination.iterdir()} != expected_names
            or any(path.is_symlink() or not path.is_file() for path in destination.iterdir())
        ):
            raise RuntimeError("shared judgment entry is incomplete")

    def _request_lock(self, request_sha256: str):
        return _FileLock(self.locks / f"{request_sha256}.lock")


class ExactSimulatorReuseStore:
    """Publish one canonical two-stage simulated-user result per exact input."""

    _REQUEST_KEYS = {
        "kind",
        "experiment_id",
        "task_id",
        "replicate",
        "instruction_sha256",
        "bank_sha256",
        "current_submission_sha256",
        "simulator",
    }
    _SEMANTIC_KEYS = {
        "attempt_count",
        "output",
        "selection_generation",
        "comment_generation",
    }
    _PRODUCER_KEYS = {
        "assignment_id",
        "condition_id",
        "replicate",
        "submission_id",
        "generation_round",
    }
    _RECORD_KEYS = {
        "kind",
        "request_sha256",
        "request",
        "producer",
        "semantic_generation",
    }
    _ALIAS_KEYS = {
        "kind",
        "assignment_id",
        "replicate",
        "submission_id",
        "request_sha256",
        "canonical_entry",
        "canonical_record_sha256",
    }

    def __init__(self, root: Path) -> None:
        self.root = Path(os.path.abspath(root.expanduser()))
        _reject_symlink_components(self.root)
        if os.path.lexists(self.root) and (
            self.root.is_symlink() or not self.root.is_dir()
        ):
            raise RuntimeError("shared simulator reuse root is invalid")
        self.entries = self.root / "entries"
        self.locks = self.root / "locks"

    def resolve(
        self,
        *,
        request: dict[str, object],
        producer: dict[str, object],
        generate: Callable[[], dict[str, object]],
    ) -> ReusedSimulatorGeneration:
        request_text = self._canonical_request_text(request)
        request_sha256 = sha256_text(request_text)
        _reject_symlink_components(self.root)
        self.entries.mkdir(parents=True, exist_ok=True)
        self.locks.mkdir(parents=True, exist_ok=True)
        _require_directory(self.entries, "shared simulator entry root")
        _require_directory(self.locks, "shared simulator lock root")
        with _FileLock(self.locks / f"{request_sha256}.lock"):
            destination = self.entries / request_sha256
            if not os.path.lexists(destination):
                generated = generate()
                semantic = self._extract_semantic_generation(generated, request)
                self._publish(
                    destination,
                    request=request,
                    request_sha256=request_sha256,
                    producer=producer,
                    semantic=semantic,
                )
            return self._load(destination, request=request)

    def load(
        self,
        *,
        request_sha256: str,
        expected_request: dict[str, object],
    ) -> ReusedSimulatorGeneration:
        """Load one exact simulator result without trusting an alias target."""

        if _SHA256.fullmatch(request_sha256) is None:
            raise RuntimeError("shared simulator request hash is invalid")
        expected_sha256 = self.request_sha256(expected_request)
        if request_sha256 != expected_sha256:
            raise RuntimeError("shared simulator alias names another request")
        _reject_symlink_components(self.root)
        _require_directory(self.entries, "shared simulator entry root")
        return self._load(
            self.entries / expected_sha256,
            request=expected_request,
        )

    def assignment_record(
        self,
        reused: ReusedSimulatorGeneration,
        *,
        experiment_id: str,
        assignment_id: str,
        submission_id: str,
        generation_round: int,
        bank_sha256: str,
        simulator_identity: dict[str, object],
    ) -> dict[str, object]:
        return {
            "kind": "submission-simulated-user-feedback",
            "experiment_id": experiment_id,
            "assignment_id": assignment_id,
            "submission_id": submission_id,
            "generation_round": generation_round,
            "bank_sha256": bank_sha256,
            "simulator": simulator_identity,
            **reused.semantic_generation,
        }

    def persist_alias(
        self,
        *,
        experiment_dir: Path,
        assignment_id: str,
        replicate: int,
        submission_id: str,
        reused: ReusedSimulatorGeneration,
    ) -> Path:
        alias = {
            "kind": "exact-simulated-user-alias",
            "assignment_id": assignment_id,
            "replicate": replicate,
            "submission_id": submission_id,
            "request_sha256": reused.request_sha256,
            "canonical_entry": reused.canonical_entry,
            "canonical_record_sha256": reused.canonical_record_sha256,
        }
        path = experiment_dir / "simulated-user-aliases" / f"{submission_id}.json"
        _reject_symlink_components(experiment_dir)
        _reject_symlink_components(path.parent)
        if path.is_symlink():
            raise RuntimeError("simulated-user alias is a symbolic link")
        if path.is_file():
            if read_json_object(path, "simulated-user alias") != alias:
                raise RuntimeError("stored simulated-user alias changed")
            return path
        path.parent.mkdir(parents=True, exist_ok=True)
        _reject_symlink_components(path.parent)
        write_json_atomic(path, alias)
        make_read_only(path)
        return path

    def validate_alias(
        self,
        path: Path,
        *,
        assignment_id: str,
        replicate: int,
        submission_id: str,
        expected_request: dict[str, object],
    ) -> ReusedSimulatorGeneration:
        _reject_symlink_components(path)
        if path.is_symlink() or not path.is_file():
            raise RuntimeError("simulated-user alias is not a regular file")
        alias = read_json_object(path, "simulated-user alias")
        if (
            not isinstance(alias, dict)
            or set(alias) != self._ALIAS_KEYS
            or alias.get("kind") != "exact-simulated-user-alias"
            or alias.get("assignment_id") != assignment_id
            or alias.get("replicate") != replicate
            or alias.get("submission_id") != submission_id
            or type(alias.get("request_sha256")) is not str
            or _SHA256.fullmatch(alias["request_sha256"]) is None
        ):
            raise RuntimeError("simulated-user alias has invalid identity")
        reused = self.load(
            request_sha256=alias["request_sha256"],
            expected_request=expected_request,
        )
        if (
            alias.get("canonical_entry") != reused.canonical_entry
            or alias.get("canonical_record_sha256")
            != reused.canonical_record_sha256
        ):
            raise RuntimeError("simulated-user alias differs from its canonical entry")
        return reused

    def _canonical_request_text(self, request: object) -> str:
        if not isinstance(request, dict) or set(request) != self._REQUEST_KEYS:
            raise ValueError("exact simulator request has invalid fields")
        return json.dumps(
            request,
            ensure_ascii=False,
            allow_nan=False,
            sort_keys=True,
            separators=(",", ":"),
        ) + "\n"

    def request_sha256(self, request: dict[str, object]) -> str:
        """Return the canonical exact-request hash."""

        return sha256_text(self._canonical_request_text(request))

    def _extract_semantic_generation(
        self,
        generated: object,
        request: dict[str, object],
    ) -> dict[str, object]:
        if not isinstance(generated, dict):
            raise RuntimeError("simulated-user generator returned an invalid record")
        if (
            generated.get("kind") != "submission-simulated-user-feedback"
            or generated.get("experiment_id") != request["experiment_id"]
            or generated.get("bank_sha256") != request["bank_sha256"]
            or generated.get("simulator") != request["simulator"]
            or not self._SEMANTIC_KEYS <= set(generated)
        ):
            raise RuntimeError("simulated-user generator record has another request")
        return {key: generated[key] for key in self._SEMANTIC_KEYS}

    def _publish(
        self,
        destination: Path,
        *,
        request: dict[str, object],
        request_sha256: str,
        producer: dict[str, object],
        semantic: dict[str, object],
    ) -> None:
        if (
            not isinstance(producer, dict)
            or set(producer) != self._PRODUCER_KEYS
            or any(
                type(producer[key]) is not str or not producer[key]
                for key in ("assignment_id", "condition_id", "submission_id")
            )
            or producer.get("replicate") != request["replicate"]
            or type(producer.get("generation_round")) is not int
            or producer["generation_round"] < 0
        ):
            raise RuntimeError("shared simulator producer identity is invalid")
        stage = Path(tempfile.mkdtemp(prefix=f".{request_sha256}.", dir=self.entries))
        try:
            write_json_atomic(stage / "record.json", {
                "kind": "exact-simulated-user-generation",
                "request_sha256": request_sha256,
                "request": request,
                "producer": producer,
                "semantic_generation": semantic,
            })
            self._validate_entry(stage, request=request, canonical_name=False)
            make_read_only(stage / "record.json")
            _fsync_file(stage / "record.json")
            os.chmod(stage, 0o555)
            _fsync_directory(stage)
            os.rename(stage, destination)
            _fsync_directory(self.entries)
        except Exception:
            if stage.exists():
                os.chmod(stage, 0o700)
                for path in stage.iterdir():
                    os.chmod(path, 0o600)
                shutil.rmtree(stage)
            raise

    def _load(
        self,
        destination: Path,
        *,
        request: dict[str, object],
    ) -> ReusedSimulatorGeneration:
        record = self._validate_entry(destination, request=request)
        semantic = record["semantic_generation"]
        assert isinstance(semantic, dict)
        return ReusedSimulatorGeneration(
            semantic_generation=semantic,
            request_sha256=record["request_sha256"],
            canonical_entry=destination.name,
            canonical_record_sha256=sha256_file(destination / "record.json"),
        )

    def _validate_entry(
        self,
        destination: Path,
        *,
        request: dict[str, object],
        canonical_name: bool = True,
    ) -> dict[str, object]:
        _reject_symlink_components(self.root)
        _require_directory(self.entries, "shared simulator entry root")
        _reject_symlink_components(destination)
        record_path = destination / "record.json"
        if (
            destination.is_symlink()
            or not destination.is_dir()
            or {path.name for path in destination.iterdir()} != {"record.json"}
            or record_path.is_symlink()
            or not record_path.is_file()
        ):
            raise RuntimeError("shared simulator entry is incomplete")
        record = read_json_object(record_path, "shared simulator")
        request_sha256 = sha256_text(self._canonical_request_text(request))
        if (
            not isinstance(record, dict)
            or set(record) != self._RECORD_KEYS
            or record.get("kind") != "exact-simulated-user-generation"
            or record.get("request_sha256") != request_sha256
            or (canonical_name and destination.name != request_sha256)
            or record.get("request") != request
            or not isinstance(record.get("producer"), dict)
            or set(record["producer"]) != self._PRODUCER_KEYS
            or any(
                type(record["producer"].get(key)) is not str
                or not record["producer"][key]
                for key in ("assignment_id", "condition_id", "submission_id")
            )
            or record["producer"].get("replicate") != request["replicate"]
            or type(record["producer"].get("generation_round")) is not int
            or record["producer"]["generation_round"] < 0
            or not isinstance(record.get("semantic_generation"), dict)
            or set(record["semantic_generation"]) != self._SEMANTIC_KEYS
        ):
            raise RuntimeError("shared simulator entry has invalid provenance")
        return record


class _FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.descriptor: int | None = None

    def __enter__(self) -> None:
        _reject_symlink_components(self.path.parent)
        _require_directory(self.path.parent, "shared judgment lock root")
        flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(self.path, flags, 0o664)
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            os.close(descriptor)
            raise RuntimeError("shared judgment lock is not a regular file")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        self.descriptor = descriptor

    def __exit__(self, *_args: object) -> None:
        assert self.descriptor is not None
        fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        os.close(self.descriptor)
        self.descriptor = None


def _reject_symlink_components(path: Path) -> None:
    current = Path(path.anchor)
    for component in path.parts[1:]:
        current = current / component
        try:
            mode = os.lstat(current).st_mode
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(mode):
            raise RuntimeError(f"path contains a symbolic link: {current}")


def _require_directory(path: Path, context: str) -> None:
    try:
        mode = os.lstat(path).st_mode
    except OSError as exc:
        raise RuntimeError(f"{context} is missing") from exc
    if not stat.S_ISDIR(mode):
        raise RuntimeError(f"{context} is not a regular directory")


def _fsync_file(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | os.O_CLOEXEC)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
