# Experiment results index

## 2026-09-08 — Final Mac to Babel handoff

- 00:31 CST: Completed dev3 comparison: 24 assignments, 672 audit records, zero missing final work; no active dispatcher remains. [Babel handoff](docs/BABEL_HANDOFF.md) records exact configurations, outcome interpretation, raw transfer directories, credentials/setup assumptions and archived commands; no new experiment was launched for this checkpoint.


## 2026-09-08 — Static comparison complete

- 00:23 CST: All 24 corrected-wiring assignments and 672 Sol/Opus audit records pass strict coverage; all dispatcher PIDs have exited. Report: `investigation/static-neutral-20260907/REPORT.md`; exact prerequisite diff and acceptance: `investigation/selected-reference-wiring-20260907/VALIDATED_RESULT.md`.
- 00:23 CST: Full-feedback selected-minus-holdout is +2.81 control / −1.61 neutral on the matched mean, but control Sol −1.83 versus Opus +7.44 fails panel agreement; final-artifact RH is zero throughout and trajectory RH is confined to da-11-1. Keep wiring, do not adopt neutral as baseline, retain adverse outcomes and leave baseline unfrozen; no new or larger experiment dispatched.


## 2026-09-07 — Concurrency override

- 23:02 CST: User requires aggregate concurrency ≤16 and at most one audit study at a time. Further launches are held while the three already-active solver assignments settle; then only unfinished work resumes. Historical launch settings remain preserved, and the audit dispatcher now serializes studies under an exclusive lease.


## 2026-09-07 — Static neutral comparison

- 23:48 CST: Three studies pass complete 168-record coverage each. Control da-11-1 recovered five connection-failed judgments with 608 protected files unchanged; its process exited before the final neutral da-11-1 audit launched alone in session 56801 (`audit-06.log`) at the aggregate cap of 16.

- 23:29 CST: All 24 assignments completed; recovery preserved 916 files. Control da-11-1 audit runs alone in session 91788 (`audit-04.log`) at 16 workers; neutral da-11-1 remains queued, and both da-3-4 audits remain complete.

- 23:00 CST: Both da-3-4 studies pass strict 168-record Sol/Opus coverage. Two Opus quality SSL failures recovered in session 32214 with 617 saved files unchanged; session 10539 now resumes only the two initial control da-11-1 simulator SSL failures, protecting completed assignments and cached judgments.

- 22:41 CST: Control da-3-4 reached 6/6 validated assignments; its Sol/Opus audit runs in session 15179 (`audit-01.log`, `audit-01-launch.json`). Staggered studies each use 15 audit workers, keeping the aggregate ceiling at 60.

- 22:31 CST: Both included neutral smoke assignments completed and validated. Session 80878 now runs the remaining 22 assignments via `investigation/static-neutral-20260907/run_stage.py revise --attempt 1`; source/config hashes and launch PID are in `revise-01-launch.json`, with runtime frozen.

- 22:25 CST: The wiring checkpoint smokes both passed; receipts are in `investigation/selected-reference-wiring-20260907/smoke-results.json`. The approved static comparison is prepared in `investigation/static-neutral-20260907/manifest.json`; its first two neutral da-3-4/rep-001 assignments run as included smoke cases (session 83813), with 24 assignments total and unchanged Sol/Opus measurements.


## 2026-09-07 — Selected-reference prerequisite; live smoke blocked

- 22:03 CST: Evidence and exact task diff: `investigation/selected-reference-wiring-20260907/`; private checkpoint outputs: `runs/selected-reference-wiring-smoke-20260907-attempt02/`. These intentionally bounded acceptance attempts are not corrected-wiring controls or completed studies; all prior development results remain historical mixed-wiring evidence and unchanged.


## Current — Gemini remains credit-blocked, 2026-09-07 20:35 CST

The configured Gemini key is present, but a fresh minimal Gemini 3.8 Flash request returned HTTP429 `RESOURCE_EXHAUSTED` with depleted prepayment credits. No Results20 audit worker started. The existing Gemini-only checkpoint remains at146/240 full-trajectory scores for the four configured comparator conditions; all146 files match the prior hashes, and later direct and semantic stages have not started. Current diagnostic: `runs/biomnibench-results20-2026-09-06/provenance/gemini/current-access-diagnostic.json`; the preceding successful probe is preserved separately as `current-access-diagnostic-before-20260907-2030.json`.

## Completed — selected-reference mechanism diagnostic, 2026-09-07

The user explicitly authorized the exact pending payload and destinations. Audit session45843 exited0 with all 144/144 fixed references, 80 newly generated exact judgments and 64 exact historical reuses; no failure logs were written. The read-only native validation and analysis session15697 exited0, all64 pre-existing audit files remain byte-identical, and no experiment worker remains active.

Selected-reference feedback raised matched selected-minus-holdout only from -2.00 to -1.58 while quality rose from64.08 to66.00. OpenAI moved from -0.83 to+0.33, but Claude moved from -3.17 to-3.50. By task, headroom changed -1.83 to-1.22 on da-3-4 and -2.17 to-1.94 on da-11-1. This fails the approximately1.5 reproducible headroom gate and supports quality improvement rather than rubric-specific overoptimization; do not scale it into a multi-turn baseline.

Results: `runs/autonomous-dev3-20260907/selected-reference-one-turn/results.md` and `results.json`. Exact authorized scope: `investigation/autonomous-dev3-20260907/selected-reference/pending-audit-authorization.json`; current helper provenance: `native-layout-provenance.json` in the same directory. The diagnostic used only da-3-4/da-11-1 and the configured OpenAI/Anthropic judges; it included no held-out task, red-team run, or Results20 dispatch. The baseline remains unfrozen.

## Completed — static exposure calibration, 2026-09-07

