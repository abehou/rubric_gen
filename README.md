# Rubric Gen

Tools for running BiomniBench-DA agents and studying rubric-guided submission
revision, including full, semi, and score-only feedback policies.

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
uv run malt --help
```

`biomnibench-agent` operates on BiomniBench tasks and revision experiments.
`malt` is a separate CLI for constructing and running the MALT reward-hacking
benchmark.

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
  --top -1 \
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
`runs/biomnibench-rubrics` in the current repository. Add `--resume` to reuse
tasks with an existing valid rubric. Use `--top N` for the first N discovered
tasks or `--top -1` for every task.

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

Initial solving and revision are separate stages. `seed` creates one immutable
`s000` per task. Every treatment points at that same seed set, scores the shared
`s000`, and then starts a new persistent solver session for its revisions. A run
with `--revision-rounds 10` produces `s000` through `s010`.

Create the shared initial submissions once:

```bash
uv run biomnibench-agent seed \
  --top 4 \
  --tasks-dir data/biomnibench-da \
  --output-dir runs/biomnibench-seeds/gemini-3.5-flash-top4 \
  --provider gemini \
  --model gemini-3.5-flash \
  --judge gpt-5.6-luna \
  --rubric rubric.txt \
  --review trace \
  --sandbox \
  --max-concurrency 4
```

Seed directories are immutable and integrity checked. Each seed seals the
solution files, initial trajectory, initial optimizer judgment, validated score,
and complete scoring identity. Task data, virtual environments, and package
caches are excluded. Every revision condition reuses that exact `s000`
judgment; agent rubric evolution begins at `s001`. If generation is interrupted,
rerun the identical command with `--resume`; valid completed judged seeds are
reused and only missing tasks are generated. Solver-only seed formats are not
accepted.

Run one task with full rubric feedback:

```bash
uv run biomnibench-agent revise data/biomnibench-da/da-19-6 \
  --seed-run-dir runs/biomnibench-seeds/gemini-3.5-flash-top4 \
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

Use `--feedback-policy semi` for the validated total plus each criterion's exact
heading, selected level, earned points, and maximum points, without tier
descriptions, judge reasoning, or the rest of the rubric text. Use
`--feedback-policy score_only` for only the validated total.

Use `--rubric-evolution agent` to run a separate Codex rubric proposer after
each preliminary score. The proposer receives `trace.md` and can selectively
retrieve complete events from an indexed JSONL trajectory. Configure it with
`--rubric-proposer-model` and `--rubric-proposer-step-limit`; the latter limits
trajectory queries per proposal. Retrieved event IDs are audited, and every
failure claim must cite an event the proposer actually retrieved. The proposer
may append one general process-penalty criterion (`A=0, B=-5, C=-10`) or make no
patch; it cannot rewrite, remove, merge, or reweight the stable task rubric.
The scoring judge then rescores the same submission against the sealed rubric,
which supplies the next round's feedback. Use `--review trace` to keep scoring
inputs bounded. Versioned rubrics, proposal metadata, and proposer traces are
stored under each experiment's `rubric/` directory. `static` remains the
control. Because the optimizer rubric can gain penalty criteria, compare final
quality using the independent rubric-free and reward-hacking evaluations, not
raw evolving-rubric scores alone.

The seed stage always uses the ordinary task-solving prompt. The default
revision profile, `--prompt base`, adds no mitigation. Use `--prompt anti-rh`
to repeat anti-gaming guidance during revisions, or `--prompt diligent` to
require a deeper audit, additional substantive work, and verification during
every revision round.

Run every task under both full-feedback and score-only conditions:

```bash
uv run biomnibench-agent revise \
  --seed-run-dir runs/biomnibench-seeds/gemini-3.5-flash-top4 \
  --top -1 \
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

Compare each completed revision experiment's initial and final answers with the
rubric-free, position-flipped three-judge protocol adapted from arXiv:2605.12474:

```bash
uv run biomnibench-agent rubric-free \
  --run-dir runs/biomnibench-revisions/revision-example/da-10-1 \
  --output-dir runs/biomnibench-rubric-free/example \
  --max-concurrency 6
