"""Convert MALT rows into blinded forensic cases and inventory their labels."""

from __future__ import annotations

import hashlib
import json
import os
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

from rubric_gen.biomnibench.forensics.reward_hacking import CASE_KIND
from rubric_gen.biomnibench.utils.progress import TerminalProgress


@dataclass(frozen=True)
class MaltPrepareConfig:
    inputs: tuple[Path, ...]
    cases_dir: Path
    gold_path: Path
    positive_labels: frozenset[str]
    negative_labels: frozenset[str] = frozenset()
    development_fraction: float = 0.2
    validation_fraction: float = 0.1
    split_seed: str = "malt-v1"
    show_progress: bool = False

    def __post_init__(self) -> None:
        if (
            self.development_fraction < 0
            or self.validation_fraction < 0
            or self.development_fraction + self.validation_fraction >= 1
        ):
            raise ValueError("split fractions must be nonnegative and sum to less than 1")


def _metadata(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("metadata")
    return value if isinstance(value, dict) else row


def iter_rows(
    paths: Iterable[Path],
    *,
    parquet_columns: list[str] | None = None,
    progress_description: str | None = None,
) -> Iterator[dict[str, Any]]:
    input_paths = tuple(paths)
    total = 0
    if progress_description is not None:
        try:
            import pyarrow.parquet as parquet
        except ImportError:
            parquet = None
        if parquet is not None:
            total = sum(
                parquet.ParquetFile(path).metadata.num_rows
                for path in input_paths
                if path.suffix == ".parquet" and path.is_file()
            )
        total += sum(
            sum(bool(line.strip()) for line in path.open(encoding="utf-8"))
            for path in input_paths
            if path.suffix == ".jsonl" and path.is_file()
        )
        for path in input_paths:
            if path.suffix == ".json" and path.is_file():
                value = json.loads(path.read_text(encoding="utf-8"))
                total += len(value) if isinstance(value, list) else 1
    with TerminalProgress(
        total=total, description=progress_description or "", unit="row"
    ) if progress_description is not None else _NoProgress() as progress:
        yield from _iter_rows(input_paths, parquet_columns, progress)


class _NoProgress:
    def __enter__(self) -> _NoProgress:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def update(self) -> None:
        return None


def _iter_rows(
    paths: Iterable[Path], parquet_columns: list[str] | None, progress: Any
) -> Iterator[dict[str, Any]]:
    for path in paths:
        if not path.is_file():
            if any(character in str(path) for character in "*?["):
                raise FileNotFoundError(
                    f"MALT input glob matched no files: {path}. Download the dataset "
                    "first or correct the path; quote-free shell globs are expanded "
                    "only when matching files exist."
                )
            raise FileNotFoundError(f"MALT input file does not exist: {path}")
        if path.suffix in {".jsonl", ".json"}:
            with path.open(encoding="utf-8") as handle:
                if path.suffix == ".json":
                    value = json.load(handle)
                    rows = value if isinstance(value, list) else [value]
                    for row in rows:
                        if not isinstance(row, dict):
                            raise ValueError(f"non-object row in {path}")
                        progress.update()
                        yield row
                else:
                    for line_number, line in enumerate(handle, 1):
                        if not line.strip():
                            continue
                        row = json.loads(line)
                        if not isinstance(row, dict):
                            raise ValueError(f"non-object row at {path}:{line_number}")
                        progress.update()
                        yield row
            continue
        if path.suffix != ".parquet":
            raise ValueError(f"unsupported MALT input: {path}")
        try:
            import pyarrow.parquet as parquet
        except ImportError as exc:
            raise RuntimeError(
                "Parquet conversion requires pyarrow; install it explicitly or export MALT as JSONL"
            ) from exc
        parquet_file = parquet.ParquetFile(path)
        # A MALT row can contain a very large agent trajectory. Converting a
        # batch of them to Python objects multiplies peak memory for no useful
        # throughput gain during preparation, which is dominated by output I/O.
        for batch in parquet_file.iter_batches(batch_size=1, columns=parquet_columns):
            for row in batch.to_pylist():
                progress.update()
                yield row


def inventory_malt(
    paths: Iterable[Path], *, show_progress: bool = False
) -> dict[str, Any]:
    labels: Counter[str] = Counter()
    models: Counter[str] = Counter()
    reviewed = Counter()
    run_ids: set[str] = set()
    task_ids: set[str] = set()
    rows = 0
    empty_labels = 0
    for row in iter_rows(
        paths,
        parquet_columns=["metadata"],
        progress_description="MALT inventory" if show_progress else None,
    ):
        rows += 1
        metadata = _metadata(row)
        raw_labels = metadata.get("labels", [])
        if not isinstance(raw_labels, list) or not all(
            isinstance(label, str) for label in raw_labels
        ):
            raise ValueError(f"row {rows} has malformed labels")
        labels.update(raw_labels)
        empty_labels += not raw_labels
        reviewed[str(metadata.get("manually_reviewed"))] += 1
        models[str(metadata.get("model"))] += 1
        if isinstance(metadata.get("run_id"), (str, int)) and not isinstance(
            metadata.get("run_id"), bool
        ):
            run_ids.add(str(metadata["run_id"]))
        if isinstance(metadata.get("task_id"), str):
            task_ids.add(metadata["task_id"])
    return {
        "schema_version": 1,
        "rows": rows,
        "unique_run_ids": len(run_ids),
        "unique_task_ids": len(task_ids),
        "empty_label_rows": empty_labels,
        "manually_reviewed": dict(sorted(reviewed.items())),
        "labels": dict(labels.most_common()),
        "models": dict(models.most_common()),
    }


def _case_id(run_id: str | int) -> str:
    return "case-" + hashlib.sha256(str(run_id).encode("utf-8")).hexdigest()[:16]


def _split(task_id: str, config: MaltPrepareConfig) -> str:
    digest = hashlib.sha256(f"{config.split_seed}\0{task_id}".encode()).digest()
    fraction = int.from_bytes(digest[:8], "big") / 2**64
    if fraction < config.development_fraction:
        return "development"
    if fraction < config.development_fraction + config.validation_fraction:
        return "validation"
    return "test"


def prepare_malt(config: MaltPrepareConfig) -> dict[str, Any]:
    if not config.positive_labels:
        raise ValueError("the positive-label mapping cannot be empty")
    if config.gold_path.exists():
        raise FileExistsError("gold output already exists")
    config.cases_dir.mkdir(parents=True, exist_ok=True)
    config.gold_path.parent.mkdir(parents=True, exist_ok=True)
    seen_runs: set[str] = set()
    gold_rows: list[dict[str, Any]] = []
    skipped_unmapped = 0
    resumed_cases = 0
    for index, row in enumerate(iter_rows(
        config.inputs,
        progress_description="MALT preparation" if config.show_progress else None,
    ), 1):
        metadata = _metadata(row)
        run_id = metadata.get("run_id")
        task_id = metadata.get("task_id")
        labels = metadata.get("labels")
        samples = row.get("samples")
        if (
            not isinstance(run_id, (str, int))
            or isinstance(run_id, bool)
            or str(run_id) == ""
        ):
            raise ValueError(f"row {index} has no run_id")
        run_key = str(run_id)
        if run_key in seen_runs:
            raise ValueError(
                f"duplicate run_id {run_id!r}; convert one MALT configuration at a time"
            )
        if not isinstance(labels, list) or not all(isinstance(label, str) for label in labels):
            raise ValueError(f"row {index} has malformed labels")
        if not isinstance(task_id, str) or not task_id:
            raise ValueError(f"row {index} has no task_id")
        if not isinstance(samples, list):
            raise ValueError(f"row {index} has malformed samples")
        positive = bool(config.positive_labels.intersection(labels))
        negative = bool(config.negative_labels.intersection(labels))
        if positive and negative:
            raise ValueError(f"row {index} matches both positive and negative rules")
        if not positive and not negative:
            skipped_unmapped += 1
            continue
        case_id = _case_id(run_id)
        case_dir = config.cases_dir / case_id
        manifest = {
            "schema_version": 1,
            "kind": CASE_KIND,
            "case_id": case_id,
            "evidence_files": ["transcript.json"],
        }
        manifest_path = case_dir / "manifest.json"
        transcript_path = case_dir / "transcript.json"
        if case_dir.exists():
            if not manifest_path.is_file() or not transcript_path.is_file():
                raise ValueError(f"incomplete prepared case checkpoint: {case_dir}")
            if json.loads(manifest_path.read_text(encoding="utf-8")) != manifest:
                raise ValueError(f"invalid prepared case checkpoint: {case_dir}")
            if transcript_path.stat().st_size == 0:
                raise ValueError(f"empty prepared transcript checkpoint: {case_dir}")
            resumed_cases += 1
        else:
            case_dir.mkdir()
            _write_json_atomic(manifest_path, manifest, indent=2)
            _write_json_atomic(
                transcript_path, {"samples": samples}, indent=2, ensure_ascii=False
            )
        gold_rows.append(
            {
                "case_id": case_id,
                "positive": positive,
                "raw_human_labels": labels,
                "source_run_id": run_id,
                "source_task_id": task_id,
                "source_model": metadata.get("model"),
                "source_run_source": metadata.get("run_source"),
                "split": _split(task_id, config),
            }
        )
        seen_runs.add(run_key)
    temporary_gold = config.gold_path.with_name(
        f".{config.gold_path.name}.tmp-{os.getpid()}"
    )
    try:
        with temporary_gold.open("x", encoding="utf-8") as handle:
            for row in gold_rows:
                handle.write(json.dumps(row, ensure_ascii=False) + "\n")
        temporary_gold.replace(config.gold_path)
    finally:
        temporary_gold.unlink(missing_ok=True)
    return {
        "schema_version": 1,
        "cases": len(gold_rows),
        "positives": sum(bool(row["positive"]) for row in gold_rows),
        "negatives": sum(not bool(row["positive"]) for row in gold_rows),
        "skipped_unmapped": skipped_unmapped,
        "resumed_cases": resumed_cases,
        "splits": dict(Counter(str(row["split"]) for row in gold_rows)),
        "cases_dir": str(config.cases_dir),
        "gold_path": str(config.gold_path),
        "warning": "gold is structurally separated but agent filesystem isolation is not guaranteed",
    }


def _write_json_atomic(
    path: Path, value: Any, *, indent: int | None = None,
    ensure_ascii: bool = True,
) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(value, handle, indent=indent, ensure_ascii=ensure_ascii)
            handle.write("\n")
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
