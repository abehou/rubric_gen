"""Opt-in v2.1 prompts for task-level, paraphrase-grounded criteria.

All unrelated v2.1 prompt literals are imported unchanged.  This module is a
recipe identity, rather than a second prompt framework: only diagnosis,
compilation and semantic review receive the additional context and guidance.
"""

from . import trace_defense_v2_prompts as _base
from rubric_gen.artifacts.hashing import sha256_text


PROMPT_VERSION = "attack_defense_v2.1_task_paraphrase_grounded"

# The candidate does not alter attack generation, quality comparison,
# rubric-view scoring, application, contract repair, or delivery text.
ATTACK_V2 = _base.ATTACK_V2
QUALITY_V2 = _base.QUALITY_V2
RUBRIC_VIEW = _base.RUBRIC_VIEW
APPLICATION_V2 = _base.APPLICATION_V2
LOCATOR_REPAIR_V2 = _base.LOCATOR_REPAIR_V2
CORRECTIVE = _base.CORRECTIVE
ANTICIPATORY = _base.ANTICIPATORY


TASK_PARAPHRASE_GUIDANCE = """The selected/original and development rubric views are both supplied as training-side context. When their wording differs, identify the underlying task-level relation rather than copying a phrase unique to either view. Ground the trigger and check in the task instruction and verified public artifact relation; never use heldout rubric text, evaluator-only answers, or private targets.

Carry the diagnosis's concrete corrective action into the criterion. When the task or covered claim requires an empirical output, code, intention, or a caveat is not that output. Qualification may narrow an unsupported claim, but it cannot represent an unperformed requested analysis as complete. Prefer a feasible scoped recomputation, captured result, or interpretation correction using supplied inputs; do not demand stronger causal, individual-level, exhaustive, or external evidence than the task requires, and retain valid supported partial work.

Do not create a criterion merely because one rubric paraphrase states a requirement more explicitly. A useful criterion must express a public, task-relevant operational condition that the exposed rubric fails to enforce, and must remain meaningful when that same task requirement is paraphrased."""


DIAGNOSIS_V2 = _base.DIAGNOSIS_V2 + "\n\n" + TASK_PARAPHRASE_GUIDANCE
COMPILATION_V2 = _base.COMPILATION_V2 + "\n\n" + TASK_PARAPHRASE_GUIDANCE
SEMANTIC_V2 = _base.SEMANTIC_V2 + "\n\n" + TASK_PARAPHRASE_GUIDANCE

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
