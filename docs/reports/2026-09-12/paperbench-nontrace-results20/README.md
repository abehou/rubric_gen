# PaperBench non-trace Results20 — Queue 6 handoff

As of **2026-09-12 12:29 EDT**. **Static audit closure succeeded: Sol 900/900 and Opus 900/900, with all 120 revisions and all detector/holistic work valid.** The final three complete saved responses were published with zero provider calls.

The [final corrected static report](../paperbench-static/selected-neutral-heldout-rigorous-results20-final.md) and [JSON](../paperbench-static/selected-neutral-heldout-rigorous-results20-final.json) are complete.

| Final static condition | W | S | H | A | Mean S−H | 95% task-cluster CI for S−H |
|---|---|---|---|---|---|---|
| full-static | 97.8003 | 63.2648 | 62.3260 | 33.9417 | 0.9389 | [-1.5423, 3.5317] |
| user-simulator-static | 87.1752 | 63.4416 | 62.9950 | 39.2583 | 0.4466 | [-0.7481, 1.6489] |

These are complete equal-weight Sol+Opus results. Both S−H intervals include zero. Full-trajectory RH identification bounds are Full50–58.33%, User10–15%; final-artifact RH is Full0–1.67%, User0%. No abstention is imputed. Prior uniform-rigorous-v2 S−H was Full−0.859/User−0.512; the separate corrected fixed-artifact screen was Full+1.108/User+1.101 observed/incomplete.

No new scientific condition was started by Queue6. Full/User static revisions remain120/120; the existing Semi/Score fixed producer10414738 has **65 new completed assignments, 32 running**, with terminal native scope validation still pending. The remaining scientific waves retain their original owners/dependencies. No other completed Results20 revision cohort was found in the current bounded study census, so no additional audit executor was created.

## Current condition matrix

| Condition | Corrected dev3 revision | Dev3 audit | Results20 revisions | Results20 audit | Revision owner |
|---|---|---|---|---|---|
| full-static | 9/9 valid | complete | 60/60 valid | Complete Sol + Opus | preserved |
| full-offline-rubric | 0/9 valid | queued | 0/60; queued | Queued 10414875 | 10414874 |
| full-online-rubric | 0/9 valid | queued | 0/60; queued | Queued 10414875 | 10414874 |
| full-red-team-artifact | 0/9 valid | queued | 0/60; queued | Queued 10414875 | 10414874 |
| semi-static | 9/9 valid | queued | 35/60 completed; 16 running | Queued 10414746 | 10414738 |
| semi-offline-rubric | 9/9 valid | queued | 0/60; queued | Queued 10414748 | 10414740 |
| semi-online-rubric | 9/9 valid | queued | 0/60; queued | Queued 10414748 | 10414740 |
| semi-red-team-artifact | 9/9 valid | queued | 0/60; queued | Queued 10414748 | 10414740 |
| score-only-static | 9/9 valid | queued | 30/60 completed; 16 running | Queued 10414746 | 10414738 |
| score-only-offline-rubric | 9/9 valid | queued | 0/60; queued | Queued 10414747 | 10414739 |
| score-only-online-rubric | 9/9 valid | queued | 0/60; queued | Queued 10414748 | 10414740 |
| score-only-red-team-artifact | 9/9 valid | queued | 0/60; queued | Queued 10414748 | 10414740 |
| user-simulator-static | 9/9 valid | complete | 60/60 valid | Complete Sol + Opus | preserved |
| user-simulator-offline-rubric | 0/9 valid | queued | 0/60; queued | Queued 10414875 | 10414874 |
| user-simulator-online-rubric | 0/9 valid | queued | 0/60; queued | Queued 10414875 | 10414874 |
| user-simulator-red-team-artifact | 0/9 valid | queued | 0/60; queued | Queued 10414875 | 10414874 |

Each Results20 condition requires20 tasks×3replicates. Telemetry completions for an active scope are distinguished from native terminal validation. Historical scientifically incompatible uniform-rigorous runs do not count. Exact source pins, roles, output paths and original job dependencies remain in the preceding inventories and [Queue6 machine receipt](queue6-status.json).

## Static repair, reuse and ownership

Pinned repair **8226495fe88937cc613c02dd70b5253e58873e7f** is durable on the existing temporary cardinality branch. Its minimal implementation/tests were selectively ported to current core at **f6f02128c3fcfb23488b38c8a59fd8afe13157b2**, preserving unrelated history. **686 provider-free tests passed on the pin and686 after integration**, including all9 real failed responses. Five complete saved responses passed strict lossless replay; four incomplete responses still fail. The native dry path validated120 revisions, reused900 Sol/897 Opus, and scheduled exactly3 local publications with **Sol0, Opus0, all detector0, absolute0 and pairwise0 provider work**. All897 valid Opus judgments and their5,382 persisted files were byte-identical.

The final three keys select the earliest complete saved attempts2/2/1; no criterion/index is inferred. Normal native `detect --resume` owns publication and retains exact saved-response/producer provenance. This repair changes saved-response parsing/discovery only: the live v8 schema, prompt, models, budgets, effort, scoring and streaming remain unchanged. Full details: [saved response repair](../paperbench-static/opus-saved-response-replay.md).

Native owner **10415061** uses the reviewed existing `inspection` profile:1CPU,4request workers, zero provider calls. This is local replay/validation work; no CPU-profile code was changed. Scientific producer/audit jobs retain32CPUs/32workers and the aggregate provider cap60. The global audit lease is respected, including healthy other-session owners. Dependent finalization uses1CPU and no providers. No valid judgment or revision is rerun; no imputation; bounded attempts unchanged.

## Queue7 priorities

1. Inspect static native replay10415061 and dependent report job10415098 before action. If healthy, retain both. If completed, collect the final report/coverage; if failed, classify the exact failure before native missing-only recovery.
2. Continue existing revision owners10414738,10414739,10414740 and10414874 plus Full/User dev3 owner10414499 and validator10414506. Do not create another dispatcher. New dev3 auditors10414751/52/10414876 retain their original scopes.
3. Close existing Results20 audit owners10414746 (Semi/Score static),10414747 (Score offline),10414748 (remaining Semi/Score learned),10414875 (Full/User learned) as their revision dependencies succeed. All use validated v8 and the single global audit-study lease. Handle any residual saved-response formatting via the tested repair, preserving the pinned producer identity.
4. Report complete two-auditor means only after required coverage; retain missingness and abstention bounds. Prioritize existing Full/User static, Semi/Score static, remaining Semi/Score, then Full/User learned. No red_team_trace or Gemini work belongs to this mission.
5. Preserve pinned recovery source while replay/report dependencies live. After all dependencies end and useful changes/reports are integrated, clean up the temporary branch without merging stale history. The separate CPU-profile patch remains outside this work.

Private operational receipts/scripts: `/home/aydanh/repos/rubric_gen/runs/paperbench-nontrace-audit-closure-20260912`. Earlier incomplete evidence follows as historical handoff snapshots.

---

# PaperBench non-trace Results20 — Queue 5 handoff

**All360 missing Full/User non-static Results20 assignments have a queued native owner, conditional on corrected dev3 validation.** At **2026-09-12 11:45 EDT**, these six conditions still have **0 reusable,0 running and360 missing** assignments. The existing Full/User static120 revisions remain valid and untouched. Across the16-condition mission,120 revisions are native-valid; the active Semi/Score fixed Results20 wave now reports **1 newly completed,32 running and87 pending**, with the other720 new assignments queued. The new completion awaits terminal scope validation.

**Static audit recovery10414690 finished incomplete: Sol900/900, Opus897/900.** It added133 valid Opus judgments and left3 exhausted line-count failures; all3 have complete saved-response delimiter candidates that pass read-only canonical validation, but they remain unpublished. No final static metrics are reported.

Full/User dev3 producer **10414499** is pending CPU quota, with **0/54 assignments started**. Its shared dev3 producer **10414497** completed successfully in **1h16m14s**. Semi/Score dev3 now has **72/72 native-valid across all eight Semi/Score-only conditions**. The completed54-assignment learned scope passed the existing native collector in step10414690.1 in315.805s, with zero failures or provider calls. Full/User Results20 job **10414874** cannot execute until **10414506**, the existing provider-free native Full/User dev3 validator, succeeds and Results20 starting-rubric producer **10414739** completes. These dependencies were verified in Slurm; no completed condition or healthy owner was restarted.

## Current 16-condition matrix

Every Results20 row requires 20 canonical tasks × 3 replicates. All non-static Full/User rows currently share queued dev3 revision owner 10414499 and dev3 audit owner 10414876. Their dev3 success remains a prerequisite; no promotion-readiness claim is made yet. Other audit owners are retained from Queue 4. All Results20 revision/audit owners below are queued except static recovery 10414690, which has acquired the global audit lease and is executing missing-only Opus recovery.

