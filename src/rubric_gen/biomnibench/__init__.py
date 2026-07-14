"""BiomniBench terminal-agent experiment helpers."""

from __future__ import annotations

import importlib

from rubric_gen.biomnibench.adapters import (
    AgentAdapter,
    AgentAdapterRegistry,
    ClaudeAdapter,
    CodexAdapter,
    GeminiAdapter,
)
from rubric_gen.biomnibench.common import (
    NO_WEB_POLICY,
    PROGRESS_BAR_FORMAT,
    PROMPT,
    ROOT,
    AgentRunConfig,
    BatchRunPaths,
    BatchRunConfig,
    CompletedRunIndex,
    GEMINI_API_PRICING_SOURCE,
    GEMINI_COST_SOURCE,
    GEMINI_STANDARD_PRICES_PER_MILLION,
    RunCost,
    RunPaths,
    TaskCatalog,
    TaskWorkspace,
    event_text,
    resolve_project_path,
)
from rubric_gen.biomnibench.judges import BiomniBenchJudgeRunner, JudgeRunConfig, JudgeTarget
from rubric_gen.biomnibench.perturbations import (
    DEFAULT_PERTURBER_MODEL,
    DEFAULT_GEMINI_API_KEY_ENV,
    DEFAULT_PERTURBATION_MAX_CONCURRENCY,
    DEFAULT_PERTURBATION_LEVELS,
    PERTURBATION_LEVELS,
    BiomniBenchPerturbationRunner,
    GeminiPerturber,
    PerturbationRequest,
    PerturbationResult,
    PerturbationRunConfig,
)
from rubric_gen.biomnibench.process_rubrics import (
    GeminiProcessRubricRewriter,
    ProcessRubricConfig,
    ProcessRubricGenerator,
    ProcessRubricRequest,
)
from rubric_gen.biomnibench.runners import AgentRunner, BiomniBenchBatchRunner, RunValidation
from rubric_gen.biomnibench.session_drivers import (
    CliSolverSessionDriver,
    SessionTurnResult,
    SolverSessionDriver,
)
from rubric_gen.biomnibench.submission_feedback import (
    FeedbackPolicy,
    ProjectedFeedback,
    project_feedback,
)
from rubric_gen.biomnibench.submission_revision import (
    SubmissionRevisionConfig,
    SubmissionRevisionResult,
    run_submission_revision,
)
from rubric_gen.biomnibench.task_rubric_compiler import (
    GeminiTaskRubricRewriter,
    ResolvedRubricBundle,
    TaskProcessRubricCompiler,
    TaskRubricCompilerConfig,
    TaskRubricRequest,
    TaskRubricRewriteResult,
    TaskRubricRewriter,
    TaskRubricRewriterProvenance,
    resolve_rubric_bundle,
)
from rubric_gen.biomnibench.task_rubrics import (
    DataFileSnapshot,
    RubricCriterion,
    RubricLevel,
    SchemaSnapshotLimits,
    TaskAnchor,
    TaskProcessRubric,
    TaskSnapshot,
    build_task_snapshot,
    canonical_json,
    load_json_strict,
    parse_task_process_rubric,
    render_task_process_rubric,
    sha256_text,
    structured_rubric_level_map,
    validate_rendered_task_process_rubric,
    validate_task_process_rubric,
)


_CLI_EXPORTS = frozenset({
    "add_agent_args",
    "build_parser",
    "main",
    "run_all",
    "run_judge",
    "run_one",
    "run_perturb",
    "run_process_rubrics",
    "run_revise",
    "run_task_process_rubrics",
})


def __getattr__(name: str) -> object:
    if name not in _CLI_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    cli = importlib.import_module(".cli", __name__)
    value = getattr(cli, name)
    globals()[name] = value
    return value


def __dir__() -> list[str]:
    return sorted(set(globals()) | _CLI_EXPORTS)


__all__ = [
    "AgentAdapter",
    "AgentAdapterRegistry",
    "AgentRunConfig",
    "AgentRunner",
    "BatchRunPaths",
    "BatchRunConfig",
    "BiomniBenchBatchRunner",
    "BiomniBenchJudgeRunner",
    "ClaudeAdapter",
    "CliSolverSessionDriver",
    "CodexAdapter",
    "CompletedRunIndex",
    "DataFileSnapshot",
    "DEFAULT_PERTURBER_MODEL",
    "DEFAULT_GEMINI_API_KEY_ENV",
    "DEFAULT_PERTURBATION_MAX_CONCURRENCY",
    "DEFAULT_PERTURBATION_LEVELS",
    "GeminiAdapter",
    "GeminiPerturber",
    "GeminiProcessRubricRewriter",
    "GeminiTaskRubricRewriter",
    "FeedbackPolicy",
    "JudgeRunConfig",
    "JudgeTarget",
    "GEMINI_API_PRICING_SOURCE",
    "GEMINI_COST_SOURCE",
    "GEMINI_STANDARD_PRICES_PER_MILLION",
    "NO_WEB_POLICY",
    "PERTURBATION_LEVELS",
    "PROGRESS_BAR_FORMAT",
    "PROMPT",
    "PerturbationRequest",
    "PerturbationResult",
    "PerturbationRunConfig",
    "ProcessRubricConfig",
    "ProcessRubricGenerator",
    "ProcessRubricRequest",
    "ProjectedFeedback",
    "ROOT",
    "ResolvedRubricBundle",
    "RubricCriterion",
    "RubricLevel",
    "RunCost",
    "RunPaths",
    "RunValidation",
    "SessionTurnResult",
    "SolverSessionDriver",
    "SubmissionRevisionConfig",
    "SubmissionRevisionResult",
    "SchemaSnapshotLimits",
    "TaskAnchor",
    "TaskCatalog",
    "TaskProcessRubric",
    "TaskProcessRubricCompiler",
    "TaskRubricCompilerConfig",
    "TaskRubricRequest",
    "TaskRubricRewriteResult",
    "TaskRubricRewriter",
    "TaskRubricRewriterProvenance",
    "TaskSnapshot",
    "TaskWorkspace",
    "BiomniBenchPerturbationRunner",
    "add_agent_args",
    "build_parser",
    "build_task_snapshot",
    "canonical_json",
    "event_text",
    "main",
    "load_json_strict",
    "parse_task_process_rubric",
    "project_feedback",
    "render_task_process_rubric",
    "resolve_project_path",
    "resolve_rubric_bundle",
    "run_all",
    "run_judge",
    "run_one",
    "run_perturb",
    "run_process_rubrics",
    "run_revise",
    "run_submission_revision",
    "run_task_process_rubrics",
    "sha256_text",
    "structured_rubric_level_map",
    "validate_rendered_task_process_rubric",
    "validate_task_process_rubric",
]
