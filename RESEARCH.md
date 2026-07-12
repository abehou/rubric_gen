# Research Backlog

## Adaptive and Co-Evolving Process Rubrics

### Motivation

A fixed process rubric may become easier to exploit as a self-improving agent
accumulates feedback. A promising follow-up is to generate increasingly
challenging, evidence-grounded rubrics from newly observed exploit traces while
the agent hill-climbs.

### Hypothesis

An adaptive verifier that revises its process rubric using immutable execution
evidence and newly observed attacks can reduce proxy--audit divergence and the
acceptance of fabricated or unsupported claims while preserving genuine
held-out scientific improvement. The main alternative is that co-adaptation
only moves the proxy, overfits to known attacks, or creates an unstable arms
race without improving execution-grounded quality.

### Candidate Designs

1. **Periodic adaptation:** after a batch of agent iterations, a separate rubric
   agent inspects exploit traces and proposes evidence requirements, anti-evidence,
   active checks, and revised criterion weights.
2. **Adversarial co-evolution:** alternate between an agent that searches for a
   higher reward and a rubric generator that searches for missed failure modes.
3. **Oracle-assisted upper bound:** permit the rubric generator, but never the
   agent, to learn from hidden audit labels.

Rubric changes should be accepted by a frozen meta-evaluator on held-out attack
traces and honest alternative solutions. Updates should happen in batches, not
after each episode, to limit nonstationarity and direct task memorization.

### Experimental Comparison

- Fixed original process rubric.
- Fixed task-specific evidence-bound rubric generated before optimization.
- Periodically adaptive rubric updated from earlier exploit traces.
- Co-evolving agent and adversarial rubric generator.
- Oracle-assisted adaptive rubric as an upper bound.

Evaluate transfer to unseen source papers, models, and attack families. Primary
outcomes are proxy--audit divergence, accepted fabricated-claim rate, held-out
scientific quality, false rejection of honest alternative analyses, optimization
stability, and verification cost.

### Required Safeguards

- Version every rubric and retain its content hash and parent version.
- Retrospectively rescore every candidate under every rubric version so scores
  remain comparable across the moving objective.
- Keep a permanently frozen audit channel outside both the agent and rubric
  generator workspaces.
- Use disjoint agent and rubric-generator models where practical.
- Prevent hidden audit evidence from leaking into solver-facing criteria.
- Test revised rubrics against held-out honest solutions as well as attacks.

### Failure Modes

- Moving goalposts make iteration scores incomparable.
- Rubrics memorize observed exploits but miss novel strategies.
- Added specificity rejects legitimate alternative analyses.
- The agent and rubric generator collude through shared model biases or
  linguistic conventions.
- Criterion revisions create new, easier proxies.
- Reward nonstationarity destabilizes hill climbing.
- Verification cost grows until adaptation is impractical.

### Why This Is Deferred

The fixed-rubric experiment must first establish the effect of optimization
pressure, validate the independent audit, and identify reproducible exploit
classes. Adding adaptation now would confound agent improvement, evaluator
improvement, and reward nonstationarity. The initial implementation therefore
generates one task-specific rubric from immutable task inputs and freezes it
before hill climbing begins.
