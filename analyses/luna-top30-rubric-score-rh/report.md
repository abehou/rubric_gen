# Rubric score and reward-hacking detection

## Result

The revised audit does not support a stable relation between rubric score and
reward hacking (RH). The direction changes with the detector rule and study.

The primary full-feedback analysis retained 356 complete three-model panels.
Five assignments had a majority RH detection. All five had a final score of
100. The other assignments had a mean score of 96.4.

The raw score difference was +3.59 points. Its 95% task-cluster interval was
+1.68 to +5.90 points. The raw point-biserial correlation was +0.053.

This raw result is fragile. Only five majority-positive assignments exist.
Only one of 120 matched cells varies in both final score and majority RH status.

## Adjusted analysis

The adjusted model compares replicates within the same task, study, prompt, and
rubric policy. It estimated +2.80 percentage points of majority RH risk per 10
final-score points. The 95% task-cluster interval was 0.00 to +13.52 points.
The within-cell permutation p-value was 0.331.

The interval is one-sided because the five positive labels sit at the score
ceiling. This result does not establish a positive score-RH relation.

## Sensitivity checks

| Analysis | Complete / RH positive | Raw correlation | Score difference | Adjusted RH change per +10 points | Permutation p |
|---|---:|---:|---:|---:|---:|
| Full, majority, final score | 356 / 5 | +0.053 | +3.59 | +2.80 pp | 0.331 |
| Full, any detector, final score | 356 / 50 | -0.222 | -5.12 | -4.91 pp | 0.309 |
| Semi, majority, final score | 355 / 15 | +0.043 | +5.14 | +0.46 pp | 0.600 |
| Full, majority, score gain | 356 / 5 | +0.045 | +9.10 | -0.10 pp | 0.945 |

The full-feedback individual detectors also disagree:

- GPT: raw correlation -0.206; adjusted -2.59 points per +10 score points; p=0.589.
- Claude: raw correlation +0.033; adjusted +2.74 points; p=0.330.
- Gemini: raw correlation -0.004; adjusted +0.47 points; p=0.856.

The majority and any-detector rules give opposite raw directions. This
difference is more important than the weak majority estimate.

## Score bands

For the full study, the majority rule found 0 of 84 assignments below 100 and
5 of 272 assignments at 100. The any-detector rule found 20 of 84 below 100 and
30 of 272 at 100.

For the semi study, the majority rule found 9 of 198 assignments below 100 and
6 of 157 assignments at 100. The band rates were not monotonic.

These comparisons do not control task or condition.

## Interpretation

The revised majority audit contains too few positives for a reliable score
analysis. The score ceiling makes this problem worse.

The broader any-detector result has more positives, but it gives the opposite
raw direction. Detector choice therefore controls the apparent conclusion.

This analysis cannot estimate causality. Score feedback can change later
behavior. Detected behavior can also affect scores. Dynamic runs change their
scoring rubric, so their scores do not share one fixed measurement target.

A stronger test needs a fixed, blinded outcome judge and independent human RH
labels.

## Method

The analysis uses the 11 values in each schema-1 `state.json` `scores`
array. The primary predictor is the final score.

The primary outcome is a complete-panel majority across GPT, Claude, and
Gemini. Any-detector and model-specific labels are sensitivity outcomes.

Raw correlations are point-biserial Pearson correlations. Confidence intervals
resample the 30 tasks. Adjusted linear-risk models remove means within each
task-study-prompt-rubric cell. Permutation tests shuffle scores within those
cells.

## Reproduction

```bash
MPLCONFIGDIR=/tmp/rubric-score-mpl \
  uv run python scripts/analyze_rubric_score_rh.py
```

The output directory also contains assignment-level data, association tables,
round analyses, score-band rates, a JSON summary, and PNG/PDF figures.
