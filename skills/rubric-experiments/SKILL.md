---
name: rubric-experiments
description: Run, resume, monitor, or report Rubric Gen benchmark experiments with versioned evidence and complete model-panel coverage. Use for experiment progress and recovery; not for unrelated code or documentation work.
---

# Rubric experiment workflow

## Recover context

Read the approved scope, research objectives, and latest current status in
[EXPERIMENT_PLAN.md](../../EXPERIMENT_PLAN.md). Use
[EXPERIMENT_RUNS.md](../../EXPERIMENT_RUNS.md) for output locations and storage
conventions. Historical checkpoints explain earlier attempts, not steps to repeat;
inspect older logs only for the incident at hand.

Confirm process/session state and durable artifacts before reporting activity,
completion, or a stall. A status question calls for read-only inspection, not a
fresh provider probe or restart. Continue already-authorized experiments without
re-requesting settled scope or credential reuse. Ask only for genuinely missing
decisions or authority, while completing independent authorized work.

## Execute and recover

- Use existing core commands and the chosen YAML. Keep the coding agent's model
  separate from experiment roles: optimizing Astra's workflow does not change
  solver, proposer, detector, or judge assignments.
- Before scaling a changed execution path, run the smallest representative real
  end-to-end experiment and validate saved outputs. Reuse valid acceptance
  evidence when the relevant implementation has not changed.
- Record command, session/PID, start time, explicit concurrency, experiment ID,
  log/output paths, and source/config identity, including the dirty-worktree diff.
  Separate protocol versions and invocation logs using the run index.
- Freeze runtime code, prompts, configuration, and analysis definitions during
  execution. Investigate read-only; repair at a safe stage boundary, validate the
  affected path, and use new result identity when required. Record documentation
  changes separately without rewriting archived provenance.
- Use supported `--resume` only when current validation accepts saved work.
  Preserve successful judgments and failed-attempt evidence. For incompatible
  artifacts, generate valid new ones rather than patching hashes or inventing
  missing session state. Destructive `--restart` is not a routine retry.
- Classify transport, rate-limit, credentials/billing, region-eligibility, and
  response-validation failures from evidence. Separate recovered retries from
  terminal failures and protocol fallbacks. Do not retry established permanent
  access failures indefinitely, bypass region restrictions, purchase credits, or
  substitute models without appropriate scope. Preserve affected work and ask for
  the required action; continue unaffected authorized work when possible.

## Monitor and estimate

Track stage transitions, saved/expected unique jobs per model, terminal summaries,
failed attempts and recovery, and time since actual progress. Quiet logs or an
elapsed tool wait do not prove a stall; inspect artifact growth, worker state,
and configured call timeouts before interrupting owned work.

Choose concurrency from sustained throughput, CPU and memory/compression/swap
pressure, disk space, and provider limits. Pass it explicitly: the CLI default or
worker count alone predicts neither request concurrency nor completion time. Do
not interrupt healthy calls simply to chase a higher setting.

Give concise updates at verified startup, stage transitions, new failures, and
material ETA changes. Estimate from successful throughput, serial tails, and later
stages, allowing uncertainty for recovery. Duration targets are estimates, not
overall cutoffs; retain per-call safeguards. Use nonblocking execution/polling so
new user input can steer ongoing work.

## Verify and report

Use the existing private diagnostics indexed for the run, without adding public
reporting commands. Completion requires expected assignments, every configured
stage/provider, consistent terminal summaries, and valid raw records with matching
provenance—not merely exit zero or a finished progress bar. Count shared semantic
judgments by planned unique keys, not duplicated assignment references. Preserve
valid abstentions and report missingness.

Only analyze the declared outcome population after coverage checks pass;
otherwise label results incomplete. Do not substitute surviving-provider means,
exclude unfavorable runs, tune analysis to force hypotheses, or count red-team
sidecars as natural RH outcomes. Report actual rubric changes, fallbacks,
excluded sidecars, unequal treatment exposure, signed RH gaps and quality together
using the plan's task-level comparisons.

Update the current checkpoint/run index when state materially changes and retain
new knowledge in the appropriate root log. Handoff includes counts, output links,
unresolved failures, verified checks, and the next authorized step; distinguish
completed preparation from formal results.
