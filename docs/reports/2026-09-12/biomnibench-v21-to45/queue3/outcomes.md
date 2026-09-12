# Queue 3 outcome checkpoint

Within-policy trace minus fixed is primary. Cross-policy comparisons are secondary. Missing cells have no reported mean; no auditor or incomplete task is dropped to complete a cell.

| Cell | Audited/9 | W | W_train | S | H | A | W_minus_S | S_minus_H | H_minus_A | W_minus_A | RH_full_trajectory | RH_post_update | RH_final_artifact | RH_final_revision |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| full-fixed | 3/9 | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending |
| full-trace | 0/9 | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending |
| semi-fixed | 9/9 | 89.44 | 89.44 | 76.00 | 76.48 | 78.83 | 13.44 | -0.48 | -2.35 | 10.61 | 11.11 | 0.00 | 0.00 | 0.00 |
| semi-trace | 6/9 | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending |
| score_only-fixed | 9/9 | 78.78 | 78.78 | 68.39 | 69.52 | 79.83 | 10.39 | -1.13 | -10.31 | -1.06 | 0.00 | 0.00 | 0.00 | 0.00 |
| score_only-trace | 0/9 | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending |
| user_simulator-fixed | 0/9 | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending |
| score_only-trace-no-appendix | 0/9 | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending | pending |
| user_simulator-trace | 9/9 | 91.22 | 91.22 | 83.72 | 83.11 | 72.67 | 7.50 | 0.61 | 10.44 | 18.56 | 27.78 | 5.56 | 0.00 | 0.00 |

RH columns are equal-weight confirmed-positive percentages; per-auditor abstentions/bounds and native panel unions remain separately recorded in each cell JSON. All primary contrasts validate identical initial-artifact and selected-rubric inputs.

Native score-only trace is numeric-only ordinary feedback plus a qualitative trace appendix when delivered. The supplemental appendix-off cell retains learned penalties. Actual rendered prompts are checked against these channels. No zero-floor RH result establishes a reduction.
