from __future__ import annotations

import json
import os
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace

import pytest

from rubric_gen.biomnibench.rubrics import schema as task_rubrics_module
from rubric_gen.biomnibench.rubrics import snapshots as task_snapshots_module
from rubric_gen.biomnibench.rubrics.schema import (
    DataFileSnapshot,
    RubricCriterion,
    RubricLevel,
    SchemaSnapshotLimits,
    TaskProcessRubric,
    TaskSnapshot,
    build_task_snapshot,
    canonical_json,
    parse_task_process_rubric,
    render_task_process_rubric,
    validate_task_process_rubric,
)
from rubric_gen.biomnibench.rubrics.snapshots import _walk_data_files


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
    (task / "trace.md").write_text("runtime trace", encoding="utf-8")
    (task / "answer.txt").write_text("runtime answer", encoding="utf-8")
    run_dir = task / "runs" / "attempt-1"
    run_dir.mkdir(parents=True)
    (run_dir / "trajectory.jsonl").write_text("runtime event", encoding="utf-8")
    return task


def mutate_after_target_fd_read(
    monkeypatch: pytest.MonkeyPatch,
    target: Path,
    mutation: Callable[[], None],
) -> list[bool]:
    original_read = os.read
    target_stat = target.stat()
    mutated = [False]

    def racing_read(fd: int, size: int) -> bytes:
        chunk = original_read(fd, size)
        opened_stat = os.fstat(fd)
        if (
            chunk
            and not mutated[0]
            and (opened_stat.st_dev, opened_stat.st_ino)
            == (target_stat.st_dev, target_stat.st_ino)
        ):
            mutation()
            mutated[0] = True
        return chunk

    monkeypatch.setattr(os, "read", racing_read)
    return mutated


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


@pytest.mark.parametrize(
    "phrase",
    (
        "search history",
        "prior score",
        "previous scores",
        "accepted candidate",
        "rejected candidates",
        "parent candidate",
        "hidden audit",
        "criterion feedback",
    ),
)
def test_runtime_search_context_phrases_are_rejected(
    snapshot: TaskSnapshot,
    phrase: str,
) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["criteria"][0]["verification"] = [  # type: ignore[index]
        f"Condition credit on the {phrase}."
    ]

    assert "runtime/search context" in validation_text(payload, snapshot)


@pytest.mark.parametrize(
    "unsafe_identifier",
    (
        "current search run ID",
        "hill-climbing candidate ID",
        "experiment condition_id used for credit",
    ),
)
def test_contextual_search_identifiers_are_rejected(
    snapshot: TaskSnapshot,
    unsafe_identifier: str,
) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["purpose"] = f"Consult the {unsafe_identifier}."

    assert "runtime/search context" in validation_text(payload, snapshot)


@pytest.mark.parametrize(
    "field_name",
    (
        "purpose",
        "title",
        "description",
        "required_evidence",
        "acceptable_alternatives",
        "anti_evidence",
        "verification",
        "level_description",
    ),
)
def test_every_free_form_rubric_text_field_rejects_runtime_context(
    snapshot: TaskSnapshot,
    field_name: str,
) -> None:
    payload = valid_rubric_payload(snapshot)
    unsafe = "Condition credit on the hidden audit."
    if field_name == "purpose":
        payload["purpose"] = unsafe
    elif field_name == "level_description":
        payload["criteria"][0]["levels"][0]["description"] = unsafe  # type: ignore[index]
    elif field_name in {"title", "description"}:
        payload["criteria"][0][field_name] = unsafe  # type: ignore[index]
    else:
        payload["criteria"][0][field_name][0] = unsafe  # type: ignore[index]

    assert "runtime/search context" in validation_text(payload, snapshot)


def test_review_reproduction_rejects_search_conditioned_level(
    snapshot: TaskSnapshot,
) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["criteria"][0]["levels"][0]["description"] = (  # type: ignore[index]
        "Award full credit when the parent candidate improves its previous score "
        "according to criterion feedback."
    )

    assert "runtime/search context" in validation_text(payload, snapshot)


def test_generic_scientific_answer_score_and_run_language_remains_allowed(
    snapshot: TaskSnapshot,
) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["purpose"] = (
        "Score the answer using artifacts from a sequencing run, compare treatment "
        "conditions, and assess candidate genes."
    )

    rubric = parse_task_process_rubric(json.dumps(payload))

    assert validate_task_process_rubric(rubric, snapshot) == ()


