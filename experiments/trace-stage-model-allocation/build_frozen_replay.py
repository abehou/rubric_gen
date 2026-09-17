"""Freeze the bounded Luna-low versus Luna-high stage replay inputs.

This script is provider-free.  It records exact current request receipts, exact
saved public artifacts from the historical forensic review, and the three
agent-side checkpoints without mutating any source experiment.
"""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import subprocess
import sys

_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPOSITORY_ROOT / "src"))

from rubric_gen.artifacts.hashing import sha256_file, sha256_text
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.benchmarks.biomnibench_da.contract import BIOMNIBENCH_DA
from rubric_gen.submission_revision import evolution_assessment as assessment
from rubric_gen.submission_revision import trace_defense_v21
from rubric_gen.submission_revision import trace_defense_v2_prompts as prompts
from rubric_gen.submission_revision import trace_defense_v2_schema as schema
from rubric_gen.submission_revision.evolution_serialization import (
    canonical_json,
    canonical_sha256,
)
from rubric_gen.submission_revision.trace_defense_evidence_v2 import (
    PublicDocument,
    source_manifest,
)


ROOT = _REPOSITORY_ROOT
RUN = ROOT / "runs/trace-stage-model-allocation-20260917"
FROZEN = RUN / "frozen"
STUDY = (
    ROOT
    / "runs/trace-v21-execution-verified-dropout-local-mac/dev3/study"
    / "biomnibench-da-factorial-r10-2f8f9cee1a53"
)
REQUEST_GLOB = "experiments/**/trace-defense-v2-requests/*/result.json"
FORENSICS = (
    ROOT / "docs/reports/2026-09-10/trace-forensics/support-review-evidence.json"
)


# Exact saved low request keys from the paused local run.  The expected pair
# verdict comes from the host-computed source/attack relation, not from Luna.
PAIR_KEYS = (
    "78845ccf0ef0354ae8a0322187044793078052522edb5a4849af6a41ef06e040",
    "15adbbb626cee334dd8a659711a7c6403860539c63a8f9a9f7f5baf51d980eea",
    "d04c61c8769c5b7de35b7a172301763b8027f81a12d3b67a5d199f273cfa6d9a",
    "6aa3fd877808362074d22ff628f51bda14f0538eba87ffdb264d8440e5d020c5",
    "ef83c8f7f8056b7cfc2cd8134a10e229559dc528ad07cb611021b51eb5915bf3",
    "01977b9bd897621e3568def039977866b3fb2475a64fe542e7075999dd8d70bf",
    "3be96f928139e8d98ba3675d6addfdbb1da7a17d4fef7d014bb7404c60ca6089",
    "f12429dc41593e80e951b316101ac476d75d5e264ea003353c3ddd05fa151674",
    "efe0546564fdacbacbabe5c47e669b628b3c83e133dc4cfa9e2f0394a4d8d764",
    "6a4047612afdf8851fa5ae4c461f6ea6db4d768d54ef7f4cbed2710add9da668",
    "27fd0eb57f0b8d8f6cbf0a490381690cd18b33085aaebe98aa318d0f81988b35",
    "85be2bcdb0d90d289a07719b3e11c6e81e66ad41b51a752c0ddabc7bb5c879cc",
)

DIAGNOSIS_KEYS = (
    "c28ce4862999f80dfbe3cd5cb65a250df6eaceed6cbe91a2b8c312d0f18a5a88",
    "bb2f8925a02223b5295f6db6f019fe769cbff017ace7dffe9f976e14840218ca",
    "6467fd50e8aed0ee3d2ed3c072a40f8a5deb4360fa56eb6f5e9d42a5ef44b379",
    "1b81c825008671634fc7385adcd25402526e024ba39312afe780be784668db32",
    "35e13dc76667bb1515c803ab18a484326c9fb72f3620e696c47ea034a9b61e1d",
    "cff4acce3745fe7c805aa0b6710f8596ca858ece480e6049cec0b35757fce066",
)

COMPILATION_KEYS = (
    "baafd77f08a82a0ec3a166b8ec3278669e2f31013a659f3676dc3561d550779c",
    "a878bb132b8d091f4375e114535b616e42d9e857f8f05c52b8e6900461e988cc",
    "ab110165fe646cbc0e014c99c7e3aa6b5546906cbea2ff5d24ddcd4fc002c28b",
)

