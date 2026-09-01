# Project preferences

## Compatibility

- Do not preserve, restore, recommend, or regress to legacy behavior unless the
  user explicitly requests it for a specific task.
- Do not add aliases, shims, fallback parsers, migrations, detached legacy
  checkouts, or fabricated compatibility metadata for obsolete interfaces or
  artifact formats.
- When current validation rejects old artifacts, use the current workflow to
  produce valid current-format artifacts. State plainly when old results cannot
  be used by the current workflow.

## CLI design

- Keep public CLIs small and shaped around the project's core user workflow.
- Prefer short verb commands such as `seed`, `revise`, `detect`, and `judge`.
- Do not expose implementation utilities, reporting helpers, plotting, maintenance,
  experiment-design, or statistical-analysis operations as public commands unless
  explicitly requested.
- Prefer automatic validation inside workflow commands over separate `status` or
  validation commands.
- Never add dry-run or preflight modes or flags. Commands should execute their
  stated operation, validate before mutation where possible, and fail clearly.
- When the workflow changes, remove obsolete commands and update every in-scope
  caller and document. Do not retain aliases, shims, or deprecated command names.

## Experimental log

- For every Codex interaction concerning experiments, decide whether it adds a
  meaningful experiment, decision, workflow change, fix, failure, or result worth
  retaining. If it does, append an entry to the repository-root
  `EXPERIMENT_LOG.md` without waiting for a separate request.
- Keep each entry to one or two concise sentences stating what was tried or
  changed and the observed result or current status. Group entries under a
  date-starting section header and prefix each entry with the specific local time
  and timezone; omit routine health checks, repeated commands, and other events
  that add no new experimental knowledge.

## Code review log

- For every Codex interaction concerning code review, decide whether it adds a
  meaningful unresolved implementation question, correctness risk, design concern,
  or maintainability concern worth retaining. If it does, append an entry to the
  repository-root `CODE_REVIEW.md` without waiting for a separate request.
- Keep each entry to one or two concise sentences. Group entries under a
  date-starting section header and prefix each entry with the specific local time
  and timezone.
- Keep experiment records and code-review records separate. Put hypotheses,
  experiment-design decisions, runs, failures, and results in `EXPERIMENT_LOG.md`.
  Put implementation questions and code concerns in `CODE_REVIEW.md`. If one
  interaction contains both, write separate entries and do not duplicate text.
