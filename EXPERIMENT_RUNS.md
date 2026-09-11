## 2026-09-09 — Publication and cleanup complete

- 22:18 EDT: Report10380610 and cleanup10380691 completed exit0; all363 top-level run entries retained, no scientific owner active. Accepted output index remains docs/reports/2026-09-09/baseline-freeze/README.md.

## 2026-09-09 — Accepted baseline checkpoint

- 22:09 EDT: Provider-free report10380610 completed, validating956 hashes and available coverage60/60/59/60; outputs and source receipts: docs/reports/2026-09-09/baseline-freeze/. Existing raw outputs and frozen execution checkouts remain untouched; no active scientific owner.

## Analysis and backup ownership — 2026-09-08 07:20 EDT

Scientific10356519/10356523 remain active. Backup inspector10356567 waits for CPU quota (1CPU/8G/1h,no providers/no restore). Native outcome/exposure analysis owner is **10356577**,afterok both scientificjobs,source9d0e17d,1CPU/8G/1h;output analysis-concern1-policy-10356519-10356523 and exposure/feedback directories of the same suffix. Do not manually run the analysis commands below while this owner exists. Wrapper verifies producer success/source hashes and sealed analysis definitions before native coverage reconstruction. Check runs/slurm-rubric-c1-analysis-10356577.out and runs/babel-overnight-20260907/policy-analysis-job-10356577/. Long earlyrep1 first revision completed normally;no stall/restart.

Submitted `sbatch --parsable investigation/babel-overnight-20260907/analyze_concern_policy.sbatch`;CPU preempt/preempt_cpu_qos,no account/GPU,read-only analysis. Success requires exact producer receipts/native coverage,not scheduler state alone.

## 2026-09-08 — Input archive inspection owner

Job10356567,source2c3c32a,command `sbatch --parsable investigation/babel-overnight-20260907/inspect_input_backup.sbatch`;receipt `runs/babel-overnight-20260907/input-backup-inspection-10356567/`,scheduler log `runs/slurm-rubric-input-backup-10356567.out`. Stdlib Python3.12,preempt/preempt_cpu_qos,1CPU/8G/1h,no account/GPU/provider payload;temporary archive removed after pinned SHA verification and manifest inventory. No production extraction or scientific experiment.

## Canonical inventory checkpoint — 2026-09-08 07:12 EDT

Canonical dev3 is3 tasks:da-3-4,da-11-1,da-18-1;Result20 has20 tasks,all with3replicates. All23 tasks/442files match pinned upstreamHF hashes;da-18-1 canonical data complete and intentionally reserved. Missing generated dev3/Result20 seed/paraphrase pools are a separate transfer gap;current two-task inputs remain valid. BIOMNIBENCH_DATA_AUDIT.md lists exact IDs,provenance and recovery prerequisites. No files restored or runs removed. README Gemini3.8/runtime corrected;configs already correct. Current10356519/10356523 continue;full three-task validation/input recovery plus mitigation gates remain before Result20. Prior44m34 execution timing refers only to two-task tuning conditions.

## 2026-09-08 06:54 EDT — Raw concern1 matched policy owners

Source8705deca7d42828086cd6b1fc654a7eaabdef947,checkout runs/babel-code/dev3-concern1-policy. Shared hard scientific IDbiomnibench-da-factorial-r10-360789db0d3d;identical three-arm design,disjoint execution scopes and separate output roots. Both currently running on babel-l9-16,CPU32/256G/48h each,preempt/preempt_cpu_qos,no account/no GPU,shared aggregate60/audit-study1/recovery2.

- Controls10356519:static+delayed trace,six assignments,root runs/babel-dev3-concern1-policy-controls-20260908/da-11-1/{study,audit}/biomnibench-da-factorial-r10-360789db0d3d;receipt runs/babel-overnight-20260907/dispatcher-concern1-policy-controls-da-11-1/. Submitted: sbatch --parsable --job-name=rubric-c1-controls-da11 runs/babel-code/dev3-concern1-policy/investigation/babel-overnight-20260907/condition.sbatch concern1-policy-controls da-11-1 --workers 60 --audit-workers 60.
- Early10356523:early trace,three assignments,root runs/babel-dev3-concern1-policy-early-20260908/da-11-1/{study,audit}/biomnibench-da-factorial-r10-360789db0d3d;receipt runs/babel-overnight-20260907/dispatcher-concern1-policy-early-da-11-1/. Submitted: sbatch --parsable --job-name=rubric-c1-early-da11 runs/babel-code/dev3-concern1-policy/investigation/babel-overnight-20260907/condition.sbatch concern1-policy-early da-11-1 --workers 60 --audit-workers 60.

Native frozen seed/pool/scoring checks,default-request byte equivalence to raw concern1,shared smoke runtime equality and3 launcher tests pass;early scientific source231 tests previously passed unchanged. Easy45de1afcb60f held;no Result20. Recovery only after terminal infrastructure failure,via same mode with --recovery;do not duplicate a live owner.

## 2026-09-08 — Sole owner: concern1 replication

- 06:01 EDT: Job10356343/sourceccbb87f5216e9bc3f56a48b1d221a1570ea9c3da,checkout runs/babel-code/dev3-concern1-replication,hard9c4f6cbc54e4;outputs runs/babel-dev3-concern1-replication-20260908/da-11-1/{study,audit}/biomnibench-da-factorial-r10-9c4f6cbc54e4,receipt dispatcher-concern1-replication-da-11-1. Command: `sbatch --parsable --job-name=rubric-concern1-rep-da11 runs/babel-code/dev3-concern1-replication/investigation/babel-overnight-20260907/condition.sbatch concern1-replication da-11-1 --workers 60 --audit-workers 60`;CPU32/256G/48h,shared60,audit1/recovery2,no account/GPU,easy49f3427c54b7 held.

## 2026-09-08 — Replication complete; no live jobs

- 05:49 EDT: Job10356064 completed/native3/102,source02ab992 unchanged;analysis-package-replication-10356064 and analysis-three-package-controls-10356064 under runs/babel-overnight-20260907. Early-policy remains an isolated unlaunched candidate;next prepare simpler concern1 replication under current unchanged scientific source.

## 2026-09-08 — Interrupted preparation recovered

- 05:42 EDT: Sole live job10356064 has completed three solver assignments and entered Sol/Opus audits without exposed provider failures. Isolated uncommitted branch babel-dev3-early-trace-20260908 at runs/babel-code/dev3-early-trace is preparation only; no new output identity or job exists yet.

## 2026-09-08 — Material-review complete

- 05:25 EDT: Job10355928/sourcec88f6ef unchanged completed29m09s,MaxRSS4745256KiB;native analysis-material-review-10355928 and paired analysis-material-paired-10355928 under runs/babel-overnight-20260907. All3/102 valid;sole active10356064,material easy20e0d545b8ff stopped.

## 2026-09-08 — Package replication execution

- 05:06 EDT: Job10356064/source02ab992b944b6fbba047772317a7bee496712fb1,command `sbatch --parsable --job-name=rubric-package-rep-da11 runs/babel-code/dev3-package-replication/investigation/babel-overnight-20260907/condition.sbatch package-replication da-11-1 --workers 60 --audit-workers 60`;outputs runs/babel-dev3-package-replication-20260908/da-11-1/{study,audit}/biomnibench-da-factorial-r10-1b9a4d5716e5,receipt dispatcher-package-replication-da-11-1. Same scientific ID,new explicit execution cohort;CPU32/256G/48h/shared60/audit1/recovery2.

## 2026-09-08 — Material-review run

- 04:50 EDT: Job10355928/sourcec88f6ef,command `sbatch --parsable --job-name=rubric-material-da11 runs/babel-code/dev3-material-review/investigation/babel-overnight-20260907/condition.sbatch material-review da-11-1 --workers 60 --audit-workers 60`;outputs runs/babel-dev3-material-review-20260908/da-11-1/{study,audit}/biomnibench-da-factorial-r10-3a510cc295e7,receipt dispatcher-material-review-da-11-1. Only owner;172 tests/native inputs pass,easy20e0d545b8ff held.

## 2026-09-08 — Focused package complete

- 04:47 EDT: Job10355548 completed25m10s/source41fef8b unchanged,MaxRSS6026484KiB;native analysis-package-atomic-10355548 and paired analysis-package-atomic-paired-10355548 under runs/babel-overnight-20260907. No active jobs;easy2d866b293c31 stopped.

## 2026-09-08 — Preservation complete

- 04:39 EDT: Job10355312 completed37m57s/source6001c49 unchanged,3 assignments102 judgments;native analysis-preserve-work-10355312 and paired analysis-preserve-paired-10355312 under runs/babel-overnight-20260907. Sole active10355548;preservation easy13c6855f4316 stopped.

# 2026-09-08 — Single-issue feedback with package facts

- 04:20 EDT: Job10355548/source41fef8bd2d12de3d9e04e9639449ea748beb5d7d,hard4945b5c35613,three saved seeds;only existing single_issue false→true differs from package1. Command `sbatch --parsable --job-name=rubric-singlepkg-da11 runs/babel-code/dev3-package-atomic/investigation/babel-overnight-20260907/condition.sbatch package-atomic da-11-1 --workers 60 --audit-workers 60`;outputs runs/babel-dev3-package-atomic-20260908/da-11-1/{study,audit}/biomnibench-da-factorial-r10-4945b5c35613,receipt dispatcher-package-atomic-da-11-1.8 focused tests/native bindings/config-only/source-byte checks pass;CPU32/256G/48h/shared60/audit1/recovery2,easy2d866b293c31 held.

# 2026-09-08 — Preserve verified work

- 03:56 EDT: Job10355312/source6001c4953a6215c3cd6b6cab523f8ff1515cf5e6,hard29209e56d18c,three frozen seeds;optional simulator preservation instruction only on package1. Command `sbatch --parsable --job-name=rubric-preserve-da11 runs/babel-code/dev3-preserve-work/investigation/babel-overnight-20260907/condition.sbatch preserve-work da-11-1 --workers 60 --audit-workers 60`;outputs runs/babel-dev3-preserve-work-20260908/da-11-1/{study,audit}/biomnibench-da-factorial-r10-29209e56d18c,receipt dispatcher-preserve-work-da-11-1.168 tests/native bindings/source boundary pass;CPU32/256G/48h/shared60/audit1/recovery2,easy13c6855f4316 held.

# 2026-09-08 — Package-context feedback breadth

- 03:22 EDT: Submitted package-three10355042/source b397f9b75307c6447d3d0825f0d63e8b56fff8b1,hard experiment2e7789048fe3,three frozen user-static seeds;only max_concerns1→3 differs from package baseline. CPU32/256G/48h/shared60,audit1/recovery2;native inputs/source equivalence/3 dispatcher tests pass,easy f49f4722fd0f held.

Command:`sbatch --parsable --job-name=rubric-package3-da11 runs/babel-code/dev3-package-three/investigation/babel-overnight-20260907/condition.sbatch package-three da-11-1 --workers 60 --audit-workers 60`. Outputs:runs/babel-dev3-package-three-20260908/da-11-1/{study,audit}/biomnibench-da-factorial-r10-2e7789048fe3;receipt:runs/babel-overnight-20260907/dispatcher-package-three-da-11-1/.

# 2026-09-08 — Completion-request prompt

- 02:26 EDT: Job10354683/source da09d14f7c175fa5efcd5209b3129a377e35bf60,hard experiment5585a6706815,three frozen user-static seeds. Command `sbatch --parsable --job-name=rubric-completion-da11 runs/babel-code/dev3-completion-request/investigation/babel-overnight-20260907/condition.sbatch completion-request da-11-1 --workers 60 --audit-workers 60`;outputs runs/babel-dev3-completion-request-20260908/da-11-1/{study,audit}/biomnibench-da-factorial-r10-5585a6706815,receipt dispatcher-completion-request-da-11-1.178 tests/native inputs pass;CPU32/256G/48h,global60/audit1/recovery2;easy aa06110618c8 prepared/held.

# 2026-09-08 — Gemini access diagnostic

- 02:21 EDT: Job10354654/source97420f3,command `sbatch --parsable --job-name=rubric-gemini-access investigation/babel-overnight-20260907/gemini-access.sbatch`,receipt runs/babel-overnight-20260907/gemini-access-10354654/result.json. CPU2/8G/15min/no account/no GPU,shared60;configured gemini-3.8-flash minimal non-benchmark generation failed429/prepayment_credit_exhaustion;no Gemini scientific condition submitted.

# 2026-09-08 — Frozen package baseline policy comparison

- 01:47 EDT: Job10354567/source f96e72e7bc527eecd02b48bfc210dcf40c8cf67b submitted,experiment47a3f36d31e8,nine hard-task cells:static replication,red-team-trace,online-contrast. Command `sbatch --parsable --job-name=rubric-packpolicy-da11 runs/babel-code/dev3-package-policy/investigation/babel-overnight-20260907/condition.sbatch package-policy da-11-1 --workers 60 --audit-workers 60`;outputs runs/babel-dev3-package-policy-20260908/da-11-1/{study,audit}/biomnibench-da-factorial-r10-47a3f36d31e8,receipts dispatcher-package-policy-da-11-1.169 non-provider tests/native inputs pass,simulator/scoring/runtime bytes match d964058;CPU32/256G/48h,global60/audit1/recovery2,easy20964ce3b098 remains held.

