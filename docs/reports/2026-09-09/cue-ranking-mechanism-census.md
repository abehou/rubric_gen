# Ranking-policy mechanism census

Complete frozen comparison: 60 matched assignments × two auditors. No provider calls or exclusions.

## Full-trajectory transitions: original trace → ranking trace

| Confirmed RH transition | Auditor rows |
|---|---:|
| 0->0 | 75 |
| 0->1 | 36 |
| 1->0 | 5 |
| 1->1 | 4 |

## Actual online exposure in the ranking arm

| Exposure | Rows | Original RH-positive | Ranking RH-positive |
|---|---:|---:|---:|
| online_admitted_any_penalty | 36 | 5 | 19 |
| no_online_admission | 44 | 3 | 10 |
| online_admitted_no_penalty | 40 | 1 | 11 |

These are descriptive post-treatment strata. Penalty-checkpoint counts can include retained offline criteria; they do not identify which online criterion was penalized. Admission and assessment do not prove simulator delivery or causal prevention. Case-level auditor reasons, scores, stop behavior, and source state paths are preserved in the adjacent JSON. Next inspect timing and actual feedback for every new-positive case before proposing another policy.
