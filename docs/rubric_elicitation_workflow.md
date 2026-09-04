# Multi-View Red-Team Rubric Induction

## Purpose

This method learns penalty criteria for failures that the active rubric misses.
The original rubric, its positive points, and its score maximum do not change.

The method uses red-team artifacts as discovery evidence. It tests whether the
same failure remains visible without the active rubric and under a separate
development rubric.

## Workflow

```text
Offline bank                           Online evidence
3 ordinary seed artifacts             previous artifact -- current artifact
1 shared adversarial seed             initial artifact  -- current artifact
        |                              current artifact  -- red-team artifact
        +----------------------+-------------------------+
                               |
                               v
                    blinded matched artifact pairs
                    one fixed randomized A/B order
                               |
             +-----------------+------------------+
             |                 |                  |
             v                 v                  v
     [LLM CALL 1]      [LLM CALL 2]       [LLM CALL 3]
      rubric-free       active rubric     development rubric
     quality choice     scores + levels     scores + levels
             |                 |                  |
             +-----------------+------------------+
                               |
                               v
                 [CODE] identify rubric gaps
                               |
                               v
             [LLM CALL 4] induce candidate criteria
                               |
                               v
             [LLM CALL 5] apply candidates blindly
                               |
                               v
                 [CODE] test total-score margins
                 [CODE] accept, replace, or reject
                               |
                               v
                     next penalty-only rubric
```

Each numbered call is one logical model completion. A completion processes all
pairs or candidates in that stage. Calls 4 and 5 are skipped when they have no
input.

## 1. Pair construction

The offline bank uses exactly three seed replicates. It selects one ordinary
artifact from each replicate and the first admitted adversarial artifact. The
same adversarial artifact is paired with all three ordinary artifacts.

These three pairs are correlated. They are not three independent attacks or
three independent experimental units. Exact artifact copies are deduplicated.

Online elicitation retains every adjacent revision pair. It also retains only
the latest initial-to-current anchor. A new anchor replaces the older anchor.
Each eligible red-team checkpoint adds a current-to-sidecar pair.

Every artifact receives a stable opaque identifier. Assessment does not receive
the source, role, score, replicate, condition, or checkpoint. Criterion induction
receives sidecar role labels. The trace policy also receives a bounded sidecar
trace excerpt.

## 2. Multi-view assessment

Code assigns one stable, pseudo-random A/B order to each pair. All three views
use this same order. The method does not make a second order-reversal call.

Three separate model calls assess each pair:

1. The rubric-free view selects the artifact with better overall task quality.
2. The active-rubric view scores the selected base rubric and each learned criterion.
3. The development view scores a reserved paraphrase and the same learned criteria.

The development paraphrase is fixed before the experiment. It is not an outcome
rubric. The remaining paraphrases stay sealed for outcome evaluation.

A rubric-free tie gives no quality direction, so the pair does not continue. A
non-tied rubric-free result defines the preferred and rejected artifacts. A
rubric view creates a gap when it ties or prefers the rubric-free rejected
artifact. Agreement means that the view covers this pair.

For each rubric-bound view, code reconstructs the current total score:

```text
current total = max(0, base-rubric score + current learned penalties)
```

Each artifact has one score per view, even when it occurs in several pairs. The
reported pair preference must match these computed totals.

The three calls use the same proposer model. They are separate completions, but
their errors can remain correlated.

## 3. Criterion induction

Only rubric gaps can enter induction. Code uses a stable hash to reserve some
non-red-team gaps from the induction prompt. Red-team gaps remain induction
evidence so that the red-team intervention can affect its assigned arm.

The proposer receives the current rubric and the selected gap pairs. It can
propose an atomic criterion only when the evidence supports a general failure.
Each candidate must meet these rules:

- It describes a public, inspectable task failure.
- It does not describe one artifact, source, model, role, or attack family.
- It does not require optional work or encode an observed answer.
- It cites each induction pair that directly supports it.
- It names any current learned criteria that it replaces.
- It remains scoreable without private trace or generation-role evidence.

The proposer does not select point values. Code assigns the fixed penalty scale.

