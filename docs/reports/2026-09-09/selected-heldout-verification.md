# Frozen cue selected-to-heldout computation verification

Read-only cross-check covers all240auditor rows (120static,120trace), their raw rubric-score records, summary role mappings and weak-feedback score compositions. No provider calls or scoring changes.

Checks passed: S uses the summary-selected judgment; H uses exactly heldout variants2,3,4; all four rubric hashes are distinct; every compared judgment binds the same final submission hash and auditor model; weak feedback reference rubric hash equals the selected strong rubric hash; H equals the arithmetic mean of the three heldout scores; S-H equals their signed difference. Original/master judgment is stored separately and not substituted into S or H. Frozen native analysis code performs the same identity checks.

Recovered S-H: static+0.1166667, trace−0.0833333. Static auditor rows:36positive,53zero,31negative; trace29positive,64zero,27negative. The near-zero mean is present in the raw scores and reflects cancellation plus many ties, not a subtraction/sign/role-mapping error found by these checks. This does not prove all scorer prompts or rubric-family construct validity; those require separate content review. No basis to describe the static estimate as clearly positive.

Evidence root: `runs/babel-result20-cue-contrast-20260908/`; row index `comparison-v1/analysis.json`; arm audit `rubric_score/summary.json` and referenced records; row-linked `rubric-evaluations` compositions. Source analysis: `runs/babel-code/result20-cue-contrast/investigation/babel-overnight-20260907/analyze_babel.py`, lines defining selected/holdout role mapping and numeric_scores. All historical outputs unchanged.

## Heldout construct check

The frozen `paraphrase_protocol.py` explicitly defines wording-only variants: preserve every requirement/exception/factual anchor and all criterion order/levels/points; do not strengthen, weaken, clarify or repair the rubric. All20sealed selectedvariant001 files and heldout002–004 preserve criterion numbering and exact Levels lines in a direct structural comparison. This is not a panel of deliberately stronger or differently specified rubrics.

Consequently S-H measures exposure/wording sensitivity within an intended semantically equivalent rubric family. A near-zero signed mean is compatible with wording robustness and cancellation of judge differences; it is not by itself evidence that selected-feedback wiring is broken. This does not prove perfect semantic equivalence for every generated wording field or rule out item-level overfitting. Preserve the frozen pool and report this limitation; do not redesign heldouts to manufacture a positive gap. Pool: `runs/babel-result20-input-restore-10356965/archive-inputs/runs/rubric-paraphrases/biomnibench/red-team-results20/tasks/`.
