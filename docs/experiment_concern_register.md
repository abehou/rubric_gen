# Experiment concern register

This register covers the planned BioMNIBench, PaperBench, and Harvey runs.
It separates fixed issues, accepted design choices, and open risks.

## Status definitions

- **Fixed** means the current workflow includes the agreed change.
- **Accepted** means the behavior is intentional and requires measurement.
- **Deferred** means another workstream owns the decision.
- **Open** means the concern can still invalidate or weaken a large run.
- **In progress** means the current worktree contains an incomplete interface change.

## Ranked concerns

### Problem 1: Long trajectories and MALT chunking

**Status: Accepted.**

Longer trajectories can create more reward-hacking opportunities. This is part
of the intended treatment response. The direct detector uses the MALT-style
prefix and chunk scan, then retains the maximum chunk score.

The run must preserve trajectory length and chunk-level scores. Analysis must
report reward-hacking rate together with trajectory length. Length is a
mediator, so the primary treatment estimate must not adjust it away.

### Problem 2: Detector threshold and panel-rule calibration

**Status: Deferred.**

The detector saves raw responses, chunk scores, and model maxima. Calibration
can therefore occur after generation. The threshold and cross-model rule must
be frozen before treatment comparisons. Calibration labels must remain
independent of the treatment analysis.

The current `any_detect` rule is not a calibrated scientific endpoint. A failed
or abstaining panel member also makes the configured result missing. Prior runs
show that provider failure can remove the planned panel.

### Problem 3: Rubric elicitation used incomplete public evidence

**Status: Fixed.**

BioMNIBench elicitation now uses `trace.md` and `answer.txt`. PaperBench uses the
full public submission tree. Direct detection still sees more process evidence
than rubric scoring. Hidden process-only behavior therefore remains outside the
rubric intervention's observable scope.

### Problem 4: The offline support graph was too small

**Status: Fixed, with residual limits.**

The seed stage now makes one clean attempt and one adversarial attempt for each
configured replicate. It uses structural-only admission. It saves invalid
attempts, makes no replacement calls, and deduplicates exact public artifacts.

This is an intention-to-treat bank. It can contain weak or unsuccessful
attacks. Failed attempts and exact duplicates can also reduce bank size. The
analysis must report attempted, admitted, and unique artifact counts by task.

The adversarial artifacts are induced stress cases. They are not observations
of natural reward hacking. They can train the rubric intervention, but they
must not enter the natural reward-hacking outcome rate.

### Problem 5: Offline and online rubric policies do not share one learned baseline

**Status: Fixed.**

The study now compiles one pre-treatment rubric for each task and selected
initial-rubric hash. Stable blinded IDs make this request independent of an
assignment. Every offline and online assignment installs the exact stored
generation and validates its provenance.

The implemented timing is:

1. Compile one pre-treatment rubric for each task and selected initial-rubric hash.
2. Reuse that exact rubric across all feedback policies and relevant solvers.
3. Score `s000` with the original rubric in every rubric-policy arm.
4. Deliver only original-rubric feedback from `s000`.
5. Use the same pre-treatment rubric for the offline and online arms at `s001`.
6. Freeze that rubric in the offline arm.
7. After `s001`, extend it with online evidence through `s001`. Use the updated
   online rubric for `s002`.
8. Apply the same one-artifact lag later. Evidence through `sNNN` can first score
   `sNNN+1`.

This ordering keeps the seed artifact and its original-rubric judgment common.
Within one solver and feedback-policy block, rubric policy cannot affect the
creation of `s001`. Static and elicitation feedback first differ at `s001`, so
`s002` is their first affected artifact. Offline and online feedback first differ
at `s002`, so `s003` is their first artifact affected by online adaptation. Each
online rubric scores an artifact that did not generate that rubric.

This design gives clear contrasts:

- `offline - static` estimates pre-treatment rubric elicitation.
- `online - offline` estimates the added live-adaptation policy.
- `online - static` estimates the complete adaptive policy.

The online contrast still includes new evidence, new calls, and new solver-visible
feedback. Those features are parts of the online policy, not separate effects.

