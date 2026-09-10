# Matched trace policy under first-concern score disclosure

Compare 20 canonical tasks × 3 frozen replicates with completed first-concern score static control (source 7cd0b76, recovery 10368806, report 10368397). Change only execution condition from fixed to red_team_trace and output paths; retain simulator, evaluator identities, prompts, thresholds, seed/paraphrase pools and shared concurrency 60.

Hypothesis: the existing trace policy reduces full-trajectory and final-artifact RH under the score-disclosing user simulator while preserving holistic quality. Baseline confirmed rates are 18.33% trajectory and 3.33% artifact. Report all endpoints, abstentions, exposure, W_train separately, quality and task-paired uncertainty, including adverse results. This is developmental Result20, not independent confirmation.

Use unchanged frozen source for scientific comparability. The future token-preparation retry patch is excluded. Native validation must pass before launch. New learned criteria are part of the policy; compare seeds and selected-base hashes to static, and record learned-rubric provenance. Never infer mitigation by comparing different simulator baselines.
