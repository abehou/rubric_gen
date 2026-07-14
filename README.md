
# Rubric Gen

Utilities for running BiomniBench-DA terminal-agent experiments, perturbing saved
agent trajectories, and judging traces with either outcome or process rubrics.

## Setup

Install dependencies:

```bash
uv sync
```

Download the BiomniBench-DA task data:

```bash
hf download phylobio/BiomniBench-DA \
  --repo-type dataset \
  --local-dir ./data/biomnibench-da \
  --exclude "da-1-3/**" \
  --exclude "da-1-4/**" \
  --exclude "da-17-1/**" \
  --exclude "da-17-3/**" \
  --exclude "da-17-5/**"
```

## Run Agents

Run one task:

```bash
uv run biomnibench-agent one data/biomnibench-da/da-26-4 \
  --provider gemini \
  --model gemini-3.5-flash \
  --skip-trust
```

Run all pending tasks into a batch directory:

```bash
uv run biomnibench-agent all \
  --tasks-dir data/biomnibench-da \
  --runs-dir runs/biomnibench-agents \
  --provider gemini \
  --model gemini-3.5-flash \
  --skip-trust \
  --continue-on-error \
  --max-concurrency 1
```

Resume an existing all-task run:

```bash
uv run biomnibench-agent all \
  --resume-run runs/biomnibench-agents/all-gemini-20260705-185054 \
  --provider gemini \
  --continue-on-error
```

## Perturb Runs

`perturb` creates judge-compatible run directories for controlled quality
variants. The perturber is rubric-blind: it sees the task instruction and saved
artifacts, not `rubric.txt` or `process_rubric.txt`.

The perturbation command calls the Gemini API directly; it does not launch a
Gemini CLI agent. Set `GEMINI_API_KEY` before running, or pass a different key
variable with `--api-key-env`.

Existing perturbation output directories are overwritten by default. Add
`--resume` to keep the directory and skip any task-level outputs that are already
complete.

Perturbation runs show a tqdm progress bar and run up to 30 task-level jobs
concurrently by default. Use `--max-concurrency` to tune this.

Levels:

- `C`: exact control copy
- `L0`: verbose irrelevant-detail variant that looks more detailed without adding real evidence
- `L1`: cosmetic/noise-only edits
- `L2`: less auditable process
- `L3`: weaker method evidence
- `L4`: polished answer with weak or inconsistent process support
- `L5`: degraded process and degraded final answer

Perturb one task from a batch run:

```bash
uv run biomnibench-agent perturb \
  --base-run runs/biomnibench-agents/all-gemini-20260705-185054 \
  --tasks da-26-4 \
  --out-dir runs/biomnibench-perturbations/da-26-4-pilot
```

Perturb every task discovered in the run folder by omitting `--tasks`:

```bash
uv run biomnibench-agent perturb \
  --base-run runs/biomnibench-agents/all-gemini-20260705-185054 \
  --out-dir runs/biomnibench-perturbations/all-tasks-pilot
```

Useful options:

```bash
--levels C,L0,L1,L2,L3,L4,L5
--perturber-model gemini-3.5-flash
--api-key-env GEMINI_API_KEY
--max-concurrency 30
--resume
--dry-run
```

The output layout is:

```text
runs/biomnibench-perturbations/<experiment>/
  perturbation_manifest.json
  C/
    tasks/<task>/trajectory.stream.jsonl
    tasks/<task>/status.json
    workspaces/<task>/trace.md
    workspaces/<task>/answer.txt
  L0/
  L1/
  ...
```

## Judge Runs

Judge normal or perturbed runs with the original outcome rubric:

```bash
uv run biomnibench-agent judge \
  --run-dir runs/biomnibench-perturbations/da-26-4-pilot/L3 \
  --review trace \
  --rubric rubric.txt \
  --model gemini-3.1-pro
```


Judge the same run with the process rubric:

```bash
uv run biomnibench-agent judge \
  --run-dir runs/biomnibench-perturbations/da-26-4-pilot/L3 \
  --review trace \
  --rubric process_rubric.txt \
  --model gemini-3.1-pro
```

