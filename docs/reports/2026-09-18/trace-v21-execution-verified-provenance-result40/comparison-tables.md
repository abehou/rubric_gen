# BioMNIBench Original Result20 — current corrected results

Updated 2026-10-12. Eight conditions; each has 20 tasks × 3 replicates = 60 assignments. W/S/H/A and all four gaps are score points. RH reports only full trajectory and final artifact; confirmed-positive counts use all 60 assignments, with abstentions retained rather than relabeled negative.

These tables include the saved-evidence manual corrections documented below, not a new model-generated audit. Raw model judgments, revisions, rubrics, W/A and RH are unchanged. H remains the mean of the original three heldouts. Gaps are computed before rounding. No new provider calls were made for this review or publication.

The displayed RH windows use their original Sol/Opus judgments. Earlier Haiku fallback records for other, omitted windows retain their actual model provenance in the source history.

For correction evidence see [current Original20 report](../../2026-10-12/biomnibench-original20/README.md).

## gpt-5.6-sol

| Condition | W | S | H | A | W−S | S−H | H−A | W−A | RH full trajectory | RH final artifact |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Full Static | 96.72 | 87.07 | 86.32 | 64.75 | 9.65 | 0.74 | 21.57 | 31.97 | 20.00% | 1.67% |
| Full RTT | 94.40 | 88.82 | 88.58 | 72.23 | 5.58 | 0.23 | 16.35 | 22.17 | 6.67% | 1.67% |
| User Static | 89.58 | 82.00 | 79.26 | 72.63 | 7.58 | 2.74 | 6.62 | 16.95 | 18.33% | 0.00% |
| User RTT | 89.63 | 80.65 | 80.14 | 79.50 | 8.98 | 0.51 | 0.64 | 10.13 | 5.00% | 0.00% |
| Semi Static | 81.70 | 69.08 | 67.30 | 79.27 | 12.62 | 1.78 | -11.97 | 2.43 | 6.67% | 0.00% |
| Semi RTT | 84.73 | 71.55 | 71.04 | 81.30 | 13.18 | 0.51 | -10.26 | 3.43 | 1.67% | 0.00% |
| Score-only Static | 63.42 | 52.53 | 51.28 | 82.58 | 10.88 | 1.26 | -31.31 | -19.17 | 10.00% | 0.00% |
| Score-only RTT | 71.50 | 62.87 | 62.54 | 81.00 | 8.63 | 0.33 | -18.46 | -9.50 | 1.67% | 0.00% |

Historical abstentions retained: Full Static: full 2, final 0.

## claude-opus-5

| Condition | W | S | H | A | W−S | S−H | H−A | W−A | RH full trajectory | RH final artifact |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Full Static | 96.72 | 90.97 | 88.77 | 70.17 | 5.75 | 2.20 | 18.60 | 26.55 | 21.67% | 5.00% |
| Full RTT | 94.40 | 89.50 | 88.06 | 77.00 | 4.90 | 1.44 | 11.06 | 17.40 | 3.33% | 1.67% |
| User Static | 89.58 | 82.48 | 81.48 | 68.32 | 7.10 | 1.01 | 13.16 | 21.27 | 21.67% | 0.00% |
| User RTT | 89.63 | 82.12 | 81.06 | 72.27 | 7.52 | 1.06 | 8.79 | 17.37 | 1.67% | 0.00% |
| Semi Static | 81.70 | 72.22 | 71.18 | 80.85 | 9.48 | 1.04 | -9.67 | 0.85 | 6.67% | 0.00% |
| Semi RTT | 84.73 | 75.55 | 75.16 | 79.30 | 9.18 | 0.39 | -4.14 | 5.43 | 0.00% | 0.00% |
| Score-only Static | 63.42 | 57.75 | 55.92 | 80.97 | 5.67 | 1.83 | -25.05 | -17.55 | 3.33% | 0.00% |
| Score-only RTT | 71.50 | 65.30 | 64.94 | 77.35 | 6.20 | 0.36 | -12.41 | -5.85 | 0.00% | 0.00% |

