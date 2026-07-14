# Research Backlog

## Adaptive Rubrics for Same-Session Submission Revision

### Current Experiment: One Frozen Rubric

The first implementation studies linear self-revision of a BiomniBench
submission. One persistent solver session produces an initial submission,
receives judge feedback, revises the same live workspace, and repeats. Every
revision becomes the next submission: there is no candidate selection,
rollback, or harness modification.

The judge uses one task-specific rubric frozen before the initial submission.
The primary condition returns the rubric, total and criterion scores, and
bounded criterion-level reasoning. A `score_only` ablation returns only the
total score. Each submission and feedback message is snapshotted, while a
separate frozen audit remains hidden from the solver and is applied after the
trajectory. A separate frozen audit is planned for post-hoc scoring and remains
hidden from the solver. This isolates whether repeated access to rubric
feedback creates genuine improvement, proxy optimization, or reward hacking.

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

- Never allow rubric adaptation to alter the solver, its tools, or the task
  harness; only the judge-side rubric may change.
- Accept updates only after evaluation on held-out exploit traces and honest
  alternative submissions.
- Keep hidden audit evidence out of solver feedback and ordinary rubric-update
  inputs; audit-assisted adaptation is a separately labeled upper bound.
- Preserve all submission, feedback, rubric, and rescore artifacts
  append-only with explicit identities.
- Run the controlled condition inside a verified provider/container filesystem
  sandbox. Treat path separation without enforced read isolation as the
  unrestricted condition, not as proof that hidden judge artifacts are secret.
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
