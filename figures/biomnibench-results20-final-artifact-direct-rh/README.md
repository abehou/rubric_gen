# BioMNIBench Results20 final-artifact direct RH

This figure audits only the original task instruction and sealed final artifacts.
It excludes revision history, feedback, scores, rubrics, and tool records.

The configured GPT-5.6 Sol, Claude Opus 5, and Gemini 3.6 Flash panel uses the
`any_detect` rule. Labels show detected and evaluated assignment counts.

All three judges completed all 317 assignments. The configured endpoint is
identified except where a judge abstained. The plots and CSV report sharp
missingness bounds for those three assignments.

Run:

```bash
MPLCONFIGDIR=/tmp/abehou-task-tmp/matplotlib .venv/bin/python \
  figures/biomnibench-results20-final-artifact-direct-rh/plot.py
```
