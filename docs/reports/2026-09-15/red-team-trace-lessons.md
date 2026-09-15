# Red-Team Trace lessons

## What v2.1 established

The v2.1 learner can reduce trajectory reward hacking while preserving useful
artifact quality, but User feedback showed a wider W-S gap than its fixed
control.  W-S is verifier disagreement, S-H is selected-to-heldout transfer,
H-A must be read with both H and A, and RH must be reported separately in all
windows.  A smaller gap caused by lower S or A is not a success.

## What the development candidates established

`task_paraphrase_grounded` showed that selected and development rubric views
should both reach learning stages.  `task_paraphrase_required` added an explicit
`claim_conditional` versus `task_required` mode: required work cannot become
`not_applicable`, while optional claims may.  Its 9/9 User result improved
heldout H and lowered trajectory RH, but W-S widened and repair was inconsistent.

The constructive and failed `da-11-1` cases show why aggregate scores are not
enough.  A task-required rule can lead to captured QC/LR outputs and a bounded
interpretation, but another continuation can remain preliminary and defer the
requested output.  In the failed case, the useful completion contrast was
selected but diagnosis called it redundant with the broad base rubric; no active
completion rule reached delivery.  This is a diagnosis abstraction failure, not
evidence that task-required application or the User prompt should be redesigned.

## Current minimal revision

The next recipe is a versioned diagnosis-only clarification: distinguish a
publicly demonstrated omission or preliminary/unexecuted required output from a
mere restatement of a broad base requirement, preserve supported partial work,
and request the smallest feasible completion or an explicit limitation.  It
keeps attacker, pair construction/selection, rubric views, compilation schema,
application, admission mathematics, penalties, reminder delivery, simulator,
solver, stopping, models, and outcome evaluation unchanged.

## Directions not to revive

Do not stack the v3/v3.1/v3.2 delivery prompts, D×G, P1/P2 or public-firewall
architectures; they did not establish a better parent.  Do not optimize W-S or
S-H alone, add reviewers, use heldout rubrics, leak private targets, tune penalty
values, or convert honest partial work into a generic completeness penalty.

## Interpretation rules

Use matched controls and task-level mechanisms.  Report signed W-S, S-H, H-A
and W-A, and explain whether each movement came from W, S, H or A.  A favorable
S-H movement requires S and H to remain healthy.  H-A can shrink because H rises
with stable A or because A collapses; these are different findings.  Full and
User feedback are separate policy arms, and zero RH windows do not demonstrate
benefit.  Preserve failures and judge disagreements rather than selecting easy
tasks or favorable continuations.