APPLICATION_KEYS = (
    # Distinguishes Mann-Whitney p=0.3041 from Spearman p=0.3037.
    "01911eecd5ec1f34ff12ca2dd2a12812a9f053002cb457d5addd4c93c8185a9a",
    # Saved low application incorrectly rejects the filtering/result mapping.
    "0f99e00f80d39d0e230788ec0d525caa9735b3881a6688102bce722f539cb405",
)

HISTORICAL_CASES = (
    "candidate_user_da-10-1_r3",
    "candidate_user_da-12-2_r3",
    "candidate_user_da-16-1_r1",
    "candidate_user_da-12-2_r2",
    "candidate_user_da-14-1_r2",
    "candidate_user_da-12-4_r2",
)

ATTACK_CASES = (
    "da-3-4/rep-001/luna/full-red-team-trace-execution-verified-dropout-0/red-team/checkpoint-0000",
    "da-11-1/rep-002/luna/full-red-team-trace-execution-verified-dropout-0/red-team/checkpoint-0000",
    "da-18-1/rep-002/luna/full-red-team-trace-execution-verified-dropout-0/red-team/checkpoint-0000",
)

SOLVER_CASES = (
    "user-da-11-1-rep-001",
    "user-da-11-1-rep-002",
    "user-da-11-1-rep-003",
    "full-da-11-1-rep-001",
)


def read(path: Path) -> dict | list:
    return json.loads(path.read_text(encoding="utf-8"))


def relative(path: Path) -> str:
    return path.resolve().relative_to(ROOT).as_posix()


def git_record() -> dict[str, object]:
    diff = subprocess.check_output(["git", "diff", "--binary", "HEAD"], cwd=ROOT)
    untracked = subprocess.check_output(
        ["git", "ls-files", "--others", "--exclude-standard", "-z"], cwd=ROOT
    )
    return {
        "commit": subprocess.check_output(
            ["git", "rev-parse", "HEAD"], cwd=ROOT, text=True
        ).strip(),
        "dirty": bool(diff or untracked),
        "tracked_diff_sha256": hashlib.sha256(diff).hexdigest(),
        "untracked_paths_sha256": hashlib.sha256(untracked).hexdigest(),
    }


def request_index() -> dict[str, Path]:
    result: dict[str, Path] = {}
    for path in STUDY.glob(REQUEST_GLOB):
        key = path.parent.name
        if key in result:
            # Identical requests were sometimes executed independently in
            # multiple assignments.  Outcomes/accounting may differ, but the
            # request represented by the content-addressed key must not.
            request = read(path)["request"]
            retained_request = read(result[key])["request"]
            if canonical_json(request) != canonical_json(retained_request):
                raise RuntimeError(f"request key collision with different requests: {key}")
            continue
        result[key] = path
    return result


def attack_index() -> dict[str, dict[str, object]]:
    result = {}
    for path in STUDY.glob("experiments/**/red-team/checkpoint-*/attack-record-v2.json"):
        value = read(path)
        if value.get("public_nonidentical"):
            result[str(value["output_public_sha256"])] = {
                "path": relative(path),
                "source_sha256": value["source_public_sha256"],
                "mechanism": (value.get("narration") or {}).get("attack_mechanism"),
            }
    return result


def exact_request_record(path: Path, *, expected_stage: str) -> dict[str, object]:
    saved = read(path)
    request = saved["request"]
    if request["stage"] != expected_stage:
        raise RuntimeError(f"{path} is {request['stage']}, not {expected_stage}")
    if canonical_sha256(request) != path.parent.name:
        raise RuntimeError(f"request receipt key changed: {path}")
    provider = request["provider"]
    if provider["model"] != "gpt-5.6-luna" or provider["reasoning_effort"] != "low":
        raise RuntimeError(f"saved control is not Luna-low: {path}")
    return {
        "kind": "exact_saved_request",
        "source_path": relative(path),
        "source_sha256": sha256_file(path),
        "request_sha256": canonical_sha256(request),
        "request": request,
        "low_outcome": saved["outcome"],
        "low_accounting": saved["accounting"],
    }


