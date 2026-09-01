# BioMNIBench Results20 user-simulator/full evaluation figures

These figures use `experiments/biomnibench-results20-user-simulator-full.yaml`.
The source is the completed `biomnibench-da-factorial-r10-4f4d5d178756`
evaluation report.

`quality_gains_by_condition` covers four evaluation endpoints:

- strong scoring with the original master rubric;
- scoring with the sealed held-out rubrics;
- rubric-free holistic absolute scoring;
- rubric-free pairwise preference for the final answer.

Let `W` be the final weak original-rubric score.
Let `O` be the final strong original-rubric score.
Let `S` be the final strong selected-rubric score.
Let `H` be the final strong held-out-rubric score.
Let `A` be the final rubric-free absolute score.
Let `P` be pairwise preference for the final artifact over the initial artifact.

`generalization_gaps_by_condition` shows three final-artifact score gaps:

- weak to strong: `W - O`;
- strong selected to strong held-out: `S - H`;
- strong original to rubric-free holistic: `O - A`.

The plot uses no initial-artifact score and no gain difference.
The prior selected-to-holistic value was `S - A`.
It was valid but did not match the requested selected-to-held-out comparison.

`strong_vs_pairwise_by_condition` plots the final `O` score against `P`.
It does not subtract them because `O` uses score points and `P` uses probability.
Pairwise preference necessarily compares the final artifact with the initial artifact.

## Exploratory many-facet Rasch model

`fit_many_facet_rasch.py` converts each final score gap into an audit trigger.
A gap triggers when its first score is strictly greater than its second score.
The script fits condition propensity, task difficulty, and audit-family severity.
It uses sum-to-zero constraints for the task and audit-family facets.

The zero threshold was not prespecified before data collection.
The Rasch estimates are therefore exploratory.
The additive task-method decomposition also fails its task-by-method diagnostic.
Use `rasch_condition_propensity` as a descriptive result, not a validated latent RH scale.
The unrestricted task-by-method item model fits much better.
However, six items have all-zero or all-one outcomes.
Their unregularized maximum-likelihood difficulties are not stable.
A primary latent-scale analysis needs regularized unrestricted item difficulties.

The condition, contrast, and facet CSV files contain estimates and artifact-clustered intervals.
`rasch_model_summary.json` contains fit diagnostics and the exact source hash.

Bars are task-balanced descriptive means.
Whiskers are 95% percentile-bootstrap intervals clustered by task.
Each task mean uses its available completed replicates.
The analysis includes 317 completed revisions and excludes 43 failed revisions.
The CSV contains all plotted estimates, intervals, sample sizes, and the exact
source-summary hash.

Run this command to regenerate the CSV, PNG files, and PDF files:

```bash
MPLCONFIGDIR=/tmp/abehou-task-tmp/matplotlib .venv/bin/python \
  figures/biomnibench-results20-user-simulator-full-evaluation/plot.py

MPLCONFIGDIR=/tmp/abehou-task-tmp/matplotlib .venv/bin/python \
  figures/biomnibench-results20-user-simulator-full-evaluation/fit_many_facet_rasch.py
```
