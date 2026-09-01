"""Compile, seal, and install shared pre-treatment rubric generations."""

from __future__ import annotations

import fcntl
import json
import os
import stat
from contextlib import contextmanager
from pathlib import Path

from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.benchmarks import SubmissionBenchmark
from rubric_gen.runtime.agents.models import AgentRunConfig
from rubric_gen.submission_revision.artifacts import read_json_object
from rubric_gen.submission_revision.contrasts import build_offline_artifact_history
from rubric_gen.submission_revision.evolution import (
    PROVIDER_FAILURE_MAX_RETRIES,
    RubricProposer,
)
from rubric_gen.submission_revision.evolution_artifacts import ArtifactHistory
from rubric_gen.submission_revision.evolution_serialization import canonical_sha256
from rubric_gen.submission_revision.prompts import PromptProfile
from rubric_gen.submission_revision.rubric_generation import (
    CompleteRubric,
    RubricGeneration,
    RubricPolicy,
)
from rubric_gen.submission_revision.rubric_generation_store import (
    load_rubric_generation,
    persist_rubric_generation,
    rubric_generation_directory,
)


PRETREATMENT_RUBRIC_KIND = "rubric-gen-shared-pretreatment-rubric"
_EVOLUTION_FILE_NAMES = (
    "artifact-history.json",
    "difference-proposal.json",
    "rubric-proposal.json",
    "evolution.json",
)


def pretreatment_blinding_scope(
    experiment_id: str,
    task_id: str,
    original_rubric_sha256: str,
) -> str:
    """Return one stable blinding scope shared by all matching assignments."""

    for name, value in (
        ("experiment_id", experiment_id),
        ("task_id", task_id),
        ("original_rubric_sha256", original_rubric_sha256),
    ):
        if type(value) is not str or not value.strip():
            raise ValueError(f"{name} must be nonempty")
    return "pretreatment:" + sha256_text(json.dumps(
        {
            "experiment_id": experiment_id,
            "task_id": task_id,
            "original_rubric_sha256": original_rubric_sha256,
        },
        sort_keys=True,
        separators=(",", ":"),
    ))


def shared_pretreatment_rubric_dir(
    root: Path,
    task_id: str,
    original_rubric_sha256: str,
) -> Path:
    """Return the canonical task and original-rubric pool directory."""

    if type(task_id) is not str or not task_id or Path(task_id).name != task_id:
        raise ValueError("pre-treatment rubric task ID is unsafe")
    if (
        type(original_rubric_sha256) is not str
        or len(original_rubric_sha256) != 64
        or any(char not in "0123456789abcdef" for char in original_rubric_sha256)
    ):
        raise ValueError("pre-treatment original rubric hash is invalid")
    return root / task_id / original_rubric_sha256