def pair_expected_source(record: dict[str, object], attacks) -> dict[str, object]:
    evidence = json.loads(record["request"]["evidence"])
    artifacts = (evidence["artifact_A"], evidence["artifact_B"])
    matches = []
    for attacked_position, source_position in ((0, 1), (1, 0)):
        attacked = artifacts[attacked_position]
        source = artifacts[source_position]
        attack = attacks.get(attacked["source_sha256"])
        if attack and attack["source_sha256"] == source["source_sha256"]:
            matches.append((attacked_position, source_position, attack))
    if len(matches) != 1:
        raise RuntimeError("selected current pair is not one exact source/attack contrast")
    attacked_position, source_position, attack = matches[0]
    record["manual_label"] = {
        "expected_preferred_artifact_id": artifacts[source_position]["artifact_id"],
        "attacked_artifact_id": artifacts[attacked_position]["artifact_id"],
        "basis": "host-computed saved source/attack relation",
        "attack": attack,
    }
    return record


def historical_quality_records() -> list[dict[str, object]]:
    rows = read(FORENSICS)
    by_case = {row["case"]: row for row in rows}
    records = []
    for case in HISTORICAL_CASES:
        row = by_case[case]
        task_id = case.split("_da-", 1)[1].rsplit("_r", 1)[0]
        task_id = "da-" + task_id
        instruction = (ROOT / f"data/biomnibench-da/{task_id}/instruction.md").read_text()
        for pair in row["pairs"]:
            presented = {
                pair["presentation_A_id"]: pair["preferred_content"]
                if pair["presentation_A_id"] == pair["preferred_artifact_id"]
                else pair["rejected_content"],
                pair["presentation_B_id"]: pair["preferred_content"]
                if pair["presentation_B_id"] == pair["preferred_artifact_id"]
                else pair["rejected_content"],
            }
            docs = {
                "artifact_A": PublicDocument(
                    "artifact_A", presented[pair["presentation_A_id"]]
                ),
                "artifact_B": PublicDocument(
                    "artifact_B", presented[pair["presentation_B_id"]]
                ),
            }
            identities = {
                "artifact_A": pair["presentation_A_id"],
                "artifact_B": pair["presentation_B_id"],
            }
            evidence = {
                "task": instruction,
                "pair_id": pair["pair_id"],
                **{
                    alias: {"artifact_id": identities[alias], **doc.model_record()}
                    for alias, doc in docs.items()
                },
                "source_manifest": source_manifest(docs, identities),
                "visible_difference": assessment.pair_text_difference(
                    presented[pair["presentation_A_id"]],
                    presented[pair["presentation_B_id"]],
                ),
            }
            validator = schema.ResponseContract(
                "quality",
                schema.quality_schema(tuple(identities.values()), docs),
                docs,
                identities,
            )
            if case in {
                "candidate_user_da-10-1_r3",
                "candidate_user_da-12-2_r3",
                "candidate_user_da-16-1_r1",
            }:
                expected = None
            elif case == "candidate_user_da-12-2_r2":
                expected = (
                    "artifact_9c80d272623f883c"
                    if pair["pair_id"] == "pair_467d8776c277f387"
                    else None
                )
            elif case == "candidate_user_da-14-1_r2":
                expected = (
                    "artifact_733eb5e799634673"
                    if pair["pair_id"] == "pair_1f8e61fa2eebdecc"
                    else None
                )
            elif case == "candidate_user_da-12-4_r2":
                expected = "artifact_affac4bc8c0bd593"
            else:
                raise AssertionError(case)
            saved_preference = pair["saved_quality_assessment"]["preference"]
            low_id = {
                "artifact_A": pair["presentation_A_id"],
                "artifact_B": pair["presentation_B_id"],
            }.get(saved_preference)
            request = {
                "stage": "quality",
                "prompt": prompts.STAGES["quality"],
                "prompt_sha256": sha256_text(prompts.STAGES["quality"]),
                "prompt_version": prompts.PROMPT_VERSION,
                "evidence": canonical_json(evidence),
                "schema": validator.schema,
                "response_contract": validator.identity(),
            }
            records.append({
                "kind": "reconstructed_exact_public_quality_request",
                "case": case,
                "pair_id": pair["pair_id"],
                "forensic_source_path": relative(FORENSICS),
                "forensic_source_sha256": sha256_file(FORENSICS),
                "request": request,
                "request_sha256": canonical_sha256(request),
                "low_outcome": {
                    "preferred_artifact_id": low_id,
                    "artifact_assessments": {
                        "artifact_A": pair["saved_quality_assessment"]["assessment_A"],
                        "artifact_B": pair["saved_quality_assessment"]["assessment_B"],
                    },
                    "reason": pair["saved_quality_assessment"]["reason"],
                },
                "manual_label": {
                    "expected_preferred_artifact_id": expected,
                    "basis": row["manual_reason"],
                    "failure_class": row["primary_support_failure"],
                },
                "identity_note": (
                    "Exact saved public artifact bytes, IDs, A/B order, task, v2 prompt, "
                    "and v2 schema; the original remote request receipt is unavailable "
                    "locally, so producer-only receipt fields are intentionally absent."
                ),
            })
    return records


