# Rubric Gen

Tools for running BiomniBench-DA agents and studying rubric-guided submission
revision, including full-feedback versus score-only ablations.

## Setup

Requirements:

- Python 3.11 or newer and [`uv`](https://docs.astral.sh/uv/)
- The Hugging Face `hf` CLI
- An installed and authenticated `gemini`, `claude`, or `codex` CLI
- `OPENAI_API_KEY` for the default `gpt-5.6-luna` judge
- `GEMINI_API_KEY` for Gemini judges, perturbation, and rubric generation
- `ANTHROPIC_API_KEY` when selecting a Claude judge

```bash
uv sync
uv run biomnibench-agent --help
```

The selected provider CLI must be on `PATH`:

```bash
command -v gemini
```

Download BiomniBench-DA:

```bash
hf download phylobio/BiomniBench-DA \
  --repo-type dataset \
  --revision e1c8ca5e11a620087bc48d97888eb69176a1f235 \
  --local-dir data/biomnibench-da \
  --exclude "da-1-3/**" \
  --exclude "da-1-4/**" \
  --exclude "da-17-1/**" \
  --exclude "da-17-3/**" \
  --exclude "da-17-5/**" \
  --exclude "da-19-3/**" \
  --exclude "da-19-4/**"
```

This snapshot contains 43 tasks below 1 GB each (about 2.85 GB total). The
excluded task directories are at least 1 GB each. Hugging Face's repository
metadata is the source of the per-task byte totals.

## Generate Task-Specific Rubrics

`generate` launches a terminal agent inside a disposable copy of a task. The
agent reads the instruction, explores the data, executes a tentative analysis,
records its evidence and uncertainty, and then writes an unconstrained
task-specific rubric. The human-authored `tests/rubric.txt`, previous runs,
judge feedback, and reference answers are not copied into the workspace.

Generate one rubric with Gemini CLI:

```bash
uv run biomnibench-agent generate data/biomnibench-da/da-19-6 \
  --harness gemini-cli \
  --model gemini-3.1-pro-preview
```

Generate every downloaded rubric with bounded concurrency:

```bash
uv run biomnibench-agent generate \
  --all \
  --tasks-dir data/biomnibench-da \
  --harness gemini-cli \
  --model gemini-3.1-pro-preview \
  --max-concurrency 4
```

Supported harnesses and their defaults are:

| Harness | Default model | Required CLI |
| --- | --- | --- |
| `gemini-cli` | `gemini-3.1-pro-preview` | `gemini` |
| `claude-code` | `claude-opus-4-8` | `claude` |
| `codex-cli` | `gpt-5.6-sol` | `codex` |

`--model` accepts any model ID supported by the selected harness. Omit
`--output-dir` to create a timestamped generation directory under
`runs/biomnibench-rubrics` in the current repository. Add `--resume` to reuse tasks with
an existing valid rubric or `--limit N` to select a smaller `--all` batch.

Each task retains only lightweight generation evidence after completion:

```text
generation-.../
├── summary.json
├── tasks/<task-id>/
│   ├── prompt.txt
│   ├── status.json
│   └── trajectory.stream.jsonl
└── workspaces/<task-id>/
    ├── instruction.md
    ├── generated_rubric.md
    └── solution_notes.md
```

Task data is copied so the autonomous harness cannot mutate the canonical
dataset, then deleted immediately after the harness exits. Rubric scoring is
not constrained to A/B/C levels or a 100-point total; validation checks only
that the required rubric and evidence notes are substantive artifacts.
During generation, the terminal shows one overall task bar plus one live bar
per concurrency slot. Completed worker rows are reused by queued tasks.

## Run Submission-Revision Experiments

`revise` keeps one solver session alive. The solver creates `s000`, receives
judge feedback, revises the same submission, and repeats. A run with
`--revision-rounds 10` produces `s000` through `s010`.

Run one task with full rubric feedback:

```bash
uv run biomnibench-agent revise data/biomnibench-da/da-19-6 \
  --revision-rounds 10 \
  --provider gemini \
  --model gemini-3.5-flash \
  --judge gpt-5.6-luna \
  --rubric rubric.txt \
  --feedback-policy full \
  --review trajectory \
  --sandbox \
  --skip-trust
```

Use `--feedback-policy score_only` for a single score-only ablation.

Run every task under both full-feedback and score-only conditions. `BULK` must
name an absolute large-storage path:

```bash
uv run biomnibench-agent revise \
  --all \
  --full-v-score \
  --tasks-dir data/biomnibench-da \
  --revision-rounds 10 \
  --provider gemini \
  --model gemini-3.5-flash \
  --judge gpt-5.6-luna \
  --rubric rubric.txt \
  --review trajectory \
  --sandbox \
  --skip-trust \
  --max-concurrency 90
```

By default, durable experiment data is stored under
`$BULK/rubric_gen/runs/biomnibench-revisions/`, while live solver workspaces,
local virtual environments, and workspace-local package caches use
`$BULK/rubric_gen/biomnibench-live/`. Set `BIOMNIBENCH_LIVE_ROOT` to another
absolute path to override only the live-storage location.

Add `--dry-run` first to print every selected task, condition, and output
directory without starting solver or judge processes.

During `revise --all`, the terminal shows one overall experiment progress bar
plus one revision-round bar for each active worker, up to `--max-concurrency`.
Worker bars disappear on completion and their terminal rows are reused by the
next queued experiments.

After every judged revision round, `revise` also publishes a lightweight,
Git-trackable mirror under `runs/biomnibench-reports/`. Each experiment report
contains only `score_improvement.png` and `summary.json`; heavy submissions,
trajectories, judge logs, and environments remain exclusively in BULK. Set
`BIOMNIBENCH_REPORTS_ROOT` to another absolute path to override the report
location.

When `--experiment-dir` is omitted, `revise` requires `BULK` to be set to an
absolute path and creates one timestamped base under
`$BULK/rubric_gen/runs/biomnibench-revisions/`. A `--all` run is one real batch
directory rather than a collection of sibling directories:

```text
revision-.../
├── batch.json
├── da-10-1/
├── da-10-3/
└── ...
```

With `--full-v-score`, each task contains `full/` and `score-only/` experiment
subdirectories. Pass `--experiment-dir PATH` to choose the batch root; an
explicit path works even when `BULK` is unset.

Each revision submission remains as an immutable snapshot under `submissions/`.
Judge staging uses hard links to that snapshot instead of copying its workspace
and cumulative trajectory, so the judge layout does not consume a second set of
file data blocks. Judge results and validation artifacts remain durable for
resume and audit.

To continue an interrupted experiment, pass its exact final directory with
`--experiment-dir PATH --resume`. To delete that experiment and start again at
`s000`, use `--experiment-dir PATH --restart` instead.

## Compile Task-Specific Process Rubrics

Compile sealed rubrics from immutable task inputs:

```bash
uv run biomnibench-agent task-process-rubrics \
  --tasks-dir data/biomnibench-da \
  --task da-19-6 \
  --task da-26-4 \
  --output-dir runs/task-process-rubrics/pilot \
  --model gemini-3.5-flash \
  --max-concurrency 2
```

Use the resulting bundle in a revision experiment by replacing
`--rubric rubric.txt` with:

```bash
--rubric-set runs/task-process-rubrics/pilot
```

`--rubric` and `--rubric-set` are mutually exclusive.

## Generate Base Agent Runs

Run one task:

```bash
uv run biomnibench-agent one data/biomnibench-da/da-26-4 \
  --runs-dir runs/biomnibench-agents \
  --provider gemini \
  --model gemini-3.5-flash \
  --skip-trust
```

Run all tasks concurrently:

```bash
uv run biomnibench-agent all \
  --tasks-dir data/biomnibench-da \
  --runs-dir runs/biomnibench-agents \
  --provider gemini \
  --model gemini-3.5-flash \
  --skip-trust \
  --continue-on-error \
  --max-concurrency 10
```

Resume a batch by adding `--resume-run PATH_TO_BATCH_RUN`.

## Judge Saved Runs

Judge a task run or batch run:

```bash
uv run biomnibench-agent judge \
  --run-dir runs/biomnibench-agents/PATH_TO_BATCH_RUN \
  --tasks-dir data/biomnibench-da \
  --review trajectory \
  --rubric rubric.txt \
  --model gpt-5.6-luna \
  --repeats 5 \
  --max-concurrency 10 \
  --resume
```

To judge with a sealed task-specific bundle, replace `--rubric rubric.txt` with
`--rubric-set runs/task-process-rubrics/pilot`.

Judge provider routing is centralized: `gpt-*`, `chatgpt-*`, and o-series
models use the OpenAI Responses API; `gemini*` models use Google GenAI; and
`claude*` models use Anthropic. Task-local judge scripts are used only when an
explicit `--judge-name` override is supplied.

Judge inputs may live in `$BULK`, but judge outputs default to a deterministic
directory under `runs/biomnibench-judges` in the current repository. This
includes score summaries, validated member evaluations, and ensemble
exploitation artifacts. Use `--output-dir PATH` to override the artifact root;
`--output FILE` overrides only the summary JSON path.

The judge accepts the top directory from an `all` or `revise --all` run. For a
revision batch, ordinary judging selects the final submission from every task.
The strong reference panel evaluates every weak-judged submission and calculates
per-task exploitation statistics:

```bash
uv run biomnibench-agent judge \
  --ensemble \
  --run-dir "$BULK/rubric_gen/runs/biomnibench-revisions/REVISION_BATCH" \
  --tasks-dir data/biomnibench-da \
  --max-concurrency 3
```

The fixed cross-provider panel is `gpt-5.6-sol`, `claude-opus-4-8`, and
`gemini-3.1-pro-preview`. Successful member evaluations are reused by default;
pass `--force` to pay for and replace them. The command writes
`strong-verifier/exploitation.json` beneath the repo-local judge artifact root.
It reports the
paper-faithful binary exploitation rate (new transitions to the best rubric
level that all three panel members reject), an ordinal extension that also
captures partial level improvements, conservative reference scores, proxy to
reference gaps, member scores, and panel agreement. A rate is `null` when a
transition contains no newly credited criteria; it is not falsely reported as
zero.
`judge --ensemble` displays one overall model-call bar plus one live bar per
concurrency slot.

## Generate Controlled Perturbations

Create all perturbation levels (`C,L0,L1,L2,L3,L4,L5`) for every task found in
a base run:

```bash
uv run biomnibench-agent perturb \
  --base-run runs/biomnibench-agents/PATH_TO_BATCH_RUN \
  --out-dir runs/biomnibench-perturbations/pilot \
  --perturber-model gemini-3.5-flash \
  --max-concurrency 30
```

Add `--tasks da-19-6,da-26-4` to select tasks, `--levels C,L1,L3,L5` to select
levels, or `--resume` to keep completed outputs.

## Generate Retrospective Rubrics

`process-rubrics` reads saved trajectories and writes task-local
`tests/process_rubric.txt` files. These are exploratory and are not sealed
canonical rewards.

```bash
uv run biomnibench-agent process-rubrics \
  --tasks-dir data/biomnibench-da \
  --run-dir runs/biomnibench-agents/PATH_TO_BATCH_RUN \
  --model gemini-3.5-flash \
  --max-concurrency 4 \
  --resume
```

## Compare Judge Scores

After generating compatible trace and trajectory score files:

```bash
uv run biomnibench-agent compare-judges \
  --run-dir runs/biomnibench-agents/PATH_TO_BATCH_RUN \
  --label-top-n 8
```

## Package Layout

- `agent/`: provider adapters, sessions, workspaces, and base runs
- `judging/`: target discovery, execution, validation, and artifacts
- `revision/`: same-session revision controller and durable state
- `rubrics/`: task-specific and retrospective rubric generation
- `perturbation/`: controlled run perturbations
- `visualization/`: revision and judge-comparison plots
- `integrations/`: external clients
- `utils/`: shared paths, progress, hashing, and text helpers
