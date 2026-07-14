"""Stable, lazily loaded interfaces for BiomniBench experiments."""

from __future__ import annotations

import importlib


_MODULE_EXPORTS = {
    ".adapters": (
        "AgentAdapter",
        "AgentAdapterRegistry",
        "ClaudeAdapter",
        "CodexAdapter",
        "GeminiAdapter",
    ),
    ".common": (
        "NO_WEB_POLICY",
        "PROGRESS_BAR_FORMAT",
        "PROMPT",
        "ROOT",
        "AgentRunConfig",
        "BatchRunConfig",
        "BatchRunPaths",
        "CompletedRunIndex",
        "GEMINI_API_PRICING_SOURCE",
        "GEMINI_COST_SOURCE",
        "GEMINI_STANDARD_PRICES_PER_MILLION",
        "RunCost",
        "RunPaths",
        "TaskCatalog",
        "TaskWorkspace",
        "event_text",
        "resolve_project_path",
    ),
    ".judges": (
        "BiomniBenchJudgeRunner",
        "JudgeRunConfig",
        "JudgeTarget",
    ),
    ".perturbations": (
        "DEFAULT_GEMINI_API_KEY_ENV",
        "DEFAULT_PERTURBER_MODEL",
        "DEFAULT_PERTURBATION_LEVELS",
        "DEFAULT_PERTURBATION_MAX_CONCURRENCY",
        "PERTURBATION_LEVELS",
        "BiomniBenchPerturbationRunner",
        "GeminiPerturber",
        "PerturbationRequest",
        "PerturbationResult",
        "PerturbationRunConfig",
    ),
    ".process_rubrics": (
        "GeminiProcessRubricRewriter",
        "ProcessRubricConfig",
        "ProcessRubricGenerator",
        "ProcessRubricRequest",
    ),
    ".rubric_bundles": (
        "ResolvedRubricBundle",
        "resolve_rubric_bundle",
    ),
    ".runners": (
        "AgentRunner",
        "BiomniBenchBatchRunner",
        "RunValidation",
    ),
    ".session_drivers": (
        "CliSolverSessionDriver",
        "SessionTurnResult",
        "SolverSessionDriver",
    ),
    ".submission_feedback": (
        "FeedbackPolicy",
        "ProjectedFeedback",
        "project_feedback",
    ),
    ".submission_revision": (
        "SubmissionRevisionConfig",
        "SubmissionRevisionResult",
        "run_submission_revision",
    ),
    ".task_rubric_compiler": (
        "GeminiTaskRubricRewriter",
        "TaskProcessRubricCompiler",
        "TaskRubricCompilerConfig",
        "TaskRubricRewriteResult",
        "TaskRubricRewriter",
        "TaskRubricRewriterProvenance",
    ),
    ".task_rubric_prompts": ("TaskRubricRequest",),
    ".task_rubrics": (
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
    ".visualizations": (
        "JudgeComparisonConfig",
        "JudgeComparisonPlotter",
        "TaskJudgeComparison",
    ),
    ".cli": (
        "add_agent_args",
        "build_parser",
        "main",
        "run_all",
        "run_compare_judges",
        "run_judge",
        "run_one",
        "run_perturb",
        "run_process_rubrics",
        "run_revise",
        "run_task_process_rubrics",
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