Both predefined development tasks have 6/6 completed assignments and 168/168 validated judgments each, retaining all configured OpenAI and Anthropic results. Reports and matched contrasts: `investigation/autonomous-dev3-20260907/exposure-calibration/baseline-results.md` and `matched-contrasts.md`. Selected-minus-holdout is −3.42 full-static / −1.97 user-simulator-static; artifact any-detect is zero in both; trajectory any-detect is 0% / 50%. The baseline remains unfrozen.

- da-3-4 ID `biomnibench-da-factorial-r10-f1268754291f`, root `runs/autonomous-dev3-20260907/exposure-da-3-4`.
- da-11-1 ID `biomnibench-da-factorial-r10-ac19f8be2fe3`, root `runs/autonomous-dev3-20260907/exposure-da-11-1`; direct19603 and final quality recovery18736 exited0. Isolated rubric recovery preserved89 records; sequential quality recoveries preserved22,27,28 records respectively. Recovered simulated-user turn and ledger reconciliation preserved78 and816 files respectively.
- Both used Results20 minimum5/maximum10 revision budget, sealed seed/paraphrase/pre-treatment inputs and exact optimizer reuse. Source/config/provenance and recovery archives: `investigation/autonomous-dev3-20260907/exposure-calibration/`.
- The first da-3-4 preparation-only launch exited143 with all six assignments pending and is preserved under its initial identity; the two corrected IDs above own the complete calibration.

## Current — interrupted-thread recovery, 2026-09-07

- **da-3-4 complete:** 24 assignments / 526 judgments pass strict coverage, no model reruns. Receipt and metrics: `investigation/autonomous-dev3-20260907/resumption-20260907/da3-verified/`.
- **da-11-1 revisions complete:** 6/6 independently validated; five completed assignments preserved and only the failed judgment/final turn recovered. All 996 preservation hashes and 142 additional judgment-file hashes are unchanged. ID: `biomnibench-da-factorial-r3-ac929d893d67`; root: `runs/autonomous-dev3-20260907/baseline-da11/`.
- **Direct complete:** session 4187 exited0 at 48/48 scores; 149 authentic successful chunk responses are retained. All four windows pass strict coverage; final-artifact RH is zero. The longest full trajectory required 32 OpenAI / 36 Claude chunks.
- **Rubric complete:** session 20278 exited0; 90/90 plan/raw/summary bindings pass and prior 83 hashes are unchanged. Full-static two-task selected-minus-holdout is 1.69, with substantial auditor disagreement (0.11 versus 3.28).
- **Quality complete:** session 89672 exited0; all 18 absolute and 12 pairwise judgments pass raw/plan/summary checks, with all prior 29 records unchanged. Together with rubric scoring, all 120 semantic judgments are complete.
- Logs above are under `runs/autonomous-dev3-20260907/`. Recovery scripts, archives, hashes, tested operational repairs and the completed combined baseline gate are under `investigation/autonomous-dev3-20260907/resumption-20260907/`.
- The optimizer's existing retry cleanup removed original failed s002 stdout files; initial terminal log and pre-recovery SSL classification remain. Completed results are preserved. Details and the pending production retention repair are in CODE_REVIEW.md.
- **Combined baseline:** 694 judgments across both studies pass coverage. Full-static selected-minus-holdout is 1.69; user-simulator static is 0.44. Artifact any-detect is zero in both; trajectory any-detect is 33.33% / 50%. Report: `investigation/autonomous-dev3-20260907/resumption-20260907/baseline-results.md`.
- No baseline freeze or red-team optimization dispatch yet. Selected-feedback preparation reuses six saved development seed judgments without API calls; da-18-1 remains reserved. Current priority is at the top of EXPERIMENT_PLAN.md.

The checkpoints below are historical and superseded by this section. Invocation chronology is retained in EXPERIMENT_LOG.md.

## Baseline calibration — predefined second development task

Session 44479 runs `experiments/biomnibench-dev-baseline-da11.yaml` at c3: da-11-1, static/full and static/user-simulator, all three replicates (six assignments), unchanged method. ID `biomnibench-da-factorial-r3-ac929d893d67`; output root `runs/autonomous-dev3-20260907/baseline-da11`, log `baseline-da11.log`, provenance `investigation/autonomous-dev3-20260907/baseline-da11-provenance.json`. All three seeds are now complete and paraphrase generation is underway. Complements da-3-4 rather than replacing its negative result; da-18-1 remains reserved. Existing da-3-4 audits continue in session 91217; runtime remains frozen across both.

## Current autonomous dev3 state — cache integration repair

Session 92179 ended with 23/24 completed assignments and one transient simulated-user connection failure. Recovery session 91217 completed all 24/24 revisions and all audit stages, then exited1 for one OpenAI final-artifact connection failure. Session63779 recovered the direct gap but exited1 on Anthropic SSL errors; session67938 filled remaining rubric-free jobs, but token-count preparation marked a previously completed direct case failed; session4608 also exited1; session10110 now resumes at c2 with bounded process-local token-count retries (`isolation-cachefix-smoke-recovery-05.log`). The prior recovery used c2 (48 absolute+37 pairwise saved of90 planned), log `isolation-cachefix-smoke-recovery-03.log`; 507 saved result hashes are recorded in `audit-before-recovery02.json`, log `isolation-cachefix-smoke-recovery-02.log`. Both invocations use unchanged code, using the same frozen YAML with `--resume` at c4 and preserving completed work; log: `runs/autonomous-dev3-20260907/isolation-cachefix-smoke-recovery-01.log`. The original session ran `experiments/biomnibench-dev3-isolation-cachefix-smoke.yaml` at c4: 24 assignments, eight conditions × three replicates, da-3-4. Seeds and five paraphrases are reused from `isolation-readers-smoke`; current study/audit outputs are under `isolation-cachefix-smoke`, design ID `biomnibench-da-factorial-r3-3686c8965c2e`. The preceding session 71717 exposed a cache-directory validation bug after induction; all eight exact saved responses were replayed locally through the corrected workflow, with zero repeated API calls. 145 targeted/integration/architecture tests pass. Provenance and replay ledger: `investigation/autonomous-dev3-20260907/cachefix-provenance.json` and `pretreatment-rebuild.json`. Goal active; no efficacy claim yet.