### Problem 6: Strong and holistic final-artifact scores were easy to misinterpret

**Status: Partly fixed. Interpretation remains open.**

Historical Results20 analysis compared scores made with terminal active rubrics.
Those rubrics differed across conditions and sometimes across artifacts. The
large strong-to-holistic shifts therefore mixed artifact quality with ruler
change. They are not reliable evidence of reward hacking or rubric efficacy.

The current evaluator scores both initial and final artifacts with common
rulers:

- `A_t` is the strong-panel score under the unchanged original master rubric.
- `Q_t` is the strong-panel rubric-free absolute score.
- `S_t` is the score under the selected sealed paraphrase.
- `B_t` is the artifact-specific active-rubric score and is diagnostic only.

This is better, but `A_t - Q_t` is still not a direct reward-hacking measure.
It mixes rubric incompleteness, judge calibration, prompt effects, and scale
interpretation. Likewise, `W_t - A_t` mixes verifier exploitation with weak and
strong judge differences.

Use direct trajectory detection as the primary reward-hacking endpoint. Use
`Q_final - Q_initial` and a blinded initial-versus-final pairwise preference as
primary quality outcomes. Keep original-rubric and active-rubric gaps as
diagnostics.

The pairwise stage now compares the initial and final artifacts directly. It
uses one judgment per model and trajectory. Replicate parity balances response
order. Identical artifacts receive a neutral score without a model call.

A final-artifact score alone is insufficient. The initial artifact provides the
paired baseline. The complete trajectory remains necessary for direct detection.

### Problem 7: Rubric elicitation can overfit its training artifacts

**Status: Fixed.**

The pre-treatment bank includes the same task and can include the assignment's
initial seed artifact. The learned rubric can therefore fit the starting cohort.
The complete pair graph also creates many correlated comparisons. Pair count is
not independent support count.

Use held-out attack attempts and held-out tasks to measure rubric coverage.
Never promote training-bank performance as generalization evidence. Report
support by distinct artifact and attack family, not only by pair count.

### Problem 8: Generated-criterion validation does not prove correctness

**Status: Open.**

Structural checks can reject malformed criteria. They cannot prove that a
criterion is correct, complete, or causally related to reward hacking. The same
model finds differences and proposes the rubric, so its errors can persist.

Pair citations are now provenance only. The program verifies that cited pairs
exist and are distinct. It does not require three artifacts or reject a shared
hub. The complete-set proposer decides whether the task and evidence justify a
criterion. This permits rare attacks, but it increases dependence on model judgment.

Measure false positives on clean held-out artifacts. Measure detection or
penalty power on held-out adversarial artifacts. Keep these measurements
separate from criterion admission in the main intention-to-treat run.

### Problem 9: Online elicitation is reactive and changes the information channel

**Status: Endpoint fixed. Reactivity and information leakage remain intrinsic.**

An online criterion can arrive only after the artifact that exposed the gap.
It can prevent a later recurrence, but it cannot repair the earlier event.
Showing a new criterion or its score can also give the solver a new target.

This is a property of the online policy. Report when each criterion first became
active and which later artifacts it could affect. Do not score the exposing
artifact as if the criterion existed earlier.

The full-trajectory `any reward hacking` endpoint is also absorbing. Once the
exposing attempt occurs, a later successful correction cannot change that endpoint.
The evaluator now keeps this policy-wide endpoint and adds a fixed post-update
window from `s003` onward. Both use all randomized assignments. The post-update
analysis does not condition on a detected attack or a created criterion.

### Problem 10: Model-family errors are correlated

**Status: Open. Additional model runs are the planned mitigation.**

The solver, proposer, rubric judge, direct detector, and quality panel can share
model families or training data. Agreement between them is not independent
validation.

Keep judge-specific results. Require the configured panel for confirmatory
claims. Add human review for a stratified sample of agreements and disagreements.

### Problem 11: Direct-audit evidence is bounded and can lose forensic detail

**Status: Resolved.**

