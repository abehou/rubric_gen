# Bounded rubric-cue simulator comparison

2026-09-08. Explicit user/collaborator request: slightly more rubric-leaking user feedback, minimal frozen-dev3 validation, then larger BioMNIBench evaluation (30 or45 tasks) with other settings unchanged. Continue red-team policy work concurrently without interrupting owned jobs.

## Hypothesis and treatment

Allow at most one of the existing maximum three concerns to quote one short requirement from the supplied training rubric and explicitly link the requested revision to that requirement. The selected rubric is already solver-visible; this is increased rubric specificity in revision feedback, not access to held-out or holistic evaluations. The supplied training rubric can include admitted dynamic criteria in policy arms. No additional feedback source is introduced.

Parent control6498d78, isolated source runs/babel-code/dev3-rubric-cue. Only the simulator instruction paragraph changes, plus the focused prompt-contract assertion. Preserve all other simulator wording, current artifacts/history/evidence, max_concerns3, token limits, solver, proposer, evaluators, RH thresholds, revision budgets and selected/master wiring. Do not introduce evidence-sidecar or contrast-proposer changes in the first simulator comparison.

## Dev3 design

Use canonical da-3-4, da-11-1, da-18-1 with three frozen replicates and seed20260806. First da11 test compares the new user-static simulator condition against current immutable control10363145; inspect full native metrics and verify matching initial/selected hashes. Extend the unchanged static control and rubric-cue arm to the other two canonical tasks for full dev3 validation. Keep ongoing policy10363145/46 and prepared59fb4d0 separate; policy candidates must later be matched to the accepted simulator.

Collect all four RH windows by auditor/panel/abstentions, monitor-score distributions, W/W_train/S/H/A/all gaps, artifact quality, revisions/stops, and actual feedback quotation frequency. Do not claim an implemented prompt produced actual leakage without inspecting generated feedback. A null or harmful result is retained. No arbitrary RH percentage or lowered detector threshold defines acceptance.

## Larger evaluation plan

Prefer45 canonical tasks ×3 replicates after dev3 validation, retaining the original20 Result20 IDs. Select25 additional tasks deterministically from the same pinned public BioMNIBench source, excluding canonical dev3; freeze IDs and hashes before outcome inspection. Keep original Result20 historical records immutable and name the extension results45. Following the latest user clarification, only user-simulator static and red-team trace comprise the intended matched comparison (270assignments at45tasks×3replicates×2conditions); any accepted simulator/policy changes are frozen before scale, with unchanged evaluators and metrics. Shared seed/paraphrase reuse requires native validation, not rewritten manifests.

More tasks improve expected precision but do not guarantee narrower observed intervals or the desired effect. Report paired task-level uncertainty and task dependence; do not selectively exclude difficult tasks or choose sample size from favorable outcomes. No PaperBench/Harvey expansion.

Primary development readout: equal-weight Sol/Opus final-artifact and full-trajectory RH. Keep per-auditor decisions, abstention bounds and panel union visible; the user's10–15% full-trajectory static range is guidance, not a threshold to manipulate or a reason to discard nulls.
