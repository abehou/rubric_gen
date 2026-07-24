"""Stable, lazily loaded interfaces for BiomniBench experiments."""

from __future__ import annotations

import importlib


_MODULE_EXPORTS = {
    ".agent.adapters": (
        "AgentAdapter",
        "AgentAdapterRegistry",
        "ClaudeAdapter",
        "CodexAdapter",
        "GeminiAdapter",
    ),
    ".agent.prompts": (
        "NO_WEB_POLICY",
        "PROMPT",
    ),
    ".agent.models": (
        "AgentRunConfig",
        "BatchRunConfig",
        "BatchRunPaths",
        "RunPaths",
    ),
    ".agent.costs": (
        "GEMINI_API_PRICING_SOURCE",
        "GEMINI_COST_SOURCE",
        "GEMINI_STANDARD_PRICES_PER_MILLION",
        "RunCost",
    ),
    ".agent.workspaces": (
        "CompletedRunIndex",
        "TaskCatalog",
        "TaskWorkspace",
    ),
    ".agent.events": (
        "event_text",
    ),
    ".utils.paths": (
        "resolve_project_path",
    ),
    ".utils.progress": ("PROGRESS_BAR_FORMAT",),
    ".judging.runner": (
        "BiomniBenchJudgeRunner",
    ),
    ".judging.models": (
        "DEFAULT_JUDGE_MODEL",
        "JudgeAttempt",
        "JudgeRunConfig",
        "JudgeTarget",
        "ResolvedRubric",
        "SCORE_INPUT_ATTESTATION_KEYS",
        "SCORE_VALIDATION_KEYS",
        "SCORE_VALIDATION_SCHEMA_VERSION",
        "safe_basename",
    ),
    ".integrations.gemini": ("DEFAULT_GEMINI_API_KEY_ENV",),
    ".perturbation.models": (
        "DEFAULT_PERTURBER_MODEL",
        "DEFAULT_PERTURBATION_LEVELS",
        "DEFAULT_PERTURBATION_MAX_CONCURRENCY",
        "PERTURBATION_LEVELS",
        "PerturbationRequest",
        "PerturbationResult",
        "PerturbationRunConfig",
    ),
    ".perturbation.gemini": ("GeminiPerturber",),
    ".perturbation.runner": ("BiomniBenchPerturbationRunner",),
    ".rubrics.retrospective": (
        "GeminiProcessRubricRewriter",
        "ProcessRubricConfig",
        "ProcessRubricGenerator",
        "ProcessRubricRequest",
    ),
    ".rubrics.bundles": (
        "ResolvedRubricBundle",
        "resolve_rubric_bundle",
    ),
    ".agent.runners": (
        "AgentRunner",
        "BiomniBenchBatchRunner",
        "RunValidation",
    ),
    ".agent.sessions": (
        "CliSolverSessionDriver",
        "SessionTurnResult",
        "SolverSessionDriver",
    ),
    ".revision.feedback": (
        "FeedbackPolicy",
        "ProjectedFeedback",
        "project_feedback",
    ),
    ".revision": (
        "RevisionDependencies",
        "SubmissionRevisionConfig",
        "SubmissionRevisionController",
        "SubmissionRevisionResult",
        "run_submission_revision",
    ),
    ".revision.models": ("RevisionPhase", "RevisionState", "revision_experiment_dir"),
    ".utils.hashing": ("sha256_bytes", "sha256_file"),
    ".rubrics.compiler": (
        "GeminiTaskRubricRewriter",
        "TaskProcessRubricCompiler",
        "TaskRubricCompilerConfig",
        "TaskRubricRewriteResult",
        "TaskRubricRewriter",
        "TaskRubricRewriterProvenance",
    ),
    ".rubrics.prompts": ("TaskRubricRequest",),
    ".rubrics.schema": (
        "DataFileSnapshot",
        "RubricCriterion",
        "RubricLevel",
        "SchemaSnapshotLimits",
        "TaskAnchor",
        "TaskProcessRubric",
        "TaskSnapshot",
        "build_task_snapshot",
        "canonical_json",
        "load_json_strict",
        "parse_task_process_rubric",
        "render_task_process_rubric",
        "sha256_text",
        "structured_rubric_level_map",
        "validate_rendered_task_process_rubric",
        "validate_task_process_rubric",
    ),
    ".visualization.comparisons": (
        "JudgeComparisonConfig",
        "JudgeComparisonPlotter",
        "TaskJudgeComparison",
    ),
    ".forensics.reward_hacking": (
        "EvidenceCase",
        "RewardHackingAuditConfig",
        "RewardHackingAuditRunner",
        "evidence_case_prompt",
        "forensic_audit_prompt",
    ),
    ".commands": (
        "run_all",
        "run_compare_judges",
        "run_judge",
        "run_one",
        "run_perturb",
        "run_process_rubrics",
        "run_revise",
        "run_task_process_rubrics",
    ),
    ".cli": (
        "add_agent_args",
        "build_parser",
        "main",
    ),
}

_EXPORT_MODULE = {
    name: module_name
    for module_name, names in _MODULE_EXPORTS.items()
    for name in names
}
_SUBMODULES = {
    module_name.removeprefix("."): module_name for module_name in _MODULE_EXPORTS
}


def __getattr__(name: str) -> object:
    if name in _SUBMODULES:
        module = importlib.import_module(_SUBMODULES[name], __name__)
        globals()[name] = module
        return module
    module_name = _EXPORT_MODULE.get(name)
    if module_name is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(_EXPORT_MODULE) | set(_SUBMODULES))


__all__ = sorted(_EXPORT_MODULE)
