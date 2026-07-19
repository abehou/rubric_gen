# Task-Specific Frozen Process Rubrics

**Date:** 2026-07-12

**Status:** Implemented on 2026-07-13

**Repository:** `rubric_gen`

## 1. Goal

Implement an offline compiler that generates an evidence-grounded process rubric
for each BiomniBench task from immutable task inputs, validates it, records full
provenance, and seals it before a submission-revision experiment begins.

The sealed rubric provides a stable optimizer objective for comparing linear
same-session revisions. A hidden audit remains external to solver-visible
feedback.

The purpose of the new rubric is not merely to detect bad traces. It must supply
a useful gradient for improving scientific work while making unsupported claims,
evidence substitution, and scorer-directed behavior less rewarding.

## 2. Scope

### In scope

- Build a task snapshot from immutable task files.
- Generate a structured, task-specific process rubric without reading any agent
  trajectory or search history.
- Render the structured rubric into the text format expected by the existing
  BiomniBench judge.
- Validate structure, task-anchor coverage, evidence requirements, scoring, and
  provenance.
- Write an immutable, content-addressed rubric bundle outside the benchmark task
  tree.
- Allow the judge runner to consume a sealed external rubric bundle and verify
  its hash before scoring.
- Strictly validate criterion keys and recompute the scalar score from the
  selected rubric levels, including signed values.
- Support one-task generation for the initial `da-19-1` smoke test and batch
  generation later.

### Out of scope

- Prompt-only, reflection-only, or memory-only experimental arms.
- Online rubric adaptation during submission revision.
- Rubric-agent and solver-agent co-evolution.
- Model-weight updates.
- Hidden-audit implementation.
- A general plugin framework or dashboard.

Adaptive and co-evolving rubrics are recorded as a follow-up direction in
`RESEARCH.md`.

## 3. Why the Current Generator Cannot Be Used Directly

`src/rubric_gen/biomnibench/process_rubrics.py` currently creates useful
retrospective rubrics, but its request includes a baseline trajectory, the
agent-written `trace.md` and `answer.txt`, and prior judge gaps. It also writes
the result directly into each benchmark task's `tests` directory.

That behavior is unsuitable for a frozen-rubric revision experiment because:

1. the reward definition is conditioned on one agent's behavior;
2. regenerating it after optimization would leak search history into the reward;
3. writing into the task tree obscures which rubric version was used;
4. the current success marker records the model but not input, prompt, response,
   or output hashes; and
5. structural validation does not prove that criteria are tied to task anchors
   or auditable evidence.

The retrospective generator will remain available for exploratory analysis, but
its output will not be treated as a canonical revision reward.

## 4. Chosen Approach

Use a separate offline `TaskProcessRubricCompiler`. The compiler produces a
typed canonical rubric first and derives judge-facing text from that structure.
It is never called by the scorer or the submission-revision controller.

Two alternatives were rejected for this first slice:

- **Reuse the current trajectory-conditioned generator:** smallest code change,
  but it creates leakage and circularity.
- **Adapt the rubric online:** scientifically interesting, but it confounds
  agent improvement with evaluator drift and makes scores non-comparable.

## 5. Architecture and Trust Boundary

```text
immutable task directory
  instruction.md
  task.toml
  tests/rubric.txt             (summary-based task-success rubric)
  deterministic data schema
            |
            v
  TaskSnapshot + input hashes
            |
            v
  TaskProcessRubricCompiler    (offline, before search)
            |
            v
  validate -> render -> seal
            |
            v
  CanonicalRubricBundle
    rubric.json
    process_rubric.txt
    manifest.json
    raw_response.txt
            |
            v
  external judge runner ------> hash-attested, validated score record
            |
            +------ solver-visible revision feedback

  hidden audit --------------- never visible to the solver
```

The compiler must not receive:

- an experiment condition or candidate ID;
- candidate source code or mutable workspace files;
- trajectories, traces, answers, scores, or criterion feedback;
- search history, parents, or accepted/rejected candidate information; or
- hidden audit data.

The canonical bundle and compiler credentials live outside candidate
workspaces. Controlled conditions score directly with the canonical bundle.
Unrestricted conditions receive a writable working copy, while the canonical
bundle remains external so the experiment can record pre/post hashes and
retrospectively rescore the trajectory.

## 6. Components

### 6.1 Task snapshot

Add a deterministic task-snapshot builder. Its inputs are:

- `instruction.md`;
- `task.toml` when present;
- `tests/rubric.txt`, interpreted as the existing summary-based rubric;
- a deterministic inventory of allowed data files; and
- bounded schema metadata such as file path, byte size, table dimensions,
  column names, and inferred dtypes when cheaply available.

