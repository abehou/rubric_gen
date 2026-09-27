# HealthBench Hard Result20 — complete 4×2 matrix

20 tasks × 3 replicates per cell. W/S/H/A on 0–100 scale; signed gaps. S/H/A are endpoints, intermediate curves are W only. All RH cells use the corrected answer-only detector, gpt-6-luna high. Raw detector decisions; abstentions are retained, not converted to negatives.

| Feedback | Rubric | W | S | H | A | W−S | S−H | H−A | Full RH | Artifact RH |
|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| full | static | 97.19 | 91.66 | 91.59 | 88.68 | 5.53 | 0.08 | 2.90 | 7/60 | 0/60 |
| full | red-team-trace | 96.03 | 92.05 | 91.93 | 88.85 | 3.98 | 0.12 | 3.08 | 6/60 | 0/60 |
| semi | static | 94.10 | 90.13 | 88.62 | 88.78 | 3.97 | 1.51 | -0.16 | 1/60 | 0/60 |
| semi | red-team-trace | 93.90 | 89.05 | 88.73 | 88.52 | 4.86 | 0.32 | 0.21 | 4/60 | 0/60 |
| score-only | static | 21.58 | 20.88 | 19.53 | 92.17 | 0.70 | 1.35 | -72.63 | 4/60 | 0/60 |
| score-only | red-team-trace | 22.05 | 19.15 | 18.93 | 91.77 | 2.90 | 0.22 | -72.84 | 2/60 | 0/60 |
| user-simulator | static | 89.64 | 86.14 | 85.05 | 88.85 | 3.50 | 1.08 | -3.80 | 2/60 | 0/60 |
| user-simulator | red-team-trace | 89.96 | 83.85 | 83.23 | 88.97 | 6.11 | 0.62 | -5.73 | 0/60 | 0/60 |

## W by revision

Initial answer bytes match across all eight conditions for every task/replicate. The extension reuses seeds but performs its own online W judgments, so its R0 mean is23.34 rather than the original batch's24.70; this is scoring variation, not different starting answers.

| Condition | R0 | R1 | R2 | R3 |
|---|---:|---:|---:|---:|
| full-static | 24.70 | 92.68 | 95.70 | 97.19 |
| full-red-team-trace | 24.70 | 92.49 | 95.97 | 96.03 |
| semi-static | 23.34 | 89.87 | 94.44 | 94.10 |
| semi-red-team-trace | 23.34 | 86.11 | 92.38 | 93.90 |
| score-only-static | 23.34 | 22.93 | 22.40 | 21.58 |
| score-only-red-team-trace | 23.34 | 22.89 | 24.67 | 22.05 |
| user-simulator-static | 24.70 | 71.58 | 83.66 | 89.64 |
| user-simulator-red-team-trace | 24.70 | 69.04 | 84.03 | 89.96 |

## Four RH windows (positive / abstain / total)

| Condition | Full | Post-update | Final revision | Artifact |
|---|---|---|---|---|
| full-static | 7 / 1 / 60 | 1 / 0 / 60 | 0 / 1 / 60 | 0 / 0 / 60 |
| full-red-team-trace | 6 / 2 / 60 | 4 / 0 / 60 | 3 / 1 / 60 | 0 / 0 / 60 |
| semi-static | 1 / 1 / 60 | 0 / 0 / 60 | 1 / 0 / 60 | 0 / 0 / 60 |
| semi-red-team-trace | 4 / 0 / 60 | 0 / 0 / 60 | 0 / 0 / 60 | 0 / 1 / 60 |
| score-only-static | 4 / 0 / 60 | 1 / 0 / 60 | 2 / 0 / 60 | 0 / 0 / 60 |
| score-only-red-team-trace | 2 / 1 / 60 | 0 / 1 / 60 | 0 / 0 / 60 | 0 / 0 / 60 |
| user-simulator-static | 2 / 2 / 60 | 0 / 0 / 60 | 0 / 1 / 60 | 0 / 0 / 60 |
| user-simulator-red-team-trace | 0 / 1 / 60 | 0 / 0 / 60 | 0 / 0 / 60 | 0 / 0 / 60 |

Additional recorded cost: $28.342327; unknown usage: 4.
