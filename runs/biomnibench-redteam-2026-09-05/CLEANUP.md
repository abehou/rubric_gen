# Cleanup receipt — 2026-09-06 09:39 CST

The completed dataset (formerly v7) now has a descriptive date-based directory.
All six relocated components passed their pre-move SHA-256 inventories:
study 86,536 files; audit 34,055; reports 19; provenance 104;
acceptance study 637; acceptance audit 586. Total: 121,937 unchanged files.

The relocated analysis ran the full strict completion gate and passed 240
assignments, all seven stages and 9,327 judgments. `relocated-outcomes.json`
equals `reports/outcomes.json` exactly after excluding only the top-level
`study` and `audit` location strings. All scientific values, assignments,
coverage, bootstrap settings and contrasts are unchanged. Twelve regression
tests plus eleven subtests pass, including the preserved small acceptance.

An additional `rh_metrics_by_audit_model.csv` appeared after the inventories
were generated. It was preserved in `supplementary-analysis/`, not deleted or
silently included in the frozen report inventory. Its scientific derivation was
not audited as part of relocation.

## Recoverable removals

The incomplete formal runs v5 and v6d were moved earlier into:
`/Users/yuenanhuang/.Trash/rubric-gen-cleanup-20260906.gCquuY/`.

The following repository-relative directories were moved, preserving their
relative hierarchy, into:
`/Users/yuenanhuang/.Trash/rubric-gen-obsolete-attempts-20260906.GSyyJQ/`.

- `runs/preflights/`: assessment-contract-v4, exact-newlines-v6,
  exact-newlines-v6b, simulator-contract-v2, simulator-contract-v3.
- `runs/preflight-detections/`: assessment-contract-v4, exact-newlines-v6b,
  gemini-transport-v6c, provider-availability-v7, simulator-contract-v3.
- `runs/diagnostics/`: headless-plotting-v6d, thread-runtime-v6d,
  score-derived-v5, import-runtime-v7-recovery, full-audit-v2-failure-probe.
- `runs/provenance/`: 20260905-redteam-v3, -v4, -v5, -v6, -v6b, -v6c, -v6d.
- `runs/github-backup/aydan-red-team`: duplicate local release packages;
  remote checksums had already been verified. The GitHub release is unchanged.

These include superseded diagnostics/acceptance, not exclusively failed calls.
They are outside the final analysis population. Private historical incident
helpers may require these archived fixtures if used again; current completion
and analysis readers use the preserved successful dataset.

Trash has not been emptied: these removals remain recoverable and do not claim
to free disk space. Unrelated older BioMNIBench/PaperBench studies, historical
logs, successful seeds/paraphrases and sealed final provenance remain intact.
The latter intentionally includes failure/recovery evidence; deleting evidence
inside the successful run would bias analysis or break provenance.

No original record/hash was rewritten, no model call was made, and no cleanup
change was pushed to GitHub. Runtime resume at relocated paths is not supported
by this offline-reader change. YAML destinations now identify separate fresh
executions, not the completed relocated dataset.
