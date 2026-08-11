# Rubric score and reward-hacking detection

## Result

No. The completed runs do not support the claim that a higher rubric score is
associated with more reward hacking (RH).

The primary full-feedback analysis retained 352 assignments with complete
three-model panels. Thirty assignments had a majority RH detection. RH-positive
assignments had a mean final score of 94.1. RH-negative assignments had a mean
of 96.7. The difference was -2.61 points, with a 95% task-cluster interval from
-5.75 to +0.68 points. The raw point-biserial correlation was -0.090, with an
interval from -0.184 to +0.027.

The raw direction is therefore weakly negative, not positive. It is not
statistically distinct from zero.

The fixed score bands show the same descriptive pattern. Assignments below 100
had 11 detections among 82 complete panels (13.4%). Assignments at 100 had 19
detections among 270 panels (7.0%). For the broader any-detector outcome, the
rates were 41.5% below 100 and 22.2% at 100. These band comparisons do not
control task or condition.

## Adjusted analysis

The strict adjusted model compares replicates within the same task, feedback
policy, prompt, and rubric policy. Its full-feedback estimate was +6.37
percentage points of majority RH risk per 10 final-score points. The 95%
task-cluster interval was -12.35 to +15.23 percentage points. The within-cell
permutation p-value was 0.316.

This estimate does not provide positive evidence. Its sign differs from the raw
association, and its interval includes large effects in both directions. Only 8
of 120 cells had variation in both final score and majority RH status. Also, 270
of 352 complete-panel assignments had a final score of exactly 100. The adjusted
estimate is therefore unstable and has little effective information.

## Sensitivity checks

| Analysis | Complete assignments / RH positive | Raw correlation | RH-positive minus RH-negative score | Adjusted RH change per +10 points | Permutation p |
|---|---:|---:|---:|---:|---:|
| Full, majority, final score | 352 / 30 | -0.090 | -2.61 | +6.37 pp | 0.316 |
| Full, any detector, final score | 352 / 94 | -0.190 | -3.48 | -4.22 pp | 0.521 |
| Semi, majority, final score | 352 / 17 | +0.030 | +3.21 | +0.31 pp | 0.752 |
| Full, majority, score gain | 352 / 30 | +0.064 | +5.56 | -0.94 pp | 0.498 |
| Full prospective, majority, final score | 174 / 17 | -0.092 | -2.95 | +9.36 pp | 0.296 |

The full-feedback individual detectors also disagree after adjustment:

- GPT: -2.45 percentage points per 10 score points; p=0.590.
- Claude: +5.12 percentage points per 10 score points; p=0.400.
- Gemini: +2.43 percentage points per 10 score points; p=0.483.

The nearest positive result was the pooled GPT analysis across both feedback
studies. Its adjusted estimate was +2.61 percentage points per 10 points, with
p=0.059. Its detector-family false-discovery-rate q-value was 0.302. This result
does not survive correction and does not appear in the full-feedback run alone.

No revision round had a significant majority association after correction. The
full-feedback round-family q-values were all at least 0.624. The semi-feedback
q-values were all at least 0.823.

## Semi-feedback results

The semi-feedback run gives the same null conclusion. It retained 352 complete
panels, with 17 majority RH detections. RH-positive assignments had a mean final
score of 86.0. RH-negative assignments had a mean of 82.8. The difference was
+3.21 points, with a 95% task-cluster interval from -3.56 to +9.84 points.

The raw point-biserial correlation was +0.030, with an interval from -0.031 to
+0.086. The strict adjusted estimate was +0.31 percentage points of RH risk per
10 final-score points. Its interval was -0.96 to +1.28 percentage points, and
the permutation p-value was 0.752. Only 12 of 120 cells varied in both score and
majority RH status.

The score-band rates were not monotonic. Assignments below 100 had 11 detections
among 194 complete panels (5.7%). Assignments at 100 had 6 detections among 158
panels (3.8%). The intermediate bands ranged from 0.0% to 11.1%, with no steady
increase as scores rose.

Static and prospective arms did not agree in direction:

- Static: raw r=+0.078; adjusted +0.39 percentage points per 10 points; p=0.744.
- Prospective: raw r=-0.039; adjusted -0.20 percentage points per 10 points;
  p=1.000.

The broader any-detector outcome also gave no supported relation. Its raw
correlation was -0.084. Its adjusted estimate was +2.16 percentage points per
10 points, with an interval from -2.10 to +6.70 and p=0.185.

GPT produced the nearest positive detector-specific result. Its adjusted
estimate was +2.96 percentage points per 10 points, with p=0.041. However, the
task-cluster interval was -1.08 to +7.03, and its detector-family q-value was
0.302. Claude gave +0.48 percentage points with p=0.569. Gemini gave -0.90
percentage points with p=0.163. These inconsistent results do not support a
common positive association.

## Interpretation

The available evidence supports a null conclusion. It does not show that higher
rubric scores accompany higher RH rates. The unadjusted full-feedback data point
in the opposite direction, but that inverse association is also uncertain.

This analysis cannot estimate causality. The score and the final RH judgment
both summarize the same revision trajectory. A detected behavior can affect the
score, and score feedback can affect later behavior. Task difficulty can affect
both measures.

Prospective runs also change their scoring rubric. Their scores are not on an
identical measurement target. Policy-specific and within-cell results reduce
this problem, but they do not create a common evaluator.

The score ceiling is the main statistical limit. More assignments or more score
variation will not fix the changing-target problem. A strong next test needs a
fixed blinded outcome evaluator and an independent RH audit.

## Method

The analysis uses the 11 values in each schema-1 `state.json` `scores` array.
The primary predictor is the final score. Secondary predictors are the baseline
score, final-minus-baseline gain, and mean post-baseline score.

The primary outcome is a strict complete-panel majority across GPT, Claude, and
Gemini. The any-detector and model-specific labels are sensitivity outcomes.

Raw correlations are point-biserial Pearson correlations. Confidence intervals
resample the 30 tasks. Adjusted linear-risk models remove means within each
task-by-study-by-prompt-by-rubric-policy cell. Their intervals resample tasks,
and their p-values permute scores among replicates within those cells.

## Reproduction

```bash
MPLCONFIGDIR=/tmp/rubric-score-mpl \
  uv run python scripts/analyze_rubric_score_rh.py
```

The output directory also contains assignment-level joined data, association
tables, round analyses, score-band rates, a JSON summary, and PNG/PDF figures.
