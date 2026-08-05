"""Post-hoc cross-rubric scoring kept outside the solver feedback path."""

from __future__ import annotations

import hashlib
import json
import os
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path

from rubric_gen.biomnibench.experiments import ExperimentDesign, verify_runtime_provenance
from rubric_gen.biomnibench.revision.artifacts import read_json_object, sha256_file
from rubric_gen.biomnibench.revision.judge import (
    BiomniSubmissionJudge,
    FrozenRubric,
    SubmissionJudgeConfig,
)
from rubric_gen.biomnibench.study import (
    inspect_study,
    resolve_study_experiment,
    validate_completed_revision,
)
from rubric_gen.biomnibench.utils.progress import TerminalProgress
from rubric_gen.biomnibench.utils.serialization import write_json_atomic


CROSS_SCORE_KIND = "rubric-gen-cross-rubric-score-matrix"
CROSS_SCORE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CrossScoreConfig:
    design: ExperimentDesign
    study_dir: Path
    max_concurrency: int
    resume: bool = False

    def __post_init__(self) -> None:
        if type(self.max_concurrency) is not int or self.max_concurrency < 1:
            raise ValueError("max_concurrency must be positive")


class CrossScoreRunner:
    def __init__(self, config: CrossScoreConfig) -> None:
        self.config = config
        self.design = config.design
        self.study_root = config.study_dir.resolve()
        self.protocol = self.design.protocol
        self._write_lock = threading.Lock()

    def run(self) -> int:
        verify_runtime_provenance(self.design)
        study = read_json_object(self.study_root / "study.json", "study manifest")
        if study.get("design_sha256") != self.design.sha256:
            raise ValueError("cross-score study differs from the design")
        health = inspect_study(self.study_root, self.design)
        if study.get("status") != "completed" or not health.complete:
            raise ValueError(
                "cross-scoring requires a completed, integrity-valid study"
            )
        records = study.get("records")
        seed_value = study.get("seed_run_dir")
        if (
            not isinstance(records, list)
            or any(not isinstance(item, dict) for item in records)
            or type(seed_value) is not str
        ):
            raise ValueError("study records are invalid")
        seed_root = Path(seed_value).resolve()
        assignments = {
            str(item["assignment_id"]): item for item in self.design.assignments
        }
        jobs: list[tuple[Path, dict[str, object], int, str, Path]] = []
        matrices: dict[Path, dict[str, object]] = {}
        for record in records:
            if record.get("status") != "completed":
                raise ValueError("completed study contains a non-completed record")
            assignment = assignments.get(str(record.get("assignment_id")))
            if assignment is None:
                raise ValueError("study record is absent from the design")
            experiment = resolve_study_experiment(
                self.study_root, record, assignment
            )
            validate_completed_revision(
                experiment,
                assignment,
                self.design,
                seed_root,
            )
            matrix = self._load_or_create_matrix(experiment, assignment)
            matrices[experiment] = matrix
            for version, rubric_path in self._rubrics(experiment):
                for submission_id in matrix["submission_ids"]:  # type: ignore[index]
                    if self._cell(matrix, version, str(submission_id)) is not None:
                        continue
                    jobs.append(
                        (
                            experiment,
                            assignment,
                            version,
                            str(submission_id),
                            rubric_path,
                        )
                    )
        failures: list[dict[str, str]] = []
        with TerminalProgress(
            total=len(jobs), description="cross-rubric scoring", unit="cell"
        ) as progress:
            with ThreadPoolExecutor(max_workers=self.config.max_concurrency) as pool:
                futures = {pool.submit(self._one, *job): job for job in jobs}
                for future in as_completed(futures):
                    job = futures[future]
                    try:
                        future.result()
                    except Exception as exc:
                        failures.append({
                            "assignment_id": str(job[1]["assignment_id"]),
                            "rubric_version": str(job[2]),
                            "submission_id": job[3],
                            "error_type": type(exc).__name__,
                            "error": str(exc),
                        })
                    progress.update()
        for experiment, matrix in matrices.items():
            with self._write_lock:
                current = self._read_matrix(experiment)
                expected = len(current["rubric_versions"]) * len(current["submission_ids"])  # type: ignore[arg-type]
                current["status"] = (
                    "completed" if len(current["cells"]) == expected else "failed"
                )
                current["failures"] = [
                    item
                    for item in failures
                    if item["assignment_id"] == current["assignment_id"]
                ]
                self._write_matrix(experiment, current)
        return int(bool(failures))

    def _one(
        self,
        experiment: Path,
        assignment: dict[str, object],
        version: int,
        submission_id: str,
        rubric_path: Path,
    ) -> None:
        text = rubric_path.read_text(encoding="utf-8")
        rubric = FrozenRubric(
            text=text,
            sha256=sha256_file(rubric_path),
            source="post-hoc-cross-score",
            rubric_set_id=None,
            rubric_id=None,
            structured_rubric_sha256=None,
            manifest_sha256=None,
        )
        judge_config = SubmissionJudgeConfig(
            task_dir=self.design.task_dir(str(assignment["task_id"])),
            experiment_dir=experiment,
            review=str(self.protocol["review"]),
            judge_model=str(self.protocol["judge_model"]),
            rubric_name=None,
            rubric_set=None,
            max_review_chars=self.protocol["max_review_chars"],  # type: ignore[arg-type]
            max_retries=int(self.design.protocol["judge_max_retries"]),
            rubric_path=rubric_path,
        )
        judge = BiomniSubmissionJudge(judge_config, rubric)
        attempt_id = hashlib.sha256(
            f"{self.design.sha256}\0{assignment['assignment_id']}\0"
            f"{version}\0{submission_id}\0{rubric.sha256}".encode()
        ).hexdigest()[:32]
        submission = experiment / "submissions" / submission_id
        artifacts = judge.evaluate(submission, attempt_id)
        validation = read_json_object(
            artifacts.score_validation_path, "cross-rubric score validation"
        )
        score = validation.get("score")
        if type(score) is not int or not 0 <= score <= 100:
            raise RuntimeError("cross-rubric judge returned an invalid score")
        cell = {
            "rubric_version": version,
            "rubric_sha256": rubric.sha256,
            "submission_id": submission_id,
            "attempt_id": attempt_id,
            "score": score,
            "score_validation_path": str(artifacts.score_validation_path),
            "score_validation_sha256": sha256_file(artifacts.score_validation_path),
            "evaluation_path": str(artifacts.evaluation_path),
            "evaluation_sha256": sha256_file(artifacts.evaluation_path),
        }
        with self._write_lock:
            matrix = self._read_matrix(experiment)
            existing = self._cell(matrix, version, submission_id)
            if existing is not None and existing != cell:
                raise RuntimeError("cross-rubric matrix cell changed")
            if existing is None:
                cells = matrix["cells"]
                assert isinstance(cells, list)
                cells.append(cell)
                cells.sort(key=lambda item: (item["rubric_version"], item["submission_id"]))
                self._write_matrix(experiment, matrix)

    def _load_or_create_matrix(
        self, experiment: Path, assignment: dict[str, object]
    ) -> dict[str, object]:
        path = experiment / "cross_scores" / "matrix.json"
        if path.is_file():
            if not self.config.resume:
                raise FileExistsError(f"cross-score matrix exists: {path}")
            matrix = self._read_matrix(experiment)
            self._validate_matrix(matrix, assignment)
            for cell in matrix["cells"]:  # type: ignore[index]
                self._validate_cached_cell(cell)
            return matrix
        if os.path.lexists(path):
            raise RuntimeError(f"invalid cross-score matrix path: {path}")
        versions = [version for version, _ in self._rubrics(experiment)]
        matrix: dict[str, object] = {
            "schema_version": CROSS_SCORE_SCHEMA_VERSION,
            "kind": CROSS_SCORE_KIND,
            "status": "running",
            "design_sha256": self.design.sha256,
            "assignment_id": assignment["assignment_id"],
            "task_id": assignment["task_id"],
            "replicate": assignment["replicate"],
            "condition_id": assignment["condition_id"],
            "rubric_versions": versions,
            "submission_ids": [
                f"s{index:03d}"
                for index in range(int(self.protocol["revision_rounds"]) + 1)
            ],
            "cells": [],
            "failures": [],
        }
        self._write_matrix(experiment, matrix)
        return matrix

    def _rubrics(self, experiment: Path) -> list[tuple[int, Path]]:
        paths = sorted((experiment / "rubric").glob("r*.txt"))
        result: list[tuple[int, Path]] = []
        for path in paths:
            if path.is_symlink() or not path.is_file():
                raise RuntimeError(f"invalid rubric version: {path}")
            try:
                version = int(path.stem[1:])
            except ValueError as exc:
                raise RuntimeError(f"invalid rubric version name: {path.name}") from exc
            result.append((version, path))
        if not result or [version for version, _ in result] != list(range(len(result))):
            raise RuntimeError("rubric version sequence is incomplete")
        return result

    @staticmethod
    def _cell(
        matrix: dict[str, object], version: int, submission_id: str
    ) -> dict[str, object] | None:
        cells = matrix.get("cells")
        if not isinstance(cells, list):
            raise RuntimeError("cross-score matrix cells are invalid")
        matches = [
            cell for cell in cells
            if isinstance(cell, dict)
            and cell.get("rubric_version") == version
            and cell.get("submission_id") == submission_id
        ]
        if len(matches) > 1:
            raise RuntimeError("duplicate cross-score matrix cell")
        return matches[0] if matches else None

    def _read_matrix(self, experiment: Path) -> dict[str, object]:
        return read_json_object(
            experiment / "cross_scores" / "matrix.json", "cross-score matrix"
        )

    @staticmethod
    def _write_matrix(experiment: Path, matrix: dict[str, object]) -> None:
        write_json_atomic(experiment / "cross_scores" / "matrix.json", matrix)

    def _validate_matrix(
        self, matrix: dict[str, object], assignment: dict[str, object]
    ) -> None:
        if (
            matrix.get("schema_version") != CROSS_SCORE_SCHEMA_VERSION
            or matrix.get("kind") != CROSS_SCORE_KIND
            or matrix.get("design_sha256") != self.design.sha256
            or matrix.get("assignment_id") != assignment["assignment_id"]
            or matrix.get("task_id") != assignment["task_id"]
            or matrix.get("replicate") != assignment["replicate"]
            or matrix.get("condition_id") != assignment["condition_id"]
        ):
            raise RuntimeError("cross-score matrix identity changed")

    @staticmethod
    def _validate_cached_cell(cell: object) -> None:
        if not isinstance(cell, dict):
            raise RuntimeError("cross-score cell is invalid")
        validation = Path(str(cell.get("score_validation_path")))
        evaluation = Path(str(cell.get("evaluation_path")))
        if (
            validation.is_symlink()
            or evaluation.is_symlink()
            or not validation.is_file()
            or not evaluation.is_file()
            or sha256_file(validation) != cell.get("score_validation_sha256")
            or sha256_file(evaluation) != cell.get("evaluation_sha256")
        ):
            raise RuntimeError("cached cross-score cell failed integrity validation")
