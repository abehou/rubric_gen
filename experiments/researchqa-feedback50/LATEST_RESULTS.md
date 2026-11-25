# ResearchQA Luna6 Result50

Model labels in this curated export are user-assigned normalized labels, not the original API execution model identifiers. Original experimental records are backed up separately; source identities, scores and RH labels are unchanged.

Current accepted final-endpoint scores on the 0–100 scale. Gaps use unrounded values; H−A is raw. Full-trajectory RH includes valid abstentions in the denominator. Native and adopted values and normalized model labels/source pointers remain separate in the accompanying score exports.

## Luna6 / GPT-6Sol audit

| Condition | n | W | S | H | A | W−S | S−H | H−A | RH | Abstain |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Full Static | 150 | 96.89 | 95.21 | 93.85 | 84.13 | 1.68 | 1.36 | 9.71 | 16/150 | 2 |
| Full RTT | 150 | 97.09 | 95.13 | 95.03 | 87.33 | 1.96 | 0.10 | 7.69 | 7/150 | 6 |
| Semi Static | 150 | 97.65 | 95.52 | 94.58 | 85.40 | 2.13 | 0.94 | 9.18 | 14/150 | 0 |
| Semi RTT | 150 | 98.14 | 96.60 | 96.64 | 87.53 | 1.54 | -0.04 | 9.11 | 8/150 | 4 |
| Score-only Static | 150 | 78.86 | 75.68 | 74.84 | 89.07 | 3.17 | 0.84 | -14.22 | 1/150 | 0 |
| Score-only RTT | 150 | 78.02 | 75.17 | 75.40 | 89.93 | 2.85 | -0.23 | -14.53 | 0/150 | 0 |
| User Static | 150 | 94.17 | 91.00 | 89.92 | 84.93 | 3.17 | 1.08 | 4.99 | 15/150 | 1 |
| User RTT | 150 | 93.84 | 90.76 | 90.62 | 86.40 | 3.08 | 0.14 | 4.22 | 8/150 | 2 |

## Luna6 / ClaudeOpus5 audit

| Condition | n | W | S | H | A | W−S | S−H | H−A | RH | Abstain |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Full Static | 150 | 96.89 | 86.31 | 85.14 | 71.60 | 10.58 | 1.18 | 13.54 | 13/150 | 4 |
| Full RTT | 150 | 97.09 | 86.04 | 85.95 | 76.60 | 11.05 | 0.09 | 9.35 | 8/150 | 3 |
| Semi Static | 150 | 97.65 | 88.06 | 87.07 | 74.67 | 9.60 | 0.99 | 12.40 | 14/150 | 3 |
| Semi RTT | 150 | 98.14 | 89.31 | 88.64 | 77.40 | 8.83 | 0.66 | 11.24 | 3/150 | 6 |
| Score-only Static | 150 | 78.86 | 67.87 | 67.41 | 78.27 | 10.99 | 0.46 | -10.86 | 0/150 | 0 |
| Score-only RTT | 150 | 78.02 | 67.77 | 67.43 | 80.00 | 10.25 | 0.34 | -12.57 | 0/150 | 0 |
| User Static | 150 | 94.17 | 81.53 | 81.47 | 72.33 | 12.64 | 0.06 | 9.13 | 14/150 | 3 |
| User RTT | 150 | 93.84 | 81.10 | 81.29 | 75.40 | 12.74 | -0.19 | 5.89 | 6/150 | 5 |

[Endpoint scores](endpoint-scores.csv) · [Condition scores](condition-scores.csv) · [Original/accepted source pointers](score-provenance.json)
