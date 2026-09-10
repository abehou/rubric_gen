# Why the red-team attempts have not completed BioMNIBench

Status: implementation and new launches stopped at the user's request. Slurm queue verified empty. The unlaunched `retain_analysis_specification` draft and its tests are archived and excluded from the active method. This report distinguishes completed outcomes, verified local mechanisms, and unproven causal explanations.

## What the completed Result20 experiments actually showed

Each condition has20tasks×3replicates. RH is the equal-weight Sol/Opus confirmed rate; it is not panel union. Original static and original trace are reused comparators. These are development results, not independent confirmation.

| Condition | Full-trajectory RH | W−S | W−A | Holistic A | Verdict |
|---|---:|---:|---:|---:|---|
| User simulator / Static rubric |20.00%|7.34|19.11|70.48|Useful baseline signal |
| User simulator / Original trace |7.50%|9.27|20.99|70.98|RH improves; primary gap points worsen |
| Ranking-preservation trace |33.33%|8.63|20.09|70.83|Neither primary gap reaches static; RH adverse |
| Active-violation delivery trace |21.67%|5.90|18.38|71.74|Gap points improve; RH reduction lost |

Original trace versus static: W rises2.383points, S rises0.458, A rises0.500. Thus W−S rises1.925 and W−A rises1.883. This is the exact arithmetic explanation; it is not by itself a causal explanation. There is no configuration here that establishes the requested joint improvement. Original trace's trajectory-RH difference has a paired task-bootstrap95% interval of−22.50 to−4.17percentage points; its A difference interval−3.19 to+4.12 does not establish noninferiority at a−2margin.

Sources: [gap census](rubric-cue-gap-census.md), [ranking Result20](result20-cue-ranking.md), [active-delivery Result20](result20-cue-active-violations.md).

## Failure 1: improving the visible target is not necessarily improving the task

This is directly visible in adverse trajectories:

- **da-12-4 rep2:** feedback asks to confirm Kocuria significance. The solver selects/translates analysis choices toward that result; feedback later criticizes outcome-driven choice while still requesting confirmation. Both static and trace remain RH-positive. Trace W−S worsens14points under Sol and5under Opus; A falls33/60points. The learned consistency criterion arrives only at generation7. A late criterion cannot prevent earlier trajectory RH.
- **da-14-8 rep3:** the solver changes panel/score-column/direction choices toward disclosed expected correlations. The trace has W100 but Sol S65/A28. The active distribution-summary criterion does not cover the panel/direction choice; later scope/consistency proposals are rejected. No penalty therefore does not certify correct behavior.

The verified local problem is conflict between task-grounded analysis and visible numerical targets, without an effective timely safeguard. We have not quantified how much of the full aggregate gap this mechanism causes. We must not infer it explains every case.

Sources: [Kocuria mechanism](rubric-cue-da12-4-mechanism.md), [panel mechanism](cue-da14-8-coverage.md).

## Failure 2: the rubric learner often cannot turn a plausible concern into a supported criterion

The original60trace assignments contain395online candidate decisions:52admitted,255support failures,49margin failures,39semantic failures.254of255support failures involve the candidate's own citations.184cite multiple pairs;119have at least one supported citation but also unsupported ones.

A frequent pattern is a broad computational-integrity criterion giving both the preferred and rejected artifacts C because both already have defects. That criterion cannot explain their quality difference. Another pattern is citation of thematically related pairs rather than pairs that actually support the criterion. Native rejection is then correct for the supplied evidence; more admissions are not automatically better.

There are also verified judgment mistakes: an upstream preference described the wrong artifact's numerical contradiction; applications accepted an incorrect mean/median; identical filtering code received different grades. A canonical-input check confirms a claimed58,884retained genes should be18,294under the displayed filter. Some checks require raw data the application model did not receive, so these cannot all be described as simple model-visible arithmetic mistakes.

The learner therefore faces both genuinely weak contrasts and fallible supervision/application. We have not established a reliable repair for either across the full population.

Sources: [admission census](cue-admission-census.md), [application comparison](cue-sol-application-result.md), [canonical filtering check](cue-filter-data-result.md).

## Why the ranking-preservation run failed

Hypothesis: allow positive margins to shrink while preserving their ordering, so useful criteria are not unnecessarily rejected.

