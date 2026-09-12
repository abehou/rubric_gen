# Trace stage CPU requests at a safe boundary

Read-only accounting on completed jobs supports different CPU profiles by stage. No live job is resized, cancelled or hot-swapped. HTTP concurrency is separate from CPU count and the shared provider60/audit1 limits remain unchanged.

| Stage/evidence | Requested CPUs | CPU seconds / wall seconds | Mean occupied cores | Observed sampled peak | Future request |
|---|---:|---:|---:|---:|---:|
| User trace R1 da-11-1,10414482 | 4 | 3947 / 4548 | 0.87 | 3.05 | 4, unchanged |
| User trace R2 da-11-1,10414485 | 4 | 2292 / 3530 | 0.65 | 3.02 | 4, unchanged |
| Semi fixed da-11-1,10414550 | 4 | 750 / 729 | 1.03 | 2.05 | 4, unchanged |
| Full fixed da-3-4,10414561 | 4 | 38 / 124 | 0.30 | 0.62 | 4, unchanged shared producer profile |
| Semi-fixed native audit,10414573 | 8 | 50.195 / 983 | 0.051 | Not sampled | 4 for future Results30 audits, same32 request workers |
| Serial inventory/collector | 1 | Small read/aggregate stage | — | — | 1, unchanged |

Producer trees reached26–29 processes and214–321 threads, although many were idle/I/O-bound. Their sampled CPU peaks reached roughly three cores; reducing these four-CPU producers would risk useful solver throughput. A small fast fixed task does not justify reducing all producers. New seed lanes have at most three active native task/replicate blocks at a time; retain four CPUs for their scientific computation and serialization rather than assuming seed generation is solely network-bound.

The completed audit reserved eight CPUs for predominantly remote requests and used about0.64% of its allocated CPU-time. No high-resolution peak sample exists, so four CPUs retain headroom for concurrent subprocess startup and public-payload preparation. This is a stage-local future request adjustment, not fewer judgments or lower model concurrency. Previously submitted eight-CPU jobs retain their requests. New audit recoveries10414945/10414965 and remaining-task audits10415055/10415056 request four CPUs with the same32 request workers. Finalization/ranking is serial and keeps its established one-CPU request. This is an initial measured allocation decision; more demanding new-task behavior remains observable in standard runtime/accounting records.

## Scale-stage accounting snapshot — 15:03 EDT

The completed Results30 seed lane 10415714 used four CPUs for 56:48 (CPU 02:15, about 0.99% allocation efficiency, 73.64 GB peak memory), and its one-block native retry 10416038 used four CPUs for 01:11 (CPU 00:11, 3.87%, 1.18 GB). A completed six-assignment revision shard 10415692 used four CPUs for 27:03 (CPU 08:13, 7.59%, 1.75 GB). These low CPU shares reflect provider/network waits and do not justify lowering the four-CPU request: each revision/seed owner configures four native workers, and the shared provider limiter—not CPU oversubscription—is the throughput control. No active request was changed; future audits/collectors remain four/one CPUs as above.