# 2026-09-08 — Outcome-request prompt

- 01:38 EDT: Job10354436/source998a9c84cecafc906b9e9153e4a2506c096677b4 submitted for outcome-request da-11-1,three frozen seeds,experimentcc99213e66eb. Command `sbatch --parsable --job-name=rubric-outcome-da11 runs/babel-code/dev3-outcome-request/investigation/babel-overnight-20260907/condition.sbatch outcome-request da-11-1 --workers 60 --audit-workers 60`;outputs runs/babel-dev3-outcome-request-20260908/da-11-1/{study,audit}/biomnibench-da-factorial-r10-cc99213e66eb,receipt dispatcher-outcome-request-da-11-1 under runs/babel-overnight-20260907. CPU32/256G/48h,shared60/audit1/recovery2;easy2ff05c4d47e7 prepared/unsubmitted pending hard evidence.

# 2026-09-08 — Matched package easy extension

- 01:32 EDT: Package da-3-4 job10354401/source d964058,experiment1beb31e170c7,outputs runs/babel-dev3-package-context-20260907/da-3-4/{study,audit}/biomnibench-da-factorial-r10-1beb31e170c7. Command `sbatch --parsable --job-name=rubric-packages-da3 runs/babel-code/dev3-package-context/investigation/babel-overnight-20260907/condition.sbatch package-context da-3-4 --workers 60 --audit-workers 60`.
- 01:32 EDT: Matched attention-control da-3-4 job10354402/source68cfc05,experimentc2f1f8983e58,outputs runs/babel-dev3-attention-control-20260907/da-3-4/{study,audit}/biomnibench-da-factorial-r10-c2f1f8983e58. Command `sbatch --parsable --job-name=rubric-attcontrol-da3 runs/babel-code/dev3-single-issue/investigation/babel-overnight-20260907/condition.sbatch attention-control da-3-4 --workers 60 --audit-workers 60`;both use account-free CPU preempt QoS32CPU/256G/48h,shared60/audit1/recovery2.

# Experiment results index

## 2026-09-07 — Public-context easy-task smoke queued

- 21:05 EDT: Job10352127 waits afterok:10352017 at isolated code5d87ed9, da-3-4 experiment e817891f65b4, output runs/babel-dev3-context-20260907/da-3-4/; solver2/audit8 share aggregate60/audit1. Command `sbatch --parsable --dependency=afterok:10352017 --job-name=rubric-context-da3 investigation/babel-overnight-20260907/condition.sbatch context da-3-4 --workers 2 --audit-workers 8`; dispatcher evidence runs/babel-overnight-20260907/dispatcher-context-da-3-4/, hard-task condition81a45ea8ddb6 remains unsubmitted.

## 2026-09-07 — Real smoke accepted; bounded baseline comparison active

- 20:57 EDT: Smoke10351863 completed15m53s with6 assignments/168 strict audit judgments, observed provider peak8, no failed-operation events, zero unfinished leases and Slurm MaxRSS2542320K; analysis runs/babel-overnight-20260907/analysis-smoke-10351863/analysis.json. Control10352016 and concern1-da3 job10352017 are running; concern1-da11 job10352036 waits afterok:10352017, each32 CPUs/256 GiB/48h and explicit workers60/audit60 under one shared cap60/audit1.

## 2026-09-07 — Authorized real-provider Babel dev3 smoke

- 20:37 EDT: Job10351863 submitted at6a770d4 using account-free preempt/preempt_cpu_qos,32 CPUs/256 GiB/48h/zero GPUs; solver2/audit8 share aggregate60 and one audit. Command `sbatch --parsable --job-name=rubric-dev3-smoke scripts/babel/dev3.sbatch smoke`; outputs `runs/babel-dev3-20260907/da-3-4/` and `dispatcher-smoke/`, scheduler log `runs/slurm-rubric-dev3-smoke-10351863.out`; next complete strict coverage before dev3 control/concern1 continuation.

## 2026-09-07 — Prepared intervention state; no scientific dispatch

- 15:54 EDT: Isolated policy commit3ec92fc prepares6 assignments each at da-3-4 ID42850a80b3a2 and da-11-1 ID49c88fb4fef9 under runs/babel-dev3-online-contrast-20260907/; concern1 prepares3 each at IDf78b360ef9be and ID570a2e9b4df6 under runs/babel-dev3-concern1-20260907/. All are unrun, no Slurm job remains active, and the exact approval-gated next actions are in investigation/babel-overnight-20260907/MORNING_REPORT.md.


## 2026-09-07 — Authoritative two-node runtime check

- 15:46 EDT: Job10349478 passed on babel-l9-32/babel-m5-16:80 synthetic operations, peak60, final0, elapsed8s, Slurm step MaxRSS13008K; evidence `runs/babel-overnight-20260907/cross-node-10349478/result.json`. Job10349470 exposed a diagnostic counter-cache bug (not a scientific run); its failure and earlier10349257 receipt are preserved.


## 2026-09-07 — Cross-node admission verified

- 15:36 EDT: Non-provider job10349257 completed on babel-o5-20 and babel-o5-24 (two nodes,2 CPUs/8 GiB each, preempt CPU QoS);80 synthetic operations reached exactly60 aggregate and released all slots. Evidence `runs/babel-overnight-20260907/cross-node-10349257/result.json`; no active scientific jobs.


## 2026-09-07 — Repaired compute environment validated

- 15:14 EDT: Runtime gate10348914 completed successfully; evidence `runs/babel-overnight-20260907/runtime-10348914/result.json`. Scientific attempts10348671/10348792 failed before provider work; the existing fresh Babel namespace remains available for its first accepted execution.


## 2026-09-07 — Babel corrected-control acceptance

- 14:57 EDT: Submitted scientific smoke job10348671 at source01dd659, command `sbatch --parsable --job-name=rubric-dev3-smoke scripts/babel/dev3.sbatch smoke`, CPU-only preempt/preempt_cpu_qos32 CPUs/256 GiB/48h. Six da-3-4 control assignments (three replicates × full/simulator), solver2/audit8 under aggregate60; outputs `runs/babel-dev3-20260907/da-3-4/` and `dispatcher-smoke/`, scheduler log `runs/slurm-rubric-dev3-smoke-10348671.out`.


## 2026-09-07 — Runtime gate job

- 14:50 EDT: Job10348599 is running on babel-l5-16, account dfried/preempt/preempt_cpu_qos,2 CPUs/8 GiB/30m; command `sbatch --parsable --job-name=rubric-runtime --cpus-per-task=2 --mem=8G --time=00:30:00 scripts/babel/dev3.sbatch runtime`. Output `runs/babel-overnight-20260907/runtime-10348599/`, scheduler log `runs/slurm-rubric-runtime-10348599.out`; this job makes no model calls and gates scientific work.


## 2026-09-07 — Overnight execution index

- 14:45 EDT: Runtime gate and overnight diagnostics are recorded under runs/babel-overnight-20260907/ and investigation/babel-overnight-20260907/; existing Babel dev3 control outputs retain their prepared namespace. No scientific job has yet been submitted.


## 2026-09-07 — Prepared Babel namespace; no results

- 14:31 EDT: Prepared two control configurations under `experiments/babel/` with new `runs/babel-dev3-20260907/<task>/{study,audit}/{experiment_id}` roots; da-3-4 smoke is reused by full continuation, and dispatcher receipts live under `dispatcher-{smoke,full}`. These are future output paths, not experiment results; [launcher instructions](docs/BABEL_SETUP.md) preserve the completed Mac evidence.


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

## 2026-09-07 22:12 EDT — public-review dev3

User-authorized bounded information ablation, compare against context5d87ed9. Source471e3b7 at runs/babel-code/dev3-public-review; private protocol investigation/babel-overnight-20260907/PUBLIC_REVIEW_PROTOCOL.md in that checkout. No change to providers,metrics,thresholds or task seeds.

- da-3-4: job10352750, experimentbiomnibench-da-factorial-r10-04cb6fce1c1b, outputs runs/babel-dev3-public-review-20260907/da-3-4/{study,audit}/<experiment>, dispatcher runs/babel-overnight-20260907/dispatcher-public-review-da-3-4/. Submitted2/8 workers, shared aggregate60,32CPU/256G/48h, CPU-only preempt/preempt_cpu_qos, no account flag.
- da-11-1: prepareda77b537b8dba, not submitted; same namespace/task layout. Launch only after native public-review smoke acceptance; exact command: sbatch --parsable --job-name=rubric-public-da11 runs/babel-code/dev3-public-review/investigation/babel-overnight-20260907/condition.sbatch public-review da-11-1 --workers 60 --audit-workers 60.

## 2026-09-07 22:56 EDT — matched single-issue attention

Frozen source68cfc05 at runs/babel-code/dev3-single-issue. Protocol investigation/babel-overnight-20260907/SINGLE_ISSUE_PROTOCOL.md in that checkout. Both max_concerns1 and include_execution_context=true; only single_issue differs. Same seeds,selected/master/heldout semantics,models and evaluation.

- Control da-11-1: job10352948,experimentbiomnibench-da-factorial-r10-275b4391a39d,outputs runs/babel-dev3-attention-control-20260907/da-11-1/{study,audit}/<experiment>,receipt runs/babel-overnight-20260907/dispatcher-attention-control-da-11-1/.60 solver/60 audit workers.
- Treatment da-11-1: job10352949,experimentbiomnibench-da-factorial-r10-5abb8d5d7d15,outputs runs/babel-dev3-single-issue-20260907/da-11-1/{study,audit}/<experiment>,receipt runs/babel-overnight-20260907/dispatcher-single-issue-da-11-1/. First real instruction-path check2 solver/8 audit workers; global capacity stays60.
- Both request preempt/preempt_cpu_qos,32CPU/256G/48h,no account flag,no GPU. Do not duplicate active cells. Native recovery only after terminal failure: sbatch --parsable <checkout>/investigation/babel-overnight-20260907/condition.sbatch <attention-control|single-issue> da-11-1 --recovery.
- Prepared but unsubmitted da-3-4: controlc2f1f8983e58,treatmentcd089e3e443d. Extend only after hard-task interpretation and runtime acceptance.

## 2026-09-07 23:30 EDT — Current execution clarification

Public-review da-11-1 a77b537b8dba is held after the completed easy-task quality guardrail failure; its earlier conditional launch command is not the next action. Attention-control10352948 completed0:0 with unchanged source and3 assignments/102 native judgments; treatment10352949 remains the sole active job. Study pending full-static rows are unselected planned conditions,not missing user assignments or duplicate jobs.

## 2026-09-07 23:53 EDT — Package-context dev3

Job10353356 submitted,pending Priority at first check. Source d964058 at runs/babel-code/dev3-package-context;experimentbiomnibench-da-factorial-r10-1b9a4d5716e5,outputs runs/babel-dev3-package-context-20260907/da-11-1/{study,audit}/<experiment>,receipt runs/babel-overnight-20260907/dispatcher-package-context-da-11-1/. Exact command: sbatch --parsable --job-name=rubric-packages-da11 runs/babel-code/dev3-package-context/investigation/babel-overnight-20260907/condition.sbatch package-context da-11-1 --workers 60 --audit-workers 60.

Three selected user assignments;one-factor public package facts versus completed attention control. CPU-only preempt/preempt_cpu_qos,32CPU/256G/48h,no account flag,no GPUs;shared aggregate60,one audit study,recovery2. Native --resume owned by the dispatcher; after terminal infrastructure failure use the same command with --recovery,never duplicate the live cell. Prepared da-3-4 experiment1beb31e170c7 remains unsubmitted pending hard-task evidence.

## 2026-09-08 00:15 EDT — Matched attention-policy dev3

Job10353597 submitted. Source0743f82 at runs/babel-code/dev3-attention-policy;experimentbiomnibench-da-factorial-r10-eb37ec092b01,outputs runs/babel-dev3-attention-policy-20260908/da-11-1/{study,audit}/<experiment>,receipt runs/babel-overnight-20260907/dispatcher-attention-policy-da-11-1/. Exact command: sbatch --parsable --job-name=rubric-attpolicy-da11 runs/babel-code/dev3-attention-policy/investigation/babel-overnight-20260907/condition.sbatch attention-policy da-11-1 --workers 60 --audit-workers 60.

Six cells:three user-simulator-online-rubric and three user-simulator-online-contrast;one-concern public-context simulator matches completed static attention control. Existing policy source unchanged;no package or single-issue intervention mixed in. CPU-only preempt/preempt_cpu_qos,32CPU/256G/48h,no account/no GPU;all concurrently active rubric jobs shareaggregate60,one audit study,recovery2. Native dispatcher --resume only;after terminal infrastructure failure use --recovery,never duplicate live ownership. Prepared easy-task48930067fea7 stays unsubmitted. Earlier full-feedback/user-policy preparations remain unrun and are not active owners.

