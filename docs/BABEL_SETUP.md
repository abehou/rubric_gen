# Babel runtime profiles — 2026-09-11

Use `scripts/babel/experiment.py` around the normal `run`, `revise`, or `detect`
entrypoint, from the pinned patched checkout. `experiment.sbatch` supplies the
locked Python 3.12 compute environment and persistent NFS caches/workspaces without
loading optional login-shell configuration. The profiles are `dev3-4` (4 CPUs / 4
workers), `dev3-8` (8 / 8), `results20` (32 / 32), and `inspection` (1 CPU / 4 HTTP
workers, detection only). Override sbatch CPUs to match the chosen profile; retain
256G for experiments. Aggregate provider reservations remain 60 and audit studies
remain one. Never replace the source of an active owner.

Normal `detect --resume` resolves documented producers for every selected source,
prepares all four direct windows and scoring families before generation, and
reuses compatible successful semantic judgments. Runtime source changes preserve
original response provenance; scientific input/model/role mismatches still fail.
A per-output lock and the shared audit lease belong to one suite coordinator.
The launch directory contains `launch.json`, `status.json`, `metrics.jsonl`,
`execution.log`, and terminal `result.json`. See the
[implementation and measured results](reports/2026-09-11/runtime-reliability/runtime-throughput-cleanup.md)
for the exact tested commands and limits.

The remaining sections preserve the September 7–8 execution record and its
historical dispatcher. Their four-CPU/60-worker settings and source-freeze recovery
instructions are superseded by the profiles above for future runtime invocations.

## Archived Babel dev3 execution — 2026-09-07

Current execution status is owned by [EXPERIMENT_RUNS.md](../EXPERIMENT_RUNS.md) and the
[checkpoint report](../investigation/babel-overnight-20260907/MORNING_REPORT.md).
The user explicitly authorized configured provider payloads;real Sol/Opus dev3 work
has passed the Babel gates. Gemini remains blocked by depleted prepaid credits.
Result20 requires the intended stable user-baseline and quality-preserving policy
pattern on dev3;earlier immediate wiring-only scale-up instructions are superseded.
Non-provider gates10348599/10348914 and cross-node shared60 test10349478 are complete.

`general` rejects CPU-only jobs through a site plugin. The validated CPU-only path
uses the Slurm default account, partition preempt, QoS preempt_cpu_qos. Future jobs request 4 CPUs/256 GiB/48h; historical
validated jobs requested 32 CPUs.
The [Mac handoff](BABEL_HANDOFF.md) and all completed artifacts remain historical evidence.

## Recovered scientific state

The shared feedback boundary formerly displayed selected-rubric text alongside
master-rubric reward and reasons. The corrected controller binds selected text,
reward, levels, reasons, simulator input and resumed hashes to the selected base
judgment (`selected-base-plus-active-penalties-v1`); dynamic rewards add only active
learned penalties. Master measurements remain independent. Acceptance covered six
saved judgments / 42 criterion bindings and both feedback-mode checkpoint smokes.
See [validated prerequisite](../investigation/selected-reference-wiring-20260907/VALIDATED_RESULT.md).

The post-fix static comparison completed 24 assignments and 672 Sol/Opus audit
records (192 direct, 360 rubric, 72 absolute, 48 pairwise), with no final gaps.
Both arms had corrected wiring, so this isolates the neutral prompt contrast,
not the causal effect of repairing wiring. Full-feedback selected−holdout was
+2.81 control versus −1.61 neutral; control disagreed across Sol (−1.83) and
Opus (+7.44). Final-artifact RH was zero throughout. Primary trajectory any-detect
was control full/simulator 50%/33.33%, neutral 16.67%/33.33%, confined to da-11-1.
Small mean quality gains did not prevent an Opus simulator decline from 48 to 27.
Keep the fix, do not adopt neutral, and leave the static baseline unfrozen.
[Results and interpretation](../investigation/static-neutral-20260907/REPORT.md).

Keep frozen models,evaluators,thresholds and existing dev3 tasks/seeds. Installing
additional scientific packages would change the environment;match Linux conditions
and treat Mac results as historical comparisons rather than a clean environment contrast.
The latest baseline-first scope is in [EXPERIMENT_PLAN.md](../EXPERIMENT_PLAN.md).

## Portable inputs and authentic resume

New paraphrase pools store `tasks_dir: "."` and task-relative rubric references,
for example `da-3-4/tests/rubric.txt`. Validation resolves the actual master through
the current experiment's task directory, checks its content hash, and checks variant
hashes, metadata, generation identity, criterion IDs, weights and semantic constraints.

