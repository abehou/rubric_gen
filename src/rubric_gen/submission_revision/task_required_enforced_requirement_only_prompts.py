"""Fresh identity for requirement-only delivery of enforced task obligations."""

from rubric_gen.artifacts.hashing import sha256_text
from . import task_required_enforced_prompts as _base


PROMPT_VERSION = "attack_defense_v2.1_task_paraphrase_required_enforced_requirement_only"
ATTACK_V2 = _base.ATTACK_V2
LOCATOR_REPAIR_V2 = _base.LOCATOR_REPAIR_V2
CORRECTIVE = _base.CORRECTIVE
ANTICIPATORY = _base.ANTICIPATORY
STAGES = _base.STAGES


def prompt_hashes():
    return {name: sha256_text(value) for name, value in {
        "attack": ATTACK_V2, **STAGES, "locator_repair": LOCATOR_REPAIR_V2,
        "corrective": CORRECTIVE, "anticipatory": ANTICIPATORY,
    }.items()}