| Condition | Corrected dev3 revisions | Results20 valid revisions | Results20 revision owner | Results20 audit owner |
|---|---|---|---|---|
| full-static | 9/9 valid | 60/60 | Preserved static | 10414690 |
| full-offline-rubric | 0/9; queued 10414499 | 0/60 | 10414874 | 10414875 |
| full-online-rubric | 0/9; queued 10414499 | 0/60 | 10414874 | 10414875 |
| full-red-team-artifact | 0/9; queued 10414499 | 0/60 | 10414874 | 10414875 |
| semi-static | 9/9 valid | 1 completed; final validation pending | 10414738 running | 10414746 |
| semi-offline-rubric | 9/9 valid | 0/60 | 10414740 | 10414748 |
| semi-online-rubric | 9/9 valid | 0/60 | 10414740 | 10414748 |
| semi-red-team-artifact | 9/9 valid | 0/60 | 10414740 | 10414748 |
| score-only-static | 9/9 valid | 0/60 | 10414738 running | 10414746 |
| score-only-offline-rubric | 9/9 valid | 0/60 | 10414739 | 10414747 |
| score-only-online-rubric | 9/9 valid | 0/60 | 10414740 | 10414748 |
| score-only-red-team-artifact | 9/9 valid | 0/60 | 10414740 | 10414748 |
| user-simulator-static | 9/9 valid | 60/60 | Preserved static | 10414690 |
| user-simulator-offline-rubric | 0/9; queued 10414499 | 0/60 | 10414874 | 10414875 |
| user-simulator-online-rubric | 0/9; queued 10414499 | 0/60 | 10414874 | 10414875 |
| user-simulator-red-team-artifact | 0/9; queued 10414499 | 0/60 | 10414874 | 10414875 |

Both static dev3 controls remain fully audited. New dev3 audits are queued: Semi/Score fixed 10414751, Semi/Score non-static 10414752, Full/User non-static 10414876. Results20 audit coverage for new conditions is pending; no partial-provider scientific means are reported. Historical uniform-rigorous and blocked static namespaces remain preserved and are not counted as corrected reusable conditions.

## Full/User source, inputs and ownership

- Frozen execution checkout: `/home/aydanh/repos/rubric_gen/runs/babel-code/paperbench-nontrace-results20-full-user-20260912`.
- Exact pin: **`411ea949ae9818085151484ce17a9de3c5b8ba41`**, adding only [one scoped config](../../../../experiments/babel/paperbench-nontrace-results20-full-user-learned.yaml) to frozen source fdd5403. No runtime, scoring, prompt or CPU-profile changes.
- Native experiment ID: **`paperbench-code-dev-factorial-r10-484a1576b8b6`**. The absolute `pretreatment_source` config binding is part of this ID; moving integration code/config paths are not interchangeable execution sources.
- Study: `/data/user_data/aydanh/rubric_gen/runs/paperbench-nontrace-results20-20260912/results20/full-user-learned/study/paperbench-code-dev-factorial-r10-484a1576b8b6`.
- Audit: `/data/user_data/aydanh/rubric_gen/runs/paperbench-nontrace-results20-20260912/results20/full-user-learned/audit/paperbench-code-dev-factorial-r10-484a1576b8b6`.
- Exact existing seeds: `/data/user_data/aydanh/rubric_gen/runs/paperbench-static-v2-20260910/results20/seeds`.
- Exact corrected pool: `/data/user_data/aydanh/rubric_gen/runs/paperbench-static-selected-neutral-heldout-rigorous-20260912/results20-final-pool/paraphrases`.

Native preparation in **10414690.0** took **33.936s**, with **zero provider calls/scientific writes**. It confirmed the absence of prior selected Full/User non-static Results20 assignments across the bounded PaperBench study census, empty new output namespaces,960 canonical ledger assignments with exactly 360 selected, unchanged common scientific fields, and a valid 100-variant corrected pool. The exact 60-seed native validation from Queue 4 is reused because source semantics and input paths are unchanged; seeds and paraphrases were not regenerated. Role policy remains **0 selected neutral, 1 development neutral, 2/3/4 rigorous-V2 heldouts**.

The new six-condition scope is **180 Full + 180 User** with no overlap with Queue 4's 480 assignments. Its native `pretreatment_source` references the **existing pinned Score-only-offline producer config**, study and ID `3d723e04c313`. That producer generates the 20 task-specific starting rubrics once. Native reuse validates its completed execution scope and original generation/blinding provenance before installing the exact shared starting rubric; no source file is rewritten. Full/User dev3 similarly retains its existing shared starting-rubric binding to dev3 producer10414497.

| Newly submitted stage | Job | Required successful dependency | CPU / workers |
|---|---|---|---|
| Full/User Results20 revisions, six conditions/360 assignments | **10414874** | `afterok:10414506:10414739` |32/32|
| Full/User Results20 native Sol+Opus audit | **10414875** | `afterok:10414874` |32/32|
| Full/User dev3 native Sol+Opus audit | **10414876** | `afterok:10414506` |32/32|

Commands are recorded exactly in the [compact Queue 5 receipt](queue5-status.json) and local `/home/aydanh/repos/rubric_gen/runs/paperbench-nontrace-full-user-20260912/launches.json`. They use ordinary `scripts/babel/experiment.sbatch --profile results20 revise|detect`; audits use `--resume`. Native detect validates completed revisions before audit execution. The existing dev3 validator uses 1 CPU. All new scientific jobs retain 32 CPUs/256GiB/32 workers, shared provider capacity 60 and one native global audit owner. CPU allocation, assignment workers and provider reservations remain separate limits; no unvalidated CPU patch was adopted and no other session's jobs or dirty work was altered.

## Native policy semantics retained

**Offline elicitation** uses exactly one pre-treatment generation with no live checkpoint; its generation 1 remains active after the initial checkpoint. **Online elicitation** starts from that same pre-treatment rubric, then uses successive revision checkpoints for its normal subsequent updates. **Red-team-artifact** retains its native live artifact-based red-team evidence in subsequent rubric updates. These are distinct policies and remain separate condition records.

The native implementation enforces these timings in `evolution_request.py`, `controller_scoring.py` and `pretreatment_rubrics.py`. `RubricPolicy.uses_red_team_trace` is false for artifact red-team, and versioned trace-defense dispatch requires the separate `red_team_trace` policy plus an explicit version. Neither is selected here. Full/User feedback definitions, solver/model settings, stopping rules, normalization and the Sol+Opus panel remain unchanged. Independent read-only config review found no blocking issue and reproduced the native consumer identity.

## Static recovery terminal result and exact residual diagnosis

Native recovery **10414690** ran from pinned **c6ec87b2fbcc3349d32625d2a8cfe78254d557fb**, ending at11:36:40 EDT with exit1 because **3 rubric judgments remain unpublished**. All120 revisions remain valid; native summary coverage is **Sol900/900, Opus897/900**, with all detector/holistic stages complete and reused. The original760 valid Opus judgments, two prior lossless replays and two successful smokes remain preserved; this recovery added **133 valid Opus judgments**. No final-panel metric or score was imputed.

The exact136 missing keys consumed **158 provider attempts**, including **22 retries**. There were25 failed attempts:120-criterion line-count errors18,178-criterion2,145-criterion1,70-criterion2,126-criterion1, and one `IncompleteProviderResponse` caused by **max_tokens**. That output-length failure recovered within its existing budget; it is not one of the terminal three. Preparation **180.448s**, global audit admission **380.773s**, provider execution **285.742s**, Slurm wall **14m11s**. No Sol/detector/holistic provider work was rescheduled.

All three terminal failures concern **ftrl,120 criteria**, with the unchanged15,360-token per-call budget. All nine attempts saved terminal JSON responses and ended far below that limit. Two responses contain119 newline-delimited rows and omit index119. Seven responses instead place rows on a **single line separated by `|`**: five contain all explicit indices0–119 in order, while two omit index119. The strict native v8 decoder correctly rejected all nine because the declared newline representation was absent or incomplete. The actual provider schema remained182bytes; this is neither schema compilation nor output-length failure.

Read-only diagnostic conversion of the five complete single-line responses retained every explicit global index, level index and entire reason substring, then passed the existing indexed decoder and canonical rubric validator with the exact saved rubric contracts. **Each of the three judgments has at least one complete candidate.** No index/criterion was inferred, no incomplete response was accepted, and no scientific record/raw response was changed. These are **unpublished lossless representation-replay candidates**, not additional valid scientific judgments yet.

| Missing judgment key | Scientific cell | Complete candidate attempts |
|---|---|---|
|`0164cfe5c2eb1d5ff576b6b14fda387d`|ftrl, User rep3, final, selected0|[2, 3]|
|`5123ea33722de6bd82e6535b02c7117a`|ftrl, User rep1, final, original|[2]|
|`af2320beaa217729634458ea4a3d90d4`|ftrl, User rep1, final, holdout3|[1, 2]|

The current native saved-response publication path supports the reviewed v5 identical-block replay, not this v8 delimiter variant. **Do not repeat unchanged bulk recovery or increase attempts.** The next shared-runtime step is a focused tested native replay extension for these exact complete representation cases, followed by missing-only zero-provider publication and native coverage validation. Existing897 valid Opus judgments must remain reusable and keep their provenance; if ambiguity prevents lossless replay, leave the affected judgment missing. This repair must preserve active execution pins and stay separate from CPU/trace work.

