# Rubric Gen

Run a preregistered, randomized 2×2 BiomniBench revision study. The supported
scientific workflow compares a base solver prompt with one treatment prompt and
a static rubric with prospective rubric evolution.

## Setup

Requirements: Python 3.11+, `uv`, the Hugging Face CLI, an authenticated
`codex` CLI, and `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, and `GEMINI_API_KEY` for
the three-member RH audit.

```bash
uv sync

hf download phylobio/BiomniBench-DA \
  --repo-type dataset \
  --revision e1c8ca5e11a620087bc48d97888eb69176a1f235 \
  --local-dir data/biomnibench-da \
  --exclude "da-1-3/**" --exclude "da-1-4/**" \
  --exclude "da-17-1/**" --exclude "da-17-3/**" \
  --exclude "da-17-5/**" --exclude "da-19-3/**" \
  --exclude "da-19-4/**"

uv run biomnibench-agent --help
uv run malt --help
```

Commit all code and configuration changes before creating a design. Scientific
commands reject a dirty Git worktree and bind the design to the exact source
tree, lockfile, CLI binary, model settings, host, and task hashes. Outputs under
`runs/` are ignored.

## 30-task, 10-round, semi-feedback 2×2 study

```bash
DATASET_REV=e1c8ca5e11a620087bc48d97888eb69176a1f235
DESIGN=runs/biomnibench-study/diligent-semi/design.json
SEEDS=runs/biomnibench-study/diligent-semi/seeds
STUDY=runs/biomnibench-study/diligent-semi/study

uv run biomnibench-agent design \
  --tasks-dir data/biomnibench-da \
  --output "$DESIGN" \
  --protocol-id diligent-semi-v1 \
  --dataset-revision "$DATASET_REV" \
  --random-seed 42 \
  --sample-size 30 \
  --replicates 3 \
  --revision-rounds 10 \
  --feedback-policy semi \
  --treatment-prompt diligent \
  --model gpt-5.6-luna \
  --reasoning-effort minimal \
  --retries 1 \
  --judge gpt-5.6-luna \
  --judge-max-retries 1 \
  --rubric-proposer-model gpt-5.6-luna \
  --rubric-proposer-step-limit 12 \
  --rubric-proposer-max-retries 1 \
  --primary-rh-rule majority \
  --audit-max-command-output-chars 2048 \
  --audit-max-retries 1 \
  --audit-max-cost-usd 1500

uv run biomnibench-agent seed \
  --design "$DESIGN" \
  --output-dir "$SEEDS" \
  --max-concurrency 12

uv run biomnibench-agent run-design \
  --design "$DESIGN" \
  --seed-run-dir "$SEEDS" \
  --output-dir "$STUDY" \
  --max-concurrency 12
```

Resume either long stage with its identical command plus `--resume`. A failed
or interrupted assignment is retried from its last validated scoring boundary.
A completed assignment is reused only after deep integrity validation; corrupt
completed output becomes `invalid` and is never silently skipped or retried.

Check completion before auditing:

```bash
uv run biomnibench-agent status --design "$DESIGN" --run-dir "$STUDY"
```

The command exits zero only when every assignment is complete and valid.

Run the locked, metadata-blinded RH panel. Exact task and condition identifiers,
manifest treatment fields, judge reasoning, rubric text, final scores, and
feedback not shown to the solver are withheld. The score-and-criterion feedback
actually shown before each revision is retained because removing it would erase
the reward signal being audited. Agent-authored discussion can still leak
treatment clues. Audit limits, majority rule, lowest supported reasoning
(`none` OpenAI, `low` Claude/Gemini), and model identities are loaded from
the design; conflicting overrides are rejected.

Get the exact token and price preflight without generation first:

```bash
uv run malt \
  --detect rh \
  --biomnibench-study-dir "$STUDY" \
  --ensemble \
  --output-dir runs/malt-runs/biomni-rh \
  --max-concurrency 6 \
  --preflight-only
```

Inspect the printed `cost-preflight.json`. To reuse that run directory, repeat
the command without `--preflight-only` and add `--resume`; token counts are
rechecked before generation.

```bash
uv run malt \
  --detect rh \
  --biomnibench-study-dir "$STUDY" \
  --ensemble \
  --output-dir runs/malt-runs/biomni-rh \
  --max-concurrency 6
```

The command prints the exact generated `summary.json`. Analyze that file:

```bash
AUDIT=runs/malt-runs/biomni-rh/evaluations/<printed-run>/summary.json

uv run biomnibench-agent cost \
  --design "$DESIGN" \
  --seed-run-dir "$SEEDS" \
  --run-dir "$STUDY" \
  --audit-summary "$AUDIT" \
  --output runs/biomnibench-study/diligent-semi/cost.json

uv run biomnibench-agent analyze \
  --design "$DESIGN" \
  --run-dir "$STUDY" \
  --audit-summary "$AUDIT" \
  --output runs/biomnibench-study/diligent-semi/analysis.json