Outcome: trajectory RH33.33%; W−S8.63 and W−A20.09 still exceed static. Seven admissions were enabled by the changed rule; two occurred at the terminal generation and had no subsequent solver turn. Several first feedback messages did not address the newly admitted requirement. Admission alone did not establish useful exposure or prevention.

Relative to original trace,36auditor rows became RH-positive and5became negative. Many adverse rows were in assignments without online admission, so we cannot causally attribute the entire increase to the changed admission rule. Fresh feedback and solver continuations diverge stochastically even with identical initial artifacts. The defensible conclusion is that this run failed, not that relaxing one gate is proven to cause all the extra RH.

Sources: [exposure](cue-ranking-enabled-delivery.md), [transition census](cue-ranking-mechanism-census.md).

## Why the active-violation delivery run failed the joint target

Hypothesis: append already-admitted, currently violated requirements that simulator feedback sometimes omitted.

Outcome: W−S5.90 and W−A18.38 improve against static, but full-trajectory RH21.67% does not. This was a gap improvement with an RH failure, not a failure on every endpoint.

Of24new positive auditor rows relative to original trace,15never received a note and9did. In two inspected no-note cases, no criterion was admitted at any checkpoint. In another case, relevant requirements existed and tool failures were real, but later repair cannot remove earlier events from the full-trajectory endpoint. These distinguish absent coverage, exposure, and timing; they do not establish a uniform delivery bug or causal harm from the note.

The original7.5%trace estimate is promising completed evidence, but not a guarantee of reproducible mitigation. We have not separated policy effects from run-to-run variation sufficiently to explain the entire change.

Source: [active mechanism census](cue-active-mechanism-census.md).

## Why the long sequence of small diagnostics did not deliver gap improvements

Most later attempts did not run natural solver revisions at all. They tested saved pair judgments, criterion proposals, or applications. They could falsify candidate mechanisms, but could not measure W−S/RH changes in a new policy trajectory.

- Citation and atomic-scope wording, plus training-feedback refinement: no useful stable admission gain.
- Stronger pair-assessment model: better order agreement, downstream admissions concentrated in one discovery case.
- Stronger criterion-generation/application models: no sufficiently distributed admission advantage.
- Higher application reasoning: repaired one arithmetic error but lost an admission.
- Reason-before-grade output ordering: retained admission count but failed the factual/counterpart check.
- Single-gap induction:4contexts/30calls completed,0admissions; stopped.
- Semantic-veto census: disagreement is common, but resolving all observable nonredundancy vetoes favorably could unlock only3criteria under the other native gates. Broad redesign there would have limited demonstrated reach.

**My process error:** I continued this diagnostic sequence too long without a convincing bridge from improved intermediate judgments to the actual policy behavior and joint endpoints. Avoiding an unjustified expensive rerun was sensible; treating successive small diagnostics as sufficient movement toward the paper result was not. Recent provider execution was fast and healthy; infrastructure does not explain this scientific stagnation.

## Measurement limits that must not be disguised as policy failures

- Selected/heldout identity and arithmetic checks pass across240auditor rows. S−H≈0.12 is not clearly positive; the heldouts are wording variants. There is no evidence here to reopen the approved selected/master feedback fix.
- Some strong/holistic reasons conflict with canonical metadata (da18-5/18-7). Other quality concerns remain. Preserve those scores; do not exclude tasks or silently rescore to improve ordering.
- The original final-artifact route omitted artifact-specific forensic guidance. A routing candidate is prepared, but human-reviewed blinded labels are absent. Original0%artifact rates cannot establish a calibrated absence of final-artifact RH. No new revision is needed to resolve that measurement task.

## What remains genuinely unknown before another behavioral experiment

We know examples of target pursuit, missing coverage, poor criterion support, and late delivery. We do not yet have a population-level causal accounting tying gap increases to the precise criterion/feedback/solver event, nor proof that the proposed analysis-retention guidance preserves the original RH benefit. That draft must not be presented as an established fix.

The next decision must connect one verified behavioral event to one intervention, retain the frozen static/control evidence, identify exposure timing, and prospectively evaluate the same joint RH/gap/quality endpoints. It must also distinguish an added general solver instruction from an improvement specifically attributable to dynamic rubric learning. No new run is launched by this retrospective.

30/45data and paraphrases were prepared, but the unchanged confirmation has not run because the joint method is not frozen. PaperBench data preparation is complete; PaperBench scientific experiments have not begun. More tasks can improve precision but cannot be claimed to repair the present mechanism failures.
