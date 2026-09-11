# Runtime reliability and throughput cleanup

Runtime implementation owner: `runtime-throughput-cleanup`, then a separate
`runtime-throughput-final` checkout for final fixes while the live source stayed
frozen. All diagnostics use allocation **10398213**, `babel-l9-20`, 8 CPUs/256 GiB,
and the existing locked Python 3.12.13 environment. No new Results20, input
regeneration, model/account change, scientific setting change, or capacity-policy
change. The shared limits remain **60 provider reservations and one audit study**.

## Incidents, fixes, and evidence

| Priority / actual failure | Owner and common change | Cost and verification |
|---|---|---|
| P0: imported producer ID rejected by all four direct windows | `source_resolution.py`, `evaluation/{targets,evidence,direct}.py`: resolve each assignment's documented producer, config, source, and consumer membership once | Historical four-window failure was structural, not a timeout. Normal 120-assignment resume now accepts all four panels, with no adapter or generation. |
| P0: 120-row subset mistaken for a 240-row full ledger; two-row recovery ledger assumed complete | `execution_scope.py`, shared assembly, validation and report readers retain the full ledger and select its declared scope | 10397848/10397864 failed; corrected historical validator 10397939 passed 120/120 in 32s. Integration uses 240 rows, 118 imports + two native recoveries, and 120 pending static rows. |
| P0: permanent two-worker recovery ceiling | Active `paperbench_launch.py:152`: `workers = 2 if args.recovery else 60`; shared launcher's subsequent-attempt ceiling also removed for future launches | Fixed 18-assignment workload: 2.827s at two workers, 1.553s at four, 0.933s at eight. The earlier 1–8 occupied global slots preceded the later Bio audit contention. |
| P0: serial audit suite; naive threaded stages would reacquire the sole parent-owned audit lease | `commands.run_detect`, `runtime/audit_execution.py`, internal `run_prepared` methods: one output owner, one global admission, six coordinators, one bounded provider-fair executor | Ownership/nesting tests complete without deadlock and preserve the global cap; a stalled provider leaves a worker for the other provider. Live measurements below distinguish admission wait from execution. |
| P0: saved neutral-policy request rejected | `paraphrase_validation.py`: exact criterion-specific attempt-envelope replay | All 51 saved PaperBench requests match configured semantic inputs. Criterion 014, attempt 2 has the documented schema repair. The private checker keyed failures by attempt number alone, confusing criteria; delay was not measured. |
| P1: serial source loading before completed futures were drained | `detection/runner.py`, shared evidence cache: bounded preparation, immediate ready-job dispatch, explicit phases | Controlled identical 18-source/36-request work, plotting startup equalized: first dispatch 1.456s → 0.086s; wall time 1.658s → 0.595s. |
| P1: healthy full-rubric streams killed; Anthropic criterion schema/cardinality failures | Retain `fe1c87d3`; durable raw response before decoding/publication; terminal-stream checks | Prior census attributed about 90 aggregate request-minutes to failed calls, not cohort wall time. Controlled streams survive 480s of healthy activity, time out on inactivity, and reject truncation; large indexed criterion coverage passes. |
| P1: startup/preemption or post-save NFS cleanup reported as scientific failure | Existing owned-session retry/checkpoint rules; completed-output cleanup records/quarantines only the owned tree | Eight real app servers started successfully; fault injection covers startup failure, preemption, attempt exhaustion and EBUSY cleanup after durable completion. No claim of eliminating cluster/provider failures. |

Recovery 10397636's **47m50s completed two real revisions**; this was useful work,
not 47m50s of timeout waste. Historical audit 10397985 completed 2,108 rubric and
600 free-score judgments; the latter took 3m24s and rubric scoring was almost
finished at 12m18s. Adapter/relaunch operator delay is unknown. These are wall
times; the census's aggregate request time is not additive wall time.

## Source ownership and scientific compatibility

The full repaired Bio ledger has **240 condition rows**. Its declared execution
scope has **120 trace assignments**, comprising **118 imported v2 producers and
two native v2.1 recoveries**. The other 120 static rows remain pending; frozen
static comparison evidence stays separately reused. One direct window has
**120 × two auditors = 240 logical judgments**, with potentially more physical
requests under the unchanged chunking protocol.

`resolve_study_sources` validates every selected row against its own import
receipt, producer config/ledger/manifest/state, task, replicate, solver,
condition and source tree. Native rows still require the consumer's producer
identity. It does not accept a cohort-wide whitelist. Rubric, absolute,
pairwise, all four direct windows, completed-revision resume and coverage/report
readers use this selection and resolution. Ordinary resume also retains
`execution_assignment_ids` when the caller does not supply a new selection.

