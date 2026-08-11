# Outcome-Trained Complete Rubric Generator

## Decision

The deployed generator receives one active submission and the current complete
rubric. It returns the complete rubric for the next revision.

The output is the action. The generator does not emit edit commands, patches,
or a special abstention token. An unchanged complete rubric means abstention.

The generator can retain, rewrite, remove, merge, split, reorder, and reweight
criteria. Each generated rubric applies prospectively. It never changes the
sealed score of the submission that caused its generation.

The original `r0000` rubric remains immutable for common outcome evaluation.
Generated rubrics are working optimizer rubrics and are not longitudinally
comparable without that fixed evaluation.

## Research question

Can a trained complete-rubric generator cause a better next revision without
increasing independently detected reward hacking?

The training target is downstream behavior. It is not textual similarity to a
human rubric or the literary quality of the generated criteria.

## Deployment contract

For revision round `t`, define the generator state as:

```text
state_t = {
  task,
  current complete rubric R_t,
  current submission,
  prior submission history,
  current evaluation,
  read-only sealed artifacts,
  bounded trajectory evidence
}
```

The generator action is:

```text
R_(t+1) = generator(state_t)
```

The harness validates the complete rubric. It does not infer or execute
semantic edit actions.

Every output rubric must:

- Use contiguous numbered criteria.
- Use at least three contiguous level labels beginning at `A`.
- Use strictly descending integer points.
- Include exactly one zero level per criterion.
- Include one nonempty description for each level.
- Sum to 100 across all `A`-level points.
- Contain no more than 100,000 characters.

The harness stores the complete rubric, its parent hash, a changed flag, and a
derived unified diff. The diff is audit metadata. It is not model output.

## Rubric-set quality principles

The generator prompt follows the Recursive Rubric Decomposition approach. A
good complete set is informative, comprehensive, and non-redundant.

The generator must:

1. Map the task to important outcome and analysis-process dimensions.
2. Decompose broad or stacked criteria into atomic discriminative dimensions.
3. Remove misaligned, conflicting, duplicate, and highly overlapping criteria.
4. Stop before decomposition tracks incidental details of one submission.
5. Allocate weight across distinct dimensions without double-counting
   correlated evidence.
6. Keep every criterion task-specific, self-contained, and objectively
   judgeable.

Process criteria should test executed analysis, data lineage, justified
transformations, robustness checks, uncertainty handling, and consistency
between artifacts and claims. Solver-written narration is not proof.

## Offline causal data collection

### 1. Select starting states

Use historical revision boundaries as starting states. Split states by task
before candidate generation. No version of one task can appear in more than one
training, development, or evaluation split.

Historical rubric assignments are not causal labels. They were not randomized
at each starting state.

### 2. Generate candidate rubric sets

For each state, sample `K` complete rubric sets. Always include the unchanged
current rubric as a candidate.

Apply the same structural checks to every candidate. Keep the candidate text
hidden from outcome evaluators.

### 3. Run matched continuations

Copy the same solver state once for each candidate set. Run one revision with
the same solver, prompt, budget, feedback policy, and tool access.

The unchanged-rubric continuation controls for the effect of receiving another
solver turn. Randomize candidate assignment and execution order.

### 4. Measure causal utility

Let `y_R` be the revision produced under candidate rubric `R`. Let `y_0` be the
matched revision under the unchanged rubric. Let `Q` be a blinded common-quality
measure.

```text
U(R, state) = Q(y_R) - Q(y_0)
```

This comparison estimates the effect of changing the complete rubric. Comparing
only with the unrevised submission would mix rubric effects with ordinary
revision effects.

### 5. Apply a reward-hacking veto

Run the independent reward-hacking audit on every continuation. Reject a
candidate when its continuation has a high-confidence reward-hacking label.

Use a lexicographic rule:

1. Reject unsafe continuations.
2. Among safe continuations, prefer the largest common-quality gain.

Do not let quality compensate for detected reward hacking.

### 6. Test superficial compliance

