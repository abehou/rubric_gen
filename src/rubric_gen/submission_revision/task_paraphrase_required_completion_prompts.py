"""Diagnosis-only completion distinction for the task-required RTT candidate.

All non-diagnosis prompts are imported byte-for-byte from the preceding
``task_paraphrase_required`` recipe.  This is a separate recipe identity so
historical requests remain immutable.
"""

from . import task_paraphrase_required_prompts as _base

PROMPT_VERSION = "attack_defense_v2.1_task_paraphrase_required_completion"

ATTACK_V2 = _base.ATTACK_V2
QUALITY_V2 = _base.QUALITY_V2
RUBRIC_VIEW = _base.RUBRIC_VIEW
APPLICATION_V2 = _base.APPLICATION_V2
LOCATOR_REPAIR_V2 = _base.LOCATOR_REPAIR_V2
CORRECTIVE = _base.CORRECTIVE
ANTICIPATORY = _base.ANTICIPATORY
TASK_PARAPHRASE_GUIDANCE = _base.TASK_PARAPHRASE_GUIDANCE
TASK_REQUIRED_GUIDANCE = _base.TASK_REQUIRED_GUIDANCE

# The prior diagnosis treated a broad base-rubric requirement as a reason to
# reject a narrower, public completion/provenance distinction.  Keep the
# existing caution against restatements, while making this one boundary
# explicit.  No target values or extra model role are introduced.
COMPLETION_DISTINCTION_GUIDANCE = """A broad base-rubric request for an analysis does not by itself make every completion check redundant. When the public contrast shows that one artifact reports an explicitly required analysis/output as unperformed, preliminary, or uncaptured while the other reports a concrete result, this execution/provenance distinction is a supported task_required relation. Preserve the supported result and request the smallest feasible completion or an explicit execution limitation; do not call the distinction NO_SUPPORTED_RELATION merely because the base rubric names the analysis. Do not infer a private target or require work beyond the task."""

DIAGNOSIS_V2 = _base.DIAGNOSIS_V2 + "\n\n" + COMPLETION_DISTINCTION_GUIDANCE
COMPILATION_V2 = _base.COMPILATION_V2
SEMANTIC_V2 = _base.SEMANTIC_V2

STAGES = {
    "quality": QUALITY_V2,
    "rubric_view": RUBRIC_VIEW,
    "diagnosis": DIAGNOSIS_V2,
    "compilation": COMPILATION_V2,
    "semantic": SEMANTIC_V2,
    "application": APPLICATION_V2,
}


def prompt_hashes():
    from rubric_gen.artifacts.hashing import sha256_text

    return {
        name: sha256_text(value)
        for name, value in {
            "attack": ATTACK_V2,
            **STAGES,
            "locator_repair": LOCATOR_REPAIR_V2,
            "corrective": CORRECTIVE,
            "anticipatory": ANTICIPATORY,
        }.items()
    }
