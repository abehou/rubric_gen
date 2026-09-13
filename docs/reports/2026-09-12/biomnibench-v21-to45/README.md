# BioMNIBench v2.1 to 45: development and expansion

**Expectations are partially met.** Full v2.1 supports further characterization; User calibration remains unresolved. All18 R1/R2 development trajectories have completed, and the corrected queue2 audit now has complete R0/R1/R2 outcomes; the queue3 policy audit is still running. No new User winner, confirmation block, or User Result20 is claimed. Results30/45 remain input preparation, not completed expanded outcomes.

Mission start: **2026-09-12 09:27:31 EDT**. This is an interim checkpoint, not the requested9–10-hour morning checkpoint (18:27–19:27 EDT). Healthy Slurm jobs retain their owners. The [shared status](../../../../../experiments/biomnibench-v21-to45/status.json) and [observed jobs/commands](queue8/observed-status.json) provide continuation state.

## 2026-09-13 resumed scale checkpoint

The resumed owners preserve all completed records and are dispatching only missing work. Results30 `da-1-3` has an inspection/archive/recovery chain (`10421606` → `10421689` → `10421690`) for the four manifestless assignments; its two completed static assignments remain untouched. Results45 `da-17-1/rep-003` has a guarded archive/cleanup/seed/validator chain; the first archive/cleanup attempts (`10421649`, `10421655`) failed after preserving evidence, so exact finalizers (`10422141`, `10422142`) wait behind read-only inspectors (`10422063`, `10422088`) before dispatching the same native recovery. The first four previously unlaunched Results45 revision tasks are queued behind that validator (`10421737`–`10421740`). The one incomplete Queue3 cell, `score_only-trace-no-appendix`, is queued for native missing-only recovery as `10422080` after the first audit owner retained its three provider-exit failures.

At this checkpoint the two healthy PaperBench jobs `10421608` and `10421810` occupy the shared 64-CPU per-user quota, so the BioMNIBench jobs remain scheduler-held; no healthy PaperBench job was changed. The exact recovery-path patch is `b5cbe7e` (q7 archive path correction plus allowlisted permission repair) and the status/log milestone is `4ff1d67`. The q7 seed retry is using the compact solution-only snapshot patch (`c2bceb2`) after the prior NFS quota failure; earlier failed attempts and q7 evidence archives remain preserved.

## Scientific findings

The [canonical nine-case diagnosis](queue2/README.md) explains a real part of weak/strong disagreement: among126 matched criterion/auditor observations,20 favor the weak judge,106 tie, and none favor the strong judge. Missing requested outputs and code-versus-captured-result distinctions dominate da-11-1, which contributes5.17 of the7.50 mean W−S gap. An earlier numeric answer is not proof of correct work. The key withdrawal followed ordinary User feedback without an appended reminder; a universal “fourth reminder causes the regression” explanation is unsupported. Per-turn strong scores were not measured, so no precise time of S decline is inferred.

The smallest current tests are **R1: append only a legacy-selected corrective reminder** and **R2: append no separate reminder**. Both retain all learned scoring, ordinary simulator feedback, the exact legacy selector/history, and Full behavior. Selection and actual delivery are recorded separately. These are ablations, not approved improvements; no further recipe is launched before their complete evidence. [Implementation, scope and tests](queue2/README.md).

Historical unsuccessful variants remain visible. v3 raised H with nearly unchanged A; v3.2 lost A and raised S−H. Those are different failure patterns. D×G completed36 feedback checks and launched0/27 challengers after repeated leaks/false assertions; P1/P2 completed24 checks and both failed. These closed diagnostics do not justify another simulator architecture or hidden-answer-guided treatment. [Historical comparison](queue4/README.md) · [D×G](../trace-user-parallel-diagnostics/README.md) · [P1/P2](../trace-user-public-evidence-firewall/README.md).

## Completed outcomes and uncertainty

