# New20 uniform-neutral heldout comparison

This is a measurement-only comparison over saved final artifacts. No revision, selected score (S), holistic score (A), or RH judgment changed. Historical H uses three rigorous heldouts; corrected H uses five `uniform_neutral` heldouts.

## Sol + Gemini mean

| Arm | Static S-H rigorous | RTT S-H rigorous | RTT-static rigorous | Static S-H neutral | RTT S-H neutral | RTT-static neutral | RTT S-H change | Contrast change |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Full | -0.10 | 0.54 | +0.64 | -0.32 | -0.23 | +0.09 | -0.77 | -0.55 |
| User | 0.63 | 1.29 | +0.66 | 0.27 | 0.35 | +0.08 | -0.94 | -0.58 |

## Neutral prompt: three versus five heldouts

This isolates the effect of averaging two additional neutral paraphrases; both columns already use the corrected neutral prompt policy.

| Arm | RTT S-H neutral-3 | RTT S-H neutral-5 | Count effect | RTT-static neutral-3 | RTT-static neutral-5 | Contrast count effect |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Full | -0.13 | -0.23 | -0.10 | +0.26 | +0.09 | -0.16 |
| User | 0.38 | 0.35 | -0.03 | +0.09 | +0.08 | -0.01 |

## Task-level uncertainty

SD and SE use the 20 matched task-level RTT-minus-static contrasts; the three replicates and two models are averaged within each task.

| Arm | Rigorous contrast mean ± SD (SE) | Neutral contrast mean ± SD (SE) | Paired change mean ± SD (SE) |
| --- | ---: | ---: | ---: |
| Full | +0.64 ± 2.26 (0.50) | +0.09 ± 2.31 (0.52) | -0.55 ± 1.64 (0.37) |
| User | +0.66 ± 2.32 (0.52) | +0.08 ± 2.14 (0.48) | -0.58 ± 1.43 (0.32) |

## Per model

| Model | Arm | Static rigorous | RTT rigorous | RTT-static rigorous | Static neutral | RTT neutral | RTT-static neutral | Contrast change |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| gpt-5.6-sol | Full | -0.34 | 0.35 | +0.69 | -0.70 | -0.85 | -0.14 | -0.83 |
| gpt-5.6-sol | User | 0.99 | 1.74 | +0.75 | 0.02 | 0.70 | +0.69 | -0.06 |
| gemini-3.8-flash | Full | 0.14 | 0.74 | +0.59 | 0.06 | 0.39 | +0.33 | -0.26 |
| gemini-3.8-flash | User | 0.26 | 0.84 | +0.58 | 0.53 | 0.00 | -0.53 | -1.10 |

## Task-level matched contrasts

| Task | Arm | RTT-static rigorous | RTT-static neutral | Change |
| --- | --- | ---: | ---: | ---: |
| da-8-1 | Full | +0.83 | +0.00 | -0.83 |
| da-8-1 | User | +0.56 | +0.53 | -0.02 |
| da-26-4 | Full | +5.83 | +5.77 | -0.07 |
| da-26-4 | User | +3.11 | +2.13 | -0.98 |
| da-20-4 | Full | -0.83 | -1.50 | -0.67 |
| da-20-4 | User | +3.06 | -0.17 | -3.22 |
| da-19-3 | Full | -0.56 | -0.50 | +0.06 |
| da-19-3 | User | -1.39 | -1.67 | -0.28 |
| da-4-1 | Full | +0.72 | -2.50 | -3.22 |
| da-4-1 | User | +1.06 | -0.90 | -1.96 |
| da-1-3 | Full | +1.00 | -0.40 | -1.40 |
| da-1-3 | User | +0.39 | +1.20 | +0.81 |
| da-3-5 | Full | +0.72 | +1.30 | +0.58 |
| da-3-5 | User | +1.61 | +1.33 | -0.28 |
| da-4-6 | Full | -4.83 | -4.87 | -0.03 |
| da-4-6 | User | -0.17 | -1.80 | -1.63 |
| da-5-1 | Full | +2.22 | +3.60 | +1.38 |
| da-5-1 | User | +3.00 | +4.07 | +1.07 |
| da-26-2 | Full | -0.39 | +0.23 | +0.62 |
| da-26-2 | User | +2.22 | +1.97 | -0.26 |
| da-9-7 | Full | +1.11 | +1.90 | +0.79 |
| da-9-7 | User | +0.22 | +1.10 | +0.88 |
| da-24-3 | Full | +4.11 | -1.37 | -5.48 |
| da-24-3 | User | -3.33 | -1.83 | +1.50 |
| da-6-5 | Full | -0.28 | +0.00 | +0.28 |
| da-6-5 | User | +0.00 | +0.00 | +0.00 |
| da-17-3 | Full | -2.33 | -2.53 | -0.20 |
| da-17-3 | User | +2.72 | +0.03 | -2.69 |
| da-1-4 | Full | -0.28 | -0.17 | +0.11 |
| da-1-4 | User | +1.22 | +0.47 | -0.76 |
| da-8-3 | Full | -0.50 | +0.07 | +0.57 |
| da-8-3 | User | +4.83 | +2.63 | -2.20 |
| da-17-5 | Full | +3.06 | +1.10 | -1.96 |
| da-17-5 | User | -1.67 | +0.40 | +2.07 |
| da-17-1 | Full | +1.33 | -1.00 | -2.33 |
| da-17-1 | User | +1.00 | -1.03 | -2.03 |
| da-9-1 | Full | +0.00 | +0.17 | +0.17 |
| da-9-1 | User | -0.22 | -0.63 | -0.41 |
| da-20-1 | Full | +1.89 | +2.57 | +0.68 |
| da-20-1 | User | -4.94 | -6.23 | -1.29 |