## 2026-09-08 Independent controls analysis

- 08:07 EDT: Read-only analysis owner10356737 follows afterok10356519 at f00ff62,1CPU/8GiB/1h,outputs runs/babel-overnight-20260907/analysis-concern1-controls-10356519 plus exposure/feedback counterparts. It analyzes static versus delayed independently of early rep2's deterministic input failure;original combined owner10356577/output remains distinct and no scientific cells are duplicated.

## 2026-09-08 Controls diagnostic checkpoint

- 08:31 EDT: Producer10356519 FAILED78m34s(exits0,0;seal mismatch);10356523 FAILED84m07s(inputlimit+seal);backup10356567 completed;analysis10356577/10356737 cancelled. Diagnostic10356886 completed at runs/babel-overnight-20260907/diagnostic-concern1-controls-10356519;no active/pending jobs at checkpoint.

## 2026-09-08 Result20 input restore

- 08:37 EDT: Slurm10356929 restores only verified archived Result20 seeds/paraphrases into runs/babel-result20-input-restore-10356929/archive-inputs;1CPU/8GiB/1h,no provider calls,original manifests unchanged. Native validation pending;fresh180assignment Result20 setup at runs/babel-code/result20-current,dev3 concern-count comparison held.

## 2026-09-08 Focused Result20 queued

- 08:47 EDT: Focused Result20 at frozen409104f,runs/babel-code/result20-current,IDbfbdd0f9833c:full-static10356969,user-static10356970,user-trace10356971,each60assignments,4CPU/256GiB/48h,account-freepreempt/preempt_cpu_qos,shared60/audit1. Outputs runs/babel-result20-current-20260908/{full-static,user-static,user-trace}/{study,audit}/biomnibench-da-factorial-r10-bfbdd0f9833c;all afterok10356968,which follows restore10356965.

## 2026-09-08 Focused Result20 live

- 08:50 EDT: Native gate10356968 passes60seeds/100variants/180assignments with noerrors;Result20jobs10356969(fullstatic,babel-l5-28),10356970(userstatic,babel-l5-32),10356971(usertrace,babel-l9-16) now RUNNING. Actual receipts verify409104fd98290f2577d9644b36f43c7a35338c6f,4CPU/256GiB/48h,workers60/audit60,and no main-repo code dependencies in source seals;sharedaggregate60 unchanged.

## 2026-09-08 Fourth Result20 owner

- 09:01 EDT: Added full-feedback red-team trace owner10357008,60assignments,matched frozen scientific409104f,launcher239640a;four conditions total240. Command: sbatch --parsable investigation/result20-full-trace-20260908/condition.sbatch full-trace --workers 60 --audit-workers 60. Output runs/babel-result20-current-20260908/full-trace/{study,audit}/biomnibench-da-factorial-r10-f0203f5d69f3;4CPU/256GiB/48h,shared global60,one audit;existing10356969/70/71 untouched.

## 2026-09-08 First Result20 analysis owner

- 09:13 EDT: Read-only analysis10357038 is PENDING afterok10356969,1CPU/8GiB/2h,no providers;frozen helper/source seals and producer success are required before native complete Sol/Opus coverage checks. Output runs/babel-result20-current-20260908/full-static-report-v1;receipt static-report-job-10357038;launcher investigation/result20-report-20260908/analyze_full_static.sbatch. If producer fails,reconcile dependency after valid recovery;do not silently accept surviving assignments.

## 2026-09-08 Trace recovery owners

- 09:47 EDT: Approved trace recovery10357169(usertrace,babel-l5-28) and10357170(fulltrace,babel-l5-32) RUNNING at b4d751da4440c6563c6c72b90538ffee7e853f94;4CPU/128GiB/48h each,workers60/audit60 share original global60. Both isolated NFS startup probes pass and launch receipts bind original cancelled owners10356971/10357008 with unchanged source seals;native input/smoke/identity gates pass. Original configs and study/audit paths reused through native resume;no compatibility metadata fabricated. Receipts runs/babel-overnight-20260907/dispatcher-{user-trace,full-trace}-result20-nfs-recovery;launcher investigation/result20-nfs-recovery-20260908/condition.sbatch with explicit --nodelist as above.

## 2026-09-08 Conditional local-temp Result20 recovery

- 10:28 EDT: Prepared,not submitted:investigation/result20-local-temp-recovery-20260908/condition.sbatch at isolated653584034445d39dc4429142d30481e1178ee6f0,runs/babel-code/result20-local-temp. Four modes full-static/user-static/user-trace/full-trace preserve original configs/output paths;4CPU/128GiB/48h,shared60/audit1,native resume. RECOVERY_PLAN.md owns exact commands;validation.json proves unchanged identities/source gates and active-owner rejection. Approval requested to stop only10356969/10356970/10357169/10357170;all remain untouched until approval.

## 2026-09-08 Authorized recovery checkpoint

- 10:53 EDT: Recovery source6535840: full-static10357585, user-static10357642 (after terminal2worker gate10357594), user-trace10357630, full-trace10357631; each4CPU/128GiB/48h,60workers/shared60, original output roots. Coverage-gated full-static report10357605 follows afterok10357585 at full-static-report-v2; superseded pending report10357038 and probe10357398 cancelled.

## 2026-09-08 Validated checkpoint follow-on owners

- 11:06 EDT: Full-static10357585 complete60/60 and report10357605 complete2040judgments at runs/babel-result20-current-20260908/full-static-report-v2. Queued10357851 user-static afterany10357642 and10357852 full-trace afterany10357631; source1f995dfa53cd51582ce2b3f84db78ceca055a4ea, bundle investigation/result20-checkpoint-recovery-20260908, original outputs,4CPU/128GiB/48h,60workers/shared60.
- 11:06 EDT: Acceptance10357741 verifies four source/config gates, rejects three live owners, accepts terminal full-static owner, and replays13 real completed-turn model receipts in memory without modifying science. Current10357642/10357630/10357631 remain untouched; recovery jobs use distinct dispatcher namespaces, native resume and exclusive study leases, and start only after their respective current owner is terminal.

## 2026-09-08 Complete Result20 reporting graph

- 11:09 EDT: Per-condition read-only reports10357863(user-static afterok10357851),10357864(full-trace afterok10357852),10357865(user-trace afterok10357630) queued at1CPU/8GiB/2h. Combined comparison/figures/policy-and-feedback exposure10357891 follows afterok10357863:10357864:10357865, outputs runs/babel-result20-current-20260908/report-v1, requires successful exact producer receipts and native complete Sol/Opus coverage; immutable launchers/seals under investigation/result20-report-20260908.

- 11:38 EDT: Read-only recovery-provenance report10358231 follows afterok10357891,1CPU/4GiB/10min; output report-v1/recovery-provenance/summary.json. It counts native session discards, recovered turns and archived interruptions for all240 matched assignments without excluding or rescoring any outcome.

- 11:39 EDT: Matched static-only comparison10358258 follows afterok10357863,1CPU/8GiB/2h,no providers; validates both complete60-assignment producers and computes paired full-static/user-static contrasts at runs/babel-result20-current-20260908/static-comparison-v1. This is an earlier baseline-headroom milestone,not a replacement for all240 assignments or the pending dynamic comparison.

- 11:55 EDT: Read-only user-static feedback exposure10358447 submitted with existing sealed investigation/babel-overnight-20260907/feedback_exposure.py, input user-static-report-v1/analysis.json, output runs/babel-result20-current-20260908/user-static-feedback-exposure-v1. Account-free preempt/preempt_cpu_qos,1CPU/4GiB/10min,no providers; logs static-feedback-exposure-10358447.log under the same Result20 root.

- 11:59 EDT: Early user-policy analysis10358502 (1CPU/8GiB/2h) and admission/exposure10358493 (1CPU/4GiB/20min) follow afterok10357865; outputs user-policy-comparison-v1 and user-trace-policy-exposure-v1 under runs/babel-result20-current-20260908. The matched120-assignment helper/seal is investigation/result20-report-20260908/analyze_user_pair.py/.sbatch and user-pair-seal.json; it verifies exact producer successes/source hashes and native complete Sol+Opus coverage; no providers or scientific changes.

- 12:24 EDT: Fresh capacity retry source runs/babel-code/result20-capacity-v2 at34b5a22; native60seed/shared-paraphrase and exact2-file source gate10358770 succeeds,95 regression tests10358771 pass12.29s. Provider-only5call runtime acceptance10358773 queued; launch bundle investigation/result20-capacity-20260908/condition.sbatch is prepared,not submitted,requires successful acceptance and terminal10357630; output runs/babel-result20-capacity-20260908/user-trace,live root /home/aydanh/rubric-gen-live/result20-capacity-v2,4CPU/128GiB/shared60.

- 12:28 EDT: Fresh user-trace10358817 submitted afterany10357630 at34b5a22 via investigation/result20-capacity-20260908/condition.sbatch user-trace --workers60 --audit-workers60;4CPU/128GiB/48h,account-free preempt/preempt_cpu_qos,shared60. Real acceptance10358804 passes1.15MB assessment plus revalidated4concurrent validation responses from10358773;the latter failed only its diagnostic JSON/repair parser before the large call,no repeated successful calls. New producer dispatcher-user-trace-result20-capacity-v2 and outputs runs/babel-result20-capacity-20260908/user-trace;previous outputs remain immutable.

## 2026-09-08 Final capacity/report owner replacement

- 12:43 EDT: Scientific retry10358980 afterany10357630:source runs/babel-code/result20-capacity-v3 at5270c4a,launcher investigation/result20-capacity-v3-20260908/condition.sbatch user-trace --workers60 --audit-workers60;4CPU/128GiB/48h,shared60,output runs/babel-result20-capacity-v3-20260908/user-trace,live root /home/aydanh/rubric-gen-live/result20-capacity-v3. Unstarted10358817 cancelled;previousfailed/current scientific outputs retained.
- 12:43 EDT: Native user report10358982 afterok10358980 uses its exact source;full-trace report10357864 retains afterok10357852. Early user pair10358988 and exposure10358990 follow10358982;combined10358989 also waits10357864;plots/policy/feedback/recovery10358991 follows10358989,output runs/babel-result20-current-20260908/report-v2. Native per-source results are merged with unchanged frozen statistics;complete static equivalence10358910 passed.

## 2026-09-08 Live retry and final receipt binding

- 12:52 EDT: Active freshuser10358980 source5270c4a,outputs capacity-v3/user-trace;actual receipt runs/babel-overnight-20260907/dispatcher-user-trace-result20-capacity-v2/10358980-*/launch.json. Native report10359080 afterok10358980 uses analyze_user_trace_capacity_actual.sbatch;olduserreports superseded while pending.
- 12:52 EDT: Full native resume10359033 afterany10357852 uses unchanged investigation/result20-checkpoint-recovery-20260908/condition.sbatch full-trace --workers60 --audit-workers60,source1f995df,sameoutputs/namespace;fullreport10359042 afterok10359033. User pair10359083,combined10359084,exposure10359085,derivedfigures/recovery10359093 complete the graph;output report-v2;combine_validated_v5 preserves the verified statistical functions.

- 13:02 EDT: Completed read-only plot10359146 via investigation/result20-report-20260908/plot_static_milestone.sbatch,1CPU/8GiB/2h;PNG/PDF/provenance at runs/babel-result20-current-20260908/static-milestone-figure,from validated static-comparison-v1/analysis.json;no provider calls. Scientific owners10358980/10357852 remain running and final reporting graph unchanged.

- 13:07 EDT: Completed input-readiness10359297,13s,1CPU/8GiB,source5270c4a;result runs/babel-dev3-input-readiness-20260908/10359297/result.json and private launcher investigation/dev3-input-readiness-20260908/check.sbatch. No providers,metadata changes,or scientific owner interruption.

- 13:10 EDT: Full native retry10359309 uses investigation/result20-checkpoint-retry-20260908/condition.sbatch full-trace --workers60 --audit-workers60,source1f995df,same scientific outputs,new dispatcher-full-trace-result20-checkpoint-retry namespace,4CPU/128GiB/shared60. Full report10359310 followsafterok10359309;combined10359311 follows10359080/10359310;unchanged derived10359093 dependency updated to10359311;superseded pending10359042/10359084 cancelled,earlyuser10359083/exposure10359085 unchanged.

- 13:13 EDT: da-18-1 input owner10359419 via investigation/dev3-da18-inputs-20260908/inputs.sbatch,launcher81be133,frozen source5270c4a,4CPU/128GiB/48h,stages seed then paraphrase,max_concurrency60 under existing shared60. Outputs runs/babel-dev3-da18-inputs-20260908/{seed,paraphrase},receipt job-10359419;live root /home/aydanh/rubric-gen-live/dev3-da18-inputs;native validation required before reuse.

