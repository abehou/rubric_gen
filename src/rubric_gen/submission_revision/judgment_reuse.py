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
import threading
from collections.abc import Callable, Mapping
from pathlib import Path
from numbers import Real

from rubric_gen.artifacts.hashing import sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.artifacts import (
    read_json_object,
    remove_owned_evaluation_tree,
    sha256_file,
)
from rubric_gen.submission_revision.judge import (
    JUDGMENT_IDENTITY_KEYS,
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
_THREAD_LOCKS_GUARD = threading.Lock()
_THREAD_LOCKS: dict[Path, threading.Lock] = {}


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
        "scoring_identity": {
            key: scoring_identity[key] for key in JUDGMENT_IDENTITY_KEYS
        },
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
    ) -> JudgeArtifacts:
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
                _fsync_file(path)
            _fsync_directory(stage)
            os.rename(stage, destination)
            _fsync_directory(self.entries)
        except Exception:
            if stage.exists():
                shutil.rmtree(stage)
            raise

    def _load(
        self,
        destination: Path,
        request: dict[str, object],
    ) -> JudgeArtifacts:
        self._validate_entry(destination, request)
        return JudgeArtifacts(
            destination / "score_validation.json",
            destination / "evaluation.json",
        )

    def _validate_entry(
        self,
        destination: Path,
        request: dict[str, object],
        *,
        require_canonical_name: bool = True,
    ) -> None:
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
        _validate_artifacts(
            destination,
            request,
            "shared judgment",
            has_record=True,
        )

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


