# Gemini/Qwen solver incident and retirement

## Executive finding

The recurring macOS Python crashes were not one unresolved NumPy defect. They
were a chain of independent containment failures in the Gemini 3.8 Flash Dev3
solver experiment:

1. Gemini sandbox commands resolved `python3` to the global
   `/Library/Frameworks/Python.framework` installation instead of the checkout
   `.venv`.
2. The global interpreter loaded global NumPy/OpenBLAS and, in other attempts,
   Torch/OpenMP. Thirty Python crash reports on 2026-09-19 show native
   OpenBLAS/OpenMP failures; none used NumPy from the checkout `.venv`.
3. A generic environment repair was written around 18:18 JST, but the active
   controller had started at 13:22 JST and was deliberately left running. A
   long-lived Python process does not hot-reload changed modules, so it kept
   spawning children with the old environment. Five more native crashes
   occurred around 19:47 JST.
4. Controller shutdown killed only the direct child process group. Gemini
   sandbox shells created nested sessions/process groups, so Gemini, Bash, and
   global-Python descendants survived as PID-1 orphans. One unsafe SVD process
   had remained alive since 17:57 JST.
5. The solver repeatedly installed Python packages and produced 9.9–14.7 GiB
   H5AD intermediates. Revision snapshots then copied those intermediates into
   multiple immutable submissions and live workspaces, converting one expensive
   computation into tens of GiB of duplicated disk use.
6. Existing tests asserted environment dictionaries but did not execute a real
   child `python3`, verify NumPy provenance, exercise nested process-group
   shutdown, or enforce output/snapshot size ceilings. The progress display also
   counted returned failures, so `35/36` did not mean 35 successful assignments.

## Why earlier fixes did not finish the job

| Repair | What it actually fixed | Why the incident continued |
| --- | --- | --- |
| `MPLBACKEND=Agg` | An earlier Matplotlib macOS GUI abort | It did not affect interpreter selection, BLAS, or OpenMP. |
| Codex-specific PATH/thread controls | Some Codex solver subprocesses | Gemini, Claude, judge, and nested shell paths were not uniformly covered. |
| Generic controlled subprocess environment | Checkout `.venv`, no user site, and one BLAS/OpenMP thread for new children | It existed only on disk; the 13:22 controller was not restarted and kept its old imported code. |
| Direct process-group termination | The provider CLI's own process group | Gemini created additional nested process groups that survived and continued running. |
| Ordinary snapshot exclusions | Known caches and virtual environments | Multi-gigabyte generated `.h5ad` files were ordinary top-level files, so they were copied repeatedly. |

The prior statement that the problem was “fixed without restarting active
experiments” was therefore incorrect. Restarting or retiring every process that
had loaded the old runtime was a required part of this fix.

## Experiment impact before retirement

The 36-assignment Gemini Dev3 state was 21 completed, 14 recorded failures, and
1 interrupted live assignment. The Sol/Opus outcome audit had not started.
Failures included native Python crashes, package-environment failures, disk-full
errors, empty/invalid status reads, one oversized Gemini input, and the final
interrupted turn. This was incomplete operational coverage and could not support
a scientific conclusion.

At peak, the persistent Gemini run occupied roughly 36 GiB and live temporary
workspaces roughly 28 GiB. Available disk space fell to about 23 GiB. The linked
cleanup first removed five oversized H5AD copies and two oversized live copies,
recovering about 56 GiB. Final retirement removed the remaining run/setup trees
and seven matching live roots, recovering roughly another 8 GiB. Available disk
space was about 87 GiB after cleanup.

## Retirement completed at user direction

- Terminated the Gemini Dev3 controller and every confirmed Gemini/Bash/Python
  descendant or orphan process group.
- Removed all seven live roots whose sentinels pointed to the Gemini solver run.
- Permanently removed `runs/gemini38-dev3-no-dropout-local-mac/` and
  `runs/qwen38-dev3-no-dropout-local-mac/`.
- Permanently removed `experiments/gemini38-dev3-no-dropout/` and
  `experiments/qwen38-dev3-no-dropout/` plus their experiment-specific tests.
- Deleted the recurring `run-qwen-no-dropout-dev3` / “Monitor Gemini Dev3”
  automation so it cannot recreate or resume either solver experiment.
- Preserved completed `gemini-result20-audit` evidence because Gemini was an
  auditor there, not the solver.
- Recorded both solver cohorts as retired and non-resumable in the experiment
  plan, run index, and log.

## Retained safeguards

The working tree retains general protections that also benefit the current
higher-priority experiments: checkout-`.venv` subprocess selection, disabled
user-site packages, single-thread BLAS/OpenMP settings, nested descendant-tree
termination, a 512 MiB per-agent-file ceiling, bounded snapshot size/headroom,
and historical snapshot compaction. A real nested-session process test and the
focused environment/resource/snapshot/session suite pass; the final focused run
was 39 tests passed.

No Gemini/Qwen solver process, run directory, experiment-specific configuration,
or recurring automation remained after verification. Reintroducing either solver
later requires a fresh experiment identity and a new real-route smoke after the
current priority work is complete.
