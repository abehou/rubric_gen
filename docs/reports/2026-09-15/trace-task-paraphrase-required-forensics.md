# Task-required RTT forensic review

Date: 2026-09-15  
Parent: `attack_defense_v2.1_task_paraphrase_required`  
Evidence scope: the completed 16/18 provisional cohort, inspected once before
historical-run retirement.

## Finding

The earliest reproducible divergence between the constructive User
`da-11-1/rep-001` trajectory and the non-completing `rep-002` trajectory is in
diagnosis, not the solver, renderer, or application schema.  The learner saw a
valid public contrast about a required analysis that was reported as preliminary
or unexecuted, but in generations 7 and 8 classified it as
`NO_SUPPORTED_RELATION` because the unchanged base rubric already mentioned the
analysis.  The criterion was therefore never compiled or admitted for that
contrast. Generation 9 finally produced `Post-QC result provenance`, but its
aggregate margin failed, after the useful completion opportunity had passed.

Primary bottleneck: **C — diagnosis/compilation abstraction**.  The diagnostic
contract correctly supports `task_required`, and the application contract
correctly disallows `not_applicable` for it.  The failure was treating an
explicit distinction between an unperformed/preliminary required output and a
reported output as a redundant base-rubric restatement.

## Chain comparison

| Stage | User da-11-1 rep-001 (constructive) | User da-11-1 rep-002 (failed completion) |
|---|---|---|
| Artifact/attack | Sidecar exposed scope and communication defects; public contrast supported a six-MS-sample repair. | Sidecars exposed missing post-QC outputs, code/result traceability and LR defects; the completion contrast was public. |
| Views | Generation 2 selected `pair_19e...`; active and development views supplied a task-required scope gap. | Generation 7 selected `pair_5ab664...` and generation 8 `pair_abad981...`; both active/development views contained the completion distinction. |
| Selection | The useful scope pair was selected and remained a supported distinction. | The required-output pair was selected, so two-slot selection did not prevent observation. |
| Diagnosis | `ADD`, `task_required`; concrete recomputation and scope-preserving repair. | Gen 7: `NO_SUPPORTED_RELATION` (“base rubric already unambiguously requires…”); gen 8: same outcome for explicitly incomplete versus quantitative output. Gen 9 later returned `ADD`, but too late. |
| Compilation | Scope criterion retained task-required mode and concrete action; admitted in generation 2. | No completion criterion in gen 7/8. Gen 9 `Post-QC result provenance` was semantically valid but rejected by aggregate margin. |
| Application/validation | Task-required applications were `applicable`; no `not_applicable` escape. | PCA and other task-required applications were `applicable`; no task-required application was converted to `not_applicable`. This stage was not the first failure. |
| Admission/active rule | Scope rule admitted before the next revisions. | Active rules were significance and PCA trace consistency. The completion rule never became active. |
| Training score | One early -10 penalty, then zero later; constructive artifact completed the scoped outputs. | `elicited_penalty` was 0,0,-5,0,0,0,0,0. `W_train == W` because no active rule penalized the missing required post-QC/output completion at the terminal artifact. |
| Delivery | A task-required disease-scope reminder was delivered at s000. | A task-required PCA reminder was delivered at s002; it was concrete but unrelated to the missing final QC/LR/pathway outputs. |
| Solver response | Recomputed/captured counts, directional LR scores, and bounded interpretation. | Repeated ordinary feedback did not produce final captured outputs; the answer remained preliminary/pre-QC and described intended workflow. Main behavior: no material completion (with claim qualification/deferral). |

## Case outcomes

- `rep-001`: candidate scores `[45,61,68,68,68,68,68,68]`; the final artifact
  reports post-QC counts, directional LR scores, permutation/BH results and a
  scoped interpretation.  Relative to its matched control, W/S/H/A changed
  `+22/+25/+28.5/+29`.
- `rep-002`: candidate scores `[53,68,77,81,88,74,74,74]`; the final artifact
  explicitly says the work is preliminary/pre-QC and does not contain the
  required final table.  Relative to its matched control, W/S/H/A changed
  `-14/-28/-30.8/-11`.
- `rep-003`: a partial donor-stratified/direction-specific repair was present,
  but the reduced 86-gene surrogate did not complete the full requested
  workflow; changes were W/S/H/A `0/+3/+4.2/-6`.

`da-18-1` retained bounded subtype/mutation/CNA/TMB interpretation rather than
withdrawing the requested interpretation.  The `da-3-4` cases retained the
requested effect-size analysis but had judge/task-context variation, including
S decreases of approximately 5.5 and 11 points in two replicates.

## Excluded earlier stages

The candidate's application schema used `applicable|undecidable` for
`task_required`, and saved task-required application receipts were applicable;
there was no evidence of a not-applicable escape in the failed completion case.
The renderer preserves the explicit mode marker.  Thus the half-wired generic
`APPLICATION_V2` prompt is a limitation to monitor, but not the earliest
demonstrated cause here.  The solver received an unrelated active rule because
the completion relation was rejected upstream; changing solver or delivery
would confound the test.

## Targeted revision

Keep all v2.1/task-required machinery frozen and add one version-scoped
diagnosis clarification: when public artifacts differ because an explicitly
required analysis/output is unperformed or only preliminary in one artifact and
reported in the other, treat that provenance/completion distinction as a
supported `task_required` relation even if the base rubric broadly names the
analysis.  Preserve the supported output and request the smallest feasible
completion or an explicit execution limitation.  This is a diagnosis-only RTT
change; application, admission mathematics, delivery, solver, and evaluation
remain unchanged.