The snapshot must not include full data values, generated answers, or any file
from `runs/`. Unsupported binary formats may contribute only path, size, and
content hash. File ordering and JSON serialization must be deterministic.

The snapshot extracts stable anchors:

- the task question and required outputs;
- data-file and schema anchors;
- each parseable criterion in the summary-based rubric; and
- the generic trajectory evidence types available to the scorer, such as tool
  events, commands, file reads/writes, produced artifacts, and final claims.

Every source file and the canonical serialized snapshot receive SHA-256 hashes.

### 6.2 Structured rubric schema

The compiler model returns strict JSON conforming to schema version 1:

```json
{
  "schema_version": 1,
  "task_id": "da-19-1",
  "purpose": "...",
  "criteria": [
    {
      "criterion_id": "C1",
      "title": "...",
      "description": "...",
      "max_points": 15,
      "task_anchors": ["summary:C1", "data:counts.csv"],
      "required_evidence": ["..."],
      "acceptable_alternatives": ["..."],
      "anti_evidence": ["..."],
      "verification": ["..."],
      "levels": [
        {"label": "A", "points": 15, "description": "..."},
        {"label": "B", "points": 10, "description": "..."},
        {"label": "C", "points": 0, "description": "..."}
      ]
    }
  ]
}
```

Strings are used for evidence instructions in version 1 so the existing LLM
judge can consume them. The surrounding structure makes them independently
validatable and leaves room for executable checks in a later schema version.

### 6.3 Compiler

Add a narrow injectable protocol:

```python
class TaskRubricRewriter(Protocol):
    def rewrite(self, request: TaskRubricRequest) -> str: ...
```

`TaskRubricRequest` contains only the task snapshot, a fixed rubric-generation
contract, schema version, and validation errors from earlier attempts. A Gemini
implementation may reuse the existing HTTP client, while tests use a fake
rewriter.

The prompt requires criteria to:

- cover all important summary-rubric task-success anchors;
- specify observable evidence and how it can be checked;
- state anti-evidence and likely misleading substitutes;
- permit scientifically valid alternative workflows;
- use partial-credit levels that form a useful optimization gradient; and
- avoid rewarding verbosity, rubric quotation, claimed-but-unexecuted work, or
  judge-directed language.

No trajectory-conditioned process-rubric examples are supplied. A small fixed
schema-format example may be included, but it must contain no BiomniBench task
content.

### 6.4 Validation and rendering

Validation fails closed. A rubric is sealable only when:

- the JSON matches the supported schema and task ID;
- criterion IDs and level labels are unique and ordered;
- every criterion has at least three strictly descending levels, contains
  exactly one zero-valued level, and may continue into explicit negative
  penalty tiers;
- the A-level total is exactly 100;
- every criterion references at least one valid task anchor;
- all required summary-rubric anchors are covered;
- every criterion contains non-empty required evidence, anti-evidence, and
  verification instructions;
- acceptable alternatives are explicitly present, even if the list states that
  no meaningful alternative exists;
- level descriptions are non-empty and evidence-grounded; and
- no forbidden runtime/search fields occur in the request or bundle.

The renderer converts the validated JSON to the current parseable text format:
`Criterion N`, `Description`, `Levels`, and one bracketed description per level.
It additionally renders task anchors, required evidence, acceptable alternatives,
anti-evidence, and verification instructions.

The judge-facing text is always derived from `rubric.json`; it is never edited
independently.

### 6.5 Canonical rubric bundle

Write each successful task bundle under a caller-selected rubric-set directory:

```text
runs/biomnibench-rubrics/<rubric-set-id>/
  manifest.json
  tasks/<task-id>/
    rubric.json
    process_rubric.txt
    manifest.json
    raw_response.txt
```

The per-task manifest records:

- task ID and snapshot hash;
- hashes of every immutable input;
- compiler code/schema/prompt versions;
- provider, exact model identifier, sampling parameters, and seed when the
  provider supports one;
- raw-response, structured-rubric, and rendered-text hashes;
- generation time and validation result; and
- the content-derived canonical rubric ID.

The root manifest lists all task bundle IDs and hashes. Writes use a temporary
directory followed by an atomic rename. Existing sealed bundles are never
overwritten. Resume is allowed only when the current input and configuration
hashes exactly match the sealed manifest.

### 6.6 Judge consumption and strict scoring

Extend `JudgeRunConfig` with an optional external rubric-set directory. When it
is supplied, the runner resolves the task's canonical bundle, validates its
manifest and hashes, and copies only the rendered text into the ephemeral judge
sandbox.