def historical_application_records() -> list[dict[str, object]]:
    rows = read(FORENSICS)
    row = next(item for item in rows if item["case"] == "candidate_user_da-12-4_r2")
    pair = row["pairs"][0]
    task = (ROOT / "data/biomnibench-da/da-12-4/instruction.md").read_text()
    criterion = {
        "criterion_id": row["criterion_id"],
        "title": row["title"],
        "requirement": row["requirement"],
        "levels": row["levels"],
    }
    records = []
    for role in ("preferred", "rejected"):
        artifact_id = pair[f"{role}_artifact_id"]
        content = pair[f"{role}_content"]
        document = PublicDocument("artifact", content)
        identities = {"artifact": artifact_id}
        documents = {"artifact": document}
        labels = tuple(item["label"] for item in row["levels"])
        evidence = {
            "task": task,
            "criterion": criterion,
            "artifact": {"artifact_id": artifact_id, **document.model_record()},
            "source_manifest": source_manifest(documents, identities),
        }
        validator = schema.ResponseContract(
            "application",
            schema.application_schema(labels, documents),
            documents,
            identities,
            labels=labels,
        )
        request = {
            "stage": "application",
            "prompt": prompts.STAGES["application"],
            "prompt_sha256": sha256_text(prompts.STAGES["application"]),
            "prompt_version": prompts.PROMPT_VERSION,
            "evidence": canonical_json(evidence),
            "schema": validator.schema,
            "response_contract": validator.identity(),
        }
        expected = "A" if role == "preferred" else "C"
        records.append({
            "kind": "reconstructed_exact_public_application_request",
            "case": "candidate_user_da-12-4_r2",
            "role": role,
            "request": request,
            "request_sha256": canonical_sha256(request),
            "low_outcome": {
                "level": pair[f"{role}_level"],
                "reason": pair[f"{role}_reason"],
            },
            "manual_label": {
                "expected_level": expected,
                "basis": row["manual_reason"],
            },
            "identity_note": (
                "Exact saved criterion/artifact bytes and IDs under the pinned v2 "
                "application prompt/schema; original remote receipt unavailable locally."
            ),
        })
    return records


def attack_case_records() -> list[dict[str, object]]:
    result = []
    experiments = STUDY / "experiments"
    for suffix in ATTACK_CASES:
        checkpoint = experiments / suffix
        manifest = read(checkpoint / "manifest.json")
        attack = read(checkpoint / "attack-record-v2.json")
        experiment = checkpoint.parents[1]
        source_candidates = []
        for workspace in sorted((experiment / "submissions").glob("s*/workspace")):
            if sha256_text(BIOMNIBENCH_DA.render_user_review(workspace)) == manifest[
                "source_artifact_sha256"
            ]:
                source_candidates.append(workspace)
        if not source_candidates:
            raise RuntimeError(f"cannot resolve attack source workspace: {checkpoint}")
        source = source_candidates[0]
        result.append({
            "case_id": "--".join(suffix.split("/")[:2] + [suffix.split("/")[3], suffix.split("/")[-1]]),
            "checkpoint_path": relative(checkpoint),
            "checkpoint_manifest_sha256": sha256_file(checkpoint / "manifest.json"),
            "source_workspace": relative(source),
            "source_public_sha256": manifest["source_artifact_sha256"],
            "prompt_path": relative(checkpoint / "prompt.txt"),
            "prompt_sha256": sha256_file(checkpoint / "prompt.txt"),
            "active_rubric_sha256": manifest["active_rubric_sha256"],
            "low_attack_record_path": relative(checkpoint / "attack-record-v2.json"),
            "low_attack_record_sha256": sha256_file(checkpoint / "attack-record-v2.json"),
            "low_attack": attack,
        })
    return result


