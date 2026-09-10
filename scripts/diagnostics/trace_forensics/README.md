# Saved Result20 forensic readers

These private stdlib scripts read existing artifacts. They do not import the experiment workflow, call providers, execute solver commands, or mutate saved runs. New large extracts go to the absolute NFS `OUT` in `collect.py`; published report/table files go to `docs/reports/2026-09-10/trace-forensics/`.

Read NFS through a Slurm compute allocation. The investigation used allocation 10386249 on babel-l5-16, with four CPUs and 64 GiB; this was a saved-data inspection job, not a behavioral experiment. Never point a workflow launcher at these scripts. `read_only.sbatch` is the allocation receipt, not an experiment config.

Reproduction order:

1. `collect.py`: validate source receipts and native generation file hashes; collect all 239 assignments and 478 saved auditor rows.
2. `enrich.py`: map ordinal score rows to stable criterion IDs and verify penalty sums. `collect.py` alone is not the final criterion-delivery extract.
3. `traces.py`: normalize natural trajectories for the union of original/candidate positive User cases, with original line numbers and hashes.
4. `summarize.py`: compute full proposal, support, lifecycle, and gap census tables.
5. `support_review.py`: select the explicit 29-criterion/53-pair human-review sample. `--show` is a bounded reader, not a new judge.
6. `provenance.py`: compare source/config/prompt/lineage identities and preservation/audit-recovery receipts.
7. `gap_review.py`: extract final artifacts, existing quality rationales and natural traces for the largest gap contributors.
8. `followups.py`: original-positive timings, first-continuation divergence and recovery completion cohorts.
9. `finalize.py`: validate the manually supplied candidate evidence anchors, compile case timelines and support annotations, and compute paired statistical resamples of fixed records. It removes redundant full feedback from rectangular CSVs; the positive-case evidence JSON retains actual feedback.
10. `appendices.py`: render report appendices from the tables, preserving the authored main report.
11. `verify.py`: check published data invariants, syntax, local links, and accidental credential patterns, then refresh the report manifest.

`manual-adjudications.json` beside the report is human forensic annotation, not an auditor rerun. Additional human support/original-case annotations are explicitly encoded in `finalize.py` and `followups.py`; reproduce the annotations as supplied, or revise them transparently. The published report separates verified behavior, ambiguity, frozen verdicts, and descriptive causal limits.

`view.py` and `inspect_case.py` are bounded evidence readers. No reader executes text taken from a trajectory. Absolute saved paths may require Babel access; the published evidence dossiers support offline review without it.
