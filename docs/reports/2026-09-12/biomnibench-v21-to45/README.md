# BioMNIBench v2.1 → Results45 mission

**Queue item 6: official Results30 membership fixed; missing seed preparation launched.**
The [Full-only expansion](queue6/README.md) retains120 existing Full records and
adds60 fixed/trace records on the official ten tasks. Source f017a3f is committed
and pushed; two four-CPU seed lanes10414853/10414854 prepare30 shared blocks.
No original20 input or outcome is regenerated. The historical BioMNIBench V2
heldout instruction differs from today's committed rigorous prompt; added-task
heldout authority is awaiting the user's decision while independent seeds proceed.

Both R1/R2 revision producers completed9/9; their audit dependencies continue.
One queue3 semi-trace task was preempted and resumes natively under10414859.
The semi-fixed audit completed two tasks but lacks six Opus rubric judgments on
da-11-1; saved failures are truncation/refusal/duplicate-key failures, not a
demonstrated network timeout. One unchanged missing-only audit resume10414883
preserves all successful scores and direct judgments. No new User winner is
nominated from partial outcomes. See [paired synthesis](queue4/README.md) and
[confirmation/scale decision](queue5/README.md).

Mission start: **2026-09-12 09:27:31 EDT**. The requested 9–10-hour checkpoint
falls at **18:27–19:27 EDT** today, irrespective of whether scale-up has finished.
Healthy submitted work may continue beyond that checkpoint. Status lives in
[the single mission status record](../../../../experiments/biomnibench-v21-to45/status.json).

## Scope and source state

The new queue supersedes unstarted portions of the previous plan. It authorizes
development followed by progressive Results20/30/45 evaluation, while preserving
completed negative evidence. Earlier experiment-specific no-launch decisions
remain historical decisions, not a prohibition on the new mission.

The architecture stays artifact → red-team attack → contrast/diagnosis →
criterion → native admission → existing feedback/revision. No new model roles,
verification pipeline, feedback round trips, or common simulator rewrite is
planned. Failed v3/P1/P2 changes are not stacked into the new reference.
Baseline recipes, models/settings, task inputs, rubric roles, scoring and RH
definitions, permissions, and completed results remain unchanged. Each later
treatment must identify its limited red-team-specific change.

At the initial Slurm inspection **no user jobs were running or pending**. The only
job dispatched for this item was **10414358**, a read-only compute-storage
inventory: **COMPLETED 0:0**, five seconds, one CPU, 0.264 CPU-seconds, 76,072 KiB
maximum RSS, **zero provider calls**. No solver, attack, seed, rubric generation,
or outcome audit was launched. Its [script](../../../../experiments/biomnibench-v21-to45/inventory.py)
reads metadata and existing completion records; [inventory.json](inventory.json)
contains the results. It does not recalculate whole-dataset hashes.

The main checkout is on `aydan-red-team` at `60bae25` with unrelated dirty and
staged runtime/PaperBench work. That work is untouched. This mission continues in
the existing worktree `/home/aydanh/repos/rubric_gen/runs/babel-code/attack-defense-v2`,
starting at **6f51cff7699053ff7c901395999c8bbd960eac7c**. Tracked files were clean;
historical untracked logs and receipts are preserved. The fetched branch had no
additional remote commits at inspection. No new branch/worktree was created.

The source already contains reviewed runtime descendants **1776460** and
**57f54af**, verified by Git ancestry: streaming/inactivity handling, missing-only
resume, shared capacity ownership, and the reviewed Anthropic rubric-cardinality
repair. See the [runtime report](../../2026-09-11/runtime-reliability/runtime-throughput-cleanup.md).
Uncommitted changes in another checkout are not assumed reviewed. Later launches
will use a committed compatible source, with no hot swap during an active job.

## Reusable scientific evidence

| Evidence | Tasks × replicates × conditions | Completed evidence | Reuse boundary |
|---|---|---|---|
| v2.1 Result20 trace | 20 × 3 × 2: Full and User | **120/120 assignments; 3,668/3,668 unique judgments**, including all four RH windows | Existing repaired cohort and producer/consumer history remain intact; new unchanged inputs use native reuse validation |
| Frozen Result20 static | 20 × 3 × 2: Full and User | **120/120 assignments**, compatible saved scoring/RH and V2 H evidence reported with v2.1 | No static regeneration for convenience; no mixing older heldouts with V2 |
| Canonical v2.1 User dev3 control | 3 × 3 × 1 | **9/9 assignments; 336/336 judgments** | One common saved trace control; compatibility was checked in the closed D×G study, and its current study/audit directories exist |
| Stress v2.1/v3/v3.1/v3.2 | 3 × 3 per variant | Completed historical comparisons | Heavily reused development cases; preserve failures, do not restart |
| D×G diagnostic challengers | 12 checkpoints × 3 | **36/36 feedback checks; 0/27 canonical trajectories** | Closed no-winner result; no new continuation of these candidates |
| P1/P2 firewall diagnostics | 12 checkpoints × 2 | **24/24 checkpoints, 108/108 model stages; no challenger trajectories** | Closed no-winner result; do not adopt their additional roles |

