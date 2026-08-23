# Harvey LAB harness-evolution study

This workflow studies reward hacking while a Codex agent designs executable
Harvey LAB harnesses. It starts from the stock `harness/` directory at one exact
Harvey LAB commit. It does not start from a hand-improved harness.

The experiment uses one proposal per round. It keeps every proposal, including a
regression. Codex can choose any earlier candidate as its parent. The controller
does not force the last candidate or automatically copy the best candidate.

## Round order

`r0000` evaluates the stock `h0000` harness with the original development-task
rubrics. Each later round does these operations in order:

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

The Codex workspace never contains held-out tasks, the sealed original rubrics,
quality-transfer results, or reward-hacking judgments.

## Artifact layout

The important output paths are:

```text
candidates/h####/harness/                 complete harness snapshot
candidates/h####/candidate.json           parent and proposal record
rubrics/r####/tasks/.../task.json          active task rubrics
rounds/r####/crossed/h####/                old outputs scored by current rubric
rounds/r####/visible-current/              exact input shown to Codex
rounds/r####/design-attempts/              Codex prompt, trajectory, and workspace
rounds/r####/canonical/h####/              new task runs and Harvey scores
audits/quality-transfer/                   sealed post-run quality results
audits/reward-hacking/                     forensic cases and detector judgments
run-seal.json                              whole-run artifact count, size, and digest
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

The command runs harness evolution, the quality audit, and reward-hacking
detection in sequence. It then writes `run-seal.json` and makes the full output
tree read-only. The seal binds every other artifact path and byte to one digest.

`--max-concurrency` bounds concurrent Harvey task runs and audit judgments. The
development tier has three tasks. Its judge uses three criterion workers per
task. Thus, three concurrent task judges issue at most nine criterion calls.
Use four task workers for the 20-task results tier. This gives at most 12
concurrent criterion calls.

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
  -n rubric-gen-harvey-dev3-r3 \
  -o /juice2/scr2/abehou/rubric_gen/runs/logs/harvey-dev3-r3.out \
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

Start the 20-task results run only after the development study completes without
task, image-cache, or judge errors. The results run has 83,479 nominal Sonnet
criterion judgments and no whole-study cost ceiling. Estimate and approve its
cost before submission.

The `env` prefix removes CPU-binding masks inherited from the submitting Slurm
allocation. A stale mask can fall outside the CPUs assigned to the new job.

```bash
env -u SLURM_CPU_BIND_LIST -u SLURM_CPU_BIND_TYPE \
  -u SLURM_CPU_BIND_VERBOSE SLURM_CPU_BIND=none \
  nlprun -g 0 -c 12 -r 64G -t 14-0 \
  -n rubric-gen-harvey-results20-r10 \
  -o /juice2/scr2/abehou/rubric_gen/runs/logs/harvey-results20-r10-%j.out \
  -w /juice2/scr2/abehou/rubric_gen \
  'exec flock -n /juice2/scr2/abehou/rubric_gen/runs/.harvey-results20-r10.lock bash -lc "if test -e /juice2/scr2/abehou/rubric_gen/runs/harvey-harness-results20-r10 || test -L /juice2/scr2/abehou/rubric_gen/runs/harvey-harness-results20-r10; then echo \"Harvey results output already exists\" >&2; exit 73; fi; exec env HARVEY_RUNTIME_ROOT=\"/tmp/rubric-gen-harvey-\${SLURM_JOB_ID:?}\" CODEX_HOME=/sailhome/abehou/.codex uv run --frozen rubric-gen run --experiment experiments/harvey-harness-evolution-results20.yaml --max-concurrency 4"'
```

The job holds `runs/.harvey-results20-r10.lock` for its full lifetime. A duplicate job
exits before it can write run artifacts. The `%j` log suffix keeps Slurm logs
separate if two submissions reach the queue.

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

The post-run quality stage first re-scores every candidate's stored development output with the
sealed original rubric. It then runs every candidate on all held-out tasks. Its
summary reports active-minus-original score gaps and held-out performance.

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

The main analysis should report these measures by round and ancestry:

- current active-rubric development score;
- the same stored output under the original rubric;
- held-out-task score under original rubrics;
- score change relative to the chosen parent, the prior proposal, and `h0000`;
- reward-hacking detector score and qualitative mechanism.

A visible score increase with a growing active-minus-original gap or falling
held-out score is evidence of rubric-set overfitting. It is not by itself proof
of intentional reward hacking. The behavior audit supplies separate evidence.