Historical abstentions retained: Full Static: full 2, final 0; Full RTT: full 1, final 0; User Static: full 2, final 0; User RTT: full 2, final 0; Semi RTT: full 0, final 1.

---

The following New20 and cumulative40 tables are the historical 2026-09-19 snapshot. New20 has not changed; cumulative40 has not been recomputed with the 2026-10-12 Original20 corrections and must not be presented as a current corrected Result40. Old Original20 rows have been replaced by the current tables above. Historical Gemini-containing panels are not part of the current Sol/Opus report.

# Historical New20 / Result40 compact tables

Gap cells are score points. RH cells are confirmed-positive auditor-row percentages; abstentions remain in each denominator. Delta rows are promoted RTT minus matched static, in points and percentage points respectively.

## GPT-5.6 Sol + Claude Opus 5

| Population | Arm | Condition | W−S | S−H | H−A | W−A | RH full | RH post | RH artifact | RH revision |
|---|---|---|---|---|---|---|---|---|---|---|
| Newly added 20 | Full | Static | 8.25 | 0.07 | 26.73 | 35.05 | 29.17 | 4.17 | 6.67 | 1.67 |
| Newly added 20 | Full | Promoted RTT | 8.73 | 0.69 | 17.89 | 27.32 | 10.00 | 0.83 | 0.83 | 0.00 |
| Newly added 20 | Full | RTT − static | 0.48 | 0.63 | -8.84 | -7.73 | -19.17 | -3.33 | -5.83 | -1.67 |
| Newly added 20 | User | Static | 8.53 | 1.02 | 12.02 | 21.57 | 15.83 | 5.83 | 2.50 | 0.83 |
| Newly added 20 | User | Promoted RTT | 7.76 | 1.77 | 9.97 | 19.50 | 5.83 | 2.50 | 0.00 | 0.00 |
| Newly added 20 | User | RTT − static | -0.78 | 0.74 | -2.04 | -2.08 | -10.00 | -3.33 | -2.50 | -0.83 |
| Cumulative 40 | Full | Static | 7.97 | 0.77 | 23.41 | 32.15 | 25.00 | 2.92 | 5.00 | 1.25 |
| Cumulative 40 | Full | Promoted RTT | 6.99 | 0.80 | 15.76 | 23.55 | 7.50 | 1.67 | 1.25 | 0.83 |
| Cumulative 40 | Full | RTT − static | -0.99 | 0.03 | -7.65 | -8.60 | -17.50 | -1.25 | -3.75 | -0.42 |
| Cumulative 40 | User | Static | 7.94 | 1.19 | 11.21 | 20.34 | 17.92 | 8.75 | 1.25 | 2.92 |
| Cumulative 40 | User | Promoted RTT | 7.80 | 1.57 | 7.26 | 16.62 | 4.58 | 3.33 | 0.00 | 0.83 |
| Cumulative 40 | User | RTT − static | -0.14 | 0.38 | -3.95 | -3.72 | -13.33 | -5.42 | -1.25 | -2.08 |

## GPT-5.6 Sol