Transferred absolute references are retained as **origin provenance**, never opened
as local paths. Manifest records and variant metadata must agree with that origin and
the locally validated content. This changes reference resolution, not rubric content
or treatment. Historical absolute-origin pools are read-only: the paraphrase runner
validates them and returns without rewriting or extending them. No manifest, hash,
compatibility marker, symlink or Mac directory is fabricated.

Completed revision studies still require their original execution identity, including
absolute task/seed/rubric paths. They cannot resume on Babel. The new YAMLs use paths
relative to their own directory and fresh `runs/babel-dev3-20260907` output roots.
New runs resume only on the same Babel checkout/output namespace with authentic live
workspace/session state. Native completed-artifact validation remains in the workflow.
The dispatcher also freezes source, launch scripts, policy, project metadata, lockfile, YAMLs, selected seed manifests and
pool files; drift rejects resume instead of rewriting receipts. A deliberate future
code/intervention change needs a newly named study/config and namespace.

## Environment and resources

`dev3.sbatch` requests exactly:

```text
--partition=preempt --qos=preempt_cpu_qos
--nodes=1 --ntasks=1 --cpus-per-task=4 --mem=256G
--time=2-00:00:00 --no-requeue --signal=B:TERM@300
```

The 2026-09-08 CPU-only resource revision keeps one node/task and shared aggregate
concurrency 60. Live `sacctmgr` reports `preempt_cpu_qos MaxTRESPU=cpu=64`;
two 32-CPU jobs consumed that entire quota. At elapsed 54m35s, `sstat AveCPU`
was 2h21m31s and 42m24s for jobs10356519/10356523, approximately 2.59 and
0.78 CPU cores on average. Four CPUs is the smallest conservative initial request
above the heavier observed mean; it permits up to 16 such jobs by CPU quota,
subject to memory/node availability. This is an estimate, not a validated
four-CPU throughput result. Keep 256 GiB memory for now.

Worker pools use threads waiting for remote APIs, not 60 CPU processes. Solver
subprocesses can perform local numerical work, so one or two CPUs could throttle
those phases. Batch launchers cap OpenMP, OpenBLAS, MKL, NumExpr, vecLib and Rayon
threads at one and disable tokenizer parallelism. Solver shell configuration
already caps OpenMP/OpenBLAS/vecLib; its filtered environment does not guarantee
inheritance of every outer variable. No scientific source or shell policy changed.
Monitor allocated-CPU saturation and comparable throughput on the next new job;
raise CPUs if sustained utilization exceeds 90% or CPU contention slows work,
without reducing API concurrency solely because fewer CPUs were requested.

Running jobs and frozen checkouts remain immutable. For a future submission from
an existing frozen checkout, use `sbatch --cpus-per-task=4 ...` and record that
explicit resource override; its archived launcher may still label its default
request as 32, while `SLURM_CPUS_PER_TASK` records the actual request. Do not edit
its source seal. Newly prepared checkouts should use the updated launchers.
The currently pending one-CPU backup/analysis jobs already have small requests;
they remain quota-blocked until a running allocation releases CPUs.

CPU only; inspected execution uses hosted models and CPU scientific subprocesses,
with no local model/GPU requirement. CPU-only scheduling and runtime passed on actual
compute nodes; real Sol/Opus provider connectivity and end-to-end dev3 execution have passed.

The batch script explicitly creates a Python3.12 virtualenv before
`uv sync --frozen --python /usr/bin/python3.12`, avoiding the system install scheme
on some nodes. Its node-local name includes lockfile, checkout and job identity; it exports the absolute checkout `src` as
`PYTHONPATH`. Keep the locked `openai-codex==0.147.0` bundled Linux binary and null
executable config. Do not substitute a global Codex binary or add scientific packages.
`uv` and Python 3.12 must be available on the compute node, with package/cache access
for frozen sync. Both repository and node-local frozen environments were installed
successfully during preparation; node-local imports avoid observed NFS overhead.

The Python dispatcher loads only OPENAI_API_KEY and ANTHROPIC_API_KEY from the trusted
mode-0600 `.env.local`, without sourcing shell code or recording values. Do not enable
shell tracing. The completed live smoke10351863 verified Sol/Opus connectivity,Codex authentication
and compute-node sandbox support;continue monitoring rates and failures for each job.

