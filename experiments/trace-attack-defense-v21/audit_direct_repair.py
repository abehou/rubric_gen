"""Audit-only direct RH recovery for the explicit v2.1 consumer cohort.

The 118 imported assignments retain the producer experiment ID in their sealed
manifests.  The consumer-import receipt already records that producer identity;
this adapter admits both the consumer and producer IDs to the unchanged direct
source validator.  It does not alter revisions, prompts, scoring, or audit
thresholds and resumes any existing direct-evaluation records.
"""
from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import dotenv_values

from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.detection_windows import RevisionDetectionWindow
from rubric_gen.submission_revision.evaluation.direct import (
    DirectDetectionConfig,
    _evaluation_dir,
    load_detection_study,
)
from rubric_gen.submission_revision.evaluation.evidence import revision_detection_source
from rubric_gen.detection.jobs import DetectionConfig
from rubric_gen.detection.runner import DetectionRunner
from rubric_gen.submission_revision.evaluation.targets import load_evaluation_targets
from rubric_gen.submission_revision.evaluation.jobs import EvaluationConfig
from rubric_gen.submission_revision.evaluation.runner import RubricFreeScoreRunner, RubricScoreRunner

from prepare import BUNDLE, ROOT, RUN, sha
from run import PANEL, check_shared_mount, verify_freeze

WINDOWS = tuple(RevisionDetectionWindow)


def _load_import_ids(revisions: tuple[Path, ...], consumer_id: str) -> tuple[tuple[str, ...], list[dict[str, str]]]:
    ids = {consumer_id}
    receipts: list[dict[str, str]] = []
    for revision in revisions:
        path = revision / "consumer-import.json"
        if not path.is_file():
            continue
        value = json.loads(path.read_text())
        if value.get("consumer_experiment_id") != consumer_id:
            raise RuntimeError(f"consumer import points to another experiment: {path}")
        producer = value.get("producer_experiment_id")
        if not isinstance(producer, str) or not producer:
            raise RuntimeError(f"consumer import has no producer experiment: {path}")
        ids.add(producer)
        receipts.append({
            "revision": str(revision),
            "producer_experiment_id": producer,
            "consumer_experiment_id": consumer_id,
            "receipt_sha256": sha(path),
        })
    return tuple(sorted(ids)), receipts


def _direct_window(exp, study, study_dir: Path, output_dir: Path, max_concurrency: int, window: RevisionDetectionWindow) -> dict[str, object]:
    settings = study.settings
    models = tuple(settings.get("models", ()))
    primary_rule = str(settings["primary_rule"])
    max_input_tokens = int(settings["max_input_tokens"])
    max_output_tokens = int(settings["max_output_tokens"])
    identity = (
        f"ensemble--detect-rh--experiment-{study.experiment_id}"
        f"--source-{study.study_experiment_id}"
        f"--window-{window.value}"
        f"--max-input-{max_input_tokens}"
        f"--max-output-{max_output_tokens}"
        f"--primary-{primary_rule}"
    )
    evaluation_dir = _evaluation_dir(output_dir, identity, resume=True)
    allowed_ids, imports = _load_import_ids(study.revisions, study.study_experiment_id)
    source = revision_detection_source(
        study.revisions,
        tasks_dir=study.tasks_dir,
        experiment_ids=allowed_ids,
        window=window,
    )
    result = DetectionRunner(DetectionConfig(
        source=source,
        models=models,
        output_dir=evaluation_dir,
        max_concurrency=max_concurrency,
        resume=evaluation_dir.is_dir(),
        detection="rh",
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        primary_rule=primary_rule,
    )).run()
    return {
        "window": window.value,
        "evaluation_dir": str(evaluation_dir),
        "exit_code": int(result),
        "allowed_experiment_ids": list(allowed_ids),
        "import_receipt_count": len(imports),
    }


