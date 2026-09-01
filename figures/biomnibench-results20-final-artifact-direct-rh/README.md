# BioMNIBench Results20 final-artifact direct RH

This figure audits only the original task instruction and sealed final artifacts.
It excludes revision history, feedback, scores, rubrics, and tool records.

The configured GPT-5.6 Sol, Claude Opus 5, and Gemini 3.6 Flash panel uses the
`any_detect` rule. Labels show detected and evaluated assignment counts.

GPT-5.6 Sol and Claude Opus 5 completed all 317 assignments. Gemini 3.6 Flash
failed all calls because both configured Google keys reported depleted prepaid
credits. The configured three-judge endpoint is therefore not identified.
The judge plot gives the two complete judge-specific results and marks Gemini
unavailable. Because the configured endpoint is not identified, the main figure shows the
available GPT-and-Claude `any_detect` diagnostic. The CSV also retains sharp
bounds for the configured three-judge endpoint.

Run:

```bash
MPLCONFIGDIR=/tmp/abehou-task-tmp/matplotlib .venv/bin/python \
  figures/biomnibench-results20-final-artifact-direct-rh/plot.py
```
