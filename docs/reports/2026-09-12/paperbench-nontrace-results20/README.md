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
