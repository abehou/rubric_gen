# Task/paraphrase-grounded architecture audit

Date: 2026-09-13 (provider-free)

The opt-in `attack_defense_v2.1_task_paraphrase_grounded` candidate does carry
the selected/original and development rubric text into diagnosis, compilation,
and semantic-review requests.  The outcome heldout rubrics are not present in
those requests.  Its attack, quality, rubric-view, application, selection,
admission, delivery, simulator, and outcome paths remain inherited from v2.1.

The candidate nevertheless has a structural omission loophole.  The diagnosis
schema has no obligation-mode field, and the compilation schema can emit only
criterion content.  `render_augmented_rubric` renders every elicited rule with
the claim-conditional scope and an A description that says “No covered claim is
made, or the check passes”.  The application contract accepts
`not_applicable` + level A with no public range.  The learning path turns that
combination into an `ArtifactApplication` and native admission can therefore
accept a rule while assigning no penalty when the solver simply omits the
covered claim.  There is no representation of an explicitly task-required
output whose absence should itself be scoreable.

This is a concrete safe-omission failure, so one versioned RTT-only repair is
justified.  The repair will add an explicit `claim_conditional` versus
`task_required` field to the new diagnosis/compilation contracts.  Only a task
instruction or frozen base-rubric obligation may support `task_required`;
semantic review remains the native check.  Task-required criteria will be
rendered with an explicit omission-is-failure instruction and their application
contract will disallow the zero-penalty `not_applicable` encoding.  Existing
v2.1 and task/paraphrase-grounded records remain untouched.

## Native scoring and identity checks

`compose_rubric_score` reads persisted criterion levels from the active rubric,
so no scoring mathematics changes.  Native `admit_candidates` still owns
observable/nonredundant, support, and aggregate-margin decisions.  The new
criterion's mode is represented in its requirement/rendering and request
receipts; no heldout score or text is supplied to learning.

The exact stage request cache is keyed by the full canonical request, including
prompt, schema, evidence, provider contract, and source manifest.  Read-only
replay revalidates the saved response against the same request-local sources.
The audit/judge path likewise has an exact semantic request identity and
missing-only recovery; no safe provider-side cache change was identified from
the checked-in implementation, so no generic cache layer is added.

## Decision

Proceed with one new versioned task-required candidate.  Do not alter the v2.1
incumbent, the existing task/paraphrase candidate, pair selection, penalty
scale, native admission mathematics, simulator, or outcome definitions.
