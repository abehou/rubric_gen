"""Private read-only completion gate; no API calls or artifact modifications."""
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from artifact_locations import recorded_root, verify_location

MODELS = {"gpt-5.6-sol", "claude-opus-5", "gemini-3.8-flash"}
WINDOWS = ("full_trajectory", "post_update", "final_artifact", "final_revision")


def _regular_within(root: Path, path: Path) -> Path:
    root = root.absolute()
    path = path.absolute()
    relative = path.relative_to(root)
    assert not root.is_symlink() and root.is_dir(), root
    current = root
    for part in relative.parts:
        assert part not in {".", ".."}, path
        current = current / part
        assert not current.is_symlink(), current
    assert path.is_file(), path
    return path


def check_semantic_records(root: Path, name: str, summary: dict) -> None:
    """Bind every reported semantic judgment to its plan and saved evidence."""
    instrument = {"absolute_score": "absolute", "pairwise_preference": "pairwise"}.get(name)
    jobs = [j for j in summary["predispatch_plan"]["jobs"]
            if instrument is None or j["instrument"] == instrument]
    expected = {j["semantic_key"]: j for j in jobs}
    assert len(expected) == len(jobs) == summary["planned_semantic_judgment_count"], name
    assert {r["judgment_key"] for r in summary["records"]} == set(expected), name
    paths = list((root / "records").glob("*.json"))
    assert {p.stem for p in paths} == set(expected), name
    saved = {}
    original_root = recorded_root(root.parent) / name
    for key, job in expected.items():
        assert key and Path(key).name == key and key not in {".", ".."}, key
        path = _regular_within(root, root / "records" / f"{key}.json")
        raw_bytes = path.read_bytes()
        raw = json.loads(raw_bytes)
        assert raw["model"] == job["model"] in MODELS, (name, key)
        if name == "rubric_score":
            for field in ("grading_identity", "answer_input_sha256", "review_input_sha256",
                          "rubric_sha256", "submission_content_sha256", "task_instruction_sha256"):
                assert raw[field] == job[field], (name, key, field)
            evaluation_path = root / Path(raw["evaluation_path"]).relative_to(original_root)
            validation_path = root / Path(raw["validation_path"]).relative_to(original_root)
            evaluation = json.loads(_regular_within(root, evaluation_path).read_text())
            validation = json.loads(_regular_within(root, validation_path).read_text())
            assert raw["score"] == validation["score"] == evaluation["total_score"], (name, key)
            for field, value in raw["grading_identity"].items():
                assert validation[field] == value, (name, key, field)
            assert validation["answer_input_sha256"] == raw["answer_input_sha256"], key
            assert validation["review_input_sha256"] == raw["review_input_sha256"], key
        else:
            assert hashlib.sha256(raw_bytes).hexdigest() == summary["completed_record_sha256s"][key], key
            assert raw["prompt_sha256"] == job["prompt_sha256"], key
            assert hashlib.sha256(raw["raw_response"].encode()).hexdigest() == raw["raw_response_sha256"], key
            assert raw["generation"]["requested_model"] == raw["model"], key
        saved[key] = raw
    # Assignment references may share one semantic judgment; compare their common
    # fields without incorrectly requiring one API call per assignment reference.
    for record in summary["records"]:
        raw = saved[record["judgment_key"]]
        for field in record.keys() & raw.keys():
            assert record[field] == raw[field], (name, record["judgment_key"], field)


def source_records(study: Path):
    ledger = json.loads((study / "study.json").read_text())
    if "execution_conditions" not in ledger:
        return ledger["records"]
    # Scoped collections retain the entire original ledger. Bind the declared
    # population to the explicit source config, never infer it from successes.
    from rubric_gen.submission_revision.experiment import load_experiment
    from rubric_gen.submission_revision.execution_scope import terminal_records
    experiment = load_experiment(Path(ledger["experiment_path"]))
    assert experiment.experiment_id == ledger["experiment_id"]
    return terminal_records(experiment, ledger)


