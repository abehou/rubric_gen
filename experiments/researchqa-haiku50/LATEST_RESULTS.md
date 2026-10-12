# ResearchQA Haiku Result50 — latest results

Updated 2026-10-11. **50 matched tasks × 3 replicates × 3 revision rounds × 8 conditions**; 150 assignments per condition. Initial answers and rubric paraphrases are reused.

Scores are on a 0–100 scale and include the latest saved evidence corrections. W is the reviewed endpoint score; original online W is preserved below and in the [per-assignment data](latest-results.json). Gaps are computed before rounding.

| Condition | W | S | H | A | W−S | S−H | H−A | Full trajectory RH | Final artifact RH |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Full Static | 90.29 | 90.21 | 90.01 | 85.10 | 0.08 | 0.20 | 4.91 | 13/150 (8.7%) | 0/150 (0.0%) |
| Full RTT | 90.04 | 89.74 | 89.83 | 85.59 | 0.30 | -0.09 | 4.23 | 2/150 (1.3%) | 0/150 (0.0%) |
| Semi Static | 93.08 | 91.99 | 90.74 | 83.62 | 1.09 | 1.25 | 7.12 | 14/150 (9.3%) | 0/150 (0.0%) |
| Semi RTT | 93.65 | 92.64 | 92.60 | 83.59 | 1.00 | 0.04 | 9.01 | 8/150 (5.3%) | 0/150 (0.0%) |
| Score-only Static | 74.22 | 74.17 | 73.95 | 87.48 | 0.05 | 0.23 | -13.53 | 0/150 (0.0%) | 0/150 (0.0%) |
| Score-only RTT | 74.49 | 74.44 | 74.38 | 87.45 | 0.05 | 0.06 | -13.08 | 0/150 (0.0%) | 0/150 (0.0%) |
| User Static | 87.69 | 85.99 | 83.81 | 75.29 | 1.70 | 2.17 | 8.52 | 7/150 (4.7%) | 0/150 (0.0%) |
| User RTT | 87.62 | 85.00 | 85.91 | 75.10 | 2.62 | -0.91 | 10.81 | 3/150 (2.0%) | 0/150 (0.0%) |

RH denominators include abstentions. Full-trajectory abstentions (Static/RTT): Full 1/4, Semi 3/3, Score-only 1/1, User 3/5. Final-artifact abstentions: zero.

Final-artifact RH means exploitation detectable from the final answer alone. Zero does not establish that all earlier RH effects were repaired. The latest [artifact-window review](FINAL_ARTIFACT_REVIEW.md) leaves all labels unchanged.

## Models

Revision uses `claude-haiku-5-5`: low effort for solver revisions, online W/feedback and user simulator; high effort for RTT trajectory generation, diagnostics, criterion proposing and validation. Independent S/H/RH use `gpt-6-luna` high. A/pairwise use `gpt-6-luna` high for the retained16 tasks and `gpt-6-sol` high for the additional34 tasks. H averages the original three heldout paraphrases.

## Original online W

| Condition | Original online W | Reviewed endpoint W |
|---|---:|---:|
| Full Static | 88.84 | 90.29 |
| Full RTT | 88.19 | 90.04 |
| Semi Static | 91.12 | 93.08 |
| Semi RTT | 91.45 | 93.65 |
| Score-only Static | 72.31 | 74.22 |
| Score-only RTT | 72.09 | 74.49 |
| User Static | 84.71 | 87.69 |
| User RTT | 85.15 | 87.62 |

## Verification

The published 1,200 assignment rows reproduce all eight means, three gaps and RH count distributions. Original online scores, saved answers and prior review evidence remain preserved locally. This publication did not run new experiments or change any score or label.
