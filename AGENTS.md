# Project preferences

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