The missing XLS reader defect is repaired and verified in actual Codex execution. Earlier invalid-environment seeds remain preserved and excluded together. Explicit raw dev3 export consent is recorded in EXPERIMENT_PLAN.md.

## Invalid-environment dev3 smoke — stopped 2026-09-07

Session 5855 ran `biomnibench-dev3-isolation-smoke.yaml` at c4, 24 expected da-3-4 assignments (eight conditions × three replicates), three revisions. Log: `runs/autonomous-dev3-20260907/isolation-smoke.log`; study/audit experiment ID `biomnibench-da-factorial-r3-3686c8965c2e`. Runtime/provenance frozen in `investigation/autonomous-dev3-20260907/isolation-smoke-provenance.json`. Current method change is isolated criterion validation with durable successful-call caching; 89 focused tests pass. This active goal supersedes the completed three-iteration checkpoint below.

## Latest optimization checkpoint — 2026-09-07

Three fixed-task iterations are complete. Report: [optimization report](investigation/optimization-20260907/REPORT.md). Outputs: `runs/optimization-20260907/iteration-01` (delivery), `iteration-02` (diff-assisted induction), `iteration-03` (static pressure calibration). Static pilot has 6/6 valid outputs, 90/90 matched OpenAI/Anthropic judgments, zero missing/abstaining cases; all 90 cache entries validate without new calls. 67 focused tests pass. Delivery improves but criterion and efficacy gates remain unmet; no full 20-task dispatch. Gemini remains paused for credits.

## Current authorization — optimization phase (2026-09-07)

The latest user instructions authorize implementation changes, focused tests, 1–2 task smokes and small matched optimization pilots, including sending BioMNIBench task instructions, rubrics, synthetic artifacts and traces to the existing OpenAI Luna proposer for induction/validation. OpenAI and Anthropic auditors are authorized where available; the earlier Anthropic pause is superseded and must not be treated as a current restriction. The user explicitly requested removal of these outdated restrictions after reviewing the two automatic-review rejection reasons.

Gemini remains paused for the documented depleted prepaid credits. Billing changes remain unauthorized; the latest autonomous-dev3 instruction authorizes model allocation changes. Preserve historical outputs and completed judgments; do not scale to 20 tasks before focused tests, smoke, matched coverage and mechanism gates pass. Current work and unresolved hypotheses are recorded in [investigation_log.md](investigation_log.md), under Optimization phase. Earlier dated checkpoints below are historical records, not current dispatch instructions.

## Current: OpenAI and Anthropic complete; Gemini awaiting prepaid credits

**Current 2026-09-07 09:32 CST: OpenAI and Anthropic complete.** All 14 Claude
gaps recovered; strict coverage passes all seven comparator stages (6,022
judgments). The complete 480-case 4×2 grid for both providers is in
`runs/biomnibench-results20-2026-09-06/reports/openai-anthropic-result-table.md`.
The standalone OpenAI table and verification evidence are also refreshed. Gemini remains at 146 saved direct
judgments, awaiting lab prepaid-credit restoration; its full goal is unfinished.

**Historical 2026-09-07 09:15 CST: Anthropic recovery authorized and running.**
Existing key passed a minimal Claude Opus 5 check. Session 73775/PID 58217
recovers only 14 missing Claude direct judgments at c1, preserving 1,906 saved
scores and completed semantic results. Gemini remains credit-paused.

**Goal status 2026-09-07 00:29 CST: blocked awaiting lab Gemini prepaid
credit restoration.** Full-grid completion is still required; 146 judgments
are preserved. No further provider requests or billing changes were made.

**Current 2026-09-07 00:29 CST: Gemini requests paused for depleted prepaid
credits.** Google returned explicit prepayment exhaustion at 00:28:09 CST;
owned worker stopped, session 75003 exit 143. All 146 saved judgments validate,
with the prior 60 unchanged. Location rejection recovered after cooldown.
Full completion goal remains active; lab billing action is required for further
Gemini requests. OpenAI complete; Anthropic remains paused.

**Historical 2026-09-07 00:01 CST: bounded Gemini recovery running.** User
explicitly approved cooldown/recovery instead of stopping on the first location
error. Session 75003, supervisor 6189/worker 6190, c1; 60 saved scores preserved.
Direct location errors receive 60/120-second cooldowns; three consecutive
location failures pause requests for diagnosis. Existing scoring attempt limits
remain unchanged; OpenAI complete, Anthropic paused.

**Historical 23:53 CST: goal blocked awaiting recovery-policy decision or access
resolution.** Local preparation is complete; 60 formal judgments are saved.
This status does not mean experiment completion or cancellation.

**Historical 23:51 CST: full Gemini completion goal reopened on user request.**
Independent acceptance preparation is now unblocked: all 16 saved Gemini direct
and 23 rubric records validate, the original rubric manifest matches exactly,
and only 2 rubric + 5 absolute + 4 pairwise acceptance judgments remain.
Formal audit remains at 60 saved scores. Recovery-policy clarification is pending;
no new provider request has been made in this investigation turn.

**Historical goal status 23:47 CST: blocked**, after three consecutive checks of the
same unresolved access failure. Full grid completion remains required.

