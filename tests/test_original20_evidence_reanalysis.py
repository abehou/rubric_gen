from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
BUNDLE = ROOT / "experiments/trace-v21-complete-public-regression"


def load(name: str, filename: str):
    sys.path.insert(0, str(BUNDLE))
    try:
        spec = spec_from_file_location(name, BUNDLE / filename)
        assert spec is not None and spec.loader is not None
        module = module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(BUNDLE))


def test_original20_case_plan_is_exact_and_condition_balanced():
    module = load("original20_evidence_test", "original20_evidence.py")

    assert len(module.TASKS) == 20
    assert len(set(module.TASKS)) == 20
    assert module.case_plan("da-10-1", 1) == (
        ("static", "Full"),
        ("static", "User"),
        ("trace", "Full"),
        ("trace", "User"),
    )


def test_original20_panel_summary_does_not_require_control_score():
    module = load(
        "evidence_calibrated_panel_original20_test",
        "run_evidence_calibrated_panel.py",
    )
    identity = {
        "task_id": "da-10-1",
        "arm": "Full",
        "replicate": 1,
        "model": "gpt-5.6-sol",
        "role": "static",
        "control_score": None,
    }
    summary = module.summarize([{
        "identity": identity,
        "records": {
            "score": 42,
            "evaluation": {"criteria": {}},
            "usage": {},
        },
        "elapsed_seconds": 1.0,
        "attempt": 1,
    }])

    assert summary["rows"][0]["evidence_calibrated_score"] == 42
    assert summary["rows"][0]["score_change"] is None
