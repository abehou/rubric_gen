# BioMNIBench Results20 user-simulator/full evaluation figures

These figures use `experiments/biomnibench-results20-user-simulator-full.yaml`.
The source is the completed `biomnibench-da-factorial-r10-4f4d5d178756`
evaluation report.

`quality_gains_by_condition` covers four evaluation endpoints:

- strong scoring with the original master rubric;
- scoring with the sealed held-out rubrics;
- rubric-free holistic absolute scoring;
- rubric-free pairwise preference for the final answer.

`generalization_gaps_by_condition` compares rubric-based gains with holistic
gains. It shows the weak-original, strong-original, and selected-rubric gap
changes.

Bars are descriptive means over completed assignments.
Whiskers are 95% percentile-bootstrap intervals clustered by task.
Each task mean uses its available completed replicates.
The analysis includes 317 completed revisions and excludes 43 failed revisions.
The CSV contains all plotted estimates, intervals, sample sizes, and the exact
source-summary hash.

Run this command to regenerate the CSV, PNG files, and PDF files:

```bash
MPLCONFIGDIR=/tmp/abehou-task-tmp/matplotlib .venv/bin/python \
  figures/biomnibench-results20-user-simulator-full-evaluation/plot.py
```
