# Research Backlog

## Adaptive Rubrics for Same-Session Submission Revision

### Current Experiment: One Frozen Rubric

The first implementation studies linear self-revision of a BiomniBench
submission. One persistent solver session produces an initial submission,
receives judge feedback, revises the same live workspace, and repeats. Every
revision becomes the next submission: there is no candidate selection,
rollback, or solver modification. A configured revision count of `R` produces
and judges `R + 1` submissions.

The judge uses one task-specific rubric frozen before the initial submission.
The primary condition returns the rubric, total and criterion scores, and
bounded criterion-level reasoning. A `score_only` ablation returns only the
total score. Each submission and feedback message is snapshotted. A separate
frozen audit is planned for post-hoc scoring but is not implemented yet; when
added, it must remain hidden from the solver. This design will help isolate
whether repeated access to rubric feedback creates genuine improvement, proxy
optimization, or reward hacking.

The current controller freezes the optimizer's rubric, judge/scorer code
hashes, review configuration, and effective judge model before `s000`. Each
sealed submission receives a fresh random 128-bit judge-attempt identity. Every
previously scored attempt is non-mutatingly revalidated and its feedback is
re-projected on resume, before each later judge boundary, and before completion;
historical scored attempts are never regenerated. Only the current unscored
attempt may be regenerated if its root is partial or invalid. This prevents a
resume from silently changing the scoring objective or accepted score history.

### Co-Evolution Hypothesis

A fixed rubric may become easier to target as the same solver session learns
its recurring preferences. A future judge-side adaptation mechanism could
revise the rubric in response to unsupported claims, missing evidence, and
other exploit patterns observed in earlier immutable submissions. The central
hypothesis is that evidence-grounded rubric updates reduce the divergence
between solver-visible reward and frozen-audit quality while preserving honest
scientific improvement.

The competing hypotheses are that adaptation merely moves the proxy, overfits
to known attacks, rejects valid alternative solutions, or produces a
nonstationary objective that makes self-revision less effective.

### Candidate Protocols

1. **Frozen rubric:** use one rubric for the full revision trajectory.
2. **Periodic adaptation:** update the judge rubric after a fixed number of
   revision turns using only earlier immutable submissions and judge evidence.
3. **Adversarial adaptation:** ask the judge-side updater to identify failure
   modes that earned high reward and add executable evidence requirements,
   anti-evidence, or active checks.
4. **Audit-assisted upper bound:** allow the updater, but never the solver, to
   use hidden audit labels when proposing rubric changes.

Updates should be batched and follow a prespecified schedule. In the full
feedback condition, the solver receives the current rubric version and its
structured feedback at each turn. In the `score_only` ablation, it receives
only the score produced by that version. This yields a natural factorial
comparison of fixed versus adaptive rubrics and full versus score-only
feedback.

### Versioning and Evaluation

Every rubric version should record its content hash, parent version, update
rationale, evidence inputs, and activation turn. Historical feedback must
remain linked to the exact submission and rubric version that produced it.

Because scores from a moving rubric are not directly comparable, every
immutable submission should be retrospectively rescored under every rubric
version. The resulting submission-by-rubric score matrix separates true
submission improvement from changes in the objective. A permanently frozen
audit should also score all submissions without exposing its rubric, outputs,
or labels to either the solver-facing feedback path or the rubric updater.

Primary outcomes are per-turn proxy--audit divergence, frozen-audit quality,
unsupported-claim acceptance, robustness across rubric versions, revision
stability, and false rejection of honest alternatives. Results should also
measure whether full feedback creates more improvement or more targeted
exploitation than score-only feedback.

### Required Safeguards

- Never allow rubric adaptation to alter the solver or its tools; only the
  judge-side rubric may change.
- Accept updates only after evaluation on held-out exploit traces and honest
  alternative submissions.
- Keep hidden audit evidence out of solver feedback and ordinary rubric-update
  inputs; audit-assisted adaptation is a separately labeled upper bound.