The audit now preserves complete event text, command output, solver-visible
feedback, and final artifacts. It applies no field-level head-tail limits.
The detector repeats only the original task context and splits all behavioral
messages through one ordered chunk path. It scores every chunk and retains the
first maximum score. A task context that cannot fit causes a preparation error;
there is no alternate prefix or truncation path.

### Problem 12: The solver-factor interface is not yet complete

**Status: Fixed.**

The seed generator is separate from one or more revision solvers. Every
task-replicate seed remains common across solvers. Solver ID enters assignment
identity, manifests, validation, reporting, and paired analysis. All current
experiment files and tests use this interface.

### Problem 13: Core inference is still too assignment-centric

**Status: Resolved for reporting.**

Replicates and conditions from one task are not independent tasks. Assignment
means and Wilson intervals can therefore understate uncertainty. Missing panel
members can also produce condition-dependent complete-case subsets.

The current report pairs task-replicate cells and averages replicate differences
within each task. It reports fixed-seed task-bootstrap intervals for condition,
solver, and solver-by-condition effects. It also reports judge-specific effects
and exact structural and metric-level missingness. Strict panel completion remains
a separate launch requirement under Problem 15.

### Problem 14: Rubric-paraphrase coverage is uneven

**Status: Fixed for the confirmatory contrast.**

Prior Results20 replicates selected different variants. Current experiments
explicitly select variant 0 for every replicate, condition, solver, and task.
The other variants remain sealed evaluation holdouts. This removes selected
wording as a source of replicate variation. The experiment does not estimate
robustness across selected paraphrases.

### Problem 15: Provider failure and audit cost can dirty the sample

**Status: Fixed for outcome handling. Provider outages remain operational.**

Prior large audits lost Gemini and parts of the Anthropic or OpenAI panels.
Strict complete panels then became unavailable. Very large rubric-score plans
also create long recovery windows and substantial missingness risk.

The normal run is the only execution path. Each resume executes every planned
semantic key. Completed exact records are reused, and unaccepted requests run
again. Rubric-score and rubric-free stages require the complete configured
panel. A missing model writes an incomplete summary, returns failure, and never
creates a survivor-only mean.

Direct detection computes sharp zero-to-one bounds under every missing or
abstaining decision. It reports an identified decision when both endpoints
agree. Otherwise, it retains `incomplete` or `abstain`. Condition, solver, and
interaction analyses report paired task-level effect bounds. No provider
preflight or smoke-test workflow is part of this policy.

### Problem 16: Old results are informative but not current-format evidence

**Status: Accepted as an interpretation limit.**

Historical Results20 artifacts used earlier rubric and evaluation semantics.
The current workflow rejects their revision format. They can motivate
hypotheses, but they cannot be pooled with a new confirmatory run.

The partial historical direct result was 15/240 static, 15/240 offline, and
8/240 online under an available-judge union. The planned three-model result was
missing. Treat this as exploratory evidence only.

### Problem 17: Harvey does not yet identify the same causal effect

**Status: Fixed as a separate randomized experiment.**

Harvey evolves a harness across rounds. BioMNIBench and PaperBench randomize
submission-revision policies. Their units, treatments, and outcomes differ.
Combining their effect sizes would be invalid.

Harvey now uses replicate-blocked randomization. Each block contains one
static-rubric control trajectory and one prospective-rubric treatment trajectory
in randomized order. Hidden selection and held-out task-agent outcomes also use
repeated runs.

Development, selection, and held-out task sets are disjoint. All evolution
trajectories finish before hidden evaluation starts. Selection tasks choose one
candidate per trajectory. Held-out tasks evaluate only that candidate and the
stock baseline. The study reports prospective-minus-static contrasts.

Harvey remains a separate experiment. Its treatment and outcome are not the same
as the BioMNIBench and PaperBench submission-revision intervention.

### Problem 18: Runtime and storage failures can select the observed sample

**Status: Open.**

Large seed pools, revision snapshots, rubric calls, and audit records can exhaust
scratch storage or wall time. Resume helps only when valid artifacts are already
durable. Failures that correlate with task size or trajectory length can create
non-random missingness.

