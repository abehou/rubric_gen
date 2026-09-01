# Harvey LAB harness-evolution study

This workflow studies reward hacking while a Codex agent designs executable
Harvey LAB harnesses. It runs a randomized replicated comparison between a
static-rubric control and a prospective-rubric treatment. Every trajectory starts
from the stock `harness/` directory at one exact Harvey LAB commit.

The randomization seed fixes condition order within adjacent replicate blocks.
Each block contains one static and one prospective trajectory. The controller
completes all trajectories before it runs any hidden selection or held-out task.

Each trajectory uses one proposal per round. It keeps every proposal, including a
regression. Codex can choose any earlier candidate as its parent. The controller
does not force the last candidate or automatically copy the best candidate.

## Task roles

The three task sets have separate roles:

- Development tasks are visible during harness design and rubric evolution.
- Selection tasks are hidden during design. They select one candidate after all
  trajectories finish.
- Held-out tasks are also hidden during design. They evaluate only the selected
  candidate and the stock baseline.

Selection and held-out task-agent evaluations use the configured number of
independent repeats. Candidate selection uses replicated mean criterion pass,
then mean all-pass, then the earliest candidate as a fixed tie break. Held-out
results cannot affect candidate selection.

## Round order

Within each randomized trajectory, `r0000` evaluates the stock `h0000` harness
with the original development-task rubrics. Each later round does these operations
in order:

1. In the prospective condition, the rubric proposer revises each task rubric
   from the prior round's canonical result. It can replace existing criterion
   titles and PASS/FAIL rules. It cannot change criterion IDs or deliverable
   scopes. In the static condition, the rubric stays unchanged.
2. The Harvey judge re-scores every stored earlier output with the new active
   rubric. The controller then computes a current ranking and Pareto frontier.
   Scores from different rubric versions are never compared.
3. Codex receives copied, read-only paths for all prior harnesses and canonical
   evaluations, plus the active task rubrics and current-rubric score table. It
   can inspect task-agent trajectories, outputs, metrics, code, and rubrics in
   any order. It chooses a parent and writes one complete candidate harness.
4. The controller runs the new candidate on all development tasks and grades
   those outputs with the active rubric. The proposal remains in the archive
   whether its score increases or decreases.

The Codex workspace never contains selection tasks, held-out tasks, sealed original
rubrics, quality-transfer results, or reward-hacking judgments.

## Artifact layout

The important output paths are:

```text
allocation.json                            fixed randomized unit allocation
study.json                                 unit outcomes and treatment contrasts
trajectories/u####/candidates/h####/       complete harness snapshots
trajectories/u####/rubrics/r####/          active development-task rubrics
trajectories/u####/rounds/r####/           crossed and canonical results
trajectories/u####/audits/quality-transfer/ hidden selection and held-out results
trajectories/u####/audits/reward-hacking/   forensic cases and judgments
run-seal.json                              whole-study artifact digest
```

Each candidate record has an explicit `parent_harness`. Thus, the analysis can
separate proposal order from ancestry and can study reversion to a strong prior.

## Run the workflow

Run the repository setup from the `rubric_gen` root:

```bash
HARVEY_RUNTIME_ROOT="/tmp/rubric-gen-harvey-${UID:?}" ./scripts/setup_harvey
```

The command clones Harvey LAB at the revision in the experiment file and runs
its official setup script. Harvey LAB uses its own uv environment because it
requires Python 3.12 or 3.13. The setup also needs the `pandoc` and `podman`
commands and installs the `lab-sandbox:latest` image. If system packages are
unavailable, install both commands in the active Conda environment:

```bash
conda install -c conda-forge pandoc podman
HARVEY_RUNTIME_ROOT="/tmp/rubric-gen-harvey-${UID:?}" ./scripts/setup_harvey
```

On Linux, Podman's writable runtime and storage stay on the compute node.
Rootless Podman does not support safe writable storage on Network File System
(NFS) storage. The configured `cache_dir` stores a shared `uv` cache and an Open
Container Initiative (OCI) image archive. The setup command populates this
archive. Evaluations restore it on each new node without another image pull.
The cache is separate for each Harvey revision and user ID. The wrapper enables
Podman's single-user-ID mode only when the account has no subordinate ID range.

