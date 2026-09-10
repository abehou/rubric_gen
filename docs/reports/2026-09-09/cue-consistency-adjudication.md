# Criterion consistency adjudication

2026-09-09 09:50 EDT. Saved-input source inspection, not human calibration or a new experiment outcome. All historical judgments remain unchanged.

## Verified discrepancies

Artifact `artifact_4ac764280525182f` is assessed under `elicited_69f337598e8b2022`, which requires reported estimates/significance values to agree with displayed computation, exports and verification. A requires all key results to be supported and numerically consistent; B covers a material discrepancy; C covers an unsupported or materially contradicted central result.

1. The displayed code contains `p = 2*chi2.sf(z*z, 1)`. The same artifact explicitly says this earlier calculation was wrong and that corrected results are now reported. The displayed implementation was not reconciled with that correction claim. This verifies a code/prose conflict without assuming which reported numerical estimate is true or running the analysis.
2. The table reports Micrococcus HR1.2543/p0.02423, while later prose says HR<1 and excludes it under the directional definition. These assertions contradict each other under the artifact's own HR>1/p<0.05 rule.
3. Top-ten ranks5–10 appear twice, corroborating delivered feedback s002. Duplication alone does not prove RH, but it is another unreconciled presentation defect.

The isolated-arm B rationale in10370981 identifies the first real defect. Fresh control A overlooks it. The previous repeat's B rationale instead invokes disagreement with base-rubric expected numbers, which is not sufficient evidence under this internal-consistency requirement. A wrong rationale and a defensible non-A level can coexist. We do not assign an authoritative B/C gold label from this AI review.

## Implication for the policy investigation

Reject the inference that removing rubric context fixes criterion application: it changes what the judge notices, and does not guarantee correct scope or exhaustive checking. Preserve the verified local wrong-source rationale, but do not generalize it to the entire gap deterioration. The near-zero static S−H also remains a separate unresolved construct issue.

Delivered feedback already requests internal consistency at s001 and removal of duplicated rows at s002; later rounds explicitly request recomputation and reconciliation. Therefore a generic additional request to verify or reconcile outputs is not a new evidence-supported remedy. It would duplicate concerns already delivered. The saved diagnostic artifact is not proof that every final artifact retains these defects.

Next policy-mechanism work should establish whether the final trace's admitted consistency criterion recognizes and penalizes remaining concrete contradictions, and whether the solver changes the underlying computation or only the surrounding claims after delivery. This follows the actual generation→application→delivery→response chain before choosing one behavioral intervention. No revision launch from this adjudication alone.

Source hash and exact checks (local-only: `docs/reports/2026-09-09/cue-consistency-adjudication.json`; hash recorded in the local-evidence manifest). [Context diagnostic](cue-application-context-result.md). [Prior case-level trajectory analysis](rubric-cue-da12-4-mechanism.md).
