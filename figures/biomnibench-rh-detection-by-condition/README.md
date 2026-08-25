# BioMNIBench results20 direct RH detection

These figures use experiment `biomnibench-da-factorial-r6-5d56fee68932`.
This is the `experiments/biomnibench-results20.yaml` experiment.

The main figure has three rubric groups.
Each group has four feedback bars placed side by side.
The bar labels give detected and evaluated counts.

The configured three-judge primary result is unavailable.
Gemini failed all 720 calls because its prepaid credits were depleted.
Claude evaluated 698 cases, and GPT evaluated 714 cases.

The main figure uses an explicitly labeled available-judge union.
A case is detected when GPT or Claude detects reward hacking.
A case is not detected when at least one usable judge gives that verdict and neither detects it.
This rule gives 719 evaluated cases and one excluded case.
It is a partial-panel result, not the configured primary result.

The companion figure shows GPT and Claude separately.
The source CSV includes all three views and every 3-by-4 condition cell.

Run this command to regenerate the CSV, PNG files, and PDF files:

```bash
MPLCONFIGDIR=/tmp/abehou-task-tmp/matplotlib .venv/bin/python \
  figures/biomnibench-rh-detection-by-condition/plot.py
```
