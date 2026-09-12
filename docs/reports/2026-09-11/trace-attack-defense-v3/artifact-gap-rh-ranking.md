# Artifact gap-rank versus RH-rank

Provider-free descriptive analysis of signed gaps, using the complete equal-weight Sol+Opus panel. Each condition is ranked separately; rank 1 is worst. Combined rank is the mean of the three component ranks. Combined score is its negative, so a positive score/RH correlation means overlapping failure orderings.

Worst-tail overlap compares the gap and continuous-RH rankings at 10%, 20%, and 25%. Boundary ties have fractional membership; overlap is the expectation under independent tie resolution. Constant scores produce undefined correlations, not evidence of no association. Abstentions remain ambiguous unless the other auditor confirms a positive.

| Condition | n | RH window | Gap | Spearman | Kendall tau-b | Worst 20% overlap |
|---|---:|---|---|---:|---:|---:|
| v2.1-full | 60 | final_artifact | W_minus_S | 0.211 | 0.167 | 0.375 |
| v2.1-full | 60 | final_artifact | S_minus_H | 0.024 | 0.012 | 0.306 |
| v2.1-full | 60 | final_artifact | H_minus_A | 0.483 | 0.365 | 0.389 |
| v2.1-full | 60 | final_artifact | combined_gap_score | 0.416 | 0.316 | 0.542 |
| v2.1-full | 60 | full_trajectory | W_minus_S | 0.074 | 0.040 | 0.417 |
| v2.1-full | 60 | full_trajectory | S_minus_H | 0.000 | 0.007 | 0.167 |
| v2.1-full | 60 | full_trajectory | H_minus_A | 0.305 | 0.215 | 0.375 |
| v2.1-full | 60 | full_trajectory | combined_gap_score | 0.225 | 0.149 | 0.333 |
| v2.1-user | 60 | final_artifact | W_minus_S | 0.096 | 0.096 | 0.292 |
| v2.1-user | 60 | final_artifact | S_minus_H | 0.167 | 0.132 | 0.229 |
| v2.1-user | 60 | final_artifact | H_minus_A | -0.122 | -0.086 | 0.194 |
| v2.1-user | 60 | final_artifact | combined_gap_score | 0.121 | 0.087 | 0.278 |
| v2.1-user | 60 | full_trajectory | W_minus_S | -0.093 | -0.054 | 0.125 |
| v2.1-user | 60 | full_trajectory | S_minus_H | -0.052 | -0.045 | 0.083 |
| v2.1-user | 60 | full_trajectory | H_minus_A | 0.008 | 0.007 | 0.208 |
| v2.1-user | 60 | full_trajectory | combined_gap_score | -0.120 | -0.099 | 0.125 |
| stress-v2.1-user | 9 | final_artifact | W_minus_S | -0.552 | -0.485 | 0.125 |
| stress-v2.1-user | 9 | final_artifact | S_minus_H | -0.139 | -0.123 | 0.125 |
| stress-v2.1-user | 9 | final_artifact | H_minus_A | 0.000 | 0.000 | 0.125 |
| stress-v2.1-user | 9 | final_artifact | combined_gap_score | -0.552 | -0.485 | 0.125 |
| stress-v2.1-user | 9 | full_trajectory | W_minus_S | -0.578 | -0.514 | 0.000 |
| stress-v2.1-user | 9 | full_trajectory | S_minus_H | 0.121 | 0.070 | 0.000 |
| stress-v2.1-user | 9 | full_trajectory | H_minus_A | 0.119 | 0.033 | 0.000 |
| stress-v2.1-user | 9 | full_trajectory | combined_gap_score | -0.213 | -0.171 | 0.000 |
| stress-v3-user | 9 | final_artifact | W_minus_S | -0.728 | -0.632 | 0.000 |
| stress-v3-user | 9 | final_artifact | S_minus_H | 0.572 | 0.497 | 0.500 |
| stress-v3-user | 9 | final_artifact | H_minus_A | 0.208 | 0.181 | 0.000 |
| stress-v3-user | 9 | final_artifact | combined_gap_score | -0.104 | -0.092 | 0.000 |
| stress-v3-user | 9 | full_trajectory | W_minus_S | -0.825 | -0.701 | 0.000 |
| stress-v3-user | 9 | full_trajectory | S_minus_H | 0.542 | 0.443 | 0.500 |
| stress-v3-user | 9 | full_trajectory | H_minus_A | 0.408 | 0.332 | 0.500 |
| stress-v3-user | 9 | full_trajectory | combined_gap_score | 0.025 | 0.000 | 0.000 |
| canonical-v2.1-user | 9 | final_artifact | W_minus_S | 0.661 | 0.578 | 0.500 |
| canonical-v2.1-user | 9 | final_artifact | S_minus_H | -0.496 | -0.369 | 0.000 |
| canonical-v2.1-user | 9 | final_artifact | H_minus_A | 0.346 | 0.289 | 0.500 |
| canonical-v2.1-user | 9 | final_artifact | combined_gap_score | 0.165 | 0.132 | 0.500 |
| canonical-v2.1-user | 9 | full_trajectory | W_minus_S | 0.768 | 0.657 | 0.500 |
| canonical-v2.1-user | 9 | full_trajectory | S_minus_H | -0.534 | -0.420 | 0.000 |
| canonical-v2.1-user | 9 | full_trajectory | H_minus_A | 0.428 | 0.340 | 0.500 |
| canonical-v2.1-user | 9 | full_trajectory | combined_gap_score | 0.035 | -0.064 | 0.500 |

Result20 is descriptive only and is not used to choose v3 wording. The CSV retains signed gaps, component/combined ranks, both auditor scores/verdicts, and ambiguous cases. The JSON includes each tail size, tie membership, literal rank-vs-score correlations and RH-positive/negative/ambiguous mean ranks.

Unavailable cohorts (no replacement provider calls):

- canonical-v3-user: FileNotFoundError: [Errno 2] No such file or directory: '/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v3-20260911/canonical-v3/da-3-4/study/biomnibench-da-factorial-r10-ff98ae958e5e/study.json'
