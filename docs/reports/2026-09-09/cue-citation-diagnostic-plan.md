# Saved-input citation diagnostic

This implements the first gate in cue-citation-policy-decision.md. No revision, simulator, scoring or outcome-auditor work.

Use the frozen da12-4rep2g7 mechanism anchor plus three deterministically selected distinct tasks from the twenty supported replay cases: da12-2rep3g3, da15-8rep3g4, da15-7rep3g4. Selection is enriched for the diagnosed mechanism and cannot estimate a population acceptance rate.

For each context, compare a fresh frozen-prompt repeat with one appended citation-precision clarification. Reuse the exact recorded induction evidence/schema, prior rubric and pairwise comparisons. Model remains gpt-5.6-luna, low reasoning, the existing provider contract and output cap. Independently apply new criteria to each artifact using unchanged native validation instructions, then run every native admission check. Original outputs remain historical evidence. No automatic removal of citations or quality comparisons.

Eight induction cells. Validation uses one native independent call per relevant artifact when criteria are proposed; up to three same-request attempts per failed call, with backoff. Four concurrent cells with at most four independent validators each; all provider calls remain subject to the shared aggregate60 limiter. CPU-only4CPU8G30min, account-freepreempt/preempt_cpu_qos. Logs and responses stored under a new job-owned runs/cue-citation-diagnostic-JOBID directory; frozen source hashes checked at start/end.

Inspect proposed/accepted counts, exact support failures, tied/inverted citations and criterion content. A no-criterion output is no exposure, not successful mitigation. Continue toward revisions only if the clarification demonstrably addresses citation precision and yields useful criteria through unchanged safeguards across more than the mechanism anchor. Mixed or null diagnostic outcomes require further diagnosis; no automatic Result20 revision submission. Record every cell including failed calls and negative outcomes. This is not an RH/quality test or a new calibrated auditor.