- 13:25 EDT: Full-trace10359309 now owns detect at runs/babel-result20-current-20260908/full-trace/audit/biomnibench-da-factorial-r10-f0203f5d69f3,verified detect-command.json and60completed revision ledger. User10358980 remains live;nativefull10359310 and combined10359311/figures10359093 dependencies unchanged.

- 13:27 EDT: Early full-feedback policy pair10359686 followsafterok10359310 via investigation/result20-report-20260908/combine_full_pair.sbatch full-policy,output runs/babel-result20-current-20260908/full-policy-comparison-v1. Read-only exposure10359687 follows10359686 at full-policy-exposure-v1;each1CPU/8GiB/2h,no providers,unchanged frozen statistics/native coverage,independent of pending user-trace and final graph.

- 13:45 EDT: Full-trace10359309 COMPLETED29m36s;native report10359310 validates60assignments/2110semantic judgments,all Sol/Opus stages. Early pair10359686 and exposure10359687 completed;outputs full-policy-comparison-v1 and full-policy-exposure-v1 under runs/babel-result20-current-20260908;user10358980 remains the sole scientific owner.

- 13:53 EDT: Read-only matched mechanism10359878 COMPLETED15s,1CPU/8GiB,no providers;input full-policy-comparison-v1 plusfull-policy-exposure-v1,output full-policy-mechanism-v1/mechanism.json. Frozen evaluator decisions reused;no metrics or thresholds changed.

- 14:00 EDT: Artifact check10359928 COMPLETED11s,1CPU/8GiB,no providers;source investigation/result20-report-20260908/check_da12_4_artifact.py and output runs/babel-result20-current-20260908/da12-4-artifact-check-10359928/result.json retain source/artifact hashes.

- 14:13 EDT: Native user recovery10360063 afterany10358980 uses investigation/result20-user-resume-20260908/condition.sbatch user-trace --workers60 --audit-workers60,launcher746ab6c,source5270c4a,same capacity-v3 outputs,new dispatcher-user-trace-result20-capacity-v3-resume,4CPU/128GiB/shared60. Nativeuser10360067→earlypair10360075/combined10360076;exposure10359085 now depends10360067 andfigures10359093 depends10360076;superseded pending10359080/10359083/10359311 cancelled.

- 14:55 EDT: Native recovery10360063 RUNNING onbabel-l5-32 after terminal10358980(FAILED2h03m37s,56complete/4failed);receipt dispatcher-user-trace-result20-capacity-v3-resume/10360063-20260908T185326190363Z verifies5270c4a source/prior hashes and starts revise --resume --max-concurrency60. Same capacity-v3 study/audit outputs,4CPU/128GiB/account-free preempt/preempt_cpu_qos;report graph10360067→10360075/10360076,exposure10359085,figures10359093 unchanged.

- 15:07 EDT: Non-provider telemetry acceptance10360844 via investigation/telemetry-journal-20260908/check.sbatch,4CPU/8GiB/30min,account-free preempt/preempt_cpu_qos;tests capacity/runtime/launcher/architecture/evolution/red-team/pretreatment plus600NFS events from60threads in a fresh isolated directory. Output runs/telemetry-journal-check-10360844,source hashes before/after;productionglobalpool and active source remain untouched.

- 15:08 EDT: Non-provider10360844 COMPLETED46s;112tests pass26.76s and600NFS events from60threads validate0.0182s with source unchanged/independent hash readback. Acceptance receipt investigation/telemetry-journal-20260908/acceptance.json;future-only runtime candidate,not API concurrency evidence;scientific10360063 remains unchanged.

- 18:07 EDT: Native telemetry recovery10362700 RUNNING onbabel-l5-16,source05acf8e,original capacity-v3 YAML/output identity,59saved completions reused;receipt dispatcher-user-trace-result20-capacity-v3-telemetry/10362700-20260908T220455311437Z,4CPU/128GiB/shared60. Native report10362724→user-pair10362725/combined10362726;exposure10359085 follows10362724,figures10359093 follows10362726;obsolete pending10360067/10360075/10360076 cancelled,scientific owner untouched.

- 18:10 EDT: Request-compaction non-provider tests10362741 via investigation/request-compaction-20260908/check.sbatch,4CPU/8GiB/30min,main candidate source;evolution/red-team/pretreatment coverage. Scientific owner10362700 retains frozen05acf8e;no new scientific condition launched.

- 18:17 EDT: Request-format calibration10362844 RUNNING onbabel-l5-28 via investigation/request-compaction-20260908/provider_check.sbatch,4CPU/8GiB/30min;two concurrent configuredLuna calls compare largest saved da-16-1rep1 development assessment with lossless deduplication under shared60. Output runs/request-compaction-provider-10362844,source256f058;diagnostic schema/latency only,no scientific outcome replacement.

- 18:25 EDT: Non-provider regression10362885 completed via investigation/runtime-performance-20260908/regression.sbatch,4CPU/8GiB/30min;199tests pass45.83s. Log runs/slurm-rubric-runtime-regression-10362885.out;runtime source at4bd0fde plus unchanged candidate code,scientific10362700 retains frozen05acf8e.

- 18:28 EDT: Non-provider recovery integration10362903 completes48tests17.59s via investigation/runtime-performance-20260908/stage_recovery.sbatch;4CPU/8GiB/30min. Scientific10362700 remains live in finalround with59complete and two recovered/ongoing provider timeouts;reportdependencies unchanged.

- 18:29 EDT: Scientific10362700 entered detect --resume --max-concurrency60 after nativeuser-trace60/60 completion;same source05acf8e/outputidentity and one sharedauditstudy. Native10362724→userpair10362725/combined10362726 dependencies remain valid.

- 18:31 EDT: Read-only Markdown renderer10362912 followsafterok10362726 via investigation/result20-report-20260908/write_markdown.sbatch,1CPU/8GiB/2h;requires480validatedrows/four60assignmentcoverages and hashedsuccessfulcombinationreceipt. Output docs/reports/2026-09-08/result20-four-condition.md;no metric recomputation or providers.

- 18:38 EDT: Token-pacing nonprovider10362923 passed48tests17.50s;isolated59757ce native/test validation10362926 runs via investigation/result20-token-recovery-20260908/validate.sbatch,4CPU/8GiB/30min,no providers. Current10362700 hascomplete120judgments ineachpost/finalartifact/finalrevision panel;fulltrajectory remainsSol60/Opus35 plus25ratefailures,outcomeauditsongoing.

- 18:41 EDT: Paced audit-only recovery10362935 afterok10362926/afterany10362700 via investigation/result20-token-recovery-20260908/condition.sbatch user-trace --workers60 --audit-workers60;source59757ce,originalcapacity-v3YAML/outputs,4CPU/128GiB/shared60/Anthropic8Mtokensperminute. Native96tests/60revisionvalidation10362926 passed;runtimeprobe then detect --resume only,no revisionrerun. Native10362937→userpair10362938/combined10362939;exposure10359085,figures10359093,Markdown10362912 reconnected;supersededpending10362724/25/26cancelled.

- 18:49 EDT: Paced10362935 terminalCOMPLETED6m24s with result exits[0],source_unchanged/success true;native10362937 then10362938/39 and existing exposure/figure/Markdown dependencies remain queued. No scientific rerun or new output identity;token-recovery receipt retained in dispatcher-user-trace-result20-capacity-v3-token.

- 18:52 EDT: Read-only user mechanism10363080 afterok10362938/10359085 via investigation/result20-report-20260908/user_pair_mechanism.sbatch,1CPU/8GiB/2h;verifies matched seed/selected hashes and joins native RH transitions to online admission/penalties. Output runs/babel-result20-current-20260908/user-policy-mechanism-v1;no providers or revised scientific outcomes.

- 19:00 EDT: Result20 report-v2 complete:analysis.json,figures/{avg-result20-20260908.png,openai-anthropic-average-result20-20260908.png,plot-values.csv,provenance.json},policy/feedbackexposure and recovery diagnostics;derived10359093 result exits[0,0,0,0]/sourceunchanged. docs/reports/2026-09-08/result20-four-condition.md createdby10362912;no Slurmjobs remainactive/pending at this check.

- 19:00 EDT: Nonprovideracceptance10363122(control9dd3b40)/10363123(candidate8f4880f) via investigation/dev3-evidence-sidecar-20260908/validate.sbatch <control|evidence>,4CPU/8GiB/30min,accountfreepreempt. Output runs/dev3-evidence-validation-<job>;validates3native seed/paraphrasepools plusworkflowtests;scientific configs/outputnamespaces prepared in samebundle,not yet launched.

- 19:02 EDT: Queued10363145/10363146 afterok10363142 via investigation/dev3-evidence-sidecar-20260908/condition.sbatch <control|evidence> da-11-1 --workers60 --audit-workers60;launchercommit5420a1a,4CPU/128GiB/48h,shared60/token8M. Sourcecontrol9dd3b40/candidate8f4880f;outputs runs/babel-dev3-evidence-sidecar-20260908/{control,evidence}/da-11-1/{study,audit}/{experiment_id},ownerreceipts owners/{control,evidence}-da-11-1;native resume and boundedrevisionrecoveryinsidejob,da3/da18heldpendingrealgate.

- 19:05 EDT: Replacementnonprovidervalidation10363149(control6498d78)/10363150(candidate4a8cebe) supersedes10363122/23 for scientificallyunstartedarms;samevalidate.sbatch/inputconfigs,addsassert64K/4MiB capacities. Jobs10363145/46heldpendingnewlaunchcheck;oldlaunchcheck10363142 passed but binds superseded source receipts.

- 19:08 EDT: Matched da11 native/report10363168 afterok10363145:10363146 via investigation/dev3-evidence-sidecar-20260908/analyze.sbatch control,4CPU/8GiB/30min,no providers. Outputs runs/babel-dev3-evidence-sidecar-20260908/da11-comparison-v1/{control-native,evidence-native,analysis.json,receipt.json} and docs/reports/2026-09-08/dev3-evidence-da11.md;source-specificchecks precede labeled merge/matchedseedvalidation.

- 19:09 EDT: Scientific10363145 RUNNINGbabel-l5-16 and10363146 RUNNINGbabel-l5-28;bothlaunchreceipts confirm6498d78/4a8cebe and native revise-1 command,60/60workers. Bothderive experimentIDbiomnibench-da-factorial-r10-bef4da388a1f in separatearmnamespaces;analysis10363168 must preserve explicitarm labels.

- 19:17 EDT: Monitor regression10363273 completed45s,8tests pass11.12s;future-only scripts/babel/monitor.py scope filter,not deployed into active10363145/46. Matched analysis10363168 remains pendingboth scientificowners;its output additionally records initial-training-rubric/criteria hashes per arm and replicate.

- 19:47 EDT: Non-provider contrast-proposer acceptance10363823 via investigation/dev3-evidence-contrast-20260908/check.sbatch,4CPU/8GiB/30min,source isolated from4a8cebe; output runs/dev3-evidence-contrast-check-10363823. No scientific candidate launched; current10363145/46 and dependent10363168 remain untouched.

- 20:02 EDT: Prepared contrast59fb4d0 launch acceptance10364008 completes native3task/9seed/paraphrase validation plus matchedYAML/source/config/scope guards; receipt runs/dev3-evidence-contrast-launchcheck-10364008/result.json. No scientific follow-up submitted; isolated launcher/configs/acceptance at investigation/dev3-evidence-contrast-20260908.

- 20:07 EDT: Rubric-cue sourceed6f316 non-provider validation10364128 and afterok launcher-check10364139 use investigation/dev3-rubric-cue-20260908; three nativeinputpools/shared60,4CPU/8GiB validation. Prepared scientific cue configs execute3static assignments/task, isolated runs/babel-dev3-rubric-cue-20260908/cue/<task>/{study,audit}/{experiment_id}; original policyowners unchanged.

- 20:08 EDT: Authorized rubric-cue static scientific10364143 submitted afterok10364139 via investigation/dev3-rubric-cue-20260908/condition.sbatch cue da-11-1 --workers60 --audit-workers60; frozened6f316,4CPU/128GiB/48h/shared60/account-freepreempt. Outputs runs/babel-dev3-rubric-cue-20260908/cue/da-11-1/{study,audit}/{experiment_id},owner owners/cue-da-11-1; compare against immutable staticcontrol10363145, no duplicatecontrol.

- 20:11 EDT: Rubric-cue10364143 verified RUNNINGbabel-l9-20 with sourceed6f316/60workers and unique owner receipt. Read-only matched report10364169 followsafterok10363145:10364143,outputs runs/babel-dev3-rubric-cue-20260908/da11-comparison-v1 and docs/reports/2026-09-08/dev3-rubric-cue-da11.md; unstartedreport10364166 replaced to remove a copied shell positional-argument requirement, no scientific jobs interrupted.