The v2.1 [report](../../2026-09-11/trace-attack-defense-v2.1/README.md),
[accounting](../../2026-09-11/trace-attack-defense-v2.1/accounting.json), and current
NFS `completion.json` agree on the trace cohort and audit counts. This item read
all seven saved stage summaries, not all 3,668 individual judgments again.
Its experiment is `biomnibench-da-factorial-r10-5115fffdd1c0`; run root:
`/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20`.
The cohort preserves 118 compatible v2 imports and two v2.1 recovered assignments;
its consumer snapshot is `c43a921f9f187cda8659304547ec8849a5f5ba7c`.

The canonical control is at
`/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/control-v21-compatible`.
Task experiment suffixes are `62e39def3939` (da-3-4), `dddf5e1c5878` (da-11-1),
and `e44e429b51a6` (da-18-1). The [saved control rows and coverage](../trace-user-parallel-diagnostics/control-outcomes.json)
contain all nine assignments and both auditors. Equal-weight full-trajectory RH
is **5/18 = 27.78%**, post-update **1/18 = 5.56%**, and both final windows **0/18**.
Native full-trajectory union is **3/9**, a different definition. This is a trace
control, not a static baseline. A future treatment still needs native input
compatibility; directory existence alone does not establish it.

The existing [Result20 config](../../../../experiments/trace-attack-defense-v21/result20.yaml)
uses three replicates and randomization seed **20260820**. Canonical dev3 uses
**20260806**. Luna remains the solver, sidecar, proposer and simulator; Sol+Opus
remain the authoritative outcome panel. Selected variant 0, development variant
1, and three heldouts retain their distinct roles. Frozen s000/g1 inputs retain
their actual producer metadata. The declared but deferred Gemini model is not an
executed third auditor.

## Reference results and unresolved findings

The following are historical v2.1 results, not new mission measurements.

| Arm | Full-trajectory RH static → v2.1 | W−S static → v2.1 | S−H static → v2.1 | H−A static → v2.1 | ΔS | ΔH | ΔA |
|---|---:|---:|---:|---:|---:|---:|---:|
| Full | 20.83% → 14.17% | 7.70 → 6.12 | 1.47 → 0.74 | 20.09 → 17.82 | +0.70 | +1.43 | +3.69 |
| User | 20.00% → 10.00% | 7.34 → 9.19 | 1.36 → 1.28 | 10.40 → 7.86 | −0.62 | −0.54 | +2.01 |

Full passed its historical practical joint rule; User did not. Those decisions
are not relabeled under today's interpretation. Full's later RH windows worsened
despite its full-trajectory improvement; all windows must remain visible. User
learning is active: 48/60 assignments admitted an online rule, versus 38/60 Full.
Admission coverage is not an optimization target; valid scientific rejection is
part of the method.

The [D×G study](../trace-user-parallel-diagnostics/README.md) found private-answer
guidance and false evaluator allegations even without a selected learned reminder.
The [firewall study](../trace-user-public-evidence-firewall/README.md) removed the
decisive private-name leakage but still produced false public claims or lost
genuine corrections. These findings concern common feedback/model reliability;
they do not authorize rewriting that comparison channel. The v3 selector defect
changed one choice across 190 checkpoints, not an established explanation of its
quality loss. New red-team-specific work starts from the correct shared v2.1
selector and existing feedback behavior.

## Task membership, exposure, and missing inputs

[task-inventory.csv](task-inventory.csv) records all 50 source-pool task IDs:
20 Result20 members, 25 historical additions, three excluded dev tasks, and two
unselected tasks. Membership comes from the existing September 8 inventory at
`/home/aydanh/repos/rubric_gen/investigation/biomnibench-results45-20260908/inventory.json`,
pinned to public source **e1c8ca5e11a620087bc48d97888eb69176a1f235**. Its historical
selection ordered non-dev tasks before new outcomes. This mission does not choose
members by scores or introduce another selection scheme.

| Set | Membership | Replicates / condition scope | Exposure and actual preparation |
|---|---|---|---|
| Canonical dev3 | da-3-4, da-11-1, da-18-1 | Three; saved User v2.1 control, later package scope to be declared | Development, already repeatedly examined; not confirmation |
| Result20 | Existing 20, listed in CSV and config | Three; frozen Full/User static and v2.1 trace | Repeated development/evaluation exposure; cannot be called untouched confirmation |
| Results30 | **No fixed 30-task membership/config found** in searched experiment/plan/run records or historical45 inventory | Not yet fixed for this mission | Must explicitly record membership before dispatch, without outcome selection |
| Results45 | Existing Result20 plus the exact 25 additions below | Historical plan: three replicates, User static/trace, 270 assignments; that is historical planned scope, not executed coverage or the new queue's final condition scope | 45 tasks' data available; older paraphrases prepared; no 30/45 scientific cohort located |

