"""Load the three score stages used by the Results20 figures."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from rubric_gen.detection.targets import detection_target
from rubric_gen.submission_revision.evaluation.panel_bounds import detection_bounds


ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = ROOT.parents[1]
EXPERIMENT_ID = "biomnibench-da-factorial-r10-4f4d5d178756"
EVALUATION_ROOT = PROJECT_ROOT / "runs/detections" / EXPERIMENT_ID
STAGE_PATHS = (
    EVALUATION_ROOT / "rubric_score/summary.json",
    EVALUATION_ROOT / "absolute_score/summary.json",
    EVALUATION_ROOT / "pairwise_preference/summary.json",
)
DIRECT_STAGE_NAMES = ("direct_full", "direct_post_update")


def load_stage_assignments() -> tuple[list[dict[str, object]], str]:
    """Join completed stage summaries by assignment ID."""

    summaries = [json.loads(path.read_text(encoding="utf-8")) for path in STAGE_PATHS]
    if any(summary.get("status") != "completed" for summary in summaries):
        raise RuntimeError("one or more evaluation stages are incomplete")
    stage_maps = [_assignment_map(summary) for summary in summaries]
    assignment_ids = set(stage_maps[0])
    if any(set(stage) != assignment_ids for stage in stage_maps[1:]):
        raise RuntimeError("evaluation stages contain different assignments")

    rows: list[dict[str, object]] = []
    for assignment_id in sorted(assignment_ids):
        rubric, absolute, pairwise = (
            stage[assignment_id] for stage in stage_maps
        )
        absolute_scores = absolute["rubric_free_absolute_scores"]
        preference_scores = pairwise["pairwise_preference_scores"]
        reference_scores = rubric["reference_scores"]
        weak_scores = rubric["weak_original_rubric_scores"]
        assert isinstance(absolute_scores, dict)
        assert isinstance(preference_scores, dict)
        assert isinstance(reference_scores, dict)
        assert isinstance(weak_scores, dict)

        artifacts: dict[str, dict[str, float]] = {}
        for artifact in ("initial", "final"):
            original = reference_scores["original"]
            assert isinstance(original, dict)
            original_artifact = original[artifact]
            assert isinstance(original_artifact, dict)
            artifacts[artifact] = {
                "weak_original_rubric_score": float(weak_scores[artifact]),
                "strong_original_rubric_score": float(original_artifact["mean"]),
                "rubric_free_absolute_score": float(
                    absolute_scores[f"{artifact}_panel_mean"]
                ),
            }

        selected = reference_scores["selected"]
        holdout = reference_scores["holdout"]
        assert isinstance(selected, dict)
        assert isinstance(holdout, dict)
        rows.append({
            "assignment_id": assignment_id,
            "task_id": rubric["task_id"],
            "replicate": rubric["replicate"],
            "solver_id": rubric["solver_id"],
            "condition_id": rubric["condition_id"],
            "rubric_policy": rubric["rubric_policy"],
            "artifacts": artifacts,
            "reference_scores": reference_scores,
            "outcomes": {
                "original_rubric_weak_gain": (
                    artifacts["final"]["weak_original_rubric_score"]
                    - artifacts["initial"]["weak_original_rubric_score"]
                ),
                "selected_rubric_gain": (
                    float(selected["final"]["mean"])
                    - float(selected["initial"]["mean"])
                ),
                "holdout_rubric_gain": (
                    float(holdout["final"]["mean"])
                    - float(holdout["initial"]["mean"])
                ),
                "rubric_free_absolute_score_gain": (
                    artifacts["final"]["rubric_free_absolute_score"]
                    - artifacts["initial"]["rubric_free_absolute_score"]
                ),
                "pairwise_preference_score": float(preference_scores["panel_mean"]),
            },
        })
    return rows, _source_sha256()


def load_direct_assignments() -> tuple[dict[str, object], str]:
    """Join direct detector stages by their source manifests."""

    by_id: dict[str, dict[str, object]] = {}
    direct_paths = tuple(_direct_summary_path(name) for name in DIRECT_STAGE_NAMES)
    field_by_window = {
        "full_trajectory": "direct_detection",
        "post_update": "post_update_detection",
    }
    for path in direct_paths:
        summary = json.loads(path.read_text(encoding="utf-8"))
        source = summary.get("source")
        if not isinstance(source, dict) or source.get("window") not in field_by_window:
            raise RuntimeError(f"direct stage has an invalid window: {path}")
        models = tuple(str(model) for model in summary["models"])
        target = detection_target(str(summary["detection"]))
        panels: dict[str, dict[str, str]] = {}
        for record in summary["records"]:
            source_path = Path(str(record["source_path"]))
            manifest = json.loads((source_path / "manifest.json").read_text())
            assignment_id = str(manifest["assignment_id"])
            by_id.setdefault(assignment_id, {
                "assignment_id": assignment_id,
                "task_id": manifest["task_id"],
                "replicate": manifest["replicate"],
                "solver_id": manifest["solver_id"],
                "condition_id": manifest["condition_id"],
                "rubric_policy": manifest["rubric_policy"],
            })
            panel = panels.setdefault(assignment_id, {})
            verdict = record.get("verdict")
            if isinstance(verdict, dict) and "decision" in verdict:
                panel[str(record["provider"])] = str(verdict["decision"])
        field = field_by_window[str(source["window"])]
        if set(panels) != set(by_id):
            raise RuntimeError("direct stages contain different assignments")
        for assignment_id, decisions in panels.items():
            bounds = detection_bounds(
                decisions=decisions,
                models=models,
                positive_decision=target.positive_decision,
                negative_decision=target.negative_decision,
                rule=str(summary["primary_rule"]),
            )
            if bounds["identified"]:
                decision = "detected" if bounds["lower"] == 1 else "not_detected"
            elif bounds["abstaining_models"] and not bounds["missing_models"]:
                decision = "abstain"
            else:
                decision = "incomplete"
            by_id[assignment_id][field] = {
                "decision": decision,
                "bounds": bounds,
                "provider_decisions": decisions,
            }
    return {"assignments": list(by_id.values())}, _paths_sha256(direct_paths)


def _assignment_map(summary: dict[str, object]) -> dict[str, dict[str, object]]:
    assignments = summary.get("assignments")
    if not isinstance(assignments, list):
        raise RuntimeError("evaluation stage has no assignments")
    result = {
        str(assignment["assignment_id"]): assignment
        for assignment in assignments
        if isinstance(assignment, dict) and "assignment_id" in assignment
    }
    if len(result) != len(assignments):
        raise RuntimeError("evaluation stage has invalid assignment IDs")
    return result


def _source_sha256() -> str:
    return _paths_sha256(STAGE_PATHS)


def _direct_summary_path(stage_name: str) -> Path:
    paths = tuple((EVALUATION_ROOT / stage_name / "evaluations").glob("*/summary.json"))
    if len(paths) != 1:
        raise RuntimeError(f"expected one summary for {stage_name}, found {len(paths)}")
    return paths[0]


def _paths_sha256(paths: tuple[Path, ...]) -> str:
    digest = hashlib.sha256()
    for path in paths:
        digest.update(path.relative_to(EVALUATION_ROOT).as_posix().encode())
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()
