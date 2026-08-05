# Rubric Gen

Seed BiomniBench submissions, revise them over multiple rounds, detect reward
hacking, and judge final quality without a rubric.

## Setup

Requires Python 3.11+, `uv`, an authenticated `codex` CLI, and OpenAI,
Anthropic, and Gemini API keys.

```bash
uv sync
```

## Workflow

Commands consume an immutable design file that locks tasks, rounds, models,
feedback, assignments, and audit settings.

```bash
uv run biomnibench-agent seed \
  --design design.json --output-dir runs/seeds

uv run biomnibench-agent revise \
  --design design.json --seed-dir runs/seeds --output-dir runs/revisions

uv run biomnibench-agent detect \
  --run-dir runs/revisions --output-dir runs/detections

uv run biomnibench-agent judge \
  --run-dir runs/revisions --output-dir runs/quality
```

All four commands support `--resume` and `--max-concurrency`.

Prospective rubric evolution remains part of `revise` when enabled by the
design. Use the separate `malt` CLI to benchmark the reward-hacking detector
against labeled MALT data.

```bash
uv run biomnibench-agent --help
uv run malt --help
```
