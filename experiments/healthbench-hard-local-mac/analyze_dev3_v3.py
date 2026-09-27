"""Report saved HealthBench Dev3 endpoints and raw per-revision W scores offline."""

from collections import Counter, defaultdict
import argparse
import json
from pathlib import Path
from statistics import mean

from rubric_gen.submission_revision.experiment import load_experiment


ROOT = Path(__file__).resolve().parents[2]
CONFIG = Path(__file__).with_name("dev3-v3.yaml")
RUN = ROOT / "runs/healthbench-hard-local-mac-20260925-v3"


def read(path: Path) -> dict:
    return json.loads(path.read_text())


def analyze(config: Path = CONFIG) -> dict:
    experiment = load_experiment(config)
    run = Path(experiment.payload["dag"]["seed"]["output_dir"]).parent
    study_dir = run / "studies" / experiment.experiment_id
    audit_dir = run / "audits" / experiment.experiment_id
    study = read(study_dir / "study.json")
    expected = len(experiment.assignments)
    if len(study["records"]) != expected or any(
        row["status"] != "completed" for row in study["records"]
    ):
        raise RuntimeError("study coverage is incomplete")
    summaries = {
        name: read(audit_dir / name / "summary.json")
        for name in ("rubric_score", "absolute_score", "pairwise_preference")
    }
    for summary in summaries.values():
        if (
            summary["status"] != "completed"
            or summary["successful_semantic_judgment_count"] != summary["planned_semantic_judgment_count"]
            or summary["assignment_coverage"]["evaluated_assignment_count"] != expected
        ):
            raise RuntimeError("audit coverage is incomplete")
    rubric = {row["assignment_id"]: row for row in summaries["rubric_score"]["assignments"]}
    absolute = {row["assignment_id"]: row for row in summaries["absolute_score"]["assignments"]}
    windows = {}
    for name in ("full_trajectory", "final_artifact", "post_update", "final_revision"):
        paths = list((audit_dir / f"direct_{name}").rglob("summary.json"))
        if len(paths) != 1:
            raise RuntimeError(f"{name} audit summary is missing or duplicated")
        data = read(paths[0])
        if len(data["records"]) != expected or any(row["status"] != "completed" for row in data["records"]):
            raise RuntimeError(f"{name} audit coverage is incomplete")
        windows[name] = {row["source_path"]: row["verdict"]["decision"] for row in data["records"]}

    rows = []
    for record in study["records"]:
        path = study_dir / record["experiment_dir"]
        state = read(path / "state.json")
        scores = [
            read(path / "rubric-evaluations" / f"{submission}.json")["reference_score"]
            for submission in state["submission_ids"]
        ]
        scores = (scores + [scores[-1]] * 4)[:4]
        composite = [read(path / "rubric-evaluations" / f"{submission}.json")["score"]
                     for submission in state["submission_ids"]]
        composite = (composite + [composite[-1]] * 4)[:4]
        refs = rubric[record["assignment_id"]]["reference_scores"]
        endpoint = {}
        for phase in ("initial", "final"):
            endpoint[phase] = {
                "W": scores[0 if phase == "initial" else -1],
                "S": refs["selected"][phase]["mean"],
                "H": refs["holdout"][phase]["mean"],
                "A": absolute[record["assignment_id"]]["rubric_free_absolute_scores"][phase + "_panel_mean"],
            }
            if refs["holdout"][phase]["variant_count"] != 3:
                raise RuntimeError("expected exactly three heldout rubric variants")
            endpoint[phase].update({
                "W-S": endpoint[phase]["W"] - endpoint[phase]["S"],
                "S-H": endpoint[phase]["S"] - endpoint[phase]["H"],
                "H-A": endpoint[phase]["H"] - endpoint[phase]["A"],
            })
        source = str(path.resolve())
        rows.append({
            "assignment_id": record["assignment_id"],
            "condition_id": record["condition_id"],
            "task_id": record["task_id"],
            "replicate": record["replicate"],
            "W_curve": scores,
            "composite_curve": composite,
            "changed_snapshots": len(state["submission_ids"]),
            "initial": endpoint["initial"],
            "final": endpoint["final"],
            "full_trajectory_RH": windows["full_trajectory"][source],
            "final_artifact_RH": windows["final_artifact"][source],
        })
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["condition_id"]].append(row)
    conditions = []
    for condition, members in sorted(grouped.items()):
        conditions.append({
            "condition": condition,
            "n": len(members),
            "initial": {key: mean(row["initial"][key] for row in members) for key in members[0]["initial"]},
            "final": {key: mean(row["final"][key] for row in members) for key in members[0]["final"]},
            "W_curve": [mean(row["W_curve"][turn] for row in members) for turn in range(4)],
            "composite_curve": [mean(row["composite_curve"][turn] for row in members) for turn in range(4)],
            "W_steps": [dict(Counter(
                "improved" if row["W_curve"][turn] > row["W_curve"][turn-1]
                else "regressed" if row["W_curve"][turn] < row["W_curve"][turn-1]
                else "unchanged" for row in members
            )) for turn in range(1, 4)],
            "full_trajectory_RH": dict(Counter(row["full_trajectory_RH"] for row in members)),
            "final_artifact_RH": dict(Counter(row["final_artifact_RH"] for row in members)),
        })
    return {
        "experiment_id": experiment.experiment_id,
        "run_dir": str(run),
        "score_definition": "W online selected-base; S independent GPT-6 Luna selected; H mean of three heldout variants; A rubric-free GPT-6 Luna. Raw W curve uses carry-forward when a turn saved no new answer.",
        "conditions": conditions,
        "assignments": rows,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--experiment", type=Path, default=CONFIG)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = analyze(args.experiment)
    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({key: value for key, value in result.items() if key != "assignments"}, indent=2))
