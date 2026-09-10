# Completed crossfile Result20: decision

Primary report10367427 completed successfully. All180 assignments across three conditions and360 auditor rows validated, combining59original crossfile cases with the one independently validated repaired case. Complete data: `runs/babel-result20-crossfile-consistency-20260908/comparison-v2/analysis.json`.

| Equal-auditor metric | Static | Previous trace | Crossfile trace |
|---|---:|---:|---:|
| Full-trajectory RH |20.00%|7.50%|11.67%|
| Post-update RH |11.67%|8.33%|6.67%|
| Final-artifact RH |0.00%|0.00%|0.00%|
| Final-revision RH |5.00%|1.67%|0.00%|
| W |89.58|91.97|89.00|
| W_train |89.58|91.63|88.42|
| S |82.24|82.70|80.30|
| H |82.13|82.78|79.68|
| A |70.47|70.97|69.18|
| W−S |7.34|9.27|8.70|
| S−H |0.12|−0.08|0.62|
| H−A |11.65|11.81|10.50|
| W−A |19.11|20.99|19.82|

RH rates above are confirmed positives with abstentions retained in denominators, averaged equally across auditors. They are not panel-union rates. Full details include both definitions and bounds.

## Decision

Do not promote crossfile over previous trace. It has mixed endpoint changes, no final-artifact headroom, and lower quality point estimates. Crossfile minus previous trace quality difference is−1.79, task-bootstrap95%[−7.34,+2.76], so quality degradation is not established statistically. Full-trajectory panel contrast interval[−13.33,+20.00]percentage points is inconclusive. The apparent positive S−H gap is also uncertain: difference from previoustrace+0.70,95%[−0.42,+1.90].

Interpretation is additionally limited by stochastic starting-rubric differences on10/20tasks. The repaired cell's starting rubric matches previoustrace but differs from its failed original attempt. These are exploratory development results, not untouched confirmatory evidence.

Retain previous cue+trace as the best current full-trajectory comparison (20%static versus7.5%trace). Do not claim artifact-level mitigation or uniformly improved gaps. Crossfile admitted66criteria in45/60assignments, so this was not merely absent policy updates; admission does not prove delivery or causal effect.

Next: finish unchanged artifact-v2 sensitivity10367028/report10367029 and inspect any artifact-visible disagreement. Avoid another detector-prompt search selected for favorable ordering. Then target a minimal simulator opportunity/framing change only if case evidence motivates it, preserving the primary detector and matched controls. No30/45 expansion or new revision condition has been launched.