Live workspaces and authentic Codex session state use the persistent, private path
`/home/aydanh/rubric-gen-live/dev3`, outside the repository as required by the runtime.
The batch script creates it with umask 077. Keep it across allocations and resumes;
node-local uv caches/environments may be regenerated. Do not delete live state or the
shared capacity directory while work is active. Scientific commands retain existing
network isolation, Agg plotting and one-thread numerical defaults.

## Shared admission control

[config/runtime.json](../config/runtime.json) fixes a single coordination root:
`/home/aydanh/repos/rubric_gen/runs/.runtime-babel`. All production processes read this
policy; local worker limits cannot override it. Keep this canonical root for every
Babel checkout/job. It is deployment configuration, not a scientific input reference.
The observed filesystem is NFS4.2 with `local_lock=none`, so file locks are server
coordinated; the launcher verifies these mount properties before loading credentials. Do not move
coordination to node-local scratch or a local-lock-only mount.

| Control | Enforcement |
| --- | --- |
| Aggregate provider work | `runtime/capacity.py`: 60 numbered kernel `flock` slots shared by processes and nodes; a sealed pool capacity rejects mismatched budgets. A slot covers a complete synchronous operation, including its retries. |
| Solver | `runtime/agents/codex_sessions.py`: complete start/resume turns; `runtime/agents/sessions.py`: alternate CLI session turns; `runtime/agents/runners.py`: subprocess lifetime. Assignment pools remain in `submission_revision/study.py`. |
| Optimizer judge | `submission_revision/judge.py`: parent holds a slot through grader subprocess and retries; frozen scoring-engine source and hashes are unchanged. |
| Hosted audit/simulator/induction | `runtime/llm.py`: generation and remote token counting use the same 60 slots. `evaluation/rubric_judge.py` and `evolution_provider.py` gate their direct provider calls too. Nested synchronous calls reuse their outer lease. |
| Audit study | `submission_revision/commands.py`: one separate audit lease spans all detect stages; detection/evaluation runners also take it for standalone stage recovery. Requests inside the study still consume the shared 60-slot provider budget. |
| Other simultaneously active workflows | Original-rubric CLI judging takes the audit lease. Harvey audit stages share it; its evaluator reserves the declared child judge parallelism from the same provider pool before subprocess execution, with no second child budget. |
| Recovery | Same production admission, local workers 2 with launcher `--recovery`; no independent recovery budget. |

Kernel locks release when owners exit; there is no guessed PID expiry or TTL that
could admit replacements while an operation remains alive. Slurm cancellation kills
child process groups, escalating after 120 seconds. The limiter bounds admitted client
operations; it cannot cancel already accepted remote computation after a network or
machine failure. Do not use archived Mac dispatchers as Babel launchers.

## Provider token pacing (2026-09-08)

Keep `max_concurrency=60` and the shared 60-slot ceiling. Anthropic requests also
pass through one shared **8,000,000 input-token / 60-second rolling window** in
`runtime/capacity.py`, below the observed 10M organization limit. Token counting
uses the configured provider integration; waiting requests release provider slots.
A new window starts with a 60-second warm-up, and HTTP 429 imposes a shared cooldown
of at least 60 seconds (or the longer provider retry delay). All Babel jobs must use
the same coordination root; do not give each study its own token budget.

The audit-only recovery `10362935` passed in 6m24s with no sampled HTTP failures;
peak sampled occupancy was 44 slots. This is successful recovery evidence, not yet
a sustained 60-call fresh-panel stress test. Track successful judgments/minute,
429s, tail latency and token-wait time before raising the token budget. Other
projects sharing the organization can consume the remaining headroom. See the
[maintained issue guide](reports/2026-09-08/experiment-issues.md) for exact failures,
acceptance evidence and outstanding automation work.

## Historical accepted control commands

These control commands already ran successfully. Do not duplicate their completed cells;
use the current owner and next action in EXPERIMENT_RUNS.md for continued work.
The original smoke command from `/home/aydanh/repos/rubric_gen` was:

```bash
sbatch scripts/babel/dev3.sbatch smoke
```

Smoke uses the unmodified scientific control on da-3-4: three replicates × full and
simulator feedback = six assignments, solver workers 2, audit workers 8. The native
schema requires at least three replicates, so smoke does not invent a one-replicate
experiment. It uses the same config/output as full and will be reused, not regenerated.

After successful smoke and review of its runtime metrics:

```bash
sbatch scripts/babel/dev3.sbatch full
```

