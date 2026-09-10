# Completed Result20: rubric-cue baseline and revised trace

All120 assignments and native Sol/Opus audit coverage passed, with frozen source0fbe0bb unchanged. Matched report10364371 completed after static10365215 and trace10364364. The20 tasks and3seeds were used for development, so these are not untouched confirmatory data.

| Equal-auditor metric | Static | Revised trace |
|---|---:|---:|
| Full-trajectory RH |20.00%|7.50%|
| Post-update RH |11.67%|8.33%|
| Final-artifact RH |0.00%|0.00%|
| Final-revision RH |5.00%|1.67%|
| W |89.58|91.97|
| W_train |89.58|91.63|
| S |82.24|82.70|
| H |82.13|82.78|
| A |70.47|70.97|
| W−S |7.34|9.27|
| S−H |0.12|−0.08|
| H−A |11.65|11.81|
| W−A |19.11|20.99|

RH point estimates count confirmed positives over all assignments and average auditors equally; abstentions remain in the denominator. Full RH identification bounds are20–21.67% static and7.5–10.83% trace. The separately recorded paired task-bootstrap interval for the confirmed-rate contrast is−22.5 to−4.17percentage points, centered at−12.5. Native panel-union contrast also has an interval below zero (−33.33 to−3.33percentage points); panel-union rates are28.33–30% versus10–15%, not the equal-auditor rates.

## What this establishes

The more rubric-specific user simulator creates substantially more trajectory-level RH headroom than the previous static Result20 point estimate4.17%. On the matched new baseline, revised trace reduces trajectory RH, with both auditors agreeing in direction. Quality difference trace−static is+0.50, task-bootstrap95%[−3.19,+4.12]; there is no clear quality difference, but equivalence/noninferiority was not established. The previous original-simulator static A was75.325 versus70.475 here, a descriptive−4.85-point change that must not be omitted when discussing the cost of creating headroom.

The trace implementation had76admissions in47/60assignments across424generations. This establishes nontrivial rubric updates, not a causal mechanism: criterion relevance, simulator delivery and behavioral use need case inspection. The policy comparison bundles the previously declared evidence-support sidecar and contrast-specific proposer changes; it does not isolate their individual effects.

## What remains unresolved

Final-artifact RH remains at floor in both arms, and selected-to-heldout gaps are near zero. W−S and W−A point gaps increase under trace rather than decrease. Post-update auditors disagree: Sol improves11.67→3.33%, whereas Opus worsens11.67→13.33%; aggregate post-update change is therefore weaker evidence than the full-trajectory result. Do not describe all gaps or all RH endpoints as improved.

The separately versioned artifact-only audit diagnostic df0ce37/10366032 runs on these exact saved artifacts with original scores retained. Its results test measurement sensitivity, not new behavior. No additional revisions are needed for this diagnostic. The complete goal is not achieved and30/45-task expansion remains unlaunched pending interpretation of the remaining final-artifact question and configuration freeze.

Full per-auditor scores, distributions, bounds, revision behavior, provenance and native paired uncertainty: [complete result](result20-cue-contrast.md). Admission details: [census](result20-cue-criterion-admissions.md). Diagnostic: [protocol/checkpoint](artifact-audit-diagnostic.md).
