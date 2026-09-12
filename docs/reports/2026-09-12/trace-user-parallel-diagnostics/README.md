# Bounded User-feedback delivery × grounding comparison

Status: provider-free discrepancy replay complete; fixed challenger implementation
and feedback-only checks in preparation. No challenger outcomes yet. No Result20
or extra feedback-policy arms are authorized in this comparison.

The reference is attack_defense_v2.1. Historical v3/v3.1/v3.2 outputs are preserved.
The [closed v3 report](../../2026-09-11/trace-attack-defense-v3/README.md) at
`31d6ed8` records the earlier experiments; v3.2 actually executed `d164a9a`.
The first v3 raised H with nearly unchanged A; v3.2 lost A and H relative to its
control. Those are distinct changes, and the earlier causal interpretations
remain hypotheses. Fresh continuation variability is unresolved.

## Fixed comparison

| Cell | Recipe | Delivery D | Grounding G |
|---|---|---|---|
| C00 | attack_defense_v2.1 | separate legacy reminder | original simulator |
| C10 | attack_defense_user_d1g0 | same selected rule competes within three concerns | original + D paragraph only when a check exists |
| C01 | attack_defense_user_d0g1 | separate legacy reminder | original + supplied G paragraph and private source references |
| C11 | attack_defense_user_d1g1 | same selected rule competes within three concerns | original + D when selected + G |

All use the v2.1 attack/learner/native gates, penalty scale, schedule and correct
legacy selector. No base-deficit ranking, mandatory base slot, v3.2 preservation
paragraph, tag-driven accept conversion, new model, or outcome prompt is added.
Private basis/references are stripped before ordinary solver rendering. They do
not alter the model's decision or remove a concern.

Canonical development: da-3-4, da-11-1, da-18-1, three replicates. Reuse one
compatible completed canonical v2.1 control, matched initial submissions and g1;
27 fresh challenger assignments, evaluated by Sol + Opus in all four RH windows.
The saved control has 5/18 confirmed-positive full-trajectory auditor judgments,
1/18 post-update, and 0/18 for each final window; thus the trajectory comparison
is not at a zero floor. These are trace-control rates, not static-baseline effects.

## Numeric-selector discrepancy

The executing v3.2 source requires an exponent in its copied numeric regex;
legacy makes the exponent optional. On `160 52 0.05 20% 1e-3`, legacy finds all
five literals and the copied selector finds only `1e-3`.

[Replay JSON](selector-replay.json) and [CSV](selector-replay.csv) compare the
correct selector with actual saved receipts, holding the saved scores, public
task and previous selection history fixed. All historical receipts reproduced.

| Saved variant | Checkpoints | Changed eligibility | Changed choice |
|---|---:|---:|---:|
| v3 | 70 | 0 | 0 |
| v3.1 | 59 | 0 | 0 |
| v3.2 | 61 | 1 | 1 |

The sole changed checkpoint is v3.2 da-13-6/rep-001/s002, g4:
`elicited_3de60b49f6523a57` was selected proactively. Its requirement includes
`adjusted p<0.05`; the correct selector skips it as
`numeric_literal_absent_from_public_task` and selects no rule. This does not
establish any downstream quality effect or explain separate target-like feedback.
A changed historical selection is not relabeled as unchanged behavior.

## Delivery-label limitation

Historical `persist_private_delivery` inferred emission from any matching origin
label, without associating that concern with the selected rule. Several omission
reasons were host branches based on concern count/decision, not simulator-provided
explanations. They are not verified exposure/omission evidence.

The v3.1/v3.2 guard could turn revise into accept and remove every concern based
solely on proactive labels. In v3.2 da-13-6/rep-001/s004 this happened to a raw
verification concern. Such a label does not establish that the underlying question
was nonmaterial. The v3.1 guard did not fire in its stress run; its outcomes cannot
be attributed to an observed guard intervention.

New budgeted receipts separately retain selection, actual rendered concern text,
model-declared association (unknown when not declared), and independently
inspected semantic exposure (unknown until reviewed). Omission reason remains
unknown absent evidence. Proactive-only revision errors remain visible model
outputs; no tag-only host rewrite conceals them.

## Feedback-only checks and execution

Twelve diagnostic checkpoints are preselected in
[feedback_checkpoints.json](../../../../experiments/trace-user-parallel-diagnostics/feedback_checkpoints.json),
covering private target guidance, population mismatch, sign allegations,
unavailable remedies, repetition, genuine corrective content, proactive-only
requests and task omissions. Up to 12 logical calls per challenger, 36 total;
no solver trajectories, offline induction or outcome-auditor calls in this step.
Scientific failures will be reported, not retried toward a desired answer.

Provider-free tests pass 122/122, covering historical literals, selector
bytes, numeric forms, metadata isolation and existing v2.1 title/admission tests.
All 12 saved diagnostic inputs reproduce their original public-artifact, full-feedback and history receipts. No model calls were made during reconstruction.

## Interpretation and stopping rule

Report D effects C10−C00 and C11−C01, G effects C01−C00 and C11−C10, and
interaction C11−C10−C01+C00, with every task/replicate and both auditors.
Three task clusters support descriptive uncertainty, not a strong mechanism claim.
Inspect retained computations, feedback accuracy and largest quality losses.

W−S need only be near the appropriate reference or modestly lower; do not trade
S/H/A or RH for a larger reduction. Interpret S−H with S and H, and H−A with both
H and A. Zero-versus-zero RH does not demonstrate preservation of a nonzero
benefit. No scalar winner search; report no winner if no profile is acceptable.
A promising candidate requires a separately agreed confirmation step.
