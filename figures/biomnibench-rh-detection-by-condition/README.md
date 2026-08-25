# BioMNIBench direct RH detection by condition

This figure shows the earlier three-task BioMNIBench development factorial.
It does not show the incomplete `results20` experiment.

The experiment ID is `biomnibench-da-factorial-r6-99fcc39acc68`.
The direct panel used the `any_detect` rule across three judges.
The run used the earlier positive-point elicitation protocol.

The original combined summary directory is no longer present.
The source counts were recovered from its saved analysis transcript.
The totals match the retained experiment log:

- Static rubric: 6/36 detected, or 16.7%.
- Offline elicited rubric: 6/33 detected, or 18.2%.
- Online elicited rubric: 7/36 detected, or 19.4%.

Three offline/full panels abstained.
The plot excludes those panels from the offline rate.

The chart stacks detected assignment counts because counts are additive.
It does not stack the four cell rates because those rates are not additive.
Each segment label gives the detected and evaluated counts for that cell.

Run this command to regenerate the PNG and PDF files:

```bash
MPLCONFIGDIR=/tmp/abehou-task-tmp/matplotlib .venv/bin/python \
  figures/biomnibench-rh-detection-by-condition/plot.py
```