Full uses both `experiments/babel/biomnibench-dev3-control-{da-3-4,da-11-1}.yaml`:
12 assignments in total, of which six are the completed smoke. Solver/audit worker
limits are 60; the two revision studies may overlap, but audit studies serialize.
The six assignments per task limit actual solver parallelism to at most 12 across
both tasks. Audit stages can expose 60-way capacity. No larger task population is
added just to saturate workers. This full-dev3 mode includes only the two-task control.
Full requires a successful smoke receipt with matching runtime and shared inputs.

Historical prepared Result20 command, **not the current next action**. The current
user instruction requires a stable user-setting baseline and quality-preserving
dynamic/red-team reduction on dev3, followed by a separately frozen matched config.
The wiring-only config below does not satisfy that gate; see
[the current scale-up protocol](../investigation/babel-overnight-20260907/RESULT20_PROTOCOL.md).

```bash
sbatch --parsable --job-name=rubric-result20 scripts/babel/dev3.sbatch result20
```

This selects `experiments/babel/biomnibench-result20-wiring-control.yaml`,120 assignments
(20 tasks ×3 replicates ×2 static feedback modes), retaining the corrected control's
randomization seed, models, prompts, variant roles and measurements. It generates
missing native seeds/paraphrases under `runs/babel-result20-wiring-20260907`, validates
them, then revises/audits. Resume repeats those native stages and preserves valid work.
Use `--workers N --audit-workers N` to select evidence-supported limits1–60; recovery
restricts both to1–2. The global policy remains60 regardless of local limits.

Missing-work recovery, after the previous allocation/owner exits:

```bash
sbatch scripts/babel/dev3.sbatch full --recovery
# Or smoke --recovery if the first smoke was interrupted.
```

The smoke/full modes invoke the installed `rubric-gen revise|detect --experiment <yaml>
--max-concurrency <limit> --resume`; revision must succeed before auditing. Ordinary
same-profile resubmission also uses native resume. No `--restart`, seed or paraphrase
generation occurs in smoke/full. Result20 separately prepares native seeds and paraphrases. The batch job receives TERM five minutes before
walltime; it stops new stages and terminates children, preserving checkpoint evidence.

Non-scientific acceptance, with no `.env.local` load or provider calls:

```bash
PYTHONPATH="$PWD/src" PYTHONDONTWRITEBYTECODE=1 /tmp/rubric-gen-babel-verify-venv/bin/python scripts/babel/check.py
```

This validates the six transferred seeds/fixed pools and runs 72 fake operations
across three processes/72 threads against an isolated namespace on the shared
filesystem. It requires peak admitted work exactly 60 and all 72 completions, and
removes its temporary coordination files. This private check is not a public CLI mode.

## Receipts and runtime acceptance

Results: `runs/babel-dev3-20260907/<task>/{study,audit}/{experiment_id}`.
Dispatcher receipts: `runs/babel-dev3-20260907/dispatcher-{smoke,full}/<jobid>-<UTC>/`.
Each records job ID, hostname, requested and allocated resources, Python/commit,
source/config/input hashes, command arrays, outputs, worker limits, shared policy,
resume/recovery flags and persistent live root. Each child has a separate log.
`result.json` records stage exits and source preservation; `runtime-identity.json`
protects future resume. Slurm stdout is `runs/slurm-rubric-dev3-<jobid>.out`.

`metrics.jsonl` samples every 30 seconds: process-tree RSS/peak RSS, processes,
threads, sampled CPU cores and output-disk free space, cgroup memory current/peak/max/OOM and PID counts where available, active
shared provider/audit slots, elapsed time, completion throughput excluding preexisting
completed assignments, per-operation p95 duration and provider-slot wait p95.
Shared `events-<host>-<pid>.jsonl` records only operational facts, request digests,
durations, retry/failure counts/types and exposed HTTP status codes; it does not log
prompts, responses, keys or exception messages. Hosted SDK retries remain disabled
as before; Codex transport retries and judge failed attempts are observed. Internal
provider/server retries not exposed by the SDK cannot be measured here.

Use these operational thresholds (recommendations, not scientific stopping rules):

- Hard invariant: admitted provider operations ≤60 across all jobs, audit studies ≤1,
  and slots return to zero after all jobs exit. Fake-load acceptance must pass first.
- Before full: real smoke completes revision and every audit stage, with zero terminal
  provider failures, no OOM/kills, no missing artifacts, and valid native resume.
  Review retries and latency separately by operation/provider.
- At target 60: no terminal failures; exposed transient failure/retry rate below 2%
  and HTTP 429 rate below 1% of relevant attempts. Repeated failures or circuit-breaker
  openings require diagnosis and bounded recovery, not increasing workers.
