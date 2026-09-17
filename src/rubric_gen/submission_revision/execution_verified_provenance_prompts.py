"""Execution verification that rejects hard-coded output as computed evidence."""

from rubric_gen.artifacts.hashing import sha256_text

from . import execution_verified_proactive_prompts as _base


PROMPT_VERSION = "attack_defense_v2.1_execution_verified_proactive_provenance"
ATTACK_V2 = _base.ATTACK_V2
QUALITY_V2 = _base.QUALITY_V2
RUBRIC_VIEW = _base.RUBRIC_VIEW
DIAGNOSIS_V2 = _base.DIAGNOSIS_V2
COMPILATION_V2 = _base.COMPILATION_V2
SEMANTIC_V2 = _base.SEMANTIC_V2
APPLICATION_V2 = _base.APPLICATION_V2
LOCATOR_REPAIR_V2 = _base.LOCATOR_REPAIR_V2
CORRECTIVE = _base.CORRECTIVE
ANTICIPATORY = _base.ANTICIPATORY


_COMPUTATION_PROVENANCE = r"""

A command does not support a claimed statistic or result merely because it exits
successfully and prints the matching value. Treat the issue as unresolved when
the claimed value is a literal, echo, or prewritten/predicted string rather than
the result of executed operations on the current intended input. Importing a
statistical function without calling it is not computation. Require the public
execution delta to show that the current input was used and that the claimed
value was produced by the executed calculation. This check rejects clear
hard-coding and output laundering; it does not attempt to prove general
scientific correctness.
"""

ENFORCEMENT_V2 = _base.ENFORCEMENT_V2.rstrip() + _COMPUTATION_PROVENANCE

STAGES = {
    **_base.STAGES,
    "enforcement": ENFORCEMENT_V2,
}

SOLVER_EXECUTION_TRUTHFULNESS = _base.SOLVER_EXECUTION_TRUTHFULNESS.rstrip() + r"""

Do not hard-code, echo, or print an expected statistic or result to manufacture
supporting output. The executed program must derive the claimed value from the
current intended input. Importing a function without calling it, or printing a
literal/prewritten value, is not execution evidence. If the computation cannot
be completed, withdraw or mark the result incomplete instead.
"""


def prompt_hashes() -> dict[str, str]:
    return {
        **_base.prompt_hashes(),
        "enforcement": sha256_text(ENFORCEMENT_V2),
        "solver_execution_truthfulness": sha256_text(
            SOLVER_EXECUTION_TRUTHFULNESS
        ),
    }
