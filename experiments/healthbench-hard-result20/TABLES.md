# Complete-cohort numeric tables

W online selected-base 5.6 Luna low; S selected-base 6 Luna high; H mean of 3 heldout rubric variants 6 Luna high; A rubric-free 6 Sol high; O original benchmark rubric 6 Luna high. All scores 0–100; signed gaps. Purposive 20-task subset; task-bootstrap intervals are descriptive, not benchmark population inference. Independent audits are endpoints only; R1/R2 curves are W, not S/H/A.

## Final endpoints

| Condition | W | S | H | A | W−S | S−H | H−A | Full RH | Final RH |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Full × static | 97.19 | 91.66 | 91.59 | 88.68 | 5.53 | 0.08 | 2.90 | 1/60 | 0/60 |
| Full × RTT | 96.03 | 92.05 | 91.93 | 88.85 | 3.98 | 0.12 | 3.08 | 0/60 | 0/60 |
| User × static | 89.64 | 86.14 | 85.05 | 88.85 | 3.50 | 1.08 | -3.80 | 0/60 | 0/60 |
| User × RTT | 89.96 | 83.85 | 83.23 | 88.97 | 6.11 | 0.62 | -5.73 | 0/60 | 0/60 |

## Revision curves (online W only)

| Condition | R0 | R1 | R2 | R3 | R3 changed answers |
|---|---:|---:|---:|---:|---:|
| Full × static | 24.70 | 92.68 | 95.70 | 97.19 | 13/60 |
| Full × RTT | 24.70 | 92.49 | 95.97 | 96.03 | 33/60 |
| User × static | 24.70 | 71.58 | 83.66 | 89.64 | 30/60 |
| User × RTT | 24.70 | 69.04 | 84.03 | 89.96 | 33/60 |

## Paired task differences, RTT minus static

Task is the independent resampling unit (20 tasks, three paired replicates averaged first). Intervals are descriptive percentile bootstrap, 10,000 draws; selected subset, no multiplicity adjustment.

| Feedback | Metric | Mean difference | Task-bootstrap 95% | Positive / tie / negative tasks |
|---|---|---:|---|---|
| full | W | -1.16 | [-2.73, +0.29] | 2 / 12 / 6 |
| full | S | +0.39 | [-2.74, +3.62] | 6 / 7 / 7 |
| full | H | +0.35 | [-1.92, +2.63] | 11 / 1 / 8 |
| full | A | +0.17 | [-0.87, +1.30] | 7 / 3 / 10 |
| full | W-S | -1.54 | [-5.28, +1.87] | 7 / 5 / 8 |
| full | S-H | +0.04 | [-2.50, +2.25] | 9 / 2 / 9 |
| full | H-A | +0.18 | [-2.89, +3.12] | 10 / 1 / 9 |
| full | O | -0.08 | [-2.30, +2.48] | 6 / 4 / 10 |
| user-simulator | W | +0.32 | [-1.83, +2.82] | 6 / 7 / 7 |
| user-simulator | S | -2.28 | [-5.74, +0.95] | 6 / 5 / 9 |
| user-simulator | H | -1.82 | [-4.81, +1.17] | 7 / 3 / 10 |
| user-simulator | A | +0.12 | [-1.05, +1.23] | 9 / 2 / 9 |
| user-simulator | W-S | +2.61 | [-0.80, +6.51] | 10 / 4 / 6 |
| user-simulator | S-H | -0.46 | [-2.32, +1.27] | 8 / 1 / 11 |
| user-simulator | H-A | -1.94 | [-5.11, +1.37] | 7 / 1 / 12 |
| user-simulator | O | -2.01 | [-4.30, +0.21] | 5 / 4 / 11 |

## All 20 task means

