# Rubric Gen

## Working context

- Use `README.md` for setup and CLI usage, `docs/architecture.md` for code
  ownership, and `docs/rubric_elicitation_workflow.md` for the induction protocol.
  Read the relevant sections, not every historical document.
- For running, recovering, monitoring, or reporting experiments, use
  [rubric-experiments](skills/rubric-experiments/SKILL.md) by reading it explicitly.
  `EXPERIMENT_PLAN.md` owns approved scope; `EXPERIMENT_RUNS.md` owns output paths.
- Complete authorized changes through verification. Answer status/review requests
  with evidence; they do not alone authorize implementation or new runs.
  Ask only when missing information materially changes the result or authority.
- Match verification to risk: use focused tests for changed behavior; broaden
  for shared execution, identity, or scoring changes. Documentation-only changes
  need link/instruction checks, not a full experiment rerun.

## Compatibility and CLI

- Do not preserve, restore, or recommend legacy behavior unless explicitly
  requested for this task. Do not add aliases, shims, fallback parsers, migrations,
  detached legacy checkouts, or fabricated compatibility metadata for obsolete
  interfaces or artifacts. If validation rejects old results, state that clearly
  and generate current-format artifacts through the current workflow.
- Keep public CLIs small and centered on core workflow verbs such as `seed`,
  `revise`, `detect`, and `judge`. Do not expose reporting, plotting, maintenance,
  experiment-design, statistical-analysis, or implementation utilities as public
  commands unless explicitly requested.
- Validate inside workflow commands, before mutation where possible; fail clearly.
  Prefer this to separate validation/status commands. Never add public dry-run or
  preflight modes or flags. Remove obsolete commands and update callers/docs together;
  do not retain deprecated names or compatibility aliases.

## Durable records

Record meaningful new knowledge without a separate request:

- `EXPERIMENT_LOG.md`: experiment decisions, runs, fixes, failures, and results.
- `CODE_REVIEW.md`: implementation questions, correctness/design risks, and
  maintainability concerns; record resolution when a tracked concern is fixed.

Use a date-starting section and prefix each entry with local time and timezone.
Keep entries to one or two sentences. Separate experimental and code concerns;
do not duplicate text, routine checks, or repeated commands across the logs.
