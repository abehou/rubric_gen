# Private experiment diagnostics

Moved from `runs/diagnostics/` on 2026-09-06. These are repository maintenance
scripts, not public CLI commands. Run from the repository root.

Current completed-result readers:

- `openai_verified_table.py`: offline, OpenAI-only verification and eight-condition
  table for the September 6 comparator cohort plus the original red-team cohort.
  Run with `PYTHONPATH=src .venv/bin/python scripts/diagnostics/openai_verified_table.py`.
  Writes only derived reports; leaves incomplete multi-provider summaries intact.

- `model_score_tables.py`: one four-condition/five-metric Markdown table per
  audit model; detected/all percentage and mean 0–10 final-artifact RH score.

- `check_audit_coverage.py`: strict completion, raw/summary agreement and relocation inventories.
- `summarize_outcomes.py`: verified formal outcomes and frozen task bootstrap.
- `summarize_delivery.py`: treatment delivery, fallbacks and sidecars.
- `artifact_locations.py`: offline original-path resolution and byte verification.
- `test_artifact_locations.py`, `test_audit_coverage.py`: current regression checks.

```sh
.venv/bin/python -m pytest scripts/diagnostics/test_artifact_locations.py scripts/diagnostics/test_audit_coverage.py -q
```

Other scripts are historical incident/recovery/backup utilities. Some make
provider calls or refer to retired paths/fixtures; do not batch-run them as
tests or launch them as current recovery commands. `relocate_completed_dataset.py`
records the already-completed one-off move; only its `verify` action remains
applicable. No aliases are left at the previous script locations.
