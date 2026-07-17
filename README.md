# Rubric Gen

Tools for running BiomniBench-DA terminal agents, compiling process rubrics,
perturbing and judging saved runs, comparing judge views, and running
persistent-session submission-revision experiments.

## Setup

Prerequisites:

- Python 3.11 or newer and [`uv`](https://docs.astral.sh/uv/).
- The Hugging Face `hf` CLI for downloading the benchmark tasks.
- An installed and authenticated `gemini`, `claude`, or `codex` CLI for agent
  and revision runs using that provider.
- `GEMINI_API_KEY` (or `GOOGLE_API_KEY`) for Gemini judging, perturbation, and
  rubric generation. Anthropic judge models instead require
  `ANTHROPIC_API_KEY`.

From the repository root, install the project dependencies:

```bash
uv sync
```

## Code Layout

The installed `biomnibench-agent` command is the stable interface. Internals are
grouped by experiment responsibility:

- `agent/`: provider adapters, persistent sessions, task workspaces, run costs,
  and single/batch execution.
- `judging/`: target discovery, race-resistant artifact storage, judge execution,
  strict scoring, and score attestation.
- `revision/`: the linear same-session revision controller, durable state store,
  immutable snapshots, feedback projection, and optimizer judge adapter.
- `rubrics/`: immutable task snapshots, structured schemas, prompts, sealed
  bundles, task-specific compilation, and retrospective rubric generation.
- `perturbation/`: perturbation models, Gemini implementation, and concurrent
  orchestration.
- `visualization/`: revision histories and paired judge comparisons.
- `integrations/`: external service clients; `utils/`: only domain-independent
  paths, progress, hashing, and text helpers.

For local development, the CLI can also be run as a module:

```bash
uv run python -m rubric_gen.biomnibench --help
```

Saved run formats and command-line behavior remain unchanged by this layout.

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

## Compile Canonical Task Process Rubrics

Run `task-process-rubrics` before using `--rubric-set` with `judge` or `revise`.
It uses only immutable task inputs and writes a sealed external bundle; repeat
`--task` to compile more than one task.

```bash
uv run biomnibench-agent task-process-rubrics \
  --tasks-dir data/biomnibench-da \
  --task da-19-6 \
  --task da-26-4 \
  --output-dir runs/task-process-rubrics/pilot \
  --model gemini-3.5-flash \
  --max-concurrency 2
```

Use `--resume` only to reuse bundles whose task inputs and compiler
configuration match exactly. A command may select either `--rubric-set` or a
task-local `--rubric`, not both.

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
  --model gemini-3.1-pro-preview
```

Judge with the sealed task-specific bundle compiled above:

```bash
uv run biomnibench-agent judge \
  --run-dir runs/biomnibench-agents/all-gemini-20260705-185054 \
  --tasks-dir data/biomnibench-da \
  --review trajectory \
  --rubric-set runs/task-process-rubrics/pilot \
  --model gemini-3.1-pro-preview
```

Judge the same run with a task-local retrospective process rubric:

```bash
uv run biomnibench-agent judge \
  --run-dir runs/biomnibench-perturbations/da-26-4-pilot/L3 \
  --review trace \
  --rubric process_rubric.txt \
  --model gemini-3.1-pro-preview
```

Judge multiple run directories in one invocation:

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
  --model gemini-3.1-pro-preview
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

Judge all tasks under a batch run directory:

```bash
uv run biomnibench-agent judge \
  --run-dir runs/biomnibench-agents/all-gemini-20260705-185054 \
  --review trajectory \
  --rubric process_rubric.txt \
  --model gemini-3.1-pro-preview
```

## Compare Judge Score Files

Run `judge` once with `--review trace` and once with `--review trajectory`
without overriding `--output`. After both default score files exist in the
batch run directory, generate a paired CSV, scatter plot, and sorted-delta plot:

```bash
uv run biomnibench-agent compare-judges \
  --run-dir runs/biomnibench-agents/all-gemini-20260705-185054 \
  --label-top-n 8
```

To compare any two compatible score summaries, pass `--left-scores` and
`--right-scores`, with optional `--left-label` and `--right-label`.

## Generate Retrospective Process Rubrics (Non-Canonical)

`process-rubrics` is trajectory-informed retrospective analysis. It reads a
completed batch's trajectories, traces, answers, and prior judge artifacts and
writes `tests/process_rubric.txt` inside each task. These rubrics are useful for
exploration but are not sealed canonical rewards; use `task-process-rubrics`
for `--rubric-set` workflows.

```bash
uv run biomnibench-agent process-rubrics \
  --tasks-dir data/biomnibench-da \
  --run-dir runs/biomnibench-agents/all-gemini-20260705-185054 \
  --model gemini-3.5-flash \
  --max-concurrency 4 \
  --resume
```

## Revise a Submission in One Agent Session

`revise` runs a linear self-revision experiment. One solver session produces an
initial rubric-blind submission, receives judge feedback, revises the same live
workspace, and repeats. There is no candidate selection or rollback: a lower
score still becomes the next revision. If `--revision-rounds` is 3, the command
produces and judges four submissions (`s000` through `s003`). An explicit
solver `--model` is required so the requested model can be pinned across the
persistent session. A provider-reported model identity is also recorded and
checked when the provider exposes one; otherwise the requested model is used as
the effective identity. The configured provider executable is recorded and must
match on resume.

Run the primary full process-rubric feedback condition with Gemini CLI:

```bash
uv run biomnibench-agent revise data/biomnibench-da/da-19-6 \
  --experiment-dir runs/biomnibench-revisions/da-19-6-process-full \
  --revision-rounds 3 \
  --provider gemini \
  --model gemini-3.5-flash \
  --judge-model gemini-3.1-pro-preview \
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
  --judge-model gemini-3.1-pro-preview \
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

The CLI turns the supplied `--experiment-dir` into a readable, condition-specific
name. It appends the task, feedback policy, revision count, provider, solver and
judge models, rubric source, review mode, permission settings, truncation,
executable, and raw-output setting. `--resume` and `--restart` are intentionally
excluded so they reopen the same experiment. Thus the full-feedback path above
and its score-only variant are always different directories.

To run every task under both feedback conditions concurrently, use `--all` and
`--full_v_score`. With 45 tasks, this expands to 90 independent experiments;
`--max-concurrency 90` permits all 90 to be scheduled at once (subject to
provider/API capacity):

```bash
uv run biomnibench-agent revise \
  --all \
  --full_v_score \
  --tasks-dir data/biomnibench-da \
  --experiment-dir runs/biomnibench-revisions/da-process \
  --revision-rounds 10 \
  --provider gemini \
  --model gemini-3.5-flash \
  --judge-model gemini-3.1-pro-preview \
  --rubric rubric.txt \
  --review trajectory \
  --sandbox \
  --skip-trust \
  --max-concurrency 90
```

Batch mode shows one progress bar for completed experiments; each worker keeps
one true solver session and its own output directory. `--feedback-policy` is
used only when `--full_v_score` is absent.

If an incomplete run stopped at a recorded clean judge boundary, repeat the
same command against the same task and experiment directory with `--resume`:

```bash
uv run biomnibench-agent revise data/biomnibench-da/da-19-6 \
  --experiment-dir runs/biomnibench-revisions/da-19-6-process-full \
  --revision-rounds 3 \
  --provider gemini \
  --model gemini-3.5-flash \
  --judge-model gemini-3.1-pro-preview \
  --rubric process_rubric.txt \
  --feedback-policy full \
  --review trajectory \
  --sandbox \
  --skip-trust \
  --resume
```

Resume validates the original configuration, frozen rubric and task hashes,
requested solver model, any available provider-reported model identity,
executable configuration, session ID, immutable snapshots, feedback, and live
workspace. It does not restart an uncertain or failed solver turn, create a
replacement session, or resume into a different experiment directory.

To discard a matching existing experiment and redo the task from `s000`, repeat
the original command with `--restart` instead of `--resume`. Restart removes the
old experiment artifacts and any retained live workspace, so use it only when
the prior run is no longer needed.

Omit `--rubric` and `--rubric-set` to optimize the task's default outcome
rubric (`tests/rubric.txt`). The solver never sees the rubric before `s000`.
Under `full`, later turns receive the frozen rubric, validated criterion scores,
selected levels, and bounded judge reasons. Under `score_only`, they receive only
the total score. The current loop keeps that rubric fixed for the full
trajectory; rubric co-evolution is future work described in `RESEARCH.md`.

Before the solver starts `s000`, the controller freezes the complete scoring
identity: rubric identity, judge source and runner hashes, scorer-module hash,
review configuration, and effective judge model. Every score must attest that
same identity.

Gemini and Claude sessions use an experiment UUID; Codex resumes the thread ID
reported by its initial JSON stream. Every turn uses the same provider session
and live workspace. The controller creates that live workspace in an external
temporary root and records its absolute path in `manifest.json`; it is not
nested under the experiment artifacts. A resumable incomplete run retains the
workspace. Successful completion verifies that the temporary root was removed
and records `live_workspace_removed: true`.

The live root has a sentinel bound to the exact experiment. Resume and cleanup
accept only a nonsymlink root with the expected prefix directly under the
platform temporary directory and a matching sentinel. These checks confine what
the controller will reopen or delete; they are not protection against arbitrary
same-user host tampering.

The experiment directory preserves `state.json`, the frozen rubric text,
per-turn prompts and trajectories, immutable submission snapshots, cumulative
trajectories, judge artifacts, projected feedback, and the complete score
sequence. The live workspace path is provenance, not a portable artifact: do
not move or delete it before resuming an incomplete run.

After each solver submission is sealed, the controller assigns a random 128-bit
judge-attempt ID and stores optimizer artifacts under
`evaluations/sNNN/<rubric-sha256>/<attempt-id>/run/judges/...`, separate from the
immutable submission snapshot. The judge runner non-mutatingly revalidates every
previously scored attempt and re-projects its feedback from the judge artifacts
on resume, before each later judge boundary, and before completion. Historical
scored attempts are immutable and are never regenerated; failed revalidation
stops the experiment. Only the current unscored attempt may have a partial or
invalid root removed within the confined evaluation namespace and regenerated.
Only `feedback/sNNN.json` is projected back into the solver conversation; raw
judge output is never placed in the live solver workspace.

Filesystem isolation is provider-specific. For Gemini, `--sandbox` requests the
Gemini CLI sandbox and omitting it changes that provider policy. The Codex
session driver always requests `workspace-write`; this limits writes but is not
a claim of hostile-process read isolation, and toggling this CLI flag does not
currently create a Codex unrestricted condition. Claude Code does not receive a
sandbox flag from this harness, so a controlled Claude run needs an externally
verified container or equivalent filesystem boundary. Treat omission as an
unrestricted ablation only when it actually changes the provider or container
policy. Path separation helps prevent accidental mixing but does not by itself
keep a hostile solver from reading judge, rubric, or audit artifacts. On POSIX,
the driver starts each provider turn in its own process group and terminates
remaining members after the turn, including ordinary descendants. A descendant
that calls `setsid`, otherwise detaches, or coordinates with another same-user
process can escape that cleanup and tamper with host-visible paths. Experiments
requiring hostile-process isolation therefore still need a verified external
container; this harness does not claim host-unrestricted tamper resistance.
