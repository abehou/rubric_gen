# Rubric Gen

Run submission-revision experiments with static or evolving rubrics. Supported
benchmarks are BiomniBench-DA, PaperBench Code-Dev, and Harvey LAB.

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

Current submission experiments require schema version 5. Old experiment and
study formats are intentionally rejected. Generate new artifacts with the
current workflow.

Use these experiment files:

| Benchmark | Small run | Larger run |
|---|---|---|
| BiomniBench-DA | `experiment_preflight.yaml` | `experiment.yaml` |
| PaperBench Code-Dev | `experiments/paperbench-code-dev-preflight.yaml` | `experiments/paperbench-code-dev-pilot.yaml` or `experiments/paperbench-code-dev.yaml` |
| Harvey LAB | `experiments/harvey-harness-evolution-preflight.yaml` | `experiments/harvey-harness-evolution.yaml` |

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

The shared pool contains several sealed semantic paraphrase sets. Each set has
one rubric for every available task. A replicate selects one complete set before
revision. All tasks and conditions in that replicate use the same set index.
Static conditions keep the selected variant. Prospective conditions evolve it
after each scored submission. During revision, the other variants remain hidden
from the solver, in-loop judge, auditor, and proposer.

Configure the stage in the experiment YAML:

```yaml
rubric_paraphrases:
  count: 4
  model: gpt-5.6-luna
  max_retries: 2
```

The paraphrase validator preserves criterion order, level labels, weights,
scoring directives, normalization, and PaperBench leaf IDs. This validation
cannot prove semantic equivalence. Review a sample before a large experiment.

## Prospective rubric proposer

The proposer returns the complete next rubric as structured JSON. It does not
return actions, patches, or a `no_patch` decision. It can retain, rewrite,
remove, merge, split, reorder, or reweight criteria.

The proposer does not receive scores, selected levels, score history, judge
reasoning, holdout rubrics, or RH detector results. It receives the task,
current submission, current rubric, and a verified trajectory-audit packet.
The prompt steers it toward task-specific and discriminative outcome criteria.
Process evidence can verify an outcome, but effort and activity earn no credit.

## Quality and reward-hacking audits

Score initial and final submissions against the original rubric:

```bash
uv run rubric-gen judge \
  --experiment experiments/luna-top30-semi-r10.yaml \
  --output-dir runs/biomnibench-judgments/luna-top30-semi-r10-original-rubric \
  --max-concurrency 3 \
  --resume
```

Run the configured reward-hacking (RH) audit:

```bash
uv run rubric-gen detect \
  --experiment experiments/luna-top30-semi-r10.yaml \
  --max-concurrency 3 \
  --resume
```

The command writes four separate signals:

- `direct/`: a strong three-model ensemble gives categorical RH decisions.
- `score-diagnostics/`: the selected paraphrase is compared with hidden
  paraphrases on the initial and final artifacts.
- `rubric-free/`: the weak in-loop score is compared with a rubric-free score
  from the same weak model.
- `summary.json`: the weak in-loop final score is also compared with a strong
  ensemble score on the final optimizer rubric.

For each score gap, a larger positive value is more RH-suspicious. These gaps
are not calibrated RH probabilities or labels. A paraphrase gap can measure
wording sensitivity. A rubric-free gap can measure rubric dependence. A strong
judge gap can measure judge calibration or capability differences. Only the
direct ensemble produces an RH detection rate.

With four paraphrases and three strong models, detection schedules 16 judgment
jobs per assignment. Direct trajectory audits can require more than one model
call when the evidence is chunked.

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
- `scripts/`: analysis and cluster utilities
- `docs/`: design and benchmark documentation

See [docs/architecture.md](docs/architecture.md) for package boundaries and
extension rules.

## CLI help

```bash
uv run rubric-gen --help
uv run rubric-gen run --help
```
