# Acceptance v4 — end-to-end diagnostic completed

Four development assignments completed, with six valid red-team sidecars.
Revision execution after shared preparation took 14m03s. The three-provider
audit began at 11:43:22 CST and the full workflow exited 0 by 11:48:50 CST.

All seven audit outputs completed with no missing provider or failed semantic
judgment: four direct windows × 12 judgments, 87 rubric-score judgments,
15 rubric-free absolute judgments, and 12 pairwise judgments (162 total).
All 48 direct verdicts were no-RH; one development task does not establish a
treatment effect, so these are acceptance results, not Results20 evidence.

The shared initial rubric admitted one criterion. Five of six online generations
had no stage fallback; full-feedback/artifact generation 3 exhausted six active
rubric-view attempts because the model's preference contradicted its own scores.
The last failure named totals 90 versus 80 and the required winner. No observed
array-order fallback remained after the v4 fix.

V5 removes the redundant rubric-view preference output and computes exactly the
already-specified higher-total/tie rule in code. Rubric-free preference remains a
model judgment. Two real artifact-history component regressions exercised all
five proposer stages with five calls each, no retries/fallbacks, and successful
current-format generation reload (80.7s and 68.4s); 720 regression tests pass with
the two previously documented environment exclusions.

The accepted readiness evidence combines this complete small workflow with the
targeted v5 verification of the only subsequently changed component. It does not
claim a complete v5 small-study rerun. V4 artifacts remain historical records;
do not resume or relabel them under the changed v5 response contract.

- Study: `runs/preflights/assessment-contract-v4/biomnibench-da-factorial-r3-b07888ff76df`.
- Audit: `runs/preflight-detections/assessment-contract-v4/biomnibench-da-factorial-r3-b07888ff76df`.
- Log: `runs/logs/biomni-redteam-acceptance-v4-20260905-1127.log`.
- Source archive: `runs/provenance/20260905-redteam-v4/`.
- Isolated v5 regression: `runs/diagnostics/score-derived-v5/summary.json`.