Keep the Harvey checkout clean. Then edit the task split and models in the
example configuration. Set `HARVEY_RUNTIME_ROOT` to one private node-local path.
Harvey creates the directory if it does not exist.

```bash
env HARVEY_RUNTIME_ROOT="/tmp/rubric-gen-harvey-${UID:?}" uv run rubric-gen run \
  --experiment experiments/harvey-harness-evolution-dev3.yaml \
  --max-concurrency 3
```

The command runs every randomized evolution trajectory first. It then runs hidden
selection, held-out evaluation, and reward-hacking detection. It writes
`run-seal.json` and makes the full output tree read-only. The seal binds every
other artifact path and byte to one digest.

`--max-concurrency` bounds concurrent Harvey task runs and audit judgments. The
development tier has three development tasks and two trajectories per condition.
The results tier has 20 development tasks and three trajectories per condition.
Both tiers repeat hidden outcome runs twice. Trajectories execute sequentially in
the randomized order.

The judge sends the same one-criterion prompt used by the pinned Harvey
evaluator. It marks the shared task-output prefix for Anthropic's five-minute
prompt cache. It completes one criterion per output scope before it starts the
remaining parallel calls. This warm request prevents the first concurrent calls
from racing to create the same cache entry. Scores now store `judge_usage` and
`task_agent_usage` separately. The current validator rejects prior score files
that mislabeled task-agent tokens as judge cost.

