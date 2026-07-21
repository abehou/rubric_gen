# Rubric Gen

Tools for running BiomniBench-DA agents and studying rubric-guided submission
revision, including full-feedback versus score-only ablations.

## Setup

Requirements:

- Python 3.11 or newer and [`uv`](https://docs.astral.sh/uv/)
- The Hugging Face `hf` CLI
- An installed and authenticated `gemini`, `claude`, or `codex` CLI
- `GEMINI_API_KEY` for Gemini judging, perturbation, and rubric generation

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
  --judge-model gemini-3.1-pro \
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
  --judge-model gemini-3.1-pro \
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
`$BULK/rubric_gen/runs/biomnibench-revisions/`. The final directory name also
includes the task and all score-relevant command arguments, so different
conditions do not collide. Pass `--experiment-dir PATH` to override the BULK
default; an explicit path works even when `BULK` is unset.

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
  --model gemini-3.1-pro \
  --repeats 5 \
  --max-concurrency 10 \
  --resume
```

To judge with a sealed task-specific bundle, replace `--rubric rubric.txt` with
`--rubric-set runs/task-process-rubrics/pilot`.

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