Relocation is an exact read-time mapping backed by existing import metadata.
Producer IDs and scientific files are not rewritten. Future assembly copies
mutable bookkeeping; the archived ad hoc repair scripts remain historical
evidence. Inspection found all **758** rewritten consumer status files on
different inodes from their producer counterparts, and all 758 producer contents
matched the repair receipt's original digests. The repair used atomic
replacement. **No producer mutation was found in this inspected set**; this is
not a claim about uninspected history.

Compatible saved judgments retain their actual original implementation identity.
Resume checks scientific inputs, role bindings, model/settings, request/evidence,
existing artifact digests and raw response replay before reuse. Direct runtime
compatibility additionally checks the recorded source tree and unchanged
scientific request modules. A genuine role/instruction/rubric/model/source
mismatch remains an error; no metadata is fabricated and no seed, paraphrase,
completed revision or known compatible judgment is regenerated to change a code
fingerprint.

All stage-family source/scope/window checks happen before generation in the same
native invocation. Prepared objects are reused. Full request validation still
precedes its own dispatch; complete cached panels do not call provider token
counters. A completed audit retains output exclusion but does not need global
generation admission merely to validate and publish saved results.

## Scheduling, retries, and observability

Assignment and request workers are separate runtime settings. The native
`StudyRunner` was already completion-driven; the observed two-worker bottleneck
was the launcher configuration, not evidence of a two-item batch scheduler.
Submission is now explicitly bounded and refills on completion, while turns
within each assignment retain their sequential workspace/session.

Future profiles: **Dev3 4 or 8 CPUs/workers**, **Results20 32 CPUs/workers**,
and **inspection 1 CPU / four request workers**, with the 256 GiB request retained.
Eight is the initial Dev3 choice; there is no evidence here supporting 16.
One global reservation covers an active Codex session/turn, not its invisible
internal agent API calls. Direct HTTP and token-count operations have their own
reservations. Existing hosted-Anthropic token-window admission remains in force;
this is not a new universal token meter for all SDK calls. Disk preparation,
inactive token waits and retry backoff do not hold provider slots.

The suite's provider-fair executor bounds all stage requests together and keeps
at least one worker available to the other configured provider. A provider's
authentication, billing or invalid-config failure stops its affected queued
dispatch; unrelated providers can finish. Standalone stages still acquire their
normal ownership. The one-study policy is retained: older participating
worktrees remain active, so there has been no compatible, quiescent boundary for
a two-study policy change.

Existing configured attempt budgets persist across resume. SDK retry
multiplication is disabled on owned paths. 429/529, connection/inactivity failures
and documented startup failures follow bounded typed retry, Retry-After and
existing cooldown rules; structural mismatch and valid negative scientific
verdicts do not. Each direct physical chunk and synthesis records intent,
attempt number, terminal response and publication separately. An ambiguous
disconnect is recorded as unknown completion, consuming an attempt; it is not
claimed to be exactly-once remote execution. Known completed chunks and raw
full-rubric/free-score responses survive later decode/publication failure.

Timeouts remain distinct: connect/read/pool settings belong to transport;
**300s read inactivity** is not a total response deadline; the full-rubric judge
subprocess retains its **3,600s** outer limit; solver sessions retain **7,200s**.
Direct RH keeps its scientific protocol, without the indexed full-rubric format.
Temporary cleanup after durable validated output is separately recorded; unknown
roots, active locks and other owners' workspaces are never removed.

The existing interval status now includes selected/completed/failed/pending and
ready/blocked assignments, configured/active workers and limit source, job-owned
versus global reservations, active operations, queue/provider state, audit/source
phase elapsed time, lease/token/backoff waits, last successful unit/rate,
failure category/action and uncertain remaining estimate. A final sample marks
completion even when the child exits between intervals. One owning launcher
orchestrates native dependencies/resume/reporting; child completion does not
wait for the reporting interval, and no logcheck Slurm jobs are needed.
Audit admission has its own phase, followed by execution and complete/incomplete;
cached evidence records separately measure file reads, decoding and parsing
without changing request metadata or scientific cache identities.

## Controlled comparisons and regressions

