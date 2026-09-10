# Pinned PaperBench data preparation

Data-only job10372604; frozen preparation commit551a45b. Uses unchanged `download_paperbench.py` and native `validate_paperbench_code_dataset`. Source openai/frontier-evals revision51052cede8cc608f95bb00346635e03759013e5a; exact20results and3devpaper IDs are taken from the native implementation, never BioMNIBench outcomes.

Destination: `/data/user_data/aydanh/rubric_gen/data/paperbench-51052cede8cc/{all,dev}`. Separate from all BioMNIBench data. Before downloading, inspect pinned Git tree and LFS pointer metadata, estimate hydrated bytes, require three times input size plus2GiB conversion allowance and180GiB reserved for concurrent BioMNIBench/working space. Temporary raw source also resides on that shared filesystem, not the active experiment node or repository mount.

Output receipts: `runs/paperbench-data-prepare-10372604/`. Capacity/source manifest precedes download; per-split validation and SHA256file receipts precede read-only sealing; final result records coverage and bytes. Existing destinations are validated and preserved, never overwritten. The native downloader has no resumable partial raw-source support; do not fabricate it. Completed validated splits survive failure of the other split. Any failure is recorded and must be reported before recovery.

Current status: RUNNING capacity/source check. No PaperBench model calls, seeds, paraphrases, induction, revisions or audits are launched. Coverage and validation are not yet claimed.

## 12:09 EDT capacity gate passed

Pinned inputs estimate87,135,025bytes (83.1MiB); conversion/temporary allowance2,408,888,723bytes; other-work reserve193,273,528,320bytes; available400,093,609,984bytes. Native all-split download is running. Final coverage/hashes still pending.

## 12:16 EDT — completed and validated

Initial job10372604 failed on DNS resolution (`URLError: [Errno -2] Name or service not known`); logs preserved. Unchanged native retry10372686 completed both pinned splits:

| Split | Papers | Files | Bytes |
|---|---:|---:|---:|
| all |20|422|78,315,187|
| dev |3|57|10,782,441|

Native validation passed for both. Complete SHA256 inventory and preserved native manifests are linked by `runs/paperbench-data-prepare-10372686/result.json` (SHA256 `93c21d5cd150fb18db6a9e78e8ccd93a451a30382ef38a48cc2ea21736dfa7dd`). Final content89,097,628bytes; shared free space378,260,160,512bytes at completion. Both dataset directories are read-only. No missing/failed files in the successful receipts; historical failed attempt retained. No seed/paraphrase/revision/scoring/auditing was run.