After the task judge returns, the outer runner must:

1. parse every rubric level with signed integer support;
2. require the evaluation to contain exactly the rubric's criterion keys;
3. require every selected level to exist in that criterion;
4. recompute the signed raw score from selected levels, derive the authoritative
   0--100 reward by clamping that raw sum, rather than trusting `reward.json`;
5. make the recomputed score authoritative while preserving any disagreement
   with the task judge's scalar as an explicit integrity field.

This addresses the current silent failures from misspelled criterion keys and
the current omission of negative summary-rubric penalties. The validated score
record stores the canonical rubric hash alongside the trajectory, model, prompt,
and scorer identifiers.

## 7. CLI

Add a separate command so the offline compiler cannot be confused with the
existing trajectory-informed command:

```text
biomnibench-agent task-process-rubrics
  --tasks-dir PATH
  --task TASK_ID [--task TASK_ID ...]
  --output-dir PATH
  --model MODEL
  --max-retries N
  --max-concurrency N
  [--resume]
```

At least one explicit task is required initially. Omitting `--task` may be added
later for all-task generation after the one-task smoke test is verified.

The existing `process-rubrics` command remains available but its help text and
audit metadata must call it **trajectory-informed retrospective generation** and
state that its outputs are not canonical rewards for revision experiments.

The judge command gains:

```text
--rubric-set PATH
```

`--rubric-set` and an arbitrary task-local `--rubric` override are mutually
exclusive.

## 8. Errors and Recovery

- Missing or unreadable immutable inputs fail before any model call.
- Unsupported data formats degrade to hashed file metadata, not an exception,
  unless no usable task anchors remain.
- Invalid model JSON is saved as an attempt artifact and retried with the exact
  validation errors.
- Exhausted retries leave audit artifacts but no sealed bundle.
- Hash or manifest mismatch fails scoring; the runner never silently falls back
  to a task-local rubric.
- Missing, extra, or misspelled criterion keys fail scoring.
- A model/provider change creates a new rubric-set identity rather than
  overwriting an earlier bundle.
- Partial batch success is explicit in the root manifest and returns a non-zero
  exit status.

## 9. Testing

Use test-driven implementation with injected fake rewriters and fake judge
subprocesses. Required tests include:

1. task snapshots are deterministic and contain only approved immutable inputs;
2. compiler requests never contain trajectories, traces, answers, scores,
   condition IDs, or search history;
3. the schema parser rejects malformed JSON, wrong task IDs, duplicate criteria,
   invalid totals, missing evidence fields, and unknown anchors;
4. the validator requires coverage of summary-rubric anchors;
5. rendering is deterministic and parseable by the shared rubric parser;
6. bundle IDs and hashes are stable for identical content;
7. resume succeeds only for an exact input/configuration match;
8. existing sealed bundles cannot be overwritten;
9. the judge loads and hash-verifies the correct external task bundle;
10. missing or extra evaluation criteria are rejected;
11. signed level values are parsed, retained in the raw score, and included in
    the clamped authoritative reward;
12. a mismatch between `reward.json` and the recomputed score is recorded while
    the recomputed score remains authoritative;
13. CLI parsing requires explicit task IDs and separates retrospective from
    canonical generation; and
14. an integration fixture compiles, seals, renders, loads, and dry-runs one
    rubric without network access.

Run the repository's scoped test suite during implementation:

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m pytest \
  -p no:cacheprovider -q tests/test_biomnibench_agents.py
```

Unscoped `pytest` currently discovers generated scientific scripts under
`runs/`; fixing test discovery is a small prerequisite if new tests are split
into multiple files.

## 10. Acceptance Criteria

The slice is complete when:

- `da-19-1` can be compiled into a sealed task-specific rubric bundle without
  reading any trajectory or run artifact;
- the manifest proves the exact task inputs, generator configuration, raw
  response, structured rubric, and rendered rubric used;
- the existing judge runner can score a saved `da-19-1` trajectory using that
  external bundle and records its hash;
- malformed criterion output fails closed, while signed-score discrepancies are
  surfaced and corrected by authoritative recomputation;
- all targeted tests pass; and
- no online rubric-adaptation loop has been introduced yet.

## 11. Implemented Next Slice

The implemented follow-up is the task-level
[submission-revision loop](2026-07-13-biomnibench-submission-revision-loop-design.md).
It uses the frozen canonical bundle as an optional optimizer rubric while one
persistent solver session revises successive immutable submissions. The
rubric-adaptation direction remains deferred in `RESEARCH.md`.