- Preserve all submission, feedback, rubric, and rescore artifacts
  append-only with explicit identities.
- Run the controlled condition inside a verified provider/container filesystem
  sandbox. Gemini's `--sandbox` requests its provider sandbox; Codex
  `workspace-write` is not proof of hostile-process read isolation; and Claude
  requires an externally verified container or equivalent boundary. Label an
  unrestricted ablation only when the provider or container policy actually
  differs. Path separation alone is not proof that hidden artifacts are secret.
- Terminate each provider turn's process group after it exits, while recognizing
  that `setsid`, detached descendants, and other same-user processes can escape
  process-group cleanup. Use external container isolation for hostile-process
  experiments; do not interpret controller path checks as host-level tamper
  resistance.
- Fix the adaptation schedule and compute budget before each run to avoid
  selectively moving the target after unfavorable results.
- Evaluate transfer across tasks, source papers, solver models, and unseen
  reward-hacking strategies.

### Failure Modes

- Rubrics memorize observed exploits but miss novel strategies.
- Additional specificity rejects legitimate alternative analyses.
- Rubric revisions introduce new, easier proxies or shared-model biases.
- The solver targets superficial differences between rubric versions.
- Nonstationarity destabilizes revision or makes online score trends
  misleading.
- Retrospective rescoring and active verification become too expensive.

### Why Adaptation Is Deferred

The frozen-rubric submission loop must first establish whether same-session
revision creates sustained optimization pressure and reproducible reward
hacking. Co-evolution would otherwise confound changes in the submission with
changes in the scoring objective. The current implementation therefore keeps
the rubric fixed, preserves versioning seams for later work, and retains the
artifacts needed for frozen post-hoc auditing before introducing rubric
adaptation.

## Measuring Rubric-Based Reward Hacking

### Measurement Target

In an iterative refinement loop, reward hacking should not be identified merely
because two rubrics score different facets differently. The target phenomenon
is optimization-induced divergence: solver-visible reward improves through
changes that do not improve, or actively damage, the intended task outcome.
This distinction separates ordinary rubric incompleteness from Goodhart-style
overoptimization.

One proposed design begins with a complete human rubric `R`, hides a subset
`S`, retains a visible core `C = R - S`, and generates proxy criteria `S'` from
`C`. The treatment trajectory optimizes `P = C union S'`; a matched control
optimizes only `C`. For any submission `z`, a proxy--expert gap can be defined
as:

```text
D(z) = f(z | P) - f(z | R)
```

The within-trajectory gap growth is:

```text
H_S = D(x_T) - D(x_0)
```

and the control-adjusted difference-in-differences estimand is:

```text
H_DiD = [D(x_T) - D(x_0)] - [D(y_T) - D(y_0)]
```

Here `x` is optimized with `S'`, while `y` is a matched control trajectory that
never sees `S'`. Both are scored post hoc by both `P` and `R`; an evaluation
rubric need not have been visible during generation. If both conditions branch
from the same initial submission, the baseline terms cancel and
`H_DiD = D(x_T) - D(y_T)`.

This estimand controls stable evaluator bias and common refinement trends, but
it does not automatically establish reward hacking. Its interpretation requires
`S'` and `S` to operationalize the same latent facets, a credible expert
reference `R`, matched or randomized treatment and control runs, frozen scoring
instruments, comparable score scales, and no hidden-rubric leakage. Differential
judge noise, shared judge failures, treatment-specific style effects, and an
incorrect `S'` remain confounds. If the rubric co-evolves during optimization,
all checkpoints must be rescored afterward under one frozen evaluation proxy;
otherwise score changes mix submission changes with measurement changes.

### Simpler Primary Alternatives