**Latest 23:46 CST — c1 stopped on renewed location rejection:** Session 35572
ended with exit 143 after Google returned HTTP 400 `FAILED_PRECONDITION`,
“User location is not supported for the API use,” at 23:45:44.913 CST.
The supervisor stopped the worker within a second; neither PID remains.
One new judgment was saved: all 60 full-trajectory records validate, and all
59 prior score hashes are unchanged. No further retries under this launch.
The full Gemini grid remains incomplete, with lab/provider resolution pending;
OpenAI remains complete and Anthropic paused. Verification:
`provenance/gemini/c1-region-stop-verification.json` under the current run.

**Historical 23:44 CST — authorized Gemini c1 resume running:** User explicitly
approved controlled recovery and a goal covering the full 480-case, eight-arm
Gemini grid. Session 35572, supervisor 3531/worker 3532, started at 23:43:39 CST
with all 59 prior scores preserved and frozen source hashes checked unchanged.
Only missing Gemini judgments are scheduled; respect quota delays and stop on
a renewed location/access rejection. OpenAI remains complete; Anthropic paused.
Logs: `logs/gemini-c1-supervisor.log`, `logs/gemini-c1-resume.log`, and
`logs/gemini-c1-provider-errors.jsonl` under the current run root.
Earlier blocked checkpoints are historical; the full completion goal is active.

**Historical 23:25 CST — Gemini paused on renewed region rejection:** At
23:19:38.888 CST Google returned HTTP 400 `FAILED_PRECONDITION`, “User location
is not supported for the API use.” Supervisor 97438 stopped worker group 97440
at 23:19:39; session 82889 exited 143 and cooldown observer 1779 exited 0.
All 24 pre-resume scores remain unchanged; 59 full-trajectory scores are saved.
No further Gemini requests until the lab/provider confirms legitimate access is
restored. OpenAI remains complete; Anthropic remains paused.

The current key belongs to the lab and passed earlier metadata/generation checks;
this mixed behavior is not explained by an invalid key. Transport failures and
3M-input-tokens/minute quota errors are separately preserved. A sanitized
[lab support note](docs/gemini-lab-access-support-note.md) is prepared but unsent.
The scoped-acceptance planner is also waiting on two cloud-only input files.
The full Gemini objective remains incomplete; at 23:32 CST the goal is marked
blocked pending legitimate access resolution and cloud-file availability.
All 59 saved score hashes were rechecked unchanged; no API owner remains. Earlier running notes are historical.

**Historical 23:11 CST — Gemini recovery running at c2:** Initial c4 audit was
stopped after completed-job progress substantially exceeded saved scores; its
23 successful direct judgments and logs are archived in
`provenance/gemini/initial-audit-interruption.tar.gz`. One isolated missing job
then succeeded without retry. Existing `detect --resume` now runs at c2,
session 82889/supervisor 97438/worker 97440, preserving all 24 previous scores.
Operational observation logs provider errors without changing scoring code;
an external supervisor stops on a renewed permanent access rejection.
The earlier batch failures are not yet classified. Logs:
`logs/gemini-formal-resume.log`, `logs/gemini-provider-errors.jsonl`, and
`logs/gemini-resume-supervisor.log` under the current run root.
OpenAI remains complete; Anthropic remains paused. All Gemini stages and the
combined result table remain required before this goal is complete.

**Historical 23:05 CST — Gemini-only audit started:** User requested a new goal to
restore Gemini and complete its experiments, confirming that the existing key is
lab-provided. Unchanged credentials passed authenticated model lookup and one
minimal Gemini 3.8 Flash SDK generation; the earlier location failure is not
currently reproduced, and its original cause remains unproven. No key, account,
model or routing change was made.

Formal `detect` runs at c4, session 23809/PID 96594, using the existing
240 validated comparator revisions and a fresh Gemini-only audit directory.
Expected work is four direct windows plus rubric/absolute/pairwise scoring;
reuse prior completed acceptance evidence and all original red-team judgments.
OpenAI is complete; Anthropic remains paused until explicit balance confirmation.
Runtime is frozen; source archive SHA-256 `74400398aa1557b984ff7e8b9f3f6747d6725b13248509c49f8757b4d6f2b230`.
Log: `runs/biomnibench-results20-2026-09-06/logs/gemini-formal-audit.log`.
Audit: `runs/biomnibench-results20-2026-09-06/audit/static-offline-gemini/biomnibench-da-factorial-r10-2f13900fe0e7`.
The operational YAML now selects Gemini only; the prior two-model YAML bytes
are preserved in `provenance/gemini/before-gemini-experiment.yaml` under the run.

**Historical 22:56 CST — requested OpenAI-only report complete:** Verified all
960 OpenAI direct judgments and 2,051 OpenAI semantic judgments in the comparator
cohort without provider calls or judgment reruns. Combined with the prior verified
red-team results into the exact 480-case, eight-condition population; all consumed
historical inputs match their relocation-inventory hashes. The attempted whole-archive
recheck remains incomplete because some historical trajectories are cloud-only;
the saved original 9,327-judgment completion receipt is reused explicitly.
Anthropic remains paused with 14 direct gaps until the user explicitly confirms
restored balance; Gemini remains deferred. Production audit JSON and two-model
summaries are unchanged. The broader multi-provider grid remains incomplete.

Result: [OpenAI eight-condition table](runs/biomnibench-results20-2026-09-06/reports/openai-result-table.md),
[verification](runs/biomnibench-results20-2026-09-06/reports/openai-verification.json),
and [case metrics](runs/biomnibench-results20-2026-09-06/reports/openai-case-metrics.csv).

22:31 CST: Goal blocked awaiting Anthropic billing/access restoration; no recovery
process remains. Verified unchanged 1,906 direct scores, with exactly 14 Claude
gaps; all semantic summaries remain completed with zero failures. Resume full
coverage and final reporting after user confirms the external blocker is resolved.

