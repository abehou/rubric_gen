# Babel `/data/user_data/aydanh` storage cleanup

Status: complete at the safe cleanup boundary. All inventory and deletion work
ran from Slurm compute nodes. No Red-Team Trace result, canonical benchmark data,
judgment, Git history, custom/fine-tuned model, or uncertain project artifact was
deleted.

## Filesystem interpretation and result

Compute-node inspection identifies `/data/user_data/aydanh` as the dedicated
NFSv4 export `nas8:/data/user_data/aydanh`, with 2.0 TiB reported capacity. The
advisor's independent storage report attributes this export to the `aydanh`
account. The filesystem returned no usable per-user `quota` result. `$HOME` is a
separate 100 GiB NAS1 export, `nas1:/srv/nfs/home/aydanh`.

| Compute-node reading | Used bytes | Available bytes | Use | Used inodes |
|---|---:|---:|---:|---:|
| Before cleanup, 2026-09-16 04:15 EDT | 2,199,016,964,096 | 6,291,456 | 100% | 8,083,308 |
| After cleanup, 2026-09-16 06:39 EDT | 1,346,806,743,040 | 852,216,512,512 | 62% | 6,460,858 |
| Change | **-852,210,221,056** | **+852,210,221,056** | **-38 points** | **-1,622,450** |

The cleanup released **793.68 GiB (0.775 TiB)**, or 38.75% of the initial used
space. About **793.69 GiB** is now available. The NFS server changes its reported
inode-pool denominator dynamically, so inode accounting uses the used-inode delta
rather than the displayed percentage.

## Why the account reached 2 TiB

The usage was distributed across several large classes rather than one accidental
file. Sizes below are bounded logical measurements taken before the applicable
deletion; nested rows are called out explicitly and should not be added twice.

| Path or class | Measured bytes | What it contained | Disposition |
|---|---:|---|---|
| `models` | 610,012,136,448 | Downloaded official checkpoints plus custom/fine-tuned model artifacts | Six inactive, redownloadable Qwen checkpoints removed; custom/uncertain models retained |
| `apptainer/images` and `apptainer/swe_together/images` | 352,411,705,856 | 625 reconstructible SIF image-cache files | Removed; small definition files retained |
| Apptainer build/cache temporaries | at least 85,498,789,888 filesystem bytes | Failed and stale container builds | User-deletable content removed; protected remnants documented below |
| `coral_math_solo_to_collab` and `coral_hard_math_7b_pilot` | 185,617,161,728 | Research projects, mostly model artifacts | Retained because uniqueness/reconstructibility was not established |
| `rubric_gen/runs/biomnibench-v21-to45-20260912` | 184,510,077,440 | Historical BioMNIBench scientific run evidence | Retained |
| `rubric_gen/live` | 62,952,698,880 | Mostly `runtime-throughput`, plus Results20 and PaperBench live state | Retained; broad deletion was not safe to infer |
| `rubric_gen/data` | 60,143,677,440 | Canonical benchmark datasets | Retained |
| `envs` | 49,809,348,096 | Multiple project environments | Only one explicit abandoned staging environment removed |
| top-level `runs` | 22,147,294,720 | Mixed project run evidence | Retained |
| `rubric_gen/cache/runtime-throughput` | 24,350,949,376 | Old job-specific `tmp-*`, pytest, matplotlib, submission-judge, and red-team temporary workspaces | Removed after exact inspection |
| top-level `pip_cache` and `vllm_cache` | 16,223,008,768 | Reconstructible package/runtime caches | Removed |

The six deleted Qwen checkpoints accounted for 346,878,145,536 logical bytes:
`Qwen3.6-35B-A3B`, `Qwen3.5-9B`, `Qwen3-32B`, `Qwen3.5-27B`,
`Qwen3.6-27B`, and `Qwen3.8-27B`. The Qwen embedding model and all AllenAI,
CooperBench, Coral, BAAI, and fastembed artifacts were preserved. The largest
retained model namespaces are AllenAI (167,421,045,760 bytes, including the
131,590,181,888-byte `tmax-27b`) and CooperBench (93,134,094,848 bytes).

A bounded per-run traversal measured the 184.5 GB BioMNIBench root and small CUE
roots, then was stopped on a metadata-heavy PaperBench run rather than spending
hours scanning protected scientific evidence. This leaves some residual usage
unattributed at fine granularity, but does not change the safe-deletion decision.

## Exact deletions

| Exact target | Reason it was safe | Filesystem bytes released | Used inodes released | Slurm job(s) |
|---|---|---:|---:|---|
| `triton_cache` | Reconstructible July compiler cache; inactive and user-owned | 12,210,667,520 | 211,566 | `10460910` |
| `torchinductor_cache` | Reconstructible compiler cache; inactive and user-owned | 56,623,104 | 446 | `10461021` |
| Apptainer `tmp`/`cache` roots | Failed/stale container build state | 85,498,789,888 | 1,241,769 | `10461151` |
| `uv_cache` and `envs/sera-cli-edf8f99d.staging.9408052` | Reconstructible package cache and abandoned environment staging | 13,700,694,016 | 109,274 | `10461248` |
| Six official Qwen checkpoints listed above | Inactive, provider-published and redownloadable | 346,880,475,136 after NFS reclamation settled | 429 | `10461426` |
| `pip_cache` and `vllm_cache` | Reconstructible caches | 15,756,951,552 | 31,744 | `10461428` |
| Two Apptainer SIF image-cache roots | Reconstructible images; definitions preserved | 295,422,656,512 | 513 | `10461601` |
| `rubric_gen/cache/runtime-throughput` | Inspected old job/test temporary workspaces | 24,333,254,656 | 10,945 | `10461873`, `10461996` |

Logical `du` size and allocated `df` release differ for some batches because of
NFS reclamation timing and filesystem allocation. The headline 852.21 GB result
uses only the non-overlapping initial-to-final `df` delta. The listed immediate
batch deltas sum to 793,860,112,384 bytes; a further 58,350,108,672 bytes became
available between receipts without another deletion, consistent with delayed
NFS reclamation after the large model/image removals.

The first runtime-cache deletion removed all normally writable content but found
old owner-read-only directories. Read-only job `10461985` verified that every
remaining entry belonged to UID 6011048 (`aydanh`); job `10461996` restored owner
write permission only inside that exact disposable cache root and removed the
remaining 1,430,445,056 bytes. No broad permission change was used.

## Protected and administrator-owned remnants

The cleanup intentionally retains scientific results, canonical inputs,
judgments, custom or uncertain model outputs, live state, and active reusable
environments. These are candidates for later owner-led archival decisions, not
cache cleanup.

Old Apptainer build residue under
`apptainer/swe_together/tmp/build-temp-786972404/rootfs` produced 19,678
permission errors because some entries are root-owned. The user account did not
use `sudo`, `chown`, or a broad permission repair. If that residue remains worth
removing, an administrator can delete that exact obsolete build-temp root after
confirming it is inactive.

A proposed broad deletion spanning `rubric_gen/cache/{environments,uv,tmp}` and
`rubric_gen/live/runtime-throughput` was not performed. Those roots may contain
needed environment or resumable live state, and the evidence supported only the
exact `cache/runtime-throughput` deletion completed above.

## Receipts

Small operational receipts are stored outside Git under
`/home/aydanh/runs/storage-cleanup-20260916/`. They record the compute node,
timestamps, exact targets, ownership checks, and before/after filesystem readings.
The bounded inventory job was `10461754`; it was cancelled after identifying the
dominant BioMNIBench root because subsequent protected PaperBench traversal was
metadata-bound. No credential or scientific payload is included in this report.
