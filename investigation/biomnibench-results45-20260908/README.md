# Planned BioMNIBench Results45 inventory

Retains all canonical Result20 tasks; adds25 of27 remaining non-dev tasks from pinned public revision e1c8ca5e11a620087bc48d97888eb69176a1f235. Selection is deterministic SHA256 ordering with namespace `rubric-gen-results45-20260806:`, fixed before new outcomes. This namespace selects tasks only; experiment randomization settings remain unchanged. Original20 result artifacts and canonical dev3 remain unchanged.

Two user-simulator conditions only: static and red-team trace,3replicates each,270assignments. Scientific scale-up is not launched; first validate the rubric-cue simulator and matched dynamic policy on frozen dev3. Inventory is not evidence of local data completeness or validated generated seed/paraphrase pools.

Additional tasks: da-8-1, da-26-4, da-20-4, da-19-3, da-4-1, da-1-3, da-3-5, da-4-6, da-5-1, da-26-2, da-9-7, da-24-3, da-6-5, da-17-3, da-1-4, da-8-3, da-17-5, da-17-1, da-9-1, da-20-1, da-4-7, da-8-2, da-19-4, da-25-1, da-6-2.

Unselected non-dev tasks: da-20-3, da-5-3.

[inventory.json](inventory.json) contains all45 IDs, upstream file metadata and provenance. New-task data preparation must run in Slurm and verify pinned hashes without overwriting existing data.

## 20:15 EDT storage prerequisite

The25 added tasks contain236 files totaling82,195,617,343 bytes. Content-unique bytes are36,408,148,834; large repeated datasets explain much of the difference. The home/repository mount currently has about41GiB free of100GiB. Do not download all82GB into this mount or assume deduplicated canonical storage solves runtime storage: workspace code copies task data, so parallel replicas can multiply storage.

Before data restoration, inspect available larger persistent/shared storage and node-local capacity through Slurm. Preserve exact data hashes and task IDs; do not silently drop large tasks for convenience. No new canonical files have been downloaded. This prerequisite does not block currently running dev3 comparisons.

## 20:20 EDT shared storage found; preparation queued

Compute-node inspection10364194 confirms `/data/user_data/aydanh` is writable shared NFS with411,227,389,952bytes free and `/scratch` has2.6TB free onbabel-l5-28. The shared path is absent on this login-node view; access it through Slurm. Canonical data-preparation10364235 targets `/data/user_data/aydanh/rubric_gen/data/biomnibench-da-results45-e1c8ca5e11a62`,4CPU/8GiB/4h, no model calls. It copies existing canonical task files, fetches missing pinned task files with configured `hf download`, verifies size/Gitblob orLFS hashes plus SHA256, and preserves a per-task progress journal.

Receipt root `runs/results45-data-prepare-10364235`. No generated seeds/paraphrases or scientific Results45 execution is launched. Future large-task workspace copies still need storage budgeting before scientific scale-up.

## 20:24 EDT download access requirement

Datajob10364235 failed4s after copying/verifying original20tasks. First new taskda-8-1 returned HTTP401 GatedRepoError: pinned source now requires authenticated access. No HF_TOKEN was configured in.env.local or standard login cache. Request for an existing authorized credential location/access setup is pending; do not repeat anonymous downloads or bypass the gate. Original20verifieddata are retained and dev3 science continues. Actual destination uses12-character revision prefix: `/data/user_data/aydanh/rubric_gen/data/biomnibench-da-results45-e1c8ca5e11a6` (the earlier prose path had an extra2).
