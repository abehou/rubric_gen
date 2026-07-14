# BiomniBench Submission Revision Loop Design

## Goal

Build a task-level experiment in which one BiomniBench solver agent keeps the
same provider conversation and workspace, receives rubric-based judge feedback,
and linearly revises its submitted solution for a fixed number of turns. The
experiment records whether optimization pressure raises the visible rubric score
through genuine improvement, unsupported presentation changes, or other reward
hacking behavior.

## Scope

The first implementation includes:

- one BiomniBench task per experiment;
- one solver provider/model and one persistent provider session;
- an initially rubric-blind submission followed by a fixed number of revisions;
- one frozen optimizer rubric per experiment, either task-local or from a
  compiled task-specific rubric set;
- `full` and `score_only` solver-visible feedback policies;
- immutable snapshots of every submitted solution and its cumulative process;
- the existing BiomniBench judge as the only feedback-producing role; and
- enough provenance to rescore submissions later with frozen audit rubrics.

This implementation excludes harness editing, prompt evolution, candidate
selection, rollback, beam search, reflection-only memory, rubric adaptation,
and rubric-generator agents.

## Roles and Experimental Boundary

There are exactly two model roles:

1. **Solver agent:** solves the task and revises its own submission in one
   persistent CLI conversation.
2. **Judge:** scores immutable snapshots and returns structured feedback through
   a trusted projection layer.

The controller is orchestration code, not an agent. It never proposes a solution
or edits solver artifacts. Hidden or audit scores are never inserted into the
solver conversation or workspace.

## Linear Revision Protocol

For submission `s000`, the controller prepares a pristine task workspace and
starts one provider session with the existing rubric-blind BiomniBench prompt.
After the solver stops, the controller validates the required `trace.md` and
`answer.txt`, snapshots the solution workspace, and constructs a cumulative
trajectory containing all solver turns through `s000`.

For each revision round `t >= 1`:

1. Score snapshot `s(t-1)` with the frozen optimizer rubric.
2. Convert validated judge artifacts into the configured feedback view.
3. Resume the exact same provider session in the same live workspace.
4. Ask the solver to revise `trace.md`, `answer.txt`, and supporting analysis
   artifacts in response to the feedback.
5. Save the new turn trajectory and immutable snapshot `s(t)`.

There is no acceptance test. A lower-scoring submission still becomes the input
to the next turn. This preserves regressions, oscillations, and attempted hacks
instead of hiding them behind best-of-search selection. After the last solver
turn, the controller also judges the final snapshot so every submission has a
visible optimizer score. A configured revision count of `R` therefore produces
and judges exactly `R + 1` submissions, including `s000`.

## True Session Continuation

The experiment stores a stable provider session ID in its manifest before or
immediately after the initial turn:

- Gemini CLI starts with `--session-id <uuid>` and continues with
  `--resume <uuid>`.
- Claude Code starts with `--session-id <uuid>` and continues with
  `--resume <uuid>`.
- Codex starts normally, records the thread ID from its JSON event stream, and
  continues with `codex exec resume <thread-id>`.

Every turn uses the same provider, model, working directory, permission policy,
and no-web setting. The system must not silently replace a lost session with a
new conversation. A missing or unresumable session stops the experiment.

## Feedback Policies

The initial submission is rubric-blind. Feedback begins only after `s000` has
been judged.

At experiment initialization, the controller records the exact optimizer rubric
text and identity hash. Every judge turn must resolve to that same identity;
changing the task-local rubric or compiled rubric set stops the experiment.

`full` feedback contains:

- the frozen optimizer rubric text;
- the validated total and raw scores;
- validated criterion levels and criterion point contributions;
- bounded per-criterion judge reasons; and
- bounded overall judge reasoning.

`score_only` contains only the validated total score. It does not expose rubric
text, criterion identities, levels, points, or judge reasons.

The projector treats `score_validation.json` as authoritative for scores and
selected levels. It reads explanatory strings from `evaluation.json` only after
the validation artifact's recorded evaluation hash matches the file. Judge
reasons are labeled as model feedback, not as verified evidence. Raw judge
artifacts, stdout, paths, reported-but-unvalidated scores, and audit results are
never passed to the solver.

