# Result20 rubric-cue runtime checkpoint

Observed 20:53 EDT; incomplete execution, not a scientific result.

| Arm | Maximum sampled CPU cores | Maximum sampled process RSS (GiB) | Samples with shared pool at60 / samples |
|---|---:|---:|---:|
| static | 2.88 | 41.68 | 19/20 |
| trace | 1.80 | 21.28 | 27/27 |

The same shared provider pool is observed by both monitors; these counts must not be added. Sampled occupancy has remained at60 for roughly12minutes. Four requested CPUs per job remain supported by observed CPU usage; no reason to reduce API concurrency for CPU pressure. Summed process RSS can double-count shared pages and is not an exact Slurm peak-memory measure. No OOM event was recorded.

No HTTP failure status was recorded in these monitor snapshots. Static has seven solver retry events; trace has one failed evolution operation and one repeated request attempt. These counters do not prove all provider calls were error-free. One static assignment had a separately diagnosed NFS cleanup failure, with native continuation queued (10364765).

Latest provider-slot wait p95 is roughly2–2.5minutes and long solver turns dominate observed operation latency. Full-pipeline runtime and stable end-to-end throughput remain unproven while most revisions are unfinished. Do not extrapolate total ETA from the first completed assignment. Rubric-cue dev3 has reached RH auditing, with1/6 panel judgments reported at the last log read; its result remains incomplete.

Home quota free space was about30GiB at this checkpoint; continue monitoring growth before any additional scale-up or workspace duplication. Raw snapshot: `investigation/result20-cue-contrast-20260908/runtime-checkpoint.json`.