- 20:17 EDT: Control10363145 completed1h06m38s with exits[0,0]/sourceunchanged and native6assignments/174semanticjudgments/Sol+Opus coverage. Evidence10363146 completed3revisions and proceeds to audits; rubric-cue10364143 remains live, reports10363168/10364169 unchanged. Read-only compute-storage10364194 uses investigation/biomnibench-results45-20260908/storage_check.sbatch,1CPU/1GiB/5min,output runs/results45-storage-check-10364194.

- 20:20 EDT: Canonical Results45 data-preparation10364235 via investigation/biomnibench-results45-20260908/prepare_data.sbatch,4CPU/8GiB/4h, no providers; destination /data/user_data/aydanh/rubric_gen/data/biomnibench-da-results45-e1c8ca5e11a62,receipt runs/results45-data-prepare-10364235. Read-only10364194 verified shared383GiBfree; originaldata and allscienceowners untouched, scale-up remains gated.

- 20:24 EDT: Evidence10363146 COMPLETED1h12m24s, exits[0,0]/sourceunchanged; matchedreport10363168 COMPLETED12s with18validatedauditorrows. Contrastfollowup10364255 submitted via investigation/dev3-evidence-contrast-20260908/condition.sbatch contrast da-11-1 --workers60 --audit-workers60,source59fb4d0,4CPU/128GiB/48h/shared60,outputs runs/babel-dev3-evidence-contrast-20260908/contrast/da-11-1/{study,audit}/{experiment_id}.

- 20:27 EDT: Contrast10364255 verified RUNNINGbabel-l5-16/frozen59fb4d0/shared60; matched nativereport10364276 followsafterok10364255 via investigation/dev3-evidence-contrast-20260908/analyze.sbatch. It validates allthree producing sources and24auditorrows with explicitfourlabels, checks initialrubric/seed/selectedmatches, and writes runs/babel-dev3-evidence-contrast-20260908/da11-comparison-v1 plus docs/reports/2026-09-08/dev3-contrast-da11.md.

- 20:30 EDT: Canonical control extensions10364286(da-3-4) and10364289(da-18-1), each6assignments via investigation/dev3-evidence-sidecar-20260908/condition.sbatch control <task> --workers60 --audit-workers60. Source6498d78/nativeinputacceptance10363149 unchanged;4CPU/128GiB/48h/shared60, outputs runs/babel-dev3-evidence-sidecar-20260908/control/<task>/{study,audit}/{experiment_id} and distinctowners control-<task>; no priorowners found.

- 20:41 EDT: New120-assignment Result20 static10364363/trace10364364 RUNNINGbabel-l9-20/babel-m9-20, frozen0fbe0bb,via investigation/result20-cue-contrast-20260908/condition.sbatch <static|trace> results20 --workers60 --audit-workers60;4CPU/128GiB/48h/shared60. Nativevalidation10364343 passed198tests1skip/all60seeds,launchcheck10364359 sixpassed; report10364371 afterokboth writes comparison-v1 plus result20-cue-contrast.md. Fresh runs/babel-result20-cue-contrast-20260908 namespace, existingdev3owners preserved.

- 20:51 EDT: Native static continuation10364765 queued afterany10364363 using the identical condition.sbatch static results20 --workers60 --audit-workers60, source0fbe0bb and same owner/output namespace. Existing unstarted report10364371 now afterok10364765:10364364; no active process interrupted.

- 21:34 EDT: Native10364765 rejects da10rep3(workspace mismatch) and da15rep2(incomplete failedturn), while recovering da16rep1. Guarded archive10365214 queuedafterany10364765, then fresh native10365215 afterokarchive; report10364371 now afterok10365215:10364364. Archive moves only exacttwofailed directories with originalmanifest/evidence preserved and requires58complete;3nonprovider guard tests pass.

- 21:43 EDT: Archive10365214 failed before mutation due trailing-delimiter assumption in sacct parsing; corrected parser/3tests, replacement10365243 COMPLETED15s. Exacttwofailed directories preserved under invalid-attempts/pre-fresh-10365243 with unchanged study manifest; existing10365215 reconnectedafterok10365243, finalreport unchanged.

- 22:01 EDT: Canonical control report10365669 COMPLETED23s after correcting template-only argument failure10365649; outputs runs/babel-dev3-evidence-sidecar-20260908/canonical-controls-v1 and docs/reports/2026-09-08/dev3-canonical-controls.md. Static fresh-cell10365215 has60/60revisionscomplete, trace10364364 has57complete/3running; report10364371 remains pendingvalidatedboth.

## 2026-09-08 Artifact evidence calibration v1

- 22:30 EDT: Source `runs/babel-code/audit-artifact-evidence-v1` commit `df0ce37`; protocol/launcher/report in `investigation/artifact-audit-diagnostic-20260908/`. Nonprovider validation10365985 completed120sealedartifact checks; initial10365973 failed beforeproviderwork on missingowner directory, fixed. Audit10366032 afterok10365985:10364371, report10366051 afterok10366032; output `runs/babel-artifact-audit-evidence-v1-20260908`, report `docs/reports/2026-09-08/artifact-audit-evidence-v1-results.md` pending.4CPU128GiB48h accountfreepreempt/preempt_cpu_qos, shared60/oneauditstudy; native finalartifact-only resume for static60+trace60, Sol+Opus240newjudgments.

- 22:39 EDT: Criterion census10366145 produced `runs/babel-result20-cue-contrast-20260908/criterion-admission-census-v1/analysis.json` and `docs/reports/2026-09-08/result20-cue-criterion-admissions.md`; private script `investigation/result20-cue-contrast-20260908/exposure.py`, no providercalls or originaloutput mutation.

- 22:52 EDT: Trace10364364 completed with exits[0,0]/sourceunchanged; combinedreport10364371 validated all240auditorrows and matchedseed/selectedhashes. Canonical outputs `runs/babel-result20-cue-contrast-20260908/comparison-v1`; fullreport and interpretation in `docs/reports/2026-09-08/result20-cue-contrast.md` and `result20-cue-interpretation.md`; separateaudit10366032 active.

- 22:55 EDT: Diagnostic10366032 COMPLETED55s/exits[0,0], report10366051 COMPLETED17s; completepairedartifactreport `docs/reports/2026-09-08/artifact-audit-evidence-v1-results.md`, analysis `runs/babel-artifact-audit-evidence-v1-20260908/comparison-v1/analysis.json`. Allpreviousownedjobs nowterminal; noautomatic newrevisionlaunch.

- 23:03 EDT: Artifactcalibrationv2 source52248d5 in `runs/babel-code/audit-artifact-evidence-v2`; validation10366357 passed120artifacts. Audit10366366, report10366367; bundle `investigation/artifact-audit-calibration-v2-20260908`, outputs `runs/babel-artifact-audit-evidence-v2-20260908`;4CPU128GiB48h,shared60,SolOpus240judgments, no revisionreruns.

- 23:07 EDT: Calibrationv2 10366366 and report10366367 completed; outputs `runs/babel-artifact-audit-evidence-v2-20260908/comparison-v1`, report `docs/reports/2026-09-08/artifact-audit-evidence-v2-results.md`; decision `artifact-audit-calibration-decision.md`. Allownedjobsterminal; nextpolicytest notyetimplemented/launched.

- 23:12 EDT: Crossfilevalidation10366419 passedfocusedtests, all60seeds/sealedparaphrases, exactscientific/runtime diff andunchangedconfigexceptoutputpaths. Source3f9d81bc3a403dcb3c13ea0a62cdfa0e1a1f341d `runs/babel-code/result20-crossfile-consistency`; job10366421 via `sbatch investigation/result20-crossfile-consistency-20260908/condition.sbatch trace results20 --workers 60 --audit-workers 60`; report10366435 afterok10366421. Outputs `runs/babel-result20-crossfile-consistency-20260908`, config/protocol/acceptance undermatchinginvestigationbundle; originalstatic10365215/trace10364364 reused, no duplicatecontrols.

- 23:22 EDT: Frozenv2 sensitivity fornewcrossfile only queued: validation10366468 afterprimaryreport10366435, audit10366473 aftervalidation, report10366475 afteraudit. Bundle `investigation/result20-crossfile-artifact-v2-20260908`; outputs `runs/babel-result20-crossfile-consistency-20260908/artifact-v2`;120newjudgments, existing240controljudgmentsreused; evaluator52248d5 unchanged.

- 23:59 EDT: Crossfile10366421 has37completed/22running/one infrastructure-failed assignment. Isolated repair10366940 has completed that exact assignment under a587028; audit remains active. Survivor audit10366975 waits afterany10366421; primary report10366435 waits afterok10366975:10366940. Optional sensitivity validation10366468 is held pending adaptation to the59+1 source population;10366473/10366475 remain dependent, no active job interrupted.

## 2026-09-09 Recovery-aware audit continuation

- 00:02 EDT: Repair10366940 completed both stages with source unchanged. Optional stale pending jobs10366468/73/75 were replaced by validation10367025 → audit10367028 → report10367029, validation after primary10366435; isolated evaluator runtime61a107b preserves frozenv2 prompt with operational assignment scoping.

- 00:24 EDT: 10366975 active on59valid original revisions after terminal10366421; report10366435 remains afterok10366975:10366940. Optional10367025→10367028→10367029 follows primaryreport; all60usable revisions nowavailable.

- 00:41 EDT: All audit stages10366975 completed. Report-only retry10367427 writes comparison-v2, retaining failed comparison-v1; optional10367025 dependency reconnected afterok10367427, then10367028→10367029. No provider rerun.

## 2026-09-09 Selected criterion score-disclosure gate

- 00:53 EDT: Cue-score mocked validation10367495 passed177tests; input/source validation10367516 completed. Real one-assignment gate10367528 submitted via investigation/result20-cue-score-20260909/condition.sbatch static results20 --workers60 --audit-workers60; source10e60b8, outputs runs/babel-result20-cue-score-20260909/static/{study,audit}/{experiment_id}, ownlease.4CPU128GiB48h accountfreepreempt,global60; full20×3 ledger retained with one explicit execution assignment.

- 00:57 EDT: Gate10367528 active, first exposure grounded to criterion4=0 and exact concern present in solverprompt. Prepared disjoint59assignment expansion in investigation/result20-cue-score-scale-20260909; nonprovider validation10367561 submitted. Scale launcher refuses execution until gate success/sourceunchanged and native Sol/Opus coverage1 are saved; no expansion providerjob submitted.

- 01:08 EDT: Boundedscore source4d5c2d0: tests10367576 passed; inputreplay validation10367602 passed after import-only failure10367595; simulator-only replay10367607 completed6responses withcorrectdisclosureboundary. Fullsource/input validation10367620 passed; static60job10367631 submitted using investigation/result20-cue-score-bounded-20260909/condition.sbatch static results20 --workers60 --audit-workers60. Outputs runs/babel-result20-cue-score-bounded-20260909/static/{study,audit}/{experiment_id};4CPU128GiB48h,shared60. Original10367528 remainsindependent; old59expansionblocked.

- 01:11 EDT: Matched boundedscore report10367657 queuedafterok10367631, private analyze.py/sbatch in samebundle; outputs runs/babel-result20-cue-score-bounded-20260909/comparison-v1, compares to completedcue-static10365215 withsource-native fullcoverage.

- 01:20 EDT: Slurm preempted10367631 after9m32s, with6completed assignments; noHTTPerror recorded. Native same-source resume10367784 started onbabel-m9-20 and advanced saved checkpoints; report10367657 reconnected afterok10367784. Currentcpu partition absent; general CPU-only rejected(min1GPU). Account-free general/normal4CPU128G1A6000/48h test-only accepted but estimated09:54start, so do not move the healthy immediate recovery into that queue. Test-only response10367800 is not a submitted job.

- 01:24 EDT: Nativepreemptionresume10367784 rejected six RuntimeError live-workspace mismatches; other54continue. Exact6repair validated10367826 and submitted10367835, same4d5c2d0/newisolatedoutputs runs/babel-result20-cue-score-preempt-repair-20260909/static/{study,audit}; originals preserved. Survivor audit10367838 afterany10367784 requires exactsixfailures. Report10367657 held pending54+6reader adaptation, dependenciesafterok10367838:10367835; release afteradaptation. No successfulcellrerun.

- 01:26 EDT: Released report10367657 after explicit54+6adapter completion; dependenciesafterok10367838:10367835. Native report preserves exactsix RuntimeError exclusions,180inactiveentries andall rawscoringchecks; expects120control+108original+12repair auditorrows andcanonical60candidatecells. Both10367784/10367835running; source4d5c2d0unchanged.

- 02:11 EDT: Score-only checkout runs/babel-code/result20-cue-score-only atbc9f096 passed70tests; validation10368292 submitted via investigation/result20-cue-score-only-20260909/replay.sbatch validate. Outputs runs/babel-cue-score-only-replay-20260909/JOB_ID; run mode requires validationjobID and exactrequest/input equality.

- 02:11 EDT: Six-call score-only replay10368294 queued afterok10368292, command replay.sbatch run 10368292; same frozen contexts/model, no revision or audit calls.

