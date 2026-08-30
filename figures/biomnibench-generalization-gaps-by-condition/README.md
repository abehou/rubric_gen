# BioMNIBench results20 generalization gaps

These figures use the current experiment ID from
`experiments/biomnibench-results20.yaml`.

Each figure has three rubric groups.
Each group has four feedback bars placed side by side.
Each condition cell contains 60 assignments from 20 tasks and three replicates.
The whiskers are task-clustered 95% percentile-bootstrap intervals.

The weak-to-strong figure plots the final-minus-initial change in `W - A`.
Negative values mean that the weak judge's score advantage decreased.
Separate companion figures show the initial and final `W - A` gaps.
Positive values mean that the weak judge gives the higher score.

The strong-score figure has three panels.
The first plots the original-rubric change in `A - Q`.
The second plots active-rubric drift as the change in `B - A`.
The third plots the selected-rubric change in `S - Q`.
The original and selected rubrics are common rulers.

`W` is the saved GPT-5.6 Luna original-rubric score.
`A` and `S` use the mean of GPT-5.6 Sol and Claude Opus 5.
`B` is the same strong-panel mean under the artifact-specific active rubric.
`Q` is the rubric-free mean from the same two strong judges.
Gemini was unavailable for the completed rubric score and rubric-free panels.

Run this command to regenerate the CSV, PNG files, and PDF files:

```bash
MPLCONFIGDIR=/tmp/abehou-task-tmp/matplotlib .venv/bin/python \
  figures/biomnibench-generalization-gaps-by-condition/plot.py
```
