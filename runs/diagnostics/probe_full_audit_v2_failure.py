"""Isolated serial replay of one unscored full-audit job; never writes formal outputs."""
import json
import os
from pathlib import Path

from rubric_gen.detection.jobs import DetectionConfig
from rubric_gen.detection.runner import DetectionRunner
from rubric_gen.submission_revision.detection_windows import RevisionDetectionWindow
from rubric_gen.submission_revision.evaluation.direct import load_detection_study
from rubric_gen.submission_revision.evaluation.evidence import revision_detection_source
from rubric_gen.submission_revision.experiment import load_experiment


def redact(message):
    for name, value in os.environ.items():
        if any(word in name for word in ("KEY", "TOKEN", "SECRET")) and len(value) > 6:
            message = message.replace(value, "[REDACTED]")
    return message


experiment = load_experiment(Path("experiments/biomnibench-results20-user-simulator-full.yaml").resolve())
study = load_detection_study(Path(experiment.dag["revise"]["output_dir"]), experiment)
source = revision_detection_source(
    study.revisions,
    tasks_dir=study.tasks_dir,
    experiment_ids=(study.study_experiment_id,),
    window=RevisionDetectionWindow.FULL_TRAJECTORY,
)
case = next(case for case in source.cases if case.case_id == "revision-000037")
model = "gemini-3.8-flash"
runner = DetectionRunner(DetectionConfig(
    source=source,
    models=(model,),
    output_dir=Path("runs/diagnostics/full-audit-v2-failure-probe/gemini-revision-000037"),
    max_concurrency=1,
    max_input_tokens=int(experiment.outcome_audit["max_input_tokens"]),
    max_output_tokens=int(experiment.outcome_audit["max_output_tokens"]),
    primary_rule=str(experiment.outcome_audit["primary_rule"]),
))
try:
    job = runner._prepare_job(case, model, runner._payload(case))
    print(json.dumps({"probe": "prepared", "case_id": case.case_id, "model": model,
                      "input_tokens": job.input_tokens, "requests": len(job.requests)}), flush=True)
    result = runner._standard_runner().execute(job)
    print(json.dumps({key: redact(str(result[key])) if key == "error" else result.get(key)
                      for key in ("case_id", "model", "status", "attempt_count", "error_type", "error")
                      if key in result}), flush=True)
except Exception as exc:
    print(json.dumps({"probe": "exception", "case_id": case.case_id, "model": model,
                      "error_type": type(exc).__name__, "error": redact(str(exc))}), flush=True)
    raise SystemExit(1)
