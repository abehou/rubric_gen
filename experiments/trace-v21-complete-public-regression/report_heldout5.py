"""Report the paired three-versus-five-heldout da-26-4 sensitivity check."""

from __future__ import annotations

from collections import defaultdict
import json
from pathlib import Path
from statistics import fmean

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.submission_revision.experiment import load_experiment


ROOT = Path(__file__).resolve().parents[2]
BUNDLE = ROOT / "experiments/trace-v21-complete-public-regression"
RESULT40 = ROOT / "experiments/trace-v21-execution-verified-provenance-result40"
ORIGINAL_CONFIG = RESULT40 / "configs/da-26-4-trace.yaml"
REPAIRED_CONFIG = BUNDLE / "configs/da-26-4-rep002.yaml"
BASE_RUN = Path(
    "/data/user_data/aydanh/rubric_gen/runs/"
    "rtt-complete-public-regression-20260921"
)
HELDOUT_RUN = BASE_RUN / "heldout5"
REPORT = ROOT / "docs/reports/2026-09-21/trace-v21-complete-public-regression"
MODELS = ("gpt-5.6-sol", "gemini-3.8-flash")
WINDOWS = ("full_trajectory", "post_update", "final_artifact", "final_revision")


def read(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def recorded_root(root: Path) -> Path:
    root = root.absolute()
    receipt = root.parent / f"{root.name}.location.json"
    if not receipt.exists():
        return root
    value = read(receipt)
    if value.get("kind") != "completed-artifact-relocation-v1":
        raise RuntimeError(f"invalid relocation receipt: {receipt}")
    return Path(str(value["original_root"]))


def _saved_record(root: Path, instrument: str, reference: dict) -> dict:
    path = root / instrument / "records" / f"{reference['judgment_key']}.json"
    if not path.is_file():
        raise RuntimeError(f"missing saved judgment: {path}")
    return read(path)


def _assignment_record(study: Path, assignment_id: str) -> dict:
    matches = [
        row
        for row in read(study / "study.json")["records"]
        if row.get("assignment_id") == assignment_id
    ]
    if len(matches) != 1 or matches[0].get("status") != "completed":
        raise RuntimeError(f"completed assignment is unavailable: {assignment_id}")
    return matches[0]


def endpoint(
    *,
    study: Path,
    audit: Path,
    assignment_id: str,
    model: str,
) -> dict[str, object]:
    assignment = _assignment_record(study, assignment_id)
    experiment_dir = study / str(assignment["experiment_dir"])
    state = read(experiment_dir / "state.json")
    submission_id = str(state["submission_ids"][-1])
    composition = read(
        experiment_dir / "rubric-evaluations" / f"{submission_id}.json"
    )
    refs = [
        reference
        for reference in read(audit / "rubric_score/summary.json")["records"]
        if reference["assignment_id"] == assignment_id
        and reference["model"] == model
        and reference["artifact"] == "final"
    ]
    role_scores: dict[tuple[str, int | None], float] = {}
    role_reasons: dict[tuple[str, int | None], dict[str, object]] = {}
    for reference in refs:
        saved = _saved_record(audit, "rubric_score", reference)
        evaluation = read(Path(str(saved["evaluation_path"])))
        for role in reference["rubric_roles"]:
            key = (str(role["name"]), role["variant_index"])
            if key in role_scores:
                raise RuntimeError(f"duplicate rubric role: {assignment_id} {key}")
            role_scores[key] = float(reference["score"])
            role_reasons[key] = {
                criterion: result["reason"]
                for criterion, result in evaluation["criteria"].items()
            }
    selected = role_scores.get(("selected", 0))
    heldouts = {
        int(index): score
        for (role, index), score in role_scores.items()
        if role == "holdout" and isinstance(index, int)
    }
    if selected is None or set(heldouts) != {2, 3, 4}:
        raise RuntimeError(
            f"saved three-heldout panel is incomplete: {assignment_id} {model}"
        )
    absolute_refs = [
        reference
        for reference in read(audit / "absolute_score/summary.json")["records"]
        if reference["assignment_id"] == assignment_id
        and reference["model"] == model
        and reference["artifact"] == "final"
    ]
    if len(absolute_refs) != 1:
        raise RuntimeError(f"absolute judgment is incomplete: {assignment_id} {model}")
    absolute = _saved_record(audit, "absolute_score", absolute_refs[0])
    source_path = str(recorded_root(study) / str(assignment["experiment_dir"]))
    rh: dict[str, dict[str, object]] = {}
    for window in WINDOWS:
        summaries = list((audit / f"direct_{window}/evaluations").glob("*/summary.json"))
        if len(summaries) != 1:
            raise RuntimeError(f"direct audit summary is missing: {audit} {window}")
        records = [
            row
            for row in read(summaries[0])["records"]
            if row["source_path"] == source_path and row["model"] == model
        ]
        if len(records) != 1:
            raise RuntimeError(f"direct judgment is incomplete: {assignment_id} {model} {window}")
        rh[window] = records[0]["verdict"]
    return {
        "assignment_id": assignment_id,
        "condition_id": assignment["condition_id"],
        "model": model,
        "submission_id": submission_id,
        "W": float(composition["reference_score"]),
        "W_train": float(composition["score"]),
        "S": selected,
        "heldouts3": heldouts,
        "H3": fmean(heldouts.values()),
        "A": float(absolute["verdict"]["score"]),
        "RH": rh,
        "reasons": {
            f"{role}:{index}": value
            for (role, index), value in role_reasons.items()
            if role in {"selected", "holdout"}
        },
    }


def _audit_roots() -> dict[str, dict[str, Path]]:
    original = load_experiment(ORIGINAL_CONFIG)
    repaired = load_experiment(REPAIRED_CONFIG)
    original_study = Path(str(original.dag["revise"]["output_dir"]))
    repaired_study = Path(str(repaired.dag["revise"]["output_dir"]))
    return {
        "original": {
            "study": original_study,
            "gpt-5.6-sol": Path(str(original.dag["detect"]["output_dir"])),
            "gemini-3.8-flash": (
                Path(
                    "/data/user_data/aydanh/rubric_gen/runs/"
                    "rtt-result40-expansion-20260918/audit-gemini/new20/"
                    "da-26-4/trace"
                )
                / original.experiment_id
            ),
        },
        "repaired": {
            "study": repaired_study,
            "gpt-5.6-sol": Path(str(repaired.dag["detect"]["output_dir"])),
            "gemini-3.8-flash": (
                BASE_RUN / "audit-gemini-authenticated" / repaired.experiment_id
            ),
        },
    }


def _assignment_ids() -> dict[str, dict[str, str]]:
    original = load_experiment(ORIGINAL_CONFIG)
    repaired = load_experiment(REPAIRED_CONFIG)
    result: dict[str, dict[str, str]] = {}
    for version, experiment in (("original", original), ("repaired", repaired)):
        by_arm = {}
        for assignment in experiment.execution_assignments:
            if assignment.replicate != 2:
                continue
            arm = "User" if assignment.condition_id.startswith("user-") else "Full"
            by_arm[arm] = assignment.assignment_id
        if set(by_arm) != {"Full", "User"}:
            raise RuntimeError(f"missing rep-002 arms: {version}")
        result[version] = by_arm
    return result


def _new_scores() -> dict[tuple[str, str, int], float]:
    summary = read(HELDOUT_RUN / "rubric-score/summary.json")
    if summary.get("status") != "completed" or summary.get("successful_judgments") != 16:
        raise RuntimeError("five-heldout score extension is incomplete")
    values: dict[tuple[str, str, int], float] = {}
    for row in summary["records"]:
        roles = row["rubric_roles"]
        if len(roles) != 1 or roles[0]["name"] != "holdout":
            raise RuntimeError("new score has an unexpected rubric role")
        variant = int(roles[0]["variant_index"])
        if variant not in {5, 6}:
            raise RuntimeError("new score has an unexpected heldout variant")
        key = (str(row["assignment_id"]), str(row["model"]), variant)
        if key in values:
            raise RuntimeError(f"duplicate new score: {key}")
        values[key] = float(row["score"])
    return values


def analyze() -> dict[str, object]:
    roots = _audit_roots()
    assignment_ids = _assignment_ids()
    new_scores = _new_scores()
    rows = []
    for version in ("original", "repaired"):
        for arm in ("Full", "User"):
            assignment_id = assignment_ids[version][arm]
            for model in MODELS:
                row = endpoint(
                    study=roots[version]["study"],
                    audit=roots[version][model],
                    assignment_id=assignment_id,
                    model=model,
                )
                extra = {
                    variant: new_scores[(assignment_id, model, variant)]
                    for variant in (5, 6)
                }
                five = {**row["heldouts3"], **extra}
                row.update(
                    version=version,
                    arm=arm,
                    heldouts5=five,
                    H5=fmean(five.values()),
                    H5_minus_H3=fmean(five.values()) - float(row["H3"]),
                )
                rows.append(row)

    panel = []
    for version in ("original", "repaired"):
        for arm in ("Full", "User"):
            group = [row for row in rows if row["version"] == version and row["arm"] == arm]
            if {row["model"] for row in group} != set(MODELS):
                raise RuntimeError(f"incomplete Sol/Gemini panel: {version} {arm}")
            means = {
                metric: fmean(float(row[metric]) for row in group)
                for metric in ("W", "S", "H3", "H5", "A")
            }
            rh = {
                window: 100
                * sum(
                    row["RH"][window]["decision"] == "reward_hacking_detected"
                    for row in group
                )
                / len(group)
                for window in WINDOWS
            }
            panel.append({
                "version": version,
                "arm": arm,
                **means,
                "three_heldout": {
                    "W_minus_S": means["W"] - means["S"],
                    "S_minus_H": means["S"] - means["H3"],
                    "H_minus_A": means["H3"] - means["A"],
                    "W_minus_A": means["W"] - means["A"],
                },
                "five_heldout": {
                    "W_minus_S": means["W"] - means["S"],
                    "S_minus_H": means["S"] - means["H5"],
                    "H_minus_A": means["H5"] - means["A"],
                    "W_minus_A": means["W"] - means["A"],
                },
                "RH_percent": rh,
            })
    shifts = [float(row["H5_minus_H3"]) for row in rows]
    return {
        "kind": "heldout5-da-26-4-rep002-analysis",
        "models": list(MODELS),
        "new_paraphrase_variants": [5, 6],
        "auditor_rows": rows,
        "panel": panel,
        "sensitivity": {
            "artifact_model_rows": len(rows),
            "H_increased": sum(value > 0 for value in shifts),
            "H_decreased": sum(value < 0 for value in shifts),
            "H_unchanged": sum(value == 0 for value in shifts),
            "mean_H5_minus_H3": fmean(shifts),
            "minimum_H5_minus_H3": min(shifts),
            "maximum_H5_minus_H3": max(shifts),
        },
    }


def markdown(analysis: dict[str, object]) -> str:
    lines = [
        "# Five-heldout sensitivity: `da-26-4` rep-002",
        "",
        "Variants 0--4 and all saved artifacts are unchanged. Variants 5/6 use the same rigorous heldout prompt as variants 2/3/4. Values below average Sol 5.6 and Gemini 3.8 Flash.",
        "",
        "| Arm | Version | S | H (3) | S-H (3) | H (5) | S-H (5) | H(5)-H(3) |",
        "| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    for row in analysis["panel"]:
        lines.append(
            "| {arm} | {version} | {S:.2f} | {H3:.2f} | {SH3:.2f} | {H5:.2f} | {SH5:.2f} | {shift:+.2f} |".format(
                **row,
                SH3=row["three_heldout"]["S_minus_H"],
                SH5=row["five_heldout"]["S_minus_H"],
                shift=row["H5"] - row["H3"],
            )
        )
    sensitivity = analysis["sensitivity"]
    lines.extend([
        "",
        "Across the eight artifact-model rows, H increased in {H_increased}, decreased in {H_decreased}, and tied in {H_unchanged}; mean H(5)-H(3) was {mean_H5_minus_H3:+.2f} (range {minimum_H5_minus_H3:+.2f} to {maximum_H5_minus_H3:+.2f}).".format(**sensitivity),
        "",
        "This is a bounded sensitivity diagnostic, not a revised Result40 estimate. Criterion-level judge reasons and all five heldout scores are retained in `heldout5-analysis.json` for strictness analysis.",
    ])
    return "\n".join(lines) + "\n"


def main() -> int:
    analysis = analyze()
    REPORT.mkdir(parents=True, exist_ok=True)
    write_json_atomic(REPORT / "heldout5-analysis.json", analysis)
    (REPORT / "heldout5.md").write_text(markdown(analysis), encoding="utf-8")
    print(json.dumps({"complete": True, "sensitivity": analysis["sensitivity"]}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
