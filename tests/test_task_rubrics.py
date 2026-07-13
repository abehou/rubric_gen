from __future__ import annotations

import json
from pathlib import Path

from rubric_gen.biomnibench.task_rubrics import (
    DataFileSnapshot,
    SchemaSnapshotLimits,
    TaskSnapshot,
    build_task_snapshot,
    canonical_json,
)


ROOT = Path(__file__).resolve().parents[1]


def make_task(tmp_path: Path) -> Path:
    task = tmp_path / "da-1-1"
    data = task / "environment" / "data"
    data.mkdir(parents=True)
    (task / "tests").mkdir()

    (task / "instruction.md").write_text(
        """# Task

## Question

Which genes respond to treatment?

## Data Files

Use `gene_exp.diff`.

## Required Outputs

Write `report.tsv`.
""",
        encoding="utf-8",
    )
    (task / "task.toml").write_text(
        'schema_version = "1.1"\n[task]\nname = "phylo/da-1-1"\n',
        encoding="utf-8",
    )
    (task / "tests" / "rubric.txt").write_text(
        """Criterion 1: Correct comparison

    Description: Compare treated and control samples.
    Levels: A=100 B=50 C=0
      [A]: Correct.
      [B]: Partial.
      [C]: Missing.
""",
        encoding="utf-8",
    )
    (data / "gene_exp.diff").write_bytes(
        b"gene_id\tlabel\tlog2(fold_change)\tstatus\tsignificant\r\n"
        b"ENSG000001\talpha,beta\t-inf\tOK\tyes\r\n"
        b"ENSG000002\tgamma\tinf\tOK\tno\r\n"
        b"ENSG000003\tdelta\t-nan\tNOTEST\tno\r\n"
    )
    (data / "invalid.bin").write_bytes(b"\xff\xfe\x00\x80")
    (data / "linked.diff").symlink_to(data / "gene_exp.diff")

    (task / "trace.md").write_text("runtime trace", encoding="utf-8")
    (task / "answer.txt").write_text("runtime answer", encoding="utf-8")
    run_dir = task / "runs" / "attempt-1"
    run_dir.mkdir(parents=True)
    (run_dir / "trajectory.jsonl").write_text("runtime event", encoding="utf-8")
    return task