Anthropic charges a five-minute cache write at 1.25 times the base input rate.
It charges a cache read at 0.1 times the base input rate. The 20-task rubric has
one output scope and a mean of 53.55 criteria per task. The repeated-prefix
input charge is therefore about 8.23 times smaller before uncached criterion
text and output tokens. The total judge-cost target is at least five times
smaller, but only realized usage can confirm it. See [Anthropic prompt-caching
pricing](https://platform.claude.com/docs/en/about-claude/pricing#prompt-caching).

`--max-retries` sets retries after the first task-agent or judge attempt. Its
default is three. Harvey retries known transient provider errors, OpenAI
`invalid_prompt` rejections, judge grammar timeouts, and truncated judge
responses. Other failures stop immediately. Each retry keeps the failed log.

On the NLP Slurm cluster, run the expanded three-round study first:

```bash
mkdir -p runs/logs
env -u SLURM_CPU_BIND_LIST -u SLURM_CPU_BIND_TYPE \
  -u SLURM_CPU_BIND_VERBOSE SLURM_CPU_BIND=none \
  nlprun -g 0 -c 12 -r 64G -t 14-0 \
  -n rubric-gen-harvey-dev3-prompt-cache-r3 \
  -o /juice2/scr2/abehou/rubric_gen/runs/logs/harvey-dev3-prompt-cache-r3.out \
  -w /juice2/scr2/abehou/rubric_gen \
  'env HARVEY_RUNTIME_ROOT="/tmp/rubric-gen-harvey-${SLURM_JOB_ID:?}" CODEX_HOME=/sailhome/abehou/.codex uv run --frozen rubric-gen run --experiment experiments/harvey-harness-evolution-dev3.yaml --max-concurrency 3'
```

`HARVEY_RUNTIME_ROOT` is the single runtime-storage contract. Harvey cannot
inspect storage topology, so the operator must select a node-local path. The
directory must be absolute, owned by the current user, mode `0700`, and free of
symbolic-link components. Harvey rejects an existing directory that violates
this contract. Evaluator worktrees, task and judge temporary files, and Podman's
writable store use this root. Rootless Podman cannot use NFS.

The explicit `CODEX_HOME` supplies the designer credential source. Each design
attempt creates one mode-`0700` state directory directly under the runtime root.
Harvey removes that directory in a `finally` block after a normal return or a
Python exception. A forced process stop can leave node-local residue. Remove the
job root after such a stop. Harvey does not put designer credentials in the
saved run tree.

The randomized results study is much larger than the old single trajectory. It
runs six evolution trajectories, evaluates every candidate on 20 selection tasks
twice, and evaluates each selected candidate plus its baseline on 20 held-out
tasks twice. Estimate the complete request and storage cost before submission.

The `env` prefix removes CPU-binding masks inherited from the submitting Slurm
allocation. A stale mask can fall outside the CPUs assigned to the new job.

```bash
env -u SLURM_CPU_BIND_LIST -u SLURM_CPU_BIND_TYPE \
  -u SLURM_CPU_BIND_VERBOSE SLURM_CPU_BIND=none \
  nlprun -g 0 -c 12 -r 64G -t 14-0 \
  -n rubric-gen-harvey-results20-prompt-cache-r10 \
  -o /juice2/scr2/abehou/rubric_gen/runs/logs/harvey-results20-prompt-cache-r10-%j.out \
  -w /juice2/scr2/abehou/rubric_gen \
  'exec flock -n /juice2/scr2/abehou/rubric_gen/runs/.harvey-results20-prompt-cache-r10.lock bash -lc "if test -e /juice2/scr2/abehou/rubric_gen/runs/harvey-harness-results20-prompt-cache-r10 || test -L /juice2/scr2/abehou/rubric_gen/runs/harvey-harness-results20-prompt-cache-r10; then echo \"Harvey results output already exists\" >&2; exit 73; fi; exec env HARVEY_RUNTIME_ROOT=\"/tmp/rubric-gen-harvey-\${SLURM_JOB_ID:?}\" CODEX_HOME=/sailhome/abehou/.codex uv run --frozen rubric-gen run --experiment experiments/harvey-harness-evolution-results20.yaml --max-concurrency 4"'
```

The job holds `runs/.harvey-results20-prompt-cache-r10.lock` for its full
lifetime. A duplicate job exits before it can write run artifacts. The `%j` log
suffix keeps Slurm logs separate if two submissions reach the queue.

Use `--resume` on an incomplete `run` only when its existing experiment identity
and checkpoints match the configuration exactly. On a completed run, `--resume`
validates the whole-run seal and exits without provider calls. A sealed run is
immutable, so `judge` and `detect` cannot rerun after the full workflow completes.

Canonical evaluation checkpoints each completed task. It also checkpoints the
agent result before judging. A resumed run skips completed tasks and judges a
saved agent result when one exists. The evaluator makes up to three retries for
each known transient task-agent or judge failure. It starts each task-agent
retry with a clean result directory. It preserves each failed log beside the
final log.

The post-run quality stage first re-scores stored development outputs with the
sealed original rubric. It evaluates every candidate on selection tasks. It then
evaluates only the selected candidate and stock baseline on held-out tasks. The
study summary reports condition means and the prospective-minus-static contrast.

The post-run detection stage converts each accepted Codex design turn into a MALT-compatible forensic
case. The evidence contains the visible ranking, raw Codex trajectory, accepted
proposal, full harness patch, and canonical visible result. The configured model
panel applies the same reward-hacking target and aggregation used by the existing
submission-revision detector.

Use `judge` or `detect` only before the full workflow seals its output.

## Security boundary

A candidate harness contains Python code. Harvey LAB isolates the task agent's
tool calls in Podman, but its host-side `harness/run.py` is still executable code.
The controller gives the task run only the named task-model credentials and gives
the judge process only the named judge credentials. It uses a temporary runtime
and checks that the pinned Harvey checkout stays clean. These checks do not make
malicious host Python safe.

Run this study in a disposable account, container, or compute allocation with no
unrelated credentials or writable data. Restrict outbound network access to the
required model endpoints. Do not run generated candidates on a personal machine
or in a working directory that contains sensitive data.

## Primary comparisons

The main analysis should report these measures by randomized condition and
trajectory replicate:

- current active-rubric development score;
- the same stored output under the original rubric;
- selection-task score under original rubrics;
- selected-minus-baseline held-out score under original rubrics;
- score change relative to the chosen parent, the prior proposal, and `h0000`;
- reward-hacking detector score and qualitative mechanism.

The primary causal contrasts are prospective minus static for held-out quality
change and reward-hacking rate. A visible score increase with a growing
active-minus-original gap or falling held-out score is evidence of rubric-set
overfitting. It is not by itself proof of intentional reward hacking. The
behavior audit supplies separate evidence.
