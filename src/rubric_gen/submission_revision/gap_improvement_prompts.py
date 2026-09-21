"""Result40 gap-improvement recipe with unchanged scientific prompts.

The recipe changes host-owned selection, delivery, and reasoning allocation.
Keeping the prompt text byte-identical to the promoted provenance recipe makes
those controller changes explicit instead of hiding a prompt intervention.
"""

from . import execution_verified_provenance_prompts as _base


PROMPT_VERSION = (
    "attack_defense_v2.1_execution_verified_proactive_provenance_gap_improvement"
)
ATTACK_V2 = _base.ATTACK_V2
QUALITY_V2 = _base.QUALITY_V2
RUBRIC_VIEW = _base.RUBRIC_VIEW
DIAGNOSIS_V2 = _base.DIAGNOSIS_V2
COMPILATION_V2 = _base.COMPILATION_V2
SEMANTIC_V2 = _base.SEMANTIC_V2
APPLICATION_V2 = _base.APPLICATION_V2
ENFORCEMENT_V2 = _base.ENFORCEMENT_V2
LOCATOR_REPAIR_V2 = _base.LOCATOR_REPAIR_V2
CORRECTIVE = _base.CORRECTIVE
ANTICIPATORY = _base.ANTICIPATORY
STAGES = _base.STAGES
SOLVER_EXECUTION_TRUTHFULNESS = _base.SOLVER_EXECUTION_TRUTHFULNESS


def prompt_hashes() -> dict[str, str]:
    return _base.prompt_hashes()
