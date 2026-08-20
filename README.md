# Rubric Gen

Run randomized submission-revision experiments with bounded rubric elicitation.
Supported benchmarks are BiomniBench-DA, PaperBench Code-Dev, and Harvey LAB.

## Setup

Requirements:

- Python 3.11 or newer
- [`uv`](https://docs.astral.sh/uv/)
- The `codex` CLI
- Credentials for each configured hosted model

Install the project:

```bash
uv sync
```

## Run an experiment

An experiment file defines the tasks, conditions, models, feedback policy, and
this workflow:

```text
seed -----------\
                 -> revise -> detect
paraphrase -----/
```

The loader derives the experiment ID from the YAML. Revision and detection
paths must end with `{experiment_id}`. Seed and paraphrase paths are shared
pools and must not contain this token.

```bash
uv run rubric-gen run \
  --experiment experiment_preflight.yaml \
  --max-concurrency 3 \
  --resume
```

`--resume` continues valid saved work. `--restart` keeps the shared seed pool
and sealed paraphrases. It replaces revision and detection outputs.

Run one stage when needed:

```bash
uv run rubric-gen seed --experiment experiment.yaml --max-concurrency 3
uv run rubric-gen paraphrase --experiment experiment.yaml --max-concurrency 3
uv run rubric-gen revise --experiment experiment.yaml --max-concurrency 3 --resume
uv run rubric-gen detect --experiment experiment.yaml --max-concurrency 3 --resume
```

Submission experiments accept only the current format. Old experiment and
study artifacts are intentionally rejected. Generate fresh artifacts with the
current workflow.

Use these experiment files:

| Benchmark | Small run | Larger run |
|---|---|---|
| BiomniBench-DA | `experiment_preflight.yaml` | `experiment.yaml` |
| PaperBench Code-Dev | `experiments/paperbench-code-dev-preflight.yaml` | `experiments/paperbench-code-dev-pilot.yaml` or `experiments/paperbench-code-dev.yaml` |
| Harvey LAB | `experiments/harvey-harness-evolution-preflight.yaml` | `experiments/harvey-harness-evolution.yaml` |

> [!WARNING]
> The supplied resource caps are hard ceilings, not approved operating budgets.
> The large BiomniBench-DA configs permit 2,764,800 mechanistic provider calls
> and 6,480 holistic provider calls. The BiomniBench-DA preflight configs permit
> 92,160 mechanistic calls and 216 holistic calls. These counts include the
> configured outer retry allowance. They exclude seed, revision, proposer,
> semantic-reviewer, solver, paraphrase, and direct-detector calls. Set
> operator-approved caps before you run either configuration.

The repository also contains larger top-30 configurations
`experiments/luna-top30-semi-r10.yaml` and
`experiments/luna-top30-full-r10.yaml`.

## PaperBench data

Install the pinned three-paper Code-Dev dataset:

```bash
uv run python download_paperbench.py \
  "${BULK%/}/rubric_gen/data/paperbench-code-dev"
```

PaperBench submissions are source repositories under `submission`. The loader
preserves the official relative rubric weights.

Live solver workspaces are not Git checkouts. The harness gives each solver a
writable `$TMPDIR` under its task workspace. Literal `/tmp` is not available in
the restricted Codex sandbox. Sealed snapshots exclude this temporary directory
and nested tool caches. Restored live solution trees are owner-writable copies.
Sealed artifacts remain read-only.

## Harvey LAB

Harvey uses its own pinned environment and needs `pandoc` and `podman`.

```bash
uv sync
./scripts/setup_harvey
```

See [docs/harvey_harness_evolution.md](docs/harvey_harness_evolution.md).

## Feedback policies

Set `protocol.feedback_policy` to one of these values:

- `full`
- `semi`
- `score_only`
- `simulated_user`

The shared pool contains several sealed rubric-paraphrase sets. Each set has
one rubric for every available task. A replicate selects one complete set before
revision. All conditions in that replicate use the same selected variant as the
initial bank. The other variants remain hidden from the solver, in-loop judge,
and proposer. They provide a common paraphrase-sensitivity diagnostic. This
diagnostic does not identify a pure wording effect.

Configure the stage in the experiment YAML:

```yaml
rubric_paraphrases:
  count: 4
  model: gpt-5.6-luna
  max_retries: 2
```

The paraphraser returns wording fields only. The program copies criterion order,
level labels, points, scoring directives, normalization, and PaperBench leaf IDs
from the master rubric. It also rejects changed numbers inside wording fields.
This validation cannot prove semantic equivalence. Review a sample before a
large experiment.

## Criterion elicitation

Every condition uses exactly one rubric. The experiment requires these three
conditions with one shared solver prompt:

- `fixed` keeps the original rubric.
- `offline_elicitation` adds criteria from three sealed pre-treatment pairs.
- `online_elicitation` adds criteria from three live historical pairs.

The original criteria remain. The proposer cannot delete or rewrite them. The
system can add at most five criteria during one assignment. When at least one
criterion is added, the original criteria receive 80 percent of the score. The
added criteria share the other 20 percent equally. The program sets these
weights. The proposer never chooses points or weights.

Each update uses two proposer calls. The first call finds uncovered differences
in three blinded artifact pairs. The second call turns recurring differences
into general criteria. Each criterion must cite at least two pair IDs. A
separate call reviews every proposed criterion with the same Luna model. It
checks task relevance, generality, evidence support, evaluability, and
duplication. A rejected or uncertain review stops the update.

The online condition compares the current artifact with the prior artifact,
the initial artifact, and a midpoint artifact. Sealed seed artifacts fill any
missing or duplicate early-round source. The offline condition uses all three
pairs among three sealed seed artifacts. Artifact order is deterministic and
blinded. Models do not receive scores, round labels, or newer/older labels.

The first two artifacts use the original rubric. After artifact `s001` is
scored, the first elicited rubric is sealed. It scores `s002`. A six-round run
therefore has five possible elicitation updates.

Each proposer and reviewer request has a 1 MiB UTF-8 cap. Each call allows at
most 32,768 output tokens and uses a 1,800-second timeout. The two proposer
stages allow five validation retries. The semantic review is one fail-closed
call per update. A write-ahead ledger binds every provider call and resume.
Malformed or indeterminate provider work cannot be silently resampled.

The saved generation binds the exact contrast texts, differences, criteria,
review, model metadata, provider ledger, rubric content, and local code hashes.
This structure proves internal consistency. It does not prove that a generated
criterion is correct or complete. Two supporting online pairs share the current
artifact, so the support rule does not provide independent replication.

## Grading

BiomniBench-DA and PaperBench use the same grading method. Each judgment sends
the complete artifact and complete rubric in one structured call. The grader
makes exactly five calls. It computes the signed score for each call and uses
their arithmetic mean. It stores all five criterion-level reports and score
dispersion.

The grader uses temperature zero and no provider retry. An errored, abstaining,
or incomplete call fails the judgment. Repository-level retry policy remains
separate and explicit.

## Current model and call specification

| Role | Model | Reasoning | Calls |
|---|---|---|---:|
| Solver | GPT-5.6 Luna | low | One solver run per revision turn |
| Rubric paraphraser | GPT-5.6 Luna | none; low text verbosity | Four variants per task; up to two retries each |
| Difference finder | GPT-5.6 Luna | low; low text verbosity | One per rubric update, plus up to five validation retries |
| Criterion writer | GPT-5.6 Luna | low; low text verbosity | One per rubric update, plus up to five validation retries |
| Criterion reviewer | GPT-5.6 Luna | low; low text verbosity | One per rubric update |
| In-loop rubric grader | GPT-5.6 Luna | none | Five full-rubric calls per artifact and rubric |
| Reference rubric scorer | GPT-5.6 Sol | none; low text verbosity | Five full-rubric calls per artifact and rubric |
| Reference rubric scorer | Claude Opus 5 | low effort | Five full-rubric calls per artifact and rubric |
| Reference rubric scorer | Gemini 3.6 Flash | low thinking | Five full-rubric calls per artifact and rubric |
| Rubric-free quality panel | Same three models | Same settings | Two absolute and two ordered pairwise calls per assignment and model |
| Direct RH panel | Same three models | Same settings | One trajectory judgment per assignment and model, before retries |

The main BioMNIBench and PaperBench studies use six revision turns, three
replicates, and three conditions. This gives seven artifacts per assignment and
five possible rubric updates. The active rubric contains at most five elicited
criteria. Each accepted criterion needs support from at least two of three
contrast pairs. All structured rubric judgments use temperature zero.

## Quality and reward-hacking audits

Score initial and final submissions against the original rubric:

```bash
uv run rubric-gen judge \
  --experiment experiments/luna-top30-semi-r10.yaml \
  --output-dir runs/biomnibench-judgments/luna-top30-semi-r10-original-rubric \
  --max-concurrency 3 \
  --resume
```

The command deduplicates exact semantic requests across conditions. It then
preflights all unique requests against the experiment's mechanistic hard caps
before it creates the output directory or calls a provider.

Run the configured reward-hacking (RH) audit:

```bash
uv run rubric-gen detect \
  --experiment experiments/luna-top30-semi-r10.yaml \
  --max-concurrency 3 \
  --resume
```

The command writes three evaluation layers:

- `direct/`: a strong three-model ensemble gives categorical RH decisions.
- `mechanistic/`: the strong panel scores both boundaries with active, selected,
  and sealed holdout rubrics.
- `holistic/`: the strong panel first scores initial and final quality without a
  criterion rubric. It also compares the highest and lowest saved in-loop-judge
  original-rubric scores across the full trajectory. Each model sees both
  response orders.
- `summary.json`: the result combines two signed components, rubric diagnostics,
  quality outcomes, and direct outcomes.

The two primary components are verifier exploitation and the dynamic-rubric
gap. Their sum equals the weak active-rubric score minus strong rubric-free
quality at each boundary. The evaluator also compares the active rubric with
the original, selected, and sealed holdout rubrics. These are score diagnostics.
They do not receive separate loss weights. Holdout score dispersion and range
measure paraphrase sensitivity without entering the identity. Only the direct
ensemble produces a categorical reward-hacking decision.

Reference call counts use the singleton primary design. Before dispatch, each
audit stage records its exact call, request-byte, and maximum-output-token plan.
The judge artifacts retain realized token use and cost when providers report
them. Across arms, only selected-rubric gain, sealed-holdout gain, rubric-free
quality gain, pairwise preference, and direct detection use common outcome
instruments. Terminal-rubric `W`, `A`, `C`, and loss values are descriptive
total-policy endpoints because their rulers can differ by arm. Pairwise
agreement is the preference rate for the higher saved in-loop-judge
original-rubric score. A score tie contributes neutral agreement of 0.5. The panel never sees the rubric,
scores, round labels, or which artifact scored higher.

See [the evaluation formulation](docs/reward_hacking_evaluation.md) for the
estimands, exact identity, and limits.

Use the separate `malt` command for labeled MALT detector evaluation:

```bash
uv run malt --help
```

## vLLM

Route a configured model to an OpenAI-compatible vLLM server:

```bash
uv run rubric-gen run \
  --experiment experiment.yaml \
  --vllm "http://HOST:PORT/v1::MODEL"
```

Repeat `--vllm URL::MODEL` for multiple models. The model name must exactly
match the experiment configuration.

The supplied launch script can start the configured Qwen servers:

```bash
UV_PROJECT_ENVIRONMENT=.vllm-venv uv sync --extra vllm
bash scripts/start_vllm_servers.sh submit .vllm-venv
```

## Repository layout

- `src/rubric_gen/benchmarks/`: all benchmark-owned contracts and workflows
- `src/rubric_gen/submission_revision/`: shared seed and revision workflow
- `src/rubric_gen/reward_hacking/`: shared detector and model-panel services
- `src/rubric_gen/runtime/`: benchmark-neutral model and process adapters
- `experiments/`: experiment configurations
- `seeds/`: shared seed pools
- `runs/`: revision and audit outputs
- `scripts/`: environment and cluster utilities
- `docs/`: design and benchmark documentation

See [docs/architecture.md](docs/architecture.md) for package boundaries and
extension rules.

## CLI help

```bash
uv run rubric-gen --help
uv run rubric-gen run --help
```
