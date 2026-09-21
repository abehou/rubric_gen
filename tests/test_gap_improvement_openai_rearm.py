from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


def recovery_module():
    path = (
        Path(__file__).resolve().parents[1]
        / "experiments/trace-v21-result40-gap-improvement/rearm_openai.py"
    )
    spec = importlib.util.spec_from_file_location("gap_openai_rearm", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    sys.path.insert(0, str(path.parent))
    try:
        spec.loader.exec_module(module)
    finally:
        sys.path.remove(str(path.parent))
    return module


def fixture(tmp_path: Path):
    module = recovery_module()
    studies = {}
    for case in module.CASES:
        study = tmp_path / case.task_id
        studies[case.task_id] = study
        experiment = study / "experiments" / "case"
        request = experiment / "trace-defense-v2-requests" / case.request_key
        request.mkdir(parents=True)
        assignment = {
            "assignment_id": case.assignment_id,
            "experiment_dir": "experiments/case",
            "status": "failed",
            "automatic_recovery_exhausted": True,
            "automatic_attempt_count": 1,
            "error_type": "RubricProposerProviderError",
            "error": f"{case.stage}: provider failure at {request}",
        }
        (study / "study.json").write_text(json.dumps({"records": [assignment]}))
        for index, (error_type, error) in enumerate(case.expected_errors, start=1):
            (request / f"attempt-{index:03d}.json").write_text(
                json.dumps(
                    {
                        "attempt": index,
                        "request_sha256": case.request_key,
                        "stage": case.stage,
                        "status": "provider_failure",
                        "permanent": False,
                        "error_type": error_type,
                        "error": error,
                    }
                )
            )
    return module, studies


def test_inspect_and_rearm_exact_two_response_free_failures(tmp_path: Path) -> None:
    module, studies = fixture(tmp_path)
    inspected = module.inspect_all(studies=studies)
    assert len(inspected) == 2
    assert sum(len(case["attempts"]) for case in inspected) == 8
    assert {case["provider_responses"] for case in inspected} == {0}

    recovered = module.rearm_all(studies=studies, stamp="fixture")
    assert len(recovered) == 2
    for case, result in zip(module.CASES, recovered, strict=True):
        assert not Path(result["request_dir"]).exists()
        assert Path(result["archived_request"]).is_dir()
        assert Path(result["assignment_failure"]["path"]).is_file()
        ledger = json.loads((studies[case.task_id] / "study.json").read_text())
        record = ledger["records"][0]
        assert record["status"] == "failed"
        assert record["automatic_recovery_exhausted"] is False
        assert record["automatic_attempt_count"] == 0


@pytest.mark.parametrize("damage", ("output", "response", "result"))
def test_rearm_refuses_any_returned_provider_material(
    tmp_path: Path, damage: str
) -> None:
    module, studies = fixture(tmp_path)
    case = module.CASES[0]
    request = (
        studies[case.task_id]
        / "experiments/case/trace-defense-v2-requests"
        / case.request_key
    )
    attempt = request / "attempt-001.json"
    value = json.loads(attempt.read_text())
    value[damage] = {"text": "returned"}
    attempt.write_text(json.dumps(value))
    with pytest.raises(RuntimeError, match="response-free failure"):
        module.inspect_all(studies=studies)


def test_rearm_refuses_extra_incomplete_request(tmp_path: Path) -> None:
    module, studies = fixture(tmp_path)
    case = module.CASES[1]
    extra = (
        studies[case.task_id]
        / "experiments/case/trace-defense-v2-requests/extra"
    )
    extra.mkdir()
    (extra / "attempt-001.json").write_text("{}")
    with pytest.raises(RuntimeError, match="unexpected incomplete request scope"):
        module.inspect_all(studies=studies)
