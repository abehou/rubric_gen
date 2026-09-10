# Bounded score disclosure: decision

The complete native report (job 10367657) validates 120 assignments and 240 Sol/Opus rows, including all six isolated repairs. Primary metrics and evaluators are unchanged.

| Equal-auditor metric | Cue control | Bounded score disclosure |
|---|---:|---:|
| Full-trajectory confirmed RH | 20.00% | 13.33% |
| Full-trajectory identification bounds | 20.00–21.67% | 13.33–16.67% |
| Post-update confirmed RH | 11.67% | 7.50% |
| Final-artifact RH | 0% | 0% |
| Final-revision confirmed RH | 5.00% | 2.50% |
| W (also W_train) | 89.58 | 90.65 |
| S | 82.24 | 80.33 |
| H | 82.13 | 79.58 |
| A | 70.48 | 68.71 |

The paired mean quality difference is −1.77 points, 95% task-bootstrap interval [−5.98, +2.07]; do not claim a conclusive quality decline. Both auditors have lower confirmed full-trajectory RH points, but uncertainty and abstentions remain.

## Decision and next diagnostic

Do not promote this candidate as a stronger RH baseline or launch its dynamic counterpart merely because it completed. Retain the preceding cue-static / cue-trace comparison as the best completed trajectory evidence (20% versus 7.5%, artifact RH zero in both).

The intended score-disclosure change also prohibited expected numeric targets. Feedback changed materially: one-concern turns increased from 133 to 331, three-concern turns decreased from 123 to 56, and mean concern characters per turn fell from 784 to 549. Mean attempted turns stayed similar (8.15 versus 8.23); revision-budget stops were 31 versus 30. These descriptive changes suggest reduced feedback content may matter, but do not establish a causal mechanism.

Next inspect matched trajectories where RH changed and actual score exposure. Separate reduced numeric-target guidance, fewer substantive concerns, and auditor disagreement before selecting another minimal prompt change. Do not tune the detector to obtain the desired ordering. No 30/45-task expansion is justified by this candidate.

Detailed scores, distributions, per-case decisions, uncertainty and exposure are in [the full report](result20-cue-score-bounded.md). Raw analysis: `runs/babel-result20-cue-score-bounded-20260909/comparison-v1/analysis.json`.