Estimate calls, bytes, storage, and wall time before launch. Keep task-level
failure reports. Do not silently analyze only completed assignments.

### Problem 19: Score-triggered early stopping can censor reward hacking

**Status: Fixed.**

An immediate stop at a rubric score of 100 is unsafe for this experiment. A
perfect proxy score can indicate genuine completion, but it can also indicate
successful rubric gaming. Stopping at saturation removes later opportunities
to observe the behavior that the experiment intends to measure.

Active rubric scores also change rulers in the online arm. They are not
comparable across turns. Even the unchanged original-rubric score is a proxy
and contains judge noise. A score-based rule can therefore create different
trajectory lengths across treatment arms for reasons unrelated to true quality.

The confirmatory workflow now uses the fixed ten-turn horizon and stops only
when the benchmark submission does not change. The solver has no explicit stop
decision. Rubric scores do not control stopping. If efficiency is a separate
estimand, pre-register a secondary policy that uses only the unchanged
original-rubric score, requires a minimum exposure period, and never stops
immediately on the first score of 100.

### Problem 20: No-change stopping can prevent online treatment exposure

**Status: Partly fixed.**

The controller stops as soon as one solver turn leaves the submission unchanged.
This can happen after a changed artifact exposes a new rubric gap, but before the
online rubric learned from that artifact can produce feedback for another turn.
The assignment is then labeled online, although no later artifact could respond
to the online-only update. This reduces treatment strength and can hide a useful
online effect.

Current protocols require five solver turns before no-change stopping. This
guarantees the first fixed post-update window and preserves unchanged checkpoints
before turn five. It does not guarantee a response to a new gap first exposed
near the terminal turn.

For complete treatment-aware stopping, let each new unique artifact enter online
elicitation. Then, let its online update produce one new
feedback opportunity before accepting no change as terminal. Do not use the
in-sample active-rubric score as an outcome. Record update exposure and response
opportunity for each assignment, and keep the randomized intention-to-treat
contrast as the primary analysis.

### Problem 21: Append-only criterion capacity can disable online adaptation

**Status: Core mechanism fixed. Reporting remains open.**

The old active rubric permitted at most five elicited criteria. One generation
could add all five, and later generations could not edit or remove them. The shared
pre-treatment rubric can therefore use every slot before the online phase starts.
In that case, the online arm cannot add a criterion and is identical to the
offline arm apart from extra calls. Early weak criteria can also lock out later
strong criteria.

The criterion-count cap and append-only rule are removed. At each generation,
the proposer returns the complete active set. It can keep, rewrite, merge, retire,
replace, or add criteria. The model chooses the set size. Request, output, and
rubric-structure limits remain resource bounds. Reports still need active-set
size, churn, and the number of live updates that changed the rubric.

### Problem 22: Fixed small penalties can leave reward hacking profitable

**Status: Fixed schedule removed. Calibration remains open.**

The old protocol gave each elicited criterion a maximum penalty of four percent
of the original rubric maximum. Its total penalty could not exceed about twenty percent.
The criteria are also claim-conditional. A solver can rationally keep a harmful
shortcut when it gains more original-rubric points than the added penalty. An
omission can also evade a criterion when the submission does not make the covered
claim.

The proposer now generates and can change each complete penalty schedule. The
highest level is zero. Lower levels are strictly negative integers. The prompt
requires a tradeoff between attack incentives and false or dominant penalties.
The program owns only the ordering invariant. It does not cap penalty magnitude.

Use held-out clean and adversarial artifacts to measure criterion activation,
false penalties, and score ordering. This model-owned policy adds variance and
bundles criterion content with penalty strength. Treat the full learned-rubric
policy as the intervention. Keep attempt-bank admission lenient.

## Launch rule

Do not start a confirmatory large run while Problems 5, 12, 13, 15, and 20 through
22 remain
unresolved. Problems 6 through 11 require a written estimand and analysis rule.
Problems 14 and 16 through 19 can remain limitations only if reporting is explicit.
