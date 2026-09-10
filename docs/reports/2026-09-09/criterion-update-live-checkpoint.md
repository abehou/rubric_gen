# Criterion-update Result20 live checkpoint

Verified 2026-09-09 07:29 EDT. Interim execution snapshot, not outcome evidence.

- Scientific owner:10369781, last verified RUNNING babel-m9-20.
- Revision state counts:{'None': 35, 'no_change': 25}; 367saved submissions including initial/intermediate artifacts.
- Actual delivery:23update notes across20assignments. Exposure is not compliance or mitigation.
- Reports:10369784 and10369789 pending successful owner completion.
- Frozen source:ffe10c4919d61767250e07277e4629a7b4fc4399; records commit0cdb3ff.
- Resources:4CPU128G48h, shared target60 reached, peak sampledRSS39.6GiB at preceding check. No manual restart.


Full outcome comparison is pending. Completed controls: static18.33% full-trajectory RH/3.33% artifact RH; original trace24.17%/1.67%, equal-auditor confirmed rates. Do not compare those completed rates to incomplete candidate data.

Starting criteria were reinduced and differ on12/20tasks from the original trace control. All selected-base rubrics remain matched. See [starting-rubric caveat](criterion-update-pretreatment-caveat.md); do not attribute all eventual differences solely to delivery.

Output:`runs/babel-result20-criterion-update-20260909/trace/{study,audit}/biomnibench-da-factorial-r10-082bfc062548`. Owner receipt:`runs/babel-result20-criterion-update-20260909/owners/trace-results20/10369781-20260909T105301051137Z`.

Next action: monitor10369781, preserve successful calls, inspect full native coverage and generated reports before a scientific decision. No30/45scale-up or new benchmark launch.

## 2026-09-09 07:40 EDT live check

Slurm owner10369781 remains RUNNING. Assignment stop reasons: {'None': 32, 'no_change': 27, 'max_revisions': 1}. Runtime journal contains 68 unique failed request keys; 65 have subsequent success and 3 have no subsequent success yet. These are pending recovery observations, not terminal scientific failures; preserve same owner and inspect again before any action. No detect log yet at this check.

## 2026-09-09 08:21 EDT — Revision stage complete

Owner10369781 remains RUNNING, now native detect --max-concurrency60 --resume. All60assignment states completed and study ledger completed_scope; no separate recovery owner. At this snapshot full-trajectory judgments completed56Sol/29Opus out of60each; other audit windows not yet started. No partial RH rates reported. Reports10369784/10369789 remain afterok dependencies. Return to frozen rubric-cue after all outcomes/reports finish, as instructed.

## 2026-09-09 08:27 EDT — Full-trajectory endpoint complete

Native full-trajectory summary has120unique source/model judgments: Sol10positive/49negative/1abstain; Opus13positive/46negative/1abstain. Equal-auditor confirmed19.17%, identification bounds19.17–20.83%. This is one completed endpoint of an incomplete run, not a promotion decision. Prior score-disclosing static18.33% and trace24.17%; starting criteria differ12/20tasks, so no isolated delivery causal claim. Remaining audits/quality/native full comparison pending. Return to cue20%→7.5%branch regardless of speculative score-disclosure continuation.

## 2026-09-09 08:46 EDT — Audit-only recovery

Original owner10369781 ended with OpenAI APIConnectionError after all60revisions, all four RH windows, and rubric scoring completed;232holistic judgments were saved. Native audit-only resume10370563 preserves all successful work and uses identical frozen scientific source; reports10369784/10369789 now depend on that recovery. No revision rerun.

At08:46 recovery is RUNNING but still in frozen uv environment setup, before launch.json/provider calls. Allocation process inspection shows uv sync, low CPU and about119MiB process RSS; elapsed setup exceeds7minutes. This is environment overhead, not slow model inference. Keep this owner unchanged; future launch optimization should validate reuse of an immutable lock-addressed environment rather than reinstalling every recovery. No claimed completion or outcome promotion.

## 2026-09-09 09:01 EDT — Full audit coverage verified

Recovery10370563 completed240absolute/120pairwise scores but exited1:10hosted token-count preparation requests failed with APIConnectionError before saved-RH lookup. Existing raw RH judgments were intact. Saved failed summary snapshots and diagnosis under that owner; new native resume10370740 with8audit workers, shared cap60, completed in1m41s and verified2134semantic judgments across all configured stages. No revised artifacts or auditor identities changed.

Reports10369784/10369789 now bind10370740. Delivery report completed:47/60withadmittedcriteria,21/60withsubmittednotes,24notes. Comparison pending; no promotion claim. Primary next science remains frozen cue branch.