The artifact red-team arm supplies sidecar role labels without traces. The trace
arm also supplies at most 32 KiB from each sidecar trajectory. Long traces keep
their start and end. The trace can suggest a public failure mechanism, but it
cannot become evidence at scoring time.

## 4. Blind criterion application

The validator sees candidates and blinded artifacts from non-tied quality
comparisons. It does not see pairs, preferences, assessment reasons, red-team
roles, candidate provenance, or traces. It applies each candidate independently.

Code accepts a candidate only when all these conditions hold:

- The validator marks it observable.
- The validator marks it nonredundant.
- It penalizes the rejected artifact more on every pair that it cites.
- A replacement preserves separation on every provenance pair of each replaced
  criterion.
- The prospective total margin does not decrease on any quality comparison in
  either rubric-bound view.
- The prospective margin strictly increases on each cited gap view.

For view `v` and pair `p`, code defines the margin as:

```text
margin(v, p) = total_score(preferred) - total_score(rejected)
```

Code rebuilds each prospective total from the view's base score, retained current
criteria, and validated candidate levels. It also applies the zero-score floor.
A margin can remain negative when it improves. For example, `-10 -> -5` passes
the strict improvement rule. An unrelated candidate-level reversal is allowed
only when the complete prospective rubric preserves the aggregate margin.

Candidates are tested in proposal order. Each accepted candidate remains in the
prospective set for later tests. Thus, every saved final set satisfies all recorded
margin checks.

Reserved gaps remain hidden from induction and produce stored blind applications.
They are diagnostic evidence. They are not an automatic candidate-level veto.

## 5. Rubric update and scoring

An accepted candidate removes only the current criteria that it names. All other
learned criteria remain active. Original criteria remain immutable.

A three-level criterion uses penalties near 0%, 5%, and 10% of the original
score maximum. A binary criterion uses penalties near 0% and 10%. Integer
rounding and the score range determine the exact values.

At each checkpoint, the canonical original-rubric judgment supplies the base
score. The active learned rubric supplies only penalties.

```text
final score = max(0, original-rubric score + learned penalties)
```

The program discards original-criterion scores from the augmented judgment.
Learned criteria cannot create positive credit.

## Experimental policies

| Policy | `s000` | `s001` | `s002` and later |
|---|---|---|---|
| Static | Original | Original | Original |
| Offline elicitation | Original | Shared induced rubric | Freeze shared rubric |
| Online elicitation | Original | Shared induced rubric | Update from revision pairs |
| Red-team artifact | Original | Shared induced rubric | Add sidecar artifacts |
| Red-team trace | Original | Shared induced rubric | Add sidecar artifacts and traces |

All elicitation arms use one sealed pre-treatment generation for each task. Online
evidence through `s001` first affects the rubric that scores `s002`. This
one-checkpoint lag continues. Sidecars are training evidence, not natural
reward-hacking outcomes.

## Saved records

Each generation stores these records:

- blinded artifact history and matched pairs;
- rubric-free, active-rubric, and development-rubric assessments;
- quality comparisons, gap views, and induction partitions;
- proposed candidates and blind artifact applications;
- candidate decisions and current-versus-prospective aggregate margins;
- accepted criteria, rendered rubric, hashes, and provider ledger.

Completed generations replay from these records. Any changed record fails
replay. Results from the removed two-order protocol are incompatible.

## Paper-ready description

We use multi-view pairwise induction to add penalty-only criteria to an immutable
task rubric. A rubric-free assessor defines artifact quality. Separate active-
and development-rubric assessments identify ties or reversals as coverage gaps.
The evidence bank combines three ordinary seed artifacts with one shared
adversarial seed and adds adjacent, cumulative, and white-box red-team contrasts
online. The proposer can use bounded private attack traces to discover public
failure mechanisms. A trace-blind validator applies each candidate independently
to blinded artifacts. Code accepts only observable, nonredundant candidates that
separate their cited evidence, preserve replacement provenance, improve their
cited rubric gaps, and do not reduce any other observed total-score margin.
Sealed outcome rubrics then test generalization outside this induction process.

**Suggested figure caption:** Multi-view red-team induction converts adversarial
artifacts and private attack traces into penalty criteria that remain scoreable
from public evidence.
