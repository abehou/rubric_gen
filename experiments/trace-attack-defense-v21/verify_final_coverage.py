"""Provider-free verification of the completed v2.1 audit cohort."""
from __future__ import annotations

import json
from pathlib import Path

from prepare import RUN


def main() -> None:
    study = Path("/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20/study/biomnibench-da-factorial-r10-5115fffdd1c0")
    completion = json.loads((RUN / "completion.json").read_text())
    experiment_id = completion["experiment_id"]
    audit = RUN / "audit" / experiment_id
    import sys
    sys.path.insert(0, str(Path("scripts/diagnostics").resolve()))
    from check_audit_coverage import check

    coverage = check(study, audit, expected_models=("gpt-5.6-sol", "claude-opus-5"))
    if not completion.get("success") or completion.get("coverage") != coverage:
        raise RuntimeError("saved completion receipt does not match current coverage")
    receipt = {
        "kind": "provider_free_final_audit_coverage_verification",
        "study": str(study),
        "audit": str(audit),
        "completion_receipt": str(RUN / "completion.json"),
        "coverage": coverage,
        "direct_windows_complete": all(
            coverage["stages"][f"direct_{window}"]["judgments"] == 240
            for window in ("full_trajectory", "post_update", "final_artifact", "final_revision")
        ),
        "no_provider_calls": True,
    }
    out = RUN / "final-coverage-verification.json"
    out.write_text(json.dumps(receipt, indent=2) + "\n")
    print(json.dumps(receipt, indent=2))


if __name__ == "__main__":
    main()
