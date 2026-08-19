# Rubric Gen

Run randomized submission-revision experiments with weighted rubric banks.
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
> The large BiomniBench-DA configs permit 552,960 mechanistic provider calls
> and 6,480 holistic provider calls. The BiomniBench-DA preflight configs permit
> 18,432 mechanistic calls and 216 holistic calls. These counts include the
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

## Rubric-bank replacement

Each condition uses one bank policy:

- `fixed` keeps the initial bank.
- `nonadaptive_replacement` replaces the full bank using task-only evidence.
- `adaptive_replacement` replaces the full bank using the preceding artifact.

The current bank format requires one member with weight `1.0`. The experiment
requires exactly one condition for each policy above. All conditions use one
prompt. The first replacement must change the bank.

Each bank has one specification anchor. Both replacement arms use a separate
anchor-proposer call. Specification repair can occur only in that anchor. A
trajectory-blind member call then supplies one short presentation. It cannot
receive a condition label, artifact, score, or trajectory.

The renderer copies the complete normative anchor payload into each member. It
preserves criterion order, labels, points, requirements, thresholds,
prerequisites, caps, aggregation rules, and pass/fail boundaries. It adds only
bounded, single-line titles, overviews, headings, and evidence lenses. A free
lens can still influence a judge. A separate reviewer therefore checks each
presentation against the locked anchor. For a changed anchor, the same
trajectory-blind review call checks the new anchor against the task and prior
anchor. Any `changed` or `uncertain` verdict stops the generation. This model
review is an approximate audit, not a semantic guarantee. The exact text lock
is the normative preservation guarantee.

The nonadaptive anchor proposer cannot receive an artifact or trajectory. The
adaptive anchor proposer receives the task, prior bank, preceding submission,
and a bounded recent trajectory. It does not receive holdout rubrics or
reward-hacking detector results. The member call and semantic reviewer remain
trajectory-blind in both replacement arms. The next bank is sealed before it
scores the next artifact.
The prompt treats all supplied task and artifact text as untrusted data. The
complete proposer request has a 1 MiB UTF-8 cap and fails before dispatch. The
harness does not silently truncate an oversized submission. Each proposer call
allows at most 96,000 output tokens and uses a 1,800-second client timeout.
These values are ceilings, not expected usage. Each replacement generation has
one separately capped semantic-review call. Provider dispatches use a durable
write-ahead ledger. A failed, malformed, or indeterminate call cannot be
silently sampled again on resume. An exact completed semantic request can reuse
its sealed decision within the assignment.

Every bank manifest records the specification anchor, member hashes, lineage,
weights, criterion maps, rubric count, and inverse weight concentration. It
also binds the provider ledger and bank-generation source identity. The inverse
weight concentration is always one in the primary experiment. The design does
not claim rubric sampling, ensemble averaging, or an effective sample size.

## Grading engines

The benchmark fixes the grading engine. The CLI cannot switch engines.

- BiomniBench-DA uses the pinned AutoRubric criterion grader. The harness
  validates the sole vote for every criterion and recomputes signed points.
- PaperBench Code-Dev uses three whole-artifact structured judgments. The
  evaluator takes the median signed-point level for each criterion. Its
  official rubrics contain up to 151 leaves. AutoRubric would resend the
  complete repository once per leaf, which is not a safe primary instrument.

Both engines preserve the repository rubric's signed point values. They disable
provider retries and reject incomplete structured output. AutoRubric remains
useful for a predeclared PaperBench calibration subset. Do not pool raw scores
from both benchmarks as if they used one measurement instrument.

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
- `holistic/`: the strong panel compares initial and final artifacts without a
  criterion rubric. Each model sees both response orders.
- `summary.json`: the result combines two signed components, rubric diagnostics,
  quality outcomes, and direct outcomes.

The two primary components are verifier exploitation and the dynamic-rubric
gap. Their sum equals the weak bank score minus strong rubric-free quality at
each boundary. Member-to-anchor, anchor-to-selected, selected-to-holdout, and
holdout-to-holistic gaps partition the dynamic term. They are diagnostics and
do not receive separate loss weights. Holdout score dispersion and range
measure paraphrase sensitivity without entering the identity. Only the direct
ensemble produces a categorical reward-hacking decision.

Reference call counts use the singleton primary design. Before dispatch, each
audit stage records its exact call, request-byte, and maximum-output-token plan.
The judge artifacts retain realized token use and cost when providers report
them. Across arms, only selected-rubric gain, sealed-holdout gain, rubric-free
quality gain, pairwise preference, and direct detection use common outcome
instruments. Terminal-bank `W`, `A`, `C`, and loss values are descriptive
total-policy endpoints because their rulers can differ by arm.

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