def ensure_pretreatment_rubric(
    *,
    root: Path,
    experiment_id: str,
    task_dir: Path,
    benchmark: SubmissionBenchmark,
    initial_rubric: CompleteRubric,
    seed_set: Path,
    seed_generator: AgentRunConfig,
    prompt_profile: PromptProfile | str,
    seed_replicates: int,
    proposer: RubricProposer,
) -> RubricGeneration:
    """Compile one shared generation or validate its exact completed copy."""

    root = root.absolute()
    root.parent.mkdir(parents=True, exist_ok=True)
    with _exclusive_pool_lock(root):
        if os.path.lexists(root):
            if root.is_symlink() or not root.is_dir():
                raise RuntimeError(
                    f"pre-treatment rubric root is not a directory: {root}"
                )
        else:
            root.mkdir()
        unexpected = {
            path.name for path in root.iterdir()
        } - {"rubric-generations", "pretreatment.json"}
        if unexpected:
            raise RuntimeError(
                f"pre-treatment rubric root has unexpected entries: {root}"
            )
        instruction = (task_dir / "instruction.md").read_text(encoding="utf-8")
        initial_generation = _initial_generation(initial_rubric)
        history = _history(
            experiment_id=experiment_id,
            task_dir=task_dir,
            benchmark=benchmark,
            initial_rubric=initial_rubric,
            seed_set=seed_set,
            seed_generator=seed_generator,
            prompt_profile=prompt_profile,
            seed_replicates=seed_replicates,
        )
        persist_rubric_generation(
            root,
            initial_generation,
            RubricPolicy.OFFLINE_ELICITATION,
        )
        generation = proposer.elicit_rubric(
            instruction=instruction,
            original_rubric=initial_rubric,
            current_generation=initial_generation,
            policy=RubricPolicy.OFFLINE_ELICITATION,
            generation_round=1,
            output_dir=root,
            artifact_history=history,
            source_checkpoint=None,
        )
        expected = _manifest(
            experiment_id=experiment_id,
            task_dir=task_dir,
            initial_rubric=initial_rubric,
            history_sha256=canonical_sha256(history.artifact_record()),
            proposer=proposer,
            generation=generation,
        )
        path = root / "pretreatment.json"
        if os.path.lexists(path):
            if path.is_symlink() or not path.is_file():
                raise RuntimeError("pre-treatment rubric manifest is not regular")
            if read_json_object(path, "pre-treatment rubric manifest") != expected:
                raise RuntimeError("pre-treatment rubric identity changed")
        else:
            write_json_atomic(path, expected)
        return validate_pretreatment_rubric(
            root=root,
            experiment_id=experiment_id,
            task_dir=task_dir,
            benchmark=benchmark,
            initial_rubric=initial_rubric,
            seed_set=seed_set,
            seed_generator=seed_generator,
            prompt_profile=prompt_profile,
            seed_replicates=seed_replicates,
            proposer=proposer,
        )


def validate_pretreatment_rubric(
    *,
    root: Path,
    experiment_id: str,
    task_dir: Path,
    benchmark: SubmissionBenchmark,
    initial_rubric: CompleteRubric,
    seed_set: Path,
    seed_generator: AgentRunConfig,
    prompt_profile: PromptProfile | str,
    seed_replicates: int,
    proposer: RubricProposer,
) -> RubricGeneration:
    """Validate a complete shared pre-treatment rubric without new model work."""

    root = root.absolute()
    if root.is_symlink() or not root.is_dir():
        raise RuntimeError(f"pre-treatment rubric root is missing: {root}")
    if {path.name for path in root.iterdir()} != {
        "rubric-generations",
        "pretreatment.json",
    }:
        raise RuntimeError("pre-treatment rubric root is incomplete")
    initial_generation = load_rubric_generation(
        root,
        0,
        expected_policy=RubricPolicy.OFFLINE_ELICITATION,
    )
    if initial_generation != _initial_generation(initial_rubric):
        raise RuntimeError("pre-treatment initial rubric changed")
    generation = load_rubric_generation(
        root,
        1,
        expected_policy=RubricPolicy.OFFLINE_ELICITATION,
    )
    generation.validate_successor(initial_generation)
    history = _history(
        experiment_id=experiment_id,
        task_dir=task_dir,
        benchmark=benchmark,
        initial_rubric=initial_rubric,
        seed_set=seed_set,
        seed_generator=seed_generator,
        prompt_profile=prompt_profile,
        seed_replicates=seed_replicates,
    )
    replayed = proposer.elicit_rubric(
        instruction=(task_dir / "instruction.md").read_text(encoding="utf-8"),
        original_rubric=initial_rubric,
        current_generation=initial_generation,
        policy=RubricPolicy.OFFLINE_ELICITATION,
        generation_round=1,
        output_dir=root,
        artifact_history=history,
        source_checkpoint=None,
    )
    if replayed != generation:
        raise RuntimeError("pre-treatment rubric generation changed")
    expected = _manifest(
        experiment_id=experiment_id,
        task_dir=task_dir,
        initial_rubric=initial_rubric,
        history_sha256=canonical_sha256(history.artifact_record()),
        proposer=proposer,
        generation=generation,
    )
    if read_json_object(
        root / "pretreatment.json",
        "pre-treatment rubric manifest",
    ) != expected:
        raise RuntimeError("pre-treatment rubric identity changed")
    return generation


