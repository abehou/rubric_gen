# One training-feedback refinement after failed support

## Evidence and hypothesis

The canonical60-assignment census shows255/395online candidates failing support;254involve their own citations.119have some supported own citations. A generic self-check citation prompt already failed. Hypothesis: actual independent application feedback on exposed training pairs can help repair scope/provenance where an unaided instruction could not.

## Frozen scope and single change

Use the previously fixed canonical Result20 contexts da-12-2/rep-003/generation3, da-15-8/rep-003/generation4 and da-15-7/rep-003/generation4. These are saved-case diagnostics, not the benchmark dev3 tier. The former da-12-4 anchor is ineligible for this policy trigger because it already admitted one criterion. No task or scientific assignment is excluded from a future Result20 evaluation.

Trigger: the update admitted no criterion and includes a criterion-support failure. Add one refinement attempt containing the previous failed candidate plus independent levels/reasons for its own cited induction pairs. Only artifacts and pair IDs already exposed in the original induction evidence may appear. Do not include hidden validation pairs, inherited pair assessments, aggregate-margin results, selected/heldout outcome scoring or RH labels. Treat application feedback as fallible; no automatic citation pruning.

Keep original Luna model/settings, native prompts except the refinement instruction, source artifacts, pair judgments, prior rubric, schemas, penalties and all admission gates. Newly proposed criteria receive fresh independent blind validation across the full original validation artifact set. No solver revisions, outcome audits or scoring.

## Reuse and acceptance gate

Reuse the corresponding completed fresh control cells from10370826 (all0admissions). Before calls, verify exact original induction request/model/schema identity and replay their native admission decisions. Validate that the feedback introduces no new artifact/pair evidence. Preserve all source hashes and controls. Run only3new refinement cells, with native application calls as needed; no regeneration of initial proposals or controls.

## Prospective decision and stop rule

Report all three cells, proposals, citations, semantic/support/margin failures, admissions, factual rationale inspection and runtime. Consider a behavioral decision only if at least2contexts obtain useful fresh admissions without invented distinctions or relaxed safeguards. Otherwise stop this candidate before revisions. A diagnostic gain is not RH/quality evidence; any later trace-only experiment requires a separate six-part decision and the existing joint RH/gap/quality endpoints. No automatic full workflow or confirmation launch.

Resources:1CPU4GiB45min;4cell workers, at most4native artifact workers per cell, shared aggregate60. New large outputs live under `/data/user_data/aydanh/rubric_gen/runs/cue-support-refinement-JOB`.