Historical additional25 order:
`da-8-1, da-26-4, da-20-4, da-19-3, da-4-1, da-1-3, da-3-5, da-4-6, da-5-1, da-26-2, da-9-7, da-24-3, da-6-5, da-17-3, da-1-4, da-8-3, da-17-5, da-17-1, da-9-1, da-20-1, da-4-7, da-8-2, da-19-4, da-25-1, da-6-2`.
Unselected non-dev tasks are **da-20-3 and da-5-3**. Do not substitute them based
on results. No new additional25 task-level outcome analysis was performed here;
absence of located execution does not prove those tasks were never inspected.

Storage findings from compute job 10414358:

- Data root: `/data/user_data/aydanh/rubric_gen/data/biomnibench-da-results45-e1c8ca5e11a6`.
  All 45 instruction/task/rubric files are present. All **646** historically
  validated files have matching sizes. The prior byte/hash validation was job
  **10372829**; this metadata check is not a new content-integrity proof.
- Canonical V2 Result20 pool: `/data/user_data/aydanh/rubric_gen/pools/paraphrases/biomnibench/result20-prompt-nofallback-v2-20260910`:
  **20 tasks, 100 variant texts**. Its selected/development/heldout use follows
  the validated v2.1 receipts; old manifest dates alone do not prove V2 contents.
- Older `confirmation-20260909/{original20,additional25}` pools contain **20/100**
  and **25/125** tasks/variant texts. Their metadata says the earlier wording-only
  protocol. Additional25 V2-compatible heldouts and their native producer
  compatibility are **not established**. Do not silently relabel this older pool.
- Planned `/data/user_data/aydanh/rubric_gen/seeds/biomnibench/confirmation-20260909`
  **does not exist**. Result20 seed inputs are present at the v1 input root used
  by v2.1. Additional25 compatible seeds, realized g1, static outputs and outcome
  judgments have not been located; preparation is still required unless a later
  inventory identifies compatible native records.
- Shared storage had **260.5 GiB available** at inspection. Large task data and
  solver workspaces require accounting before scale-up; do not duplicate the
  82.7 GB dataset per treatment. Only small reports/configuration belong in home.

## Prospective interpretation and prioritized plan

For new packages, W is weak selected-base, W_train includes learned penalties,
S is strong selected, H is canonical V2 heldout, and A is rubric-free absolute
quality. W−S is verifier disagreement: approximately baseline-level or a modest
0.1–0.5-point reduction can be acceptable. A larger reduction is not intrinsically
better. Keep S−H low while preserving S/H, and interpret H−A with both H and A.
Preserve A and genuine RH benefit where the comparator has headroom; zero-floor
windows cannot demonstrate reduction. Signed-gap overshoot or lower quality is
not improvement. Equal-weight Sol+Opus rates, native panel union, abstentions,
and individual auditor results remain separate. Ranking agreement is descriptive.
Historical numerical thresholds remain attached to their historical experiments;
no new composite score or numerical gate is introduced here.

1. **Queue item 2:** declare its specific v2.1-based red-team treatment and reuse
   the available development inputs/control. Explain any evidence-supported
   substitution before dispatch; do not invent an unprovided package.
2. Test the changed behavior, commit a ready configuration, and execute useful
   bounded development comparisons under normal launch/resume. Diagnose losses
   from saved cases; preserve negatives and continue other authorized useful work.
3. Select the simplest supported treatment, then run matched Result20 evaluation
   using compatible static/pretreatment evidence. Report all metrics/windows,
   uncertainty, cost, completion and mechanisms before any scale increment.
4. Fix Results30 membership and final condition scope prospectively; preserve
   the recorded Results45 membership. Prepare only missing compatible inputs.
   Reuse completed overlapping tasks through native validation, with no fabricated
   metadata or silent replacement of heldouts.
5. Progress through Results30 and Results45 as evidence and available capacity
   permit, committing each complete increment and concrete failure diagnosis.
   These are progressively larger evaluations, not automatically untouched
   confirmation. Publish the time-window checkpoint even if healthy work remains.

Operations use one shared provider cap **60**, one audit-study lease, native
dependencies and disjoint owners. Current Slurm QOS reports **64 CPUs per user**
and **32 per job**. The prior [CPU review](../../2026-09-11/trace-attack-defense-v3/cpu-resource-audit.md)
already reduced audits to eight CPUs and serial finalization/reporting to one,
while retaining producer requests where numerical tool peaks were not bounded.
No additional profile change is justified by this inventory. Future requests
must reflect actual workers/processes and stage workload, not copy producer
allocations into serial stages. Monitor compact status at coarse intervals;
do not restart a healthy job because a completion count is temporarily unchanged.