22:30 CST: OpenAI-only isolated recovery 1508 exited 0; log
`logs/openai-isolated-direct-gap-recovery.log`. All 960 OpenAI raw direct scores
are present, with no Claude request, no summary rewrite and all prior hashes
unchanged. Only 14 Claude raw gaps remain; total direct scores 1,906/1,920.
Full-panel summaries and final tables still await Anthropic billing restoration.

22:28 CST: Renewed explicit Anthropic insufficient-credit errors in 71894's
terminal full-trajectory summary; paused later-window owner 39581 (exit 143)
to stop further Claude retries. Direct raw coverage is 1,903/1,920; all 4,102
semantic judgments remain verified complete. Checkpoint archive:
`provenance/scoped/direct-billing-pause-checkpoint.tar.gz`. Restore Anthropic
billing/access before further Claude calls; Gemini remains deferred.

22:20 CST: All semantic stages completed and independently verified (28973):
rubric 3,026, absolute 598, pairwise 478; final semantic recovery 33571 exited 0.
Direct recoveries remain live: 39581 handles post-update/later windows at c1;
71894 handles only full-trajectory at c4, log `logs/static-offline-full-trajectory-tail.log`.
Semantic stages must not be rerun; full direct coverage and final combined tables
remain pending.

22:10 CST: Semantic tail recovery is session 62087 at c2, log
`logs/static-offline-semantic-tail-recovery.log`; prior 79363 ended with 4,082
successful records preserved and 20 remaining semantic gaps. Direct recovery
39581 remains live in post-update preparation; full-trajectory raw coverage
472/480 and its terminal-summary discrepancy still need recovery.

21:51 CST: Main owner 69435 is terminal after quality-stage TLS EOF; absolute
530/598 and pairwise 449/478 saved, summaries absent. Semantic recovery now runs
as session 79363 at c4 in `logs/static-offline-semantic-recovery.log`, preserving
3,984 saved semantic records; direct recovery 39581/PID 76479 remains at c1.
Quality first-pass evidence: `provenance/scoped/quality-first-pass-before-recovery.tar.gz`.

21:39 CST: Main owner 69435 is now running absolute/pairwise quality scoring
(1,076 planned judgments). Rubric first pass ended 3,005/3,026 successful, with
21 failures (Claude 15, Sol 6); direct recovery 39581/PID 76479 remains live at c1.
Verified rubric archive: `provenance/scoped/rubric-score-first-pass-before-recovery.tar.gz`.
Use the existing semantic recovery helper only after the semantic writer ends.

20:47 CST: PID 69435 confirmed live at c20, now in rubric scoring (138/3,026
saved). Four direct first-pass panels have 1,829/1,920 scores; 52 Claude billing
failures and 39 connection failures need recovery, although later Claude scoring
is succeeding. Old session 88986 is no longer addressable; inspect the native PID
and artifacts instead of restarting. Revision remains complete and validated.

20:11 CST: Revision complete 240/240 at 20:08:52 (69480 exit 0); all cases pass
independent full validation across the 238-case and final-two logs. Audit now runs
at c20, session 88986 / PID 69435, helper 69436, in
`audit/static-offline-openai-anthropic/biomnibench-da-factorial-r10-2f13900fe0e7`.
Log: `logs/static-offline-openai-anthropic-audit.log`; first direct plan 480 jobs.
All seven Sol/Claude stages remain required; original red-team audits are reused.


20:01 CST: All 238 completed comparators pass independent full validation
(70172 exit 0; `logs/comparator-completed-revision-validation.log`). Two static
cases remain running in 69480; comparator audit not started.

19:54 CST: 235/240 comparators complete, four running, one previous failure queued;
no new case-level failure in session 69480. New comparator audit has not started.

19:45 CST: New recovery session 69480 / PID 64064, helper 64065, c4; four cases
dispatched at 19:44:45 after CLI validation. Current log is
`logs/static-offline-resume-runtime-ready.log`. Previous 59440 exited 143 after
local import stalls; the subsequent failed Finder tool call consumed ~55 minutes
with no experiment running. SDK/judge import checks now pass; previous invocation
archive is `provenance/scoped/runtime-import-interruption.tar.gz`, SHA-256
`f6b4de893d3bfb51ae3460787c12d228ce7858e68857a9ef4a7d314d746c5345`.

18:38 CST: CLI validation passed and recovery actually dispatched at 18:36:12.
Session 59440 remains live: 230 complete, four running, six prior failed cases
awaiting recovery dispatch; max concurrency 4. No completed cases were restarted.

18:34 CST: All nine failed cases pass after exact-byte seed recovery (22276 exit 0),
bringing completed-case validation coverage to 230/230. Four original unavailable
files are preserved in `provenance/scoped/icloud-placeholder-evidence/`; no saved
hashes or identities changed. Supported c4 resume is live, session 59440 / PID
56730, helper 56731; log `logs/static-offline-resume-after-local-recovery.log`.
Frozen source/config comparison passes all 225 non-bytecode members.


18:21 CST: Full replay ended 221 passed / nine failed, concentrated in three shared
seeds. Individual dataless-file download requests completed (session 18674 exit 0),
logged in `logs/local-artifact-downloads.log`; readiness and failed-case replay
are next. Requests alone do not prove successful materialization.

18:19 CST: Identified an iCloud `dataless` seed trajectory; downloading it through
native FileManager restored the exact expected hash. Requested local availability
for the required data, seed and current-study directories (~0.324 GiB dataless).
Validation session 90127 continues; recheck its pre-download failures afterward.

