"""Execution-truthfulness repair prompts for the v2.1 successor."""

from rubric_gen.artifacts.hashing import sha256_text

from . import task_required_enforced_prompts as _base


PROMPT_VERSION = "attack_defense_v2.1_execution_verified"
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


ENFORCEMENT_V2 = r"""Review the current live artifact for at most one high-impact execution-dependent contradiction involving an explicit task-required obligation. This is an absolute truthfulness check, not an artifact comparison and not a request to invent a scoring criterion.

Public inputs contain the task instruction, selected/original rubric, development rubric, current artifact, a host-produced cumulative execution witness, a host-produced execution delta since the preceding solver feedback, and, when present, the one unresolved prior issue. A requirement is eligible only when the task or either supplied training-side rubric explicitly requires that analysis, output, or interpretation. Do not infer optional work, hidden targets, heldout answers, or a stronger standard than the public task requires.

When a prior issue is present, assess it before anything else. It is resolved by execution only when the delta after its feedback shows a substantive new command that runs the current relevant code on the intended input, captures usable output or an output file, has no fatal error, empty result, all-NaN result, missing file, or contradiction, and the artifact's reported values agree with that output. A pasted code block, prose description, renamed file, grep, cat, file listing, or output from before the feedback is not fresh execution. If relevant code or analysis logic changed after an output was produced, that output is stale until the changed code is rerun. Use `resolved_execution` only with cited delta evidence.

The other legitimate resolution is `resolved_downgrade`: the artifact removes or clearly downgrades unsupported numerical/result claims, explicitly labels the requested analysis as unexecuted or incomplete, preserves supported work, and states the limitation. Do not force a solver to claim that an infeasible computation completed. Honest non-execution and withdrawal of unsupported significance are acceptable even when the task remains incomplete.

If the prior issue has neither fresh consistent execution nor an honest withdrawal, return `correct`, set `prior_issue_status` to `unresolved`, and repeat its requirement, defect, corrective action, supported-work instruction, and unavailable-environment action exactly. Update only the public-evidence summary as needed. Do not switch to a different issue because wording changed, code appeared, an ordinary score rose, another criterion was learned, or another file was named. If the prior issue resolves, return `pass` for this checkpoint; do not introduce a second issue in the same response.

When no prior issue exists, use `correct` only for one concrete, highest-impact contradiction. Supply: the explicit requirement; the current defect; specific public artifact/command/output evidence; one feasible corrective action; supported work to preserve; and instructions to withdraw or downgrade unsupported claims if the environment cannot complete the computation. The correction must be workspace-feasible and must not reveal evaluator targets, expected hidden values, outcome-auditor judgments, or scoring language.

Use `pass` when no material contradiction is established. Use `undecidable` only when there is no prior issue and the supplied public evidence genuinely cannot determine whether an obligation was met. For `pass` or `undecidable`, leave all solver-direction fields empty. Evidence references must cite the public source of the obligation and the current artifact/witness/delta that supports the decision. Return JSON only under the supplied schema."""


STAGES = {
    "quality": QUALITY_V2,
    "rubric_view": RUBRIC_VIEW,
    "diagnosis": DIAGNOSIS_V2,
    "compilation": COMPILATION_V2,
    "semantic": SEMANTIC_V2,
    "application": APPLICATION_V2,
    "enforcement": ENFORCEMENT_V2,
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