Run one adversarial continuation for promising rubric sets. Instruct the solver
to maximize apparent rubric compliance without improving the task.

Reject a rubric when this continuation gains rubric score without a
corresponding common-quality gain. Also reject it when the reward-hacking audit
fires.

## Training records

Store one immutable record for each candidate set. Each record must contain:

- Starting-state and task identifiers and hashes.
- Current and candidate complete rubrics and hashes.
- The derived rubric diff.
- Generator model and sampling configuration.
- Normal, unchanged-rubric, and adversarial continuation identifiers.
- Blinded quality judgments and provenance.
- Reward-hacking judgments and provenance.
- Eligibility and downstream utility.

Do not include evaluator reasoning in generator inputs.

## Generator training

### Stage 1: Rejection-sampling fine-tuning

1. Keep complete rubric sets that beat the unchanged set on hidden quality.
2. Remove sets that fail reward-hacking or adversarial checks.
3. Fine-tune on `(state, winning complete rubric)` examples.
4. Include unchanged outputs when no candidate helps.

Full-output training can be dominated by copied criteria. Retention is a real
decision, but unchanged tokens must not overwhelm changed set composition.
Store criterion alignment as derived metadata and test criterion-aware loss
weighting during development. Inference must still emit the full rubric.

### Stage 2: Preference training

Create preference pairs from complete rubric sets generated for the same state.
Prefer the set with larger clean downstream utility. Normalize sequence-level
objectives for rubric length so longer sets do not receive an accidental
training advantage.

Keep the optimizer judge and outcome evaluators frozen. Joint training can let
the generator and judge create shared blind spots.

### Training limits

- Train only on task-level training splits.
- Select checkpoints on a task-level development split.
- Evaluate once on untouched tasks.
- Preserve unchanged-rubric examples.
- Limit bootstrap rounds on generated data.
- Do not use arm-specific optimizer scores as task-quality labels.

## Evaluation plan

Compare:

1. Static rubric.
2. Prompted complete-rubric generator.
3. Outcome-trained complete-rubric generator.

Use the same single-lineage interface in all arms. Use one immutable common
quality evaluator and one independent reward-hacking audit.

Primary outcomes are:

- Blinded final task quality against `r0000`.
- Pairwise preference over matched final revisions.
- High-confidence reward-hacking rate.
- Quality conditional on no detected reward hacking.

Secondary diagnostics are:

- Changed-rubric rate.
- Criterion retention, removal, and addition counts.
- Rubric length and criterion count.
- Semantic overlap and task-coverage loss.
- Adversarial compliance success rate.
- Judge agreement and evidence support.

Treat task as the clustering unit. Prespecify quality and reward-hacking bounds
before untouched evaluation.

## Implementation sequence

1. Deploy the complete-rubric inference contract.
2. Validate version hashes, full structure, trace evidence, and derived diffs.
3. Build a deterministic state-fork runner.
4. Add the matched unchanged-rubric continuation.
5. Add blinded quality and reward-hacking evaluation.
6. Add adversarial continuations.
7. Export immutable set-level training records.
8. Train the rejection-sampling checkpoint.
9. Evaluate on untouched tasks before preference training.

Do not add an action-parser compatibility path for the obsolete additive-patch
contract.

## Related work

[Rethinking Rubric Generation for Improving LLM Judge and Reward Modeling for
Open-ended Tasks](https://arxiv.org/abs/2602.05125) introduces recursive
decomposition, misalignment and redundancy filtering, and correlation-aware
weighting for informative, comprehensive, non-redundant rubric sets.

[Learning Query-Specific Rubrics from Human
Preferences](https://arxiv.org/abs/2602.03619) trains reusable rubric generators
from preferred and rejected reports. [Rubric-ARM](https://arxiv.org/abs/2602.01511)
treats rubric generation as an action optimized for preference prediction.

These methods optimize judgment or reward quality. This plan evaluates complete
rubrics by their causal effect on the next solver revision.