| Identical workload | Before | After | Interpretation |
|---|---:|---:|---|
| Native 18 assignments × three sequential 0.1s turns | Two workers: 2.827186s | Four: 1.553315s; eight: 0.933077s | **3.03×** two-to-eight; 1.66× four-to-eight; observed peak workers exactly 2/4/8 |
| First assignment dispatch, same workload | 0.01048s | Four: 0.004855s; eight: 0.004828s | Prompt refill; no wait for a slow pair |
| 18 sources × 80ms preparation, 36 × 20ms requests | Serial loading boundary: 1.658488s | Bounded pipeline: 0.594634s | **2.79×**, same 18 reads and 36 requests |
| First dispatch, same preparation workload | 1.456035s | 0.085645s | **17.0×** lower preparation barrier |

These use controlled service times, not a second slow live cohort. A repeat
scheduler measurement under concurrent startup was 2.792/1.535/0.916s, consistent
with the first comparison. No workload was shrunk to meet a speed target.
Duplicate known successful dispatches are zero in missing-only and second-resume
fixtures.

Both preparation variants read 3,032 serialized source-payload bytes and dispatch
92,140 serialized request bytes, with peak eight active requests. Aggregate
source preparation was 1.4415s/1.4423s; last generation completed at
1.5754s/0.5174s; post-generation publication/plotting took 0.0831s/0.0773s.
These byte counts describe controlled payloads, not NFS traffic. The initial
2.416s/0.597s comparison included first-use plotting overhead in the serial arm;
the table uses the rerun with plotting initialized before both variants.

The focused suite exercises the actual native source selection, StudyRunner,
detect/resume, stage execution and publication paths with captured record/schema
shapes and controlled providers. It covers wrong per-assignment mappings,
hard-link isolation, candidate-local duplicate-title rejection without swallowing
programmer errors, deterministic stage errors before generation, mixed completed
and missing panels, persistent bounded retries, raw-save/publication boundaries,
provider fairness, active parent audit ownership and completed-audit admission.

The broad compute suite produced **1,014 passed, two skipped and four failures**
in 206.43s. The four failures concern unchanged historical V1 identity assertions,
two experiment-matrix fixtures expecting pre-existing home rather than approved
NFS paths, and the unchanged MALT dataset prerequisite/error-order assertion.
They are not hidden or repaired by weakening historical checks. Subsequent
focused changed-path runs: 52 direct tests passed, 27 ownership/scope tests passed,
39 streaming tests passed, and 110 completed-admission/experiment tests passed.
Final scope/status/launcher/experiment checks passed **120 tests in 23.97s**;
the capacity tests passed **12 in 5.65s**.
The phase checks passed six tests; evidence/monitor checks passed 55 in 16.41s.

## Real compute measurements and validation

No operating-system cache flush was performed. “First invocation” is not a
cold-mount claim.

| Measured work | Result |
|---|---|
| Initial real NFS resolver, 240 full rows / 120 selected / 118 imports | 0.1814s; existing cache state |
| Separate all-window preparation of the real 120 | Scope 1.1608s; window-boundary checks 64.9535s; render 480 window inputs 18.8226s |
| Reads for that preparation | 995 trajectory reads / 220,339,988 bytes; 113,091,493 rendered characters |
| Re-render within the same invocation | 0.007738s; zero additional trajectory reads |
| First normal complete 120-assignment resume, source `5c15bbcf` | 85.3549s preparation; all six stages reused; zero provider/token-count operations |
| Second normal complete resume, same source, clean launch receipt | 38.8104s preparation; all six stages reused; zero provider/token-count operations |
| Final launcher/status check, source `1194cb4`, clean receipt | 46.0865s total including monitoring; exit zero, terminal `finished=true`, all 120 complete and zero owned reservations |
| Eight real Codex app-server startups, no model turns | All ready in 6.31s; total including closure 7.7755s; zero startup errors |
| Startup process-tree measurements | Peak 17 processes, 1,207,324 KiB sampled RSS, 0.974 sampled CPU cores; cgroup peak 1,307,193,344 bytes, no OOM events |

Both normal completed-audit resumes verified **2,108 rubric + 360 absolute +
240 pairwise + 960 direct = 3,668** saved judgments and returned zero while the
old PaperBench owner still held global audit admission. No private consumer
adapter was imported. First invocation source/scope checks took 4.5100s; scoring
preparation took 11.876s; saved-response replay took 68.969s. Second invocation:
4.3292s, 6.5906s and 27.8908s respectively. Each cached direct stage then took
under 0.33s. The first launch receipt captured a transient NFS Git-index dirty
status; subsequent compute inspection found no diff, and the second receipt was
clean. That original receipt is preserved.

These measurements meet the under-five-minute warm preparation target for this
cohort. They do not establish a two-hour Results20 completion bound or eight
simultaneously working solver sessions' maximum memory.

