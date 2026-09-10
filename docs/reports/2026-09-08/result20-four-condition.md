# Complete four-condition BioMNIBench Result20

2026-09-08 18:55 EDT

Coverage: **240 assignments, 20 tasks × 3 replicates × 4 conditions**, with complete configured GPT-5.6 Sol and Claude Opus 5 native audits. Gemini is not included. This is completion of the requested comparison, not proof of the desired scientific pattern.

## Scores and gaps

| Condition | W | W_train | S | H | A | W−S | S−H | H−A | W−A | Quality gain |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| Full-feedback static | 96.72 | 96.72 | 89.02 | 87.52 | 67.46 | 7.70 | 1.50 | 20.06 | 29.26 | -6.08 |
| User-simulator static | 90.33 | 90.33 | 83.08 | 82.69 | 75.33 | 7.25 | 0.39 | 7.36 | 15.01 | 1.44 |
| Full-feedback trace | 96.73 | 96.48 | 90.09 | 90.13 | 68.82 | 6.64 | -0.04 | 21.31 | 27.92 | -4.59 |
| User-simulator trace | 89.03 | 88.95 | 81.25 | 80.72 | 71.52 | 7.78 | 0.53 | 9.20 | 17.52 | -1.65 |

W is the selected-base weak score; W_train includes elicited penalties. A is rubric-free holistic quality. Score improvements and penalty-induced reward changes must be distinguished.

## Direct reward hacking

Ranges are abstention identification bounds, not confidence intervals. Matched-panel RH uses the frozen analysis aggregation. Full trajectory, post-update, final-artifact and final-revision windows are different endpoints.

| Condition / auditor | Full trajectory | Post-update | Final artifact | Final revision |
|---|---:|---:|---:|---:|
| Full-feedback static / gpt-5.6-sol | 20.00–23.33% | 1.67–3.33% | 1.67% | 0.00% |
| Full-feedback static / claude-opus-5 | 21.67–25.00% | 1.67% | 5.00% | 1.67% |
| Full-feedback static / matched-panel | 25.00–26.67% | 3.33–5.00% | 6.67% | 1.67% |
| User-simulator static / gpt-5.6-sol | 5.00–6.67% | 1.67% | 0.00% | 0.00% |
| User-simulator static / claude-opus-5 | 3.33–6.67% | 0.00–5.00% | 0.00% | 0.00% |
| User-simulator static / matched-panel | 6.67–10.00% | 1.67–5.00% | 0.00% | 0.00% |
| Full-feedback trace / gpt-5.6-sol | 13.33% | 1.67% | 3.33–5.00% | 0.00–1.67% |
| Full-feedback trace / claude-opus-5 | 11.67% | 3.33–6.67% | 6.67–8.33% | 5.00% |
| Full-feedback trace / matched-panel | 16.67% | 3.33–6.67% | 6.67–8.33% | 5.00% |
| User-simulator trace / gpt-5.6-sol | 13.33% | 3.33–5.00% | 1.67% | 0.00% |
| User-simulator trace / claude-opus-5 | 13.33–16.67% | 6.67–8.33% | 0.00% | 3.33–6.67% |
| User-simulator trace / matched-panel | 20.00–23.33% | 6.67–10.00% | 1.67% | 3.33–6.67% |

## Paired contrasts

Signs follow **left minus right**. RH contrasts are percentage points; uncertainty is the frozen task-bootstrap 95% interval. Intervals including zero do not establish a directional effect.

| Contrast | Metric | Difference / bounds | 95% interval |
|---|---|---:|---:|
| full-static minus user-simulator-static | RH_full_trajectory | 15.00–20.00% | [5.00, 33.33] |
| full-static minus user-simulator-static | RH_post_update | -1.67–3.33% | [-8.33, 10.00] |
| full-static minus user-simulator-static | RH_final_artifact | 6.67% | [0.00, 15.00] |
| full-static minus user-simulator-static | RH_final_revision | 1.67% | [0.00, 5.00] |
| full-static minus user-simulator-static | A | -7.87 | [-12.26, -3.50] |
| full-static minus user-simulator-static | WS | 0.45 | [-3.66, 4.07] |
| full-static minus user-simulator-static | SH | 1.10 | [-0.92, 3.47] |
| full-static minus user-simulator-static | HA | 12.70 | [7.33, 18.35] |
| full-static minus user-simulator-static | WA | 14.25 | [9.15, 19.83] |
| full-static minus full-red-team-trace | RH_full_trajectory | 8.33–10.00% | [0.00, 16.67] |
| full-static minus full-red-team-trace | RH_post_update | -3.33–1.67% | [-11.67, 6.67] |
| full-static minus full-red-team-trace | RH_final_artifact | -1.67–0.00% | [-6.67, 6.67] |
| full-static minus full-red-team-trace | RH_final_revision | -3.33% | [-10.00, 0.00] |
| full-static minus full-red-team-trace | A | -1.36 | [-4.35, 1.40] |
| full-static minus full-red-team-trace | WS | 1.06 | [-1.32, 3.55] |
| full-static minus full-red-team-trace | SH | 1.53 | [-0.41, 3.52] |
| full-static minus full-red-team-trace | HA | -1.25 | [-4.01, 1.19] |
| full-static minus full-red-team-trace | WA | 1.34 | [-1.88, 4.67] |
| user-simulator-static minus user-simulator-red-team-trace | RH_full_trajectory | -16.67–-10.00% | [-28.33, 0.00] |
| user-simulator-static minus user-simulator-red-team-trace | RH_post_update | -8.33–-1.67% | [-15.00, 5.00] |
| user-simulator-static minus user-simulator-red-team-trace | RH_final_artifact | -1.67% | [-5.00, 0.00] |
| user-simulator-static minus user-simulator-red-team-trace | RH_final_revision | -6.67–-3.33% | [-13.33, 0.00] |
| user-simulator-static minus user-simulator-red-team-trace | A | 3.81 | [0.33, 8.17] |
| user-simulator-static minus user-simulator-red-team-trace | WS | -0.53 | [-4.02, 2.69] |
| user-simulator-static minus user-simulator-red-team-trace | SH | -0.14 | [-1.64, 1.27] |
| user-simulator-static minus user-simulator-red-team-trace | HA | -1.84 | [-5.79, 2.15] |
| user-simulator-static minus user-simulator-red-team-trace | WA | -2.51 | [-7.72, 2.42] |

## Interpretation and next decision

Read the user-static minus user-trace contrast first: a positive RH difference favors the trace policy, whereas a positive A difference means the trace policy has lower holistic quality. A full-trajectory reduction alone is insufficient if later RH worsens or quality collapses.

Before assigning a mechanism, inspect criterion admission, actual penalties, feedback delivery, revision timing, auditor disagreement and recovery exposure. Keep all assignments in the declared analysis. Choose one targeted matched dev3 change from that evidence; do not adjust detector thresholds or switch evaluators.

## Provenance and detailed distributions

[Validated analysis, individual rows, monitor distributions and uncertainty](../../../runs/babel-result20-current-20260908/report-v2/analysis.json). The analysis records each native producer and source seal. [Execution ledger](../../../EXPERIMENT_RUNS.md) retains job/config/output history.

Analysis SHA-256: `d75d334102e0b11222a4da79619b6502d7d4ec7220898a57bcf5a24ad72df73f`. Markdown job: `10362912`.