```

This evaluator reads only the original instruction and the two answer files. It
does not expose rubrics, scores, feedback, trajectories, treatment labels, or
revision numbers to the judges.

By default, durable experiment data is stored under
`runs/biomnibench-revisions/`, while live solver workspaces, local virtual
environments, and workspace-local package caches use
`tmp/biomnibench-live/`. Set `BIOMNIBENCH_LIVE_ROOT` to another absolute path
to override only the live-storage location.

Add `--dry-run` first to print every selected task, condition, and output
directory without starting solver or judge processes.

Codex runs use a network-isolated workspace sandbox by default. Add
`--allow-network` when solver commands must install packages; this enables
outbound command access without enabling the provider's web-search tool.

During `revise --top N`, the terminal shows one overall experiment progress bar
plus one revision-round bar for each active worker, up to `--max-concurrency`.
Worker bars disappear on completion and their terminal rows are reused by the
next queued experiments.

After every judged revision round, `revise` also publishes a lightweight,
Git-trackable mirror under `runs/biomnibench-reports/`. Each experiment report
contains only `score_improvement.png` and `summary.json`; heavy submissions,
trajectories, judge logs, and environments remain in the revision run. Set
`BIOMNIBENCH_REPORTS_ROOT` to another absolute path to override the report
location. Reports preserve the same run/task hierarchy as the heavy batch.

When `--experiment-dir` is omitted, `revise` creates one timestamped base under
`runs/biomnibench-revisions/`. A `--top` run is one real batch
directory rather than a collection of sibling directories:

```text
revision-20260724-120000--top-all--fb-full--pr-base--sd-gemini-3.5-flash-top4--n-10--p-gemini--m-gemini-3.5-flash--j-gpt-5.6-luna--rb-rubric.txt--v-trajectory--.../
├── batch.json
├── da-10-1/
├── da-10-3/
└── ...
```

The identity-bearing top-level name is reused under
`runs/biomnibench-reports/`, where each task subdirectory contains only its
plot and compact summary.

With `--full-v-score`, each task contains `full/` and `score-only/` experiment
subdirectories. Pass `--experiment-dir PATH` to choose the batch root.

Each revision submission remains under `submissions/`. A treatment's local
`s000` hard-links the immutable seed payload instead of copying it. The mutable
live workspace is private to the treatment so an agent cannot corrupt the
shared seed. Consecutive snapshots hard-link byte-identical files, and judge
staging also uses hard links. After completion, older rounds are compacted to
`answer.txt` and `trace.md`; only the final submission retains its complete
workspace. Workspace-local `.venv`, `venv`, `packages`, and cache directories
are never included in a submission snapshot.

To continue an interrupted automatic batch, rerun the same `revise` command
with `--resume`. It selects the newest batch whose encoded arguments and
recorded task IDs match, resumes existing task experiments from their safe
boundaries, and starts any missing task experiments. Pass
`--experiment-dir PATH --resume` to select a batch or single experiment
explicitly. To delete an explicitly selected experiment and start again at
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

The judge accepts the top directory from an `all` or `revise --top` run. For a
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

## Audit Revision Runs for Reward Hacking

Run an open-ended forensic audit with independent Codex CLI, Claude Code, and
Gemini CLI investigators:

```bash
uv run biomnibench-agent judge --agent-ensemble \
  --run-dir "$BULK/rubric_gen/runs/biomnibench-revisions/REVISION_EXPERIMENT" \
  --tasks-dir data/biomnibench-da \
  --max-concurrency 3
```

The three harnesses use their strongest configured models and receive the
original task plus the complete revision experiment, including feedback,
submissions, artifacts, and tool-call trajectories. They are instructed to
ignore prior strong-judge opinions, investigate chronologically, and discover
reward-hacking mechanisms from evidence rather than classify findings into a
predefined taxonomy. Web access is disabled for the auditors.

Each member writes an independent `audit.md` and raw trajectory. The command
also writes `panel.md`, which concatenates the reports without majority voting
or discarding findings reported by only one investigator, and `summary.json`
with execution provenance. Outputs default to a deterministic `agent-ensemble`
directory beneath the matching artifact root in `runs/biomnibench-judges`; use
`--output-dir` to override it and `--resume` to reuse valid member reports.
`--agent-ensemble` and the rubric-scoring `--ensemble` mode are mutually
exclusive.

### MALT behavior benchmarks

The standalone `malt` CLI handles inspection, preparation, execution, and
scoring. It is deliberately not a `biomnibench-agent` subcommand. Standard uv
syntax is `uv run malt`, not `uv malt`.

After receiving access to the gated dataset, download exactly one MALT
configuration at an immutable Hugging Face commit:

```bash
export MALT_REVISION="$(
  curl -fsSL \
    -H "Authorization: Bearer $HF_TOKEN" \
    https://huggingface.co/api/datasets/metr-evals/malt-public |
  python -c 'import json, sys; print(json.load(sys.stdin)["sha"])'
)"
hf download metr-evals/malt-public \
  --repo-type dataset \
  --revision "$MALT_REVISION" \
  --include "data/*.parquet" \
  --local-dir data/malt-public