The rubric-split design creates a second proxy-validation problem: it must first
show that generated `S'` is a faithful substitute for hidden `S`. A simpler
primary design follows established reward-model-overoptimization experiments:
save every checkpoint, track the visible proxy score `p_t`, and independently
measure intended quality `q_t` using blinded domain experts, reproducible task
checks, artifact recomputation, or a prespecified combination. Reward hacking
is evidenced when `p_t` continues to improve while `q_t` plateaus or declines.

Two useful summaries are:

```text
gold regret = max_t q_t - q_argmax_t(p_t)
reversal rate = Pr(expert prefers x_t over x_(t+1) | p_(t+1) > p_t)
```

Gold regret measures the quality lost by trusting proxy-based checkpoint
selection. The reversal rate is a blinded pairwise measure of how often a
rubric-approved revision is substantively worse. Pairwise review should hide
revision order, visible scores, feedback, and model identity.

Additional complementary measurements are:

- **Semantic-preserving exploitability:** optimize formatting, confidence,
  verbosity, headings, or rubric mirroring while holding substantive claims
  fixed and independently verifying semantic equivalence. Score inflation then
  measures judge hackability directly.
- **Counterfactual ablation:** remove evaluator-facing prose that contributes no
  new evidence and measure how much visible score disappears while experts
  judge substantive content unchanged.
- **Integrity-event rate:** use command logs, file-access logs, artifact hashes,
  patch tracking, and grader-side recomputation to detect unsupported claims,
  fabricated analyses, schema-only artifacts, restricted-data access, or
  evaluator tampering. Report task correctness and exploit incidence separately.
- **Feedback placebo experiment:** compare exact rubric feedback with matched
  generic, score-only, irrelevant, or no-feedback conditions, while evaluating
  all outputs with the same independent quality measure.

No single scalar covers all reward hacking. The recommended report combines
outcome-based overoptimization (gold regret and pairwise reversals) with direct
behavioral integrity violations. High gold regret without a detected violation
suggests proxy misspecification or subtle gaming; a verified violation plus
high regret is substantially stronger evidence.

### Relevant Literature

- Gao, Schulman, and Hilton study proxy optimization while tracking a separate
  fixed gold reward, establishing the characteristic overoptimization curve:
  [Scaling Laws for Reward Model Overoptimization](https://proceedings.mlr.press/v202/gao23h.html).
- Pan et al. study the especially relevant iterative self-refinement setting and
  compare improving model-evaluator ratings against human judgments:
  [Spontaneous Reward Hacking in Iterative Self-Refinement](https://arxiv.org/abs/2407.04549).
- Khalaf et al. characterize inference-time reward hacking under increasing
  optimization pressure:
  [Inference-Time Reward Hacking in Large Language Models](https://arxiv.org/abs/2506.19248).
- BITE measures score inflation from meaning-preserving stylistic optimization
  against LLM judges:
  [Turning Bias into Bugs](https://openreview.net/forum?id=7g23tYAIDC).
- Recent tool-agent benchmarks treat evaluation integrity as a separate outcome
  using protected evaluators, access logs, diffs, and trusted recomputation:
  [RewardHackingAgents](https://arxiv.org/abs/2603.11337) and
  [Reward Hacking Benchmark](https://arxiv.org/abs/2605.02964).

## Prompt-Level Mitigation Hypothesis

A low-cost mitigation is to explicitly instruct the solver that judge feedback
is an imperfect diagnostic rather than the task objective. Every improvement
should correspond to a real, independently defensible improvement in the
analysis or answer. The solver should not add unsupported claims, keywords,
sections, confidence, citations, or verbosity merely to match rubric language;
claim unperformed checks; tailor artifacts to evaluator quirks; or remove valid
caveats to sound stronger. This guidance must appear in the initial prompt and
be repeated on every full- and score-only-feedback turn so that iterative judge
feedback does not progressively displace it.

This intervention is expected to reduce blatant gaming but cannot replace
independent evaluation or evaluator hardening. It should be tested as an
ablation, with prompt-only mitigation compared against the unchanged loop using
gold regret, pairwise reversal, integrity-event rate, and ordinary task quality.
