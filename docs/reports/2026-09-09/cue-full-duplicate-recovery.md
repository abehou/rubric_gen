# Cue full-feedback trace: duplicate-evidence correctness recovery

## Verified failure and cause of omission

Job10379267 ended FAILED after45m57s. Terminal inventory10380122 establishes59completed assignments and exactly one failure, da-16-1replicate1. Source and sidecar workspace hashes repeat at checkpoints2and3. Artifact pairs are already deduplicated by content, but red-team evidence was appended once per checkpoint; the unique-pair validator rejected the second evidence entry. This is infrastructure-invalid coverage, not a scientific negative result.

The preceding checkout was intentionally pinned to0fbe0bb plus scoped reuse fix314ea3d. I used a restrictive diff allowlist to exclude experimental policy drafts but omitted the previously known duplicate-evidence fix30ae38e from that allowlist. Tests and source equality consequently validated an incomplete correctness baseline. That was an execution-preparation error, not a provider failure. No successful assignments will be rerun to repair it.

## Approved patch and source composition

30ae38e changes one file, contrasts.py, adding seven lines: create a represented-pair set and skip duplicate evidence entries after the existing matched-pair check. It retains the first chronological trace for a content-identical pair; every later raw sidecar stays sealed. Unique-pair inputs are unchanged. For repeated pairs there was no valid prior behavior—the history construction crashed. The patch changes no policy family, criterion generation/admission rules, scoring, weights, thresholds, prompts, solver feedback rendering or evaluator identity. It repairs the representation invariant rather than increasing or decreasing pair weight.

Execution branch babel-cue-full-recovery-20260909, commit7cf34ef, consists of0fbe0bb →314ea3d(reuse-only check and tests) → cherry-picked30ae38e. Exactly two source files differ from frozen cue: pretreatment_reuse.py and contrasts.py. No policy drafts from the dirty main worktree are used.84focused tests passed. A provider-free replay of the real failed history must additionally reproduce original failure at checkpoint3, preserve checkpoint2 exactly, and accept checkpoint3 under the fix before provider submission.

## Minimum recovery and compatibility boundary

The native final ledger identifies only da-16-1rep1 as incomplete. All59successful manifest/state pairs are hash-protected in investigation/cue-full-recovery-20260909/inventory.json. Their revisions are never restarted; their audits run under their real producing314ea3dcode, with the failed original explicitly retained in the ledger.

The correctness patch changes the native rubric-generation fingerprint. Provider-free native validation rejects the former learned-rubric cache (`completed rubric generation changed`). No identity is masked or rewritten. Only the failed cell will restart from its existing seed under the same frozen scientific protocol, with its learned starting rubric regenerated for that task. This may change the stochastic realization of learned criteria; it is not byte-identical learned-rubric reuse and must be disclosed in the final comparison. Task inventory, three seeds/replicates, selected/master/development/heldouts, simulator, solver, scoring and auditors are unchanged. A separate current-format recovery output preserves both source versions. Native assignment_selection contains exactly the failed assignment, so no successful assignment can enter the revision worker pool.

New output: /data/user_data/aydanh/rubric_gen/runs/result20-cue-full-recovery-20260909. Original59outputs remain under result20-cue-full-trace-20260909. Combine59+1only after exact60unique assignment coverage and120unique Sol/Opus audit rows are validated. Historical full-static and cue user-static/trace remain unchanged. No new scientific condition or policy variant is introduced.

## Recurrence prevention

Private scripts/babel/frozen_cue.py checks the entire scientific source/config/environment inventory against0fbe0bb, allowing only exact hashes for the approved reuse and duplicate fixes. It rejects the previous314ea3dcheckout specifically because30ae38e is absent, and rejects extra/unvalidated source files. This guard runs both in provider-free validation and immediately before provider credentials are loaded by the recovery launcher. The actual duplicate-history replay is a second required gate. Future frozen-cue recovery launches must use this guard rather than only matching a historical commit or broad allowlist; there is no new public CLI command or flag.

Diagnostic validation10380129 also encountered a private script named inspect.py shadowing Python's standard inspect module; it was renamed inventory_check.py. That diagnostic error and the cache-compatibility rejection happened before provider calls. Prior failure logs are preserved.