def install_pretreatment_rubric(
    *,
    source_root: Path,
    destination_root: Path,
    policy: RubricPolicy,
) -> RubricGeneration:
    """Install the exact shared generation in one elicitation assignment."""

    if policy not in {
        RubricPolicy.OFFLINE_ELICITATION,
        RubricPolicy.ONLINE_ELICITATION,
    }:
        raise ValueError("only elicitation policies use a pre-treatment rubric")
    generation = load_rubric_generation(
        source_root,
        1,
        expected_policy=RubricPolicy.OFFLINE_ELICITATION,
    )
    source = rubric_generation_directory(source_root, 1)
    evolution_files = {
        name: (source / name).read_text(encoding="utf-8")
        for name in _EVOLUTION_FILE_NAMES
    }
    persist_rubric_generation(
        destination_root,
        generation,
        policy,
        evolution_files=evolution_files,
    )
    validate_installed_pretreatment_rubric(
        source_root=source_root,
        destination_root=destination_root,
        policy=policy,
    )
    return generation


def validate_installed_pretreatment_rubric(
    *,
    source_root: Path,
    destination_root: Path,
    policy: RubricPolicy,
) -> RubricGeneration:
    """Require a local generation to equal its shared source byte for byte."""

    shared = load_rubric_generation(
        source_root,
        1,
        expected_policy=RubricPolicy.OFFLINE_ELICITATION,
    )
    local = load_rubric_generation(
        destination_root,
        1,
        expected_policy=policy,
    )
    if local != shared:
        raise RuntimeError("installed pre-treatment rubric differs from its source")
    source = rubric_generation_directory(source_root, 1)
    destination = rubric_generation_directory(destination_root, 1)
    for name in _EVOLUTION_FILE_NAMES:
        source_path = source / name
        destination_path = destination / name
        if (
            source_path.is_symlink()
            or destination_path.is_symlink()
            or not source_path.is_file()
            or not destination_path.is_file()
            or source_path.read_bytes() != destination_path.read_bytes()
        ):
            raise RuntimeError(
                "installed pre-treatment evolution evidence differs from its source"
            )
    return local


def _initial_generation(rubric: CompleteRubric) -> RubricGeneration:
    return RubricGeneration(
        generation_round=0,
        source_checkpoint=None,
        rubric=rubric,
        elicited_criteria=(),
        proposer_call_budget=0,
    )


def _history(
    *,
    experiment_id: str,
    task_dir: Path,
    benchmark: SubmissionBenchmark,
    initial_rubric: CompleteRubric,
    seed_set: Path,
    seed_generator: AgentRunConfig,
    prompt_profile: PromptProfile | str,
    seed_replicates: int,
) -> ArtifactHistory:
    return build_offline_artifact_history(
        seed_set=seed_set,
        task_dir=task_dir,
        benchmark=benchmark,
        seed_generator=seed_generator,
        prompt_profile=prompt_profile,
        seed_replicates=seed_replicates,
        blinding_scope=pretreatment_blinding_scope(
            experiment_id,
            task_dir.name,
            initial_rubric.content_sha256,
        ),
    )


def _manifest(
    *,
    experiment_id: str,
    task_dir: Path,
    initial_rubric: CompleteRubric,
    history_sha256: str,
    proposer: RubricProposer,
    generation: RubricGeneration,
) -> dict[str, object]:
    return {
        "kind": PRETREATMENT_RUBRIC_KIND,
        "experiment_id": experiment_id,
        "task_id": task_dir.name,
        "benchmark": proposer.benchmark.value,
        "instruction_sha256": sha256_file(task_dir / "instruction.md"),
        "initial_rubric_sha256": initial_rubric.content_sha256,
        "artifact_history_sha256": history_sha256,
        "proposer": proposer.proposer_contract.record(),
        "max_retries": proposer.max_retries,
        "provider_failure_max_retries": PROVIDER_FAILURE_MAX_RETRIES,
        "generation_sha256": generation.generation_sha256,
    }


@contextmanager
def _exclusive_pool_lock(root: Path):
    lock = root.parent / f".{root.name}.lock"
    flags = os.O_CREAT | os.O_RDWR | os.O_CLOEXEC
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(lock, flags, 0o664)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise RuntimeError("pre-treatment rubric lock is not a regular file")
        fcntl.flock(descriptor, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)
