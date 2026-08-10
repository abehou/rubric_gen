# Outcome-Trained Dynamic Rubric Generator

## Decision

The deployed method accepts one active submission. It never requires peer
submissions from the user.

At each revision round, the rubric generator returns one short criterion or
`no_patch`. The criterion applies only to the current round. Criteria do not
accumulate.

The generator is dynamic because it conditions on the current submission and
its revision history. Its model weights remain frozen during a user session.

Multiple continuations exist only during offline training. The research harness
creates these continuations from copies of one historical state. The user does
not create them.

## Research question

Can a trained rubric generator choose feedback that causes a better next
revision without increasing independently detected reward hacking?

The current proposer cannot answer this question. Its prompt describes what a
good criterion should look like, but no training signal measures the effect of
that criterion on the next revision.

The target is therefore downstream utility, not plausible rubric prose.

## Deployment contract

For revision round `t`, define the generator state as:

```text
state_t = {
  task,
  current submission,
  previous submission, when available,
  previous criterion and assessment, when available,
  read-only sealed artifacts
}
```

The generator action is:

```text
action_t = no_patch | one criterion
```

The criterion must:

- Contain no more than 30 words.
- Test one task-relevant outcome.
- Be assessable from the answer or sealed artifacts.
- Avoid custom score levels, weights, and long rationales.
- Avoid rewarding documentation, stated intent, or self-authored claims alone.

The revision loop is:

```text
current submission
        |
        v
rubric generator -> one criterion or no_patch
        |
        v
criterion judge -> concise assessment
        |
        v
solver receives feedback and revises
        |
        v
new submission becomes the next state
```

The solver-authored `trace.md` can help locate evidence. It is not proof that an
action occurred or that a result is valid.

## Offline causal data collection

### 1. Select starting states

Use historical revision boundaries as starting states. Split states by task
before candidate generation. This prevents versions of one task from appearing
in both training and evaluation data.

The existing revision studies provide a large state bank. Their observed rubric
assignments are not causal training labels because those assignments were not
randomized at each state.

### 2. Generate candidate criteria

For each state, sample `K` candidate criteria from the current prompted
generator. Always include `no_patch` as a candidate.

Apply the same hard output constraints to every candidate. Do not ask a model to
grade the literary quality of its own rubric.

### 3. Run matched continuations

Copy the same solver state once for each candidate. Give each copy one candidate
criterion. Run one revision with the same model, prompt, budget, feedback format,
and tool access.

Also run a no-new-criterion continuation. This continuation controls for the
benefit of receiving another solver turn.

Randomize candidate assignment and execution order. Keep candidate text hidden
from outcome evaluators.

### 4. Measure causal utility

Let `y_c` be the revision produced under criterion `c`. Let `y_0` be the matched
revision produced with no new criterion. Let `Q` be a blinded task-quality
measure.

The basic utility is:

```text
U(c, state) = Q(y_c) - Q(y_0)
```

This comparison estimates the effect of the criterion. Comparing `y_c` only
with the unrevised submission would mix rubric effects with ordinary revision
effects.

For real user data, `Q` should be the user's blinded pairwise preference between
the two revisions. For benchmark training, `Q` should use a common outcome
evaluator that never sees the candidate criterion or optimizer score.

### 5. Apply a reward-hacking veto

Run the independent reward-hacking audit on each continuation. A criterion is
ineligible for training when its continuation has a high-confidence
reward-hacking label.

Use a lexicographic decision rule:

1. Reject reward-hacking continuations.
2. Among the remaining continuations, prefer the largest quality gain over
   `no_patch`.

Do not let a quality score compensate for detected reward hacking.

### 6. Test superficial compliance

Test promising criteria with one adversarial continuation. Instruct this solver
to maximize apparent criterion compliance without materially improving the
task.

Reject the criterion when the adversarial continuation receives criterion
credit without a corresponding hidden quality gain. Also reject it when the
reward-hacking audit fires.

This test targets criteria that reward statements such as "the analysis was
checked" instead of requiring the check and its result.

## Training records

Store one immutable record for each candidate intervention. Each record must
contain:

- The starting-state identifier and hash.
- The task identifier and split.
- The candidate criterion or `no_patch`.
- The generator model and sampling configuration.
- The normal continuation identifier.
- The matched no-new-criterion continuation identifier.
- The adversarial continuation identifier, when run.
- Blinded quality judgments and provenance.
- Reward-hacking judgments and provenance.
- The final eligibility decision and utility.

Do not store evaluator reasoning in the generator input.

## Generator training

### Stage 1: Rejection-sampling fine-tuning

Start with the simplest stable method.

1. Keep criteria that beat `no_patch` on hidden quality.
2. Remove criteria that fail the reward-hacking or adversarial test.
3. Fine-tune the generator on `(state, winning criterion)` examples.
4. Include valid `no_patch` examples when no criterion helps.

This stage teaches the required output form and the relationship between a
single current state and useful feedback.

