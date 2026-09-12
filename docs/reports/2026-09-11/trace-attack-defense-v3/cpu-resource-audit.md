# Trace-v3 CPU allocation review

Reviewed at the idle scientific boundary after stress v3.1 and its full audit;
the only subsequent job was a completed provider-free test run. No healthy job
was interrupted. Changes affect future invocations only. Memory reservations,
scientific settings, assignment concurrency, provider limit 60 and audit-study
limit one are unchanged.

The [complete script inventory](cpu-resource-audit.csv) lists every tracked
trace-v3 sbatch file and its before/after request. [Slurm accounting](cpu-resource-accounting.txt)
includes duplicate/preempted attempts rather than hiding them.

| stage | CPUs before → after | actual concurrency and evidence |
|---|---|---|
| outcome audit | 32 → 8 | Retains 32 request workers and native shared provider coordination. Three task studies run sequentially. Job 10409706 used 35.03 CPU-seconds over 996 seconds (0.035 average cores); most time is provider/network wait. Eight cores retain parsing, tokenization, subprocess and plotting headroom. |
| stress finalization | 8 → 1 | Serial saved-output validation, no model calls. Job 10409423 used 19.32 CPU-seconds over 20 seconds; approximately one useful core. |
| outcome reporting | 8 → 1 | Serial JSON/NFS reconstruction, no provider calls. Job 10409709 used 1.02 CPU-seconds over 34 seconds. |
| stress forensic export | 8 → 1 | Serial file reads, JSON parsing and public-text diffs. Job 10409710 used 3.71 CPU-seconds over 769 seconds; NFS waiting dominates, not parallel computation. |
| gap/RH ranking | script 8 → 1; last invocation used 4 | Python ranking over 147 artifacts, no worker pool or model calls. Job 10410280 used 1.80 CPU-seconds over 192 seconds. |
| recovery finalizer / ledger and configuration inspection | 2 → 1 | Serial inspection/validation. Job 10407854 used 51.83 CPU-seconds over 319 seconds. No revision-recovery worker count is changed. |
| control-receipt validation / historical forensic extraction | 8 or 2 → 1 | Serial code, no provider fan-out. These scripts have the same file-bound workload; their existing memory limits remain. |
| producer, stress, canonical solver runs and behavioral recovery | 32 → 32 | Preserve current requests pending a measurement that bounds solver tool peaks. Current stress uses three task runners with **one** assignment worker each, not nine simultaneous workers; earlier owner metadata overstated this. Tool subprocesses can perform local numerical work with library threads. Low averaged CPU use alone does not bound those peaks. |
| seed generation | 32 → 32 | Up to three task runners × three seed workers, plus solver tool processes. No new seed generation is authorized for the current iteration. |
| tests | 2 → 2 | 370 tests include fork/subprocess/concurrency fixtures. Completed test attempt used 59.15 CPU-seconds over 87 seconds; two cores provide reasonable fixture headroom. |
| already one-CPU inspection scripts | 1 → 1 | Already appropriate; unchanged. |

Producer accounting is also low on average: original stress job 10402416 used
8,275 CPU-seconds over 13,262 seconds (0.62 average cores); v3.1's preempted attempt
used 1,606.6 over 7,943 seconds (0.20 average cores). This suggests a future
producer peak-utilization measurement could justify a smaller reservation, but
the existing accounting does not separate numerical bursts from provider waits.
This review therefore makes the clear serial/audit reductions first. It does
not silently change BLAS threads, assignment workers or solver execution to make
a smaller allocation appear sufficient.

The shared `scripts/babel/experiment.py` profiles are left intact: dev3-4 and
dev3-8 bind 4/8 workers to 4/8 CPUs; results20 binds 32 workers to 32 CPUs; inspection
allows four request workers with one CPU. These are profiles for different
workloads, not interchangeable CPU targets. The trace audit's eight-CPU request
retains its existing 32-worker setting explicitly rather than selecting a profile
that would reduce concurrency as a side effect.

The next stress script invokes the normal scoped `revise --resume` command for
each task, with the same one-worker-per-task concurrency as v3.1. It records Git
commit/restart in append-mode Slurm logs and creates no experiment-specific
recovery framework. Production Result20 is still not authorized to launch until
development is satisfactory.

## Completed v3.2 evidence

The reduced requests have now completed the unchanged scientific pipeline.
All five jobs below exited 0:0; no active job was resized or interrupted.

| job / stage | CPUs | elapsed | total CPU seconds | average used cores |
|---|---:|---:|---:|---:|
| 10411526 producer | 32 | 2:04:02 | 3,301.817 | 0.444 |
| 10411527 finalizer | 1 | 1:19 | 22.486 | 0.285 |
| 10411528 Sol+Opus audit | 8 | 22:47 | 24.552 | 0.018 |
| 10411530 report | 1 | 0:38 | 1.134 | 0.030 |
| 10411532 forensic | 1 | 1:44 | 2.424 | 0.023 |

The audit completed all 330 required judgments with the existing 32 request
workers and shared capacity limits. Serial one-CPU jobs validated all nine cases
and produced complete reports. These observations support the stage-specific
reductions; they are not a controlled throughput comparison to 32 CPUs. No
further producer reduction is inferred from averages. CPU accounting includes
waiting time in the denominator and is not a peak-thread measurement.

Structured accounting, including maximum RSS and allocation efficiency, is in
[the JSON](cpu-resource-audit.json). No model/settings, worker count, BLAS-thread,
scientific prompt, outcome or evaluation change was made to save CPUs.