Only relevant paths are committed and pushed to `origin/aydan-red-team`, without
force. No extra hash, recovery framework, or general preflight gate was added.

## Queue 2 milestone

The [appendix-only comparison](queue2/README.md) has a completed nine-case selected-criterion diagnosis, 86 passing tests and native input checks. R1 retains only corrective appendices; R2 removes appendices while preserving selection history and ordinary learned-rule influence. Both use the saved canonical User v2.1 control. Dispatch and exact job state are recorded in the shared mission status.

### Queue 2 dispatch

10:09 EDT: execution `534e797` is running 18 fresh canonical User
assignments in jobs **10414481–10414486**, reusing the complete nine-case v2.1
control. Sol+Opus audit jobs **10414487–10414488** and comparison report
**10414489** wait on dependencies. Startup shows no assignment failures.
The [queue 2 report](queue2/README.md) records the complete criterion-level
diagnosis, tests, input reuse and exact scope. Item 3 can proceed independently.

## Queue 3 milestone

The [eight-cell feedback matrix](queue3/README.md) reuses nine compatible User
trace assignments and prepares 63 missing fixed/trace assignments plus nine
Score-only appendix-off assignments. Ninety-six tests and 24 native input checks
passed. Full, Semi, Score-only and User comparisons are within-policy trace minus
fixed; native Score-only trace includes a qualitative appendix when delivered.

### Queue 3 dispatch

10:32 EDT: execution `b97c4fd` owns 24 scoped producers
**10414549–10414572**, eight audits and collectors **10414594–10414596**.
The matrix reuses nine User trace cases, adds 63 missing matrix cases, and keeps
the nine-case score-only appendix-off supplement separate. Three Semi-fixed
producers have started; later waves await capacity/dependencies. Six unstarted
report jobs were consolidated after Slurm’s submission-count limit, preserving
all scientific jobs. See [the exact scope, jobs and progress](queue3/README.md).


## Queue7 current checkpoint — 12:07 EDT

The [Results45 extension record](queue7/README.md) fixes Full `attack_defense_v2.1` through the official nested45-task membership. Intended Full coverage is270 records:120 reused original20,60 for the added10 and90 for the final15. No new User winner or45-task outcome is claimed. The [saved coverage snapshot](queue7/checkpoint.json) records all18 completed R1/R2 trajectories and the remaining policy/audit work.

Results30 seed job10414853 sealed12/15 blocks; three missing-output failures were archived before one native missing-only recovery10415010. Lane10414854 continues independently. At12:04 EDT,16/30 added-ten seed blocks were sealed. Final-fifteen preparation10415017/10415018 is queued behind those owners under sourceaba77eb, with45 new shared starts intended. Treatment revisions and new heldout generation remain unlaunched pending the unresolved original-V2 versus committed-prompt authority question; old selected/development contents and completed20-task outcomes are preserved.

R1/R2 da-3-4 audits encountered permanent HTTP400 `Schema is too complex` requests; R1 also suffered Slurm preemption. Successful rubric/quality/RH records remain intact and permanent requests are not resampled. Eight tests verify a small private task-scoping change; independent remaining-task audits10415055/10415056 use native resume, then the existing Semi/Score-only/Full/User audit chain continues. The original report10414489 failed on incomplete coverage; there is no complete candidate decision yet.

Semi-fixed and Score-only-fixed each completed9/9 trajectories. Their native recovery returned incomplete on the same6/8 Opus rubric requests with bounded-attempt histories unchanged; other tasks and both sets of quality/RH records remain preserved. This is an incomplete evaluation, not permission to substitute an auditor or change output budgets. Subsequent policy comparisons continue independently.

[CPU accounting](queue6/resource-profile.md) supports4CPU producers,4CPU future audit recoveries with unchanged32 request workers, and1CPU serial collectors. Existing healthy jobs are not resized. No20-task Semi/Score-only expansion or dropout job is launched from incomplete evidence. The separate PaperBench session remains outside this session's ownership.


12:10 EDT correction: remaining-task audit dispatch10415055/10415056 exited in2s/1s **before provider dispatch**, because the new script used its own checkout's config path and native source validation rejected it. The checkout also includes later shared schema changes, so it is not a substitute for the original scientific runtime. These failed operational attempts are retained. The corrected launch uses the original534e797 library and original config paths; the small task-scoped driver reads the existing `RUBRIC_GEN_PROJECT_ROOT` setting. No completed record is rewritten and no new-schema judgment is mixed into this comparison.