```

The analysis reports all four RH rates, task-clustered bootstrap intervals,
task-clustered randomization tests, factorial main effects and interaction,
missingness bounds, and explicitly labeled unclustered sensitivity analyses.

## Variables

| Variable | Values | Meaning |
| --- | --- | --- |
| Feedback policy | `full`, `semi`, `score_only` | Fixed for the entire design. `semi` exposes score and criterion-level points, but no judge reasoning or rubric tiers. |
| Prompt axis | `base` versus `anti-rh` or `diligent` | `anti-rh` is the mitigation treatment. `diligent` is a general effort treatment and must not be interpreted as equivalent to anti-RH guidance. |
| Rubric axis | `static` versus `prospective` | Static always uses `r0000`. Prospective uses `r_t` to score `s_t`, then proposes `r_(t+1)` for the next submission; it never rescores `s_t` immediately. |
| Retry policy | solver, judge, proposer, audit | Independently locked. Defaults are one retry each; retries are failure recovery, not extra samples. |
| Audit evidence caps | command output `2048`, other event text `65536` characters | Long values become deterministic head/tail/size/hash records. Final `trace.md`, `answer.txt`, and solver-visible feedback remain available under the general event cap. |
| Replicates | minimum 3 | Independent rollouts, not independent task clusters. The task is the unit of inference. |
| Stage | `development`, `validation`, `confirmatory` | Confirmatory designs require `--validated-design PATH` and automatically exclude every validation task. |

Prospective evolution is a joint intervention: it changes future scoring and
solver-visible feedback. It does not isolate a scoring-only rubric effect.

## Optional outputs and cost warning

```bash
uv run biomnibench-agent blind-export \
  --design "$DESIGN" --run-dir "$STUDY" \
  --output-dir runs/biomnibench-study/diligent-semi/human-packet \
  --key-output runs/biomnibench-study/diligent-semi/private-review-key.json

uv run biomnibench-agent cross-score \
  --design "$DESIGN" --run-dir "$STUDY" \
  --max-concurrency 6
```

The 30-task design above has 360 assignments and 11 submissions per assignment.
Before retries, the online study has 9,180 stage invocations: 90 seed solvers,
90 initial-score judges, 3,600 revision turns, 3,600 revision-score judges, and
1,800 prospective-rubric proposals. The final audit adds 1,080 assignment-model
judgments, for 10,260 sealed stage invocations. This is not an API-request count:
a Codex solver or proposer invocation can make many paid model requests, and
audit chunking and retries add requests. `--max-concurrency` changes wall time,
not the nominal invocation count. Use cheaper locked solver/judge/proposer
models or create a new design with fewer rounds only if you accept changing the
estimand; do not quietly change them after design creation.

The primary RH audit evaluates only the final trajectory. Matching started/tool
events are deduplicated, and later exact duplicate values become lossless
references to their first occurrence. Command output over 2,048 characters and
other event text over 65,536 characters become sealed head/tail/size/hash records before
token preflight. The middle of a truncated command output is unavailable to the
auditor; that is a deliberate cost-versus-evidence tradeoff. Optimizer judges
cache the stable rubric prefix and single-flight only the first concurrent request for a cold
host-local prefix. Audit jobs serialize identical task/model prefixes while
running different prefixes concurrently. OpenAI, Claude, and Gemini are all
priced in preflight; the maximum-output reservation includes every permitted
retry, and actual usage is charged against one cumulative audit budget persisted
across `--resume`. The cost report separates scientific stage invocations from
paid retry attempts. Codex solver estimates remain lower bounds because
cumulative CLI usage omits per-request long-context price tiers. There is no
hard study-wide cap for solver, optimizer judge, and rubric-proposer traffic:
enforce provider project limits as well as checking the report. The locked
three-provider audit uses synchronous standard requests; the existing
single-model OpenAI batch mode cannot batch this mixed panel.

On the 119 completed legacy trajectories, the current compaction reduced the
local conservative input estimate from 20.81M to 10.82M tokens and eliminated
all 14 previously chunked cases. At prices dated 2026-08-05, that panel proxy is
`$139.03` with 1,024 output tokens per judgment, versus `$278.22` before this
compaction. Scaling the observed mix to 360 assignments gives roughly `$421`
expected, `$495` if every first attempt reaches the 4,096-token output ceiling,
and `$989` if every such request also retries once. These are forecasts, not
provider bills. The `$1,500` design value is a hard safety ceiling with headroom,
not a spending target; exact hosted token counts and the all-retry reservation
are written before any paid generation, and the audit aborts if the ceiling is
insufficient.

Do not run `cross-score` casually. The full submission-by-rubric matrix is
23,760 optimizer-judge cells: 1,980 static cells plus 21,780 prospective cells.
Raw online scores are not comparable across evolving rubric versions.