[Compact terminal evidence](static-opus-v8-recovery-tail.json) records all nine attempt errors, explicit counts, actual schema sizes, native canonical validation results and exact saved-response paths. The read-only initial manifest comparison was discarded because the intentionally preserved historical manifest uses old wire identities; missingness above uses the **current terminal native summary and its plan**. Private diagnosis is under `runs/paperbench-nontrace-full-user-20260912/`; no raw provider response is staged.

## Queue 6 priorities

1. Inspect existing owners before any action: static recovery 10414690; Full/User dev3 producer10414499 and validator10414506; shared Results20 starting-rubric producer10414739; Results20 owners10414738/39/40/10414874 and their existing audit dependencies. Do not create another dispatcher for any namespace.
2. Allow corrected Full/User dev3 to finish and validate. Its successful validator automatically releases10414874 once the shared Results20 producer also completes. If a concrete failure occurs, classify it and resume only missing assignments natively; keep valid cells and starting rubrics. Update dependent job IDs only if a failed owner has genuinely been replaced by authorized native resume.
3. Continue independent revision production while audits use the shared global lease;10414738 is already running. Repair/replay the three static delimiter cases through tested native publication before another unchanged recovery invocation. Report Slurm queue time, audit admission wait and provider execution separately. Do not cancel healthy work to change resource allocation.
4. After static Sol and Opus both reach 900/900 and detector/holistic coverage remains valid, compute the previously withheld final static metrics, task-cluster intervals and paired comparisons. Preserve the distinction between historical uniform-rigorous baseline, fixed-artifact screen and corrected full-revision result.
5. Collect every condition's native completed-revision and full audit coverage before reporting its final science. Retain the temporary cardinality source while10414690 depends on it; its validated general repair is already integrated without merging unrelated stale history.

Queue 5 hands off with the authorized Full/User workflow submitted and required validation dependencies intact. No red_team_trace condition was started and no final scientific result is claimed for the queued cells.

---

# PaperBench non-trace Results20 — Queue 4 handoff

**All 480 Semi/Score-only Results20 assignments now have queued native revision owners.** Before dispatch the exact inventory was **0 reusable, 0 running, 480 genuinely missing** (60 for each of eight conditions). At 2026-09-12 11:15 EDT, Results20 completion remains **0/480**, active Results20 assignments **0**, and queued assignments **480**. These are submitted jobs, not completed scientific results; CPU quota currently prevents admission.

Corrected dev3 now has **seven conditions at9/9 native-valid**, with Score-only-red-team-artifact at **7/9 valid and two running**, no assignment failures. In total **70/72** target dev3 assignments are native-valid. The five-condition learned-policy Results20 wave retains its existing successful-dev3-validation dependency: it cannot execute the two unvalidated cases' condition before validation. Its shared starting-rubric producer is also still queued, so this dependency does not currently add admission delay.

## Eight-condition promotion matrix

All Results20 cells require20 canonical tasks×3 replicates. `Queued` means zero assignment execution so far. Native dev3 validation covered the actual feedback/rubric policy, selected/development/heldout mapping, saved trajectory/checkpoint integrity and expected turn/stop behavior. The latest partial learned-dev3 collector exits1 because two assignments are still running; its failure list is empty.

| Condition | Dev3 revisions | Dev3 audit owner | Results20 revisions | Results20 audit owner | Blocking dependency / failure |
|---|---|---|---|---|---|
| semi-static | **9/9 valid** | 10414751 queued | 0/60; job **10414738** queued | 10414746 after revision | CPU quota; no assignment failure |
| semi-offline-rubric | **9/9 valid** | 10414752 queued | 0/60; job **10414740** queued | 10414748 after revision | Shared producer10414739 + native dev3 validator10414505; no assignment failure |
| semi-online-rubric | **9/9 valid** | 10414752 queued | 0/60; job **10414740** queued | 10414748 after revision | Shared producer10414739 + native dev3 validator10414505; no assignment failure |
| semi-red-team-artifact | **9/9 valid** | 10414752 queued | 0/60; job **10414740** queued | 10414748 after revision | Shared producer10414739 + native dev3 validator10414505; no assignment failure |
| score-only-static | **9/9 valid** | 10414751 queued | 0/60; job **10414738** queued | 10414746 after revision | CPU quota; no assignment failure |
| score-only-offline-rubric | **9/9 valid** | 10414752 queued | 0/60; job **10414739** queued | 10414747 after revision | CPU quota; no assignment failure |
| score-only-online-rubric | **9/9 valid** | 10414752 queued | 0/60; job **10414740** queued | 10414748 after revision | Shared producer10414739 + native dev3 validator10414505; no assignment failure |
| score-only-red-team-artifact | **7/9 valid**; 2 running | 10414752 queued | 0/60; job **10414740** queued | 10414748 after revision | Shared producer10414739 + native dev3 validator10414505; no assignment failure |

At initial dispatch, Semi-static, Score-only-static and Score-only-offline were already9/9 native-valid. Subsequent validation completed the other three Semi cells and Score-only-online while the queued waves remained unchanged. The one outstanding Score-only-artifact dev3 cell remains healthy. Opus transport does not block revision validation or these submissions.

## Source, frozen inputs and wave ownership

Execution checkout: `/home/aydanh/repos/rubric_gen/runs/babel-code/paperbench-nontrace-results20-20260912`, exact clean pin **`fdd5403abb16e412c003aa7db79d3eaf8cd4b552`**. It adds only three configuration files to the reviewed, live-validated v8 source **`c6ec87b2fbcc3349d32625d2a8cfe78254d557fb`**. No runtime/scoring/scientific prompt or CPU-profile code changed. The moving integration branch remains distinct from this execution pin; its unrelated prompt implementation changes derive different experiment identities.

The native input check loaded **60/60 exact existing seeds** and validated **20×5=100 existing corrected variants**, including role mapping0 selected neutral,1 development neutral,2/3/4 rigorous-V2 heldouts. It took80.342s in step10414497.12, with zero provider calls or scientific writes. A bounded scan of all PaperBench-named study roots found no already-executed Results20 assignments for these eight conditions. Dev3 uses a disjoint three-task set and contributes no reusable Results20 trajectories; the existing Full/User static120 remain preserved in their original namespace.

- Seeds: `/data/user_data/aydanh/rubric_gen/runs/paperbench-static-v2-20260910/results20/seeds`.
- Corrected pool: `/data/user_data/aydanh/rubric_gen/runs/paperbench-static-selected-neutral-heldout-rigorous-20260912/results20-final-pool/paraphrases`.
- Output base: `/data/user_data/aydanh/rubric_gen/runs/paperbench-nontrace-results20-20260912/results20/<scope>/{study,audit}/<experiment_id>`.

| Scope / native config | Assignments | Revision owner / dependency | Audit owner | Experiment ID suffix |
|---|---:|---|---|---|
| [semi-score-fixed](../../../../experiments/babel/paperbench-nontrace-results20-semi-score-fixed.yaml) |120| **10414738**, ready dev3 cells; queued CPU quota |10414746 afterok10414738|`3d723e04c313`|
| [score-only-offline](../../../../experiments/babel/paperbench-nontrace-results20-score-only-offline.yaml) |60| **10414739**, ready dev3 cell; queued CPU quota |10414747 afterok10414739|`3d723e04c313`|
| [semi-score-learned-rest](../../../../experiments/babel/paperbench-nontrace-results20-semi-score-learned-rest.yaml) |300| **10414740**, afterok10414739:10414505 |10414748 afterok10414740|`61c2335984ea`|

The full IDs are `paperbench-code-dev-factorial-r10-<suffix>`. Identical IDs in the first two scopes have disjoint selected conditions and distinct output roots, with one dispatcher each. Each config retains the same canonical16-condition non-trace definition and randomization; `execution_conditions` selects120/60/300 assignments, totaling480 without overlap. The generic20-condition YAML is not launched. No red_team_trace condition is selected.

Score-only-offline's ordinary native pipeline creates the20 task-specific shared starting rubrics once. The remaining learned-policy wave references that exact producer through native `pretreatment_source`; it generates only its policy-specific downstream evolution, not seeds/paraphrases or a duplicate starting pool. Native reuse requires a completed source scope, which explains dependency10414739. Future Full/User learned Results20 scopes should reuse the same producer where their native identity permits it. No scientific definitions were altered to accelerate scheduling.

All revision and audit jobs use the reviewed **Results20 profile:32 CPUs,256GiB,32 assignment/request workers where applicable**. Hosted provider reservations are separately bounded by the shared cap60; audit ownership remains one globally. The earlier unvalidated CPU-allocation patch is not included. Healthy PaperBench and other-session jobs remain intact. No duplicate dispatcher was submitted.

## Score-only interpretation from actual delivered messages

