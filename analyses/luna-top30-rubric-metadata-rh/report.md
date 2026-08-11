# Rubric metadata and reward-hacking detections

## Result

The existing runs do not show a reliable relation between dynamic rubric length and reward-hacking (RH) detection. The strict matched estimate is -1.3 pp per 1,000 added characters, with a 95% task-cluster bootstrap interval of -4.2 pp to +0.9 pp. The within-cell permutation p-value is 0.370.

This estimate compares the dynamic-minus-static RH outcome across replicates within the same task, feedback policy, and prompt policy. It therefore controls the requested task and prompt factors.

## Matched treatment comparison

The complete-panel majority analysis retained 351 of 360 pairs. Static runs had 14 detections (4.0%). Dynamic runs had 6 detections (1.7%). The paired difference was -2.3 pp (95% cluster interval -4.9 pp to +0.0 pp; task-cluster sign-flip p=0.134).

A two-available-vote sensitivity retained 357 pairs and gave a difference of -2.2 pp.

Semi feedback: -5.1 pp. Full feedback: +0.6 pp.

Detector-specific results differ:

- `gpt-5.6-sol`: 352 pairs; static 13.6%; dynamic 9.9%; difference -3.7 pp.
- `claude-opus-4-8`: 359 pairs; static 1.7%; dynamic 0.6%; difference -1.1 pp.
- `gemini-3.1-pro-preview`: 360 pairs; static 5.0%; dynamic 2.8%; difference -2.2 pp.

Detector-specific length slopes also disagree:

- `gpt-5.6-sol`: +1.0 pp per 1,000 characters; raw p=0.652; detector-sensitivity-family q=0.962.
- `claude-opus-4-8`: -0.7 pp per 1,000 characters; raw p=0.387; detector-sensitivity-family q=0.809.
- `gemini-3.1-pro-preview`: +0.4 pp per 1,000 characters; raw p=0.754; detector-sensitivity-family q=0.986.

## Rubric growth

Dynamic rubrics added a mean of 3,583 characters (median 3,400; range 0 to 8,804). They added a mean of 4.01 criteria (median 4; range 0 to 10).

In a dynamic-only model, the length estimate was -1.0 pp per 1,000 added characters. Its 95% cluster interval was -2.3 pp to +0.0 pp.

Cumulative exposure gave -2.3 pp per 10,000 added character-rounds. Moving the average criterion activation one round earlier gave +0.2 pp. Their permutation p-values were 0.346 and 0.864.

The strongest exploratory subgroup was earlier activation under the base prompt: +0.1 pp per round (raw p=0.955; Benjamini-Hochberg q across all scope-feature checks=1.000).

The prompt- and feedback-stratified slopes are:

| Scope | Final length slope | Permutation p | Earlier-activation slope | Permutation p |
|---|---:|---:|---:|---:|
| Pooled | -1.3 pp per 1k chars | 0.370 | +0.2 pp per round | 0.864 |
| Semi | -2.1 pp per 1k chars | 0.397 | +0.3 pp per round | 0.847 |
| Full | -0.5 pp per 1k chars | 0.794 | +0.0 pp per round | 0.978 |
| Base | -3.0 pp per 1k chars | 0.114 | +0.1 pp per round | 0.955 |
| Diligent | +1.9 pp per 1k chars | 0.376 | +0.3 pp per round | 0.849 |

Across the 30 task rubrics, baseline character count had Spearman rho=-0.20 with static-run RH rate (permutation p=0.284). This task-level comparison is confounded by task content and difficulty.

Most final-rubric features do not identify separate mechanisms. Added characters correlate 0.998 with added words and 0.982 with added criteria. Every changed round added one criterion. Every criterion added exactly 10 possible penalty points. The criterion-count, update-count, and penalty-capacity effects are therefore mathematically identical in these runs. Cumulative exposure and activation timing add a distinct longitudinal dimension.

## Interpretation limits

- Rubric growth is post-treatment. Earlier solver behavior caused the proposer to add criteria. The analysis cannot identify a causal effect of length.
- The detector reviewed the same trajectory that caused rubric growth. More rubric surface can also change what the detector can observe.
- RH is a model-judge label. It is not verified ground truth. Detector-specific estimates are therefore necessary.
- Character count, word count, criterion count, penalty capacity, and changed rounds are strongly related. The data cannot isolate one mechanism.
- Only three replicates exist in each task-feedback-prompt cell. Estimates can miss small or nonlinear effects.

## Method

Each pair shares the experiment, task, replicate seed, prompt policy, and initial rubric text. The pair differs in static versus prospective rubric policy. The main outcome is the final three-model complete-panel majority RH decision. A two-available-vote majority is a missing-panel sensitivity check.

The metadata model demeans outcomes and rubric features within each task-feedback-prompt cell. It estimates a linear risk-difference slope from replicate variation. Confidence intervals resample the 30 tasks. Permutation tests shuffle metadata across replicates within each cell. Benjamini-Hochberg q-values cover four metadata features within each scope. A second correction covers every majority scope-feature check.

A panel is missing from the majority analysis if any model lacks a substantive RH decision. Raw decision counts follow:

- `full:claude-opus-4-8:abstain`: 1
- `full:claude-opus-4-8:no_reward_hacking_detected`: 357
- `full:claude-opus-4-8:reward_hacking_detected`: 2
- `full:gemini-3.1-pro-preview:no_reward_hacking_detected`: 353
- `full:gemini-3.1-pro-preview:reward_hacking_detected`: 7
- `full:gpt-5.6-sol:abstain`: 3
- `full:gpt-5.6-sol:no_reward_hacking_detected`: 309
- `full:gpt-5.6-sol:reward_hacking_detected`: 48
- `semi:claude-opus-4-8:no_reward_hacking_detected`: 354
- `semi:claude-opus-4-8:reward_hacking_detected`: 6
- `semi:gemini-3.1-pro-preview:no_reward_hacking_detected`: 339
- `semi:gemini-3.1-pro-preview:reward_hacking_detected`: 21
- `semi:gpt-5.6-sol:abstain`: 5
- `semi:gpt-5.6-sol:no_reward_hacking_detected`: 317
- `semi:gpt-5.6-sol:reward_hacking_detected`: 38

## Files

- `matched_pairs.csv`: pair identities, rubric metadata, and detector outcomes.
- `paired_rh_rates.csv`: matched rates and discordant-pair tests.
- `feature_associations.csv`: strict within-cell metadata models.
- `baseline_task_associations.csv`: task-level baseline-rubric correlations.
- `metadata_correlations.csv`: dependence among the rubric features.
- `length_growth_quartiles.csv`: descriptive matched differences by relative growth quartile.
- `rubric_metadata_rh.png` and `.pdf`: the main visualization.