The [complete-cell table](queue8/README.md) contains **every completed scope**, reuse/new counts, W/W_train/S/H/A, W−S/S−H/H−A/W−A and all four RH windows. [CSV](queue8/complete-cells.csv) · [both auditors](queue8/complete-cells-by-auditor.csv) · [native panel detail and paired intervals](queue8/synthesis.json). Incomplete cells are listed without surviving-task/provider means.

| Result20 condition | W | W_train | S | H | A | W−S | S−H | H−A | W−A | RH full / post / artifact / revision (%) |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|
| Full fixed |96.72|96.72|89.02|87.54|67.46|7.70|1.47|20.09|29.26|20.83 /1.67 /3.33 /0.83|
| Full v2.1 |95.83|95.83|89.72|88.97|71.15|6.12|0.74|17.82|24.68|14.17 /6.67 /4.17 /4.17|
| User fixed |89.58|89.58|82.24|80.88|70.47|7.34|1.36|10.40|19.11|20.00 /11.67 /0 /5.00|
| User v2.1 |90.82|90.73|81.62|80.34|72.48|9.19|1.28|7.86|18.33|10.00 /5.83 /0 /5.00|

This historical core has240 assignment records (120trace/120fixed); all are reused in this mission. The repaired trace panel completed3668/3668 required judgments. RH above is the equal-weight confirmed-positive auditor rate, distinct from the native panel union. All abstentions and denominator bounds remain in the linked data.

Full’s paired full-trajectory change is−6.67pp (95% task-cluster interval−15.00 to+2.50), W−S−1.58(−3.80,+0.53), W−A−4.58(−9.05,−0.28); S+0.70 and A+3.69. Its later RH windows are worse. User’s RH change is−10.00pp(−18.33,−2.50), W−S+1.85(−0.91,+4.95), W−A−0.78(−5.13,+3.45); S−0.62 and A+2.01. Full passed the historical practical joint thresholds; User did not. Full’s inconclusive primary intervals prevent a blanket statistical-superiority claim.

The current collaborator interpretation is prospective and separate: a modest W−S reduction of0.1–0.5 can suffice; do not maximize it. Keep S−H low while preserving S/H; interpret heldout-to-holistic H−A using both H and A. Signed overshooting or quality loss is not success. Bootstrap uncertainty resamples task clusters, keeping replicates and auditors together (10000 draws,seed20260910); auditors are not independent tasks.

![Full/User RH, all windows](queue8/result20-rh.png)
![Weak-to-strong, selected-to-heldout, heldout-to-holistic gaps](queue8/result20-gaps.png)

## Feedback-policy comparison and delivery

The canonical matrix is72 records: nine reused User trace controls plus63 new Full/Semi/Score-only/User fixed/trace records. The nine-case Score-only appendix-off supplement is separate. Each comparison is trace minus fixed **within feedback policy**; historical stress starts are not substituted as matched controls. Current incomplete audits prevent a complete policy-effect table. [Scope and owners](queue3/README.md) · [coverage figure](queue8/feedback-policy.png).

Native Score-only trace means numerical ordinary feedback **plus a qualitative trace appendix when delivered**. R2’s Score-only supplement removes only that appendix. Original instructions are not treatment feedback, and appendix-off does not remove learned penalties. Actual delivered-message accounting is retained with the cell reports; no numerical-feedback-only causal claim is made from the native trace arm.

## Gap rank and RH rank

