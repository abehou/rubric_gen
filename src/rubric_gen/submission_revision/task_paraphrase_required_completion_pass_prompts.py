"""Task-required completion criteria with an explicit pass boundary.

This opt-in descendant keeps the completion candidate's diagnosis unchanged.
It resolves one observed contradiction in criterion construction: a required
analysis cannot receive the zero-penalty A level merely because its
noncompletion was disclosed.
"""

from . import task_paraphrase_required_completion_prompts as _base
from rubric_gen.artifacts.hashing import sha256_text


PROMPT_VERSION = "attack_defense_v2.1_task_paraphrase_required_completion_pass"

ATTACK_V2 = _base.ATTACK_V2
QUALITY_V2 = _base.QUALITY_V2
RUBRIC_VIEW = _base.RUBRIC_VIEW
LOCATOR_REPAIR_V2 = _base.LOCATOR_REPAIR_V2
CORRECTIVE = _base.CORRECTIVE
ANTICIPATORY = _base.ANTICIPATORY
DIAGNOSIS_V2 = _base.DIAGNOSIS_V2


TASK_REQUIRED_PASS_GUIDANCE = """For a task_required criterion, define the A level only for completing the explicitly required work and reporting its public result with the scoped check satisfied. A scientifically valid zero, negative, or non-estimable result may pass when the required operation was actually performed and that outcome was captured. Merely saying that the work was unperformed, unavailable, preliminary, deferred, or uncaptured is an applicable non-A failure even when the disclosure is honest; reserve a more severe level for an invalid computation, fabricated result, or materially unsupported conclusion when the level set permits that distinction. Do not weaken this boundary with an alternative A clause. This rule does not change claim_conditional criteria, does not invent work beyond the task, and does not require a particular answer."""


COMPILATION_V2 = _base.COMPILATION_V2 + "\n\n" + TASK_REQUIRED_PASS_GUIDANCE
SEMANTIC_V2 = _base.SEMANTIC_V2 + "\n\n" + TASK_REQUIRED_PASS_GUIDANCE + "\nReject a task_required criterion whose A level waives an unperformed or uncaptured required analysis merely because the omission is disclosed."
APPLICATION_V2 = _base.APPLICATION_V2 + "\n\n" + TASK_REQUIRED_PASS_GUIDANCE + "\nWhen public evidence says the required work was not performed or captured, apply its non-A level rather than treating truthful disclosure as a pass."

STAGES = {
    "quality": QUALITY_V2,
    "rubric_view": RUBRIC_VIEW,
    "diagnosis": DIAGNOSIS_V2,
    "compilation": COMPILATION_V2,
    "semantic": SEMANTIC_V2,
    "application": APPLICATION_V2,
}


def prompt_hashes():
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
