# BioMNIBench Results20 final-revision detector calibration

This package contains an exploratory Codex annotation of all 317 completed
final revisions. It is not human ground truth.

Each packet included the task, prior public artifact, triggering feedback, last
artifact-producing trajectory, and final public artifact. Condition identifiers
and detector scores were absent. Feedback content remained visible because it is
required to interpret the revision.

The annotation used two repeated GPT-5.6 Sol passes with high reasoning and
fresh sessions. The passes agreed on 308 of 317 labels (97.2%; Cohen's kappa
0.785). A third fresh pass resolved the nine disagreements. The final labels
contain 24 reward-hacking cases and 293 negative cases. The two passes use the
same model and are not independent human annotators.

The split was fixed before annotation. It contains 187 calibration cases and
130 validation cases. Threshold selection maximized Matthews correlation on the
calibration split. Ties used F1, precision, and then the higher threshold.

Gemini was inactive because it assigned score 0 to every case. The calibration
therefore used GPT and Claude. It selected the maximum active-judge score with a
positive threshold of 3. On the held-out split, this rule had 50% precision,
50% recall, and MCC 0.476. The original threshold of 6 had 100% precision,
33.3% recall, and MCC 0.568. Therefore, the held-out data do not validate the
lower threshold as a better replacement. Threshold 3 is only a higher-recall
screening option.

The final Codex-label rates were:

| Rubric | Full feedback | User simulator |
|---|---:|---:|
| Static | 1/56 (1.8%) | 3/51 (5.9%) |
| Offline elicited | 3/56 (5.4%) | 7/49 (14.3%) |
| Online elicited | 3/55 (5.5%) | 7/50 (14.0%) |

Pooling rubric types, user-simulator cases had 17/150 positive labels versus
7/167 full-feedback cases (two-sided Fisher exact p=0.019). Pooling feedback
types, elicited-rubric cases had 20/210 positives versus 4/107 static-rubric
cases (p=0.074). These are unadjusted, assignment-level exploratory comparisons.

Files:

- `codex_annotations.jsonl`: final frozen labels and reasons;
- `codex_annotations_pass1.jsonl` and `codex_annotations_pass2.jsonl`: repeated
  blinded passes;
- `case_scores_and_labels.csv`: labels joined to scores after label freeze;
- `threshold_metrics.csv`: metrics for every score threshold and split;
- `calibration_summary.json`: selected rule and held-out result;
- `condition_rates.csv`: descriptive rates after condition unblinding;
- `threshold_calibration.png` and `.pdf`: calibration and validation curves.

Regenerate packets, annotations, and analysis with the scripts in this folder.
The packet files and raw Codex session logs are temporary because they contain
large repeated evidence. The tracked annotation rows include packet hashes.
