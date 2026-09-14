# PaperBench stop and cleanup handoff

**As of:** 2026-09-13 21:40 EDT

All PaperBench scientific execution has been stopped after the corrected static
Results20 baseline reached terminal coverage. No PaperBench provider work remains
in the Slurm queue. The separate `trace-*` work and BioMNIBench work were left
untouched.

## Terminal scientific result

The final corrected selected-neutral / heldout-rigorous static Results20 baseline
is complete and remains the result of interest:

| Condition | Revisions | Sol | Opus | W | S | H | A | Mean S-H |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Full-static | 60/60 | 900/900 | 900/900 | 97.8003 | 63.2648 | 62.3260 | 33.9417 | +0.9389 |
| User-simulator-static | 60/60 | 900/900 | 900/900 | 87.1752 | 63.4416 | 62.9950 | 39.2583 | +0.4466 |

The complete report and machine-readable result are already present on the
integration branch:

- `docs/reports/2026-09-12/paperbench-static/selected-neutral-heldout-rigorous-results20-final.md`
- `docs/reports/2026-09-12/paperbench-static/selected-neutral-heldout-rigorous-results20-final.json`

The broader 16-cell non-trace expansion was intentionally stopped at 2/16
terminal conditions. Its partial outputs remain preserved for provenance; they
are not represented as complete scientific results.

## PaperBench jobs stopped

A final `squeue -u aydanh` check showed only `trace-*` jobs. The PaperBench jobs
were canceled without rerunning valid work:

| Job | State/action | Reason |
|---|---|---|
| 10424672 | canceled after 9:51:59 | stale audit/finalization owner; 120/120 assignments already present and no active provider slot |
| 10424681 | canceled before execution | held score-only-offline audit owner |
| 10424684 | canceled before execution | held Full/User dev3 audit owner |
| 10422051 | canceled before execution | superseded score-only-offline audit chain |
| 10424410 | canceled before execution | superseded score-only-offline recovery chain |
| 10422649 | canceled before execution | failed-prerequisite Full/User dev3 audit chain |
| 10424419 | canceled before execution | downstream stale dev3 audit chain |
| 10422655 | canceled before execution | failed-prerequisite Full/User Results20 producer |

No revision, valid rubric judgment, detector result, holistic result, seed, or
paraphrase pool was deleted or rerun during shutdown.

## Conservative cleanup

The NFS inventory before cleanup reported 18 MB available and 36,576 free
inodes, with 100% bytes and inode utilization. Cleanup job **10432176** removed
only the five provider-free validation roots below. They were reproducible
schema/decoder experiments rather than scientific outputs, had no live or queued
owner, and their conclusions are retained in the committed PaperBench reports.

| Deleted root | Bytes measured before deletion | Files |
|---|---:|---:|
| `runs/paperbench-count-safe-audit-validation-v4-20260910` | 1,187,196 | 17 |
| `runs/paperbench-count-safe-audit-validation-v5-20260910` | 1,353,650 | 21 |
| `runs/paperbench-keyed-audit-validation-v1-20260910` | 1,256,757 | 13 |
| `runs/paperbench-keyed-audit-validation-v2-20260910` | 1,239,192 | 13 |
| `runs/paperbench-keyed-audit-validation-v3-20260910` | 1,328,198 | 13 |
| **Total** | **6,364,993** | **77** |

The post-cleanup check reported 24 MB available and 49,108 free inodes. The
filesystem is still effectively full, so this cleanup restores only small
headroom. No larger PaperBench root was deleted because its scientific,
provenance, or failure-evidence role could not be safely ruled out. In
particular, the canonical seeds, corrected paraphrase pool, final study/audit,
partial non-trace outputs, historical failure evidence, and reports remain.

## Repository and next owner

This handoff is based on `origin/aydan-red-team` at
`7f05584190e29c24f161a18ad0d1eba845f8520a`. The CPU-resource-audit worktree and
all trace/BioMNIBench work remain separate. The next available execution focus
is the red-team-trace session after it independently verifies NFS capacity.