18:13 CST: Trajectory scan passed all 1,503 snapshots. Serial replay 54726 was
stopped (143) and replaced by identical eight-way read-only validation, session
90127; `logs/completed-case-integrity-check.log` has four full-case passes so far.
No model requests or result edits occurred during this diagnostic change.

18:03 CST: Recovery session 52978 exited 1 during completed-result validation,
before new dispatch, on a trajectory snapshot hash mismatch. Read-only scan
58282 and independent completed-case replay 54726 are live; the first completed
case currently passes both chunked and whole-file trajectory hashes. Recovery log
is retained unchanged; prior running checkpoints below are historical.

17:55 CST: First pass terminated 16:17 with 230/240 completed and ten connection
failures. After explicit recovery authorization, c4 scoped resume launched as
session 52978 / PID 50430, helper 50431, log
`runs/biomnibench-results20-2026-09-06/logs/static-offline-formal-recovery.log`.
Failed-case evidence archive is `provenance/scoped/formal-failures-before-recovery.tar.gz`
under the same run root, SHA-256
`d8cdabbf038bdada04c0aa5a299f41abbca6dfc90019c1c79f88454c41ed2225`.
Prior checkpoints below are historical; original completed results are retained.

16:08 CST: 221/240 completed, ten running, nine connection failures. Queue empty;
session 2720 remains live. Prepare lower-concurrency recovery only after its exit.

16:01 CST: 205/240 completed, 26 running, nine failed, no pending dispatches.
All 198 completions captured by the independent replay snapshot passed validation
(session 45872 exit 0). Current revision owner session 2720 remains live; wait
for its terminal state before recovery, then validate the full 240-case population.

15:55 CST: 182/240 completed, 40 running, nine pending, nine connection failures.
The current owner is still live and generating trajectories; no restart or
configuration change has occurred. Complete this invocation before recovery.

15:50 CST: 165/240 completed, 40 running, 26 pending, nine connection failures
(eight simulator calls, one optimizer judge). Current session 2720 remains live;
wait for its terminal state before lower-concurrency validated recovery.

15:46 CST: 144/240 completed, 40 running, 49 pending, seven connection failures
awaiting terminal-boundary recovery. Original four-arm dataset was independently
rechecked: 240 cases and 9,327 judgments pass the strict three-model coverage gate.

15:36 CST: 104/240 completed, 40 running, 94 pending, two simulated-user
connection failures (`da-13-1/rep-003` and `da-15-1/rep-001`, both
user-simulator-offline-rubric). Recover only after the current study owner ends;
preserved intermediate snapshots and live roots are required for supported resume.

15:31 CST: 82/240 completed, 40 running, one simulated-user connection failure,
117 pending. Recent throughput ~6–7 completions/minute; coarse remaining revision
ETA 30–60 minutes including tail/recovery, audit additional. Disk availability
recovered to ~14 GiB as live workspaces were released; no manual temporary cleanup.

15:26 CST snapshot: 48/240 selected cases completed, 40 running, 152 pending,
zero selected failures. All 21 new completions in the earlier replay snapshot
pass independent validation. Memory headroom ~42%, swap ~7.7 GiB, free disk ~10 GiB;
new run tree ~1.0 GiB, user temporary tree ~11 GiB (do not clean active workers).

15:20 CST: acceptance recovery exited 0, coverage passed 100/100 with 95 original
successful records byte-identical. Receipt:
`scoped-acceptance/reports/openai-anthropic-coverage.json` under the new run root.
Formal scoped resume is live at c40: session 2720, PID 89189/helper 89190;
`logs/static-offline-formal-revise.log`. Selected 240 cases initially contain
20 completed, 40 running and 180 pending; no excluded conditions are active.
All frozen source/config/test bytes match; a Python reporting bytecode cache was
regenerated during table-reader verification. Older checkpoints below are historical.

15:17 CST: first pass session 24895 exited 1 with 95/100 judgments saved; five
Claude judgments are missing. Existing semantic runners now recover at c1,
session 39894, log `logs/scoped-acceptance-semantic-recovery.log`; the direct
panels and revisions are untouched. First-pass snapshot is
`provenance/scoped/openai-anthropic-first-pass.tar.gz`, SHA-256
`b69b3ff6880ff57bd969e2fd9f9b1bb766bd4176ae59417417c12a14595ba372`.

User approved a temporary two-model panel and a new 2×4-grid goal is active.
Session 24895, PID 86777/helper 86778, c4; log
`runs/biomnibench-results20-2026-09-06/logs/scoped-acceptance-openai-anthropic.log`.
New audit root: `scoped-acceptance/audit-openai-anthropic/biomnibench-da-factorial-r3-28b45d344cb6`.
Source snapshot: `provenance/scoped/openai-anthropic-source.tar.gz`, SHA-256
`9aad0ffd7a4f99d52eddc1e143001f27b498ca1dd2d3e79ae2bcf8aabec1c00c`.
Old three-model audit remains untouched, Gemini is deferred, and no revision was
rerun. Earlier stopped-run notes below are historical.

14:57 CST: session 72341 exited 143 after confirmed Gemini unsupported-location
errors; owner tree 85271/85272/85273 stopped. Saved judgments remain intact;
snapshot `provenance/scoped/acceptance-audit-region-interruption.tar.gz` includes
all partial audit output and terminal log. No formal resume is launched. The
running descriptions below are historical; await eligible Gemini access or an
explicitly revised panel before completing the acceptance gate.

At 14:44:51 CST, after explicit user payload/provider authorization, launched
four-case scoped acceptance revision at c4: session 60221, PID 83948, caffeinate
helper 83949. Verified all four selected arms running and 12 excluded rows pending.
Log: `runs/biomnibench-results20-2026-09-06/logs/scoped-acceptance-revise.log`.
205 tests and nine subtests passed; frozen source/config/test archive is
`provenance/scoped/authorized-source.tar.gz`, SHA-256
`4a86a39a1177dea20d239bbb6deec3ca531cefe6e673043ab3eb59020390d995`.
The earlier authorization blocker below is resolved; formal resume awaits this
scoped acceptance's complete revision and seven-stage/three-model audit gate.

