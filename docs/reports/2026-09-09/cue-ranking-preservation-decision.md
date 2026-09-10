# Prospective ranking-preservation admission diagnostic

Preparation only. No changed trace revision is launch-ready.

## 1. Verified mechanism

Eleven of52frozen online aggregate-margin rejections lose some margin but preserve every affected strictly positive ordering. Current per-pair magnitude nondecrease is stricter than maintaining the correct preference. This can block a supplementary criterion that identifies a real local defect in an otherwise better artifact. Correctness of every underlying application is not assumed; first replay native decisions and inspect adverse and favorable cases.

## 2. Exactly one candidate change

For non-strict aggregate checks only, permit a decrease when both current and prospective margins are strictly positive. Keep the existing rule whenever the current margin is zero/negative; keep strict-improvement checks unchanged. Do not permit a positive ordering to become a tie or reversal. Semantic validation, provenance support, score floors, penalties, model identities and all other admission logic stay unchanged. Apply only online updates; preserve realized offline starting criteria.

## 3. Reuse

First reuse frozen proposals, applications, comparisons and prior generations for native replay. No provider calls. Reuse all static evidence and unchanged seeds/paraphrases/scoring/outcome definitions. Before behavioral launch, validate honest native reuse of offline starting material and fresh trace output identity; never forge compatibility metadata.

## 4. Why revisions would eventually be needed

Changed online admissions can change subsequent feedback and solver behavior. Saved replay measures exposure opportunity only. Only a modified trace arm would require new revisions and its affected downstream evaluation; static and shared pools are reused. No revision launch before replay and focused verification.

## 5. Prespecified success criteria

Retain the already prospective joint criteria in cue-citation-policy-decision.md: W−S and W−A both non-worsening versus frozen cue static; full-trajectory confirmed RH at least5percentage points lower, with paired task-bootstrap95% difference interval excluding zero for clear developmental evidence; holistic one-sided95% lower difference bound above−2. Report both auditors, bounds, W_train separately and all secondary decompositions. Artifact RH remains secondary under independently human-calibrated frozen measurement. No endpoint changes after seeing outcomes. The unresolved static S−H criterion remains unresolved.

## 6. Stop rule

Stop before revisions if native replay does not reproduce originals, breaks a protected ranking/strict gap check, adds no useful coverage, or honest starting-material reuse fails. Inspect new candidates rather than equating more admission with benefit. If a later trace arm fails joint criteria, preserve it and diagnose; no selective exclusions, relaxed thresholds, extra revision rounds or automatic scale-up.

## Implementation checkpoint

Native admission now has a default-off preserve_positive_margins option. RubricProposer applies it only to RED_TEAM_TRACE generations>1 and records preserve_positive_rank in their context; original and offline calls retain the old context/rule. Direct use on generation0 admission is rejected.95related tests and11new focused boundary/offline checks pass. Experiment protocol/config plumbing is still pending, so no existing condition enables this change and no new revision has launched.

## Experiment integration checkpoint

Optional `protocol.preserve_positive_margins: true` now selects the proposer opt-in, changes experiment identity, and records a matching revision manifest field. Recovery, study validation and audit target checks require that field only for the opt-in configuration; existing default manifests remain unchanged.113admission/reuse and210experiment/revision/evaluation tests pass. A matched frozen-cue source/config diff and launcher validation remain before trace-only execution.

## Concrete matched launch candidate

Scientific source: isolated branch babel-cue-ranking, commit1314fac, checkout runs/babel-code/result20-cue-ranking. Exact config: investigation/result20-cue-ranking-20260909/trace-results20.yaml. Restore cue simulator/red-team/induction wording and artifact-history construction in this isolated branch; do not use unrelated later main-branch simulator settings. Frozen cue source0fbe0bb remains the control.

The new arm runs only60user-simulator trace assignments (canonical20tasks×3replicates); existing static60assignments and their frozen scores/audits are reused. Seed/paraphrase pools unchanged. Explicit pretreatment_source consumes all20realized cue starting rubrics with original producer provenance and consumer receipts. Only preserve_positive_margins:true changes online scientific treatment. Native retry/identity/provenance plumbing is engineering support; no detector prompt/threshold change.

Matched-input validation10371494 must pass before submission. Isolated source passed182focused evolution/experiment/reuse tests. The existing stage launcher uses4CPUs128G, account-free preempt CPU48h, shared aggregate60 with retry/pacing/runtime monitoring, immutable ownership and native stage recovery. No seed or paraphrase generation stage runs. Audit-only artifact calibration remains independent/pending human labels.

All success and stop criteria above remain frozen. No automatic30/45scale-up from this run. Preserve adverse results and report actual additional criterion admission/exposure alongside W_train and selected-base W.
