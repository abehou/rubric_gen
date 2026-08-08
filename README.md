# Rubric Gen

Seed BiomniBench submissions, revise them over multiple rounds, detect reward
hacking, and judge final quality without a rubric.

## Setup

Requires Python 3.11+, `uv`, and the `codex` CLI. Hosted-model runs also need
the corresponding OpenAI, Anthropic, and Gemini credentials. vLLM solver runs
use Codex only as the sandboxed tool harness and do not copy hosted credentials
into that harness.

```bash
uv sync
```

## Workflow

The repository-level `experiment.yaml` declares tasks, randomized conditions,
protocol settings, stage outputs, and the `seed -> revise -> detect` DAG.

```bash
uv run biomnibench-agent run \
  --experiment experiment.yaml \
  --max-concurrency 16 \
  --resume
```

Stages can also be executed separately. Their input and output directories come
from the DAG in `experiment.yaml`.

```bash
uv run biomnibench-agent seed --experiment experiment.yaml --resume
uv run biomnibench-agent revise --experiment experiment.yaml --resume

uv run biomnibench-agent detect \
  --run-dir runs/biomnibench-studies/luna-top30-semi-r10 \
  --output-dir runs/biomnibench-detections/luna-top30-semi-r10 \
  --resume

uv run biomnibench-agent judge \
  --run-dir runs/revisions --output-dir runs/quality
```

Workflow commands support `--resume` and `--max-concurrency`.

## vLLM models

`seed`, `revise`, `detect`, `judge`, and `run` accept a repeatable endpoint
mapping:

```text
--vllm URL::MODEL
```

The model string must exactly match the model configured in `experiment.yaml`.
For example, a Qwen solver, optimizer judge, and prospective-rubric proposer can
all use the same endpoint:

```yaml
protocol:
  solver:
    provider: vllm
    model: Qwen/Qwen3.6-27B
    reasoning_effort: null
    service_tier: null
    executable: null
    retries: 1
    timeout_seconds: 7200
  judge_model: Qwen/Qwen3.6-27B
  rubric_proposer_model: Qwen/Qwen3.6-27B
```

For `detect`, the endpoint models and their order must exactly match
`outcome_audit.models` in the experiment. `judge` takes its entire model panel
from the repeated endpoints and cannot mix `--vllm` with hosted `--models`.

Install the serving environment and submit the two supplied cluster launchers:

```bash
UV_PROJECT_ENVIRONMENT=.vllm-venv uv sync --extra vllm
bash scripts/start_vllm_servers.sh submit .vllm-venv
```

The launchers use the native 262,144-token context and eight-way tensor
parallelism. They request 8 H100 GPUs for `Qwen/Qwen3.6-27B` and 8 H200 GPUs for
`Qwen/Qwen3.6-35B-A3B`. Model weights are cached under
`/juice2/u/nlp/data/abe_models/huggingface`; the login-node default cache is too
small for these repositories. Once each server is healthy, its complete
`URL::MODEL` mapping is written to:

```text
runs/vllm-endpoints/qwen36-27b.endpoint
runs/vllm-endpoints/qwen36-35b-a3b.endpoint
```

Pass one or both mappings to any workflow command. For example:

```bash
uv run biomnibench-agent seed \
  --experiment experiment.qwen36-27b.yaml \
  --vllm "http://HOST:43117/v1::Qwen/Qwen3.6-27B"

uv run biomnibench-agent revise \
  --experiment experiment.qwen36-27b.yaml \
  --vllm "http://HOST:43117/v1::Qwen/Qwen3.6-27B"

uv run biomnibench-agent detect \
  --run-dir runs/biomnibench-studies/qwen \
  --output-dir runs/biomnibench-detections/qwen \
  --vllm "http://HOST27:43117/v1::Qwen/Qwen3.6-27B" \
  --vllm "http://HOST35:43583/v1::Qwen/Qwen3.6-35B-A3B"

uv run biomnibench-agent judge \
  --run-dir runs/revisions/example \
  --output-dir runs/quality/qwen \
  --vllm "http://HOST27:43117/v1::Qwen/Qwen3.6-27B" \
  --vllm "http://HOST35:43583/v1::Qwen/Qwen3.6-35B-A3B"
```

An experiment has exactly one solver configuration. To compare both Qwen
solvers, create two experiment YAMLs with distinct experiment IDs and output
directories, changing `protocol.solver.model` between them. The two-model panel
is supported directly for `detect` and `judge`.

Prospective rubric evolution remains part of `revise` when enabled by the
experiment. Use the separate `malt` CLI to benchmark the reward-hacking detector
against labeled MALT data.

```bash
uv run biomnibench-agent --help
uv run malt --help
```
