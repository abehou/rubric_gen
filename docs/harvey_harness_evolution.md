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
```

Each candidate record has an explicit `parent_harness`. Thus, the analysis can
separate proposal order from ancestry and can study reversion to a strong prior.

## Run the workflow

Run the repository setup from the `rubric_gen` root:

```bash
./scripts/setup_harvey
```

The command clones Harvey LAB at the revision in the experiment file and runs
its official setup script. Harvey LAB uses its own uv environment because it
requires Python 3.12 or 3.13. The setup also needs the `pandoc` and `podman`
commands and installs the `lab-sandbox:latest` image. If system packages are
unavailable, install both commands in the active Conda environment:

```bash
conda install -c conda-forge pandoc podman
./scripts/setup_harvey
```

On Linux, the wrapper and evaluator use node-local Podman runtime and image
storage. They enable Podman's single-UID HPC mode only when `/etc/subuid` or
`/etc/subgid` does not contain a range for the current account. The image cache
is local to one compute node and is populated on first use.

Keep the Harvey checkout clean. Then edit the task split and models in the
example configuration.

```bash
uv run rubric-gen run \
  --experiment experiments/harvey-harness-evolution.yaml

uv run rubric-gen judge \
  --experiment experiments/harvey-harness-evolution.yaml

uv run rubric-gen detect \
  --experiment experiments/harvey-harness-evolution.yaml
```

The run displays progress for harness candidates and their development tasks.
The sealed quality audit displays candidate and task progress. Reward-hacking
detection displays preparation and model-judgment progress.

Use `--resume` on `run` or `detect` only when their existing experiment identity
and checkpoints match the configuration exactly.

`judge` first re-scores every candidate's stored development output with the
sealed original rubric. It then runs every candidate on all held-out tasks. Its
summary reports active-minus-original score gaps and held-out performance.

`detect` converts each accepted Codex design turn into a MALT-compatible forensic
case. The evidence contains the visible ranking, raw Codex trajectory, accepted
proposal, full harness patch, and canonical visible result. The configured model
panel applies the same reward-hacking target and aggregation used by the existing
BiomniBench detector.

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