At frozen dev3 source4f67a3b, all four score-only policies deliver **numeric score feedback plus standard task/revision instructions**. Offline/online/red-team-artifact rubric machinery can change the numeric penalty, but does **not** append criterion text or qualitative reminders to these solver messages. This is a statement about delivered feedback, not a claim that tasks or revision instructions contain no text.

A read-only census inspected all36 score-only assignments and **349 persisted feedback records,349 turn prompts and349 started-attempt messages**. Every feedback object had exactly the `score` key; every turn and started-attempt message matched native score-only rendering, with **zero differences/errors and no enabled trace reminder gate**. Actual rendered score lines include `Rubric score: 22.705/100`; no policy-generated qualitative component appeared.

| Rubric policy | Inspected delivered turns | Turns with nonzero learned penalty | Observed generation rounds |
|---|---:|---:|---|
|fixed|87|0|0|
|offline_elicitation|87|18|0–1|
|online_elicitation|90|20|0–9|
|red_team_artifact|85|16|0–9|

`RevisionScorer._ordinary_checkpoint_feedback()` calls `project_rubric_feedback()`, whose score-only projection contains just the score. `render_revision_prompt()` embeds it into the standard revision message. `trace_defense_registry.enabled()` requires a versioned red_team_trace regime, which none of these four policies has. Saved rubric-generation/evaluation files were counted separately and are not evidence of solver delivery. Native completed-revision validation also reconstructs and checks the saved prompts. [Compact delivery evidence](score-only-delivery.json) retains exact sample message paths and counts; the full read-only operational census is `runs/paperbench-nontrace-results20-20260912/score-delivery.json`.

## Audit ownership and Queue 5 priorities

The v8 repair is validated and integrated (Queue3 core commitc451942); no known-broken bulk retry is launched. New native Sol+Opus owners are Results20 audits10414746/10414747/10414748 and dev3 audits10414751/10414752. Each uses `detect --resume` from the frozen execution source and the exact producer config. Dev3 identity was checked under v8 and remains `paperbench-code-dev-factorial-r10-c297aebb88ed`; both audit namespaces were unoccupied before submission.

Fixed-dev3 producer10414496 completed in40m32s and passed18/18 native checks. Its controller job ID had aged out: an `afterok:10414496` audit submission was rejected with `Job dependency problem` and created no job. After confirming `Invalid job id` in the controller and the successful accounting/validation evidence, audit10414751 was submitted as ready work without that expired dependency. Learned-dev3 audit10414752 waits for native validator10414505. Existing pure validators10414504/10414505/10414506 remain owned, and Full/User dev3 revision10414499 retains its original afterok10414497 dependency.

1. Inspect the existing jobs before action; do not resubmit queued/healthy owners. Collect validator10414505 and the two remaining Score-only-artifact dev3 assignments. If they fail, use native missing-only recovery, preserve the validated other cells and reconsider only the still-unstarted affected wave/dependency rather than blocking them on a failed condition indefinitely.
2. Let ready Results20 jobs10414738/10414739 enter normally;10414740 starts only after its native dependencies succeed. If preemption occurs, resume that same scope missing-only and update affected pending dependencies to the successful replacement owner.
3. Continue Full/User work in Queue5 using its existing dev3 owner10414499 and validator10414506. The Results20 shared starting-rubric producer is10414739; preserve its exact pool and producer scope.
4. Monitor static corrected audit recovery10414690, currently queued CPU quota:900/900 Sol,764/900 Opus,136 missing Opus remain. No static revision/valid judgment was rerun. Final static metrics remain withheld until full intended coverage is complete.
5. Audit scheduler wait, global lease admission and actual provider execution must remain separately measured. Preserve frozen execution pins while any pending/live job depends on them; do not switch to moving core prompts or mix the separate CPU patch into these runs.

[Machine-readable Queue4 state](queue4-status.json) contains exact commands, job dependencies, output roots, source pins, per-condition counts and operational exceptions. Private preparation/launch/native-validation receipts are under `runs/paperbench-nontrace-results20-20260912/`. No score was imputed, and no completed scientific result is inferred from directory names or successful submission.

---

## Queue 3 and earlier historical handoffs

# PaperBench non-trace Results20 — Queue 3 handoff

**The v8 single-call Opus repair passed both production smokes. Static coverage is now Sol 900/900 and Opus 764/900**, with all 120 revisions valid and detector/holistic stages complete. Native missing-only recovery **10414690** is submitted for the remaining **136 Opus judgments**. At handoff it is **PENDING (`QOSMaxCpuPerUserLimit`)**; no bulk provider calls have started. Final static metrics remain withheld until complete coverage.

Two proven lossless v5 saved responses were published with **zero provider calls**, retaining original v5 provenance. The subsequent 306 and 872 smokes each made exactly **one** new Opus call, ended with `end_turn`, validated every criterion, published canonically, and were recognized by fresh native resume. Output tokens were **8,388 and 18,472**, both within the unchanged 32,768 budget. Zero smoke retries, max-token failures, imputation or known-valid duplicate calls. All **5,472 pre-existing files** checked across the smokes remain byte-identical.

Execution stays pinned to **`c6ec87b2fbcc3349d32625d2a8cfe78254d557fb`** in `/home/aydanh/repos/rubric_gen/runs/babel-code/paperbench-opus-cardinality-20260912`, on the existing temporary `paperbench-opus-cardinality-v7-20260912` lineage. The 182-byte schema has only `criteria_text` and `overall_reasoning` strings; the local validator requires exact explicit ordered criterion coverage. **792 provider-free tests passed** on the execution pin, and **792 passed again** after the minimal code/test patch was ported to current integration base `96e4ad0`. Original scientific prompts, inputs, criterion/scoring semantics, provider settings and old canonical provenance remain bound exactly.

Before smokes, native dry preparation confirmed **Sol 0, valid Opus 0, missing Opus 138, detector/holistic 0** provider work. After publishing both smokes, fresh native preparation confirms **136 missing Opus only**. There is one static audit owner: job10414690. It retains the unmodified Results20 allocation of **32 CPUs, 256 GiB, 32 request workers**, shared provider cap60, and one global audit-study lease. Scheduler wait and later audit admission/lease wait must be reported separately from audit execution. No CPU-resource patch was adopted.

| Stage | Status / ownership | Runtime or remaining work |
|---|---|---|
| Two saved-v5 replays | Passed, step10414497.2, zero providers | 603.586s including native validation |
| V8 tests and native read-only census | Passed, steps10414497.5/.4 | 94.38s tests; 234.615s native census |
| Staged 306 then872 live smokes | Passed, step10414497.7 | 435.837s total; 0.001311s lease admission; 96.818s +170.830s provider wrappers |
| Core integration tests | Passed, step10414497.8 | 70.33s |
| Static native audit recovery | **10414690 pending CPU quota** | 136 missing Opus; all other provider work0 |
| Dev3 A Semi/Score fixed | **10414496 COMPLETED**, exit0 | 40m32s; validator10414504 pending quota |
| Dev3 B Semi/Score learned | **10414497 running** | Native missing work continues; validator10414505 retains dependency |
| Dev3 C Full/User learned | **10414499 pending**, afterok10414497 | 54 assignments; validator10414506 retains dependency |

Latest home telemetry: A {"completed": 18}; B {"completed": 35, "running": 19}. No assignment failures are recorded. Completion telemetry is not promotion validation: use the existing queued native validators before Results20 promotion. B has recorded transient evolution-generation timeouts under native recovery; no assignment failure is recorded. The auxiliary replay/test/smoke steps never stopped or replaced the revision dispatcher.

## Priorities for Queue 4

1. Inspect existing recovery owner **10414690** and its native runtime status. Do not submit a duplicate dispatcher. Allow native bounded retries and missing-only publication; if terminally incomplete, classify exact residual failures before further native resume.
2. Continue the existing dev3 B/C workflow and collect validators10414504/10414505/10414506. Promote only fully native-valid cells; preserve all completed assignments and original corrected-role Full/User controls.
3. Future audits of these pinned dev3 producers should use the validated pinned repair code with their existing exact config paths. Do not load old scientific namespaces through moving integration prompts that derive a different experiment ID. Global audit ownership remains one, so healthy revision work must continue while audits await admission.
4. Once static coverage is genuinely900/900 for both auditors and all other stages remain complete, compute withheld W/S/H/A/S-H/RH, task-cluster intervals and paired comparisons, then publish the final static report. No scientific means are claimed in this handoff.
5. Retain the temporary recovery branch/checkout while job10414690 depends on its pin. Its minimal general code/tests are integrated separately; after all dependencies end and remaining useful reports are preserved, remove the temporary branch safely. Do not merge its stale history.

Exact replay judgment keys, provenance, schema measurements, tests and live call receipts are in the [Opus repair report](../paperbench-static/opus-rubric-response-validation-fix.md) and [compact v8 evidence](../paperbench-static/opus-rubric-response-validation-v8.json). No trace condition or separate CPU-profile work was touched by Queue3.

## Queue 2 handoff and historical inventory

# PaperBench non-trace Results20 — current Queue 2 handoff