At 14:50 CST, revision is now complete (4/4, finished 14:49:22; session 60221
exit 0) and all four cases independently replay. Audit session 72341 is running
at c12; `logs/scoped-acceptance-audit.log` under the new run root. Frozen source
bytes still match the authorized archive; no formal scoped resume launched yet.

The user approved retaining only Full/User simulator × static/offline (240 new
cases), plus the original four red-team arms (240 completed cases). The earlier
20-condition expansion below is superseded.

- Mixed invocation 9314 ended with exit 143; controller 55738 is gone.
- Saved mixed study: 60 completed, one failed, 40 interrupted, 859 pending.
- Wanted comparators: 20 completed and independently revalidated; four interrupted
  plus 216 unstarted remain. Excluded-arm outputs are retained, not deleted.
- No new experiment process has launched. Scoped execution/audit support passed
  194 focused tests and five audit-gate tests (nine subtests); the real acceptance
  launch was rejected by execution approval over benchmark payload/provider
  authorization. Obtain explicit approval before retrying; never present the
  full old ledger as a completed 960-case study.
- Acceptance config: `experiments/biomnibench-results20-static-offline-acceptance.yaml`,
  planned outputs in `scoped-acceptance/{study,audit}/biomnibench-da-factorial-r3-28b45d344cb6/`.
- Formal selected audit route: `audit/static-offline/biomnibench-da-factorial-r10-2f13900fe0e7/`.
- Complete stopped snapshot is `provenance/formal/mixed-scope-before-narrowing.tar.gz`
  under `runs/biomnibench-results20-2026-09-06/`, SHA-256
  `52f415a114e5f6ae9df3a752013bcf52f9ed92e3a4abde6bd08d2d0a255b1efe`.

Details and approved scope: [EXPERIMENT_PLAN.md](EXPERIMENT_PLAN.md).

## Historical: full Results20 expansion — superseded 2026-09-06

The following describes the stopped mixed invocation, not a live process or the
current authorized scope. Use the current checkpoint above for next actions.

Goal: complete all 20 conditions, reuse the four completed conditions below, and
execute 960 remaining assignments plus audits. **Formal revision is running**:
started 13:40:46 CST, session 9314 / PID 55738, concurrency 40, `caffeinate -i`,
Agg and one numeric thread. Initial ledger is 40 running and 920 pending; formal
audit has not started. Outputs:

At 14:00 CST: 46 completed, one failed, 40 running, 873 pending; later storage
sampling found 50 completed. The failed case is `da-13-1/rep-002/score-only-static`,
at `s008` reviewed-file stability checking. Its current snapshot hash and unchanged
production reader pass; preserve the strict guard and recover through normal
resume after the current study owner ends. Evidence archive:
`provenance/formal/failed-read-da-13-1-rep002-score-only-static.tar.gz`, SHA-256
`064c36ff45e059ec73cd7153b187e515c082df2077ba32bc15d9f31b8245cc8f`.
The first ten formal completions independently passed current-format replay
across eight tasks. Live snapshots are appended to
`runs/biomnibench-results20-2026-09-06/logs/formal-monitor.jsonl`; latest delivery
counts at 14:00 are 155 online generations, 15 retried stages, zero fallbacks and
64 included sidecars with none excluded. These are partial delivery counts, not
formal RH outcome results.
Owned workers used ~7.2 GiB aggregate RSS and ~230% CPU at 13:43; startup swap
growth stabilized at ~6.2 GiB on the next check, with 40% memory headroom.
Disk availability stabilized around 15 GiB; at 13:44 the new run tree itself was only 158 MiB, so
do not attribute the whole free-space change to saved formal artifacts. Continue
monitoring disk and swap alongside completed-case throughput.
At 14:00, recent throughput is about 2–3 completed cases/minute: coarse remaining
revision ETA 5–7 hours, audit additional. Resources shortly afterward: 39% memory
headroom, ~6.7 GiB swap, ~14 GiB free disk; new run tree 586 MiB. Fifty completed
case directories total 309.2 MiB (mean 6.2 MiB, max 34.1 MiB), an early sample rather
than a guaranteed final storage forecast.

- Study: `runs/biomnibench-results20-2026-09-06/study/biomnibench-da-factorial-r10-2f13900fe0e7/`
- Audit (future): `runs/biomnibench-results20-2026-09-06/audit/biomnibench-da-factorial-r10-2f13900fe0e7/`
- Log: `runs/biomnibench-results20-2026-09-06/logs/formal-revise.log`
- Frozen source/config/analysis: `runs/biomnibench-results20-2026-09-06/provenance/formal/source.tar.gz`
  (SHA-256 `56cddf7489a2eb3a6d9ae424034be9620d20d67acb71a92d5909a68d8a7e40e7`).

Initial coarse estimate: revision 4–10 hours, audit additional hours; revise from
measured formal completions and resource pressure, not a hard overall deadline.

### Completed acceptance and recovery evidence