| Population | Arm | Condition | W−S | S−H | H−A | W−A | RH full | RH post | RH artifact | RH revision |
|---|---|---|---|---|---|---|---|---|---|---|
| Newly added 20 | Full | Static | 9.18 | -0.34 | 27.76 | 36.60 | 30.00 | 5.00 | 5.00 | 3.33 |
| Newly added 20 | Full | Promoted RTT | 9.88 | 0.35 | 15.75 | 25.98 | 13.33 | 1.67 | 0.00 | 0.00 |
| Newly added 20 | Full | RTT − static | 0.70 | 0.69 | -12.01 | -10.62 | -16.67 | -3.33 | -5.00 | -3.33 |
| Newly added 20 | User | Static | 9.87 | 0.99 | 7.44 | 18.30 | 21.67 | 6.67 | 3.33 | 0.00 |
| Newly added 20 | User | Promoted RTT | 9.68 | 1.74 | 6.06 | 17.48 | 8.33 | 5.00 | 0.00 | 0.00 |
| Newly added 20 | User | RTT − static | -0.18 | 0.75 | -1.38 | -0.82 | -13.33 | -1.67 | -3.33 | 0.00 |
| Cumulative 40 | Full | Static | 9.42 | 0.20 | 24.66 | 34.28 | 25.00 | 3.33 | 3.33 | 1.67 |
| Cumulative 40 | Full | Promoted RTT | 7.73 | 0.29 | 16.05 | 24.07 | 10.00 | 2.50 | 0.83 | 0.83 |
| Cumulative 40 | Full | RTT − static | -1.68 | 0.09 | -8.61 | -10.21 | -15.00 | -0.83 | -2.50 | -0.83 |
| Cumulative 40 | User | Static | 8.72 | 1.87 | 7.03 | 17.62 | 20.00 | 9.17 | 1.67 | 1.67 |
| Cumulative 40 | User | Promoted RTT | 8.92 | 1.51 | 3.39 | 13.81 | 6.67 | 5.00 | 0.00 | 0.83 |
| Cumulative 40 | User | RTT − static | 0.19 | -0.36 | -3.64 | -3.82 | -13.33 | -4.17 | -1.67 | -0.83 |

## Claude Opus 5

| Population | Arm | Condition | W−S | S−H | H−A | W−A | RH full | RH post | RH artifact | RH revision |
|---|---|---|---|---|---|---|---|---|---|---|
| Newly added 20 | Full | Static | 7.32 | 0.47 | 25.71 | 33.50 | 28.33 | 3.33 | 8.33 | 0.00 |
| Newly added 20 | Full | Promoted RTT | 7.58 | 1.04 | 20.03 | 28.65 | 6.67 | 0.00 | 1.67 | 0.00 |
| Newly added 20 | Full | RTT − static | 0.27 | 0.57 | -5.68 | -4.85 | -21.67 | -3.33 | -6.67 | 0.00 |
| Newly added 20 | User | Static | 7.20 | 1.05 | 16.60 | 24.85 | 10.00 | 5.00 | 1.67 | 1.67 |
| Newly added 20 | User | Promoted RTT | 5.83 | 1.79 | 13.89 | 21.52 | 3.33 | 0.00 | 0.00 | 0.00 |
| Newly added 20 | User | RTT − static | -1.37 | 0.74 | -2.71 | -3.33 | -6.67 | -5.00 | -1.67 | -1.67 |
| Cumulative 40 | Full | Static | 6.53 | 1.34 | 22.16 | 30.02 | 25.00 | 2.50 | 6.67 | 0.83 |
| Cumulative 40 | Full | Promoted RTT | 6.24 | 1.31 | 15.47 | 23.02 | 5.00 | 0.83 | 1.67 | 0.83 |
| Cumulative 40 | Full | RTT − static | -0.29 | -0.03 | -6.68 | -7.00 | -20.00 | -1.67 | -5.00 | 0.00 |
| Cumulative 40 | User | Static | 7.15 | 0.52 | 15.39 | 23.06 | 15.83 | 8.33 | 0.83 | 4.17 |
| Cumulative 40 | User | Promoted RTT | 6.67 | 1.64 | 11.13 | 19.44 | 2.50 | 1.67 | 0.00 | 0.83 |
| Cumulative 40 | User | RTT − static | -0.47 | 1.12 | -4.26 | -3.62 | -13.33 | -6.67 | -0.83 | -3.33 |

## Gemini 3.8 Flash

