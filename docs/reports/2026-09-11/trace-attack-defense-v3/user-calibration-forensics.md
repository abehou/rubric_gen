# User calibration forensic extraction (v2.1)

Saved Result20 root: `/data/user_data/aydanh/rubric_gen/runs/trace-attack-defense-v21-20260911/result20/study/biomnibench-da-factorial-r10-5115fffdd1c0/experiments`.
This provider-free extraction reads sealed feedback, simulator-generation receipts, reminder receipts, prompts, public workspaces, and paired v2.1 case scores. It makes no model calls and does not relabel official scores.

## Scope

Target tasks: da-15-1, da-13-6, da-18-5, da-19-1, da-15-2, da-12-4, da-14-8. Positive controls: da-14-1, da-12-2, da-15-7, da-19-6. Rows: 285 turn records across 33 task-replicates.

## Preliminary evidence taxonomy counts

| classification | turn records |
|---|---:|
| DYNAMIC_OVERSTEER | 25 |
| LIMITATION_OVERUSED | 2 |
| METHOD_OR_SCOPE_DRIFT | 7 |
| NO_REGRESSION | 156 |
| OTHER_UNCLEAR | 27 |
| VALID_WORK_REMOVED | 54 |
| WEAK_STRONG_DISAGREEMENT | 14 |

The machine-readable JSON retains exact paths, hashes, concern text, selected reminder metadata, prompt hashes, before/after workspace hashes, and bounded unified-diff excerpts. The case-summary companion preserves per-task/replicate deltas and dynamic-delivery counts. Classifications are evidence pointers for manual review, not causal estimates.

## Decision note

The saved records support a narrow delivery hypothesis. The current User trace gives the simulator up to three ordinary concerns and then appends a separate focused rule block to the solver prompt. In the seven high-contribution tasks, the largest strong-rubric declines repeatedly coincide with proactive learned selections or with corrective selections alongside repeated ordinary concerns. For example, `da-15-1/rep-001/s003` has two ordinary concerns and a separate proactive normalization reminder; its `s003→s004` public diff changes the primary method/output claim. `da-13-6/rep-001/s000` supplies two task/method concerns while also appending a proactive null-expectation rule, and `da-18-5/rep-001/s000` supplies three ordinary concerns plus a proactive proxy-exposure rule. The exact receipts and before/after public hashes are in the JSON rows for those checkpoints.

The same traces show that the solver often responds by changing scope, method, or requested-result coverage while A improves or remains mixed: `da-15-1/rep-003` has ΔS −60 and ΔA −35 with proactive reminders at `s000`, `s001`, and `s004`; `da-13-6/rep-003` has ΔS −40 and ΔA −19 with proactive reminders at `s000`, `s004`, and `s007`; `da-18-5/rep-001` has ΔS −8 and ΔA +4.5 with three proactive reminders. These are evidence of oversteer/valid-work-removal risk, not proof that every reminder caused the decline. Positive controls also show that the same selector can coexist with improvement (`da-14-1/rep-001` ΔS +17, `da-12-2/rep-001` ΔS +61), so the selector/admission learner itself is not uniformly harmful.

The smallest supported change is therefore User-only **budgeted delivery**: keep the v2.1 selection, but pass it privately to the simulator so it competes for the existing three-concern budget; provide a deterministic private summary of unresolved base criteria ranked by existing point loss; and strip private concern-origin labels before rendering. The attack, learner, evidence binding, admission mathematics, Full path, and solver model remain unchanged. This is a mechanism test, not an admission-coverage target. No provider call was made for this forensic extraction.

## Case-level compact table

The following table reports the saved paired case deltas for the requested target cases. `pro` and `corr` are the selected dynamic reminder checkpoints; they are exposure observations, not causal labels.

| task | rep | ΔS | ΔA | Δ(W−S) | pro checkpoints | corr checkpoints |
|---|---:|---:|---:|---:|---|---|
| da-15-1 | 1 | −2.5 | +12.0 | +25.5 | s003 | — |
| da-15-1 | 2 | +26.0 | +40.0 | −16.0 | s001,s005 | — |
| da-15-1 | 3 | −60.0 | −35.0 | +60.0 | s000,s001,s004 | — |
| da-13-6 | 1 | −5.0 | +4.5 | +5.0 | s000,s002,s003 | — |
| da-13-6 | 2 | −2.5 | −8.0 | +2.5 | s000,s002,s003 | — |
| da-13-6 | 3 | −40.0 | −19.0 | +20.0 | s000,s004,s007 | — |
| da-18-5 | 1 | −8.0 | +4.5 | +8.0 | s000,s003,s004 | — |
| da-18-5 | 2 | 0.0 | −25.5 | 0.0 | — | — |
| da-18-5 | 3 | −13.0 | +14.0 | +13.0 | s002,s004,s006 | s000 |
| da-19-1 | 1 | −10.0 | −2.5 | +10.0 | s001 | — |
| da-19-1 | 2 | −2.0 | −3.5 | +2.0 | s001 | — |
| da-19-1 | 3 | −4.5 | −1.5 | +4.5 | — | — |
| da-15-2 | 1 | +5.0 | +4.5 | +5.0 | s008 | s000–s005 |
| da-15-2 | 2 | 0.0 | −4.0 | −10.0 | s006 | s000–s004,s007 |
| da-15-2 | 3 | −31.0 | +15.5 | +21.0 | — | s000–s006 |
| da-12-4 | 1 | 0.0 | +4.5 | +5.0 | s001,s005 | — |
| da-12-4 | 2 | 0.0 | +5.0 | +5.0 | s000 | s007 |
| da-12-4 | 3 | +14.0 | −2.5 | +5.0 | s000,s002 | — |
| da-14-8 | 1 | +5.5 | +25.5 | −5.5 | s000 | — |
| da-14-8 | 2 | +2.5 | −6.0 | +7.5 | s005,s006 | s000 |
| da-14-8 | 3 | −36.5 | −31.0 | +12.5 | s000 | — |

No-admission rows remain valid scientific outcomes. The v2.1 pipeline receipts distinguish `NO_SUPPORTED_RELATION`, `PREFERENCE_CONFLICT`, support/margin failure, semantic failure, and application undecidable; the companion pipeline tables are the authoritative decomposition. This forensic does not turn any of those outcomes into a defect merely because an admission was absent.

The complete User pipeline has 59/60 assignments with a proposal and 48/60
with an admission, leaving 12 assignments with no online admission. Across
395 generation-level candidate reviews, the saved reasons are 166
`NO_SUPPORTED_RELATION` diagnoses, 275 `PREFERENCE_CONFLICT` diagnoses, 129
criterion-support failures, 136 aggregate-margin failures, 10 semantic failures,
and 79 application-undecidable ineligibilities (some categories occur at
different stages and are not additive assignment counts). There are also seven
empty compilations. These are the documented scientific funnel outcomes, not a
coverage target; the full receipt is
`docs/reports/2026-09-11/trace-attack-defense-v2.1/pipeline-summary.json`.
