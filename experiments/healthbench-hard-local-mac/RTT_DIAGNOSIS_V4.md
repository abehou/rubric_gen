# v4 RTT critical-path diagnosis — 2026-09-25

Update 23:17 PDT: The user rejects the Sol proposer recommendation below: Luna high is the ceiling for the solver/RTT chain. The replacement candidate `dev3-v5.yaml` keeps gpt-5.6-luna and adds high validation; the historical diagnosis remains valid, but upgrading the first four stages to Sol is not authorized. No claim is made that validation effort alone fixes high-effort assessment/induction errors.

Read-only review of saved runtime evidence; no provider calls, prompt/config edits, or new experiment. Uses the rubric-experiments evidence workflow. This refines the earlier broad statement that RTT diagnostics miss main-answer quality defects: some defects are detected correctly but lost in induction, candidate application, or online scoring.

## 1. Evidence attribution error → invalid provenance → rejected criterion

Case: `dev-001/rep-002/luna/full-red-team-trace`, generation0002.

The actual `assessment_rubric_free` request pairs seed artifact `artifact_e68cc6239a45ff0e` with revised main artifact `artifact_8257336d31bd23f1` in `pair_1cffd17f5f60de35`. Both complete texts and the untruncated A→B diff are present. The revised main answer has repetitive additions, but no invented anion-gap calculation. A different artifact, the red-team sidecar `artifact_1c8cc496ce6f05f9`, adds “anion gap of 28 mEq/L (Na 140 − [Cl 100 + HCO3 12])”.

The high-effort diagnostic attributes that unsupported exact laboratory claim to the revised **main** answer. Induction then cites both the actual sidecar pair and this clean-main pair as support for “Support for patient-specific quantitative claims”. Blind application cannot separate the clean-main pair under that criterion; admission records `criterion_support_failed`. No criterion is accepted in this generation.

This is a concrete cross-artifact evidence-attribution failure in the model response, not an absent input, truncated diff, or demonstrated artifact-ID plumbing error. The public payload's IDs/texts are consistent. It also illustrates why a valid sidecar-discovered failure need not improve the main answer: the latter never made the numerical claim. The repetitive structure remains unaddressed.

Evidence: proposer record `99f94da039f81d4a9ad961812a986b6f4c5cdcc604e987425230207938184129.json`, generation0002 artifact-history, pairwise-assessment-rubric-free, criterion-proposal, criterion-validation and aggregate-margins.

## 2. Correct diagnosis → criterion with conflicting scope → validation/online disagreement

Case: `dev-003/rep-003/luna/full-red-team-trace`, generation0002.

Diagnostics correctly prefer the original sparse note over `live:s001`, because the latter adds an unrequested referral recommendation. This main-answer gap `pair_45461f6a39fe4514` enters induction.

Accepted criterion `elicited_d786ac7279907876`, “Unsupported management additions”, has a requirement penalizing unsupported recommendations/referrals. However, its A-level description allows a proposed action if clearly conditional and not stated to have occurred. That exception permits the very observed answer: “Recommend referral ... as clinically appropriate.”

The isolated validator marks that main artifact `artifact_d80322bd2c6b492d` **B**, citing an unsupported recommendation. The online judge later marks the **same unchanged answer** at s002 **A**, explicitly invoking “as clinically appropriate”. The online feedback lists all criteria at maximum, and the answer remains unchanged. The validation semantics did not survive application in the full rubric.

This is not solver refusal to follow a valid negative signal. The positive signal actually delivered says the answer meets the added criterion. Upgrading diagnostics alone cannot address that mismatch; induction needs unambiguous, internally consistent levels, and validation needs faithful application of the exact levels.

An additional limitation is visible in the saved margins: the base rubric rewards the referral by+6 raw points, while the learned penalty is−3. Even the validator's B changes the preferred-minus-rejected margin only from−6 to−3. Admission intentionally permits partial improvement; it does not guarantee corrected ranking. Do not change official points or relax admission simply to force this example to win. A stronger model cannot by itself remove that arithmetic constraint.