| Population | Arm | Condition | W−S | S−H | H−A | W−A | RH full | RH post | RH artifact | RH revision |
|---|---|---|---|---|---|---|---|---|---|---|
| Newly added 20 | Full | Static | -0.10 | 0.14 | 4.61 | 4.65 | 8.33 | 0.00 | 3.33 | 0.00 |
| Newly added 20 | Full | Promoted RTT | 1.42 | 0.74 | 1.41 | 3.57 | 5.00 | 0.00 | 0.00 | 0.00 |
| Newly added 20 | Full | RTT − static | 1.52 | 0.59 | -3.19 | -1.08 | -3.33 | 0.00 | -3.33 | 0.00 |
| Newly added 20 | User | Static | -0.52 | 0.26 | -0.86 | -1.12 | 1.67 | 1.67 | 0.00 | 0.00 |
| Newly added 20 | User | Promoted RTT | 0.90 | 0.84 | -0.81 | 0.93 | 0.00 | 0.00 | 0.00 | 0.00 |
| Newly added 20 | User | RTT − static | 1.42 | 0.58 | 0.06 | 2.05 | -1.67 | -1.67 | 0.00 | 0.00 |
| Cumulative 40 | Full | Static | -0.12 | 0.41 | 2.84 | 3.13 | 5.00 | 0.00 | 1.67 | 0.00 |
| Cumulative 40 | Full | Promoted RTT | 0.71 | 0.58 | -1.16 | 0.12 | 2.50 | 0.00 | 0.83 | 0.00 |
| Cumulative 40 | Full | RTT − static | 0.82 | 0.17 | -4.00 | -3.01 | -2.50 | 0.00 | -0.83 | 0.00 |
| Cumulative 40 | User | Static | -1.86 | -0.18 | -0.98 | -3.02 | 2.50 | 0.83 | 0.00 | 0.00 |
| Cumulative 40 | User | Promoted RTT | -0.07 | 0.32 | -2.18 | -1.93 | 0.00 | 0.00 | 0.00 | 0.00 |
| Cumulative 40 | User | RTT − static | 1.78 | 0.50 | -1.20 | 1.08 | -2.50 | -0.83 | 0.00 | 0.00 |

## GPT-5.6 Sol + Claude Opus 5 + Gemini 3.8 Flash

| Population | Arm | Condition | W−S | S−H | H−A | W−A | RH full | RH post | RH artifact | RH revision |
|---|---|---|---|---|---|---|---|---|---|---|
| Newly added 20 | Full | Static | 5.47 | 0.09 | 19.36 | 24.92 | 22.22 | 2.78 | 5.56 | 1.11 |
| Newly added 20 | Full | Promoted RTT | 6.29 | 0.71 | 12.40 | 19.40 | 8.33 | 0.56 | 0.56 | 0.00 |
| Newly added 20 | Full | RTT − static | 0.83 | 0.62 | -6.96 | -5.52 | -13.89 | -2.22 | -5.00 | -1.11 |
| Newly added 20 | User | Static | 5.52 | 0.77 | 7.73 | 14.01 | 11.11 | 4.44 | 1.67 | 0.56 |
| Newly added 20 | User | Promoted RTT | 5.47 | 1.46 | 6.38 | 13.31 | 3.89 | 1.67 | 0.00 | 0.00 |
| Newly added 20 | User | RTT − static | -0.04 | 0.69 | -1.34 | -0.70 | -7.22 | -2.78 | -1.67 | -0.56 |
| Cumulative 40 | Full | Static | 5.28 | 0.65 | 16.55 | 22.48 | 18.33 | 1.94 | 3.89 | 0.83 |
| Cumulative 40 | Full | Promoted RTT | 4.89 | 0.73 | 10.12 | 15.74 | 5.83 | 1.11 | 1.11 | 0.56 |
| Cumulative 40 | Full | RTT − static | -0.38 | 0.08 | -6.43 | -6.74 | -12.50 | -0.83 | -2.78 | -0.28 |
| Cumulative 40 | User | Static | 4.67 | 0.74 | 7.15 | 12.56 | 12.78 | 6.11 | 0.83 | 1.94 |
| Cumulative 40 | User | Promoted RTT | 5.17 | 1.15 | 4.11 | 10.44 | 3.06 | 2.22 | 0.00 | 0.56 |
| Cumulative 40 | User | RTT − static | 0.50 | 0.42 | -3.04 | -2.12 | -9.72 | -3.89 | -0.83 | -1.39 |
