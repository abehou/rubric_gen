# BioMNIBench red-team — 2026-09-05

Completed formal study: 240 assignments, seven audit stages, 9,327 unique
judgments, with Sol / Claude Opus 5 / Gemini 3.8 Flash. Luna generated revisions
and rubrics. This is the dataset historically called v7, not a rerun.

Start with [the report](reports/REPORT.md) and [frozen outcomes](reports/outcomes.json).
`study/` and `audit/` are the formal analysis population; `acceptance/` holds
the successful small end-to-end test. Do not pool acceptance or red-team sidecars
into formal outcomes. Five response-validation fallbacks and six excluded
sidecars remain preserved and reported.

`provenance/` contains sealed source/config and recovery evidence, including
intermediate attempts. Those archives are evidence, not additional analysis runs.
`reports/` preserves all original report/checkpoint bytes. Newly generated
material belongs outside these attested trees: `supplementary-analysis/` holds
an additional CSV discovered during relocation, preserved without modification.

## Relocation integrity

Six pre-move inventories cover 121,937 files. Sibling `*.location.json` receipts
bind each new directory to its original root and inventory SHA-256. Original
records, paths and hashes were not rewritten. Offline analysis resolves saved
identities using those receipts and fails on changed/missing/additional files.
Do not add files inside the six attested components.

From the repository root, use:

```sh
.venv/bin/python scripts/diagnostics/check_audit_coverage.py runs/biomnibench-redteam-2026-09-05/study runs/biomnibench-redteam-2026-09-05/audit
.venv/bin/python scripts/diagnostics/summarize_outcomes.py runs/biomnibench-redteam-2026-09-05/study runs/biomnibench-redteam-2026-09-05/audit
```

These are private offline readers, not production resume support. The current
YAMLs now name separate fresh-execution destinations; do not run them expecting
to resume this relocated dataset. Choose a descriptive dated identity before
the next experiment. Original frozen YAMLs remain in provenance.

See [cleanup record](CLEANUP.md), [results index](../../EXPERIMENT_RUNS.md),
[failure lessons](../../EXPERIMENT_RELIABILITY.md) and
[original GitHub backup](../../GITHUB_BACKUP.md). The remote backup retains its
original layout and has not been replaced by this local cleanup.
