# Rubric dropout Phase 1

Base: `7178f1968594027c7c27960940029363f58f07b3`.
Branch: `aydan-red-team-dropout`, in `/home/aydanh/repos/rubric_gen_dropout`.
Scope: implementation correctness with local mocked providers; no scientific runs,
Slurm jobs, parameter sweep, model changes, or merge into the trace branch.

## Implementation

The mechanism follows [arXiv:2608.11669v1, sections 3.2–3.3](https://arxiv.org/html/2608.11669v1#S3.SS2):
mask positive-weight criterion contributions after full judging, retain at least
three eligible criteria, and evaluate with the full rubric. This repo adapts the
shared optimization-step mask to one assignment × solver revision turn.

The only new experiment input is `conditions[].rubric_dropout_rate`, default `0.0`,
valid in `[0,1)`, with nonzero values restricted to `red_team_trace`. Existing
condition IDs and the factorial structure stay intact; compare 0.0 and 0.3 with
separate YAMLs. The existing `randomization.seed` becomes the internal revision
config's `randomization_seed`; it is not a new user-facing seed option.

`RevisionScorer._ordinary_checkpoint_feedback` constructs the mask from the active
generation. `project_rubric_feedback` applies it after validating and combining
canonical selected-base judgments with active learned penalties, immediately before
rendering the solver payload. It reuses `validate_judge_score` on retained criteria,
with the sum of their positive maxima as the normalization maximum. Signed points
and clipping remain the existing scorer's behavior; there is no IPW, correction
factor, new judge, or duplicated pipeline.

The RNG is local `random.Random`, seeded by the integer SHA-256 digest of compact
JSON `["rubric_dropout", seed, assignment_id, revision_round]`. Eligible IDs are
sorted before Bernoulli draws; uniformly sampled dropped IDs fill a shortfall to
`min(3, eligible_count)`. Retry/resume use the same key, independently of attempt
IDs and generation numbers. Repeated subsets across different rounds remain possible.

`ProjectedFeedback.score`, controller state, normal checkpoint event `score`, and
rubric evaluation records retain their full canonical values. Only the projected
payload's score/criteria/rubric text are masked. Simulator input uses that same
projection, and reminders consult the retained IDs. Unstructured overall reasoning
is cleared when criteria are dropped because it cannot be safely attributed to the
retained subset. Prior interaction history stays intact. Nonzero checkpoint events
add the rate, key, retained/dropped IDs, and optimization score under `rubric_dropout`.
Completed-study replay reconstructs the same projection; no mask store is added.

Current learned criteria are penalty-only (maximum zero), so they are excluded from
dropout and retain their existing signed contribution. Any future positive-weight
learned criterion would be eligible by the same point-based rule. Informational or
other nonpositive-weight criteria are likewise kept. No new protected criterion
category is introduced. Full evaluation definitions, including RH, W-S, W-A, and A,
are unchanged, as are rubric admission, attacks, proposal logic, judge prompts,
simulator instructions, models, and revision counts.

Zero is a direct mask no-op. Explicit zero normalizes to omission before YAML
identity/serialization, and no dropout fields enter saved manifests/events at zero.
Existing source-provenance hashes change with feedback/trace source edits, so
pre-change artifacts are not promised byte-identical provenance or resume acceptance.
Those existing checks are preserved.

## Verification

Python 3.12.13; locked dependencies installed with `uv sync --frozen --python 3.12`.
The first NFS environment installation/test attempts were stopped after verifying
their owned processes were waiting on NFS I/O. Tests then used
`/tmp/rubric-dropout-env.5Y7wm5/bin/python`, with
`PYTHONPYCACHEPREFIX=/tmp/rubric-dropout-pycache`.

- `python -m pytest tests/test_rubric_dropout.py -q --tb=short`: **30 passed**.
  Covers zero parity, independent process/Python-hash-seed determinism, round
  variation, recovery, minimum retention, rubric immutability, signed weighted
  scoring, all feedback modes, reminders, config identity/wiring, full evaluation,
  and completed-run validation.
- Selected regression suite: **422 passed**. Files: `test_rubric_dropout.py`,
  `test_submission_revision.py`, `test_experiment.py`, `test_trace_attack_defense.py`,
  `test_trace_defense_v2.py`, `test_trace_defense_v21.py`, `test_revision_evaluation.py`,
  `test_full_rubric_judge.py`, `test_evaluation_rubric_judge.py`,
  `test_rubric_evolution.py`, and `test_architecture.py`, all under `tests/`.
- Broader first pass, additionally including `test_experiment_matrix.py` and
  excluding the new tests: **396 passed, 2 failed**. Both failures are inherited path
  expectations, reproduced by executing the base commit's test functions against
  its YAMLs via `git show`: `test_biomni_and_paperbench_use_one_exact_factorial_per_tier`
  and `test_biomni_results_focused_feedback_factorial_reuses_shared_inputs` expect a
  home-relative pool, but the YAMLs use the persistent `/data/user_data/...` pool.
  No experiment config or existing test was changed to hide these failures.
- Direct comparison against parent `feedback.py`, loaded in memory using `git show`:
  **8/8 passed**, with identical scores, payloads and solver prompts for first/later
  Full, Semi, Score-only, and User-simulator projections.

## Local smoke evidence

`python -m pytest tests/test_rubric_dropout.py -k local_trace_smoke -q -s --tb=short`:
**5 passed, 25 deselected**. Four cases cover Full/User-simulator × 0.0/0.3; the fifth
interrupts and resumes the first User-simulator solver turn at 0.3. All use the
current `attack_defense_v2.1` recipe and local mock judge/proposer/attacker/simulator.
Each normal case executes two solver turns and three full selected-rubric judgments;
dropout adds no judge calls. Completed resume makes no new calls. The interrupted
case reuses its exact prompt, saved simulator response, and mask.

Every checkpoint retains full active score **73.0** and independent master score
**80.0** for these fixed fixtures. At rate zero there are no dropout records.

| Feedback | Revision | Dropped criterion numbers | Retained count | Optimization score | Full score |
|---|---:|---|---:|---:|---:|
| Full, 0.3 | 1 | 1, 2 | 6 | 73.33333333333333 | 73.0 |
| Full, 0.3 | 2 | 2, 4, 6, 7, 8 | 3 | 100.0 | 73.0 |
| User simulator, 0.3 | 1 | 1, 3, 4 | 5 | 71.62162162162163 | 73.0 |
| User simulator, 0.3 | 2 | 1, 2, 8 | 5 | 80.0 | 73.0 |

Saved local smoke artifacts and JUnit output use
`/tmp/rubric-dropout-phase1-smoke.kAT63a/`; this is disposable test evidence.
These tests demonstrate implementation correctness, not scientific effectiveness.

## Changed files and reconciliation

Production changes under `src/rubric_gen/submission_revision/`:
`rubric_dropout.py` (new), `feedback.py`, `models.py`, `experiment.py`, `study.py`,
`controller.py`, `controller_scoring.py`, `controller_recovery.py`, `artifacts.py`,
`study_validation_context.py`, `study_validation_artifacts.py`,
`trace_defense_delivery.py`, and `evaluation/targets.py`.
Tests: `tests/test_rubric_dropout.py` (new).
Documentation: `README.md`, `docs/architecture.md`, this report, `CODE_REVIEW.md`,
`EXPERIMENT_PLAN.md`, `EXPERIMENT_RUNS.md`, and `EXPERIMENT_LOG.md`.

Likely reconciliation overlap is in feedback projection, trace reminder delivery,
and manifest/replay plumbing; the helper and new tests are isolated. Once the other
session has finalized and pushed `aydan-red-team`, merge that finalized origin tip
into this dropout branch, preserve the narrow projection hook, and rerun zero-parent
parity plus the 0.0/0.3 Full/User smokes and focused regressions before considering
any merge back. No reconciliation or merge is performed in Phase 1.
