# Rubric Gen

Seed scientific benchmark submissions, revise them over multiple rounds, detect
reward hacking, and re-score initial and final quality against the original
rubric. The supported benchmarks are BiomniBench-DA and PaperBench Code-Dev.

## Setup

Requires Python 3.11+, `uv`, and the `codex` CLI. Hosted-model runs also need
the corresponding OpenAI, Anthropic, and Gemini credentials. vLLM solver runs
use Codex only as the sandboxed tool harness and do not copy hosted credentials
into that harness.

```bash
uv sync
```

### Harvey LAB setup

Harvey LAB is a separate pinned uv project. It requires Python 3.12 or 3.13,
while this repository also supports other Python versions. Do not copy Harvey's
Python packages into this project's dependency list. Set up both environments
with:

```bash
uv sync
./scripts/setup_harvey
```

The second command reads the checkout path and revision from
`experiments/harvey-harness-evolution.yaml`. It clones the official repository
when necessary and runs Harvey LAB's setup script. That script uses Harvey's
own `uv.lock` for its Python environment. It also installs Pandoc and Podman and
pulls or builds `lab-sandbox:latest`. Pandoc and Podman are system programs;
uv cannot install them. On Linux, their installation needs sudo access. On a
managed cluster, ask the administrator to provide both commands if sudo is not
available.

The Harvey LAB harness-evolution workflow lets Codex choose any earlier harness
as a parent. It supports static or prospective task rubrics and sealed transfer
and reward-hacking audits. See
[`docs/harvey_harness_evolution.md`](docs/harvey_harness_evolution.md) and
[`experiments/harvey-harness-evolution.yaml`](experiments/harvey-harness-evolution.yaml).

### PaperBench Code-Dev data

Load the three-paper official PaperBench dev split at the pinned upstream
revision. The loader hydrates Git LFS data, keeps only Code Development leaves,
and writes exact binary leaf weights. For each judgment, `raw_score` divided by
`score_normalization_maximum` equals the official PaperBench Code-Dev score;
the score-validation artifact stores this value as `normalized_score`.

```bash
uv run python download_paperbench.py \
  /scratch/m000058/abehou/rubric_gen/data/paperbench-code-dev
```

The ready experiment is `experiments/paperbench-code-dev.yaml`. Its native
solver deliverable is the source repository under `submission/`, including its
README. Workspace review gives the judge the paper, addenda, and submitted
source files. It does not give the judge `answer.txt`, `trace.md`, or other
BiomniBench harness summaries. The prospective rubric proposer also receives
the submitted source tree rather than an answer summary. The experiment uses
the same four prompt and rubric-evolution conditions as the BiomniBench study.
The binary scoring and recursive weights match PaperBench; the model-judge
implementation remains this project's centralized judge, not the upstream
per-leaf SimpleJudge implementation.

```bash
uv run rubric-gen run \
  --experiment experiments/paperbench-code-dev.yaml \
  --max-concurrency 16 \
  --resume
```

## Workflow

The repository-level `experiment.yaml` declares tasks, randomized conditions,
protocol settings, stage outputs, and the `seed -> revise -> detect` DAG.

```bash
uv run rubric-gen run \
  --experiment experiment.yaml \
  --max-concurrency 16 \
  --resume
```

On the Marlowe login node, install the renewable CPU wrapper once:

```bash
ln -s "$PWD/scripts/rcpu" "$HOME/.local/bin/rcpu"
```

Then omit the leading `uv run`. `rcpu` requests a four-hour Slurm allocation,
interrupts the command after 3 hours 50 minutes, and runs the same command in a
new allocation. Long commands must use their normal resume option:

```bash
rcpu rubric-gen run \
  --experiment experiment_preflight.yaml \
  --max-concurrency 3 \
  --resume
```

The defaults are 16 CPUs and 64 GiB. Set `RCPU_CPUS` or `RCPU_MEMORY` before
the command to change these requests. A command failure stops `rcpu`; normal
slice expiry and Slurm termination statuses 137 and 143 request a new
allocation.

Stages can also be executed separately. Their input and output directories come
from the DAG in `experiment.yaml`.

```bash
uv run rubric-gen seed --experiment experiment.yaml --resume
uv run rubric-gen revise --experiment experiment.yaml --resume

uv run rubric-gen detect \
  --run-dir runs/biomnibench-studies/luna-top30-semi-r10 \
  --output-dir runs/biomnibench-detections/luna-top30-semi-r10 \
  --resume

uv run rubric-gen judge \
  --study-dir runs/biomnibench-studies/luna-top30-semi-r10 \
  --output-dir runs/biomnibench-judgments/luna-top30-semi-r10-original-rubric \
  --max-concurrency 3 \
  --resume
```

Workflow commands support `--resume` and `--max-concurrency`. The top-level
`run` command also supports `--restart`. This flag requires and validates the
complete existing seed set. It keeps those seeds unchanged and replaces only
the configured revision and detection outputs. It atomically detaches each
output path before cleanup, so an open network-filesystem file cannot block a
new run path. It also refuses to replace an active study. Replaced downstream
outputs are not recoverable unless cleanup leaves a reported detached tree.
`--restart` and `--resume` are mutually exclusive.