The separately pinned runtime-only Bio cohort contains the first task/replicate's
two trace conditions, reusing their completed revisions. Its full ledger remains
240 rows, with exactly two declared selected assignments and 238 pending rows.
Its normally required audit is separate from published scientific results.
The selection was recorded before generation; no scientific outcome determines
repetition. The current live owner uses frozen `5c15bbcf`; its first shared
source preparation took 1.0724s.

**Live audit completion/coverage and admission/execution/resource measurements
will be filled from the owning invocation before publication.** An earlier
owned, zero-call waiting invocation was stopped at a safe boundary to install the
completed-resume admission fix; it had spent 397.1459s waiting. The active
PaperBench source and owner were not changed. The replacement bounded live owner
waits normally for that owner's existing audit lease.

## Source versions, commands, and adoption

Reviewed `fe1c87d3b245f80c745fd2b94452ed287b5aab21` is retained.
Implementation commits are `19082d6` (common runtime), `91ade9e` (durable
resume/ownership/terminal responses), and `5c15bbc` (completed-audit admission and
saved token-plan reuse). Merge `d783505` preserved newer published remote history,
including `c43a921`, `5879c76` and `5389caf`; those incoming changes were inspected
before integration. Commit `1f67355` preserves declared subset membership and
terminal runtime status. Active PaperBench 10397534 used its older `4c6` source, so its
running requests did not acquire the new timeout implementation merely because
the fix existed on origin.

Changed code is in:

- `submission_revision/{source_resolution,execution_scope,study,study_validation*,commands,store,seeds,controller_setup}.py` (using the existing `study_layout` resolver);
- `submission_revision/evaluation/{targets,evidence,evidence_ledger,direct,runner,resume,jobs,rubric_score,rubric_judge,score_execution}.py`;
- `detection/{runner,job_runner}.py`, `runtime/{audit_execution,capacity,failures,provider_streams,agents/codex_sessions}.py`;
- owned cleanup in `submission_revision/{artifacts,controller,judge,judging/executor}.py`, recorded-input replay in `paraphrase_validation.py`, `paraphrases.py`, `trace_defense_v2*.py` and `judging/discovery.py`;
- `cli.py`, `scripts/babel/{experiment.py,experiment.sbatch,launch.py,dev3.sbatch,monitor.py}`, `scripts/diagnostics/check_audit_coverage.py`, the historical consumer assembler's shared call, relevant tests, README, Babel setup and architecture.

Exact tested commands are the normal resource-profile launcher and missing-only
resume, from the pinned W checkout, inside allocation 10398213 with
`PYTHONPATH=$PWD/src:$PWD/scripts/babel` and
`RUBRIC_GEN_PROJECT_ROOT=$PWD`:

```bash
/data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python scripts/babel/experiment.py --profile dev3-8 detect --experiment /home/aydanh/repos/rubric_gen/runs/babel-code/runtime-throughput-cleanup/runs/runtime-throughput-validation-20260911/biomnibench.yaml
/data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602/bin/python scripts/babel/experiment.py --profile dev3-8 detect --experiment /home/aydanh/repos/rubric_gen/runs/babel-code/runtime-throughput-cleanup/runs/runtime-throughput-validation-20260911/biomnibench.yaml --resume
```

The first command owns this fixed output already; subsequent use is the second
command. Future independently approved runs submit the same profile through
`scripts/babel/experiment.sbatch` from a fresh pinned checkout of the published
branch. Use `run` for the complete authorized seed/paraphrase/revise/detect DAG or
`revise` for revision-only work, with the approved YAML. Do not launch a formerly
active experiment-specific worktree because its branch name looks current:
check the launcher receipt's absolute source, commit and tracked source status.
No custom assemble/validate/direct-recovery wrapper is part of future resume.

Small invocation receipts, status and logs are in the W checkout's
`runs/runtime-10398213-*`; full runtime-only outputs and the preselected source
receipt are under
`/data/user_data/aydanh/rubric_gen/runs/runtime-throughput-validation-20260911/`.
The original completed consumer remains at its existing trace-v2.1 result20
location. `EXPERIMENT_RUNS.md` records exact owners and paths. No secrets, model
session files or large evidence are committed.

Remaining limits: provider latency/overload, ambiguous disconnects, cluster
preemption and NFS stalls remain possible. Permanent provider failures stop
affected work with saved progress and a missing-work list. Single-study admission
can still dominate waiting until compatible owners reach a coordinated boundary;
this change improves concurrency within that boundary rather than raising the
cap. Historical scientific go/no-go decisions, including PaperBench's
manipulation decision, remain binding.