def test_task_snapshot_is_deterministic_and_runtime_blind(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    first = build_task_snapshot(task)
    second = build_task_snapshot(task)

    assert canonical_json(first.to_dict()) == canonical_json(second.to_dict())
    assert first.snapshot_sha256 == second.snapshot_sha256
    serialized = canonical_json(first.to_dict())
    for forbidden in ("trajectory", "trace.md", "answer.txt", "runs/"):
        assert forbidden not in serialized


def find_table(snapshot: TaskSnapshot, name: str) -> DataFileSnapshot:
    return next(data_file for data_file in snapshot.data_files if data_file.path == name)


def test_schema_preserves_task_specific_values(tmp_path: Path) -> None:
    table = find_table(build_task_snapshot(make_task(tmp_path)), "gene_exp.diff")

    assert "log2(fold_change)" in table.columns
    assert table.delimiter == "\t"
    assert "-inf" in canonical_json(table.to_dict())
    assert "inf" in canonical_json(table.to_dict())
    assert "-nan" in canonical_json(table.to_dict())
    assert "yes" in canonical_json(table.to_dict())


def test_snapshot_sorts_nested_paths_and_never_follows_symlinks(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    data = task / "environment" / "data"
    (data / "z").mkdir()
    (data / "z" / "last.csv").write_text("id,value\nz,1\n", encoding="utf-8")
    (data / "a").mkdir()
    (data / "a" / "first.csv").write_text("id,value\na,1\n", encoding="utf-8")
    (data / "alias").symlink_to(data / "z", target_is_directory=True)

    paths = [data_file.path for data_file in build_task_snapshot(task).data_files]

    assert paths == ["a/first.csv", "gene_exp.diff", "invalid.bin", "z/last.csv"]
    assert all("alias" not in path and "linked" not in path for path in paths)


def test_probe_is_byte_bounded_without_misclassifying_split_utf8(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    data = task / "environment" / "data"
    (data / "utf8.tsv").write_bytes("name\tvalue\nα\t1\n".encode("utf-8"))
    limits = SchemaSnapshotLimits(max_probe_bytes=12)

    table = find_table(build_task_snapshot(task, limits), "utf8.tsv")

    assert table.kind == "table"
    assert table.columns == ("name", "value")
    assert table.probe_bytes == 12
    assert table.probe_truncated is True


def test_invalid_utf8_file_exposes_inventory_metadata_only(tmp_path: Path) -> None:
    binary = find_table(build_task_snapshot(make_task(tmp_path)), "invalid.bin")

    assert binary.to_dict() == {
        "kind": "binary",
        "path": "invalid.bin",
        "sha256": binary.sha256,
        "size_bytes": 4,
    }


def test_table_probe_applies_row_column_example_and_string_limits(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    data = task / "environment" / "data"
    (data / "wide.csv").write_text(
        "verylongcolumn,c1,c2\nabcdef,1,x\nabcghi,2,y\nabcjkl,3,z\n",
        encoding="utf-8",
    )
    limits = SchemaSnapshotLimits(
        max_rows=2,
        max_columns=2,
        max_examples_per_column=1,
        max_string_chars=5,
    )

    table = find_table(build_task_snapshot(task, limits), "wide.csv")

    assert table.columns == ("veryl", "c1")
    assert table.rows_seen == 3
    assert table.examples == (("abcde",), ("1",))
    assert table.omitted_rows == 1
    assert table.omitted_columns == 1
    assert table.omitted_examples == 2


def test_snapshot_extracts_immutable_inputs_and_stable_anchors(tmp_path: Path) -> None:
    snapshot = build_task_snapshot(make_task(tmp_path))

    assert snapshot.question == "Which genes respond to treatment?"
    assert snapshot.required_outputs == ("report.tsv",)
    hash_paths = [path for path, _ in snapshot.input_hashes]
    assert hash_paths == sorted(hash_paths)
    assert set(hash_paths) == {
        "environment/data/gene_exp.diff",
        "environment/data/invalid.bin",
        "instruction.md",
        "task.toml",
        "tests/rubric.txt",
    }

    anchor_ids = {anchor.anchor_id for anchor in snapshot.anchors}
    assert {
        "task:question",
        "task:required-output:report.tsv",
        "summary:C1",
        "data:gene_exp.diff",
        "data:invalid.bin",
        "schema:gene_exp.diff#log2(fold_change)",
        "evidence:events",
        "evidence:commands",
        "evidence:file-reads",
        "evidence:file-writes",
        "evidence:artifacts",
        "evidence:final-claims",
    } <= anchor_ids
    assert snapshot.required_summary_anchor_ids == ("summary:C1",)


def test_schema_budget_drops_examples_then_columns_then_files(tmp_path: Path) -> None:
    limits = SchemaSnapshotLimits(max_output_chars=400)

    snapshot = build_task_snapshot(make_task(tmp_path), limits)
    schema_json = canonical_json([data_file.to_dict() for data_file in snapshot.data_files])

    assert len(schema_json) <= limits.max_output_chars
    assert json.loads(schema_json)
    assert [data_file.path for data_file in snapshot.data_files] == ["gene_exp.diff"]
    assert snapshot.data_files[0].examples == ()
    assert snapshot.data_files[0].columns == ()
    assert snapshot.data_files[0].omitted_examples == 13
    assert snapshot.data_files[0].omitted_columns == 5
    assert snapshot.omitted_data_files == 1


def test_real_da_19_1_snapshot_has_three_bounded_tables() -> None:
    task = ROOT / "data" / "biomnibench-da" / "da-19-1"

    snapshot = build_task_snapshot(task)
    column_counts = {data_file.path: len(data_file.columns) for data_file in snapshot.data_files}
    schema_json = canonical_json([data_file.to_dict() for data_file in snapshot.data_files])

    assert snapshot.task_id == "da-19-1"
    assert column_counts == {
        "processed_data/rnaseq/cuffdiff/gene_exp.diff": 14,
        "processed_data/rnaseq/cuffdiff/run.info": 2,
        "processed_data/rnaseq/rnaseq_alignment_manifest.tsv": 6,
    }
    assert len(schema_json) <= SchemaSnapshotLimits().max_output_chars
    assert all("runs/" not in path for path, _ in snapshot.input_hashes)
