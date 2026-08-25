# BioMNIBench partial mechanistic judge gap

This figure uses the live partial mechanistic cache for the BioMNIBench
`results20` experiment.

The weak judge is GPT-5.6 Luna. The strong score is the arithmetic mean of
GPT-5.6 Sol and Claude Opus 5. Each assignment must have complete terminal-bank
scores from all three judges at both the initial and final boundaries.

The plotted gap is `weak score - strong score`. A positive value means the weak
judge gives a higher score. The change panel subtracts the initial gap from the
final gap. A negative change means the weak-judge advantage shrank.

This is a convenience analysis of incomplete output. Completion is not random,
and the terminal rubric can differ across assignments and rubric policies. The
figure is not the final mechanistic estimand.

The saved 2026-08-25 09:29 PDT snapshot contains 486 paired assignments. The
mean weak-minus-strong gap falls from 10.83 points to 8.16 points. The paired
change is -2.67 points. By rubric policy, the mean changes are -1.63 static,
-3.03 offline, and -3.52 online. Full feedback has the largest decrease at
-5.47 points across rubric policies.

Run this command to refresh the snapshot:

```bash
MPLCONFIGDIR=/tmp/abehou-task-tmp/matplotlib .venv/bin/python \
  figures/biomnibench-partial-mechanistic-judge-gap/plot.py
```