def main() -> None:
    if not os.environ.get("SLURM_JOB_ID") or int(os.environ.get("SLURM_CPUS_PER_TASK", "0")) != 32:
        raise RuntimeError("direct audit repair requires one 32-CPU Slurm allocation")
    frozen, commit = verify_freeze()
    exp = load_experiment(BUNDLE / "result20.yaml")
    if tuple(exp.outcome_audit["models"]) != PANEL:
        raise RuntimeError("audit panel differs from frozen v2.1 panel")
    check_shared_mount()
    credentials = dotenv_values("/home/aydanh/repos/rubric_gen/.env.local")
    for key in ("OPENAI_API_KEY", "ANTHROPIC_API_KEY"):
        if not credentials.get(key):
            raise RuntimeError(f"configured credential unavailable: {key}")
        os.environ[key] = str(credentials[key])

    study_dir = Path(str(exp.dag["revise"]["output_dir"]))
    output_dir = Path(str(exp.dag["detect"]["output_dir"]))
    study = load_detection_study(study_dir, exp)
    if len(study.revisions) != 120:
        raise RuntimeError(f"direct audit repair expected 120 revisions, found {len(study.revisions)}")
    owner = RUN / "owners" / f"direct-repair-{os.environ['SLURM_JOB_ID']}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    owner.mkdir(parents=True, exist_ok=True)
    launch = {
        "kind": "audit_only_direct_repair",
        "job": os.environ["SLURM_JOB_ID"],
        "host": socket.gethostname(),
        "commit": commit,
        "freeze_sha256": sha(BUNDLE / "execution-freeze.json"),
        "failed_audit_job": "10397985",
        "reason": "imported producer manifests have explicit producer experiment IDs; direct source validator otherwise rejects them",
        "scientific_changes": False,
        "provider_scope": "direct RH windows only; prior rubric/absolute/pairwise stages are reused",
        "consumer_study": str(study_dir),
        "audit_root": str(output_dir),
    }
    (owner / "launch.json").write_text(json.dumps(launch, indent=2) + "\n")

    # The failed run already completed the semantic stages. Verify their saved
    # plans/records before direct recovery; this is an audit boundary check, not
    # a new scientific gate or a request for additional judgments.
    targets_cfg = EvaluationConfig(
        experiment=exp,
        study_dir=study_dir,
        paraphrase_dir=Path(str(exp.dag["paraphrase"]["output_dir"])),
        output_dir=output_dir / "rubric_score",
        max_concurrency=32,
        resume=True,
    )
    targets = load_evaluation_targets(targets_cfg)
    RubricScoreRunner(targets_cfg, targets).preflight()
    RubricFreeScoreRunner(
        EvaluationConfig(**{**targets_cfg.__dict__, "output_dir": output_dir}),
        targets,
    ).preflight()

    windows: list[dict[str, object]] = []
    for window in WINDOWS:
        print(json.dumps({"stage": "direct_repair", "window": window.value}), flush=True)
        windows.append(_direct_window(exp, study, study_dir, output_dir / f"direct_{window.value}", 32, window))
    (owner / "windows.json").write_text(json.dumps(windows, indent=2) + "\n")

    sys.path.insert(0, str(ROOT / "scripts/diagnostics"))
    from check_audit_coverage import check
    coverage = check(study_dir, output_dir, expected_models=PANEL)
    (owner / "coverage.json").write_text(json.dumps(coverage, indent=2) + "\n")
    completion = {
        "success": True,
        "commit": commit,
        "owner": str(owner),
        "audit_adapter": "consumer-import-producer-experiment-id-v1",
        "reused_failed_audit_job": "10397985",
        "coverage": coverage,
        "experiment_id": exp.experiment_id,
        "frozen_files_sha256": frozen["files"],
    }
    (RUN / "completion.json").write_text(json.dumps(completion, indent=2) + "\n")
    print(json.dumps({"stage": "complete", "coverage": coverage}), flush=True)


if __name__ == "__main__":
    main()