def solver_case_records() -> list[dict[str, object]]:
    # Import only after all immutable path constants above are defined.
    import importlib.util

    source = ROOT / "experiments/trace-v21-execution-verified-dropout/run_saved_case.py"
    spec = importlib.util.spec_from_file_location("saved_case_module", source)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    low_root = (
        ROOT
        / "runs/trace-v21-execution-verified-dropout-local-mac/saved-case-behavior/cases"
    )
    records = []
    for case_id in SOLVER_CASES:
        case = module.CASES[case_id]
        low_case = low_root / case_id
        result_path = (
            low_case / "followup-3-result.json"
            if case_id == "user-da-11-1-rep-003"
            else low_case / "result.json"
        )
        records.append({
            "case_id": case_id,
            "source_workspace": relative(case.source_workspace),
            "source_submission": case.source_submission,
            "ordinary_prompt": relative(case.ordinary_prompt),
            "ordinary_prompt_sha256": sha256_file(case.ordinary_prompt),
            "solver_visible_prompt": module._solver_prompt(case),
            "solver_visible_prompt_sha256": sha256_text(module._solver_prompt(case)),
            "issue": case.issue,
            "expected": case.expected,
            "low_result_path": relative(result_path),
            "low_result_sha256": sha256_file(result_path),
            "low_result": read(result_path),
        })
    return records


def main() -> None:
    index = request_index()
    attacks = attack_index()
    needed = set(PAIR_KEYS + DIAGNOSIS_KEYS + COMPILATION_KEYS + APPLICATION_KEYS)
    missing = sorted(needed - set(index))
    if missing:
        raise RuntimeError(f"saved request keys unavailable: {missing}")
    current_pairs = [
        pair_expected_source(
            exact_request_record(index[key], expected_stage="quality"), attacks
        )
        for key in PAIR_KEYS
    ]
    payload = {
        "kind": "trace-stage-model-allocation-frozen-replay-v1",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git": git_record(),
        "scientific_model": "gpt-5.6-luna",
        "saved_control_reasoning": "low",
        "diagnostic_reasoning": "high",
        "dev3_remains_paused": True,
        "current_pair_quality": current_pairs,
        "historical_pair_quality": historical_quality_records(),
        "diagnosis": [
            exact_request_record(index[key], expected_stage="diagnosis")
            for key in DIAGNOSIS_KEYS
        ],
        "compilation": [
            exact_request_record(index[key], expected_stage="compilation")
            for key in COMPILATION_KEYS
        ],
        "current_application": [
            exact_request_record(index[key], expected_stage="application")
            for key in APPLICATION_KEYS
        ],
        "historical_application": historical_application_records(),
        "reused_application_diagnostic": {
            "contexts": 9,
            "judgments": 57,
            "low_model": "gpt-5.6-luna",
            "low_reasoning": "low",
            "high_model": "gpt-5.6-luna",
            "high_reasoning": "high",
            "exact_identity_verified": True,
            "report_path": "docs/reports/2026-09-09/cue-application-reasoning-result.md",
            "report_sha256": sha256_file(
                ROOT / "docs/reports/2026-09-09/cue-application-reasoning-result.md"
            ),
            "note": (
                "The report and frozen diagnostic code attest exact model, prompt, "
                "input, schema, candidate, and control reuse. Raw remote call files "
                "are not present on this Mac, so no calls are regenerated."
            ),
        },
        "attack": attack_case_records(),
        "solver": solver_case_records(),
        "excluded_stages": [
            "execution_reviewer",
            "selector",
            "admission_mathematics",
            "user_simulator",
            "final_auditors",
            "evaluation",
        ],
    }
    FROZEN.mkdir(parents=True, exist_ok=True)
    destination = FROZEN / "manifest.json"
    if destination.exists():
        previous = read(destination)
        # Creation time is provenance, not replay identity.
        previous = {k: v for k, v in previous.items() if k != "created_at"}
        candidate = {k: v for k, v in payload.items() if k != "created_at"}
        if canonical_json(previous) != canonical_json(candidate):
            raise RuntimeError("existing frozen manifest differs; do not overwrite")
        print(json.dumps({"status": "already_frozen", "sha256": sha256_file(destination)}))
        return
    write_json_atomic(destination, payload)
    write_json_atomic(FROZEN / "receipt.json", {
        "manifest": relative(destination),
        "manifest_sha256": sha256_file(destination),
        "current_pair_count": len(payload["current_pair_quality"]),
        "historical_pair_count": len(payload["historical_pair_quality"]),
        "diagnosis_count": len(payload["diagnosis"]),
        "compilation_count": len(payload["compilation"]),
        "new_application_count": len(payload["current_application"]) + len(payload["historical_application"]),
        "reused_application_judgments": 57,
        "attack_count": len(payload["attack"]),
        "solver_count": len(payload["solver"]),
    })
    print(json.dumps(read(FROZEN / "receipt.json"), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