**Queue 2 has submitted all 126 missing dev3 assignments.** Existing Full-static and User-simulator-static remain **18/18 native-valid and fully audited**, with no rerun. As of the compute snapshot at **2026-09-12 10:09:36 EDT**, **40 new assignments are running, 32 are pending in active dispatchers, and 54 are queued behind the shared pretreatment producer**. No new assignment has yet completed; no failed/invalid row is recorded. This is active dev3 validation, not completed Results20 science.

The static Results20 scientific state is unchanged: 120/120 valid revisions, Sol 900/900, Opus 760/900, detector/holistic complete, two unpublished lossless replays and 138 genuinely missing provider judgments. The Opus completeness blocker is handed to Queue 3. No Opus probe, static recovery, Results20 revision, trace condition, or audit has been launched by this queue.

## Current dev3 matrix

Each cell requires three canonical tasks × three replicates. Runtime below is shared wave elapsed time at the snapshot, not summed per-condition CPU time or a completion estimate. `D` is the existing corrected-role dev3 producer documented in the historical inventory below; `Q2` is the new pinned execution source. Promotion readiness here means **revision wiring validated**; audit remains separately pending wherever indicated, as the user directed.

| Condition | 9/9 revision status | Audit status | Source | Runtime | Failure | Promotion to Results20 |
|---|---|---|---|---|---|---|
| full-static | **9/9 native-valid, reused** | Complete | D: `4c6f321` | Prior run; revalidated in 10414492 | None | Ready; retain original outputs |
| full-offline-rubric | 0/9; queued after B | Pending Opus repair | Q2: `4f67a3b` | Not started | None observed | Pending 9/9 native validation |
| full-online-rubric | 0/9; queued after B | Pending Opus repair | Q2: `4f67a3b` | Not started | None observed | Pending 9/9 native validation |
| full-red-team-artifact | 0/9; queued after B | Pending Opus repair | Q2: `4f67a3b` | Not started | None observed | Pending 9/9 native validation |
| semi-static | 0/9 complete; 5 running, 4 pending | Pending Opus repair | Q2: `4f67a3b` | A: 2m32s elapsed | None observed | Pending 9/9 native validation |
| semi-offline-rubric | 0/9 complete; 5 running, 4 pending | Pending Opus repair | Q2: `4f67a3b` | B: 3m33s elapsed | None observed | Pending 9/9 native validation |
| semi-online-rubric | 0/9 complete; 4 running, 5 pending | Pending Opus repair | Q2: `4f67a3b` | B: 3m33s elapsed | None observed | Pending 9/9 native validation |
| semi-red-team-artifact | 0/9 complete; 7 running, 2 pending | Pending Opus repair | Q2: `4f67a3b` | B: 3m33s elapsed | None observed | Pending 9/9 native validation |
| score-only-static | 0/9 complete; 3 running, 6 pending | Pending Opus repair | Q2: `4f67a3b` | A: 2m32s elapsed | None observed | Pending 9/9 native validation |
| score-only-offline-rubric | 0/9 complete; 6 running, 3 pending | Pending Opus repair | Q2: `4f67a3b` | B: 3m33s elapsed | None observed | Pending 9/9 native validation |
| score-only-online-rubric | 0/9 complete; 5 running, 4 pending | Pending Opus repair | Q2: `4f67a3b` | B: 3m33s elapsed | None observed | Pending 9/9 native validation |
| score-only-red-team-artifact | 0/9 complete; 5 running, 4 pending | Pending Opus repair | Q2: `4f67a3b` | B: 3m33s elapsed | None observed | Pending 9/9 native validation |
| user-simulator-static | **9/9 native-valid, reused** | Complete | D: `4c6f321` | Prior run; revalidated in 10414492 | None | Ready; retain original outputs |
| user-simulator-offline-rubric | 0/9; queued after B | Pending Opus repair | Q2: `4f67a3b` | Not started | None observed | Pending 9/9 native validation |
| user-simulator-online-rubric | 0/9; queued after B | Pending Opus repair | Q2: `4f67a3b` | Not started | None observed | Pending 9/9 native validation |
| user-simulator-red-team-artifact | 0/9; queued after B | Pending Opus repair | Q2: `4f67a3b` | Not started | None observed | Pending 9/9 native validation |

## Execution ownership and native reuse

Exact execution commit: **`4f67a3b8daca4a545d9c0a67578b283296e63823`**, three configuration files added to reviewed **`7178f1968594027c7c27960940029363f58f07b3`**. Checkout: `/home/aydanh/repos/rubric_gen/runs/babel-code/paperbench-nontrace-dev3-20260912`. Its tracked source was clean at both launches. The same configs were selectively ported and pushed to `origin/aydan-red-team` at **`0d560ab6841a1f134774cf3c9b1b78824611cc1c`**, preserving concurrent upstream commit `534e797998c3059c1582034e07b1c2d664d2ce10` without force. Moving integration code is not the execution pin: unrelated prompt implementation changes derive a different native scientific identity.

All three files declare the same canonical **16-condition** non-trace factorial and the unchanged randomization. Native `execution_conditions` selects disjoint missing cells; the two already completed fixed controls are not scheduled. Generic 20-condition YAML is not executed. Relative config links below resolve to the published files; live jobs use those files in the pinned checkout.

| Wave | Native config | Conditions / assignments | Producer | CPU / workers | Dependency | Provider-free final validator |
|---|---|---:|---|---:|---|---|
| A | [Semi/Score fixed](../../../../experiments/babel/paperbench-nontrace-dev3-semi-score-fixed.yaml) | 2 / 18 | `10414496` running | 8 / 8 | None | `10414504`, afterany:10414496 |
| B | [Semi/Score non-static](../../../../experiments/babel/paperbench-nontrace-dev3-semi-score-learned.yaml) | 6 / 54 | `10414497` running | 32 / 32 | None | `10414505`, afterany:10414497 |
| C | [Full/User non-static](../../../../experiments/babel/paperbench-nontrace-dev3-full-user-learned.yaml) | 6 / 54 | `10414499` pending | 32 / 32 | afterok:10414497 | `10414506`, afterany:10414499 |

A and B have experiment ID `paperbench-code-dev-factorial-r10-c297aebb88ed`, with distinct output roots and disjoint execution scopes. C has `paperbench-code-dev-factorial-r10-f1fb62662d3a`; its explicit native `pretreatment_source` binds B's experiment, study, and blinding identity. Native reuse requires a completed source scope, which explains C's dependency. This shares B's exact learned starting rubrics across all twelve non-static cells instead of regenerating them for Full/User. At the snapshot, all three B pretreatment manifests exist and the study has entered `revision`.

For each wave `<scope>` is `semi-score-fixed`, `semi-score-learned`, or `full-user-learned`:

- Study: `/data/user_data/aydanh/rubric_gen/runs/paperbench-nontrace-results20-20260912/dev3/<scope>/study/<experiment_id>`.
- Reserved audit path: `/data/user_data/aydanh/rubric_gen/runs/paperbench-nontrace-results20-20260912/dev3/<scope>/audit/<experiment_id>`; no audit owner has been submitted for these paths.
- Shared existing seeds: `/data/user_data/aydanh/rubric_gen/runs/paperbench-static-selected-neutral-heldout-rigorous-20260911/dev3/seeds`.
- Shared corrected paraphrases: `/data/user_data/aydanh/rubric_gen/runs/paperbench-static-selected-neutral-heldout-rigorous-20260911/dev3/paraphrases`.

Exact submission commands, from the pinned checkout:

```bash
sbatch --parsable --cpus-per-task=8 --mem=256G --job-name=pb-dev3-semi-score-fixed   scripts/babel/experiment.sbatch --profile dev3-8 revise   --experiment experiments/babel/paperbench-nontrace-dev3-semi-score-fixed.yaml

sbatch --parsable --cpus-per-task=32 --mem=256G --job-name=pb-dev3-semi-score-learned   scripts/babel/experiment.sbatch --profile results20 revise   --experiment experiments/babel/paperbench-nontrace-dev3-semi-score-learned.yaml

sbatch --parsable --cpus-per-task=32 --mem=256G --dependency=afterok:10414497   --job-name=pb-dev3-full-user-learned   scripts/babel/experiment.sbatch --profile results20 revise   --experiment experiments/babel/paperbench-nontrace-dev3-full-user-learned.yaml
```

These are historical launch commands, **not instructions to resubmit running work**. The `results20` profile in B/C supplies the reviewed 32-CPU/32-worker allocation; their scientific population is still the canonical three-task dev3 set. The 8/32-CPU profiles, 256 GiB memory, native retries/timeouts, and global provider cap 60 remain unchanged. No separate CPU-audit patch was adopted.

## Verification and live telemetry

Provider-free job **10414492** completed in **3m22s Slurm wall time** (199.924s measured work), with zero providers/scientific writes. Normal native machinery loaded all **nine exact seed blocks and 15 corrected variants**, validated role selection 0/1/2–4, and confirmed **9/9 Full-static plus 9/9 User-static** completed revisions against their original producer configuration. There were zero native validation errors. Their rubric/absolute/pairwise summaries remain 270/270, 54/54, and 36/36; the four completed detector windows make the full 504/504 panel documented in Queue 1. No historical uniform-rigorous revision was counted as corrected-role validation.

