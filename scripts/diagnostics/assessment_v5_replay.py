"""Private live regression of changed proposer logic; not an outcome experiment."""

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import json
import time

from rubric_gen.artifacts.hashing import sha256_file
from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.benchmarks import SubmissionBenchmarkId
from rubric_gen.submission_revision.evolution import RubricProposer
from rubric_gen.submission_revision.evolution_artifacts import (
    ArtifactHistory, ArtifactPair, BlindedArtifact, RedTeamEvidence,
)
from rubric_gen.submission_revision.evolution_assessment import (
    AssessmentView, assessment_schema,
)
from rubric_gen.submission_revision.rubric_generation import CompleteRubric, RubricPolicy
from rubric_gen.submission_revision.rubric_generation_store import load_rubric_generation


SOURCE = Path("runs/preflights/assessment-contract-v4/biomnibench-da-factorial-r3-b07888ff76df")
DESTINATION = Path("runs/diagnostics/score-derived-v5")
CONDITIONS = ("full-red-team-artifact", "user-simulator-red-team-artifact")


def replay(condition):
    source = SOURCE / "experiments/da-18-1/rep-001/luna" / condition
    manifest_path = source / "manifest.json"
    manifest = json.loads(manifest_path.read_text())
    history_path = source / "rubric-generations/generation-0003/artifact-history.json"
    raw = json.loads(history_path.read_text())
    history = ArtifactHistory(
        artifacts=tuple(BlindedArtifact(**item) for item in raw["artifacts"]),
        pairs=tuple(ArtifactPair(item["pair_id"], tuple(item["artifact_ids"])) for item in raw["pairs"]),
        red_team_evidence=tuple(RedTeamEvidence(**item) for item in raw["red_team_evidence"]),
    )
    current = load_rubric_generation(source, 2)
    schema = assessment_schema(history, view=AssessmentView.ACTIVE_RUBRIC, current_generation=current)
    if "preference" in schema["properties"]["assessments"]["items"]["properties"]:
        raise RuntimeError("Score-derived preference implementation is not active; no calls made")
    task = Path(manifest["task_dir"])
    instruction = task / "instruction.md"
    development = Path(manifest["development_rubric_path"])
    assert sha256_file(instruction) == manifest["instruction_sha256"]
    assert sha256_file(development) == manifest["development_rubric_sha256"]
    output = DESTINATION / condition
    calls = output / "calls"
    calls.mkdir(parents=True, exist_ok=False)
    write_json_atomic(output / "source.json", {
        "purpose": "component regression; never combine with Results20 outcomes",
        "source_manifest": str(manifest_path.resolve()),
        "source_manifest_sha256": sha256_file(manifest_path),
        "history_sha256": sha256_file(history_path),
        "prior_generation_sha256": current.generation_sha256,
    })
    proposer = RubricProposer(
        benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,
        model="gpt-5.6-luna", max_retries=5,
    )
    original_call = proposer.run_proposer
    call_count = 0

    def observed_call(**kwargs):
        nonlocal call_count
        call_count += 1
        started = time.monotonic()
        call_path = calls / f"{call_count:03d}-{kwargs['stage']}.json"
        print(condition, "call", call_count, kwargs["stage"], "started", flush=True)
        try:
            result = original_call(**kwargs)
        except Exception as error:
            write_json_atomic(call_path, {
                "stage": kwargs["stage"], "error_type": type(error).__name__,
                "elapsed_seconds": time.monotonic() - started,
            })
            raise
        write_json_atomic(call_path, {
            "stage": kwargs["stage"], "response_text": result.response_text,
            "response_schema": kwargs["response_schema"],
            "generation": result.generation, "cost": result.cost,
            "elapsed_seconds": time.monotonic() - started,
        })
        print(condition, "call", call_count, "returned", flush=True)
        return result

    proposer.run_proposer = observed_call
    arguments = dict(
        instruction=instruction.read_text(),
        original_rubric=load_rubric_generation(source, 0).rubric,
        development_rubric=CompleteRubric.from_content(development.read_text()),
        current_generation=current, policy=RubricPolicy(manifest["rubric_policy"]),
        generation_round=3, source_checkpoint=2, artifact_history=history,
        output_dir=output,
    )
    started = time.monotonic()
    generated = proposer.elicit_rubric(**arguments)
    evolution = json.loads((output / "rubric-generations/generation-0003/evolution.json").read_text())
    fallbacks = {key: value for key, value in evolution.items() if key.endswith("fallback_reason") and value}
    for stage in ("assessment_rubric_free", "assessment_active_rubric", "assessment_development_rubric"):
        assert evolution[f"{stage}_attempt_count"] >= 1

    def no_generation(**kwargs):
        raise AssertionError("Validated completed-generation reload must not make API calls")

    proposer.run_proposer = no_generation
    reloaded = proposer.elicit_rubric(**arguments)
    assert reloaded.generation_sha256 == generated.generation_sha256
    result = {
        "condition": condition, "passed": not fallbacks, "fallbacks": fallbacks,
        "api_calls": call_count, "elapsed_seconds": time.monotonic() - started,
        "accepted_candidate_ids": evolution["accepted_candidate_ids"],
        "generation_sha256": generated.generation_sha256,
        "completed_generation_reload_verified": True,
    }
    write_json_atomic(output / "result.json", result)
    return result


if __name__ == "__main__":
    if DESTINATION.exists():
        raise FileExistsError("Diagnostic output already exists; preserve it")
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(replay, CONDITIONS))
    write_json_atomic(DESTINATION / "summary.json", {"results": results, "passed": all(x["passed"] for x in results)})
    print(json.dumps(results), flush=True)
    if not all(x["passed"] for x in results):
        raise SystemExit(1)
