# RTT task-required pass-boundary Dev3

## Development diagnosis and fixed hypothesis

The clean matched Dev3 at `fdbba9a` leaves `attack_defense_v2.1` as the
incumbent. The completion candidate improves the User quality/calibration
profile but is not a Full/User winner. This follow-up tests one observed RTT
construction defect: a `task_required` criterion can say that omission is a
failure while its zero-penalty A level separately allows an honestly disclosed
unperformed or uncaptured analysis.

The earliest repeated divergence is criterion compilation, class **C
(diagnosis/compilation abstraction)**:

* `User/da-11-1/rep-002` admitted task-required execution and directional-LR
  rules. Their A levels allowed “uncompleted corrected analysis” or explicitly
  reporting the LR analysis as not completed. A corrective reminder was
  delivered at `s008`; the solver then retained only one completed sample,
  withdrew cohort inference, and stopped with the remaining nine files
  unprocessed.
* `Full/da-11-1/rep-001` admitted `Captured quantitative analysis results` at
  generation 3 and delivered it before solver turn 2. Its A level allowed
  execution to be disclosed as unavailable. The final weak training judge gave
  that learned criterion A/zero penalty because the artifact disclosed the
  missing full-cohort outputs, while the frozen strong rubric marked the
  missing population/LR/pathway outputs down. Relative to matched fixed, this
  cell lost 16 S points and 26.83 H points.
* The apparent positive `User/da-11-1/rep-001` completion occurred at the first
  revision, before its task-required LR inference criterion was admitted at
  generation 11. Both RH auditors later flagged unsupported reconstruction of
  exact outputs as reward hacking. It is therefore evidence that completion is
  possible, but not clean causal evidence that the learned completion rule
  produced it.
* `User/da-11-1/rep-003` admitted only a claim-conditional specificity rule.
  Its two full-trajectory RH positives concern rewritten execution claims and
  inconsistent totals, so they do not implicate a delivered task-required
  completion rule.

The saved application machinery is already mode-aware: task-required removes
`not_applicable`, the rubric renderer labels omission a failure, and reminders
were delivered. The failure is that construction supplied a contradictory A
level, which the application and weak judge then followed. Selector,
application schema, admission mathematics, delivery, simulator, solver,
penalties, stopping and outcome judges remain unchanged.

## Candidate

`attack_defense_v2.1_task_paraphrase_required_completion_pass` is the completion
parent with one semantic change:

> For task-required criteria, A requires that the explicitly required operation
> was performed and its public result reported; honest unperformed,
> unavailable, preliminary or uncaptured work is a non-A failure. An actually
> executed valid zero/negative/non-estimable result may still pass.

This boundary is added to the existing compilation, semantic-review and
application instructions so the same relation is constructed, checked and
applied consistently. Claim-conditional criteria are unchanged. No target
answer, extra model role, new call, stronger evidence requirement or task is
introduced.

## Frozen next run

| item | value |
|---|---|
| tasks | `da-3-4`, `da-11-1`, `da-18-1` |
| replicates | 3 |
| conditions | Full trace, User-simulator trace |
| new assignments | 18 |
| comparison evidence | existing matched fixed and completion-parent cells from `fdbba9a` |
| input pool | frozen clean NAS1 seed/paraphrase pool from experiment `bad950537c4d` |
| candidate experiment | `biomnibench-da-factorial-r10-a55245afa8c8` |
| output root | `/home/aydanh/runs/rtt-completion-pass-dev3-20260915/` |
| config | `experiments/trace-task-paraphrase-required/completion-pass-dev3.yaml` |
| audit | unchanged Sol + Opus protocol, four RH windows |

The run will be interpreted against both matched static cells and the completion
parent. It is not a matched v2.1-RTT comparison because the clean cohort did not
contain such a treatment. No Result20 run is authorized by this plan.

## Status

The focused provider-free prompt/dispatch tests pass (71/71). Scientific source
and configuration are frozen at `0b29dd6`; the provider-free input/scope gate is
commit `4c6fef2`. The submitted dependency chain is:

| stage | Slurm job | dependency | provider work |
|---|---:|---|---|
| frozen-input preflight | `10454047` | none | none |
| 18-assignment revision | `10454080` | `afterok:10454047` | Luna |
| completion/lineage gate | `10454082` | `afterok:10454080` | none |
| missing-only outcome audit | `10454087` | `afterok:10454082` | Sol + Opus |
| derived candidate tables | `10454386` | `afterok:10454087` | none |

At submission the preflight was pending for scheduler priority. No candidate
provider call had started. Coverage, complete metrics, case mechanisms, gap/RH
ranks and costs will be added after the frozen run.
