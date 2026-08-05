"""Create treatment-blind human-review packets with a separate decoding key."""

from __future__ import annotations

import hashlib
import json
import os
import random
import re
from pathlib import Path

from rubric_gen.biomnibench.experiments import ExperimentDesign
from rubric_gen.biomnibench.study import (
    inspect_study,
    resolve_study_experiment,
    validate_completed_revision,
)
from rubric_gen.biomnibench.utils.hashing import sha256_file
from rubric_gen.biomnibench.utils.serialization import write_json_atomic


def export_blinded_review(
    design: ExperimentDesign,
    study_dir: Path,
    output_dir: Path,
    key_output: Path,
) -> int:
    root = output_dir.resolve()
    key_path = key_output.resolve()
    study_root = study_dir.resolve()
    if os.path.lexists(root):
        raise FileExistsError(f"review output already exists: {root}")
    if os.path.lexists(key_path):
        raise FileExistsError(f"review key already exists: {key_path}")
    if key_path == root or root in key_path.parents:
        raise ValueError("the private decoding key must be outside the review packet")
    study = json.loads((study_root / "study.json").read_text(encoding="utf-8"))
    if study.get("design_sha256") != design.sha256:
        raise ValueError("study does not match the design")
    health = inspect_study(study_root, design)
    if study.get("status") != "completed" or not health.complete:
        raise ValueError(
            "blinded review requires a completed, integrity-valid study"
        )
    records = study.get("records")
    seed_value = study.get("seed_run_dir")
    if not isinstance(records, list) or type(seed_value) is not str:
        raise ValueError("study records are invalid")
    seed_root = Path(seed_value).resolve()
    assignments = {
        str(item["assignment_id"]): item for item in design.assignments
    }
    root.mkdir(parents=True)
    cases: list[dict[str, object]] = []
    key_rows: list[dict[str, object]] = []
    template_lines: list[str] = []
    for record in records:
        if not isinstance(record, dict) or record.get("status") != "completed":
            raise ValueError("completed study contains a non-completed record")
        assignment = assignments.get(str(record.get("assignment_id")))
        if assignment is None:
            raise ValueError("study record is absent from design")
        experiment = resolve_study_experiment(study_root, record, assignment)
        rounds = int(design.protocol["revision_rounds"])
        validate_completed_revision(
            experiment,
            assignment,
            design,
            seed_root,
        )
        case_id = "case-" + hashlib.sha256(
            f"{design.sha256}\0{assignment['assignment_id']}\0human-review".encode()
        ).hexdigest()[:20]
        case_dir = root / "cases" / case_id
        case_dir.mkdir(parents=True)
        task_dir = design.task_dir(str(assignment["task_id"]))
        task_id = str(assignment["task_id"])
        condition_id = str(assignment["condition_id"])

        def blinded_text(value: str) -> str:
            redacted = re.sub(
                rf"(?i)(?<![A-Za-z0-9]){re.escape(task_id)}(?![A-Za-z0-9])",
                "[TASK_ID]",
                value,
            )
            return re.sub(
                rf"(?i)(?<![A-Za-z0-9]){re.escape(condition_id)}(?![A-Za-z0-9])",
                "[CONDITION]",
                redacted,
            )

        (case_dir / "instruction.md").write_text(
            blinded_text((task_dir / "instruction.md").read_text(encoding="utf-8")),
            encoding="utf-8",
        )
        initial = experiment / "submissions" / "s000" / "workspace"
        final = experiment / "submissions" / f"s{rounds:03d}" / "workspace"
        rng = random.Random(int.from_bytes(hashlib.sha256(case_id.encode()).digest()[:8], "big"))
        order = ["initial", "final"]
        rng.shuffle(order)
        sources = {"initial": initial, "final": final}
        positions: dict[str, str] = {}
        for label, source_name in zip(("A", "B"), order, strict=True):
            positions[source_name] = label
            for artifact in ("answer.txt", "trace.md"):
                source = sources[source_name] / artifact
                if source.is_symlink() or not source.is_file():
                    raise RuntimeError(f"missing review artifact: {source}")
                (case_dir / f"{artifact.removesuffix('.txt').removesuffix('.md')}-{label}.txt").write_text(
                    blinded_text(source.read_text(encoding="utf-8", errors="replace")),
                    encoding="utf-8",
                )
        hashes = {
            path.name: sha256_file(path)
            for path in sorted(case_dir.iterdir())
            if path.is_file()
        }
        cases.append({"case_id": case_id, "artifact_sha256": hashes})
        key_rows.append({
            "case_id": case_id,
            "assignment_id": assignment["assignment_id"],
            "task_id": assignment["task_id"],
            "replicate": assignment["replicate"],
            "condition_id": assignment["condition_id"],
            "initial_position": positions["initial"],
            "final_position": positions["final"],
            "experiment_dir": str(experiment),
        })
        template_lines.append(json.dumps({
            "case_id": case_id,
            "adjudicator_id": "",
            "preferred_answer": "abstain",
            "reward_hacking_detected": None,
            "confidence": None,
            "notes": "",
        }, sort_keys=True))
    write_json_atomic(root / "manifest.json", {
        "schema_version": 1,
        "kind": "rubric-gen-blinded-human-review-packet",
        "design_sha256": design.sha256,
        "blinding": (
            "manifest treatment metadata, solver model, explicit score history, "
            "structured feedback, revision order, and rubric policy withheld; "
            "known exact task and condition identifiers redacted from artifacts"
        ),
        "cases": cases,
    })
    (root / "labels-template.jsonl").write_text(
        "\n".join(template_lines) + ("\n" if template_lines else ""),
        encoding="utf-8",
    )
    write_json_atomic(key_path, {
        "schema_version": 1,
        "kind": "rubric-gen-private-human-review-key",
        "design_sha256": design.sha256,
        "cases": key_rows,
    })
    return len(cases)
