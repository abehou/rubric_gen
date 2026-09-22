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
        study.mkdir()
        studies[case.task_id] = study
        experiment = study / "experiments" / "case"
        request_root = experiment / "trace-defense-v2-requests"
        failed_request = request_root / case.failed_request_key
        assignment = {
            "assignment_id": case.assignment_id,
            "experiment_dir": "experiments/case",
            "status": "failed",
            "automatic_recovery_exhausted": True,
            "automatic_attempt_count": 1,
            "error_type": "RubricProposerProviderError",
            "error": (
                f"{next(request.stage for request in case.requests if request.request_key == case.failed_request_key)}: "
                f"provider failure at {failed_request}"
            ),
        }
        (study / "study.json").write_text(json.dumps({"records": [assignment]}))
        for request in case.requests:
            request_dir = request_root / request.request_key
            request_dir.mkdir(parents=True)
            for index, (error_type, error) in enumerate(
                request.expected_errors, start=1
            ):
                (request_dir / f"attempt-{index:03d}.json").write_text(
                    json.dumps(
                        {
                            "attempt": index,
                            "request_sha256": request.request_key,
                            "stage": request.stage,
                            "status": "provider_failure",
                            "permanent": False,
                            "error_type": error_type,
                            "error": error,
                        }
                    )
                )
    return module, studies


def test_inspect_and_rearm_exact_three_response_free_requests(tmp_path: Path) -> None:
    module, studies = fixture(tmp_path)
    inspected = module.inspect_all(studies=studies)
    assert len(inspected) == 2
    assert sum(len(case["requests"]) for case in inspected) == 3
    assert sum(
        len(request["attempts"])
        for case in inspected
        for request in case["requests"]
    ) == 12
    assert {case["provider_responses"] for case in inspected} == {0}

    recovered = module.rearm_all(studies=studies, stamp="fixture")
    assert len(recovered) == 2
    for case, result in zip(module.CASES, recovered, strict=True):
        assert all(
            not Path(request["request_dir"]).exists()
            for request in result["requests"]
        )
        assert len(result["archived_requests"]) == len(case.requests)
        assert all(Path(path).is_dir() for path in result["archived_requests"])
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
    request_spec = case.requests[0]
    request = (
        studies[case.task_id]
        / "experiments/case/trace-defense-v2-requests"
        / request_spec.request_key
    )
    attempt = request / "attempt-001.json"
    value = json.loads(attempt.read_text())
    value[damage] = {"text": "returned"}
    attempt.write_text(json.dumps(value))
    with pytest.raises(RuntimeError, match="response-free failure"):
        module.inspect_all(studies=studies)


def test_rearm_refuses_extra_incomplete_request(tmp_path: Path) -> None:
    module, studies = fixture(tmp_path)
    case = module.CASES[0]
    extra = (
        studies[case.task_id]
        / "experiments/case/trace-defense-v2-requests/extra"
    )
    extra.mkdir()
    (extra / "attempt-001.json").write_text("{}")
    discovered = module.discover_case(studies[case.task_id], case)
    assert [item["request_key"] for item in discovered["incomplete_requests"]] == [
        case.requests[0].request_key,
        case.requests[1].request_key,
        "extra",
    ]
    with pytest.raises(RuntimeError, match="unexpected incomplete request scope"):
        module.inspect_all(studies=studies)
