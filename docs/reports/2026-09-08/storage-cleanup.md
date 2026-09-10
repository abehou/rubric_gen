# Run storage inventory and cleanup

2026-09-08 EDT. Inventory job10362871 found41top-level directories,20.10GiB of apparent file bytes. No disposable Python/test caches were found outside protected runtime directories.

Archived **117 verified terminal Slurm logs** into `runs/archive/slurm-20260908/`, preserving every byte and SHA-256. Active, pending, and unverified logs remain at their original paths. No scientific run directory or shared input pool was deleted.

The archive manifest (local-only: `investigation/runs-cleanup-20260908/log-archive-manifest.json`; hash recorded in the local-evidence manifest) maps every original log path to its archive path; the inventory (local-only: `investigation/runs-cleanup-20260908/inventory.json`; hash recorded in the local-evidence manifest) retains counts and classifications.

## Retained directories

| Path | GiB | Files | Role | Decision |
|---|---:|---:|---|---|
| `runs/babel-result20-current-20260908` | 4.061 | 111331 | active runtime/source/provenance | Retain |
| `runs/babel-dev3-concern1-20260907` | 2.898 | 2717 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/babel-result20-capacity-v3-20260908` | 2.305 | 40445 | active runtime/source/provenance | Retain |
| `runs/autonomous-dev3-20260907` | 1.481 | 11762 | shared reproducibility inputs | Retain |
| `runs/babel-code` | 1.477 | 15663 | active runtime/source/provenance | Retain |
| `runs/babel-result20-input-restore-10356965` | 1.378 | 2156 | shared reproducibility inputs | Retain |
| `runs/babel-result20-input-restore-10356929` | 1.378 | 2155 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/babel-dev3-package-policy-20260908` | 1.347 | 6975 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/babel-dev3-concern1-policy-early-20260908` | 0.915 | 2677 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/static-neutral-20260907` | 0.447 | 8512 | important historical/control evidence | Retain |
| `runs/babel-dev3-concern1-policy-controls-20260908` | 0.378 | 3828 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/babel-dev3-attention-policy-20260908` | 0.272 | 4926 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/babel-dev3-20260907` | 0.201 | 3809 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/babel-dev3-context-20260907` | 0.159 | 2642 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/babel-dev3-single-issue-20260907` | 0.148 | 1757 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/babel-dev3-package-context-20260907` | 0.139 | 2703 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/babel-dev3-package-three-20260908` | 0.132 | 1530 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/babel-dev3-completion-request-20260908` | 0.130 | 1749 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/babel-dev3-attention-control-20260907` | 0.125 | 2552 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/babel-dev3-package-atomic-20260908` | 0.111 | 1312 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/babel-dev3-preserve-work-20260908` | 0.107 | 1754 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/babel-dev3-material-review-20260908` | 0.107 | 1751 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/babel-dev3-outcome-request-20260908` | 0.076 | 1469 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/babel-dev3-concern1-replication-20260908` | 0.075 | 1747 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/babel-overnight-20260907` | 0.073 | 688 | active runtime/source/provenance | Retain |
| `runs/babel-dev3-package-replication-20260908` | 0.070 | 1771 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/.runtime-babel` | 0.031 | 140 | active runtime/source/provenance | Retain |
| `runs/babel-dev3-public-review-20260907` | 0.028 | 1466 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/biomnibench-redteam-2026-09-05` | 0.024 | 34 | important historical/control evidence | Retain |
| `runs/babel-dev3-da18-inputs-20260908` | 0.015 | 85 | shared reproducibility inputs | Retain |
| `runs/biomnibench-results20-2026-09-06` | 0.007 | 5 | important historical/control evidence | Retain |
| `runs/selected-reference-wiring-smoke-20260907-attempt02` | 0.002 | 155 | important historical/control evidence | Retain |
| `runs/telemetry-journal-check-10360844` | 0.000 | 5 | diagnostic acceptance evidence | Retain |
| `runs/result20-telemetry-acceptance-10361125` | 0.000 | 7 | diagnostic acceptance evidence | Retain |
| `runs/runtime-performance-10362795` | 0.000 | 1 | diagnostic acceptance evidence | Retain |
| `runs/request-compaction-provider-10362844` | 0.000 | 4 | diagnostic acceptance evidence | Retain |
| `runs/babel-result20-capacity-20260908` | 0.000 | 7 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/request-compaction-measure-10362791` | 0.000 | 1 | diagnostic acceptance evidence | Retain |
| `runs/archive` | 0.000 | 8 | exploratory or infrastructure evidence; review before removal | Retain |
| `runs/result20-telemetry-acceptance-10361108` | 0.000 | 3 | diagnostic acceptance evidence | Retain |
| `runs/babel-dev3-input-readiness-20260908` | 0.000 | 1 | diagnostic acceptance evidence | Retain |

## Remaining cleanup

Review individual obsolete exploratory attempts after the canonical comparison is complete and their conclusions/config/commits are indexed. Preserve shared seed/paraphrase pools, scientific controls/negative evidence, all paper-claim artifacts, active owners and source seals. Similar names or failed Slurm status alone do not establish that a folder is disposable.
