# Static control versus neutral revision guidance

All 24 assignments and both auditors are retained; strict coverage passed before aggregation. Higher signed gaps indicate greater rubric/holistic mismatch. Direct RH percentages here are individual auditor votes; matched rows average those votes. The unchanged primary any-detect endpoint is reported separately.

| Auditor | Arm | Feedback | Weak−strong | Selected−holdout | Original−quality | Quality | Final RH % | Trajectory RH % |
|---|---|---|---:|---:|---:|---:|---:|---:|
| gpt-5.6-sol | control | full-static | 15.33 | -1.83 | 17.50 | 64.33 | 0.00 | 50.00 |
| gpt-5.6-sol | control | user-simulator-static | 7.67 | -2.28 | 13.00 | 69.33 | 0.00 | 16.67 |
| gpt-5.6-sol | neutral | full-static | 18.83 | -2.33 | 15.67 | 65.50 | 0.00 | 16.67 |
| gpt-5.6-sol | neutral | user-simulator-static | 8.00 | -4.61 | -3.33 | 74.00 | 0.00 | 33.33 |
| claude-opus-5 | control | full-static | 13.50 | 7.44 | 17.83 | 65.83 | 0.00 | 33.33 |
| claude-opus-5 | control | user-simulator-static | 5.17 | 0.17 | 18.67 | 66.17 | 0.00 | 16.67 |
| claude-opus-5 | neutral | full-static | 8.50 | -0.89 | 24.00 | 67.50 | 0.00 | 16.67 |
| claude-opus-5 | neutral | user-simulator-static | 8.50 | -3.22 | 3.67 | 66.50 | 0.00 | 16.67 |
| matched-mean | control | full-static | 14.42 | 2.81 | 17.67 | 65.08 | 0.00 | 41.67 |
| matched-mean | control | user-simulator-static | 6.42 | -1.06 | 15.83 | 67.75 | 0.00 | 16.67 |
| matched-mean | neutral | full-static | 13.67 | -1.61 | 19.83 | 66.50 | 0.00 | 16.67 |
| matched-mean | neutral | user-simulator-static | 8.25 | -3.92 | 0.17 | 70.25 | 0.00 | 25.00 |

## Neutral minus control

| Auditor | Feedback | Weak−strong Δ | Selected−holdout Δ | Original−quality Δ | Quality Δ | Final RH pp | Trajectory RH pp |
|---|---|---:|---:|---:|---:|---:|---:|
| gpt-5.6-sol | full-static | 3.50 | -0.50 | -1.83 | 1.17 | 0.00 | -33.33 |
| gpt-5.6-sol | user-simulator-static | 0.33 | -2.33 | -16.33 | 4.67 | 0.00 | 16.67 |
| claude-opus-5 | full-static | -5.00 | -8.33 | 6.17 | 1.67 | 0.00 | -16.67 |
| claude-opus-5 | user-simulator-static | 3.33 | -3.39 | -15.00 | 0.33 | 0.00 | 0.00 |
| matched-mean | full-static | -0.75 | -4.42 | 2.17 | 1.42 | 0.00 | -25.00 |
| matched-mean | user-simulator-static | 1.83 | -2.86 | -15.67 | 2.50 | 0.00 | 8.33 |

## Primary any-detect

| Arm | Feedback | Final RH % | Trajectory RH % |
|---|---|---:|---:|
| control | full-static | 0.00 | 50.00 |
| control | user-simulator-static | 0.00 | 33.33 |
| neutral | full-static | 0.00 | 16.67 |
| neutral | user-simulator-static | 0.00 | 33.33 |

Per-task values, abstentions and raw-evidence paths are retained in results.json. No task was excluded and no detector threshold or metric definition changed.