def test_scientific_run_condition_and_candidate_ids_remain_allowed(
    snapshot: TaskSnapshot,
) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["purpose"] = (
        "Verify the mass spectrometry run ID, compare the experimental sample "
        "condition IDs, and report each molecular candidate ID from the evidence."
    )

    rubric = parse_task_process_rubric(json.dumps(payload))

    assert validate_task_process_rubric(rubric, snapshot) == ()


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

    assert "required summary anchor is not covered" in validation_text(
        payload, snapshot
    )


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

    assert "required_evidence contains duplicate items" in validation_text(
        payload, snapshot
    )


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

    assert "level points must be strictly descending" in validation_text(
        payload, snapshot
    )


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
    assert (
        first
        == """Purpose: Evaluate an evidence-grounded analysis process.

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
    )


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


def test_rendered_rubric_round_trip_rejects_runtime_context_independently(
    snapshot: TaskSnapshot,
) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["purpose"] = "Condition credit on the search history."
    rubric = parse_task_process_rubric(json.dumps(payload))

    with pytest.raises(ValueError, match="runtime/search context"):
        task_rubrics_module.validate_rendered_task_process_rubric(
            rubric,
            render_task_process_rubric(rubric),
        )


@pytest.mark.parametrize(
    "unsafe_identifier",
    (
        "current search run ID",
        "hill-climbing candidate ID",
        "experiment condition_id used for credit",
    ),
)
def test_rendered_rubric_rejects_contextual_search_identifiers_independently(
    snapshot: TaskSnapshot,
    unsafe_identifier: str,
) -> None:
    payload = valid_rubric_payload(snapshot)
    payload["purpose"] = f"Consult the {unsafe_identifier}."
    rubric = parse_task_process_rubric(json.dumps(payload))

    with pytest.raises(ValueError, match="runtime/search context"):
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


def test_required_content_and_hash_cannot_split_during_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = make_task(tmp_path)
    instruction = task / "instruction.md"
    mutated = mutate_after_target_fd_read(
        monkeypatch,
        instruction,
        lambda: instruction.write_text(
            "# Task\n\n## Question\n\nMUTATED QUESTION\n",
            encoding="utf-8",
        ),
    )

    with pytest.raises(ValueError, match="changed while being snapshotted"):
        build_task_snapshot(task)

    assert mutated == [True]


def test_data_hash_and_preview_cannot_split_during_snapshot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = make_task(tmp_path)
    data_file = task / "environment" / "data" / "gene_exp.diff"
    mutated = mutate_after_target_fd_read(
        monkeypatch,
        data_file,
        lambda: data_file.write_text(
            "mutated_column\tvalue\nMUTATED\t1\n",
            encoding="utf-8",
        ),
    )

    with pytest.raises(ValueError, match="changed while being snapshotted"):
        build_task_snapshot(task)

    assert mutated == [True]


def test_data_symlink_substitution_during_snapshot_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = make_task(tmp_path)
    data_file = task / "environment" / "data" / "gene_exp.diff"
    outside = tmp_path / "outside.tsv"
    outside.write_text("outside_column\tsecret\nLEAK\t1\n", encoding="utf-8")

    def substitute_symlink() -> None:
        data_file.unlink()
        data_file.symlink_to(outside)

    mutated = mutate_after_target_fd_read(
        monkeypatch,
        data_file,
        substitute_symlink,
    )

    with pytest.raises(ValueError, match="changed while being snapshotted"):
        build_task_snapshot(task)

    assert mutated == [True]


def test_task_config_replacement_after_validation_fails_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    task = make_task(tmp_path)
    outside = tmp_path / "outside-task.toml"
    outside.write_text('schema_version = "outside"\n', encoding="utf-8")
    original_validate = task_snapshots_module._validated_task_input
    substituted = [False]

    def substitute_after_validation(
        task_root: Path,
        relative_path: str,
        *,
        required: bool,
    ) -> Path | None:
        path = original_validate(task_root, relative_path, required=required)
        if relative_path == "task.toml" and path is not None:
            path.unlink()
            path.symlink_to(outside)
            substituted[0] = True
        return path

    monkeypatch.setattr(
        task_snapshots_module,
        "_validated_task_input",
        substitute_after_validation,
    )

    with pytest.raises(ValueError, match="regular, non-symlink file"):
        build_task_snapshot(task)

    assert substituted == [True]


def test_file_omitted_from_schema_preview_still_changes_snapshot_identity(
    tmp_path: Path,
) -> None:
    task = make_task(tmp_path)
    omitted = task / "environment" / "data" / "z_omitted.tsv"
    omitted.write_text("id\tvalue\n1\tbefore\n", encoding="utf-8")
    limits = SchemaSnapshotLimits(max_files=1)

    before = build_task_snapshot(task, limits)
    before_hashes = dict(before.input_hashes)
    omitted.write_text("id\tvalue\n1\tafter\n", encoding="utf-8")
    after = build_task_snapshot(task, limits)
    after_hashes = dict(after.input_hashes)

    assert [item.path for item in before.data_files] == ["gene_exp.diff"]
    assert "environment/data/z_omitted.tsv" in before_hashes
    assert before.omitted_data_files == 2
    assert (
        before_hashes["environment/data/z_omitted.tsv"]
        != after_hashes["environment/data/z_omitted.tsv"]
    )
    assert before.snapshot_sha256 != after.snapshot_sha256


@pytest.mark.parametrize(
    "relative_path",
    (Path("instruction.md"), Path("tests/rubric.txt")),
)
def test_required_task_input_symlinks_are_rejected(
    tmp_path: Path,
    relative_path: Path,
) -> None:
    task = make_task(tmp_path)
    required_path = task / relative_path
    outside_path = tmp_path / f"outside-{required_path.name}"
    outside_path.write_bytes(required_path.read_bytes())
    required_path.unlink()
    required_path.symlink_to(outside_path)

    with pytest.raises(ValueError, match="regular, non-symlink file"):
        build_task_snapshot(task)


def test_symlinked_required_input_parent_cannot_leak_outside_task(
    tmp_path: Path,
) -> None:
    task = make_task(tmp_path)
    rubric_path = task / "tests" / "rubric.txt"
    rubric_bytes = rubric_path.read_bytes()
    rubric_path.unlink()
    rubric_path.parent.rmdir()
    outside_tests = tmp_path / "outside-tests"
    outside_tests.mkdir()
    (outside_tests / "rubric.txt").write_bytes(rubric_bytes)
    (task / "tests").symlink_to(outside_tests, target_is_directory=True)

    with pytest.raises(ValueError, match="symlinked path component"):
        build_task_snapshot(task)


def test_optional_task_config_symlink_is_rejected(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    config_path = task / "task.toml"
    outside_config = tmp_path / "outside-task.toml"
    outside_config.write_bytes(config_path.read_bytes())
    config_path.unlink()
    config_path.symlink_to(outside_config)

    with pytest.raises(ValueError, match="regular, non-symlink file"):
        build_task_snapshot(task)


@pytest.mark.parametrize(
    "relative_path",
    (Path("instruction.md"), Path("tests/rubric.txt")),
)
def test_required_task_inputs_must_be_regular_files(
    tmp_path: Path,
    relative_path: Path,
) -> None:
    task = make_task(tmp_path)
    required_path = task / relative_path
    required_path.unlink()
    required_path.mkdir()

    with pytest.raises(ValueError, match="regular, non-symlink file"):
        build_task_snapshot(task)


def test_symlinked_task_directory_ancestor_is_rejected(tmp_path: Path) -> None:
    task = make_task(tmp_path / "real")
    alias_parent = tmp_path / "task-parent-alias"
    alias_parent.symlink_to(task.parent, target_is_directory=True)

    with pytest.raises(ValueError, match="symlinked path component"):
        build_task_snapshot(alias_parent / task.name)


def find_table(snapshot: TaskSnapshot, name: str) -> DataFileSnapshot:
    return next(
        data_file for data_file in snapshot.data_files if data_file.path == name
    )


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


def test_snapshot_sorts_nested_paths(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    data = task / "environment" / "data"
    (data / "z").mkdir()
    (data / "z" / "last.csv").write_text("id,value\nz,1\n", encoding="utf-8")
    (data / "a").mkdir()
    (data / "a" / "first.csv").write_text("id,value\na,1\n", encoding="utf-8")

    paths = [data_file.path for data_file in build_task_snapshot(task).data_files]

    assert paths == ["a/first.csv", "gene_exp.diff", "invalid.bin", "z/last.csv"]


@pytest.mark.parametrize("target_is_directory", (False, True))
def test_data_entry_symlinks_are_rejected(
    tmp_path: Path,
    target_is_directory: bool,
) -> None:
    task = make_task(tmp_path)
    data = task / "environment" / "data"
    if target_is_directory:
        target = data / "real-directory"
        target.mkdir()
        (target / "table.tsv").write_text("id\n1\n", encoding="utf-8")
    else:
        target = data / "gene_exp.diff"
    (data / "linked-entry").symlink_to(
        target,
        target_is_directory=target_is_directory,
    )

    with pytest.raises(ValueError, match="environment/data.*symlink"):
        build_task_snapshot(task)


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

    assert enumerated == 4
    assert files == ()
    assert truncated is True


def test_exact_entry_limit_inventories_and_hashes_every_file(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    limits = SchemaSnapshotLimits(max_entries_visited=2)

    snapshot = build_task_snapshot(task, limits)

    assert [data_file.path for data_file in snapshot.data_files] == [
        "gene_exp.diff",
        "invalid.bin",
    ]
    assert snapshot.data_traversal_truncated is False
    assert {
        path
        for path, _ in snapshot.input_hashes
        if path.startswith("environment/data/")
    } == {
        "environment/data/gene_exp.diff",
        "environment/data/invalid.bin",
    }


def test_exact_entry_limit_does_not_truncate_an_empty_directory(
    tmp_path: Path,
) -> None:
    task = make_task(tmp_path)
    (task / "environment" / "data" / "empty").mkdir()

    snapshot = build_task_snapshot(
        task,
        SchemaSnapshotLimits(max_entries_visited=3),
    )

    assert snapshot.data_traversal_truncated is False


def test_wide_directory_overflow_fails_closed_regardless_of_order(
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

    with pytest.raises(ValueError, match="data traversal exceeded.*6"):
        build_task_snapshot(task, limits)
    reverse_many = True
    with pytest.raises(ValueError, match="data traversal exceeded.*6"):
        build_task_snapshot(task, limits)


def test_default_entry_limit_rejects_a_partial_snapshot(tmp_path: Path) -> None:
    task = make_task(tmp_path)
    data = task / "environment" / "data"
    for index in range(300):
        (data / f"overflow-{index:03}.tsv").write_text(
            "id\n1\n",
            encoding="utf-8",
        )

    default_limit = SchemaSnapshotLimits().max_entries_visited
    with pytest.raises(
        ValueError,
        match=rf"data traversal exceeded.*{default_limit}",
    ):
        build_task_snapshot(task)


def test_stable_file_signature_includes_ctime_when_available() -> None:
    common = {
        "st_dev": 1,
        "st_ino": 2,
        "st_size": 3,
        "st_mtime_ns": 4,
    }

    before = SimpleNamespace(**common, st_ctime_ns=5)
    after = SimpleNamespace(**common, st_ctime_ns=6)

    assert task_snapshots_module._stable_file_signature(
        before,
    ) != task_snapshots_module._stable_file_signature(after)


def test_probe_is_byte_bounded_without_misclassifying_split_utf8(
    tmp_path: Path,
) -> None:
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


def test_table_probe_applies_row_column_example_and_string_limits(
    tmp_path: Path,
) -> None:
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
    schema_json = canonical_json(
        [data_file.to_dict() for data_file in snapshot.data_files]
    )

    assert len(schema_json) <= limits.max_output_chars
    assert json.loads(schema_json)
    assert [data_file.path for data_file in snapshot.data_files] == ["gene_exp.diff"]
    assert snapshot.data_files[0].examples == ()
    assert snapshot.data_files[0].columns == ()
    assert snapshot.data_files[0].omitted_examples == 13
    assert snapshot.data_files[0].omitted_columns == 5
    assert snapshot.omitted_data_files == 1


@pytest.mark.skipif(
    not REAL_DA_19_1.is_dir(), reason="real da-19-1 data is not checked in"
)
def test_real_da_19_1_snapshot_has_three_bounded_tables() -> None:
    snapshot = build_task_snapshot(REAL_DA_19_1)
    column_counts = {
        data_file.path: len(data_file.columns) for data_file in snapshot.data_files
    }
    schema_json = canonical_json(
        [data_file.to_dict() for data_file in snapshot.data_files]
    )

    assert snapshot.task_id == "da-19-1"
    assert column_counts == {
        "processed_data/rnaseq/cuffdiff/gene_exp.diff": 14,
        "processed_data/rnaseq/cuffdiff/run.info": 2,
        "processed_data/rnaseq/rnaseq_alignment_manifest.tsv": 6,
    }
    assert len(schema_json) <= SchemaSnapshotLimits().max_output_chars
    assert all("runs/" not in path for path, _ in snapshot.input_hashes)
