# Babel `/data/user_data/aydanh` storage cleanup

Status: cleanup and bounded inventory in progress. All measurements and deletion
actions run from Slurm compute nodes. This work does not change Red-Team Trace
science or delete RTT results.

## Filesystem interpretation

On 2026-09-16, a compute-node mount check showed that
`/data/user_data/aydanh` is its own NFSv4 export,
`nas8:/data/user_data/aydanh`, with a reported capacity of 2.0 TiB. The advisor's
storage report independently attributes the full 2.00 TiB export to this account.
The filesystem did not return a usable per-user `quota` result. `$HOME` is a
different export, `nas1:/srv/nfs/home/aydanh`, with 100 GiB capacity.

The initial compute-node measurement at 2026-09-16 04:15 EDT reported
2,199,016,964,096 bytes used, only 6,291,456 bytes available, and 8,083,308 used
inodes. The NFS server changes the reported inode-pool denominator dynamically,
so cleanup accounting uses changes in used inode count rather than comparing the
displayed percentage alone.

## Confirmed cleanup

| Path | Classification | Evidence and action | Bytes released | Used inodes released |
|---|---|---|---:|---:|
| `/data/user_data/aydanh/triton_cache` | Reconstructible compiler cache | July job-specific caches; user-owned; no running jobs; deleted by Slurm job `10460910` | 12,210,667,520 | 211,566 |
| `/data/user_data/aydanh/torchinductor_cache` | Reconstructible compiler cache | July job-specific caches; user-owned; no running jobs; deleted by Slurm job `10461021` | 56,623,104 | 446 |
| `/data/user_data/aydanh/apptainer/{tmp,cache}` and user-deletable parts of `apptainer/swe_together/{tmp,cache}` | Failed/stale container build temporaries and caches | Exact-path deletion job `10461151`; stopped after the remaining old build tree produced 19,678 permission errors on root-owned files | 85,498,789,888 | 1,241,769 |
| `/data/user_data/aydanh/uv_cache` | Reconstructible package cache | Exact-path deletion job `10461248` | included in the 13,700,694,016-byte job delta below | included in the 109,274-inode job delta below |
| `/data/user_data/aydanh/envs/sera-cli-edf8f99d.staging.9408052` | Abandoned environment staging directory | Exact-path deletion job `10461248`; its measured logical size was 93,197,312 bytes | included with `uv_cache` | included with `uv_cache` |

The Apptainer cleanup deliberately preserves completed `.sif` images and
definition files. The root-owned remnants under
`apptainer/swe_together/tmp/build-temp-786972404/rootfs` require administrator
help if they remain material after the bounded inventory; broad permission
changes were not attempted.

Across the initial reading before any cleanup and the reading after job
`10461248`, reported used space fell by 111,631,400,960 bytes (103.97 GiB) and
used inodes fell by 1,564,676. Available space rose from 6 MiB to approximately
104 GiB. The UV cache's logical `du` size was 37,184,705,536 bytes, whereas the
filesystem allocation changed by 13,700,694,016 bytes when it and the staging
directory were removed; this report uses the `df` delta for capacity accounting
and preserves both observations rather than treating logical size as bytes freed.

## Partial attribution before cleanup

The first bounded traversal reached these top-level roots before it was stopped
at the obsolete Apptainer build tree:

| Path | Bytes | Preliminary classification | Deleted? |
|---|---:|---|---|
| `/data/user_data/aydanh/models` | 610,012,136,448 | Model weights; inspect by model before any deletion | No |
| `/data/user_data/aydanh/envs` | 49,809,348,096 | Active/obsolete environments mixed | Only the explicit stale staging root |
| `/data/user_data/aydanh/uv_cache` | 13,844,595,200 | Reconstructible package cache | In progress |
| `/data/user_data/aydanh/hf_home` | 768,163,840 | Hugging Face state/cache | No |
| `/data/user_data/aydanh/tools` | 365,870,080 | Installed tooling | No |

A post-cleanup bounded top-level byte/inode inventory is queued as Slurm job
`10461251`. It will determine the remaining major roots before any further
deletion. Scientific trajectories, canonical inputs, judgments, Git history,
current RTT outputs, and unrelated project data remain protected by default.

## Receipts

Small operational receipts are stored outside Git under
`/home/aydanh/runs/storage-cleanup-20260916/`. They include the before/after
filesystem readings and exact job outputs. No credentials or scientific payloads
are included in this report.