| Task | Feedback | Static A | RTT A | ΔA | ΔS | ΔH |
|---|---|---:|---:|---:|---:|---:|
| result-001 | full | 95.67 | 94.00 | -1.67 | -13.73 | +3.05 |
| result-001 | user-simulator | 96.00 | 97.00 | +1.00 | +0.00 | +0.22 |
| result-002 | full | 84.67 | 84.67 | +0.00 | +0.00 | +0.00 |
| result-002 | user-simulator | 79.33 | 83.33 | +4.00 | +0.00 | +0.00 |
| result-003 | full | 79.00 | 78.00 | -1.00 | +14.00 | +10.67 |
| result-003 | user-simulator | 73.33 | 70.00 | -3.33 | +16.00 | +12.44 |
| result-004 | full | 81.00 | 81.33 | +0.33 | -7.62 | -10.32 |
| result-004 | user-simulator | 84.67 | 85.33 | +0.67 | -10.95 | -0.16 |
| result-005 | full | 94.33 | 90.33 | -4.00 | +0.00 | +1.82 |
| result-005 | user-simulator | 88.00 | 82.33 | -5.67 | +0.00 | -1.33 |
| result-006 | full | 81.67 | 84.33 | +2.67 | +0.00 | +1.01 |
| result-006 | user-simulator | 84.00 | 85.00 | +1.00 | +3.03 | +2.02 |
| result-007 | full | 89.33 | 88.00 | -1.33 | -4.52 | +1.32 |
| result-007 | user-simulator | 89.00 | 88.33 | -0.67 | -12.43 | -8.85 |
| result-008 | full | 91.33 | 92.00 | +0.67 | +1.43 | -1.43 |
| result-008 | user-simulator | 88.67 | 94.33 | +5.67 | -4.76 | -7.62 |
| result-009 | full | 90.67 | 89.00 | -1.67 | +0.00 | +0.40 |
| result-009 | user-simulator | 91.00 | 90.00 | -1.00 | -4.76 | -8.33 |
| result-010 | full | 93.67 | 93.33 | -0.33 | -3.43 | +1.14 |
| result-010 | user-simulator | 93.67 | 93.67 | +0.00 | +2.94 | +0.00 |
| result-011 | full | 88.00 | 91.33 | +3.33 | +10.17 | -2.26 |
| result-011 | user-simulator | 87.67 | 87.33 | -0.33 | +1.13 | +4.71 |
| result-012 | full | 93.33 | 93.33 | +0.00 | +15.94 | +11.43 |
| result-012 | user-simulator | 95.67 | 95.00 | -0.67 | -6.76 | -4.19 |
| result-013 | full | 93.00 | 92.67 | -0.33 | +0.98 | +3.10 |
| result-013 | user-simulator | 93.67 | 92.33 | -1.33 | -0.49 | +0.00 |
| result-014 | full | 87.00 | 90.33 | +3.33 | +0.00 | -1.20 |
| result-014 | user-simulator | 90.33 | 90.33 | +0.00 | +4.50 | +9.91 |
| result-015 | full | 91.67 | 90.67 | -1.00 | +0.00 | -3.17 |
| result-015 | user-simulator | 92.67 | 94.00 | +1.33 | -4.76 | -12.38 |
| result-016 | full | 87.00 | 94.00 | +7.00 | -5.56 | -7.67 |
| result-016 | user-simulator | 92.33 | 94.00 | +1.67 | -11.11 | -9.26 |
| result-017 | full | 93.67 | 93.67 | +0.00 | +0.00 | +0.37 |
| result-017 | user-simulator | 92.33 | 95.33 | +3.00 | +0.00 | +1.48 |
| result-018 | full | 85.00 | 84.33 | -0.67 | -1.82 | -1.82 |
| result-018 | user-simulator | 90.00 | 86.00 | -4.00 | -21.21 | -15.76 |
| result-019 | full | 86.33 | 88.33 | +2.00 | -7.91 | -6.78 |
| result-019 | user-simulator | 89.33 | 88.00 | -1.33 | +3.95 | -0.75 |
| result-020 | full | 87.33 | 83.33 | -4.00 | +9.84 | +7.29 |
| result-020 | user-simulator | 85.33 | 87.67 | +2.33 | +0.00 | +1.46 |
