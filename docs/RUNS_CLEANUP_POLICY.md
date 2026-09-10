# BioMNIBench run retention and cleanup

Authorized on 2026-09-08. Cleanup is deferred while the baseline and policy are
being developed. Do not delete or relocate active experiments, their frozen code
checkouts, runtime coordination files, or shared inputs.

The cleanup gate is a frozen accepted BioMNIBench dev3 baseline and matched
policy, complete provenance, and readiness for the frozen Result20 scale-up (or
completed Result20). Canonical dev3 contains three tasks and three replicates;
a two-task tuning subset alone does not pass this gate. Current experiments have
not established the required baseline-versus-policy pattern, so no cleanup is
currently authorized by this gate.

Before removal, inventory every run directory, including hidden runtime state,
archived attempts, code worktrees, dispatcher receipts and shared pools. Classify
it as one of:

- Canonical baseline evidence: retain raw artifacts, trajectories and audits.
- Canonical dynamic/red-team evidence: retain outcomes and method/exposure evidence.
- Result20 evidence: retain canonical outputs and provenance.
- Important negative, control or mechanism evidence: retain raw evidence needed
  for scientific claims, variability estimates and failure explanations.
- Reproducibility input/shared seed/paraphrase pool: retain; never delete because
  its original consumer appears obsolete.
- Obsolete exploratory run: eligible only after dependency and claim review.
- Infrastructure-invalid/superseded attempt: eligible only when its necessary
  failure/recovery evidence is preserved and no valid state depends on it.

Write a dated cleanup manifest under the normal execution records before deleting
anything. Each directory entry must record run path, experiment ID (or explicit
non-experiment role), source commit/config/hash, scientific role, dependencies,
retain/remove decision and reason, and the durable summary location. Record the
inventory timestamp, reviewed Slurm ownership, action status and eventual deletion
time separately. A planned removal is not a completed removal. The manifest is
an administrative record, never replacement scientific provenance or invented
resume compatibility.

Update EXPERIMENT_LOG.md, EXPERIMENT_RUNS.md and the cross-session handoff with
conclusions before removing eligible raw exploratory directories. Verify no
active/pending job, accepted artifact, test fixture, retained report or downstream
input requires the proposed removal. Preserve the raw evidence behind paper
claims, including important unfavorable findings. Hash/summary records alone do
not replace such evidence. Do not trim failures out of retained successful runs.

Keep canonical directories at their authenticated locations; casual renaming can
break current native resume/analysis identity. Handle inactive Git worktrees
through Git after checking branches and dependencies, not by deleting active
checkout files. Removal is limited to specifically reviewed obsolete paths;
never apply a broad wildcard cleanup to runs/.

The final layout should expose a small set of accepted baseline/policy/dev3 and
Result20 runs, scientifically necessary negative/control evidence, shared inputs,
and runtime/provenance records. Historical scientific conclusions and model
identities remain unchanged. Actual selection of removable paths waits for the
gate and complete inventory; this document removes nothing.