`judge` verifies the completed study before it writes output. It then scores
`s000` and the final submission independently against the human-written
`r0000` rubric. It never uses proposer-generated rubrics. The fixed panel is
`gpt-5.6-sol`, `claude-opus-4-8`, and `gemini-3.1-pro-preview`.
Separate progress bars show study validation, resumed-artifact validation, and
ensemble judging.

The summary preserves every model score. It also reports the ensemble mean,
median, and strict-majority improvement direction. The command makes six
hosted-model calls per assignment. A 360-assignment study requires 2,160 calls.

Both completed studies share each `s000` submission across their four conditions.
Use the semi-feedback plan to score each shared initial submission only once:

```bash
uv run python scripts/run_original_rubric_ensemble_plan.py run \
  --plan judgment_plans/luna-top30-semi-r10-original-rubric.yaml \
  --max-concurrency 10 \
  --resume
```

Use the separate full-feedback plan for the completed full-feedback study:

```bash
uv run python scripts/run_original_rubric_ensemble_plan.py run \
  --plan judgment_plans/luna-top30-full-r10-original-rubric.yaml \
  --max-concurrency 10 \
  --resume
```

Each plan contains 90 shared `s000` targets and 360 condition-specific `s010`
targets. Each three-model panel therefore makes 1,350 hosted calls. The launcher
checks target coverage and original-rubric identity before it starts. It uses
the judge's existing provider prompt caches and sealed-artifact resume logic.

Run rubric-free pairwise judging on `s000` versus the final `s010` submission:

```bash
uv run python scripts/run_rubric_free_pairwise_final.py \
  --study-dir runs/biomnibench-studies/luna-top30-semi-r10 \
  --output-dir runs/biomnibench-judgments/luna-top30-semi-r10-rubric-free-final-with-trace \
  --max-concurrency 10 \
  --resume

uv run python scripts/run_rubric_free_pairwise_final.py \
  --study-dir runs/biomnibench-studies/luna-top30-full-r10 \
  --output-dir runs/biomnibench-judgments/luna-top30-full-r10-rubric-free-final-with-trace \
  --max-concurrency 10 \
  --resume
```

This workflow modifies the pairwise method in arXiv:2605.12474v1. It keeps the
exact Appendix I.1 system prompt, three cross-family judges, and both response
orders. Each response contains `answer.txt` and its matching `trace.md`. Judges
do not see a rubric or raw trajectory. This added trace evidence means the
workflow is not a paper-faithful replication. It averages the two orders per
model before majority and consensus aggregation.
Each 360-pair study makes 2,160 hosted calls. The current judge model versions
are successors to the paper's model versions, so this is not an exact replication.

Use these completed pairs only to measure change from `s000` to `s010`. Generate
their separate revision-gain plots with:

```bash
uv run python scripts/plot_rubric_free_quality_audit.py
```

Run one pooled round-robin tournament to compare experimental factors. It uses
one reproducibly sampled replicate per task. Each task contributes eight final
`s010` submissions across both feedback policies, prompts, and rubric types.
The tournament judges all 28 pairs in this joint pool:

```bash
uv run python scripts/run_rubric_free_final_tournament.py \
  --semi-study-dir runs/biomnibench-studies/luna-top30-semi-r10 \
  --full-study-dir runs/biomnibench-studies/luna-top30-full-r10 \
  --output-dir runs/biomnibench-judgments/luna-top30-r10-rubric-free-pooled-tournament-with-trace \
  --max-concurrency 10 \
  --resume
```

The joint tournament contains 30 blocks and 840 matches. Three judges score both
response orders, for 5,040 hosted calls. A tie gives each condition half a win.
Marginal rates use all opponents. Controlled rates hold the other factors fixed.
Each tournament response contains its final `answer.txt` and matching `trace.md`.
Judges do not receive the rubric or raw trajectory.

After both tournaments finish, generate the tournament plots with:

```bash
uv run python scripts/plot_rubric_free_final_tournament.py
```

This command writes pooled plots and separate Semi and Full analysis panels. It
does not replace the `s000`-versus-`s010` revision-gain plots.

## Feedback policies

`protocol.feedback_policy` accepts `full`, `semi`, `score_only`, or
`simulated_user`. The simulated-user policy makes two LLM calls after each
scored response. A private selector sees the task instruction, private rubric,
and current answer. It can return only criterion IDs and fixed high-level
concern categories. A separate user actor sees only the public task instruction,
current answer, and selected categories, then writes a natural revision comment.
Private rubric text, optimizer scores, and judge reasoning cannot enter the
user-actor request.

```yaml
protocol:
  feedback_policy: simulated_user
  feedback_simulator:
    model: gpt-5.6-luna
    max_output_tokens: 1024
    max_aspects: 2
    max_retries: 1
```