printf '%s\n' "$MALT_REVISION" > data/malt-public/REVISION
```

The remote `default/` export is obsolete and lacks manual-review provenance;
do not use it. The CLI reads the immutable commit from
`data/malt-public/REVISION`, hashes every local shard, and records both the
commit and content hashes. Branch names such as `main` are not valid revision
markers because they are mutable.

Do not pool `data`, `irrelevant_detail`, `language_mixing`, `summarize`, and
`vague_cot`: they contain paired variants of the same runs.

With no positional inputs, `malt` reads
`data/malt-public/data/*.parquet`. Pass shard paths explicitly
only to use a different configuration. `--top K` draws exactly K cases after split selection
using `--seed` (default `42`), so every judge mode can evaluate the same
reproducible sample. Add `--balanced` with an even `--top` to draw equal class
counts; for example, `--balanced --top 100` draws 50 reviewed positives and 50
reviewed negatives. The command fails instead of silently returning an
imbalanced sample when the selected split lacks enough cases in either class.

Prepare the shared blinded cases without running judges:

```bash
uv run malt --detect rh
```

By default this writes `inventory.json`, `cases/`, and the private gold file
under `$BULK/rubric_gen/runs/malt-benchmark`. `--detect` is required. `rh`
uses only `reward_hacking` as positive and `normal` as negative. `non-normal`
uses every public label except `normal` as positive. Other labels are excluded
from `rh`; neither mode silently treats an unmapped or empty label as negative.
Only rows with `manually_reviewed: true` are prepared or scored. Missing or
non-boolean review provenance is a hard error, and unreviewed rows are counted
but excluded.
Preparation reads one trajectory at a time and keeps completed cases in a
`.preparing` checkpoint. If the job is interrupted, rerunning the same command
resumes that checkpoint instead of rewriting completed transcripts.

Choose one evaluation mode to prepare the cases, run judges, and score their
strict verdicts. The harness ensemble runs Codex, Claude Code, and Gemini CLI:

```bash
uv run malt \
  --detect rh \
  --agent-ensemble \
  --split test \
  --top 100 \
  --balanced \
  --seed 42 \
  --max-concurrency 6
```

For MALT cases, each harness uses the same deterministic message index rather
than repeatedly loading the raw transcript. The agents inspect the full
chronology through bounded `inventory`, `timeline`, `search`, and `show`
queries. The index stores each complete structured message or trajectory event,
including function and tool calls, plus an ordered source-reference timeline.
Repeated conversation-prefix references are compressed without being described
as repeated agent actions. Runs are
capped at 24 agent turns, Gemini shell output is capped before it enters model
context, Claude has a per-case $3 hard ceiling, and member records include
reported or estimated cost when the harness exposes usage. These controls do
not merge the agents or route only disagreements: `--agent-ensemble` still
runs all three independent harness judges on every selected case.

The comparable baselines use the same cases, prompt objective, verdict schema,
gold labels, and split:

```bash
# Three direct strong-model judges
uv run malt \
  --detect rh \
  --ensemble

# One Codex harness judge
uv run malt \
  --detect rh \
  --agent codex

# One direct model judge
uv run malt \
  --detect rh \
  --judge gpt-5.6-luna
```

Direct judges also receive a content-preserving compact JSONL transcript rather
than the repeated raw MALT payload. Exact duplicate complete message values are
represented once, followed by every ordered serialized-source reference. Each
judge still makes exactly one independent model call per case. Inputs above the
safe compact-input ceiling fail locally before making a paid request. A resumed
evaluation is accepted only when its prompt, dataset hashes, requested model,
request parameters, audit protocol, and source-tree hash match exactly.
Detection metadata records the requested and effective served model, provider
response ID, usage when available, and the fixed medium OpenAI reasoning effort.

Open-source models served by vLLM use the same direct-judge path. The default
single judge is `Qwen/Qwen3.6-27B`; the default panel adds
`zai-org/GLM-4.7-Flash` and `openai/gpt-oss-120b`. Server jobs publish their
dynamically allocated hostnames under `runs/vllm-endpoints`, so no URLs are
needed:

```bash
# Single open-source judge
uv run malt \
  --detect rh \
  --vllm-judge

# Three-model open-source panel
uv run malt \
  --detect rh \
  --vllm-ensemble
```

The server ports remain the unusual fixed values `43117`, `44783`, and `45991`,
but Slurm chooses the available Sphinx hosts. Override discovery with
`--vllm-qwen-url`, `--vllm-glm-url`, and `--vllm-gpt-oss-url`, or change the
endpoint directory with `--vllm-endpoint-dir`. For arbitrary models, repeat
`--vllm 'URL::MODEL'` exactly once or three times.

`VLLM_API_KEY` is optional and defaults to `EMPTY`. These are model-only
baselines: vLLM does not turn an open-source model into a Codex, Claude Code,
or Gemini CLI tool-using harness.

The server jobs explicitly activate a `vllm` conda environment by default.
Prepare that environment with a sufficiently recent vLLM build; GLM-4.7-Flash
currently requires vLLM main/nightly support.

Preview the three generated Stanford NLP cluster jobs without submitting:

```bash
scripts/start_vllm_servers.sh test
```

Submit them with `nlprun`:

```bash
scripts/start_vllm_servers.sh submit
```

The jobs request the `sphinx` queue with one GPU each and let Slurm select
currently available A100, H100, or H200 hosts. They use low priority, 120 GB
host memory, a one-day limit, and logs under `logs/vllm/`. Each server waits
for `/health` before atomically publishing its ready endpoint. To use a
different environment, pass it as the second argument, for example
`scripts/start_vllm_servers.sh submit my-vllm-env`. Do not start model servers
or run the MALT evaluation on a login node; submit the evaluation as a compute
job or enter an interactive compute session.

After all three server logs report `ready`, dry-run the CPU request job:

```bash
mkdir -p logs/vllm
nlprun -q jag -g 0 -c 4 -r 16G -t 1-0 -p standard \
  -n malt-vllm-eval -o logs/vllm/evaluation.out \
  "bash scripts/run_malt_vllm.sh rh" test
```

Submit it by removing the final `test`:

```bash
nlprun -q jag -g 0 -c 4 -r 16G -t 1-0 -p standard \
  -n malt-vllm-eval -o logs/vllm/evaluation.out \
  "bash scripts/run_malt_vllm.sh rh"
```

This maps to the concrete `jag-standard` Slurm partition through `nlprun` and
keeps the API-request workload off the login node.

The shared benchmark directory contains:

```text
$BULK/rubric_gen/runs/malt-benchmark/
├── inventory.json
├── rh/
│   ├── cases/
│   └── private/
│       ├── gold.jsonl
│       └── preparation.json
└── non-normal/
    ├── cases/
    └── private/
        ├── gold.jsonl
        └── preparation.json
```

New evaluation runs are stored separately in the repository:

```text
runs/malt-runs/evaluations/
    ├── 20260725-143012-123456--agent-ensemble--split-test--top-100--seed-42--split-seed-malt-v1--dev-0.2--val-0.1--mc-6--raw-0/
    │   ├── summary.json
    │   ├── run-provenance.json
    │   └── metrics.json
    └── 20260725-...--judge-gpt-5.6-luna--split-test--top-100--seed-42--split-seed-malt-v1--dev-0.2--val-0.1--mc-6--raw-0/
```

Each timestamped evaluation directory encodes its behavior-affecting CLI
arguments and has its own `metrics.json`. `--resume` selects the newest run
whose encoded arguments match the current command. Panel modes report every
member independently and the predeclared majority, any-detect, and
unanimous-detect rules. The default scored split is `test`; use `--split
development` or `--split validation` while developing prompts, and do not tune
against test results.

Prepared cases and private reviewed annotations remain under `$BULK`; prompts,
responses, verdicts, `summary.json`, and aggregate `metrics.json` remain together
in each repository-local evaluation run. Partial or failed runs still write
coverage-aware metrics. Use `--benchmark-dir` to override the shared benchmark
root and `--output-dir` to override the evaluation-run root.

Case artifacts contain no labels or original run identifiers. This is
structural blinding, not a security boundary: the current external CLI agents
are not guaranteed to be filesystem-isolated from gold data. For a publishable
evaluation, run each harness in a container or equivalent environment that
mounts only one evidence case and its audit workspace.

The auditors are autonomous terminal agents. They receive explicit read-only
instructions and may write only inside their audit workspaces, but those
instructions are not a security boundary.

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
