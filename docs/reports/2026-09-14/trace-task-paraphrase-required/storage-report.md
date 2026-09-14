# Frozen Dev3 storage and worker readiness report

**Recorded:** 2026-09-14 06:29 EDT  
**Scientific recipe:** `attack_defense_v2.1_task_paraphrase_required`  
**Source commit:** `ed98e95`  
**Dev3 state:** 0/18 provider assignments launched; candidate code and 53 focused tests are complete.

## Filesystem interpretation

The current compute-node probe was Slurm job `10437391` on `babel-v9-20`. It
reports two different NFS exports:

| mount | filesystem reported by `df` | bytes | inodes |
|---|---|---:|---:|
| `/data/user_data/aydanh` | `nas8:/data/user_data/aydanh` (`nfs4`) | 2.0T total, 2.0T used, **6.0M free, 100%** | 8,093,308 used, **10,873 free, 100%** |
| `/home/aydanh` | `nas1:/srv/nfs/home/aydanh` (`nfs4`) | 100G total, 93G used, **7.1G free, 93%** | 1,188,011 used, **14,712,986 free, 8%** |

The `df` figures describe the mounted filesystem/export. They do not establish
that the full 2.0 TB is this account's personal 500 GB quota. A read-only quota
query on the compute node returned `quota: user /data/user_data/aydanh does not
exist`; no usable per-user quota report is available. The mount options and
filesystem identity are preserved in `experiments/trace-task-paraphrase-required/storage-10437319.log`.

The earlier check `10432884` reported 25M free and 49,491 free inodes on the
same export. The later `10437319` diagnostic and the independent current probe
`10437391` both report 6.0M and 10,873, respectively. This is a shared/export
state change, not evidence that a Dev3 output was created: the candidate output
root is still absent and no scientific provider call has run.

## Bounded ownership and usage evidence

The immediate top-level enumeration in `10437319` found directories owned by
UID/GID `6011048` (the account) including `triton_cache`, `hf_cache`, `envs`,
`hf_home`, `uv_cache`, `tools`, `datasets`, `torchinductor_cache`, `models`,
`apptainer`, `vllm_cache`, `checkpoints`, `tmp`, `rubric_gen`, `logs`,
`coral_math_solo_to_collab`, `projects`, `runs`, `pip_cache`, and
`coral_hard_math_7b_pilot`. The numbers printed beside those entries were
directory inode `st_size` values, not recursive byte or file counts.

A bounded `du -x --max-depth=1` over the complete top level was attempted with a
240-second limit. It remained in NFS metadata I/O (`top_bytes_status=124`), and
the job was canceled after five minutes before an inode scan. No aggregate size
or inode total is invented from that incomplete scan. This avoids an
unbounded recursive walk while the export is inode-exhausted.

The following are the largest *measured* or previously censused items, with
their safety classification:

| path | measured bytes / entries | category | active dependency? | safe to delete now? | reason |
|---|---:|---|---|---|---|
| `/data/user_data/aydanh/rubric_gen/cache/environments/a5f86d3f89f6256c-d61735ca9b4a-10380169` | 1,017,505,307 bytes / 21,703 entries (complete prior census) | obsolete runtime environment cache | no, verified by allowlist | **already deleted** by `10423023` | reconstructible, owned by UID/GID 6011048; receipt records the deletion |
| `/data/user_data/aydanh/rubric_gen/cache/environments/a5f86d3f89f6256c-be8151e15cce-10380168` | absent | obsolete runtime environment cache | no | no action | already absent in the allowlist receipt |
| `/data/user_data/aydanh/rubric_gen/cache/environments/trace-repair-10381602` | directory `st_size` 10; recursive total not rescanned | active Python/runtime environment | **yes** | **no** | current candidate and native tooling may depend on it; protected |
| `/data/user_data/aydanh/rubric_gen/data/.../da-17-1/environment/data` | 11G in targeted prior measurement | scientific task data | potentially yes | **no** | durable benchmark input/output, not reconstructible cache |
| `/data/user_data/aydanh/rubric_gen/data/.../da-1-3/environment/data` | 9.0G in targeted prior measurement | scientific task data | potentially yes | **no** | durable benchmark input/output, not reconstructible cache |
| `/data/user_data/aydanh/rubric_gen/validation` | 124M in incomplete prior top-level scan | validation/scientific records | uncertain | **no** | provenance and validation evidence are protected |
| `triton_cache`, `torchinductor_cache`, `hf_cache`, `uv_cache`, `vllm_cache`, `pip_cache`, `tmp`, `logs` | recursive totals unavailable; top-level enumeration only | possible transient caches | not established | **no** | no current non-use, ownership-at-depth, or safe allowlist was established; deleting by name would risk active jobs/data |
| `/data/user_data/aydanh/rubric_gen/runs` and benchmark `data` roots | recursive totals unavailable | durable scientific runs/inputs | yes or unknown | **no** | preserve trajectories, seeds, rubrics, judgments, and recovery state |

