"""Read saved final public artifacts and original outcome rationales; no model calls."""
from __future__ import annotations

import json
from pathlib import Path

from report_dev3_outcomes import BUNDLE, reconstruct

ROOT = BUNDLE.parents[1]
REPORT = ROOT / "docs/reports/2026-09-11/trace-attack-defense-v3"


def learning_evidence():
    """Small saved-record supplement: admission witnesses and realized prompts."""
    from collections import Counter

    forensic = json.loads((REPORT / "stress-v32-user-forensics.json").read_text())
    evidence = []
    for case in forensic["cases"]:
        root = Path(case["v3"]["case"]["root"])
        item = {"task_id": case["task_id"], "replicate": case["replicate"],
                "root": str(root), "generations": [], "quality_requests": Counter(),
                "realized_prompts": []}
        for generation in case["v3"]["case"]["learning"]["generations"]:
            directory = Path(generation["path"])
            proposal = json.loads((directory / "criterion-proposal.json").read_text())
            evolution = json.loads((directory / "evolution.json").read_text())
            admitted = set(generation["admitted_ids"])
            validation = json.loads((directory / "criterion-validation.json").read_text())
            item["generations"].append({"path": str(directory), "evolution": evolution,
                "selection": proposal["selection"],
                "proposals": proposal["criteria"], "admitted_ids": generation["admitted_ids"],
                "admitted_reviews": [r for r in validation["reviews"] if r["criterion_id"] in admitted]})
        for path in (root / "trace-defense-v2-requests").glob("*/result.json"):
            result = json.loads(path.read_text())
            if result["request"]["stage"] == "quality":
                value = result["outcome"].get("value")
                item["quality_requests"]["no_response" if value is None else
                    "ordered" if value["preferred_artifact_id"] is not None else "null"] += 1
        for turn in case["v3"]["turns"]:
            if turn["has_solver_prompt"]:
                path = Path(turn["solver_prompt_path"])
                item["realized_prompts"].append({"path": str(path), "text": path.read_text()})
        for name in ("instruction.md", "answer.txt", "trace.md"):
            path = root / "submissions/s000/workspace" / name
            if path.is_file():
                item["initial_" + name] = {"path": str(path), "text": path.read_text()}
        evidence.append(item)
    target = BUNDLE / "stress-v32-learning-review-inputs.json"
    target.write_text(json.dumps({"provider_calls": 0, "cases": evidence}, indent=2) + "\n")
    print(json.dumps({"output": str(target), "cases": len(evidence)}))


def first_iteration_learning():
    from forensic_stress_v31 import collect_learning

    forensic = json.loads((REPORT / "stress-user-forensics.json").read_text())
    cases = []
    for case in forensic["cases"]:
        root = Path(case["v3"]["case"]["root"])
        learning = collect_learning(root)
        # Large margin matrices already remain in the original generation records.
        learning.pop("generations")
        cases.append({"task_id": case["task_id"], "replicate": case["replicate"],
                      "root": str(root), **learning})
    target = REPORT / "stress-iteration1-learning-summary.json"
    target.write_text(json.dumps({"provider_calls": 0, "cases": cases}, indent=2) + "\n")
    print(json.dumps({"output": str(target), "cases": len(cases)}))


def main():
    forensic = json.loads((REPORT / "stress-v32-user-forensics.json").read_text())
    rows = []
    for flavor, folder, prefix in (("v21", "stress", "v21-control"),
                                    ("v3", "stress-v32", "v32-candidate")):
        for task in ("da-15-1", "da-13-6", "da-18-5"):
            _, _, values = reconstruct(BUNDLE / folder / f"{prefix}-{task}.yaml")
            for value in values:
                quality_path = Path(value["quality_path"])
                value["quality_verdict"] = json.loads(quality_path.read_text())["verdict"]
                value["flavor"] = flavor
                rows.append(value)
    cases = []
    for case in forensic["cases"]:
        item = {"task_id": case["task_id"], "replicate": case["replicate"]}
        for flavor in ("v21", "v3"):
            record = case[flavor]["case"]
            root = Path(record["root"])
            sid = record["state"]["submission_ids"][-1]
            public = {}
            for name in ("answer.txt", "trace.md"):
                path = root / "submissions" / sid / "workspace" / name
                public[name] = {"path": str(path), "text": path.read_text()}
            item[flavor] = {"public": public, "rows": [r for r in rows
                if r["flavor"] == flavor and r["task_id"] == case["task_id"]
                and int(r["replicate"]) == int(case["replicate"])]}
        cases.append(item)
    # This local read-only review copy is not a replacement scientific artifact.
    # Original public bytes and audit records remain in their recorded NFS roots.
    target = BUNDLE / "stress-v32-review-inputs.json"
    target.write_text(json.dumps({"provider_calls": 0, "cases": cases}, indent=2) + "\n")
    print(json.dumps({"output": str(target), "cases": len(cases), "audit_rows": len(rows)}))


if __name__ == "__main__":
    main()
