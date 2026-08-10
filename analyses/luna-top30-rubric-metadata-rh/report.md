# Rubric metadata and reward-hacking detections

## Result

The existing runs do not show a reliable relation between dynamic rubric length and reward-hacking (RH) detection. The strict matched estimate is +1.9 pp per 1,000 added characters, with a 95% task-cluster bootstrap interval of -1.0 pp to +4.7 pp. The within-cell permutation p-value is 0.207.

This estimate compares the dynamic-minus-static RH outcome across replicates within the same task, feedback policy, and prompt policy. It therefore controls the requested task and prompt factors.

## Matched treatment comparison

The complete-panel majority analysis retained 344 of 360 pairs. Static runs had 24 detections (7.0%). Dynamic runs had 23 detections (6.7%). The paired difference was -0.3 pp (95% cluster interval -2.6 pp to +2.1 pp; task-cluster sign-flip p=1.000).

A two-available-vote sensitivity retained 356 pairs and gave a difference of -0.3 pp.

Semi feedback: -2.9 pp. Full feedback: +2.3 pp.

Detector-specific results differ:

- `gpt-5.6-sol`: 360 pairs; static 24.2%; dynamic 31.4%; difference +7.2 pp.
- `claude-opus-4-8`: 353 pairs; static 4.0%; dynamic 3.7%; difference -0.3 pp.
- `gemini-3.1-pro-preview`: 351 pairs; static 6.0%; dynamic 4.8%; difference -1.1 pp.

Detector-specific length slopes also disagree:

- `gpt-5.6-sol`: +4.1 pp per 1,000 characters; raw p=0.053; detector-sensitivity-family q=0.488.
- `claude-opus-4-8`: +0.4 pp per 1,000 characters; raw p=0.769; detector-sensitivity-family q=0.961.
- `gemini-3.1-pro-preview`: +2.2 pp per 1,000 characters; raw p=0.157; detector-sensitivity-family q=0.488.

## Rubric growth

Dynamic rubrics added a mean of 3,583 characters (median 3,400; range 0 to 8,804). They added a mean of 4.01 criteria (median 4; range 0 to 10).

In a dynamic-only model, the length estimate was +0.8 pp per 1,000 added characters. Its 95% cluster interval was -1.2 pp to +2.8 pp.

Cumulative exposure gave +0.8 pp per 10,000 added character-rounds. Moving the average criterion activation one round earlier gave -2.1 pp. Their permutation p-values were 0.737 and 0.076.

The strongest exploratory subgroup was earlier activation under the base prompt: -4.8 pp per round (raw p=0.009; Benjamini-Hochberg q across all scope-feature checks=0.313).

The prompt- and feedback-stratified slopes are:

| Scope | Final length slope | Permutation p | Earlier-activation slope | Permutation p |
|---|---:|---:|---:|---:|
| Pooled | +1.9 pp per 1k chars | 0.207 | -2.1 pp per round | 0.076 |
| Semi | +1.2 pp per 1k chars | 0.656 | -3.0 pp per round | 0.095 |
| Full | +2.7 pp per 1k chars | 0.100 | -1.3 pp per round | 0.440 |
| Base | +3.2 pp per 1k chars | 0.172 | -4.8 pp per round | 0.009 |
| Diligent | -0.2 pp per 1k chars | 0.884 | +1.1 pp per round | 0.500 |

Across the 30 task rubrics, baseline character count had Spearman rho=-0.25 with static-run RH rate (permutation p=0.187). This task-level comparison is confounded by task content and difficulty.

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

- `full:claude-opus-4-8:missing`: 4
- `full:claude-opus-4-8:no_reward_hacking_detected`: 338
- `full:claude-opus-4-8:reward_hacking_detected`: 18
- `full:gemini-3.1-pro-preview:abstain`: 3
- `full:gemini-3.1-pro-preview:missing`: 1
- `full:gemini-3.1-pro-preview:no_reward_hacking_detected`: 335
- `full:gemini-3.1-pro-preview:reward_hacking_detected`: 21
- `full:gpt-5.6-sol:no_reward_hacking_detected`: 268
- `full:gpt-5.6-sol:reward_hacking_detected`: 92
- `semi:claude-opus-4-8:missing`: 3
- `semi:claude-opus-4-8:no_reward_hacking_detected`: 348
- `semi:claude-opus-4-8:reward_hacking_detected`: 9
- `semi:gemini-3.1-pro-preview:abstain`: 5
- `semi:gemini-3.1-pro-preview:no_reward_hacking_detected`: 338
- `semi:gemini-3.1-pro-preview:reward_hacking_detected`: 17
- `semi:gpt-5.6-sol:no_reward_hacking_detected`: 252
- `semi:gpt-5.6-sol:reward_hacking_detected`: 108

## Files

- `matched_pairs.csv`: pair identities, rubric metadata, and detector outcomes.
- `paired_rh_rates.csv`: matched rates and discordant-pair tests.
- `feature_associations.csv`: strict within-cell metadata models.
- `baseline_task_associations.csv`: task-level baseline-rubric correlations.
- `metadata_correlations.csv`: dependence among the rubric features.
- `length_growth_quartiles.csv`: descriptive matched differences by relative growth quartile.
- `rubric_metadata_rh.png` and `.pdf`: the main visualization.