The prior allowlisted deletion removed only the obsolete runtime cache and kept
the active environment. Since the current export still has effectively no byte
or inode headroom, and the bounded scan cannot attribute the remaining usage to
reconstructible material, cleanup stops here. The condition requires filesystem
administration or an owner-approved, specifically identified cache target; it is
not safe to delete benchmark evidence to compensate for a shared NAS constraint.

## Scratch and `$HOME` review

`run_candidate.sbatch` currently places the durable live root and temporary/cache
paths under `/data/user_data/aydanh/rubric_gen/...`. Durable study artifacts must
remain persistent. Provider workspace, parsing/retry intermediates, and app
server temporary files could be candidates for `/scratch/job_tmp/$SLURM_JOB_ID`
in a future operational change, but the current runtime/resume contract has not
been validated for that relocation. No path was changed in this readiness task.

`$HOME` is a different export and is healthy by inode count, but silently moving
the frozen output root there would break the prepared native paths/provenance and
could consume most of its remaining 7.1G. It is not used as a fallback.

## Worker and launch status

The last same-route smoke, Slurm job `10432888`, failed before a model turn with
`CodexProviderHealthError`; its saved route record identifies
`TransportClosedError: Codex app-server closed stdout during startup`. The job
also logged that `/var/tmp/aydanh-codex-runtime/redteam/tmp` was absent and fell
back to `/tmp`. It made no scientific provider call. Per the readiness order, no
new smoke is attempted while persistent output storage is at 100% bytes and
inodes.

There are no running candidate jobs. The visible held/dependency-blocked legacy
Slurm jobs are historical or belong to other workflows and were not modified.
The frozen Dev3 launch has therefore **not** been submitted. The exact native
continuation remains:

```text
sbatch experiments/trace-task-paraphrase-required/run_candidate.sbatch
```

It is safe to submit only after both conditions have fresh evidence: (a) durable
`/data/user_data` byte and inode headroom suitable for 18 assignments and (b) a
same-route smoke that reaches and persists a real model turn. The candidate,
scientific prompts, settings, and output ownership remain unchanged.

## Receipts

- Current read-only probe: `experiments/trace-task-paraphrase-required/storage-current-10437391.log` (`10437391`, completed, 1 CPU, 1 second).
- Bounded storage diagnosis: `experiments/trace-task-paraphrase-required/storage-10437319.log` (`10437319`, canceled after the NFS `du` timeout; no writes to scientific roots).
- Earlier storage snapshot: `experiments/trace-task-paraphrase-grounded/current-storage-10432884.log` (`10432884`).
- Worker smoke: `experiments/trace-task-paraphrase-grounded/route-10432888.log` (`10432888`, failed before model turn).
- Obsolete-cache census and deletion receipt: `experiments/biomnibench-v21-to45/queue8/obsolete-cache-inspection.json`, `experiments/biomnibench-v21-to45/queue8/exact-cache-cleanup-receipt-v2.json`, and cleanup job `10423023`.