Acceptance revision started at 12:55 CST, session 39685 /
PID 47723, concurrency 8, with 16 assignments (one task, three turns); its outputs
are under `runs/biomnibench-results20-2026-09-06/acceptance/study/biomnibench-da-factorial-r3-28b45d344cb6/`
and its log is `runs/biomnibench-results20-2026-09-06/logs/acceptance-revise.log`.
Revision session 39685 exited 0 at 13:09:57 CST with all 16 assignments completed
and independently replay-validated. The 14 online generations have zero fallback
or retried stages and one admitted criterion; all eight red-team sidecars were
included. All 194 frozen source/test/config files still match the archive.
Acceptance audit started at 13:10:48 CST, session 95681 / PID 52149, concurrency
12, using the same frozen runtime and all seven stages/three models. Its log is
`runs/biomnibench-results20-2026-09-06/logs/acceptance-audit.log`; its output is
`runs/biomnibench-results20-2026-09-06/acceptance/audit/biomnibench-da-factorial-r3-28b45d344cb6/`.
Initial audit ETA is 10–20 minutes, conditional on provider response and retries.
That initial estimate was exceeded by connection retries: at 13:35 CST all four
direct panels pass raw/summary agreement (192/192), rubric scoring ended at
257/258 with one failed Claude judgment, and quality scoring was then live at
50/51 absolute plus 45/48 pairwise (remaining four also Claude). The terminal
rubric first pass is preserved in
`provenance/acceptance-rubric-score-first-pass.tar.gz` (SHA-256
`4160524cef80217493a9b2fdd6aa5c313d260763d67425b2a7b87d14b7de6739`).
The generic private `scripts/diagnostics/monitor_audit.py` reads per-attempt
failures as well as scores; quiet main logs do not prove there were no retries.
First audit session 95681 exited 1 by 13:36 CST with an
Anthropic APIConnectionError in quality scoring. Semantic-only recovery ran
from 13:37:18 CST, session 77877 / PID 55351, concurrency 1, using existing
`RubricScoreRunner` and `RubricFreeScoreRunner` with validated `resume=True`.
Log: `runs/biomnibench-results20-2026-09-06/logs/acceptance-semantic-recovery.log`.
Quality first-pass/log archive: `provenance/acceptance-quality-first-pass.tar.gz`,
SHA-256 `c882c03952a5052fc1864779585553222b49632d243c3108db692213866a8873`.
Recovery exited 0 at 13:38:57. The complete gate passes 549 total judgments
(192 direct, 258 rubric, 51 absolute, 48 pairwise), all terminal summaries and
three-model coverage; all 352 prior successful semantic score files are
byte-identical to the first-pass archives. Receipt:
`runs/biomnibench-results20-2026-09-06/acceptance/reports/audit-coverage-complete.json`.
Immediately before formal launch: 43% memory headroom, stable ~3.1 GiB swap and
22 GiB disk availability.
Starting rubrics have already been replay-validated and copied for all 20 formal
tasks without model calls; that preparation-only copy is now retained under
`provenance/reuse-validation-formal/` so the formal command can create a fresh
study ledger in its own output root. Fresh formal outputs are configured below
`runs/biomnibench-results20-2026-09-06/{study,audit}/<experiment_id>/`.
The completed four-condition dataset stays immutable at its existing location.

## Completed: BioMNIBench red-team — 2026-09-05

Canonical local dataset: `runs/biomnibench-redteam-2026-09-05/`.
Former incident label: `20260905-redteam-v7`; this is the same experiment,
not a new run. All 240 assignments and seven audit stages completed, with
9,327 unique judgments across Sol, Claude Opus 5 and Gemini 3.8 Flash.
Solver/proposer/red-team: Luna. No new experiment is running for this cleanup.

- [Final report](runs/biomnibench-redteam-2026-09-05/reports/REPORT.md)
- [Frozen analysis](runs/biomnibench-redteam-2026-09-05/reports/outcomes.json)
- [Per-model five-metric score tables](runs/biomnibench-redteam-2026-09-05/supplementary-analysis/model-score-tables.md)
- [Dataset layout and relocation verification](runs/biomnibench-redteam-2026-09-05/README.md)
- [Failure lessons and next-run checklist](EXPERIMENT_RELIABILITY.md)
- [Original GitHub backup and restore instructions](GITHUB_BACKUP.md)

| Directory | Purpose |
| --- | --- |
| `study/` | Complete formal assignment artifacts and traces |
| `audit/` | All three-model direct and semantic judgments |
| `reports/` | Unmodified final reports and historical verification evidence |
| `provenance/` | Sealed source/config and recovery evidence; not another analysis population |
| `acceptance/study/`, `acceptance/audit/` | Successful small end-to-end acceptance |
| `inventories/`, `*.location.json` | Original identities and byte-level relocation evidence |

Referenced inputs remain at `seeds/biomnibench/native-prompt-results20` and
`runs/rubric-paraphrases/biomnibench/red-team-results20`.
Five genuine response-validation fallbacks and six excluded red-team sidecars
remain in the completed dataset: cleaning obsolete attempts must not bias results.

## Reading relocated results

Original raw records retain their original absolute paths and hashes. The private
offline analysis readers resolve those identities through explicit relocation
receipts and verify the file inventories. This does **not** make production CLI
resume valid at the relocated location. Do not edit raw JSON to make resume pass.
Use a fresh, descriptive output identity for a new experiment.

The release `aydan-red-team-backup-20260906` preserves the original layout;
its remote assets/checksums have not been changed by local cleanup.
Earlier invocation chronology is in [EXPERIMENT_LOG.md](EXPERIMENT_LOG.md)
and the original backup, rather than mixed into this current-results index.
Unrelated older BioMNIBench/PaperBench experiments are outside this cleanup.

## Future runs

Private tools now live in [scripts/diagnostics/](scripts/diagnostics/README.md).
Other older studies, audits, logs and quarantine evidence are grouped under
[runs/archive/](runs/archive/README.md); these are historical records, not all
failed runs. Current shared paraphrase dependencies remain at their original paths.

Use descriptive date-based names; keep study, audit, reports, provenance and
small acceptance separate. Record protocol/source identity independently of
the human-readable name. Consult [approved scope](EXPERIMENT_PLAN.md) and the
reliability checklist before executing new experiments.
