# HealthBench Hard Haiku Result50

50 tasks ×8 conditions ×3 replicates,3 revision rounds;150 trajectories per condition. Scores/gaps use0–100; RH uses positives/all150, including abstentions.

The tables include the completed saved-evidence S/H and RH corrections. Original audit records and numeric RH scores are retained; the latest RH-only review does not change W/S/H/A, gaps, answers or population.

## Haiku50 — current results

| Condition | W | S | H | A | W−S | S−H | H−A | Full trajectory RH | Final artifact RH |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Full × Static | 88.39 | 82.88 | 80.78 | 82.45 | 5.51 | 2.11 | -1.68 | 52/150 (34.7%) | 0/150 (0.0%) |
| Full × RTT | 86.65 | 79.30 | 80.38 | 82.45 | 7.35 | -1.08 | -2.07 | 35/150 (23.3%) | 0/150 (0.0%) |
| Semi × Static | 92.76 | 87.45 | 85.86 | 80.02 | 5.31 | 1.60 | 5.84 | 48/150 (32.0%) | 2/150 (1.3%) |
| Semi × RTT | 93.20 | 88.36 | 88.68 | 79.55 | 4.84 | -0.32 | 9.13 | 45/150 (30.0%) | 0/150 (0.0%) |
| Score-only × Static | 31.50 | 32.14 | 28.98 | 85.09 | -0.64 | 3.16 | -56.11 | 13/150 (8.7%) | 4/150 (2.7%) |
| Score-only × RTT | 28.66 | 27.04 | 28.28 | 84.43 | 1.62 | -1.24 | -56.16 | 11/150 (7.3%) | 1/150 (0.7%) |
| User × Static | 73.62 | 70.15 | 68.52 | 81.25 | 3.47 | 1.63 | -12.73 | 18/150 (12.0%) | 1/150 (0.7%) |
| User × RTT | 72.13 | 68.72 | 68.52 | 81.69 | 3.40 | 0.20 | -13.17 | 17/150 (11.3%) | 1/150 (0.7%) |

## Luna50 — previously published results

| Condition | W | S | H | A | W−S | S−H | H−A | Full trajectory RH | Final artifact RH |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Full × Static | 94.41 | 90.03 | 88.61 | 86.19 | 4.38 | 1.42 | 2.42 | 26/150 (17.3%) | 0/150 (0.0%) |
| Full × RTT | 92.01 | 88.60 | 88.02 | 87.61 | 3.41 | 0.58 | 0.41 | 17/150 (11.3%) | 1/150 (0.7%) |
| Semi × Static | 92.84 | 89.31 | 87.61 | 86.73 | 3.53 | 1.70 | 0.88 | 23/150 (15.3%) | 1/150 (0.7%) |
| Semi × RTT | 91.57 | 88.00 | 87.32 | 86.38 | 3.57 | 0.68 | 0.94 | 20/150 (13.3%) | 1/150 (0.7%) |
| Score-only × Static | 27.35 | 25.69 | 25.60 | 91.55 | 1.65 | 0.10 | -65.96 | 5/150 (3.3%) | 0/150 (0.0%) |
| Score-only × RTT | 27.95 | 25.59 | 26.46 | 92.02 | 2.35 | -0.87 | -65.56 | 3/150 (2.0%) | 0/150 (0.0%) |
| User × Static | 85.77 | 82.42 | 81.03 | 87.41 | 3.35 | 1.39 | -6.39 | 7/150 (4.7%) | 1/150 (0.7%) |
| User × RTT | 85.58 | 79.77 | 80.12 | 88.17 | 5.81 | -0.35 | -8.06 | 3/150 (2.0%) | 0/150 (0.0%) |

## Matched comparison

Both runs cover the same50 source tasks and3 replicates; all150 initial answer files match byte-for-byte. Haiku replaces the revision solver, online W and user simulator, and RTT components; this is not a Haiku-from-scratch seed run. Both use6Luna-high S/H/RH and6Sol-high A/pairwise. W uses a different model in each run, so it is not a common-judge quality comparison.

| Policy | Haiku full RH: Static → RTT | Luna full RH: Static → RTT | Haiku A: Static → RTT | Luna A: Static → RTT |
|---|---:|---:|---:|---:|
| Full | 34.7% → 23.3% | 17.3% → 11.3% | 82.45 → 82.45 | 86.19 → 87.61 |
| Semi | 32.0% → 30.0% | 15.3% → 13.3% | 80.02 → 79.55 | 86.73 → 86.38 |
| Score-only | 8.7% → 7.3% | 3.3% → 2.0% | 85.09 → 84.43 | 91.55 → 92.02 |
| User | 12.0% → 11.3% | 4.7% → 2.0% | 81.25 → 81.69 | 87.41 → 88.17 |

- Full-trajectory RH is lower for RTT than Static in each of the four policies in both reported tables. Haiku reductions are11.33,2.00,1.33,0.67 percentage points; Luna reductions are6.00,2.00,1.33,2.67.
- Haiku full-trajectory RH is higher than Luna in all eight cells. Its A scores are3.74–7.59 points lower across the matched cells; this is a between-run difference, not a claim of within-run degradation.
- Within Haiku, RTT minus Static S−H is−3.19/−1.92/−4.40/−1.43 points (Full/Semi/Score-only/User). These are signed gap differences; negative gaps do not by themselves demonstrate better independent quality.

## Verification and evidence

- [Machine-readable results](results.json): all1200 assignment endpoints and RH judgments.
- [Correction evidence](review-corrections.json): prior criterion/RH corrections and the latest22 RH-window changes, with saved evidence paths and reasons.
- [Offline export/verification](publish_results.py): checks population, aggregates, gap arithmetic, all RH windows, unchanged score fields and shared initial answers.
- Local originals: `runs/healthbench-haiku50-20261009/{matrix-analysis.json,review/}`. Referenced run artifacts remain local, not bundled into this Git publication.
- [Previously published Luna50](../healthbench-hard-result50/RESULTS.md).

This publication performs no API calls and changes no experimental outcomes.
