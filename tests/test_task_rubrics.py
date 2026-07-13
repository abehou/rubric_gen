from __future__ import annotations

import json
from pathlib import Path

import pytest

from rubric_gen.biomnibench import task_rubrics as task_rubrics_module
from rubric_gen.biomnibench.task_rubrics import (
    DataFileSnapshot,
    RubricCriterion,
    RubricLevel,
    SchemaSnapshotLimits,
    TaskProcessRubric,
    TaskSnapshot,
    _walk_data_files,
    build_task_snapshot,
    canonical_json,
    parse_task_process_rubric,
    render_task_process_rubric,
    validate_task_process_rubric,
)


ROOT = Path(__file__).resolve().parents[1]
REAL_DA_19_1 = ROOT / "data" / "biomnibench-da" / "da-19-1"


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


@pytest.fixture
def snapshot(tmp_path: Path) -> TaskSnapshot:
    return build_task_snapshot(make_task(tmp_path))


def valid_rubric_payload(snapshot: TaskSnapshot) -> dict[str, object]:
    return {
        "schema_version": 1,
        "task_id": snapshot.task_id,
        "purpose": "Evaluate an evidence-grounded analysis process.",
        "criteria": [
            {
                "criterion_id": "C1",
                "title": "Task-specific analysis",
                "description": "Assess whether the required analysis was executed.",
                "max_points": 100,
                "task_anchors": ["summary:C1", "data:gene_exp.diff"],
                "required_evidence": ["Commands show the comparison was run."],
                "acceptable_alternatives": ["An equivalent scripted comparison."],
                "anti_evidence": ["A claim without a supporting artifact."],
                "verification": ["Inspect commands and the produced report."],
                "levels": [
                    {
                        "label": "A",
                        "points": 100,
                        "description": "Complete, verified analysis.",
                    },
                    {
                        "label": "B",
                        "points": 50,
                        "description": "Partial but supported analysis.",
                    },
                    {
                        "label": "C",
                        "points": 0,
                        "description": "No supported analysis.",
                    },
                ],
            },
            {
                "criterion_id": "C2",
                "title": "Unsupported-claim penalty",
                "description": "Penalize claims that contradict the evidence.",
                "max_points": 0,
                "task_anchors": ["evidence:final-claims"],
                "required_evidence": ["Final claims are traceable to results."],
                "acceptable_alternatives": ["No unsupported claims are made."],
                "anti_evidence": ["The final answer invents a result."],
                "verification": ["Cross-check final claims against artifacts."],
                "levels": [
                    {
                        "label": "A",
                        "points": 0,
                        "description": "Every claim is supported.",
                    },
                    {
                        "label": "B",
                        "points": -5,
                        "description": "One material claim is weakly supported.",
                    },
                    {
                        "label": "C",
                        "points": -10,
                        "description": "A material claim is contradicted.",
                    },
                ],
            },
        ],
    }


def parsed_valid_rubric(snapshot: TaskSnapshot) -> TaskProcessRubric:
    return parse_task_process_rubric(json.dumps(valid_rubric_payload(snapshot)))


def validation_text(payload: dict[str, object], snapshot: TaskSnapshot) -> str:
    rubric = parse_task_process_rubric(json.dumps(payload))
    return " ".join(validate_task_process_rubric(rubric, snapshot))


def test_penalty_criterion_is_valid(snapshot: TaskSnapshot) -> None:
    rubric = parsed_valid_rubric(snapshot)

    assert validate_task_process_rubric(rubric, snapshot) == ()
    assert isinstance(rubric, TaskProcessRubric)
    assert isinstance(rubric.criteria[0], RubricCriterion)
    assert isinstance(rubric.criteria[0].levels[0], RubricLevel)
    assert rubric.criteria[-1].levels[-1].points == -10


@pytest.mark.parametrize("target", ("root", "criterion", "level"))
def test_unknown_json_keys_are_rejected(
    snapshot: TaskSnapshot,
    target: str,
) -> None:
    payload = valid_rubric_payload(snapshot)
    if target == "root":
        payload["unexpected"] = "value"
    elif target == "criterion":
        payload["criteria"][0]["unexpected"] = "value"  # type: ignore[index]
    else:
        payload["criteria"][0]["levels"][0]["unexpected"] = "value"  # type: ignore[index]

    with pytest.raises(ValueError, match="unexpected key"):
        parse_task_process_rubric(json.dumps(payload))


