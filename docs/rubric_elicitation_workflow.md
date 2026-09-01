# Rubric Elicitation Workflow

## Purpose

Rubric elicitation learns additional criteria that detect unsupported or invalid
claims missed by the original task rubric. The original criteria, points, and
score denominator never change. Learned criteria can only subtract points.

## Workflow

```text
Task + original rubric
        │
        ├── Generate sealed clean and adversarial seed artifacts
        │   across all task replicates
        │
        ├── Deduplicate and blind artifacts
        │
        ├── Compare every artifact pair for task-relevant differences
        │
        ├── Propose the complete active learned-criterion set
        │
        └── Validate, render, hash, and seal rubric generation 1
                    │
          ┌─────────┴─────────┐
          │                   │
       Offline             Online
       Freeze generation 1  Update after each eligible checkpoint
```

### 1. Build the pre-treatment artifact bank

For each task replicate, the seed stage produces one primary solution and one
opposite-role solution. The opposite role is adversarial for a good-faith
primary solution, or good-faith for an adversarial primary solution. The bank
admits valid public artifacts without using their scores or detector labels.
Exact duplicate artifacts are removed.

### 2. Blind and compare artifacts

The workflow assigns each unique artifact a stable opaque identifier. It hides
the solver role, score, replicate, chronology, and treatment condition from the
proposer. It then constructs the complete unordered pair graph.

A first model call describes task-relevant differences for every pair. These
differences identify possible failure mechanisms. Pair identifiers provide
audit provenance, not a minimum evidence threshold.

### 3. Propose the complete learned rubric

A second model call returns the complete active set of learned criteria. It can
retain, rewrite, merge, retire, replace, or add criteria. It also chooses the set
size and penalty schedule.

Each learned criterion has these constraints:

- It detects an uncovered way to claim success without task-valid evidence.
- It is claim-conditional. An unclaimed optional feature cannot fail it.
- Its best level gives zero points.
- Each lower level gives a strictly larger negative penalty.
- It cannot reward optional work or create an easier success path.
- It must be decidable from the submitted artifact and visible review evidence.

### 4. Share one pre-treatment rubric

The study compiles one sealed generation-1 rubric for each task and selected
original-rubric hash. Every offline and online assignment for that task installs
the exact same generation. This shared baseline prevents assignment-specific
pre-treatment rubric variation.

### 5. Apply the three rubric policies

| Policy | `s000` | `s001` | `s002` and later |
|---|---|---|---|
| Static | Original rubric | Original rubric | Original rubric |
| Offline elicitation | Original rubric | Shared generation 1 | Freeze generation 1 |
| Online elicitation | Original rubric | Shared generation 1 | Update from prior checkpoints |

For online elicitation, evidence through `s001` creates generation 2, which
scores `s002`. Evidence through `s002` creates generation 3, which scores
`s003`. This pattern continues for later checkpoints. Each update includes all
sealed seed artifacts and all live artifacts available through the preceding
checkpoint.

## Scoring

Each checkpoint receives two logically separate judgments:

1. The canonical original-rubric judgment supplies the base score.
2. The active learned rubric supplies only learned penalties.

The final checkpoint score is:

```text
max(0, canonical original-rubric score + learned penalties)
```

The workflow discards any original-criterion scores produced in the augmented
judgment. Learned criteria therefore cannot re-award original points.

## Validation and audit controls

The system validates the response structure, level labels, integer penalties,
pair references, criterion uniqueness, original-rubric preservation, and score
normalization. It saves the artifact history, pairwise differences, complete
rubric proposal, provider metadata, call ledger, rendered rubric, and code
hashes for every generation.

These checks establish provenance and internal consistency. They do not prove
that a learned criterion is correct, complete, or free from proposer bias. The
online policy is an adaptive intervention because later rubrics depend on
earlier solver artifacts.

## Paper-ready summary

We generated a shared pre-treatment rubric for each task from a blinded bank of
clean and adversarial seed solutions. A two-stage proposer first identified
task-relevant differences across the complete artifact-pair graph and then
returned the complete active set of claim-conditional, penalty-only criteria.
The offline condition froze this rubric. The online condition began with the
same rubric and regenerated the complete learned-criterion set after each
eligible checkpoint using all seed artifacts and prior live submissions. The
original rubric remained immutable, and final scores combined its canonical
score with learned penalties. All rubric generations were sealed with their
evidence, model outputs, provider metadata, and implementation hashes.

**Suggested figure caption:** Rubric elicitation uses blinded pairwise contrasts
between seed solutions to construct a shared penalty-only baseline. Offline
elicitation freezes this baseline, whereas online elicitation updates it using
the accumulating submission history. Both conditions preserve the original
rubric and differ only in post-treatment adaptation.
