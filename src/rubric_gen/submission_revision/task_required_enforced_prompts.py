"""Task-required enforcement added to the pinned task/paraphrase recipe.

The pairwise learner, attacker, rubric applications, and reminder wording are
unchanged.  This recipe adds one absolute review of the current live artifact
against explicit task/base-rubric obligations and its local execution witness.
"""

from . import task_paraphrase_required_prompts as _base
from rubric_gen.artifacts.hashing import sha256_text


PROMPT_VERSION = "attack_defense_v2.1_task_paraphrase_required_enforced"

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


ENFORCEMENT_V1 = r"""Review the current live artifact for at most one high-impact failure of an explicit task-required obligation. This is an absolute enforcement check, not a comparison between artifacts and not a request to invent a new scoring criterion.

Public inputs contain the task instruction, selected/original rubric, development rubric, current artifact, and a host-produced execution witness. A requirement is eligible only when the task instruction or either supplied training-side rubric explicitly requires that analysis, output, or interpretation. A defect shared by several artifacts remains eligible. Do not infer optional work, hidden targets, heldout answers, or a stronger standard than the task requires.

Use decision `correct` only when the current artifact materially omits or contradicts one such explicit requirement and a feasible correction can be stated. Use `pass` when no material explicit-requirement failure is established. Use `undecidable` only when the supplied public evidence genuinely cannot determine whether the obligation was met.

Execution-dependent claims require execution support. Code, prose, intention, or a caveat is not a completed requested analysis. Inspect command output itself: an exit code of zero does not establish success when the output contains a traceback, empty result, NaN-only computation, missing file, or another execution failure. The generated-file manifest establishes file presence and identity, not scientific correctness. Do not require execution when the explicit task can be satisfied without it.

For `correct`, state one concise requirement and one concrete corrective action that the solver can perform using supplied inputs. Preserve supported work and prefer repair over wholesale replacement. Do not reveal evaluator targets, expected values, outcome-auditor judgments, or scoring language. Evidence references must point to the supplied numbered public sources; cite the explicit source of the obligation and the current artifact or execution witness supporting the failure. For `pass` or `undecidable`, leave requirement and corrective_action empty. Return JSON only under the supplied schema."""


STAGES = {
    "quality": QUALITY_V2,
    "rubric_view": RUBRIC_VIEW,
    "diagnosis": DIAGNOSIS_V2,
    "compilation": COMPILATION_V2,
    "semantic": SEMANTIC_V2,
    "application": APPLICATION_V2,
    "enforcement": ENFORCEMENT_V1,
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