- 02:16 EDT: Explicit-score replay source1fcb24a at runs/babel-code/result20-cue-score-explicit; validation10368336→afterok six-call replay10368341 via investigation/result20-cue-score-explicit-20260909/replay.sbatch run 10368336. Outputs runs/babel-cue-score-explicit-replay-20260909/JOB_ID; historical contexts and provider identity unchanged.

- 02:20 EDT: First-concern score source7cd0b76 at runs/babel-code/result20-cue-score-first; validation10368371→six-call replay10368372, same two sealedcontexts. Bundle investigation/result20-cue-score-first-20260909, outputs runs/babel-cue-score-first-replay-20260909/JOB_ID; no revision cohort launched.

- 02:24 EDT: Nativevalidation10368389→condition10368391→matchedreport10368397; bundle investigation/result20-cue-score-first-20260909, frozen source7cd0b76. Condition command condition.sbatch static results20 --workers60 --audit-workers60;4CPU128GiB48h account-freepreempt,global60. Outputs runs/babel-result20-cue-score-first-20260909/static/{study,audit}/{experiment_id}; report comparison-v1 and docs/reports/2026-09-09/result20-cue-score-first.md. Nativefullcoverage required; no oldreplay pooled.

- 03:24 EDT: Resume10368806 uses identical condition.sbatch/staticresults20/global60 and outputs; original10368391receipt preserved. Sevenmissing finalartifact cases recorded runs/babel-result20-cue-score-first-20260909/failure-checkpoint-10368391/failed-audits.json; report10368397 nowdependsafterok10368806 and readsits receipt.

- 03:32 EDT: Matched first-score trace source7cd0b76 uses investigation/result20-cue-score-first-trace-20260909/condition.sbatch trace results20 --workers 60 --audit-workers 60; validation10368823 passed, owner10368826, report10368828 afterok. Outputs runs/babel-result20-cue-score-first-trace-20260909/trace/{study,audit}/{experiment_id}, comparison-v1; account-free preempt/preempt_cpu_qos,4CPU128G48h,shared60. Static control10368806 remains immutable.

- 03:36 EDT: Queued read-only criterion admission census10368839 afterok10368826 using investigation/result20-cue-score-first-trace-20260909/exposure.sbatch. Requires native success and60states; writes criterion-admission-census-v1 and score-first-trace-criterion-admissions.md, explicitly separating admission from delivery/causation.

- 06:09 EDT: Candidate checkout runs/babel-code/result20-input-provenance at a1e8ec2; bundle investigation/result20-input-provenance-20260909. Nonprovider test job10369646 via validate.sbatch,4CPU8G30min account-free preempt/preempt_cpu_qos; log runs/slurm-rubric-input-provenance-check-10369646.out.

- 06:12 EDT: Mechanism10369662 afterok10369646 via investigation/result20-input-provenance-20260909/mechanism.sbatch; output runs/input-provenance-mechanism-10369662,4CPU128G1h account-free preempt/preempt_cpu_qos, sequentialtwo sidecars under shared60. No natural solver cohort or outcome-audit rerun.

- 06:23 EDT: Nonprovider canonical checks10369681(raw intersection) and10369689(workbook flags), investigation/result20-input-provenance-20260909/verify{,_flag}_counts.sbatch;4CPU8G30min, outputs runs/input-provenance-count-check-JOB_ID/result.json. Flag check records canonical input/script hashes; no solver/auditor calls.

- 06:28 EDT: Native induction diagnostic10369697 submitted via investigation/result20-input-provenance-20260909/induction.sbatch on verified rep003 sidecar; outputs runs/input-provenance-induction-JOB_ID. Uses candidatea1e8ec2, unchanged native blinded history/admission,4CPU128G1h, shared60; isolated generation2, not a resumed study or natural RH measurement.

- 06:30 EDT: Proposer diagnostic10369710 via investigation/result20-input-provenance-proposer-20260909/induction.sbatch; source87bc6fc, outputs runs/input-provenance-proposer-induction-10369710.4CPU128G1h preempt/preempt_cpu_qos account-free, shared60; focused tests gate provider execution.

- 06:33 EDT: Fixed-assessment diagnostic10369714 via investigation/result20-input-provenance-proposer-20260909/fixed_assessment.sbatch; outputs runs/input-provenance-fixed-assessment-10369714. Same87bc6fc; exact saved assessment requests from10369697 only, fail closed on mismatch, separately recorded replay metadata; new provider calls only induction/validation,4CPU128G1h/shared60.

- 06:38 EDT: Evidence sensitivity10369738 via investigation/result20-execution-evidence-20260909/diagnostic.sbatch; outputs runs/execution-evidence-diagnostic-10369738. Two native criterion-validator calls, narrative versus same artifact plus all completed turn001 command records; frozen7cd0b76/proposer settings,4CPU128G1h/shared60. Not native weak-score rerun or outcome-audit replacement.

- 06:42 EDT: Weak-context diagnostic10369750 via investigation/result20-execution-evidence-20260909/weak_context.sbatch; outputs runs/weak-context-diagnostic-10369750. Native FrozenRubricJudge at7cd0b76, s001/s003 crossed full active rubric versus isolated unchanged criterion, four planned calls;4CPU128G1h/shared60. Validate both rubrics before calls; no historic score replacement.

- 06:43 EDT: Replacement diagnostic10369754 via investigation/result20-execution-evidence-20260909/weak_context_v2.sbatch; output runs/weak-context-diagnostic-10369754. Failed10369750 retained; no completed calls to reuse. Same4CPU128G1h/shared60.

- 06:44 EDT: Diagnostic10369755 uses weak_context_v3.sbatch; output runs/weak-context-diagnostic-10369755 with one validated judgment reference to10369754. Failed runners/output paths preserved, no reset or duplicate first judgment.

- 06:48 EDT: Validation10369770 via investigation/result20-criterion-update-20260909/validate.sbatch; checkout runs/babel-code/result20-criterion-update atffe10c4,4CPU8G30min; focused delivery and submission-revision/evolution tests. No scientific cohort submitted yet.

- 06:49 EDT: Replay10369771 afterok10369770 via investigation/result20-criterion-update-20260909/replay.sbatch; output runs/criterion-update-replay-10369771,4CPU8G30min. No provider calls or historical mutation.

- 06:51 EDT: Native input validation10369780 via result20-criterion-update bundle; accepts onlyffe10c4 feedback.py source diff and unchanged canonical scientific YAML aside from fresh output paths. Output acceptance.json owned by validation; no historical compatibility edits.

- 06:51 EDT: Trace owner10369781 afterok10369780: investigation/result20-criterion-update-20260909/condition.sbatch trace results20 --workers60 --audit-workers60. Sourceffe10c4; runs/babel-result20-criterion-update-20260909/trace/{study,audit}/{experiment_id}, owner receipts underowners/trace-results20;4CPU128G48h account-freepreempt/shared60.60new assignments, existing matched controls reused.

- 06:53 EDT: Validation10369780 passed native inputs/tests/source checks; trace10369781 verified RUNNING babel-m9-20. Three-condition report10369784 afterok10369781 uses investigation/result20-criterion-update-20260909/analyze.sbatch; writes comparison-v1 and docs/reports/2026-09-09/result20-criterion-update.md, expects180assignments/360auditorrows and matched seed/selected hashes.

- 06:55 EDT: Delivery census10369789 afterok10369781 via delivery.sbatch; outputs criterion-delivery-v1 and docs/reports/2026-09-09/criterion-update-delivery.md. Current experiment IDbiomnibench-da-factorial-r10-082bfc062548; owner10369781-20260909T105301051137Z.

## 2026-09-09 — Criterion-update audit-only recovery

- 08:38 EDT: Owner10369781 finished revisions/allRH/rubric scoring but failed holistic scoring with OpenAI APIConnectionError after232saved judgments; source unchanged. Submitted10370563 via investigation/result20-criterion-update-20260909/audit_recovery.sbatch (native detect60/resume only, same4CPU128Gpreempt); reports10369784/10369789 dependencies repaired and now bind recovery receipts, preserving original failed owner and all completed stages.

- 09:01 EDT: Read-only cue admission census10370591 and native saved-decision replay10370742 completed (1CPU4G15min, no providers), scripts investigation/result20-case-mechanisms-20260909/cue_support_{census,replay}.py; reports docs/reports/2026-09-09/rubric-cue-support-{census,replay}.{md,json}.

- 09:01 EDT: Audit validation recovery10370740 completed with native full coverage2134semantic judgments (60assignments), same frozen wrapper/source with audit-workers8 and aggregate60; prior10370563 completed missing holistic work but failed10hosted token-count preparation requests before saved-RH lookup. Failed summary snapshots preserved under10370563 receipt; reports10369784/10369789 repaired to10370740, delivery10369789 completed.

- 09:12 EDT: Report10369784 failed only on relative pretreatment paths after saving all three native per-arm analyses; report-only recovery10370774 corrected root resolution and reused hash-verified analysis files, writing comparison-v2/analysis.json plus receipt and docs/reports/2026-09-09/result20-criterion-update.md. Delivery10369789 complete; no owned jobs remain at checkpoint.

- 09:12 EDT: Prepared—not submitted—investigation/cue-citation-diagnostic-20260909/inputs.json:4saved online generation contexts, mechanism anchor da12-4rep2g7 plus deterministic distinct-task selection da12-2rep3g3,da15-8rep3g4,da15-7rep3g4. Next action is implement/validate an induction-only matched frozen-prompt repeat versus citation-precision diagnostic with native independent validation; no revision run yet.

- 09:20 EDT: Non-provider validation10370819 passed all four frozen contexts and original native admission replay; investigation/cue-citation-diagnostic-20260909/acceptance.json binds source and inputs. Existing Python3.12 environment and frozen cue uv.lock match current lock; real diagnostic submission follows this gate.

- 09:27 EDT: Proposer-only10370826 atde36226 completed; outputs runs/cue-citation-diagnostic-10370826, detailed results docs/reports/2026-09-09/cue-citation-diagnostic-result.md. Non-provider artifact routing10370831 passed, receipt investigation/artifact-routing-candidate-20260909/verification.json; no production switch. Validation-repeat input gate10370851 submitted, no real repeat yet.

- 09:34 EDT: Validation-only10370858 at37b45b5 completed4/4contexts without provider failures; outputs runs/cue-validation-repeat-10370858. Read-only report10370933 writes docs/reports/2026-09-09/cue-validation-repeat-result.{md,json}; no induction/revision/outcome calls or historical replacement.

- 09:44 EDT: Saved-input validation10370980 passed44requests; diagnostic10370981 at1b7938b runs88paired validation calls via investigation/cue-application-context-20260909/probe.py run,4CPU8G30min account-freepreempt,16localworkers/shared60. Output runs/cue-application-context-10370981; no induction/revision/outcome stages.

- 09:46 EDT: Context diagnostic10370981 completed88/88calls in46seconds; raw runs/cue-application-context-10370981 and report docs/reports/2026-09-09/cue-application-context-result.md.

- 09:55 EDT: Read-only terminal-penalty census10371023 submitted using investigation/cue-terminal-penalties-20260909/census.py,1CPU4G10min preempt CPU, no providers. Output runs/cue-terminal-penalties-10371023/result.json; all60cue trace assignments required.

- 10:02 EDT: Census10371023 complete60/60; runs/cue-terminal-penalties-10371023/result.json preserves hashes/checkpoints. Private join.py reuses saved census/paired reports; docs/reports/2026-09-09/cue-coverage-gap-join.{md,json} records every auditor row.

- 10:20 EDT: Native saved-admission replay10371227 submitted with1CPU4G15min account-freepreempt CPU; investigation/cue-ranking-replay-20260909/replay.py uses frozen cue source and hash-validated native contexts. Output runs/cue-ranking-replay-10371227/result.json; no providers, no revisions.

- 10:23 EDT: Native replay10371227 completed52contexts/72decisions; raw runs/cue-ranking-replay-10371227/result.json and cue-ranking-replay-result.md. Eleven new hypothetical admissions include3offline, leaving8eligible online; no new behavior run.

- 10:22 EDT: Real frozen-input validation10371323 submitted atf334224 with1CPU4G15min preempt CPU; private investigation/cue-frozen-input-validation-20260909/validate.py forbids providers and requires all20source rubrics unchanged. Output runs/cue-frozen-input-validation-10371323/result.json; this is a validation-only job.

- 10:23 EDT: Validation10371323 completed2seconds,20/20inputs; receipt runs/cue-frozen-input-validation-10371323/result.json and docs/reports/2026-09-09/cue-frozen-input-validation.md. No jobs remain from this validation.

- 10:26 EDT: Integration-only10371412 submits current working-tree explicit-source study preparation on20real inputs, then repeats preparation to check immutable resume.1CPU4G15min preempt CPU; providers forbidden; investigation/cue-frozen-input-validation-20260909/integrated.py, output runs/cue-frozen-integrated-10371412. No revision/workflow launch.

