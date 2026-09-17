# RTT Result20 Babel/NAS8 staging

## Purpose and ownership

The current development split is:

- Local Mac Codex thread `codex://threads/01a09fd6-b336-7d63-a016-68524bb793c4`
  owns Dev3 method exploration and improvement.
- Babel does not perform independent method tuning. After Dev3 produces a clear
  positive signal, Babel will execute the promoted, committed method on Result20.
- Git commit, candidate/config identity, and the committed Dev3 report are the
  executable handoff. The thread URI is a coordination reference, not scientific
  provenance.

This document began as the pre-execution staging record. The authorized
Results20 validation has now completed from promoted candidate
`attack_defense_v2.1_execution_verified_proactive_provenance`; its authoritative
outcome is the [Results20 report](../../2026-09-17/trace-v21-execution-verified-provenance-result20/README.md).
The failed completion-pass Dev3 chain (`10454080`, OOM; downstream jobs
cancelled) remained retired and was not used as the Results20 source.

## Storage layout

All new large Result20 state will be persistent on NAS8:

| purpose | path |
|---|---|
| run ownership, logs, study, audit and reports | `/data/user_data/aydanh/rubric_gen/runs/rtt-result20-next/` |
| native live workspaces | `/data/user_data/aydanh/rubric_gen/live/rtt-result20-next/` |
| reconstructible runtime caches | `/data/user_data/aydanh/rubric_gen/cache/rtt-result20-next/` |
| future seeds, paraphrases and pretreatment inputs | `/data/user_data/aydanh/rubric_gen/pools/biomnibench/rtt-result20-next/` |
| canonical benchmark data | `/data/user_data/aydanh/rubric_gen/data/` |

Provider-free Slurm job `10472398` created and write-tested these roots on
`babel-w9-26`. It verified owner UID, absence of path symlinks and the NAS8 NFSv4
mount with `local_lock=none`. It did not populate scientific inputs, copy old run
data or make provider calls. Code, configuration and compact reports remain in
the home Git worktree.

At staging, NAS8 had 852,239,581,184 bytes (793.71 GiB) available, with
6,458,815 used inodes. This is sufficient headroom for a Result20-scale run.
NAS1 had only about 6.8 GiB available at the latest check and should not hold new
large experiment outputs.

## Concurrency and Slurm profile

The original staging policy enforced:

- aggregate provider concurrency: **60**;
- audit request concurrency within `detect`: **60 total**;
- simultaneously active independent audit studies: **1**;
- one shared cross-process/node capacity namespace.

The existing capacity seals were also inspected directly: the provider namespace
contains 60 slot files with capacity 60, and the audit namespace contains one
slot file with capacity 1. Provider-free Slurm test `10472417` then passed 16/16
focused runtime-capacity and scale-dispatch tests in 9.28 seconds. No capacity
namespace was replaced or split and no provider call was made.

The approved Results20 execution supersedes the combined audit ceiling while
leaving revision behavior unchanged. Current `preempt_cpu_qos` limits are 64
CPUs per user and 32 CPUs per job, with 20 running jobs and 50 submitted jobs
per user. Seed/paraphrase/revision use the reviewed aggregate ceiling of 60;
the Sol+Opus audit uses provider-partitioned concurrency:

```bash
uv run rubric-gen seed --experiment <result20.yaml> --max-concurrency 60
uv run rubric-gen paraphrase --experiment <result20.yaml> --max-concurrency 60
uv run rubric-gen revise --experiment <result20.yaml> --max-concurrency 60 --resume
uv run rubric-gen detect --experiment <result20.yaml> --max-concurrency 120 --resume
```

`audit_studies=1` is a lease on the number of distinct audit studies/owners that
may run simultaneously. It does **not** set the number of judgment workers to
one. The one active `detect` owner has independent 60-slot partitions for OpenAI
Sol and Anthropic Opus, for at most 120 audit requests total. Sol and Opus jobs
are submitted together and neither provider can occupy the other's allocation.
The ordinary `provider` pool remains capped at 60 for revision and all non-audit
calls. Both producer and audit use 32 allocated CPUs; provider request
concurrency and CPU allocation remain distinct. Recovery uses native missing-only
resume and must preserve completed assignments and judgments.

Provider-free Results20 preflight `10477780` validated the final execution
configuration: 120 assignments, ordinary provider capacity 60, one audit owner,
and independent 60-slot OpenAI and Anthropic audit partitions (120 total). The
test dispatched 60 simulated requests in each audit partition concurrently and
made no provider call.

Disposable per-job temporary files should use
`/scratch/job_tmp/$SLURM_JOB_ID`; persistent study, live, audit and ownership
records stay in the NAS8 roots above. This avoids placing high-churn temporary
files on NAS8 without weakening native resume.

This is a maximum, not a requirement that 60 calls remain active continuously.
The launcher must record actual workers, process/thread counts, HTTP concurrency,
memory and provider occupancy. It should reduce only the affected stage if
measured pressure or provider limits require it, without changing scientific
semantics.

## Executed promotion handoff

The promoted run used revision job `10478084` and one provider-partitioned audit
owner, job `10479921`, followed by missing-only recovery `10480179`. Revision
remained aggregate-60 with internal RTT fanout four. Audit reached 60 concurrent
Sol requests and 60 concurrent Opus requests, for 120 total; it did not retain
the older shared-total-60 assumption. Assignment coverage is 120/120 and the
final Sol+Opus audit contains 3,678/3,678 semantic judgments.

The executed handoff followed these checks:

1. fetch the Mac-promoted commit from `origin/aydan-red-team`;
2. verify the committed Dev3 report identifies a clear positive signal and exact
   candidate/config;
3. create a new isolated worktree at that commit and freeze it during execution;
4. instantiate Result20 configuration under the NAS8 paths above, preserving the
   official task membership, models, solver/simulator, judge definitions and seed
   policy;
5. validate task inputs, writable output roots, 60-slot revision admission, one
   audit-study lease, `detect --max-concurrency 120`, independent Sol-60 and
   Opus-60 dispatch, native resume and the exact missing audit scope;
6. run the minimum representative same-route smoke only if the runtime/provider
   path changed;
7. launch the single intended Result20 producer, then the complete Sol+Opus audit
   with missing-only recovery.

The Result20 run is validation of the promoted Dev3 method, not another tuning
loop. It must not start from uncommitted Mac state, the retired blocked goal, or
historical partial outputs.

The legacy Codex goal object remains marked `blocked` because the goal API has no
delete/abandon operation and the underlying OOM-stopped experiment was not
scientifically complete. It is operationally retired by this plan and must not be
resumed or treated as current authorization.
