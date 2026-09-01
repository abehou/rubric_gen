# BioMNIBench results20 generalization gaps

These figures use experiment `biomnibench-da-factorial-r6-5d56fee68932`.
This is the `experiments/biomnibench-results20.yaml` experiment.

Each figure has three rubric groups.
Each group has four feedback bars placed side by side.
Each condition cell contains 60 assignments from 20 tasks and three replicates.
The whiskers are task-clustered 95% percentile-bootstrap intervals.

The weak-to-strong figure plots the final-minus-initial change in `W - A`.
Negative values mean that the weak judge's score advantage decreased.
Separate companion figures show the initial and final `W - A` gaps.
Positive values mean that the weak judge gives the higher score.

The strong-to-holistic figure has two panels.
The first plots the active terminal-rubric change in `A - Q`.
The active rubric can differ by condition.
The second plots the common selected-rubric change in `S - Q`.
This common ruler gives the cleaner cross-condition comparison.

`W` is the GPT-5.6 Luna terminal-rubric score.
`A` and `S` use the mean of GPT-5.6 Sol and Claude Opus 5.
`Q` is the rubric-free mean from the same two strong judges.
Gemini was unavailable for the completed mechanistic and holistic panels.

Run this command to regenerate the CSV, PNG files, and PDF files:

```bash
MPLCONFIGDIR=/tmp/abehou-task-tmp/matplotlib .venv/bin/python \
  figures/biomnibench-generalization-gaps-by-condition/plot.py
```
