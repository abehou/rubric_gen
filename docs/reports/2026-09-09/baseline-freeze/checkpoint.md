# Accepted baseline checkpoint

## Scope and evidence

The static baseline is frozen. Formal feedback names are **Full feedback** and **User simulator**; the internal simulator provenance label is retained only in version/configuration/source records. [Complete available results and plots](README.md) cover the two static arms (60 each), User simulator trace (60), and Full feedback trace (59). No new policy is adopted and no experiment is launched.

## Selected/master wiring and source verification

Correctness commit **6234edf** is retained. `test_selected_reference_later_checkpoint_and_resume` exercises every feedback policy across later checkpoints and resume: selected-rubric scores61/71/95 remain distinct from master80/55/65, feedback records carry the selected rubric hash, and the simulator consumes selected criterion feedback. Heldouts remain evaluation-only. The feedback composition tests additionally distinguish selected-base W from W_train after learned penalties.

The active submission-revision package is byte-identical to **7cf34ef**: accepted scientific source **0fbe0bb**, scoped pretreatment reuse correction **314ea3d**, and duplicate-evidence correctness fix **30ae38e**. Duplicate identical evidence is counted once; unique evidence, policy, prompts, scoring and feedback content are unchanged by that fix. Producer59 used314ea3d, not30ae38e; the cancelled replacement is excluded.

A bounded detection token-count connection retry is retained outside the scientific package. Later speculative simulator, induction, admission, active-violation delivery and assignment-scope changes are removed from the active scientific package. Their commits, configs, execution checkouts and evidence remain available. The unlaunched retention draft is archived as a patch and test source. No metadata was rewritten to claim cross-version resume.

[Input/implementation field and hash comparison](../cue-full-compatibility.md) and its JSON receipt establish reuse of the earlier Full feedback static. The earlier Full feedback trace is scientifically different and is not substituted for the missing case. The new report revalidated956 state/composition hashes and matched initial-artifact/selected-rubric identities across every available case.

## Measurement and interpretation

Freeze tasks, seeds, simulator, scoring and current Sol/Opus auditors. Gemini3.8 Flash remains configured but unexecuted; no model replacement is implied. W−S and W−A regressions under trace are preserved. S−H≈0.12 for User simulator static is acceptable for semantic paraphrase heldouts. Final-artifact calibration is unfinished and separate; no threshold/prompt change or revision rerun has been made.

The baseline is accepted, not the complete mitigation hypothesis. Further trace optimization and30/45 confirmation await the user's next instruction.

The [Result20 heldout V2 static baseline](../../2026-09-10/result20-heldout-v2-static.md) regenerated all 471 wording units with zero fallbacks. User simulator S−H is now a healthy positive baseline at1.364.

## Historical evidence and cleanup

[Failed variants](failed-trace-variants.md) remain negative/adverse evidence. [Archived drafts](../../../archive/baseline-freeze-20260909/README.md) are not active methods. Raw outcomes, execution worktrees, input pools, manifests, audit logs and failed-attempt traces are retained at their original paths. Cleanup is limited to explicitly inventoried disposable caches and moving supplied reference figures to a labeled historical archive after publication.

## Verification

324 provider-free tests passed:284 revision/feedback/resume/induction/duplicate-evidence/pretreatment/config/detection/scope tests, plus40 matrix/judgment-reuse/judging/Babel recovery/monitor tests. Report-only CPU job10380610 validated956 state/composition hashes, matching inputs, exact available inventories and frozen metric definitions; figures were visually inspected. No threshold, auditor, solver, seed or task was changed.

The published CSV uses LF line endings; values are unchanged from the validated report job. Archival patch whitespace is preserved so the drafts remain exact.
