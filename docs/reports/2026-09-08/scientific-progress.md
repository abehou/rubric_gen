# BioMNIBench scientific progress

2026-09-08 19:10 EDT. **The requested four-condition Result20 is complete**, with 240 assignments and native Sol/Opus audit coverage. [Detailed scores and uncertainty](result20-four-condition.md), [interpretation](result20-interpretation.md), and [all report/figure links](../README.md).

| Condition (20 tasks × 3 replicates) | Full-trajectory panel RH | Holistic A | S−H |
|---|---:|---:|---:|
| Full-feedback static |25–26.67%|67.46|1.50|
| User-simulator static |6.67–10%|75.33|0.39|
| Full-feedback red-team trace |16.67%|68.82|−0.04|
| User-simulator red-team trace |20–23.33%|71.52|0.53|

RH ranges are abstention identification bounds, not confidence intervals. Gemini3.8 remains credit-paused. Historical1.7% was per-auditor and is not directly comparable to these panel unions.

## Interpretation for paper planning

Selected-rubric feedback wiring is fixed and published (`6234edf4458c966370f5c0a311c09918affe107c`). The static user setting has modest trajectory headroom and the desired full-feedback > user ordering, but sparse positives and zero final-artifact RH. Positive S−H point estimates do not establish a robust gap when their intervals include zero.

**The current user-trace policy fails the desired mitigation pattern:** more trajectory RH and lower quality. Static quality exceeds trace by3.81points (task-bootstrap95%0.33–8.17). Full-feedback trace has a favorable trajectory direction, but uncertainty touches zero and later RH does not consistently improve. The publication objective remains incomplete.

## Current development work

Jobs10363145(control: static/current trace) and10363146(evidence-support trace candidate) are running on da-11-1, three frozen replicates per condition. The candidate changes only the sidecar prompt, targeting a publicly observable mismatch between claimed computation/results and supporting evidence. Solvers, simulator, evaluators, thresholds and criterion admission are unchanged. Shared concurrency60 and token pacing remain active.

Final matched sources6498d78/4a8cebe retain64K proposer output and4MiB input limits; both pass native inputs for all three canonical dev3 tasks and198tests(1skip). Launcher check10363152 passes32tests. Analysis10363168 follows both scientific jobs automatically. The prepared da-3-4/da-18-1 expansion follows the first real execution gate; no Result20 repeat or other benchmark is currently launched.

The proposed mechanism remains unproven. In Result20, criteria often address narrower interpretation/method issues while auditors flag unsupported execution claims; existing sidecar wording excluded fabricated execution claims. The candidate must still produce publicly observable, independently admissible criteria and improve natural solver behavior. Sidecar success alone is not mitigation.

## Historical completion checkpoints

The following dated snapshots are preserved as execution history, superseded by the complete result above.

## 18:29 EDT revision-completion milestone

Native study status is `completed_scope` with all60 selected assignments completed. Recovery10362700 reused59 successes, finished the last assignment, and entered `detect --resume`. All240 requested revisions are finished; the fourth condition is not yet fully audited.

## 18:41 EDT paced audit recovery

The original audit owner10362700 finished. Full-trajectory Opus has25HTTP429 failures from the10million input-token/minute limit; later direct-RH panels completed bothauditors. Paced recovery10362935 uses unchangedscientificsource and an8million-token sharedwindow, after96tests/native60validation. It runs detect --resume only. Native10362937 feedsusercomparison10362938/combined10362939;figures10359093 andMarkdown10362912 followcombinedcoverage. FullResult20 remains incomplete untilmissingjudgments validate.
