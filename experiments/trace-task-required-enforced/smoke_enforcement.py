"""Run one persisted Luna request through the enforced candidate stage path."""

from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from rubric_gen.artifacts.serialization import write_json_atomic
from rubric_gen.benchmarks.base import SubmissionBenchmarkId
from rubric_gen.submission_revision.evolution import RubricProposer
from rubric_gen.submission_revision.evolution_artifacts import BlindedArtifact
from rubric_gen.submission_revision.rubric_generation import CompleteRubric
from rubric_gen.submission_revision.task_paraphrase_required_stage import TraceStagesV2
from rubric_gen.submission_revision.task_required_enforcement import VERSION, enforcement_request


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-assignment", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--runtime-config", type=Path, required=True)
    args = parser.parse_args()
    source = args.source_assignment.resolve()
    output = args.output_root.resolve()
    runtime = args.runtime_config.resolve()
    if runtime.is_symlink() or not runtime.is_file():
        raise RuntimeError("runtime config must be a regular file")
    os.environ["RUBRIC_GEN_RUNTIME_CONFIG"] = str(runtime)
    manifest = json.loads((source / "manifest.json").read_text())
    history = json.loads((source / "rubric-generations/generation-0002/artifact-history.json").read_text())
    current = [item for item in history["red_team_evidence"] if item["source_checkpoint"] == 0]
    if len(current) != 1:
        raise RuntimeError("smoke source lacks exactly one checkpoint-zero witness")
    identity = current[0]["observed_artifact_id"]
    artifacts = {item["artifact_id"]: item for item in history["artifacts"]}
    artifact = BlindedArtifact(**artifacts[identity])
    original = CompleteRubric.from_content(Path(manifest["initial_rubric_path"]).read_text())
    development = CompleteRubric.from_content(Path(manifest["development_rubric_path"]).read_text())
    instruction = (Path(manifest["task_dir"]) / "instruction.md").read_text()
    evidence, validator, witness = enforcement_request(
        instruction=instruction, original_rubric=original, development_rubric=development,
        artifact=artifact, output_dir=source, source_checkpoint=0,
    )
    proposer = RubricProposer(
        benchmark=SubmissionBenchmarkId.BIOMNIBENCH_DA,
        model="gpt-5.6-luna", max_retries=1, red_team_trace_version=VERSION,
    )
    stage = TraceStagesV2(proposer, output / "requests")
    response = stage.call("enforcement", evidence, validator)
    record = {
        "kind": "task-required-enforcement-route-smoke",
        "time": datetime.now(timezone.utc).isoformat(),
        "version": VERSION,
        "source_assignment": str(source),
        "source_artifact_id": identity,
        "witness": witness,
        "response": response,
        "resolved_evidence": validator.validate(response) if response else {},
        "request_record": stage.records[0],
    }
    write_json_atomic(output / "smoke.json", record)
    print(json.dumps({"response": response, "receipt": str(output / "smoke.json")}, ensure_ascii=False))


if __name__ == "__main__":
    main()
