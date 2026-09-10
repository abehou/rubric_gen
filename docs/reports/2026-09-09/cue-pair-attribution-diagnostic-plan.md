# Pair-attribution diagnostic — preparation, not a revision launch

2026-09-09 15:43 EDT. The verified anchor has a factual A/B attribution reversal in the rubric-free pair assessment, despite correct program mapping. The completed single-edit census is still needed to select additional examples without judging their outcomes. This is distinct from failed citation clarification and rubric-context omission.

## Single candidate change

Append only to rubric-free **induction pair-assessment** instructions:

> Before comparing quality, resolve each pair's artifact_A and artifact_B references to their exact artifact_id entries. Check each claimed difference against that artifact's own text and unchanged context. In assessment_A and assessment_B, name the referenced artifact_id and quote the shortest relevant text supporting the distinction. Verify that your preference names the artifact supported by those assessments. A minus line belongs to A and a plus line to B in the supplied A-to-B diff; the diff alone does not establish which version is correct. If the evidence does not establish a quality difference, return tie.

No outcome-auditor modification. No new model, schema, threshold, scoring, candidate-admission, simulator, or solver behavior. This instruction may increase abstention/ties; that tradeoff must be reported, not counted automatically as success.

## Matched saved-input design

Use original complete pair-assessment contexts; do not silently replace a full-context control with a single-pair prompt. Freeze the source requests and hashes before new calls. Choose up to eight contexts from the numerical-edit inventory in deterministic source-path order, at most one per task/replicate; include the known anchor separately as a discovery case, not independent validation. Do not select according to their historical judge preference or RH outcomes.

Cross original versus candidate instructions with original versus swapped A/B presentation. Swapping must change references and regenerate the navigation diff together, leaving the artifact table, task, schema, and all other settings unchanged. Map returned preferences back to artifact IDs before comparison. The original-order control must match its saved request byte-for-byte; record the exact intentional mutations for the other three cells. Maximum36requests if eight independent contexts plus the anchor qualify; deduplicate anchor overlap. Preserve every failure and response.

Before launch, validate these transformations without providers on compute. Use the frozen producer's provider integration and model settings, shared aggregate60 cap, bounded local diagnostic workers, no credential output. Store requests/responses under an immutable `/data/user_data/aydanh/rubric_gen/` directory.

## Diagnostic endpoints and stop rule

Review literal source attribution independently of condition-level RH/gap ordering. Report correct/incorrect/ambiguous attribution, preference consistency under swapping, ties, invalid output, retries, and token usage. AI source review is not human calibration and cannot fulfill the artifact-auditor TODO. Contradiction checks do not establish the biological answer or globally optimal artifact.

Do not promote if the candidate only increases ties, does not improve verified attribution, introduces unsupported factual claims, or relies on weakening admission safeguards. With this small enriched set, favorable diagnostics justify at most a separately documented trace-only policy test; they do not prove RH reduction, solve static S−H, or justify confirmation. A future revision needs the existing six-part decision note and frozen primary RH/gap/quality gates. Reuse the completed static arm and all compatible starting material.
