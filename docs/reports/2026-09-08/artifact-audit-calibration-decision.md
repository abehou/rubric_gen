# Artifact calibration: decision after two matched diagnostics

Original final-artifact RH remains0% for both conditions. Evidencepromptv1 gave4.17%static/5.83%trace; calibratedv2 gives3.33%static/4.17%trace. The small final-artifact differences do not establish mitigation or a reliable adverse effect. Both versions and all raw judgments remain separate from the unchanged primary detector.

V2 removes the independently disproven p-value argument from trace da12-2rep1 (score8→6; remaining rationale cites other inconsistencies), and reduces trace da15-8rep1 score8→2. The latter's task-description conflict is real: the workbook labels MOESM2 CSF, contradicting the task text. No benchmark correction or historical label alteration was made.

V2 took54.94seconds inside the audit runner and cost$8.9469625 observed, with240complete judgments and zero revision reruns. The reports retain abstentions, every score transition and task-bootstrap uncertainty. Higher sensitivity alone does not validate the detector; these remain development diagnostics.

## Next decision

Stop broad detector prompt iteration for now. The main experiment already shows a clear full-trajectory reduction20→7.5% with no clear matchedqualitydifference, while the artifact evidence repeatedly exposes mismatches among displayed code, claimed exact exports, result tables and final answers. Improve the artifact-producing policy, not the labels, if those contradictions persist.

The current evidence-support sidecar prompt is already aimed at unsupported computation in general. A minimal next candidate should narrow its synthetic defect to a concrete cross-file contradiction between an asserted exact rerun/export and the final reported table/answer, preserving otherwise correct computation and task content. Change only that sidecar prompt; keep the current cue simulator and contrast proposer as controls. Require useful admitted criterion exposure and inspect whether the actual discrepancy decreases; do not conflate any lower penalty-adjusted W_train with better quality. This is a proposed next test, not yet implemented or launched.

Reuse all existing static revisions/audits and the completed trace comparison. Existing direct-Result20 authorization permits a new matchedtrace condition on original20tasks×3replicates after focused runtime/sourcevalidation. Continue original primary audits and keep calibrationv2 as a separately labeled sensitivity endpoint, rather than silently replacing evaluator semantics. No30/45scale-up or runs cleanup yet.