### Stage 2: Preference training

Use preference training only after Stage 1 improves held-out results.

Create pairs of criteria from the same state. Prefer the criterion with the
larger clean downstream utility. Direct Preference Optimization is sufficient;
joint generator-and-judge training is not required.

Keep the criterion judge frozen. Joint training can let the generator and judge
develop shared blind spots.

### Training limits

- Train only on task-level training splits.
- Select checkpoints on a task-level development split.
- Evaluate once on untouched tasks.
- Limit bootstrap rounds. Do not repeatedly train on the generator's own
  unverified outputs.
- Preserve `no_patch` so the model is not forced to invent a weakness.

## Criterion judging

Judge one criterion per call. Do not paste a growing rubric into one prompt.

The judge receives:

- The task.
- The criterion.
- The current answer.
- Read-only access to sealed artifacts and harness records.

The judge does not treat `trace.md`, a manifest, a checkpoint description, or a
self-authored audit as positive evidence by itself. If required evidence is
absent, the criterion is unmet.

Use one fixed assessment scale for all generated criteria. The generator does
not write custom levels.

## Evaluation plan

### Baselines

Use the same single-lineage interface in all arms:

1. `no_patch`: ordinary revision without a new criterion.
2. Prompted generator: the current untrained generator with the new short
   output contract.
3. Outcome-trained generator: the frozen trained checkpoint.

Do not combine this experiment with cumulative rubric evolution or the private
integrity generator. Those mechanisms would confound the generator-training
effect.

### Primary outcomes

- Blinded final task quality under one common evaluator.
- Pairwise preference for criterion-guided revisions over matched `no_patch`
  revisions.
- High-confidence reward-hacking rate.
- Quality conditional on no detected reward hacking.

The generated criterion score is an optimization diagnostic. It is not a
primary outcome.

### Secondary diagnostics

- Criterion length.
- `no_patch` rate.
- Fraction of criteria that beat the matched baseline.
- Adversarial compliance success rate.
- Fraction supported by sealed evidence.
- Criterion-judge agreement across repeated blinded judgments.
- Failure categories and recurrence across tasks.

### Analysis unit

The task is the main clustering unit. Revisions from one task and all forks from
one starting state are dependent observations.

Estimate treatment effects against the matched `no_patch` continuation. Use
task-clustered uncertainty. Prespecify quality and reward-hacking acceptance
bounds before the untouched evaluation.

## Research stages

### Stage A: Retrospective feasibility

- Sample historical states.
- Generate short candidate criteria.
- Confirm that the fork runner and blinded evaluations work.
- Estimate how often any criterion beats `no_patch`.

Stop if most criteria have zero or negative downstream utility.

### Stage B: Small causal pilot

- Use a limited set of training tasks.
- Collect normal, baseline, and adversarial continuations.
- Train the rejection-sampling model.
- Evaluate on held-out development tasks.

Stop if the trained generator does not beat the prompted generator or increases
reward hacking.

### Stage C: Preference training

- Build within-state winning and losing criterion pairs.
- Train one preference-optimized checkpoint.
- Compare it with the Stage 1 checkpoint on the same development protocol.

Advance only if preference training adds a clear held-out gain.

### Stage D: Untouched single-lineage evaluation

- Freeze prompts, models, checkpoints, budgets, and evaluators.
- Run the three deployment arms on untouched tasks.
- Use one active submission per assignment.
- Report quality and reward hacking from the common hidden evaluation.

## Implementation sequence

1. Define the state, criterion, intervention, and outcome schemas.
2. Build a deterministic state-fork runner.
3. Add the matched `no_patch` continuation.
4. Add blinded quality and reward-hacking evaluation.
5. Add the adversarial continuation.
6. Export immutable training records.
7. Train the rejection-sampling checkpoint.
8. Add the single-lineage generator interface.
9. Run the small pilot before any full experiment.

Each workflow command must validate its inputs before mutation. Do not add a
dry-run or compatibility path for the obsolete cumulative-rubric workflow.

## Non-goals

This plan does not claim that a trained generator is unhackable. It gives the
generator a causal and user-relevant training objective.

This plan does not train from one user's session alone. It amortizes evidence
from prior randomized revision experiments into a generator that serves one
submission at deployment.

This plan does not use arm-specific rubric scores to claim task improvement.
Only common blinded outcomes support that claim.

## Related work

[Learning Query-Specific Rubrics from Human Preferences](https://arxiv.org/html/2602.03619)
trains a reusable rubric generator from preferred and rejected report pairs.
[Rubric-ARM](https://arxiv.org/html/2602.01511) treats rubric generation as an
action optimized for preference prediction. [Deep Research as Rubric](https://arxiv.org/html/2606.01091)
supports short, atomic, evidence-grounded criteria.

These methods optimize rubric quality or judgment accuracy. This plan changes
the target to the causal effect of rubric feedback on the next revision.