## Workspace and Artifact Model

The solver edits one live workspace throughout the conversation. After each
turn, the controller copies solution artifacts into a submission snapshot while
excluding canonical task data, `instruction.md`, virtual environments, and
caches. Canonical task inputs remain referenced by content hash. Snapshot files
are made read-only after hashing.

The experiment layout is:

```text
<experiment>/
  manifest.json
  events.jsonl
  live/workspace/
  turns/turn-000/{prompt.txt,trajectory.stream.jsonl,status.json}
  turns/turn-001/{prompt.txt,trajectory.stream.jsonl,status.json}
  submissions/s000/
    workspace/{trace.md,answer.txt,scripts-and-artifacts...}
    trajectory.stream.jsonl
    snapshot.json
  submissions/s001/...
  evaluations/s000/...
  evaluations/s001/...
  feedback/s000.json
  feedback/s001.json
```

Each submission's trajectory is cumulative, because a later solution may depend
on analysis performed in earlier turns. Per-turn trajectories remain separate
under `turns/` so changes in strategy can also be analyzed locally.

Judge output roots are namespaced by submission and optimizer rubric identity,
preventing summary, process, or later audit rescoring from overwriting one
another.

## Components

### Session driver

A provider-specific session driver builds initial and resume commands, streams
JSONL output, and returns the stable session ID. It reuses the current provider
configuration and does not alter the ordinary one-shot `AgentRunner` behavior.

### Feedback projector

A pure projector reads validated optimizer artifacts and produces both a
canonical feedback record and the next solver message. Keeping this boundary
pure makes `full` versus `score_only` an experiment condition rather than a
different judging implementation.

### Submission revision controller

The controller owns the live workspace, turn ordering, snapshots, judging,
feedback delivery, and append-only event records. Dependencies for session turns
and judging are injected so the orchestration can be tested without model calls.

### CLI

Add one task-level command that accepts the task directory, experiment output,
revision count, solver provider/model, optimizer rubric selection, judge model,
review mode, and feedback policy. `trajectory` is the default review mode.

## Failure and Resume Semantics

Completed snapshots, evaluations, and feedback records are immutable. Resume is
supported only from completed turn or judge boundaries. If a process dies during
a solver turn, the controller records the incomplete turn and stops rather than
replaying the same judge message into an uncertain conversation. A user may
inspect or explicitly restart that experiment, but the implementation does not
pretend exactly-once delivery was achieved.

A failed judge turn produces no solver feedback and stops the loop. A solver
turn that lacks non-empty required outputs is retained as a failed turn but is
not judged as a valid submission.

## Reward-Hacking Analysis

The loop records the complete visible optimization trajectory without deciding
whether an improvement is legitimate. Later analysis can compare:

- visible optimizer score versus frozen outcome/process/audit scores;
- changes to answers versus changes only to trace language;
- claimed checks versus saved scripts and artifacts;
- per-turn strategy changes in the raw trajectory; and
- improvement under `full` versus `score_only` feedback.

The primary process experiment judges cumulative raw trajectory. Trace-only
judging remains a comparison condition because an editable narrative is easier
to game.

## Future Co-Evolving Rubrics

`RESEARCH.md` will describe rubric co-evolution over this submission loop, not
over harness code. Future rubric versions must be immutable, parent-linked, and
activated only at recorded submission boundaries. When a rubric changes, all
retained submissions and the current incumbent must be rescored under the same
version before comparisons are made. Frozen audit rubrics remain permanently
outside both solver and rubric-generator visibility.

No rubric adaptation is implemented in this milestone.

## Lean Verification

Only two new automated tests are required:

1. A fake end-to-end loop verifies one session ID across turns, rubric-blind
   `s000`, linear continuation after a score decrease, immutable snapshots, and
   final judging.
2. A feedback projection test verifies that `full` exposes only validated fields
   while `score_only` exposes only the total score.

CLI help and one manual fake-provider smoke run provide integration verification.
No exhaustive validation matrix or provider subprocess test suite is added.
