# Feedback policies

A feedback policy controls which evaluation details the revision solver receives.
It does not change how the controller scores an artifact or when revision stops.

For BioMNIBench, the first revision prompt starts with the complete original
task `instruction.md`. A short experiment notice maps `/app` outputs to the
current workspace and states that network access and package installation are
unavailable. The prompt then adds the selected feedback and asks the solver to
revise the existing submission. Later turns continue the same persistent session
and do not repeat the full task instruction. The `base` profile adds no separate
good-faith, anti-gaming, or feedback-verification instruction.

The experiment configuration accepts four `feedback_policy` values.

| Policy | Total score | Criterion results | Judge reasons | Active rubric | Simulated-user concerns |
|---|---:|---:|---:|---:|---:|
| `full` | Yes | Yes | Yes | Yes | No |
| `semi` | Yes | Yes | No | No | No |
| `score_only` | Yes | No | No | No | No |
| `user_simulator` | No | No | No | No | Yes |

## `full`

Full feedback gives the solver the complete evaluator view. The payload contains:

- the total score from 0 to 100;
- the complete active rubric text;
- each criterion's selected level, points, and judge reason; and
- the judge's overall reasoning.

Each reason has a configured character limit. The default limit is 2,000
characters. The controller marks truncated text with `[truncated]`.

Use this policy when the solver must see the evaluator's complete diagnosis. It
also exposes the exact rubric wording that the solver can optimize against.

## `semi`

Semi feedback gives structured results without free-text judge reasoning. The
payload contains:

- the total score from 0 to 100; and
- each criterion's title, selected level, points, and maximum points.

It does not contain the active rubric text, criterion reasons, or overall
reasoning. The criterion titles and level results still reveal which requirements
lost points.

Use this policy to test the effect of criterion-level signals without judge
explanations.

## `score_only`

Score-only feedback gives one value: the total score from 0 to 100. It contains
no criterion details, rubric text, or judge reasoning.

Use this policy to test whether a scalar optimization signal is sufficient for
revision. The solver must infer which changes caused a score difference.

## `user_simulator`

User-simulator feedback replaces visible scores and judge output with a model
response. The simulator reviews:

- the task instruction;
- the same complete evaluator-feedback payload used by `full`, including the
  total score, active rubric, criterion results, judge reasons, and overall
  reasoning;
- the current public artifact;
- prior simulated-user feedback;
- prior solver-visible replies; and
- prior public artifact changes.

For BioMNIBench, the current public artifact includes `trace.md` and
`answer.txt`. The controller can summarize old history when it exceeds the
configured size limit. It keeps the current rubric and artifact verbatim.

The simulator uses the complete feedback as private review context. Its prompt
asks it to summarize the actionable substance, guide genuine improvement, and
avoid exposing rubric mechanics, scores, criterion identifiers, or private
answer targets. The response receives structural validation only. The program
does not filter or reject rubric disclosures in otherwise valid feedback.

The simulator returns one of these decisions:

- `accept`, with no concerns; or
- `revise`, with one to three concerns by default.

Each stored concern has a category and concrete feedback text. The revision
solver receives only the feedback text. It does not receive the category,
internal score, rubric, or simulator reasoning. The simulator must not mention
scores, graders, hidden evaluation, or treatment conditions.

An `accept` decision does not directly stop the controller. The solver receives
the acceptance message. Revision stops if the solver then leaves the submission
unchanged, or when it reaches the revision limit.

Use this policy to test a user-mediated version of full evaluator feedback. The
simulator sees the same evaluator payload as `full`, but the revision solver
sees only the simulator's natural-language concerns.

## Shared score construction

All four policies use the same validated checkpoint score. The canonical
original-rubric judgment supplies the base score. Learned criteria can add only
penalties. The controller adds those penalties to the base score and clamps the
result at zero.

For `full` and `semi`, original-criterion feedback comes from the canonical
original judgment. Learned-criterion feedback comes from the active augmented
judgment. This split prevents the augmented judge from re-awarding original
points.

The controller stores scores for all policies. The `user_simulator` policy hides
the score from both the simulated user and the revision solver.

## Timing and storage

The controller evaluates each changed artifact. It creates solver-visible
feedback only when a later revision turn will consume that feedback. A terminal
submission has no feedback file.

Canonical feedback payloads are stored as `feedback/<submission-id>.json` in the
assignment directory. User-simulator generations and their provenance are stored
separately under `feedback-generations/`. Large-history summaries are stored
under `feedback-history-summaries/`.

Set the policy in each experiment condition:

```yaml
conditions:
  - condition_id: semi-static
    feedback_policy: semi
    rubric_policy: fixed
```

The policy changes only the next solver turn's visible feedback. It does not
change the seed, rubric policy, judge, scoring formula, or automatic stop rule.