def persist_judgment_copy(
    *,
    experiment_dir: Path,
    submission_id: str,
    rubric_sha256: str,
    request: dict[str, object],
    source: JudgeArtifacts,
) -> JudgeArtifacts:
    """Atomically copy one completed judgment into its assignment."""

    destination = _local_judgment_dir(
        experiment_dir,
        submission_id,
        rubric_sha256,
    )
    if os.path.lexists(destination):
        return load_judgment_copy(
            experiment_dir=experiment_dir,
            submission_id=submission_id,
            rubric_sha256=rubric_sha256,
            expected_request=request,
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(destination.parent)
    _require_directory(destination.parent, "local judgment parent")
    source_root = source.score_validation_path.parent
    if source.evaluation_path.parent != source_root:
        raise RuntimeError("judge artifacts do not share one output directory")
    stage = Path(tempfile.mkdtemp(prefix=f".{rubric_sha256}.", dir=destination.parent))
    try:
        for name in _CANONICAL_FILES:
            source_path = source_root / name
            if source_path.is_symlink() or not source_path.is_file():
                raise RuntimeError(f"judge output lacks canonical artifact {name}")
            shutil.copyfile(source_path, stage / name)
        _validate_artifacts(stage, request, "local judgment")
        for path in stage.iterdir():
            _fsync_file(path)
        _fsync_directory(stage)
        os.rename(stage, destination)
        _fsync_directory(destination.parent)
    except Exception:
        if stage.exists():
            shutil.rmtree(stage)
        raise
    return _judge_artifacts(destination)


def load_judgment_copy(
    *,
    experiment_dir: Path,
    submission_id: str,
    rubric_sha256: str,
    expected_request: dict[str, object],
) -> JudgeArtifacts:
    """Load and validate one assignment-local judgment copy."""

    destination = _local_judgment_dir(
        experiment_dir,
        submission_id,
        rubric_sha256,
    )
    _validate_artifacts(destination, expected_request, "local judgment")
    return _judge_artifacts(destination)


def discard_temporary_judgment(
    experiment_dir: Path,
    artifacts: JudgeArtifacts,
) -> None:
    """Delete a completed judge workspace after its durable copy exists."""

    evaluations = experiment_dir / "evaluations"
    try:
        relative = artifacts.score_validation_path.relative_to(evaluations)
    except ValueError:
        return
    if (
        len(relative.parts) != 8
        or relative.parts[3:5] != ("run", "judges")
        or relative.name != "score_validation.json"
    ):
        raise RuntimeError("judge output has an unexpected temporary path")
    attempt_root = evaluations.joinpath(*relative.parts[:3])
    remove_owned_evaluation_tree(attempt_root, evaluations)


def _local_judgment_dir(
    experiment_dir: Path,
    submission_id: str,
    rubric_sha256: str,
) -> Path:
    if Path(submission_id).name != submission_id or not submission_id:
        raise ValueError("local judgment has an invalid submission ID")
    if _SHA256.fullmatch(rubric_sha256) is None:
        raise ValueError("local judgment has an invalid rubric hash")
    root = Path(os.path.abspath(experiment_dir.expanduser()))
    _reject_symlink_components(root)
    return root / "judgments" / submission_id / rubric_sha256


def _judge_artifacts(root: Path) -> JudgeArtifacts:
    return JudgeArtifacts(
        root / "score_validation.json",
        root / "evaluation.json",
    )


def _validate_artifacts(
    root: Path,
    request: dict[str, object],
    context: str,
    *,
    has_record: bool = False,
) -> None:
    _reject_symlink_components(root)
    expected_names = set(_CANONICAL_FILES)
    if has_record:
        expected_names.add("record.json")
    if (
        root.is_symlink()
        or not root.is_dir()
        or {path.name for path in root.iterdir()} != expected_names
        or any(path.is_symlink() or not path.is_file() for path in root.iterdir())
    ):
        raise RuntimeError(f"{context} is incomplete")
    validation = read_json_object(root / "score_validation.json", context)
    scoring_identity = request["scoring_identity"]
    assert isinstance(scoring_identity, dict)
    if (
        validation.get("task") != request["task_id"]
        or validation.get("rendered_rubric_sha256") != request["rubric_sha256"]
        or validation.get("review_input_sha256") != request["review_text_sha256"]
        or validation.get("answer_input_sha256") != request["answer_text_sha256"]
        or any(
            validation.get(key) != scoring_identity[key]
            for key in JUDGMENT_IDENTITY_KEYS
        )
        or validation.get("reward_sha256") != sha256_file(root / "reward.json")
        or validation.get("evaluation_sha256")
        != sha256_file(root / "evaluation.json")
        or validation.get("usage_sha256") != sha256_file(root / "usage.json")
        or sha256_file(root / "judge_input_trace.md")
        != request["review_text_sha256"]
        or sha256_file(root / "judge_input_answer.txt")
        != request["answer_text_sha256"]
        or isinstance(validation.get("score"), bool)
        or not isinstance(validation.get("score"), Real)
        or not math.isfinite(float(validation["score"]))
        or not 0 <= float(validation["score"]) <= 100
    ):
        raise RuntimeError(f"{context} score validation changed")


class _FileLock:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.descriptor: int | None = None
        with _THREAD_LOCKS_GUARD:
            self.thread_lock = _THREAD_LOCKS.setdefault(path, threading.Lock())

    def __enter__(self) -> None:
        self.thread_lock.acquire()
        _reject_symlink_components(self.path.parent)
        _require_directory(self.path.parent, "shared judgment lock root")
        flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        try:
            descriptor = os.open(self.path, flags, 0o664)
            if not stat.S_ISREG(os.fstat(descriptor).st_mode):
                os.close(descriptor)
                raise RuntimeError("shared judgment lock is not a regular file")
            fcntl.flock(descriptor, fcntl.LOCK_EX)
            self.descriptor = descriptor
        except Exception:
            self.thread_lock.release()
            raise

    def __exit__(self, *_args: object) -> None:
        assert self.descriptor is not None
        fcntl.flock(self.descriptor, fcntl.LOCK_UN)
        os.close(self.descriptor)
        self.descriptor = None
        self.thread_lock.release()


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
