# BioMNIBench Results20 final-revision direct RH

This figure audits only the last artifact-producing revision. It includes the
prior artifact as context, its feedback, the last revision trajectory, and the
sealed final outputs. It excludes all earlier revision behavior and any later
no-change stopping probe.

The configured GPT-5.6 Sol, Claude Opus 5, and Gemini 3.6 Flash panel uses the
`any_detect` rule. Labels show detected and evaluated assignment counts.

All 951 judge assignments completed. Three assignments abstained. The primary
detection rates were 0.0%, 1.8%, and 1.8% for full feedback under the fixed,
offline, and online rubrics. The corresponding user-simulator rates were 2.0%,
4.1%, and 8.2%.

Run:

```bash
DIRECT_RH_WINDOW=final_revision \
DIRECT_RH_FIGURE_ROOT=figures/biomnibench-results20-final-revision-direct-rh \
MPLCONFIGDIR=/tmp/abehou-task-tmp/matplotlib .venv/bin/python \
  figures/biomnibench-results20-final-artifact-direct-rh/plot.py
```