Configuration checks proved three tasks, three replicates, 144 canonical ledger entries per full definition, selected scope counts 18/54/54, 14 unique nonoverlapping execution conditions, no trace membership, unchanged common scientific fields, common input paths, and unoccupied new study/audit namespaces before submission. Queue 1's other study inventory remains applicable; the only newly discovered PaperBench root is this queue's owned namespace.

The live snapshot confirms matching feedback/rubric policies in all **40 created assignment manifests**, selected study counts 18 and 54, no failed/invalid assignment, and one or two persisted submissions per active assignment so far. These partial trajectories do not establish expected terminal turns/stops; native completion checks will validate those before promotion. The corrected pool passed native no-fallback validation; no paraphrase generation was invoked.

At startup, A reported eight active workers/eight owned provider reservations; B reported 32 active workers/nine owned reservations. Aggregate capacity samples were 43–44 reservations, below 60; workers are not provider reservations. A briefly queued behind the CPU quota while the read-only preparation allocation finished, then started normally. Six independent other-session jobs had appeared using 24 CPUs; our active A+B use 40, totaling 64. Those jobs and their audit/report dependencies were left untouched. No healthy job was interrupted or resized.

Durable local handoff receipts:

- `/home/aydanh/repos/rubric_gen/runs/paperbench-nontrace-dev3-20260912/{prepare.json,launches.json,snapshot.json}`.
- A telemetry: `/home/aydanh/repos/rubric_gen/runs/babel-code/paperbench-nontrace-dev3-20260912/runs/runtime-10414496-mxyyu_uy/`.
- B telemetry: `/home/aydanh/repos/rubric_gen/runs/babel-code/paperbench-nontrace-dev3-20260912/runs/runtime-10414497-b3hyicr8/`.
- Each producer also has `runs/slurm-pb-dev3-<scope>-<job>.out` in the pinned checkout; C will create its runtime receipt on admission.
- Queued one-CPU, provider-free collectors call `resolve_study_sources` and `validate_completed_revision` and write `validation-<scope>-<job>.json` plus `validate-<scope>-<job>.out` in the local handoff directory. They record per-condition native-valid counts, actual stop reasons/submission counts, failures, and revision-promotion readiness. They do not publish scientific judgments.

## Queue 3 handoff

Continue with the shared Opus omission blocker while A/B compute and C's dependency remain intact. Audits for new cells are pending; no audit dependency is safe to dispatch blindly through the known incomplete Opus path. All valid old audits and trajectories stay frozen. Do not rerun an assignment that completes during the handoff.

Use the owned jobs and native validator receipts to refresh this matrix. If a producer fails, diagnose its concrete failure and use the same scoped native `revise --resume` once appropriate; never launch a second dispatcher while its owner is healthy. A failed B leaves C's afterok dependency unsatisfied: preserve B's completed cells and shared pretreatment, repair/resume B natively, then update only the pending C dependency after B is valid. No automatic unlimited resubmission loop was created. Any newly exposed wiring bug should be isolated and tested without redefining a condition; independent work continues.

Queue 2 hands control back with all missing dev3 work submitted and no claim of completed dev3/Results20 science for the new cells. No long audit wait is part of this item.

---

# Queue 1 historical inventory — 09:53 EDT

This historical snapshot is superseded by the current dev3 status above. As of **2026-09-12 09:53 EDT**, the 16-condition mission has **120/960 reusable Results20 revision assignments**, with **840 missing**. Full-fixed and User-simulator-fixed already passed corrected-role dev3: **18/18 assignments and 504/504 unique audit judgments** across those two conditions. The other 14 conditions have no execution evidence in the inspected canonical namespaces and require **126 dev3 assignments** before their Results20 production runs.

The existing corrected static Results20 audit remains incomplete: **Sol 900/900, Opus 760/900**, with all detector and holistic stages complete. Of the 140 missing Opus judgments, two have losslessly replayable saved responses that remain unpublished; 138 require new responses. Final static metrics remain withheld. There are **no active or pending user Slurm jobs** at handoff, including no audit, repair dependency, or final-report owner.

Queue 1 performed inventory only. Its read-only compute job `10414403` completed in 4m42s using one CPU, with zero provider calls and zero scientific writes. No scientific job was launched, resumed, cancelled, or duplicated. The next queue should use the priorities below; this item does not wait for long jobs.

## Scope and evidence

The user-approved mission is feedback `{full, semi, score_only, user_simulator}` crossed with rubric `{fixed, offline_elicitation, online_elicitation, red_team_artifact}`. All `red_team_trace` conditions belong to another session and are excluded. Dev3 establishes wiring/execution validity; Results20 remains the scientific target.

Every condition must retain the corrected mapping: variant 0 selected neutral/original, variant 1 development neutral/original, and variants 2/3/4 rigorous-V2 heldouts. Preserve Luna/settings, three replicates, revision protocol, task membership, feedback and rubric-policy definitions, randomization, Sol+Opus panel, holistic/RH definitions, and aggregation. No Gemini probe or recovery is needed.

Evidence collected includes Slurm queue/accounting; independent execution clones and Git worktrees; home receipts/reports; and a compute-side scan of all ten PaperBench-named NFS run roots plus the conventional shared study/detection/pool locations. The scan found five study ledgers, seven audit-summary locations (including two historical snapshots), and ten seed/paraphrase pool locations, with no read errors. It inspected ledger rows, assignment state-file presence, audit summaries and canonical record counts, task membership, and pool manifests/variant files. Heavy artifact/trajectory subtrees were not exhaustively traversed. “Never run” below means no run found in these inspected locations, rather than completion inferred from a directory name.

This bounded inventory corroborates earlier native validation and replay receipts; it does not rerun scientific validation or provider work. The latest native read-only validation, job `10414163`, loaded all 120 corrected Results20 revisions and proved reuse of all 900 Sol and 760 Opus judgments. Local inventory evidence is retained at `/home/aydanh/repos/rubric_gen/runs/paperbench-nontrace-inventory-20260912/storage-inventory.json`, with scanner and `scan-10414403.out` alongside it; these operational files are not staged for Git.

## Sixteen-condition matrix

Reusable/missing assignment columns count **Results20 revisions only**: 20 tasks × 3 replicates = 60 per condition. Dev3 requires 3 tasks × 3 replicates = 9 per condition. `D` and `R` identify the exact source and namespace entries below. `O` means the shared Opus output-completeness blocker; `N` means a mission-scoped config and dev3 execution/validation are still required. An audit can be partial while all its revision assignments are reusable.

| Condition | Feedback policy | Rubric policy | Dev3 revision status | Dev3 audit status | Results20 revision status | Results20 audit status | Reusable assignments | Missing assignments | Source commit | Output owner | Blocking issue |
|---|---|---|---|---|---|---|---:|---:|---|---|---|
| full-static | full | fixed | Complete, reusable 9/9 | Complete (D) | Complete, reusable 60/60 | Partial; 82 missing Opus references | 60 | 0 | D: 4c6f321; R: 7178f19 | D + R; no live job | O |
| full-offline-rubric | full | offline_elicitation | Never run, 0/9 | Never run | Never run, 0/60 | Never run | 0 | 60 | — | Unassigned | N |
| full-online-rubric | full | online_elicitation | Never run, 0/9 | Never run | Never run, 0/60 | Never run | 0 | 60 | — | Unassigned | N |
| full-red-team-artifact | full | red_team_artifact | Never run, 0/9 | Never run | Never run, 0/60 | Never run | 0 | 60 | — | Unassigned | N |
| semi-static | semi | fixed | Never run, 0/9 | Never run | Never run, 0/60 | Never run | 0 | 60 | — | Unassigned | N |
| semi-offline-rubric | semi | offline_elicitation | Never run, 0/9 | Never run | Never run, 0/60 | Never run | 0 | 60 | — | Unassigned | N |
| semi-online-rubric | semi | online_elicitation | Never run, 0/9 | Never run | Never run, 0/60 | Never run | 0 | 60 | — | Unassigned | N |
| semi-red-team-artifact | semi | red_team_artifact | Never run, 0/9 | Never run | Never run, 0/60 | Never run | 0 | 60 | — | Unassigned | N |
| score-only-static | score_only | fixed | Never run, 0/9 | Never run | Never run, 0/60 | Never run | 0 | 60 | — | Unassigned | N |
| score-only-offline-rubric | score_only | offline_elicitation | Never run, 0/9 | Never run | Never run, 0/60 | Never run | 0 | 60 | — | Unassigned | N |
| score-only-online-rubric | score_only | online_elicitation | Never run, 0/9 | Never run | Never run, 0/60 | Never run | 0 | 60 | — | Unassigned | N |
| score-only-red-team-artifact | score_only | red_team_artifact | Never run, 0/9 | Never run | Never run, 0/60 | Never run | 0 | 60 | — | Unassigned | N |
| user-simulator-static | user_simulator | fixed | Complete, reusable 9/9 | Complete (D) | Complete, reusable 60/60 | Partial; 95 missing Opus references | 60 | 0 | D: 4c6f321; R: 7178f19 | D + R; no live job | O |
| user-simulator-offline-rubric | user_simulator | offline_elicitation | Never run, 0/9 | Never run | Never run, 0/60 | Never run | 0 | 60 | — | Unassigned | N |
| user-simulator-online-rubric | user_simulator | online_elicitation | Never run, 0/9 | Never run | Never run, 0/60 | Never run | 0 | 60 | — | Unassigned | N |
| user-simulator-red-team-artifact | user_simulator | red_team_artifact | Never run, 0/9 | Never run | Never run, 0/60 | Never run | 0 | 60 | — | Unassigned | N |

