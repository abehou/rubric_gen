"""Verify the all-case supplemental audit and compare it with preserved Luna A."""

import json
from collections import defaultdict
from pathlib import Path
from statistics import mean

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.runtime.process_environment import install_controlled_process_environment
from rubric_gen.submission_revision.evaluation.absolute_score import validate_verdict
from usage_snapshot import snapshot

install_controlled_process_environment()


def analyze():
    here = Path(__file__).resolve().parent
    old = json.loads((here / "analysis-v4.json").read_text())
    run = Path(old["run_dir"])
    root = run / "absolute-sol/absolute_score"
    summary = json.loads((root / "summary.json").read_text())
    luna = json.loads((run / "audits" / old["experiment_id"] / "absolute_score/summary.json").read_text())
    assert summary["status"] == "completed"
    assert summary["assignment_coverage"] == luna["assignment_coverage"]
    assert summary["planned_semantic_judgment_count"] == summary["successful_semantic_judgment_count"] == 45
    assert len(summary["assignments"]) == 36 and len(summary["records"]) == 72
    assert not summary["missing_models"] and not summary["judge_failures"]
    original = {(r["assignment_id"], r["artifact"]): r for r in luna["records"]}
    for ref in summary["records"]:
        prior = original[(ref["assignment_id"], ref["artifact"])]
        # Verify identical evidence/prompt provenance, not just matching task names.
        a = json.loads((root / "records" / f'{ref["judgment_key"]}.json').read_text())
        b = json.loads((run / "audits" / old["experiment_id"] / "absolute_score/records" / f'{prior["judgment_key"]}.json').read_text())
        for field in ("submission_content_sha256", "task_instruction_sha256", "prompt_id", "prompt_sha256", "review", "max_review_chars"):
            assert a[field] == b[field], field
        validate_verdict(a["verdict"])
        assert json.loads(a["raw_response"]) == a["verdict"] == ref["verdict"]
        assert a["model"] == a["generation"]["effective_model"] == "gpt-6-sol"
        assert a["generation"]["request_parameters"]["reasoning_effort"] == "high"
        assert sha256_file(root / "records" / f'{ref["judgment_key"]}.json') == summary["completed_record_sha256s"][ref["judgment_key"]]
    by_id = {r["assignment_id"]: r for r in summary["assignments"]}
    rows = []
    for before in old["assignments"]:
        row = {**before, "initial": dict(before["initial"]), "final": dict(before["final"])}
        score = by_id[row["assignment_id"]]["rubric_free_absolute_scores"]
        for phase in ("initial", "final"):
            row[phase]["A_luna"] = row[phase]["A"]
            row[phase]["A"] = score[f"{phase}_panel_mean"]
            row[phase]["H-A"] = row[phase]["H"] - row[phase]["A"]
        rows.append(row)
    groups = defaultdict(list)
    for row in rows:
        groups[row["condition_id"]].append(row)
    conditions = [{"condition": c, "n": len(rs), **{
        phase: {k: mean(r[phase][k] for r in rs) for k in rs[0][phase]}
        for phase in ("initial", "final")
    }} for c, rs in sorted(groups.items())]
    pairs = []
    for feedback in ("full", "user-simulator"):
        for task in ("dev-001", "dev-002", "dev-003"):
            for rep in (1, 2, 3):
                baseline = next(r for r in groups[feedback + "-static"] if r["task_id"] == task and r["replicate"] == rep)
                rtt = next(r for r in groups[feedback + "-red-team-trace"] if r["task_id"] == task and r["replicate"] == rep)
                pairs.append({"feedback": feedback, "task_id": task, "replicate": rep,
                              "RTT_minus_static": {k: rtt["final"][k] - baseline["final"][k] for k in ("W", "S", "H", "A", "W-S", "S-H", "H-A")}})
    usage = snapshot(root)
    usd = ((usage["input_tokens"] - usage["cached_input_tokens"] - usage["cache_write_input_tokens"]) * 2
           + usage["cached_input_tokens"] * .2 + usage["cache_write_input_tokens"] * 2.5
           + usage["output_tokens"] * 10) / 1e6
    usage.update(estimated_usd=usd, caveat="Saved GPT-6 Sol standard short-context usage estimate, not invoice; usage-less failed calls excluded.")
    return {"experiment_id": old["experiment_id"], "A_model": "gpt-6-sol", "scope": "Supplemental all-case A-only audit; W/S/H/RH unchanged",
            "conditions": conditions, "assignments": rows, "paired_contrasts": pairs, "usage": usage}


if __name__ == "__main__":
    result = analyze()
    dest = Path(__file__).with_name("analysis-v4-absolute-sol.json")
    dest.write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps({k:v for k,v in result.items() if k not in {"assignments", "paired_contrasts"}}, indent=2))
