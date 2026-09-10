# Early evidence-sidecar mechanism: proposal succeeds, admission fails

2026-09-08. Both matched da-11-1 jobs are still running; this is not an efficacy result. The synthetic sidecar is excluded from natural RH outcomes.

In candidate job10363146, replicate2/checkpoint1, the sidecar adds a claim of three clustering reruns with mean adjusted Rand index0.94. The original artifact has no such claim. The altered trace displays one KMeans invocation and no rerun/ARI computation. The generator's separate explanation identifies this defect truthfully; the sealed sidecar has no input/output integrity errors.

Generation2 proposes **Evidence for completed computational claims**, citing the exact original-versus-sidecar pair. This establishes that the changed sidecar prompt can produce relevant proposal evidence without changing the solver prompt, RH detector or admission rules.

Blind validation recognizes the unsupported ARI claim but scores **both artifacts C**: it finds other unsupported computation claims in the original. The criterion consequently fails support on its cited pair and is not admitted. A second, broad quantitative-auditability criterion fails aggregate margins. Generation2 retains zero criteria.

The distinction matters: this is neither a missing sidecar nor a proposer that entirely ignores the desired mechanism. It is a broad criterion that also penalizes defects shared by the pair, so it cannot explain their quality difference. The admission rejection is consistent with the unchanged rules. Do not weaken admission or relabel this as exposure or mitigation.

If this pattern persists in the completed comparison, the next small candidate is contrast-specific proposal wording: isolate an observable defect that differs between cited artifacts and avoid making their shared defects saturate the same level. Existing online_contrast wording is relevant, but its old simulator settings must not be imported. Any follow-up should change one factor relative to this candidate and preserve current controls. No follow-up variant is launched on the strength of this single early case.

Hashed case provenance (local-only: `investigation/dev3-evidence-sidecar-20260908/early-admission-case.json`; hash recorded in the local-evidence manifest). The full matched outcome report will follow jobs10363145/10363146 as10363168.

## 19:44 EDT partial admission census

Across published online generations, the evidence-focused candidate has 19 criterion-support rejections, three aggregate-margin rejections and zero admissions. The current-trace control has four admissions, 36 support rejections, eight aggregate-margin rejections and one semantic rejection. These are proposal-decision counts, not independent assignments or RH outcomes; generations and exposure time differ while execution continues. All inspected generation data match their published manifest hashes.

This extends the early example: admission, rather than a lack of generated proposals, is currently the candidate's immediate bottleneck. It does not establish that every rejection has the same cause, nor that the candidate lowers or raises natural RH. Completed audits remain required. The next candidate, if the completed comparison confirms no exposure, should narrowly adjust proposal specificity while preserving blind admission and the matched simulator.

Partial census and hashed generation references (local-only: `investigation/dev3-evidence-sidecar-20260908/admission-checkpoint-1944.json`; hash recorded in the local-evidence manifest).