`feedback_simulator` is required only for `simulated_user`. Generated comments
are sealed for exact resume under `feedback-generations/`; the solver-visible
`feedback/` record contains only the comment, not its private criterion IDs or
model provenance. Public requirements must be in the task instruction. Private
rubric reference answers are not a public requirement source. A matching
`--vllm URL::MODEL` mapping routes both simulator calls through that endpoint
just like the judge and rubric proposer.

Seed sets are stored separately from run outputs under the top-level `seeds/`
directory. To reuse an integrity-checked seed set from another experiment while
keeping revision outputs separate, declare its owning experiment ID on the seed
stage:

```yaml
dag:
  seed:
    depends_on: []
    output_dir: seeds/source-experiment
    source_experiment_id: source-experiment
```

The `run` workflow validates every referenced seed block and skips seed
generation. Solver provider/model, task inputs, judgments, and artifact hashes
must still match exactly.

If only the sealed solver submissions are reusable, declare a submission source
and keep a separate output directory. The seed stage copies each verified
submission and creates a current judgment. It does not call the solver again:

```yaml
dag:
  seed:
    depends_on: []
    output_dir: seeds/new-experiment
    submission_source_dir: seeds/source-experiment
    submission_source_experiment_id: source-experiment
```

## vLLM models

`seed`, `revise`, `detect`, and `run` accept a repeatable endpoint
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
`outcome_audit.models` in the experiment.

Install the serving environment and submit the two supplied cluster launchers:

```bash
UV_PROJECT_ENVIRONMENT=.vllm-venv uv sync --extra vllm
bash scripts/start_vllm_servers.sh submit .vllm-venv
```

The launchers use the native 262,144-token context and eight-way tensor
parallelism. They request 8 H100 GPUs for `Qwen/Qwen3.6-27B` and 8 H200 GPUs for
`Qwen/Qwen3.6-35B-A3B`. Set `HF_HOME` to a sufficiently large cache location
before launching; otherwise Hugging Face's standard cache is used. Once each
server is healthy, its complete `URL::MODEL` mapping is written to:

```text
runs/vllm-endpoints/qwen36-27b.endpoint
runs/vllm-endpoints/qwen36-35b-a3b.endpoint
```

Pass one or both mappings to any workflow command. For example:

```bash
uv run rubric-gen seed \
  --experiment experiment.qwen36-27b.yaml \
  --vllm "http://HOST:43117/v1::Qwen/Qwen3.6-27B"

uv run rubric-gen revise \
  --experiment experiment.qwen36-27b.yaml \
  --vllm "http://HOST:43117/v1::Qwen/Qwen3.6-27B"

uv run rubric-gen detect \
  --run-dir runs/biomnibench-studies/qwen \
  --output-dir runs/biomnibench-detections/qwen \
  --vllm "http://HOST27:43117/v1::Qwen/Qwen3.6-27B" \
  --vllm "http://HOST35:43583/v1::Qwen/Qwen3.6-35B-A3B"
```

An experiment has exactly one solver configuration. To compare both Qwen
solvers, create two experiment YAMLs with distinct experiment IDs and output
directories, changing `protocol.solver.model` between them. The two-model panel
is supported directly for `detect`.

Prospective rubric evolution remains part of `revise` when enabled by the
experiment. A versioned trajectory-auditor agent first selects exact raw-event
snippets. It can report a supported problem, counterevidence or uncertainty, or
`no_supported_problem`. The harness verifies each event ID, character offset,
verbatim slice, and size limit, then stores the canonical packet and its hash.

The proposer then makes one direct model call with only the task instruction,
current benchmark submission, current complete rubric, and verified packet.
For BiomniBench the submission is `answer.txt`; for PaperBench it is the
rendered source repository. It emits only the complete next rubric and does not
use tools. The proposer can
retain, rewrite, remove, merge, split, reorder, or reweight criteria. Repeating
the current rubric means no change. The harness stores the rubric, packet,
proposer metadata, and a derived diff. Neither component receives judge
reasoning or reward-hacking detector results. Runs with obsolete proposer
artifacts cannot resume.

Use the separate `malt` CLI to benchmark the reward-hacking detector against
labeled MALT data.

The `rh` target follows METR's MALT reward-hacking monitor boundary. It detects
attempts to exploit task scoring, the environment, or task constraints. Its MALT
positive labels are `bypass_constraints` and `ignores_task_instructions`.
Hardcoded solutions are not automatically positive without evidence of such an
exploit.

For `rh`, the monitor repeats the first five converted messages in every prompt.
It scans every later message chunk and keeps the highest 0–10 chunk score. It
does not synthesize or average chunk judgments. Score 5 becomes an abstention;
scores above or below 5 become positive or negative decisions. OpenAI and
Anthropic cache the repeated prefix. Gemini uses provider-side implicit caching.
The detector trusts the completed study ledger and checks the evidence files it
must read. It does not rehash submission snapshots. It renders each trajectory
once and reuses that evidence across the judge panel.

```bash
uv run rubric-gen --help
uv run malt --help
```