[Artifact data, methods, component associations and plots](queue8/README.md#gap-rank-versus-rh-rank) use saved measurements only. Signed component ranks use average ties, convert to high=severe percentiles, then average equally. The raw gap sum is W−A, not a new metric. Continuous final-artifact RH is primary; trajectory RH is separately labeled. Constant scores give undefined correlation; abstentions/unknowns remain unresolved. Worst10/20/25% overlaps share boundary ties fractionally.

Within-condition associations vary: Result20 Full trace final-artifact Spearman≈0.42, User trace≈0.12; their trajectory associations are≈0.22 and−0.12. These are descriptive, not evidence that gaps substitute for RH or mediate treatment effects. No weighting search or pooled-condition inference is used.

## Expansion and operations

The official nested task membership is fixed before new outcomes: [T20/T30/T45](../../../../../experiments/biomnibench-v21-to45/queue6/membership.json). Protected canonical dev3 tasks remain excluded; stress tasks in the original twenty are development-exposed. Full-only scope is180 records at30tasks and270 at45:120 reused original records,60 additional-ten records,90 final-fifteen records. User scale-up is not nominated.

**Heldout decision resolved:** at12:39 EDT the user authorized committed rigorous-V2 prompt **47463ca** for new tasks. Original twenty-task heldouts remain unchanged. Their recorded generation instructions differ from the new prompt; the historical exact text was not recoverable. Added-ten/final-fifteen H and cumulative H will explicitly retain that generation difference, with block-specific results. No historical prompt identity is rewritten. [Results30 plan](queue6/README.md) · [Results45 plan](queue7/README.md).

[Runtime recovery](queue8/runtime-recovery.md) reuses reviewed c451942 in isolated audit consumers0b58da6/9233e64. It fixes provider schema complexity through a different output representation with unchanged grading semantics;514 focused tests and native saved-record replay passed. Completed responses remain intact. Preemptions, invalid/missing solver output, and provider/schema errors remain separate failure classes.

[CPU audit](queue6/resource-profile.md) retains4CPUs for producers (sampled≈3-core peaks), reduces only future audit requests8→4CPUs with unchanged32 request workers, and keeps serial reporting/ranking at1CPU. Provider cap60 and audit lease1 remain shared with other jobs. No healthy active job is resized. Measured calls/tokens and cost are reported only where saved accounting exists; estimated cost is not labeled billed cost.

## Current decision and continuation

- **Complete:** v2.1 Result20, canonical User control9/336, closed historical diagnostics, R1/R2 trajectories18/18, queue2 R0/R1/R2 audited outcomes (provider-free reuse), task-membership plan, stage-specific CPU audit, rigorous-V2 heldouts for the added-ten and final-fifteen blocks.
- **Running/incomplete:** queue3 corrected all-cell audit (job10415408, after queue2 R2), Results30 missing-only seed recovery (jobs10415501/10415502 with lane-0 retry10415538), and Results45 missing-only seed recovery (jobs10415531/10415532). No Results30/45 revision or outcome-audit stage has been dispatched.
- **Scientifically unresolved:** a better User treatment, broad anti-RH claims across later windows, causal attribution to appendix delivery, generalization to new tasks.
- **Deferred pending evidence:** independent User confirmation and new User Result20; Semi/Score-only scale extensions; dropout. No new speculative variant is dispatched.

Expectations are **partially met**, supported by Full v2.1 rather than an overall successful bundle. Queue2 is complete; queue3 and the Results30/45 input/revision/audit stages are **incomplete**. The heldout authority blocker is resolved, and all missing work is being resumed through the native owners without resubmitting completed cells. This checkpoint does not end the30/45 mission.

Collaborator update draft:「目前Full v2.1在20题上的主要方向成立，但后期RH窗口和统计不确定性仍需保留；User校准问题尚未解决。R1/R2共18条轨迹已完成，Queue2评审已补齐，Queue3正在按原计划恢复。30/45题按已固定任务集推进，旧20题heldout不变，新题使用已批准的rigorous-V2提示并明确记录生成差异。现在是部分达标，不是全部预期已实现。」


## 2026-09-13 08:10 EDT — persisted scale state after recovery attempts

This section supersedes the earlier “running” wording where the current receipts below are more specific. It is a provider-free checkpoint; it does not claim a completed Results30 or Results45 outcome. The original twenty-task records and all successful judgments remain unchanged.

### Results30

The ten-task extension has 60 intended new Full records. The ten native task seed manifests were valid in inventory job `10416169`. The `da-1-3` shard is still incomplete: the four exact failed targets (`rep-001/full-static`, `rep-001/full-red-team-trace`, `rep-002/full-red-team-trace`, and `rep-003/full-red-team-trace`) each contain a valid manifest and one `s000` submission but remain `judge_in_progress` with no completed score (`10423138`, [receipt](queue8/q6-da1-3-revision-target-inspection.json)). The provider-free archive pass `10423093` therefore removed nothing. Its native resume remains held; no Results30 revision or audit judgment has been started for these missing records. Results30 audit `10422299` and report `10422300` remain held.

### Results45

The final-fifteen extension has 90 intended new Full records. Native inventory `10416170` verified 44/45 seed blocks; only `da-17-1/rep-003` was incomplete. Its preserved archive was verified by `10422953`, which then failed only while removing a nested directory with `PermissionError`. The exact directory-mode repair `10423118` changed four directory modes inside that target and removed only the failed target ([receipt](queue8/q7-seed-target-permission-repair.json)); the archive was not promoted to a seed, so native seed regeneration and validation are still required. Repaired revision waves `10422174`–`10422196`, Results45 audit `10422302`, and report `10422304` remain held.

### Queue3 missing cell and provider boundary

The only incomplete Queue3 cell is `score_only-trace-no-appendix` for `da-11-1`. Native resume `10422809` reached all three saved failed-turn checkpoints without buying another provider call. Replicates 1 and 3 stop at turn 3 and replicate 2 at turn 4; the sealed submissions and scores are retained. The failed-turn records report the Codex account usage-limit response, with access reported to reset at `2026-09-19 04:09`. Audit `10422818` is consequently `DependencyNeverSatisfied`; its downstream reports remain held. This is an external provider-capacity blocker, separate from scientific nulls, audit disagreements, the earlier NFS failure, and the controller memory-allocation incident. No model substitution, task replacement, or repeated unfavorable draw was used.

### Storage and CPU accounting

The q6 read-only cache census `10422942` found the active `trace-repair-10381602` environment intact, one allowlisted obsolete cache already absent, and the second allowlisted cache at 1,017,505,307 bytes. Direct cleanup `10423023` removed only that second obsolete cache ([receipt](queue8/q6-exact-cache-cleanup-receipt-v2.json)); it did not chmod or rewrite metadata. The one-CPU q7/q6 storage operations used narrow paths and preserved failed evidence. The q6 archive job `10423093` used one CPU and made no scientific change. The established profile remains four CPUs for four-worker producers/revisions, four for future audit request workers, and one for serial reports/finalizers; no healthy scientific job was resized.

### Current job ownership and resumption

The BioMNIBench jobs currently held are q3 audit `10422818`, q6 local recovery `10422169` and Results30 audit `10422299`, q7 seed/validator `10422170`→`10422171`, q7 repaired revision waves `10422174`–`10422196`, and Results45 audit/report `10422302`→`10422304`. The q7 seed dependency was retargeted to the completed exact repair `10423118`; q6’s old archive dependency remains held because Slurm rejected a replacement dependency after the completed one-shot archive `10423093`, so it must be resubmitted or manually repaired by the native owner after provider access returns. No held job was released into the provider queue.

After the provider limit resets, resume only the native missing work in this order: q3 `--resume` for the three failed `da-11-1` assignments and its held audit; q6 `da-1-3` native resume after validating the four saved targets; q7 native seed regeneration/validator for `da-17-1/rep-003`; then release the already prepared revision waves and scale audits through their native dependencies. The existing report jobs and `10422359` synthesis should run only after their inputs are complete. The exact output roots are `/data/user_data/aydanh/rubric_gen/runs/biomnibench-v21-to45-20260912/results30` and `/data/user_data/aydanh/rubric_gen/runs/biomnibench-v21-to45-20260912/results45-added15`; access them through Slurm, not login-node existence checks.

The historical Result20 table above remains the last complete scientific scale result. No expanded W/W_train/S/H/A, gap, RH, interval, or final joint-decision values are reported for Results30/45 because their new-task revisions and audits are not complete. The appropriate status is **partially met; Results30/45 incomplete and externally provider-blocked**, with all valid prior work and failure evidence retained.