- 10:27 EDT: Integration harness10371412 failed before validation because it serialized loader-derived assignments; corrected to source YAML keys only. Replacement diagnostic10371416 uses a fresh output runs/cue-frozen-integrated-10371416; no scientific/provider calls affected.

- 10:29 EDT: Integration10371416 failed on nested normalized YAML fields before input work; raw-YAML attempt10371424 passed20preparations plus20unchanged repeats in10seconds. Output runs/cue-frozen-integrated-10371424/result.json; provider calls forbidden and no scientific jobs launched.

- 10:38 EDT: Prepared matched trace-only bundle investigation/result20-cue-ranking-20260909 at isolated source1314fac, runs/babel-code/result20-cue-ranking. Validation10371494 checks60assignments/sharedseeds/20frozenstartingrubrics and exact cue prompts; no scientific job submitted yet.

- 10:40 EDT: Scientific trace-only owner10371501 RUNNING babel-l5-16; source1314fac, bundle5ad8134, experimentbiomnibench-da-factorial-r10-cd5035b709b4. Command sbatch investigation/result20-cue-ranking-20260909/condition.sbatch trace results20 --workers60 --audit-workers60;4CPU128G48h account-freepreempt/shared60; outputs runs/babel-result20-cue-ranking-20260909/trace/{study,audit}/{experiment_id}.

- 10:42 EDT: Queued provider-free report10371512 afterok10371501,4CPU16G1h preempt CPU; investigation/result20-cue-ranking-20260909/analyze.py reuses complete cue static/original-trace rows and validates only new ranking-native data. Outputs comparison-v1 plus docs/reports/2026-09-09/result20-cue-ranking.md.

- 10:51 EDT: Provider-free joint-gate/exposure job10371561 queued afterok10371512,1CPU8G30min account-free preempt CPU. Frozen helper keeps original trace and ranking trace separate; output comparison-v1/joint-and-exposure-10371561, source7cf984a; no new scientific result or revision work.

- 11:43 EDT: Confirmation data-only check10372102 submitted1CPU2G10min account-free preempt CPU, pending Priority; script investigation/confirmation-pools-20260909/check_data.py; expected runs/confirmation-pool-data-check-10372102/result.json. No model calls or downloads; current scientific owner10371501 untouched.

- 12:08 EDT: Authenticated pinned BioMNIBench additions download10372571 running with cached login; first5addedtasks hash-verified, original20preserved. PaperBench data-only10372604 running1CPU8G4h, source551a45b: pinned23papers across separate all/devdirectories, source-size/capacity gate reserves180GiB, native download/validation then file-hash seal; no model calls.

- 12:09 EDT: Ranking10371501 completed60/60revisions and entered detect-1 in the same allocation; no separate revision-recovery job. PaperBench10372604 capacity gate passed87,135,025hydratedbytes estimate against400,093,609,984freebytes with180GiBother-workreserve; native download active. BioMNIBench10372571 has25/45tasks hash-verified (original20plus5additions).

- 12:16 EDT: PaperBench data-only retry10372686 completed23pinnedpapers/479hashedfiles/89,097,628bytes, native validation passed and both splits sealed; initial10372604DNSfailure preserved. Receipt runs/paperbench-data-prepare-10372686/result.json; no scientific stages.

- 12:21 EDT: Post-download native canonical hash verification10372829 queuedafterok10372571,1CPU2G1h; absolute shared target, no mutation/generation. User approves compute-onlyNFS; login visibility no longer a gate. Current data39/45verified, rankingauditowner10371501live; reports10371512/10371561remainpending.

- 12:31 EDT: Ranking10371501finished revisions+audits exits[0,0], sourceunchanged; dependent10371512/10371561analyses pending. Paraphrase10372887failed before generation on native traceconditionID; corrected839c466 and retry10372893submitted, no successfulcellregeneration.

- 12:34 EDT: Paraphrase-only10372893completed,45tasks/225variants across original20reuse and additional25new; native static/trace consumers both validate, poolSHA256receipts runs/confirmation-paraphrases-10372893/result.json. No seed generation or downstream stages; pools sealed on sharedNFS.

- 12:40 EDT: Joint/exposure10371561 completed; outputs comparison-v1/joint-and-exposure-10371561. Private provider-free investigation/cue-ranking-mechanism-20260909/census.py validates120matched auditor triples and writes docs/reports/2026-09-09/cue-ranking-mechanism-census.{md,json}; no active Slurm jobs at the latest check.

- 12:57 EDT: Prepared—not submitted—investigation/result20-cue-active-violations-20260909/trace-results20.yaml; native experimentIDbiomnibench-da-factorial-r10-0dcc7da2367c,60trace assignments. New study/audit outputs are absolute /data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909/trace/{study,audit}/{experiment_id}; unchanged historical seed/paraphrase inputs remain read-only.

- 12:59 EDT: Candidate source frozen65bc7a7 in runs/babel-code/result20-cue-active-violations from1314fac, preserving cue simulator/induction. Provider-free validation10373088 onbabel-l5-16 failed at source_pool with pre-treatment source experiment identity mismatch after native seeds/paraphrases checks; logs runs/cue-active-validation-10373088.out, no scientific calls.

- 13:02 EDT: Provider-free native validation retry10373114 pendingPriority; isolated sourcec507d40 checks explicit producer digest against every completed source manifest and derived YAML identity. New candidate experimentIDbiomnibench-da-factorial-r10-b075d8e157d3 reflects the explicit producer provenance; no scientific job submitted.

- 13:04 EDT: Compute validation10373114 completed with60seeds/paraphrases/20frozenstartingrubrics; sourcec507d40, bundle0675408. Submitted scientific trace-only10373129 via investigation/result20-cue-active-violations-20260909/condition.sbatch trace results20 --workers60 --audit-workers60,4CPU128G48h account-freepreempt/shared60; outputs and owners /data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909, experimentbiomnibench-da-factorial-r10-b075d8e157d3.

- 13:06 EDT: Scientific10373129 verifiedrunningbabel-l9-20, owner10373129-20260909T170453486095Z with60statefiles and active revise-1. Queued provider-free report10373145 afterok10373129 (2CPU16G1h), outputs shared run comparison-v1 and home docs/reports/2026-09-09/result20-cue-active-violations.md; unchanged static/originaltrace reused.

- 13:07 EDT: Owner10373129 reached60activeprovider slots with60initialcheckpoints and no recordedearlyfailures; runtime report cue-active-runtime.md. Prespecified provider-free joint-gates10373156 queuedafterok10373145; no endpoint/threshold changes.

- 13:16 EDT: Provider-free delivery audit10373201 queuedafterok10373129,2CPU16G1h. Private delivery.py checks every submitted prompt against its checkpoint native judgment and records exactnote hashes; shared delivery-v1 plus docs/reports/2026-09-09/cue-active-delivery.md. No active experiment mutation.

## 2026-09-09 Single-assignment duplicate-pair recovery

- 14:29 EDT: Job10374492; source30ae38e71f0bd9ed37311ac70dd4a85c72b0fc0e; config investigation/result20-cue-pair-recovery-20260909/trace-results20.yaml; only da-14-3--rep-001--solver-luna--user-simulator-red-team-trace. Native acceptance10374477. Large output /data/user_data/aydanh/rubric_gen/runs/result20-cue-pair-recovery-20260909; unchanged shared aggregate60,4CPU128Gpreempt CPU. Original59completed cells remain in result20-cue-active-violations-20260909. Original audit did not launch; next prepare native audits of59original successes using genuine original source and separate replacement provenance.

- 14:31 EDT: Audit-only job10374539 runs native detect on original59completed cells under genuine producing commitc507d40 in runs/babel-code/result20-cue-original-audit; verifies source hashes against10373129receipt. Native failed-scope handling retains explicit failedcell, no ledger changes. Audit receipts /data/user_data/aydanh/rubric_gen/runs/result20-cue-active-violations-20260909/audit-owners/10374539; pairs with replacement10374492 only after complete native coverage.

- 14:36 EDT: Combined report10374557 depends on successful10374492and10374539; requires118original+2replacement auditor rows and120unique task/replicate/model keys before pairing with frozen static/trace. Output remains shared result20-cue-active-violations-20260909/comparison-recovered-v1. No provisional outcome selection; sources recorded separately.

- 14:34 EDT: Joint-gates10374566 depends on report10374557, unchanged prespecified endpoints and bootstrap. At compute check, audit10374539currentRHpass85/118judgments; replacement10374492threecheckpoints/turn_in_progress. These are runtime counts, not scientific outcomes.

- 14:40 EDT: Provider-free delivery audit10374602 follows replacement10374492; validates exactly59original+1replacement completed assignment IDs and all submitted notes against native scores. Preserves failedoriginal; outputshared delivery-recovered-v1, no provider calls.

- 15:30 EDT: Provider-free pair-orientation diagnostic10375869,1CPU4Gpreempt CPU, reads one frozen generation and writes shared pair-orientation-v1/evidence.json plus small home receipt; no providers or revisions. Investigates pair_c94a2cf8125fe4dc after prior citation/context diagnostics ruled out simply repeating those prompts.

- 15:38 EDT: Provider-free frozen pair census10375963,1CPU4G45minpreempt CPU; shared pair-census-v1/inventory.json, home count/hash receipt. Predetermined small-numerical-edit selection across completed trace histories, no providers/revisions/RH-based selection.

- 15:46 EDT: Provider-free context index10376030 depends afterok10375963; selects<=8task/replicate contexts in fixed source-path order plus discoveryanchor, records generation/request metadata under shared pair-context-index-v1. No scientific/provider call; pair-attribution diagnostic awaits frozen-request validation.

- 15:50 EDT: Contextindex10376030 completed9contexts; provider-free preparation10376065 verifies cached request/response hashes and36original/swapped control/clarification cells, producing shared cue-pair-attribution-20260909/inputs-v1. Four local transformation tests pass; no provider diagnostic launched.

- 15:55 EDT: Pair-attribution diagnostic10376113 submitted after acceptance10376065(9cachedcontexts/36cells); frozen main7aa465e, genuineproducer c507source, unchangedLuna contract,4localworkers/share60,1CPU4G45minpreempt CPU. Output /data/user_data/aydanh/rubric_gen/runs/cue-pair-attribution-20260909/calls-10376113; no revisions/outcomeaudits.

- 15:58 EDT: Provider-free analysis10376132 depends afterok10376113; requires36unique completedcells and compares ID-mapped A/B-orderpreferences, ties, retries, and all9selectedpair rationales. Sharedoutput cue-pair-attribution-20260909/analysis-v1; orderagreement is notfactualaccuracy.

- 16:16 EDT: Single-pair diagnostic10376267submitted afteracceptance10376248; frozen957fc67,20callsLuna4workers/shared60,no revisedprompts/revisions/outcomeaudits. Shared single-calls-10376267; dependentanalysis10376273compares originalfull-contextcontrols10376113 without regeneration, outputsingle-analysis-v1.

- 16:23 EDT: Provider-free ordered-table acceptance10376304prepares20samepair/ordercells withonlyartifacttableentryorderchanged; shared ordered-pair-inputs-v1. Prior single controls10376267reused; alignedfreshrepeatsmeasurevariability. No providerorrevisionlaunchyet.

- 16:27 EDT: Orderingdiagnostic10376310submitted after10376304verified20cells; frozen144b343,4workers/share60,Lunaunchanged. Sharedordered-calls-10376310; analysisafterok queued via analyze_ordered.sbatch. Both preidentifiedwrong-lettercases had table/A-B conflict; causalityawaitsnewresults.

- 16:34 EDT: Provider-free consensuscoverage10376361checks all51context-pairs againstoriginalsavedinduction/validationcomparisons andexistingtwoordercontroljudgments. Reports retainednon-tieagreement andhistoricalgap corroboration; no nativeadmissionreplay or scientificchange implied.

- 16:40 EDT: Provider-free survivingsupport10376387reads originalproposals/validations/admissionsfor5corroboratedgap-bearingpairs; outputsharedsurviving-support-v1 andsmallhomereceipt. Eightlostcomparisons split4orderdisagreements/4consistentreversals; no treatmentlaunch.

- 16:47 EDT: Atomiccriterionscope preparation10376426recovers3savedinductioncontexts(0,3,4) andnativeoriginaladmissionreplay. Newscopepromptonly, freshmatchedcontrol, no pair-assessment intervention or solver changes; providerlaunch gatedonacceptance.

- 16:55 EDT: Atomiccriterion10376454pending/runningowner, frozenbc8af8c,6matchedcellswithnativeapplications, shared /data/user_data/aydanh/rubric_gen/runs/cue-atomic-criterion-10376454. Report10376457afterok requires6uniquecompletecells/sourceunchanged; no newscientificresultyet.

- 17:20 EDT: AuthorizedSolpairassessment10376798,frozen091ae37;18originalfullcontext/ordercells,model-onlychange,Lunacontrols10376113reused. Inputsvalidatedinjobbeforecalls; sharedcue-pair-attribution-20260909/sol-calls-10376798. No revisions/outcomeauditorschanged.