def test_missing_json_key_is_rejected(snapshot: TaskSnapshot) -> None:
    payload = valid_rubric_payload(snapshot)
    del payload["purpose"]

    with pytest.raises(ValueError, match="missing key"):
        parse_task_process_rubric(json.dumps(payload))


def test_bool_points_are_rejected_without_integer_coercion(
    snapshot: TaskSnapshot,
) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["criteria"][0]["levels"][0]["points"] = True  # type: ignore[index]

    with pytest.raises(ValueError, match="points must be an integer"):
        parse_task_process_rubric(json.dumps(payload))


@pytest.mark.parametrize(
    "malformed",
    (
        '{"schema_version":1,"schema_version":1}',
        '{"schema_version":NaN}',
        '{"schema_version":Infinity}',
    ),
)
def test_malformed_rubric_json_is_rejected_strictly(malformed: str) -> None:
    with pytest.raises(ValueError):
        parse_task_process_rubric(malformed)


@pytest.mark.parametrize(
    "malformed",
    ('{"value":1,"value":2}', '{"value":NaN}', '{"value":-Infinity}'),
)
def test_shared_strict_json_loader_rejects_noncanonical_json(
    malformed: str,
) -> None:
    loader = getattr(task_rubrics_module, "load_json_strict", None)

    assert loader is not None
    with pytest.raises(ValueError):
        loader(malformed)


def test_wrong_task_id_is_rejected(snapshot: TaskSnapshot) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["task_id"] = "da-wrong"

    assert "task_id does not match snapshot" in validation_text(payload, snapshot)


def test_skipped_criterion_id_is_rejected(snapshot: TaskSnapshot) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["criteria"][1]["criterion_id"] = "C3"  # type: ignore[index]

    assert "criterion IDs must be contiguous" in validation_text(payload, snapshot)


def test_skipped_level_label_is_rejected(snapshot: TaskSnapshot) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["criteria"][0]["levels"][1]["label"] = "D"  # type: ignore[index]

    assert "level labels must be contiguous" in validation_text(payload, snapshot)


def test_duplicate_anchor_is_rejected(snapshot: TaskSnapshot) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["criteria"][0]["task_anchors"] = ["summary:C1", "summary:C1"]  # type: ignore[index]

    assert "duplicate task anchor" in validation_text(payload, snapshot)


def test_unknown_anchor_is_rejected(snapshot: TaskSnapshot) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["criteria"][0]["task_anchors"] = ["unknown:anchor"]  # type: ignore[index]

    assert "unknown task anchor" in validation_text(payload, snapshot)


def test_uncovered_summary_anchor_is_rejected(snapshot: TaskSnapshot) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["criteria"][0]["task_anchors"] = ["data:gene_exp.diff"]  # type: ignore[index]

    assert "required summary anchor is not covered" in validation_text(payload, snapshot)


@pytest.mark.parametrize(
    "field_name",
    (
        "required_evidence",
        "acceptable_alternatives",
        "anti_evidence",
        "verification",
    ),
)
def test_empty_evidence_list_is_rejected(
    snapshot: TaskSnapshot,
    field_name: str,
) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["criteria"][0][field_name] = []  # type: ignore[index]

    assert f"{field_name} must be non-empty" in validation_text(payload, snapshot)


@pytest.mark.parametrize(
    "field_name",
    (
        "required_evidence",
        "acceptable_alternatives",
        "anti_evidence",
        "verification",
    ),
)
def test_blank_evidence_item_is_rejected(
    snapshot: TaskSnapshot,
    field_name: str,
) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["criteria"][0][field_name] = [" "]  # type: ignore[index]

    assert f"{field_name} contains an empty item" in validation_text(payload, snapshot)


def test_duplicate_evidence_item_is_rejected(snapshot: TaskSnapshot) -> None:
    payload = valid_rubric_payload(snapshot)
    evidence = "Commands show the comparison was run."
    payload["criteria"][0]["required_evidence"] = [evidence, evidence]  # type: ignore[index]

    assert "required_evidence contains duplicate items" in validation_text(payload, snapshot)


def test_criterion_without_anchor_is_rejected(snapshot: TaskSnapshot) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["criteria"][0]["task_anchors"] = []  # type: ignore[index]

    assert "task_anchors must be non-empty" in validation_text(payload, snapshot)