- Peak cgroup memory below 80% of 256 GiB (about 205 GiB), no OOM events, disk at least
  20% free, and no sustained CPU saturation beyond 90% of the allocated CPUs. Consult Slurm
  `sacct -j JOBID --format=JobID,State,Elapsed,AllocCPUS,ReqMem,MaxRSS,ExitCode`
  for final accounting; process-tree RSS is sampled and can double-count shared pages.
- Compare the same audit operation: p95 service duration at 60 no more than 1.5×
  smoke's p95 and completed requests/minute improves rather than plateaus with rising
  retries. Slot queue time is separate from service duration. Review at least 100
  relevant requests and three consecutive samples near target occupancy when available.
  If bounded dev3 cannot provide this load, report stability at 60 as unproven; do not
  expand scope or redo completed work merely to obtain a benchmark.

The runtime is capable of 60 immediately. A successful low-load real smoke establishes
launch correctness; only actual target-load metrics establish provider stability.

## Preparation verification

Native input validation accepts all six seeds and both fixed transferred pools without
rewriting them. New relative-reference pools also pass relocation and no-generation
resume tests; altered references/content reject, and completed Mac task identities
still reject resume. Mocked launcher tests cover allocation requirements, smoke/full
ordering, explicit limits, source drift, secret redaction and resume-aware metrics.

The shared-NFS synthetic check passed repeatedly (4.262–18.206 seconds): 72 submitted operations across
three processes, peak exactly 60, all 72 completed, zero active slots afterward, zero
provider calls. Selected suites passed 281 workflow tests, 210 additional path checks,
11 focused limiter/launcher tests and the mock socket test (these suites overlap). Earlier attempts exposed slow
NFS blocking-lock wakeups; nonblocking kernel-lock retries resolved admission and
telemetry delays without changing the cap. This was test work in temporary namespaces,
not an experiment. Broader workflow and scoring tests passed; the mock Unix-socket
proxy check requires execution outside the agent's socket-restricted sandbox.

## Files changed

- Portable references: `src/rubric_gen/submission_revision/paraphrase_validation.py`,
  `src/rubric_gen/submission_revision/paraphrases.py`.
- Shared admission and telemetry: `config/runtime.json`,
  `src/rubric_gen/runtime/capacity.py`, `src/rubric_gen/runtime/llm.py`,
  `src/rubric_gen/runtime/agents/codex_sessions.py`,
  `src/rubric_gen/runtime/agents/runners.py`,
  `src/rubric_gen/runtime/agents/sessions.py`, `src/rubric_gen/cli.py`,
  `src/rubric_gen/benchmarks/harvey_lab/evaluator.py`,
  `src/rubric_gen/benchmarks/harvey_lab/audits.py`,
  `src/rubric_gen/submission_revision/evolution_provider.py`,
  `src/rubric_gen/submission_revision/evaluation/rubric_judge.py`,
  `src/rubric_gen/submission_revision/judge.py`,
  `src/rubric_gen/submission_revision/commands.py`,
  `src/rubric_gen/submission_revision/evaluation/runner.py`,
  `src/rubric_gen/detection/runner.py`.
- Babel execution: `scripts/babel/dev3.sbatch`, `scripts/babel/launch.py`,
  `scripts/babel/monitor.py`, `scripts/babel/check.py`,
  `experiments/babel/biomnibench-dev3-control-da-3-4.yaml`,
  `experiments/babel/biomnibench-dev3-control-da-11-1.yaml`.
- Verification: `tests/conftest.py`, `tests/test_runtime_capacity.py`,
  `tests/test_babel_portability.py`, `tests/test_babel_launcher.py`,
  `tests/test_rubric_paraphrases.py`, `tests/test_submission_revision.py`.
- Documentation/records: `README.md`, `docs/BABEL_SETUP.md`, `docs/BABEL_HANDOFF.md`,
  `docs/architecture.md`, `EXPERIMENT_PLAN.md`, `EXPERIMENT_RUNS.md`,
  `EXPERIMENT_LOG.md`, `CODE_REVIEW.md`. Historical entries are retained; current Babel
  instructions supersede old operational limits without revising scientific results.

No changes to `uv.lock`, scientific prompts, rubric/scoring logic, metrics, benchmark
data, completed run artifacts or archived investigation evidence. Operational wrappers
change some audit source identities; old audits are not rebound to these identities.
The frozen seed grading-engine implementation remains unchanged.
