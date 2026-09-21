# Result40 development-rubric gap diagnostic

## Decision

The observed RTT selected-to-heldout gap is primarily a selected-to-development
rubric mismatch, not a heldout-only generalization failure:

\[
S-H=(S-D)+(D-H).
\]

Relative to static, RTT increases `S-D` by 5.07 points in Full and 2.43 points
in User. `D-H` moves in the opposite direction (-3.27 and -0.89 points), so the
development rubric is generally harsher than the heldout panel on RTT and
partly cancels the selected-rubric optimism. The resulting `S-H` increase is
1.80 points in Full and 1.54 points in User.

Keep the high-reasoning proposer. This diagnostic does not contain a randomized
high-versus-low proposer comparison and therefore cannot estimate a causal
model effect. The saved trajectories nevertheless show that the high proposer
finds the important defects early when the necessary evidence exists. The
earliest remediable bottleneck is downstream: criterion selection/admission,
delivery timing, and revision-budget allocation. A low-reasoning proposer is
not supported by these data and would target the wrong stage.

No new Dev3, Result50, Opus, revision, solver, or existing S/H/A/RH audit run
was launched.

## Frozen scope and completion

- Tasks: `da-26-4`, `da-26-2`, `da-17-1`, `da-17-5`, `da-20-4`.
- Artifacts: saved final artifacts only; Full/User static/RTT, three replicates.
- Rubric: frozen development variant 1 only.
- Panel: equal-weight `gpt-5.6-sol` plus `gemini-3.8-flash`, matching the S/D/H
  reconstruction panel.
- New work: exactly 120 D judgments (60 artifacts x two models), zero revision
  calls, zero failures, and zero abstentions.
- Scientific source: `5a381fd0d9f9a49dd2ee5cf0de1fe30d818c321c`.
- Score job: `10518254`, 83.19 seconds, maximum audit concurrency 12.
- Trajectory export: provider-free job `10518255`, 30 RTT cases, 183,444,416
  bytes, zero provider calls.
- Output root:
  `/data/user_data/aydanh/rubric_gen/runs/rtt-result40-development-score-pilot-20260921/`.

`S` is the saved final artifact score under selected rubric variant 0, `D` is
the same artifact under development rubric variant 1, and `H` is the same
artifact under the rigorous heldout rubrics. All differences below are signed
score points and use the same equal-weight Sol+Gemini panel.

## Scores and decomposition

| Arm | Condition | n artifacts | S | D | H | S-D | D-H | S-H |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Full | Static | 15 | 88.60 | 91.10 | 88.94 | -2.50 | 2.16 | -0.34 |
| Full | RTT | 15 | 67.73 | 65.17 | 66.28 | 2.57 | -1.11 | 1.46 |
| User | Static | 15 | 66.07 | 65.53 | 65.38 | 0.53 | 0.16 | 0.69 |
| User | RTT | 15 | 60.93 | 57.97 | 58.70 | 2.97 | -0.73 | 2.23 |

Paired RTT-minus-static differences:

| Arm | n artifacts | delta S | delta D | delta H | delta(S-D) | delta(D-H) | delta(S-H) |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Full | 15 | -20.87 | -25.93 | -22.67 | 5.07 | -3.27 | 1.80 |
| User | 15 | -5.13 | -7.57 | -6.68 | 2.43 | -0.89 | 1.54 |

Across the five task-cluster means, Full `delta(S-D)` has SD 4.51 and
descriptive SE 2.02; Full `delta(D-H)` has SD 3.97 and SE 1.78; Full
`delta(S-H)` has SD 2.73 and SE 1.22. The corresponding User values are
3.01/1.35, 2.12/0.95, and 1.99/0.89. These are descriptive uncertainty
summaries over five deliberately selected mechanism tasks, not confirmatory
population inference.