No matrix condition is currently running. Two are partially audited; fourteen are never run in the inspected namespaces. Scientifically incompatible historical executions are listed separately below and contribute zero reusable **revision assignments** to this matrix.

The 82 Full and 95 User missing audit references overlap on 37 shared initial/seed judgments: **82 + 95 − 37 = 140 unique missing judgments**. Per-condition rubric coverage is Sol 600/600 in each condition, Opus 518/600 Full and 505/600 User; these per-condition counts must not be added to obtain the union because initial judgments are shared.

## Reusable sources and exact output owners

All NFS paths below are under `/data/user_data/aydanh/rubric_gen/` and must be accessed through Slurm. Source identity belongs to the producing execution, not the current integration branch.

**D — corrected-role dev3.** Producer commit `4c6f321846147b50d8cf47f6b2dc05f515e14063`; experiment `paperbench-code-dev-factorial-r10-05110eff34b1`. Exported execution snapshot: `/home/aydanh/repos/rubric_gen/runs/babel-code/paperbench-role-policy-4c6`. This snapshot has no independent `.git`; a Git lookup falling through to its parent repository is not its producer identity.

- Study: `/data/user_data/aydanh/rubric_gen/runs/paperbench-static-selected-neutral-heldout-rigorous-20260911/dev3/study/paperbench-code-dev-factorial-r10-05110eff34b1`.
- Audit: `/data/user_data/aydanh/rubric_gen/runs/paperbench-static-selected-neutral-heldout-rigorous-20260911/dev3/audit/paperbench-code-dev-factorial-r10-05110eff34b1`.
- Terminal execution owners: `10397371`, `10397451`, `10397534`. Receipt root includes `.../paperbench-static-selected-neutral-heldout-rigorous-20260911/owners/dev3/10397534-20260911T095108Z`.
- Confirmed audit union: rubric 270/270 (135 each Sol/Opus), absolute 54/54, pairwise 36/36, four detector windows 36/36 each, total 504/504. See the [corrected-role execution report](/home/aydanh/repos/rubric_gen/docs/reports/2026-09-11/paperbench-static/selected-neutral-heldout-rigorous-execution.md).

**R — corrected Results20 with original-seed reuse.** Producer commit `7178f1968594027c7c27960940029363f58f07b3`; experiment `paperbench-code-dev-factorial-r10-08ba4d2c0d00`.

- Pinned producer checkout: `/home/aydanh/repos/rubric_gen/runs/babel-code/paperbench-results20-seed-reuse-fixed-20260912-clone`.
- Existing storage-only overlay: `experiments/babel/paperbench-static-selected-neutral-heldout-rigorous-results20-seed-reuse-fixed.yaml` in that checkout. Retain this exact configuration for this namespace; do not recreate the run using a moving branch with changed scientific identity.
- Study: `/data/user_data/aydanh/rubric_gen/runs/paperbench-static-selected-neutral-heldout-rigorous-20260912/results20-seed-reuse-fixed/study/paperbench-code-dev-factorial-r10-08ba4d2c0d00`.
- Audit: `/data/user_data/aydanh/rubric_gen/runs/paperbench-static-selected-neutral-heldout-rigorous-20260912/results20-seed-reuse-fixed/audit/paperbench-code-dev-factorial-r10-08ba4d2c0d00`.
- Confirmed union: rubric 1,660/1,800 (Sol 900, Opus 760), absolute 360/360, pairwise 240/240, four detector windows 240/240 each; **3,220/3,360** total. Final metrics remain withheld until the intended panel completes.

| Job / ownership | Terminal state | Slurm elapsed | Interpretation |
|---|---|---:|---|
| 10407656 revision producer | OUT_OF_MEMORY | 2:53:04 | Original corrected producer; 119 completed before recovery |
| 10410202 native revision resume | COMPLETED | 0:15:40 | Only remaining assignment recovered; current 120/120 valid |
| 10410277 initial audit | FAILED | 3:41:29 | Preserve its valid judgments and failed attempts |
| 10410404 dependent final report | CANCELLED | 0:00:00 | No queued final-report execution remains |
| 10411954 native audit resume | FAILED | 0:28:50 | Recovered two judgments; remaining 140 exhausted attempts |
| 10414045 v6 single-cell smoke | FAILED | 0:06:15 | Anthropic HTTP 400 schema complexity; no publication |
| 10414163 v7 native read-only dry validation | COMPLETED | 0:05:49 | 120 revisions and all valid audit outputs reusable |
| 10414183 v7 single-cell smoke | FAILED | 0:01:36 | Schema compiled; incomplete criterion output rejected |
| 10414205 smoke evidence inspection | COMPLETED | 0:00:02 | Read-only classification; no provider calls |
| 10414403 this inventory | COMPLETED | 0:04:42 | One CPU; no scientific mutation |

## Frozen inputs and other discovered pools

| Input root | Observed contents / earlier native validation | Reuse decision |
|---|---|---|
| `runs/paperbench-static-selected-neutral-heldout-rigorous-20260911/dev3/seeds` | Three tasks; nine original seed blocks used by completed D | Reuse for the same dev3 task/settings identity |
| `runs/paperbench-static-selected-neutral-heldout-rigorous-20260911/dev3/paraphrases` | Three manifest tasks, 15 variant files; corrected roles native-validated | Preferred corrected dev3 pool |
| `runs/paperbench-static-v2-20260910/results20/seeds` | 20 tasks; exact 60 original blocks already native-loaded by R | Preserve and reuse these exact seeds where native identity permits |
| `runs/paperbench-static-selected-neutral-heldout-rigorous-20260912/results20-final-pool/paraphrases` | 20 manifest tasks, 100 variant files; corrected roles native-validated | Preferred corrected Results20 pool; used by R |
| `runs/paperbench-static-selected-neutral-heldout-rigorous-20260911/results20-pool-retry2/paraphrases` | 20 manifest tasks, 100 variant files; historical corrected-screen pool | Preserve screen provenance; do not substitute for R's final pool |
| `runs/paperbench-static-selected-neutral-heldout-rigorous-20260911/results20/paraphrases` | 20 task directories, only 12 variants; empty manifest task list | Incomplete attempt; not reusable as a completed pool |
| `runs/paperbench-static-selected-neutral-heldout-rigorous-20260911/results20-pool-retry/paraphrases` | 20 task directories, zero variants; empty manifest task list | Failed attempt; not reusable as a completed pool |
| `runs/paperbench-static-v2-20260910/dev3/seeds` | Three task directories; historical dev3 seed set | Preserve; corrected D already has its own validated seed set |
| `runs/paperbench-static-v2-20260910/dev3/paraphrases` | Three tasks, 15 variants; uniform-rigorous policy | Scientifically incompatible role policy for this mission |
| `runs/paperbench-static-v2-20260910/results20/paraphrases` | 20 tasks, 100 variants; uniform-rigorous policy | Scientifically incompatible role policy for this mission |

These abbreviated paths share the absolute NFS root given above. The original Results20 seed producer is `609ce6889fc8d66db60f77b564a19c8f2d7a2919`; the reviewed seed-semantic reuse fix at `7178f196...` allows reuse without rewriting them. New condition consumers must use normal native identity checks; no input regeneration or compatibility fabrication is authorized by this inventory.

Canonical dev3 tasks are `semantic-self-consistency`, `self-expansion`, `self-composing-policies`; randomization seed `20260812`, replicates 3. Results20 tasks are `fre`, `mechanistic-understanding`, `bridging-data-gaps`, `test-time-model-adaptation`, `all-in-one`, `sequential-neural-score-estimation`, `robust-clip`, `what-will-my-model-forget`, `pinn`, `stay-on-topic-with-classifier-free-guidance`, `rice`, `sample-specific-masks`, `adaptive-pruning`, `sapg`, `lca-on-the-line`, `stochastic-interpolants`, `bbox`, `lbcs`, `bam`, `ftrl`; randomization seed `20260820`, replicates 3.

## Historical runs excluded from mission completion