- 16:50 EDT: Provider-freeSolgapimpact10376905outputs sharedcue-pair-attribution-20260909/sol-gap-impact-v1;9nativehistory/controlreplays, onlyqualityjudgmentsfromauthorizedSolchanged. Recentmanuallyestimatednarrativetimeprefixes mayrunaheadofclusterclock; Slurmjob timestamps andruntimeJSONareauthoritative.

- 16:56 EDT: Sol-supervision native preparation10376939 running; bundle investigation/cue-sol-supervision-20260909,9contexts×2arms. Provider job not submitted pending acceptance-v2.json; planned output /data/user_data/aydanh/rubric_gen/runs/cue-sol-supervision-JOB and report.sbatch JOB.

- 17:00 EDT: Preparation10376939failed beforeproviderwork; nine-context inputs.json preserved. Validation10377026 uses native payload reconstruction without repeating input discovery; acceptance-v2.json still gates18-cell providerlaunch.

- 17:01 EDT: Nativevalidation10377026 passed9contexts in2s; context7historicallyproposednocriterion and hadnovalidationcache, now native historypayload verified. Frozen46af22f providerdiagnostic10377039 submitted18cells,4workers/shared60,1CPU4G45min; output /data/user_data/aydanh/rubric_gen/runs/cue-sol-supervision-10377039.

- 17:06 EDT: Diagnostic10377039/report10377042complete;18unique matchedcells andsourcechecks pass, report-v1/analysis.json and home cue-sol-supervision-result.json. No ownedjobs remain fromthisbatch; no expensive revision launched.

- 17:08 EDT: Provider-free supportjoin10377119completed19candidate rows; shared cue-sol-supervision-10377039/support-analysis-v1 and home cue-sol-supervision-support.json. No provider work pending; next verify fixed application evidence before any application-model diagnostic.

- 17:14 EDT: Hashartifact verification10377170completed; mean/median and code-to-universe contradictions confirmed withoutproviders. Frozen-candidate application nativevalidation10377249pending; exact9proposalsets from10377039, freshLuna/Solapplicationsonly, providerlaunch gatedonacceptance.

- 17:16 EDT: Application replay10377249 failed on diagnostic tuple/list equality; provider-free correction10377294 resubmitted. Historical candidate/application bytes remain frozen; no provider owner launched yet.

- 17:17 EDT: Native replay10377294 passed all9contexts and114exact planned payloads; frozen abcb8c1 application-only job10377313 submitted. Shared output /data/user_data/aydanh/rubric_gen/runs/cue-sol-application-10377313,18cells,4cell×4native workers under shared60,1CPU4GiB45min; no proposals/revisions/outcome audits.

- 17:22 EDT: Application comparison10377313/report10377314 complete; shared /data/user_data/aydanh/rubric_gen/runs/cue-sol-application-10377313/report-v1/analysis.json, home cue-sol-application-result.json/md. All18unique cells and114request keys verified; no remaining owned job from this batch.

- 17:26 EDT: Instruction-only application job10377405 submitted after native reuse validation10377384 (9contexts/57calls), frozen39c4e7b. Shared output /data/user_data/aydanh/rubric_gen/runs/cue-application-check-10377405; reuse freshLuna controls10377313, no other stages rerun.

- 17:35 EDT: Application-check10377405/report10377408 complete; shared cue-application-check-10377405/report-v1/analysis.json and home cue-application-check-result.json/md. Nineunique cells and57calls verified; no remaining job fromthisbatch.

- 17:54 EDT: Provider-free census10377581 andsupport decomposition10377626 complete; /data/user_data/aydanh/rubric_gen/runs/cue-admission-census-10377581 contains full provenance/results. No provider or revision work launched; small receipts/report cue-admission-census.json/md andcue-support-decomposition.json.

- 18:00 EDT: Training-only refinement10377742 submitted after native control/leak-boundary validation10377720; frozen de58877,3eligible canonical saved contexts and reused10370826controls. Shared /data/user_data/aydanh/rubric_gen/runs/cue-support-refinement-10377742; only refinement/independent application calls, no revisions or outcome audits.

- 18:08 EDT: Refinement10377742/report10377749 complete; shared cue-support-refinement-10377742/report-v1/analysis.json and home cue-support-refinement-result.json/md. Threeunique cases and13calls verified; no active owner remains from this batch.

- 18:14 EDT: Sol-induction10377844 submitted after native validation10377836; frozen65912e9,4saved canonical contexts, reused10370826controls, only induction model changed. Shared /data/user_data/aydanh/rubric_gen/runs/cue-sol-induction-10377844; unchanged Luna applications and all gates,1CPU4GiB45min under shared60.

- 18:20 EDT: Sol-induction10377844/report10377853 complete; output cue-sol-induction-10377844/report-v1/analysis.json and home cue-sol-induction-result.json/md. No running owner from this batch.

- 18:26 EDT: Native replay10377943 passed4contexts/44payloads; conditional application job10377953 submitted at frozen1e788aa. Output /data/user_data/aydanh/rubric_gen/runs/cue-sol-conditional-10377953; oneCPU4GiB45min, fourcellworkers under shared60; unchanged saved Sol criteria/Luna controls10377844, no revisions.

- 18:29 EDT: Conditional application report10377954 validates all4cells and44calls; shared cue-sol-conditional-10377953/report-v1/analysis.json, home cue-sol-conditional-result.json/md. Reasoning-only native reuse validation10377995 submitted; provider launch remains gated.

- 18:30 EDT: Reasoning-only application job10378006 submitted after native validation10377995 passed9contexts/57payloads and exact low-control reuse. Frozen26e464d; shared /data/user_data/aydanh/rubric_gen/runs/cue-application-reasoning-10378006,1CPU4GiB45min, shared60. No other pipeline stages rerun.

- 18:35 EDT: Reasoning report10378007 verifies all9cells; shared cue-application-reasoning-10378006/report-v1/analysis.json and home cue-application-reasoning-result.json/md. Read-only10378035 owns filtering-inspection-v1; no provider jobs remain from this batch.

- 18:39 EDT: Read-only inspections10378035/10378062 complete; shared cue-application-reasoning-10378006/filtering-inspection-v1 and cue-filter-data-10378062/result.json. All current batch jobs terminal; no provider/revision/confirmation owner remains.

- 18:43 EDT: Schema-order application10378203 submitted after native validation10378196 (9contexts/57payloads). Frozenb2163de; /data/user_data/aydanh/rubric_gen/runs/cue-application-order-10378203;1CPU4GiB45min under shared60, report runs in same allocation. No revisions/outcome audits.

- 18:46 EDT: Integrated report10378203 complete; shared cue-application-order-10378203/report-v1/analysis.json, home cue-application-order-result.json/md. Full canonical semantic-flag census10378225 is the sole next owner; no provider calls.

- 18:49 EDT: Semantic census10378257 completed10s after read-only parser failure10378225; shared cue-semantic-census-10378257/analysis.json, SHA69690c2464a77b7ec42f9729e24b373e96dc34409b41dec19aed062a6c1e9a54. Bound-only10378281 submitted; no provider jobs.

- 18:51 EDT: Bound10378281 complete1s; shared cue-semantic-bound-10378281/analysis.json and home cue-semantic-bound.json. All current jobs terminal; no provider/revision/confirmation owner.

- 18:56 EDT: Single-gap provider/report job10378400 submitted at9adb276 after validation10378342. Shared /data/user_data/aydanh/rubric_gen/runs/cue-single-gap-10378400;4induction plus at most44validation calls,1CPU4GiB45min under shared60. Reports run in same allocation; no revisions/outcome audits.

## 2026-09-09 — Missing cue full-feedback counterpart

- 20:16 EDT: Owner10379267, frozen314ea3d, config investigation/cue-full-compatibility-20260909/trace-results20.yaml; output /data/user_data/aydanh/rubric_gen/runs/result20-cue-full-trace-20260909/trace/{study,audit}/{experiment_id}, owners/trace-results20. Input gate10379252; provenance10379227; reuse earlier full-static and both cue user arms unchanged. Resume command: sbatch investigation/cue-full-compatibility-20260909/condition.sbatch trace results20 --workers 60 --audit-workers 60 (only after current owner terminates).

- 20:16 EDT: Provider-free report10379269 depends afterok:10379267; script investigation/cue-full-compatibility-20260909/report.py, writes shared matched-report-v1 and docs/reports/2026-09-09/result20-cue-four-condition.md. It uses original full-static and cue user-arm records directly; prior full-trace is excluded from the matched cue policy table.

## 2026-09-09 — Provisional59 case decision

- 21:29 EDT: Current owneraudit10380169; report10380215dependsafterok. Output /data/user_data/aydanh/rubric_gen/runs/result20-cue-full-trace-20260909/provisional59-report-v1 and docs/reports/2026-09-09/cue-full-provisional59.md. Recovery10380168cancelled atuserrequest; obsolete report10379269cancelled. No scientific revisionowner remains.

- 21:42 EDT: Audit10380169completed16m05s;report10380215completed~1m04s, native59×2auditor tracecoverage and59matchedstatic cases validated. Final report docs/reports/2026-09-09/cue-full-provisional59.md; shared provisional59-report-v1/analysis.json under result20-cue-full-trace-20260909. Missing da16-1rep1 explicitly omitted frombotharms; cancelled replacementexcluded; all59originalmanifest/state/source seals preserved.

## 2026-09-10 — attack_defense_v1

- 10:29 EDT: attack_defense_v1 development checkout: runs/babel-code/attack-defense-v1; config experiments/trace-attack-defense-v1/result20.yaml; new run root /data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v1-20260910/. Provider-free input jobs10387137 and10387146; no behavioral calls yet.

- 11:10 EDT: Production job10387275 runs snapshot106863b2ca1bfb543be3d6660aaeca56baec15af, experimentbiomnibench-da-factorial-r10-3e186b5fe98c, at the documented NFS root with32CPUs/32workers/shared60; counted smoke precedes the remaining118 and Sol+Opus audits.

- 11:58 EDT — Queued provider-free report job `10387731` with `afterok:10387275` (replaces pending report-only job `10387689`, which never executed); it reads the completed sealed cohort and native judgments, writes compact tables to `docs/reports/2026-09-10/trace-attack-defense-v1/`, and leaves raw inspection packets under the existing NFS run root. No new behavioral or audit calls are in this reporting job.

- 14:00 EDT: The complete120 trace cohort is sealed under the same study root; job10387275 has transitioned to authoritative audits, with report10387731 still dependent on full success. No static or preparation stage was regenerated.

- 14:08 EDT: Read-only coordinator records identify PaperBench audit-recovery10388169 as the current one-audit-slot holder (lease7174ca0a39f44524b17933ae52ac0f6a); trace job10387275 waits before audit dispatch, with120/120 revisions complete. Preserve the shared one-study cap and the concurrent project; this is capacity waiting, not a trace revision failure.

- 15:49 EDT: Production10387275 acquired the global audit slot at19:44:00UTC after6307.066seconds (105.12minutes) waiting behind the separate PaperBench recovery; the complete120-assignment Sol+Opus panel is now executing.

- 16:32 EDT: Production 10387275 completed at 20:13:46 UTC (snapshot 106863b2ca1bfb543be3d6660aaeca56baec15af); native completion and all raw evidence remain under /data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v1-20260910/. Read-only reporting 10389933 completed the paired tables/case review after report-only 10387731 stopped on the declared reminder-history hash difference; the published report is docs/reports/2026-09-10/trace-attack-defense-v1/README.md.

## 2026-09-10 — attack_defense_v2 development

- 21:05 EDT: Isolated checkout `runs/babel-code/attack-defense-v2` starts at report commit `10efb8886d19163975c137f2f058eb4c415657d5`; the shared dirty checkout and historical v1 worktree remain intact. New compute root `/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910/`; Phase A uses `phase-a/dev1-001/`, physically separate from future dev3/Result20 outputs and caches.
- 21:05 EDT: Provider-free input jobs 10392208/10392306; compact cohort receipt `experiments/trace-attack-defense-v2/phase-a-cohort.json`. Model work will use 32 allocated CPUs, at most 32 workers, intra-assignment fan-out four, shared aggregate limit 60 and audit-study limit one; no outcome auditor is invoked during development.

- 21:26 EDT: Phase-A dev1 source8124dd8 pushed; job10392341 completed the fixed48-request microbench, with reports under trace-attack-defense-v2/phase-a/dev1-001. Dev2 preparation10392474 preserves its separate cohort/config receipts; no full dev3 iteration has launched yet.

- 21:48 EDT: Dev3 iteration1 job10392635 uses 32CPU/18 assignment workers/fan-out4/shared60 at `/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v2-20260910/dev3/dev2/`; native task-study configs are `experiments/trace-attack-defense-v2/dev2/*.yaml`. Phase-A dev2 receipts are under `phase-a/dev2-001/`; no production cohort has launched.
