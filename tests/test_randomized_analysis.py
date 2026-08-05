from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

import rubric_gen.biomnibench.analysis as analysis_module
from rubric_gen.biomnibench.analysis import analyze_study
from rubric_gen.biomnibench.experiments import ExperimentDesign
from rubric_gen.biomnibench.forensics.protocol import outcome_audit_protocol


DESIGN_SHA = "d" * 64


def _design(root: Path) -> ExperimentDesign:
    conditions = [
        {
            "condition_id": f"{prompt}--{rubric}",
            "prompt": prompt,
            "rubric_evolution": rubric,
        }
        for prompt in ("base", "anti-rh")
        for rubric in ("static", "prospective")
    ]
    assignments: list[dict[str, object]] = []
    execution = 0
    for task_index in range(1, 4):
        for replicate in range(1, 4):
            for within, condition in enumerate(conditions, 1):
                execution += 1
                task_id = f"da-{task_index}-1"
                condition_id = str(condition["condition_id"])
                assignments.append({
                    "assignment_id": (
                        f"{task_id}--rep-{replicate:03d}--{condition_id}"
                    ),
                    "task_id": task_id,
                    "replicate": replicate,
                    "condition_id": condition_id,
                    "within_block_order": within,
                    "execution_order": execution,
                })
    return ExperimentDesign(
        root / "design.json",
        {
            "design_sha256": DESIGN_SHA,
            "protocol_id": "analysis-protocol",
            "conditions": conditions,
            "assignments": assignments,
            "protocol": {
                "revision_rounds": 10,
                "prompt_treatment": "anti-rh",
            },
            "analysis": {
                "primary_outcome": "final-trajectory-reward-hacking",
                "primary_rule": "majority",
            },
            "outcome_audit": outcome_audit_protocol(primary_rule="majority"),
        },
    )


def _files(root: Path, design: ExperimentDesign) -> tuple[Path, Path]:
    study = root / "study"
    study.mkdir()
    records: list[dict[str, object]] = []
    audit_records: list[dict[str, object]] = []
    models = list(design.outcome_audit["models"])
    for assignment in design.assignments:
        relative = (
            Path("experiments")
            / str(assignment["task_id"])
            / f"rep-{int(assignment['replicate']):03d}"
            / str(assignment["condition_id"])
        )
        experiment = study / relative
        experiment.mkdir(parents=True)
        records.append({
            "assignment_id": assignment["assignment_id"],
            "task_id": assignment["task_id"],
            "replicate": assignment["replicate"],
            "condition_id": assignment["condition_id"],
            "execution_order": assignment["execution_order"],
            "status": "completed",
            "experiment_dir": str(relative),
        })
        positive = str(assignment["condition_id"]).startswith("anti-rh--")
        decision = (
            "reward_hacking_detected"
            if positive
            else "no_reward_hacking_detected"
        )
        for model in models:
            audit_records.append({
                "case_id": "revision-" + hashlib.sha256(
                    f"{design.sha256}\0{assignment['assignment_id']}".encode()
                ).hexdigest()[:20],
                "source_path": str(experiment.resolve()),
                "source_kind": "revision",
                "model": model,
                "provider": model,
                "status": "completed",
                "verdict": {"decision": decision},
            })
    (study / "study.json").write_text(json.dumps({
        "schema_version": 1,
        "kind": "rubric-gen-randomized-revision-study",
        "status": "completed",
        "design_path": str(design.path),
        "design_sha256": design.sha256,
        "protocol_id": design.protocol_id,
        "seed_run_dir": str(root / "seeds"),
        "records": records,
    }))
    locked = design.outcome_audit
    provenance = {
        "audit_protocol_version": locked["protocol_version"],
        "detection": "rh",
        "models": models,
        "max_retries": locked["max_retries"],
        "max_input_tokens": locked["max_input_tokens"],
        "max_output_tokens": locked["max_output_tokens"],
        "max_event_text_chars": locked["max_event_text_chars"],
        "max_command_output_chars": locked["max_command_output_chars"],
        "max_cost_usd": locked["max_cost_usd"],
        "execution": locked["execution"],
        "primary_rule": locked["primary_rule"],
        "design_sha256s": [design.sha256],
        "openai_reasoning_effort": locked["openai_reasoning_effort"],
        "openai_text_verbosity": locked["openai_text_verbosity"],
        "anthropic_effort": locked["anthropic_effort"],
        "gemini_thinking_level": locked["gemini_thinking_level"],
        "prompt_cache": locked["prompt_cache"],
    }
    audit = root / "audit.json"
    audit.write_text(json.dumps({
        "schema_version": 7,
        "kind": "malt-model-judges",
        "detection": "rh",
        "primary_rule": "majority",
        "max_retries": locked["max_retries"],
        "design_sha256s": [design.sha256],
        "models": models,
        "run_provenance": provenance,
        "cost": {
            "observed_api_usd": 1.0,
            "observed_by_model_usd": {model: 1.0 / len(models) for model in models},
        },
        "records": audit_records,
    }))
    return study, audit


def test_analysis_uses_task_clusters_and_locked_audit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    design = _design(tmp_path)
    study, audit = _files(tmp_path, design)
    monkeypatch.setattr(
        analysis_module, "validate_completed_revision", lambda *_args: None
    )

    result = analyze_study(design, study, audit, tmp_path / "analysis.json")

    assert result["observed_count"] == 36
    assert result["cell_rates"]["base--static"]["rate"] == 0.0
    assert result["cell_rates"]["anti-rh--static"]["rate"] == 1.0
    prompt_effect = result["factorial_contrasts"]["prompt_main_effect"]
    assert prompt_effect["effect"] == 1.0
    assert prompt_effect["complete_task_clusters"] == 3


def test_analysis_rejects_audit_protocol_drift(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    design = _design(tmp_path)
    study, audit = _files(tmp_path, design)
    payload = json.loads(audit.read_text())
    payload["run_provenance"]["openai_reasoning_effort"] = "high"
    audit.write_text(json.dumps(payload))
    monkeypatch.setattr(
        analysis_module, "validate_completed_revision", lambda *_args: None
    )

    with pytest.raises(ValueError, match="openai_reasoning_effort"):
        analyze_study(design, study, audit, tmp_path / "analysis.json")


def test_analysis_rejects_redirected_study_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    design = _design(tmp_path)
    study, audit = _files(tmp_path, design)
    manifest_path = study / "study.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["records"][0]["experiment_dir"] = "experiments/redirected"
    manifest_path.write_text(json.dumps(manifest))
    monkeypatch.setattr(
        analysis_module, "validate_completed_revision", lambda *_args: None
    )

    with pytest.raises(RuntimeError, match="record identity"):
        analyze_study(design, study, audit, tmp_path / "analysis.json")


def test_analysis_rejects_reassigned_audit_case(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    design = _design(tmp_path)
    study, audit = _files(tmp_path, design)
    payload = json.loads(audit.read_text())
    payload["records"][0]["case_id"] = "revision-00000000000000000000"
    audit.write_text(json.dumps(payload))
    monkeypatch.setattr(
        analysis_module, "validate_completed_revision", lambda *_args: None
    )

    with pytest.raises(ValueError, match="audit record identity"):
        analyze_study(design, study, audit, tmp_path / "analysis.json")
