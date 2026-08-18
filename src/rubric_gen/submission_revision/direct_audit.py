"""Run the direct reward-hacking panel on a completed revision study."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from rubric_gen.reward_hacking.protocol import PRIMARY_RH_MODELS
from rubric_gen.reward_hacking.runner import (
    RewardHackingJudgeConfig,
    RewardHackingJudgeRunner,
)
from rubric_gen.submission_revision.audit_evidence import revision_audit_source
from rubric_gen.submission_revision.experiment import load_experiment
from rubric_gen.submission_revision.study import resolve_study_experiment


@dataclass(frozen=True)
class DirectAuditConfig:
    study_dir: Path
    output_dir: Path
    max_concurrency: int
    resume: bool
    base_urls: dict[str, str]
    detection: str = "rh"


@dataclass(frozen=True)
class AuditStudy:
    revisions: tuple[Path, ...]
    experiment_id: str
    tasks_dir: Path
    protocol: dict[str, object]


def load_audit_study(study_dir: Path) -> AuditStudy:
    """Validate a terminal study and return its completed revisions."""

    source = study_dir.resolve()
    study_path = source / "study.json"
    try:
        study = json.loads(study_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid randomized benchmark study: {source}") from exc
    if (
        study.get("kind") != "rubric-gen-randomized-revision-study"
        or study.get("status") not in {"completed", "failed"}
        or type(study.get("experiment_path")) is not str
        or type(study.get("experiment_id")) is not str
        or type(study.get("seed_run_dir")) is not str
        or type(study.get("paraphrase_run_dir")) is not str
    ):
        raise ValueError(f"unsupported benchmark study: {source}")

    experiment = load_experiment(Path(str(study["experiment_path"])))
    if study["experiment_id"] != experiment.experiment_id:
        raise ValueError(f"benchmark study experiment ID changed: {source}")
    records = study.get("records")
    if not isinstance(records, list) or any(
        not isinstance(item, dict) for item in records
    ):
        raise ValueError(f"benchmark study has invalid records: {source}")
    assignments = {
        str(item["assignment_id"]): item for item in experiment.assignments
    }
    record_ids = [str(record.get("assignment_id")) for record in records]
    if len(record_ids) != len(set(record_ids)) or set(record_ids) != set(assignments):
        raise ValueError(f"benchmark study ledger differs from its experiment: {source}")

    revisions: list[Path] = []
    for record in records:
        status = record.get("status")
        if status not in {"completed", "failed", "invalid"}:
            raise ValueError(
                "benchmark study must reach a terminal boundary before audit: "
                f"{source}"
            )
        if status == "completed":
            assignment = assignments[str(record["assignment_id"])]
            revisions.append(
                resolve_study_experiment(source, record, assignment).resolve()
            )
    if len(revisions) != len(set(revisions)):
        raise ValueError("duplicate benchmark revision experiment")
    if not revisions:
        raise ValueError("benchmark study has no completed assignments to audit")
    return AuditStudy(
        revisions=tuple(revisions),
        experiment_id=experiment.experiment_id,
        tasks_dir=experiment.tasks_dir.resolve(),
        protocol=experiment.outcome_audit,
    )


def run_direct_audit(config: DirectAuditConfig) -> int:
    """Run the study's sealed direct audit protocol."""

    study = load_audit_study(config.study_dir)
    models = tuple(config.base_urls) if config.base_urls else PRIMARY_RH_MODELS
    expected_models = tuple(study.protocol.get("models", ()))
    if models != expected_models:
        raise ValueError(
            "selected detector models differ from experiment.yaml: "
            f"selected={models!r}, expected={expected_models!r}"
        )

    primary_rule = str(study.protocol["primary_rule"])
    max_retries = int(study.protocol["max_retries"])
    max_input_tokens = int(study.protocol["max_input_tokens"])
    max_output_tokens = int(study.protocol["max_output_tokens"])
    max_event_text_chars = int(study.protocol["max_event_text_chars"])
    max_command_output_chars = int(study.protocol["max_command_output_chars"])
    max_cost_usd = float(study.protocol["max_cost_usd"])
    execution = str(study.protocol["execution"])
    mode = "vllm" if config.base_urls else "ensemble"
    identity = (
        f"{mode}--detect-{config.detection}--source-{study.experiment_id}"
        f"--mc-{config.max_concurrency}"
        f"--mi-{max_input_tokens}--budget-{max_cost_usd:g}"
        f"--mo-{max_output_tokens}--me-{max_event_text_chars}"
        f"--mco-{max_command_output_chars}"
        f"--exec-{execution}--primary-{primary_rule}"
    )
    evaluation_dir = _evaluation_dir(
        config.output_dir,
        identity,
        resume=config.resume,
    )
    resume_evaluation = config.resume and evaluation_dir.is_dir()
    source = revision_audit_source(
        study.revisions,
        tasks_dir=study.tasks_dir,
        experiment_ids=(study.experiment_id,),
    )
    result = RewardHackingJudgeRunner(RewardHackingJudgeConfig(
        source=source,
        models=models,
        base_urls=config.base_urls,
        output_dir=evaluation_dir,
        max_concurrency=config.max_concurrency,
        max_retries=max_retries,
        resume=resume_evaluation,
        detection=config.detection,
        max_input_tokens=max_input_tokens,
        max_output_tokens=max_output_tokens,
        max_event_text_chars=max_event_text_chars,
        max_command_output_chars=max_command_output_chars,
        max_cost_usd=max_cost_usd,
        execution=execution,
        primary_rule=primary_rule,
    )).run()
    print(f"Wrote direct reward-hacking judgments: {evaluation_dir / 'summary.json'}")
    return result


def _evaluation_dir(root: Path, identity: str, *, resume: bool) -> Path:
    evaluations = root.resolve() / "evaluations"
    if resume:
        candidates = sorted(evaluations.glob(f"*--{identity}"))
        if candidates:
            return candidates[-1]
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    return evaluations / f"{timestamp}--{identity}"
