# Local three-task revision diagnostics

These configs preserve the official Dev3 task, model, randomization, condition,
revision, and paraphrase settings while selecting one Luna
`full-online-rubric` assignment from replicate 1 for each task. Run `seed` and
`paraphrase` before `revise`; do not use the full `run` command for the
revision-only diagnostic.

The configured outcome-audit panel is inert during `seed`, `paraphrase`, and
`revise`. Gemini-only detection uses a separate audit-only config.
