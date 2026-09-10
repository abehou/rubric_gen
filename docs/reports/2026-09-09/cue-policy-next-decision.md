# Next policy decision after completed ranking analysis

Status update (2026-09-09 14:07 EDT): saved-input and native source acceptance gates passed; trace-only Result20 job **10373129** is running at frozen commit `c507d402a953dde9bf5177ca9eafb78bcbce7df4`. The prospective decision below is preserved. Acceptance: `investigation/result20-cue-active-violations-20260909/acceptance.json`; exposure evidence: [saved-input census](cue-active-violation-exposure.md); execution: [runtime record](cue-active-runtime.md). No scientific outcome is available yet.

## Evidence and prior intervention

The ranking arm fails all joint gates. Retain original rubric-cue static and trace as the primary reference; do not retain the relaxed admission rule in the next candidate. The criterion-specific census verifies that a learned requirement assessed as violated can be omitted or delayed while selected-rubric target concerns are delivered (da14-8rep2s003–s004, da10-1rep1s006). Other violated requirements are conveyed, so the problem is selective delivery, not universal loss of criteria.

The earlier criterion-update condition appended newly admitted requirements. It delivered24notes across21/60assignments, despite47assignments admitting criteria. Its completed full-trajectory RH was19.17%, versus24.17% matched trace and18.33% matched static. Equal-auditor WS was9.56 and WA23.10, versus trace8.65/19.96 and static8.53/21.91; holistic quality was69.65 versus trace71.21 and static70.20. Thus it did not establish the joint pattern. It also used score-disclosing simulator wording and independently induced starting criteria, so it is not a clean test of the frozen rubric-cue setup. Do not merge its favorable RH contrast with the rubric-cue gap estimates.

## Exactly one candidate change

**Deliver currently violated learned requirements, rather than only announcing newly admitted ones.** At each existing revision opportunity, append a compact policy-generated note containing the requirements of currently active elicited criteria assessed below their zero-penalty level. Use the current checkpoint's already-computed assessments. No new criterion generation, no admission relaxation, no additional judgment, no new solver turn, no simulator wording change, and no selected score/threshold change. Preserve existing task-scoped applicability and requirement text; do not expose held-out or holistic judgments.

This differs from the prior update intervention in its trigger and persistence: an old but still violated criterion remains eligible, while an unviolated newly admitted criterion creates no note. Do not combine this with target suppression, reward reweighting, or a different simulator. Extra solver-visible text is the intended treatment and must be reported.

## Reuse and revision necessity

Reuse frozen rubric-cue static outputs, shared seeds, selected/development/held-out rubrics, frozen starting elicited criteria, and all compatible evaluations of unchanged artifacts. Only a modified trace arm needs new revision, because solver-visible feedback changes. Its new artifacts require their own scoring/audits. Do not copy experiment-bound feedback records or pretend the resulting trajectories share identical stochastic initial feedback. Retain the original rule and runtime source identities explicitly in a prospective source comparison.

## Required gate before launch

Run a provider-free census on the **original rubric-cue trace** to quantify the number of existing nonterminal violated-criterion checkpoints that would receive the note, using stable criterion IDs and native judgment hashes. Validate exact note contents on saved cases, absence on zero-penalty/terminal checkpoints, unchanged controls, and unchanged selected-reference feedback. Confirm this adds exposure in the primary branch, not only the rejected ranking branch. Write the resulting gate receipt and freeze source/config before any expensive run. This document does not claim those checks have passed.

## Prespecified success and stop rule

Use the same previously declared primary endpoints: W−S and W−A must each not worsen in point estimate versus matched rubric-cue static; full-trajectory RH must decrease by at least5percentage points with the paired task-bootstrap95% interval below zero; holistic A's one-sided95% lower bound must exceed−2points. Keep Sol/Opus identities, >5 detector rule and abstention handling unchanged. Report S−H and H−A plus W_train separately. Final-artifact RH remains secondary and cannot be promoted without independent human-reviewed calibration.

If the saved-input gate shows no meaningful new exposure, stop without revision. If a complete trace run fails any joint criterion, retain the adverse result and stop this candidate rather than scaling or altering thresholds. Infrastructure failures receive native missing-work recovery only. Confirmation30/45 remains held until a coherent configuration meets all user completion criteria, including the unresolved static S−H and calibrated artifact measurement requirements.