def test_a_level_must_equal_max_points(snapshot: TaskSnapshot) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["criteria"][0]["max_points"] = 99  # type: ignore[index]

    assert "A-level points must equal max_points" in validation_text(payload, snapshot)


def test_each_criterion_must_have_exactly_one_zero(snapshot: TaskSnapshot) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["criteria"][0]["levels"][2]["points"] = -1  # type: ignore[index]

    assert "exactly one zero-point level" in validation_text(payload, snapshot)


def test_level_points_must_be_strictly_descending(snapshot: TaskSnapshot) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["criteria"][0]["levels"][1]["points"] = 100  # type: ignore[index]

    assert "level points must be strictly descending" in validation_text(payload, snapshot)


def test_criterion_must_have_at_least_three_levels(snapshot: TaskSnapshot) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["criteria"][0]["levels"] = payload["criteria"][0]["levels"][:2]  # type: ignore[index]

    assert "at least three levels" in validation_text(payload, snapshot)


def test_criterion_must_not_have_more_than_26_levels(
    snapshot: TaskSnapshot,
) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["criteria"][0]["max_points"] = 26  # type: ignore[index]
    payload["criteria"][0]["levels"] = [  # type: ignore[index]
        {
            "label": chr(ord("A") + index),
            "points": 26 - index,
            "description": f"Level {index}",
        }
        for index in range(27)
    ]

    assert "at most 26 levels" in validation_text(payload, snapshot)


def test_level_labels_are_restricted_to_ascii_a_through_z(
    snapshot: TaskSnapshot,
) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["criteria"][0]["levels"][2]["label"] = "["  # type: ignore[index]

    assert "level labels must use A through Z" in validation_text(payload, snapshot)


@pytest.mark.parametrize(
    "field_name",
    (
        "purpose",
        "title",
        "description",
        "task_anchors",
        "required_evidence",
        "acceptable_alternatives",
        "anti_evidence",
        "verification",
        "level_description",
    ),
)
@pytest.mark.parametrize("control", ("\n", "\x00", "\x1f", "\x7f"))
def test_rendered_string_fields_reject_ascii_control_characters(
    snapshot: TaskSnapshot,
    field_name: str,
    control: str,
) -> None:
    payload = valid_rubric_payload(snapshot)
    if field_name == "purpose":
        payload["purpose"] = f"unsafe{control}value"
    elif field_name == "level_description":
        payload["criteria"][0]["levels"][0]["description"] = f"unsafe{control}value"  # type: ignore[index]
    elif field_name in {"title", "description"}:
        payload["criteria"][0][field_name] = f"unsafe{control}value"  # type: ignore[index]
    else:
        payload["criteria"][0][field_name][0] = f"unsafe{control}value"  # type: ignore[index]

    assert "ASCII control characters" in validation_text(payload, snapshot)


def test_total_max_points_must_equal_100(snapshot: TaskSnapshot) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["criteria"][0]["max_points"] = 90  # type: ignore[index]
    payload["criteria"][0]["levels"][0]["points"] = 90  # type: ignore[index]

    assert "total max_points must equal 100" in validation_text(payload, snapshot)


def test_render_task_process_rubric_is_deterministic(snapshot: TaskSnapshot) -> None:
    rubric = parsed_valid_rubric(snapshot)

    first = render_task_process_rubric(rubric)
    second = render_task_process_rubric(rubric)

    assert first == second
    assert first.encode("utf-8") == second.encode("utf-8")
    assert first == """Purpose: Evaluate an evidence-grounded analysis process.

Criterion 1: Task-specific analysis

    Description: Assess whether the required analysis was executed.
    Task anchors:
      - summary:C1
      - data:gene_exp.diff
    Required evidence:
      - Commands show the comparison was run.
    Acceptable alternatives:
      - An equivalent scripted comparison.
    Anti-evidence:
      - A claim without a supporting artifact.
    Verification:
      - Inspect commands and the produced report.
    Levels: A=100 B=50 C=0
      [A]: Complete, verified analysis.
      [B]: Partial but supported analysis.
      [C]: No supported analysis.

Criterion 2: Unsupported-claim penalty

    Description: Penalize claims that contradict the evidence.
    Task anchors:
      - evidence:final-claims
    Required evidence:
      - Final claims are traceable to results.
    Acceptable alternatives:
      - No unsupported claims are made.
    Anti-evidence:
      - The final answer invents a result.
    Verification:
      - Cross-check final claims against artifacts.
    Levels: A=0 B=-5 C=-10
      [A]: Every claim is supported.
      [B]: One material claim is weakly supported.
      [C]: A material claim is contradicted.
"""


