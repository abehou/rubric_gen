# Historical experiment and diagnostic code

These dated directories preserve scripts, configurations and protocols used during development. They are reproducibility records, not the active method or a queue of authorized experiments. Diagnostic variants may require their original local execution checkout and native input records; do not launch them against current outputs.

- Active accepted method: `src/rubric_gen/` and [frozen baseline configuration index](../experiments/frozen-biomnibench/README.md).
- Current report and plots: [BioMNIBench checkpoint](../docs/reports/2026-09-09/baseline-freeze/README.md).
- Rejected policies and interpretation: [failed variants](../docs/reports/2026-09-09/baseline-freeze/failed-trace-variants.md).
- Current report-only generator: `scripts/reporting/frozen_biomnibench.py` (Slurm, no providers).
- Local-only diagnostic payloads: [path/hash inventory](../docs/archive/baseline-freeze-20260909/local-evidence-manifest.json).

Raw data, workspaces and traces are excluded from GitHub. Local execution histories and all raw evidence remain at their original paths. Internal simulator version labels remain in this directory for provenance; use Full feedback and User simulator in formal results.
