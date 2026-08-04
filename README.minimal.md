# BiomniBench Revision Experiments

Run one shared seed set, revise every seed under controlled conditions, and
optionally score every saved submission with the strong judge ensemble.

## Setup

Requirements: Python 3.11+, [`uv`](https://docs.astral.sh/uv/), and an
authenticated `codex`, `claude`, or `gemini` agent CLI.

```bash
uv sync

# The ordinary judge needs OpenAI. The strong ensemble needs all three.
export OPENAI_API_KEY=...
export ANTHROPIC_API_KEY=...
export GEMINI_API_KEY=...
```

Put the BiomniBench-DA `da-*` task directories under
`data/biomnibench-da`, then verify the CLI:

```bash
uv run biomnibench-agent --help
```

All commands below assume:

```bash
TASKS=data/biomnibench-da
SEEDS=runs/biomnibench-seeds/codex-luna-top30
```

## 1. Create the shared seeds

Each task gets one immutable, judged `s000`. Every later condition must reuse
this same seed directory.

```bash
uv run biomnibench-agent seed \
  --top 30 \
  --tasks-dir "$TASKS" \
  --output-dir "$SEEDS" \
  --provider codex \
  --model gpt-5.6-luna \
  --judge gpt-5.6-luna \
  --rubric rubric.txt \
  --review trace \
  --sandbox \
  --allow-network \
  --skip-trust \
  --retries 5 \
  --max-concurrency 16
```

If interrupted, rerun the same command with `--resume`.

## 2. Run revisions

This example runs 10 revision rounds with semi feedback:

```bash
OUT=runs/biomnibench-revisions/example

uv run biomnibench-agent revise \
  --top 30 \
  --tasks-dir "$TASKS" \
  --seed-run-dir "$SEEDS" \
  --experiment-dir "$OUT" \
  --revision-rounds 10 \
  --feedback-policy semi \
  --prompt base \
  --rubric-evolution static \
  --provider codex \
  --model gpt-5.6-luna \
  --judge gpt-5.6-luna \
  --rubric rubric.txt \
  --review trace \
  --sandbox \
  --allow-network \
  --skip-trust \
  --retries 5 \
  --max-concurrency 16
```

Append `--resume` to the identical command to continue an interrupted batch.

## Experiment variables

| Axis | Values | Meaning |
| --- | --- | --- |
| `--feedback-policy` | `full` | Score, complete rubric, selected levels, and judge reasoning. |
| | `semi` | Score plus criterion headings, selected levels, and points; no rubric tiers or reasoning. |
| | `score_only` | Total score only. |
| `--prompt` | `base` | No extra revision-effort or anti-gaming instruction. |
| | `anti-rh` | Repeats anti-reward-hacking guidance. |
| | `diligent` | Requires substantive work, deeper auditing, and verification. |
| `--rubric-evolution` | `static` | Reuse the original task rubric for every round. |
| | `agent` | After each preliminary score, a separate agent may append one process-penalty criterion. It cannot rewrite the original rubric. |

These axes are independent. `diligent` is a solver prompt; `agent` is a rubric
policy. Do not treat them as the same intervention.

## 2 x 2 prompt/rubric matrix

The function below fixes feedback to `semi` and varies only prompt and rubric
policy:

```bash
run_condition() {
  local prompt="$1"
  local rubric_policy="$2"
  local output="$3"

  uv run biomnibench-agent revise \
    --top 30 \
    --tasks-dir "$TASKS" \
    --seed-run-dir "$SEEDS" \
    --experiment-dir "$output" \
    --revision-rounds 10 \
    --feedback-policy semi \
    --prompt "$prompt" \
    --rubric-evolution "$rubric_policy" \
    --rubric-proposer-model gpt-5.6-luna \
    --rubric-proposer-step-limit 12 \
    --provider codex \
    --model gpt-5.6-luna \
    --judge gpt-5.6-luna \
    --rubric rubric.txt \
    --review trace \
    --sandbox \
    --allow-network \
    --skip-trust \
    --retries 5 \
    --max-concurrency 16
}

run_condition base     static runs/biomnibench-revisions/base-static
run_condition base     agent  runs/biomnibench-revisions/base-agent
run_condition diligent static runs/biomnibench-revisions/diligent-static
run_condition diligent agent  runs/biomnibench-revisions/diligent-agent
```

Run the four calls in separate shells if you want the four matrix cells to run
concurrently. The function above runs them sequentially.

## 3. Strong ensemble judging

The ensemble judges every saved submission with GPT-5.6 Sol, Claude Opus 4.8,
and Gemini 3.1 Pro, then writes exploitation statistics. This is expensive: a
30-task experiment with `s000` through `s010` makes 990 successful model calls.

```bash
uv run biomnibench-agent judge \
  --ensemble \
  --run-dir \
    runs/biomnibench-revisions/base-static \
    runs/biomnibench-revisions/base-agent \
    runs/biomnibench-revisions/diligent-static \
    runs/biomnibench-revisions/diligent-agent \
  --tasks-dir "$TASKS" \
  --resume \
  --max-concurrency 16 \
  --max-retries 1
```

Use `--force` only when you intentionally want to pay to rerun completed judge
calls.