def test_structured_rubric_level_map_is_pure_and_scoring_compatible(
    snapshot: TaskSnapshot,
) -> None:
    helper = getattr(task_rubrics_module, "structured_rubric_level_map", None)

    assert helper is not None
    rubric = parsed_valid_rubric(snapshot)
    assert helper(rubric) == {
        "criterion_1": {"A": 100, "B": 50, "C": 0},
        "criterion_2": {"A": 0, "B": -5, "C": -10},
    }


def test_rendered_rubric_level_map_must_round_trip_exactly(
    snapshot: TaskSnapshot,
) -> None:
    validator = getattr(
        task_rubrics_module,
        "validate_rendered_task_process_rubric",
        None,
    )

    assert validator is not None
    rubric = parsed_valid_rubric(snapshot)
    rendered = render_task_process_rubric(rubric).replace(
        "Levels: A=100 B=50 C=0",
        "Levels: A=99 B=50 C=0",
        1,
    )
    with pytest.raises(ValueError, match="criterion/level map"):
        validator(rubric, rendered)


def test_rendered_rubric_round_trip_rejects_control_characters_independently(
    snapshot: TaskSnapshot,
) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["purpose"] = "unsafe\nvalue"
    rubric = parse_task_process_rubric(json.dumps(payload))

    with pytest.raises(ValueError, match="ASCII control characters"):
        task_rubrics_module.validate_rendered_task_process_rubric(
            rubric,
            render_task_process_rubric(rubric),
        )


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


@pytest.mark.parametrize(
    "field_name",
    (
        "max_files",
        "max_entries_visited",
        "max_probe_bytes",
        "max_rows",
        "max_columns",
        "max_examples_per_column",
        "max_string_chars",
        "max_output_chars",
    ),
)
def test_negative_schema_limits_raise_value_error(field_name: str) -> None:
    with pytest.raises(ValueError, match=field_name):
        SchemaSnapshotLimits(**{field_name: -2})


def test_schema_output_budget_must_fit_valid_json() -> None:
    with pytest.raises(ValueError, match="max_output_chars"):
        SchemaSnapshotLimits(max_output_chars=1)


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


def test_entry_limit_bounds_directory_enumeration(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    data = tmp_path / "data"
    many = data / "many"
    many.mkdir(parents=True)
    for index in range(20):
        (many / f"{index:02}.tsv").write_text("id\n1\n", encoding="utf-8")

    original_iterdir = Path.iterdir
    enumerated = 0

    def counted_iterdir(path: Path):
        nonlocal enumerated
        for child in original_iterdir(path):
            enumerated += 1
            yield child

    monkeypatch.setattr(Path, "iterdir", counted_iterdir)

    files, _, truncated = _walk_data_files(
        data,
        SchemaSnapshotLimits(max_entries_visited=3),
    )

    assert enumerated == 3
    assert files == ()
    assert truncated is True


def test_wide_directory_overflow_is_order_independent_and_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = make_task(tmp_path)
    many = task / "environment" / "data" / "many"
    many.mkdir()
    for index in range(10):
        (many / f"{index:02}.tsv").write_text("id\n1\n", encoding="utf-8")

    original_iterdir = Path.iterdir
    reverse_many = False

    def permuted_iterdir(path: Path):
        children = list(original_iterdir(path))
        if path == many:
            children.sort(key=lambda child: child.name, reverse=reverse_many)
        return iter(children)

    monkeypatch.setattr(Path, "iterdir", permuted_iterdir)
    limits = SchemaSnapshotLimits(max_entries_visited=6)

    first = build_task_snapshot(task, limits)
    reverse_many = True
    second = build_task_snapshot(task, limits)

    assert canonical_json(first.to_dict()) == canonical_json(second.to_dict())
    assert first.snapshot_sha256 == second.snapshot_sha256
    assert [data_file.path for data_file in first.data_files] == [
        "gene_exp.diff",
        "invalid.bin",
    ]
    assert first.data_traversal_truncated is True


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


@pytest.mark.skipif(not REAL_DA_19_1.is_dir(), reason="real da-19-1 data is not checked in")
def test_real_da_19_1_snapshot_has_three_bounded_tables() -> None:
    snapshot = build_task_snapshot(REAL_DA_19_1)
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
