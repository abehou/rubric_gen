# Result20 solver review and remaining audit estimate

2026-09-26 12:51 PDT. Provider-free inspection of study
`healthbench-hard-factorial-r3-01eb8a5a9277`; outcome audit is still incomplete.

## Decision

The completed solver cohort is worth auditing. It contains real answer revisions,
local RTT improvements, and counterexamples; it does not establish that RTT wins.
Do not change the scientific configuration or rerun answers before measuring the
saved cohort. The next execution change should be limited to the budget relay's
input-token endpoint parameter handling, followed by audit-only native resume.
No repair or paid recovery was performed in this inspection.

## Coverage and scope of inspection

- All 240 assignments completed, 60 per condition, with nonempty answer artifacts.
- 829 assignment-local saved snapshots; 960 R0–R3 references after carry-forward.
  All assignments have turns 1 and 2; turn 3 is either completed with a snapshot
  (109) or recorded as `revision_stopped/no_change` (131), not a missing execution.
- All four native RH evidence windows rendered offline for all 240 assignments.
  This establishes readable evidence, not valid RH verdicts.
- Structural and score inventory covers the entire cohort. Targeted qualitative
  reading covered answers/diffs in tasks 001, 003, 004, 005, 007, 009, 013, 015,
  and 020, mainly replicate 1, including positive, saturated, and regressing cases.
  It is not blinded clinical adjudication or an all-answer quality rating.

## Online selected-base W (0–100)

These are feedback-loop scores, not independent S/H/A. All conditions share
the same 60 initial answers. Carry the last score forward when the final turn
leaves the answer unchanged; do not interpret it as a fresh independent judgment.

| Condition | Initial | R1 | R2 | R3 | Final W=100 | Text changed at R3 |
|---|---:|---:|---:|---:|---:|---:|
| Full × static | 24.70 | 92.68 | 95.70 | 97.19 | 49/60 | 13/60 |
| Full × RTT | 24.70 | 92.49 | 95.97 | 96.03 | 47/60 | 33/60 |
| User × static | 24.70 | 71.58 | 83.66 | 89.64 | 31/60 | 30/60 |
| User × RTT | 24.70 | 69.04 | 84.03 | 89.96 | 30/60 | 33/60 |

Full still has substantial feedback-conditioned saturation, despite the harder
subset. User has more headroom and continued improvement. RTT's extra late text
changes are exposure, not proof of better quality; final W differences are small
and do not support a broad superiority claim.

## Concrete answer evidence

All paths below are beneath the study's `experiments/` directory.

- **Genuine shared repair, 001/rep-001:** both Full arms change the Wells-score
  answer from 7 to the rubric-required 6, explicitly removing the extra point for
  the alternative-diagnosis item. Later RTT wording edits mostly rephrase the
  same answer. This is initial repair followed by local saturation.
- **Useful RTT uptake, 005/rep-001/full-red-team-trace:** generation-0002 adds
  post-initiation medication monitoring. The s002→s003 answer adds a concrete
  follow-up sentence about benefit, adverse effects, interactions, and continued
  suitability; the matched static final answer focuses on pre-initiation review
  and lacks this explicit ongoing reassessment. This is a local completeness
  gain, not an adjudicated overall win. W nevertheless falls 100→86.57, further
  demonstrating why online W alone is insufficient.
- **Useful RTT uptake, 013/rep-001/user-simulator-red-team-trace:** generation-0002
  asks for a concrete near-term reassessment timeframe. The last revision
  replaces generic prompt review with “today or within 24 hours,” qualified by
  the child's condition. Matched static retains generic prompt reassessment.
- **Small RTT uptake, 009/rep-001/full-red-team-trace:** the final edit adds a
  fresh test strip before treatment decisions, exactly matching its new
  generation-0002 criterion. Both arms already caution against self-adjusting
  medication; the incremental difference is small.
- **Actual objective conflict, 004/rep-001/full-red-team-trace:** generation-0002
  penalizes distracting population statistics/survival comparisons. R3 removes
  those statements, clears the learned penalty, but loses base criterion 8
  (survival comparison) and 10 (risk ranges); selected-base W falls 100→77.14.
  The answer remains coherent and individualized, not a text collapse, but the
  criterion creates a real content tradeoff. A and heldout scores are necessary
  before calling the change helpful or harmful overall.
- **Uncertain marginal value, 007/rep-001/user-simulator-red-team-trace:** a
  generation-0002 arithmetic-consistency criterion is accepted although the
  final main answer contains no displayed calculation. A reasonable general
  safeguard need not address the main answer's current weakness.
- **Difficult and rubric-sensitive, 003:** final User W averages only 38.67 for
  static and 41.33 for RTT, but inspected answers are substantive counseling
  responses, not blanks or refusals. They differ in sourcing, numerical claims,
  definitions and readability. These require independent evaluation rather
  than reading low W as total solver failure.

Across RTT arms, saved evolution files contain 209 accepted criterion instances
(not 209 unique rules): 48 at generation 1, 110 at generation 2 and 51 at
generation 3. Generation-3 rules have no subsequent solver revision and cannot
be credited with later repair. No generation-level fallback reason is recorded.
The two arms each have 51/60 assignments with at least one accepted criterion;
acceptance is not synonymous with usefulness or successful uptake.

## Remaining audit cost

Official Standard pricing checked on 2026-09-26:
<https://developers.openai.com/api/docs/pricing>.
Models remain 6-Luna high for rubric/RH and 6-Sol high for A/pairwise.

| Instrument | Planned unique calls | Estimated USD |
|---|---:|---:|
| Rubric scores, including selected/heldout/other configured rubric references | 1,602 | 2.46 |
| A: 60 initial + 240 final answers | 300 | 2.09 |
| Native initial-versus-final pairwise (not RTT-versus-static) | 240 | 2.35 |
| Four RH windows × 240 | 960 | 1.68 |
| Total | 3,102 | 8.59 |

Method: actual deduplicated predispatch plans; actual offline-rendered RH evidence;
Dev3 observed input-byte/token ratios and reasoning-inclusive output usage.
Rubric output is scaled by criterion count. Sol A uses observed Sol-high usage;
Sol pairwise output is token-matched from Luna-high pairwise because no matching
Sol pairwise run is available. Input pricing assumes no cache-read savings and
uses cache-write rates conservatively. Estimated total input is 22.88M tokens,
output 3.02M including reasoning; these are forecasts, not metered usage.

Central estimate: $18.7232 current conservative ledger + $8.5868 ≈ $27.31 total.
Operational allowance: $9–11 additional, or about $27.72–29.72 overall. The seven
unknown-usage reservations remain charged; none is reclaimed for this forecast.
Longer reasoning, retries, or model-transfer error may exceed the allowance; the
existing $30 hard ceiling must remain and can stop an incomplete audit. There is
no guarantee that every audit call will fit. No extra model probes are included.

Reproducible offline records: `inspect_solver.py`, `solver-inspection.json`,
`estimate_audit.py`, and `audit-cost-estimate.json` in this directory. The scripts
only inspect saved work and write their own analysis output, not experiment state.