Evidence: generation0002 `criterion-proposal.json`, `criterion-validation.json`, `aggregate-margins.json`; s001/s002 `answer.txt` are identical; s002 `feedback.json` is stored as `feedback/s002.json`, where criterion9 is A with zero penalty.

## 3. Correct gap → overbroad application erases another accepted distinction

Case: `dev-003/rep-001/luna/full-red-team-trace`, generation0002.

Diagnostics correctly identify the main answer's unsupported referral; induction proposes `elicited_bbd90322a5b008c5`, “Unsupported clinical recommendation added”. Validation penalizes not only the referral-bearing main answer but also a clean seed saying further assessment is needed before finalizing a plan, treating the latter as an unsupported clinical action. Another clean seed's “Further history, examination, and treatment recommendations pending additional information” is not penalized.

On an earlier pair, a previously accepted unsupported-participant criterion creates a positive margin; adding the new criterion cancels that distinction. The aggregate admission code rejects the new criterion with `aggregate_margin_failed`: strict improvement on previously supported pair `pair_7f4ae89b86f7c689` is erased. This is not evidence that admission should be weakened. The useful target was lost through insufficiently discriminating candidate scope/application.

Some dev-003 induction outputs omit the referral issue despite an induction-eligible main-answer gap (Full replicate2 and User replicate2). User replicate1's referral gap was reserved for validation rather than induction, so that omission must not be labeled a proposer failure to use evidence it did not receive.

## Extent and effort settings

Across **21 online evolution events** (generation≥2), the saved decisions contain39 candidate instances:19 accepted,11 `criterion_support_failed`,9 `aggregate_margin_failed`. No stage fallback reason is recorded. These are event/instance counts, not independent task-level observations; rejection is not automatically an error.

Saved online proposer records confirm:

| Stage | Model | Effort | Saved records |
| --- | --- | --- | ---: |
| Rubric-free assessment | 5.6 Luna | high | 21 |
| Active-rubric assessment | 5.6 Luna | high | 21 |
| Development-rubric assessment | 5.6 Luna | high | 21 |
| Induction | 5.6 Luna | high | 21 |
| Isolated validation | 5.6 Luna | **low** | 123 |

Validation records are per isolated artifact, so their count is not a retry count or directly comparable to whole-pair assessment calls. There is no observed evidence that simply changing the first four stages from low→high is possible: they are **already high**.

## Targeted next candidate, not yet implemented

Preserve the architecture, official predicates/points, tasks, solver/W, red-team generator, three rounds and feedback policies. The smallest coherent configuration candidate is:

- Change the existing proposer model to the agreed GPT-6 Sol.
- Retain high effort for all three assessment views and induction.
- Explicitly set the already-supported `validation` stage to **high** rather than leaving it on the low default.

This upgrades the diagnosis→definition→blind-application chain together. It does not change online W; disagreement with W must therefore still be reported. Existing instructions already require artifact-specific evidence, supported provenance, observable independent levels, and no invented distinctions. Do not add case-specific clinical rules, weaken admission, or rewrite source criteria as a shortcut.

In the next approved standard Dev3 comparison, report whether cross-artifact claims persist, whether criterion levels actually distinguish their cited pair, whether the accepted criterion is applied consistently to an unchanged main answer, and whether the solver's next answer repairs the underlying defect. Continue reporting S/H/A and their gaps; zero final-artifact RH is not a blocker. These are analyses of the normal run's saved evidence, not a new paid diagnostic stage or additional release gate.

Expected benefit is a testable hypothesis, not a promise of higher aggregate A: small-task variance, remaining W interpretation noise, changing criterion coverage, and immutable base-score/penalty tradeoffs can still limit the outcome.

All paths above are relative to the indicated assignment under `runs/healthbench-hard-local-mac-20260925-v4/studies/healthbench-hard-factorial-r3-967d6a08c7ea/experiments/`. General outcome context: [RESULTS_V4_ABSOLUTE_SOL.md](RESULTS_V4_ABSOLUTE_SOL.md).
