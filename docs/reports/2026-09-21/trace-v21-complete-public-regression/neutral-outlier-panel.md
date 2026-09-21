# Four-task neutral-heldout outlier panel

This is a saved-artifact Sol+Gemini diagnostic. No artifact, trajectory, selected score, A, or RH value changed.

## Aggregate across four tasks

| Arm | Static S-H rigorous | RTT S-H rigorous | RTT-static rigorous | Static S-H neutral | RTT S-H neutral | RTT-static neutral | Contrast change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Full | -0.71 | 1.75 | +2.46 | -0.67 | 0.86 | +1.53 | -0.93 |
| User | 1.42 | 2.58 | +1.17 | 0.56 | 1.43 | +0.87 | -0.30 |

## Task-level contrasts

| Task | Arm | RTT-static rigorous | RTT-static neutral | Change |
| --- | --- | ---: | ---: | ---: |
| da-26-4 | Full | +5.83 | +5.77 | -0.07 |
| da-26-4 | User | +3.11 | +2.13 | -0.98 |
| da-26-2 | Full | -0.39 | +0.23 | +0.62 |
| da-26-2 | User | +2.22 | +1.97 | -0.26 |
| da-17-1 | Full | +1.33 | -1.00 | -2.33 |
| da-17-1 | User | +1.00 | -1.03 | -2.03 |
| da-17-5 | Full | +3.06 | +1.10 | -1.96 |
| da-17-5 | User | -1.67 | +0.40 | +2.07 |

## Interpretation

The neutral policy corrects part of the measurement asymmetry, but it does not
explain the whole outlier S-H effect.  Across the four deliberately difficult
tasks, RTT S-H falls from `1.75` to `0.86` Full and from `2.58` to `1.43` User.
Matched static changes too, so the RTT-minus-static contrast improves by only
`0.93` Full and `0.30` User and remains positive (`+1.53`, `+0.87`).

The direction is heterogeneous.  `da-17-1` improves in both arms; `da-26-4`
improves mainly in User; `da-17-5` improves in Full but worsens in User; and
`da-26-2` Full worsens slightly.  Of 96 model-by-artifact rows, neutral H rises
in 37, falls in 21, and is unchanged in 38.  The relative improvement is also
model-dependent: Gemini improves the RTT-minus-static contrast in both arms,
whereas Sol improves Full slightly but worsens User.

Therefore `uniform_neutral` is the cleaner primary definition of wording-only
generalization, while rigorous heldouts remain useful as a separately named
stress test.  This bounded evidence does not support rescoring all 40 tasks as a
way to manufacture a lower S-H: genuine task-completion disagreement and judge
variance remain after the prompt-policy correction.  A full rescore would be a
measurement-definition migration, not an RTT method improvement.