Multiple run dir:
```bash
uv run biomnibench-agent judge \
  --run-dir runs/biomnibench-agents/all-gemini-20260705-185054/tasks/da-26-4 runs/biomnibench-agents/all-gemini-20260705-185054/tasks/da-19-6 runs/biomnibench-agents/all-gemini-20260705-185054/tasks/da-10-1 \
  --review trajectory \
  --rubric process_rubric.txt \
  --model gemini-3.5-flash \
  --repeats 5 \
  --max-concurrency 10
```


Judge raw trajectories instead of `trace.md`:

```bash
uv run biomnibench-agent judge \
  --run-dir runs/biomnibench-perturbations/da-26-4-pilot/L3 \
  --review trajectory \
  --rubric process_rubric.txt \
  --model gemini-3.1-pro
```

Run repeated judges to estimate judge variance:

```bash
uv run biomnibench-agent judge \
  --run-dir runs/biomnibench-perturbations/da-26-4-pilot/L0 \
  --review trace \
  --rubric process_rubric.txt \
  --repeats 5 \
  --max-concurrency 5
```

Judge all tasks under the run directory

```bash
uv run biomnibench-agent judge \
  --run-dir runs/biomnibench-agents/all-gemini-20260705-185054 \
  --review trajectory \
  --rubric process_rubric.txt \
  --model gemini-3.1-pro
```

## Revise a Submission in One Agent Session

`revise` runs a linear self-revision experiment. One solver session produces an
initial rubric-blind submission, receives judge feedback, revises the same live
workspace, and repeats. There is no candidate selection or rollback: a lower
score still becomes the next revision. If `--revision-rounds` is 3, the command
produces and judges four submissions (`s000` through `s003`).

Run full process-rubric feedback with Gemini CLI:

```bash
uv run biomnibench-agent revise data/biomnibench-da/da-19-6 \
  --experiment-dir runs/biomnibench-revisions/da-19-6-process-full \
  --revision-rounds 3 \
  --provider gemini \
  --model gemini-3.5-flash \
  --judge-model gemini-3.1-pro \
  --rubric process_rubric.txt \
  --feedback-policy full \
  --review trajectory \
  --sandbox \
  --skip-trust
```

Use a sealed task-specific process-rubric bundle instead of a task-local file:

```bash
uv run biomnibench-agent revise data/biomnibench-da/da-19-6 \
  --experiment-dir runs/biomnibench-revisions/da-19-6-task-process-full \
  --revision-rounds 3 \
  --provider gemini \
  --model gemini-3.5-flash \
  --judge-model gemini-3.1-pro \
  --rubric-set runs/task-process-rubrics/pilot \
  --feedback-policy full \
  --review trajectory \
  --sandbox \
  --skip-trust
```

For the score-only ablation, change only:

```bash
--feedback-policy score_only
```

Omit `--rubric` and `--rubric-set` to optimize the task's default outcome
rubric (`tests/rubric.txt`). The solver never sees the rubric before `s000`.
Under `full`, later turns receive the frozen rubric, validated criterion scores,
selected levels, and bounded judge reasons. Under `score_only`, they receive only
the total score.

Gemini and Claude sessions use an experiment UUID; Codex resumes the thread ID
reported by its initial JSON stream. Every turn uses the same provider session
and live workspace. The experiment directory preserves per-turn prompts and
trajectories, immutable submission snapshots, cumulative trajectories, judge
artifacts, projected feedback, and the complete score sequence.

Optimizer artifacts are stored under
`evaluations/sNNN/<rubric-sha256>/run/judges/...`, separate from the immutable
submission snapshot. Only `feedback/sNNN.json` is projected back into the solver
conversation; raw judge output is never placed in the live solver workspace.

Keep `--sandbox` for the controlled condition. Omitting it is the explicitly
unrestricted ablation: path separation still prevents accidental mixing, but it
is not a cross-provider hostile-process security boundary.
