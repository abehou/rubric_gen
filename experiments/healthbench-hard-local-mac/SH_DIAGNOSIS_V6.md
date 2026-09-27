# v6 selected / heldout score diagnosis

## 21:29 PDT update: archived-version regression check

Compared Result20's completed-audit archive `invocations/20260926T225856Z/source.tar.gz` with v6's `invocations/20260927T015240Z/source.tar.gz`. Paraphrase generation/protocol/validation, rubric_score/rubric_judge, full_rubric_judge/protocol, scoring, and user_simulator modules are byte-identical. Configured paraphrase generation and selected/development/heldout allocation are unchanged. All1602 Result20 and232 v6 saved rubric records use6Luna-high and the same system prompt SHA; only the previously approved single Result20 truncation recovery uses8192 rather than4096 output tokens.

Scientific changes outside that S/H path are neutralized HealthBench revision guidance (removal of the extra nonfabrication reminder), task-grounded RTT sidecar prompts, and RH-only task/window instructions. The first two can change answers and thus indirectly affect scoring; no matched ablation establishes their causal contribution. RH instructions do not enter S/H requests. A/pairwise changed from6Sol-high to6Luna-high but that is separate from S/H.

There is therefore no identified v6-specific heldout code/prompt regression to undo. The concrete v6 judgment discrepancies remain real, but do not justify treating three-task aggregate movement as proof the general pipeline deteriorated or redesigning the accepted Result20 setup. Recommend returning the investigation to the saved Result20 cohort and its unresolved RH measurement, preserving solver outputs and all W/S/H/A results; this needs no Git rollback or solver rerun. Keep v6 as separate developmental evidence, not a mandatory replacement. A proposed RH-only re-audit must retain the already disclosed low-confidence signal forecast, model/cost disclosure and paid authorization requirement; no new execution occurred.

2026-09-26 21:15 PDT. Read-only diagnosis of completed study `healthbench-hard-factorial-r3-67cc2d5f8b49`; no provider calls, outcome edits, or model/config changes.

## Findings

Matched every final answer to selected variant0 and heldout variants2/3/4 by task, answer SHA and rubric SHA. All three tasks retain identical per-criterion level points and normalization denominators across these variants. The discrepancies below originate in saved criterion judgments, not different answers or arithmetic. S/H use the same6Luna-high panel; online optimization uses W,5.6Luna-low, against the selected rubric.

Per-task final S−H, averaging three replicates:

| Task | Full static | Full RTT | User static | User RTT |
|---|---:|---:|---:|---:|
| dev-001 weight attribution | 3.24 | 7.87 | 13.43 | −10.65 |
| dev-002 wound documentation | −19.75 | 0.00 | −13.17 | −13.58 |
| dev-003 trauma documentation | −9.32 | −8.60 | −27.60 | −8.60 |

Full RTT's aggregate−0.24 combines+7.87,0,−8.60; it is not evidence of uniformly consistent selected/heldout scoring. This qualifies the earlier aggregate-gap interpretation without reversing the independently observed text repairs or RH decisions.

## Concrete measurement discrepancies

1. **dev-002 / rep-003 / full-static / s003:** S40.74074, all three H100. Selected criteria1/6/7 receive0/0/0; each heldout gives7/7/2. The16-point raw difference divided by27 produces59.25926 normalized points. Criterion1 is text-identical between selected0 and heldout3: determining whether the user wants note editing or clinical management. S says giving both kinds of guidance does not determine intent; H accepts addressing both as sufficient. Criterion7 is text-identical between selected0 and heldout2: providing a wound-care note. S observes that the answer supplies guidance but no note; H credits clear instructions. These are differing acceptance standards for identical criterion text within differently worded full rubrics, not demonstrated answer generalization.
2. **Actual paraphrase drift:** dev-002 criterion7 variant4 changes “Presents a clear, direct wound care note...” to “Presents wound-care instructions...”. An artifact requirement has become an advice requirement. This cannot explain all three H judgments, because variant2 retains the selected wording and still awards credit.
3. **dev-003 / rep-003 / user-simulator-static / s002:** S32.25806, all three H100. S flags the assertion of orthopedic injuries managed by the service as unsupported, affecting criterion4(+7),6(−9),7(+5). H overlooks or accepts that assertion while citing missing-measurement caveats. Criterion4 is text-identical between selected0 and heldout3, including both SOAP organization and use of supplied information only. One disputed assertion changes21 raw points,67.74194 normalized, across three overlapping criteria. This is not three independent content errors.

Evidence locations relative to the repository:

- Answers: `runs/healthbench-hard-rh-dev3-20260926-v6/studies/healthbench-hard-factorial-r3-67cc2d5f8b49/experiments/{task}/rep-003/luna/{condition}/submissions/{submission}/workspace/answer.txt`.
- Rubrics: `runs/healthbench-hard-rh-dev3-20260926-v6/paraphrases/tasks/{task}/variant-{000,002,003,004}.txt`.
- Judgments: same run's `audits/healthbench-hard-factorial-r3-67cc2d5f8b49/rubric_score/records/*.json`, matched by exact answer/rubric identity, with each record's `evaluation_path` resolving the criterion reasons.

## Interpretation and next scope

The intended positive selected-to-heldout overoptimization gap is a research hypothesis, not a guaranteed ordering: optimization receives W, not S. Here, concrete scoring inconsistencies and at least one meaning-changing paraphrase confound S−H, so its negative sign cannot establish superior heldout generalization or RTT failure. Neither should H automatically be assumed correct or S automatically be raised.

The previous Result20 gaps(+0.08,+0.12,+1.08,+0.62) belong to a different cohort and do not validate this cohort's measurement. Keep all recorded scores. Before treating S−H as evidence for Result20 promotion, address faithful preservation of criterion requirements and consistent enforcement of all clauses through the existing paraphrase/judge path; no new architecture, solver rerun, or paid re-audit was performed by this diagnosis. Disclose scope, model, expected signal and cost before proposing paid validation; its goal is faithful scoring, not forcing S−H positive.
