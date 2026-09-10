# Cue citation-precision diagnostic: no admitted criteria

Job10370826; frozen base0fbe0bb, diagnostic implementationde36226. Four saved online contexts, fresh matched control versus the one citation clarification. No revisions or outcome audits.

| Task / replicate | Arm | Proposed | Admitted | Admission failures |
|---|---|---:|---:|---|
| da-12-4/rep-002 | control | 3 | 0 | {'aggregate_margin_failed': 2, 'criterion_support_failed': 1} |
| da-12-4/rep-002 | citation | 1 | 0 | {'criterion_support_failed': 1} |
| da-12-2/rep-003 | control | 1 | 0 | {'criterion_support_failed': 1} |
| da-12-2/rep-003 | citation | 1 | 0 | {'criterion_support_failed': 1} |
| da-15-8/rep-003 | control | 1 | 0 | {'aggregate_margin_failed': 1} |
| da-15-8/rep-003 | citation | 1 | 0 | {'criterion_support_failed': 1} |
| da-15-7/rep-003 | control | 1 | 0 | {'criterion_support_failed': 1} |
| da-15-7/rep-003 | citation | 1 | 0 | {'criterion_support_failed': 1} |

All8cells complete; 96successful provider calls, including88independent single-artifact validations;0recorded failures. Recorded validation payloads contain no pair/preference/provenance fields. Both arms keep frozen provider/model/settings, scoring and admission safeguards.

## Mechanism and decision

The clarification produces fewer candidates in da12-4 but does not turn the diagnosed citation behavior into effective exposure. Every modified-prompt candidate fails criterion support. Fresh controls also admit none; three control candidates pass initial support but fail global margin checks. This does not show that the new policy reduces or increases RH: no criteria are admitted in this diagnostic and no solver ran.

Stop this prompt candidate before revisions. Do not relax validation or claim success from shorter citation lists. The prior native replay operated on fixed original proposals and original application judgments; these fresh calls changed both proposals and their independently generated applications. Therefore this diagnostic cannot yet distinguish proposal variability from application-judge instability. The minimum next diagnostic is an exact saved-candidate validation repeat, preserving original candidate text and all original blind artifact inputs; no new induction, revision or outcome audit.

The contexts were selected for this failure mechanism, so these counts cannot estimate overall Result20 admission rates. Original outputs, fresh controls and all negative cells remain preserved.

[Prospective plan](cue-citation-diagnostic-plan.md) · [Policy decision note](cue-citation-policy-decision.md) · [Original native replay](rubric-cue-support-replay.md)

Result SHA256: `b44667d2cbc56bbfddfa066685a6f16cda77929be99ba03ded126d78fdcb1448`.