The large absolute Full RTT loss is dominated by `da-20-4`: S, D, and H all
fall by about 86-88 points relative to static, while `delta(S-H)` is only -0.83.
That is a common artifact failure, not the source of a widened rubric gap.
The largest selected-to-development divergence is `da-17-5` Full, where RTT
raises S by 5.33 points but lowers D by 6.00; `delta(S-D)` is 11.33, partly
offset by `delta(D-H)` of -8.28.

## Earliest failure stages

1. **Task feasibility and initial execution, before criterion proposing.** All
   three Full `da-20-4` trajectories fail to produce the requested DESeq2,
   apeglm, and Hallmark GSEA evidence because the count extraction/package
   path does not complete. The loop correctly withdraws unsupported NES claims.
   Since S, D, and H collapse together, proposer quality cannot repair this
   class of failure.
2. **Selection/admission and delivery latency.** In User `da-26-2` replicate 3,
   the red-team attack exposes an unsupported PTPN11 claim at checkpoint 0 and
   the high proposer learns a useful biomarker claim-evidence criterion by
   generation 2. The delivered feedback causes the solver to execute the check
   and conclude that no patient-only biomarker is supported. A second necessary
   source-to-result provenance criterion is not admitted until generation 11,
   after the ten-turn revision budget is exhausted. This artifact scores
   S=56.00, D=39.50, H=44.33 (`S-D`=16.50).
3. **Revision-budget allocation after a useful correction.** The same
   `da-26-2` trajectory spends later rounds repeatedly synchronizing
   reproducibility, formatting, identifiers, and execution wording. The solver
   usually applies the delivered corrections, but `max_revisions` arrives
   before the late requirement can be delivered. The failure is scheduling and
   coverage, not inability to diagnose or apply feedback.
4. **Development criteria can expose genuine selected-rubric blind spots.** In
   Full `da-17-5`, trajectories achieve execution-backed donor-level results,
   while the development criteria add evidence-bounded treatment implications
   and execution-supported quantitative claims. S improves under RTT but D
   declines, producing the largest task-level `delta(S-D)`. In Full `da-26-4`
   replicate 2, the loop repairs execution-truthfulness contradictions and
   reaches S=50.50/D=48.50, while H=39.83 shows a separate heldout weakness;
   not every case is selected-rubric optimism.

The trajectory evidence therefore supports retaining the high proposer while
changing, in any separately authorized future method study, how already-found
criteria compete for admission, when they are delivered, and how revision
turns stop or prioritize substantive versus repetitive feedback. This report
does not authorize that follow-up.

## Accounting and limitations

Sol returned usage for all 60 judgments: 366,680 input tokens, 20,008 output
tokens, and 366,500 cache-write input tokens. The dated repository pricing
registry estimates $2.891765 for those responses. Gemini returned no usage
metadata and is absent from that pricing registry, so total experiment cost is
not known; the estimate is not an invoice. Mean worker elapsed time was 6.82
seconds for Sol and 3.38 seconds for Gemini.

The five tasks were chosen for mechanism diagnosis. There is no proposer-model
randomization, no causal high-versus-low estimate, and no basis for extrapolating
the task-cluster SEs to the full benchmark. The report preserves every artifact
and model point so the heterogeneous cases are not hidden by averages.

## Files

- `analysis.json`: complete machine-readable result and definitions.
- `accounting.json`: job, coverage, latency, usage, and cost receipts.
- `model-points.csv`: all 120 model-level S/D/H points.
- `artifact-points.csv`: all 60 equal-weight artifact points.
- `arm-condition-means.csv`, `task-means.csv`: condition and task summaries.
- `paired-rtt-static-differences.csv`,
  `model-paired-rtt-static-differences.csv`, `paired-task-means.csv`: paired
  RTT-minus-static contrasts.
- `uncertainty.csv`: artifact- and task-cluster SD/SE summaries.
- `usage-and-latency.csv`: per-judgment provider timing and usage receipts.
- Provider-free trajectory evidence:
  `/data/user_data/aydanh/rubric_gen/runs/rtt-result40-development-score-pilot-20260921/forensics/trajectory-evidence.json`.
