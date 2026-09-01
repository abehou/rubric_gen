# BioMNIBench Results20 user-simulator/full direct RH detection

These figures use `experiments/biomnibench-results20-user-simulator-full.yaml`.
The source is the completed `biomnibench-da-factorial-r10-4f4d5d178756`
evaluation report.

The main figure shows the configured three-judge `any_detect` panel.
It compares full feedback with user-simulator feedback across the static,
offline-elicited, and online-elicited rubric policies.
It shows full-trajectory and post-update evidence in separate panels.

Bar labels give detected and evaluated counts.
Thin vertical marks show sharp missingness bounds.
The analysis includes 317 completed revisions and excludes 43 failed revisions.
The post-update panel has all 951 judge decisions.
The full-trajectory panel has 948 of 951 judge decisions.

The companion figure shows GPT-5.6 Sol, Claude Opus 5, and Gemini 3.6 Flash
separately for both evidence windows.
The CSV contains all plotted counts, rates, bounds, and the source-summary hash.

Run this command to regenerate the CSV, PNG files, and PDF files:

```bash
MPLCONFIGDIR=/tmp/abehou-task-tmp/matplotlib .venv/bin/python \
  figures/biomnibench-results20-user-simulator-full-direct-rh/plot.py
```