- **Uniform-rigorous-v2 baseline:** producer `609ce6889fc8d66db60f77b564a19c8f2d7a2919`; dev3 `paperbench-code-dev-factorial-r10-94e33cf9dae5`, Results20 `paperbench-code-dev-factorial-r10-8d26fd3360b3`, under `runs/paperbench-static-v2-20260910/{dev3,results20}/{study,audit}`. Historical dev3 18/18 and Results20 120/120 revisions are complete, but revision optimization used the wrong selected role for the new mission. The [historical final report](/home/aydanh/repos/rubric_gen/docs/reports/2026-09-10/paperbench-static/results20/README.md) composes 3,333 original judgments plus 27 recovered v5 judgments; the old root's stale incomplete summary alone does not describe that historical completion. Its S−H values, Full −0.859 and User −0.512, are comparison baselines only. Its exact original seeds remain reusable as documented above.
- **Corrected fixed-artifact screen:** `runs/paperbench-static-selected-neutral-heldout-rigorous-20260911/results20/manipulation-screen`, based on the old baseline's artifacts with corrected-role scoring from the `4c6f321...` execution context. Current records are 959/960: Sol 480/480, Opus 479/480; Full 480 references, User 479. It contributes no new revision trajectories. Full S−H +1.108 and User +1.101 observed/incomplete must stay separate from the final corrected revision baseline.
- **Blocked pre-fix attempt:** preserve unchanged `runs/paperbench-static-selected-neutral-heldout-rigorous-20260912/results20/study/paperbench-code-dev-factorial-r10-08ba4d2c0d00`, produced from `1776460cd252997f45800a04a5fd590f57a64af3`. The ledger still says `running` with 114 failed and six running assignment rows, but there is no live job and no valid scientific completion. This stale ledger is failure evidence, not an active execution or a resume target.
- **Audit diagnostics/recovery supplements:** the five `paperbench-keyed-audit-validation-v{1,2,3}-20260910` / `paperbench-count-safe-audit-validation-v{4,5}-20260910` roots and `paperbench-v5-missing-only-20260910`, `paperbench-v5-stream-missing-only-20260910` contain validation/failure/recovery evidence. They are not additional matrix conditions. Two `owners/results20/.../native-before` audit-summary snapshots likewise are not independent completed audits.

## Shared Opus blocker and repair ownership

The temporary recovery branch is `paperbench-opus-cardinality-v7-20260912`. Exact code pin: **`8bff72545f78f58cd93101043842a134fa04ad38`**; published repair/smoke-report tip: **`bc345a6f644ecf882106604e6545d9d9653fa178`**. Execution checkout remains `/home/aydanh/repos/rubric_gen/runs/babel-code/paperbench-opus-cardinality-20260912`, detached at the code pin. It has only known local logs/report files beyond that pin, with implementation/tests clean. The current diagnosis is in that checkout's [repair report](/home/aydanh/repos/rubric_gen/runs/babel-code/paperbench-opus-cardinality-20260912/docs/reports/2026-09-12/paperbench-static/opus-rubric-response-validation-fix.md) and [compact smoke receipt](/home/aydanh/repos/rubric_gen/runs/babel-code/paperbench-opus-cardinality-20260912/docs/reports/2026-09-12/paperbench-static/opus-rubric-response-validation-v7-smoke.json).

V5 permitted duplicate/omitted coarse blocks. V6 (`57f54af532b9589c6f665321d562e16296d2c3fe`) required keyed trees but failed server schema compilation. V7 reduces provider schema size at 306/872 criteria to 413/761 bytes using required block strings, while strict local parsing rejects incomplete judgments. Provider-free tests passed (460), and the native dry scheduling receipt gives Sol 0, existing valid Opus 0, missing Opus provider judgments 138, local replays 2, detector/holistic 0. All 760 valid Opus judgments and their 4,560 files remained byte-identical.

However, v7 smoke `10414183` for `fre`, replicate 3, User-static, final heldout variant 2 **failed scientific completeness**. Anthropic accepted the schema and ended normally (`end_turn`, 2,441 output tokens of 32,768), but returned only indices 0–63, empty `block_1`/`block_2`/`block_3`, and literal `x` as the tail. All remaining 242 judgments are absent. This is an omission/placeholder failure, not schema compilation or max-token truncation. Exact native error: `block-string rubric block_1 must contain exactly 64 criterion lines`.

No 872 smoke, salvage publication, or bulk recovery followed. The two old lossless saved-response recoveries are still unpublished. Queue 2 must not interpret “schema compiled” as permission to bulk-resume a validated fix. Resolve or explicitly carry this blocker forward using bounded production validation while retaining all scientific invariants and existing valid outputs; do not impute absent judgments.

## Source hygiene and operational limits

The inventory/report checkout is detached at reviewed core `c866831da478042fc2b7e6c79828c324ef013e6e` in `/home/aydanh/repos/rubric_gen/runs/babel-code/paperbench-nontrace-inventory-20260912`. This is a documentation checkout, not a new experiment or condition branch. The long-lived integration destination remains `origin/aydan-red-team`.

The main checkout at `60bae25c3d39d8feaec1848cc757969935dd62e1` contains concurrent dirty/staged work; the earlier incomplete final scientific reports are already staged there. This inventory leaves that index and all those files untouched. The `paperbench-opus-cardinality-review-20260912` checkout at `0a0b0aff2e5ea8a3c0e5ce4d72fb4c7bb1e0f15f` is an older integration/review copy, not the v7 scientific execution pin. The separate `paperbench-results20-cpu-resource-audit-20260912` checkout is based on `7178f196...` and contains uncommitted resource work; none is adopted here. `runtime-throughput-final` at `1776460...` is the blocked source and must not execute this recovery.

Do not create branches per condition/job. Retain the existing temporary v7 branch while its shared repair remains unvalidated. Port reviewed general commits into current `aydan-red-team` selectively when ready; do not merge a stale scientific branch wholesale. Delete temporary branches only after useful changes/reports are integrated and no live job depends on them. BioMNIBench worktrees, jobs, and dirty files are outside this session's ownership.

The effective PaperBench launcher profiles inspected are `dev3-4=(4 CPUs, 4 workers)`, `dev3-8=(8 CPUs, 8 workers)`, `results20=(32 CPUs, 32 workers)`, and `inspection=(1 CPU, 4 workers)`. The shared sbatch default is 8 CPUs; the established Results20 invocation explicitly requests 32 CPUs and 256 GiB. The separate proposed reductions (revision 8, audit 4, small recovery 2) have not established live throughput equivalence and are not adopted. This one-CPU metadata inventory is not such an equivalence test.

Keep the per-user CPU quota at 64, aggregate provider reservation cap at 60, and one global audit-study owner. Assignment workers, allocated CPUs, and provider reservations are distinct. Recheck all sessions' active allocations before scheduling; a pair of 32-CPU jobs may fit the CPU quota but still contend for provider capacity, and two audits cannot own the global study lease together. Never interrupt healthy jobs to change allocations.

## Immediate handoff priorities

1. **Queue 2 receives this inventory and the v7 omission evidence immediately.** No scientific job or dependency needs monitoring/restarting. Preserve the existing 120 revisions, 900 Sol, 760 Opus, complete detector/holistic records, exact seeds/pool, and both unpublished lossless replays. The static audit blocker is shared infrastructure work; complete a real exact-cardinality production judgment before treating the current repair as recovery-ready.
2. **Prepare the canonical non-trace dev3/Results20 scope on a reviewed core pin.** Current `experiments/paperbench-{dev3,results20}.yaml` each include 20 conditions including trace and a Gemini auditor, so they must not be launched wholesale for this mission. The corrected `experiments/babel/paperbench-static-selected-neutral-heldout-rigorous-{dev3,results20}.yaml` supplies the validated role policy and Sol+Opus panel but only two fixed conditions. Carry the approved 16-condition scope forward without changing common scientific settings. Register actual output owners/paths when launching; no new scientific namespaces were allocated in Queue 1.
3. **Validate the 14 missing conditions on canonical dev3.** First address semi-fixed and score-only-fixed (18 missing assignments together), then the four-feedback offline, online, and artifact policy groups (36 assignments per group). This is a handoff ordering, not permission to serialize independent preparation unnecessarily. Reuse the corrected dev3 inputs when native identity permits. Existing Full/User-fixed validation remains reusable; do not rerun it merely to fill a larger matrix.
4. **Promote each successfully validated condition to its missing Results20 production work.** There are 840 missing assignments total, with none missing in Full/User-fixed. Use the exact validated Results20 seeds and corrected final pool where compatible. Schedule native missing-only work under shared CPU/provider limits; avoid letting an unrelated condition's audit wait prevent independent preparation or authorized revision production.
5. **Complete native Sol+Opus auditing and reporting.** Give the existing static audit only its genuinely missing judgments after the shared output problem is resolved; account separately for zero-call replay and new responses. Audit the newly validated/produced conditions through the single global owner. Final condition metrics require complete intended coverage, without imputation; report incomplete coverage explicitly until then. Keep old uniform-rigorous results, corrected fixed-artifact screen, and the corrected full-revision baseline distinct.

Subsequent queued instructions can refine this ordering. Queue 1 is complete; no additional experiment, trace condition, provider probe, CPU-profile patch, or long-job wait was started.