def check(study: Path, audit: Path, *, expected_models=None):
    panel = MODELS if expected_models is None else set(expected_models)
    assert panel and panel <= MODELS
    verify_location(study)
    verify_location(audit)
    original_study = recorded_root(study)
    ledger = json.loads((study / "study.json").read_text())
    assignments = source_records(study)
    assert assignments and all(r["status"] == "completed" for r in assignments)
    ids = {r["assignment_id"] for r in assignments}
    assert len(ids) == len(assignments)
    paths = set()
    for record in assignments:
        relative = Path(record['experiment_dir'])
        assert not relative.is_absolute() and '..' not in relative.parts
        paths.add(str(original_study / relative))
    result = {"assignment_count": len(ids), "stages": {}, "semantic_judgments": 0,
              "audited_models": sorted(panel), "deferred_models": sorted(MODELS - panel)}
    for window in WINDOWS:
        name = f"direct_{window}"
        summaries = list((audit / name / "evaluations").glob("*/summary.json"))
        assert len(summaries) == 1, (name, "missing or ambiguous summary")
        summary = json.loads(summaries[0].read_text())
        assert set(summary["models"]) == panel
        assert summary["source"]["window"] == window
        assert summary["primary_rule"] == "any_detect"
        records = summary["records"]
        assert all(r["status"] in {"completed", "skipped"} for r in records), name
        observed = [(r["source_path"], r["model"]) for r in records]
        expected = {(p, m) for p in paths for m in panel}
        assert len(observed) == len(expected) and set(observed) == expected, name
        for record in records:
            # Current resume summaries mark validated cached successes "skipped";
            # they still require the exact underlying completed score artifact.
            score = summaries[0].parent / "cases" / record["case_id"] / record["model"] / "score.json"
            assert not score.is_symlink() and score.is_file(), name
            saved = json.loads(score.read_text())
            assert saved["status"] == "completed", name
            assert saved == {**record, "status": "completed"}, name
        result["stages"][name] = {
            "judgments": len(records),
            "by_model": dict(Counter(r["model"] for r in records)),
            # Abstention is a valid detector outcome, never a failed API call or no-RH.
            "decisions": dict(Counter(r["verdict"]["decision"] for r in records)),
        }
        result["semantic_judgments"] += len(records)
    for name in ("rubric_score", "absolute_score", "pairwise_preference"):
        summary = json.loads((audit / name / "summary.json").read_text())
        assert summary["status"] == "completed", name
        assert Path(summary["study_dir"]) == original_study, name
        assert set(summary["models"]) == panel
        assert not summary["missing_models"] and not summary["judge_failures"], name
        assert summary["failed_semantic_judgment_count"] == 0, name
        planned = summary["planned_semantic_judgment_count"]
        assert planned == summary["successful_semantic_judgment_count"], name
        assert planned == summary["used_semantic_judgment_count"], name
        assert summary["assignment_coverage"]["excluded_assignment_count"] == 0, name
        assert summary["assignment_coverage"]["evaluated_assignment_count"] == len(ids), name
        if "execution_conditions" in ledger:
            coverage = summary["assignment_coverage"]
            assert coverage["execution_conditions"] == ledger["execution_conditions"], name
            assert coverage["full_ledger_assignment_count"] == len(ledger["records"]), name
            assert coverage["out_of_scope_assignment_count"] == len(ledger["records"]) - len(ids), name
        assert {a["assignment_id"] for a in summary["assignments"]} == ids, name
        by_assignment = {aid: set() for aid in ids}
        for record in summary["records"]:
            by_assignment[record["assignment_id"]].add(record["model"])
        assert all(models == panel for models in by_assignment.values()), name
        check_semantic_records(audit / name, name, summary)
        result["stages"][name] = {"judgments": planned, "missing_models": []}
        result["semantic_judgments"] += planned
    return result


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("Supply study and audit directories")
    print(json.dumps(check(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve()), indent=2))
