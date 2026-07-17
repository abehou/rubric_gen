# Deep Repository Refactor Design

## Purpose

Refactor the BiomniBench experiment repository around clear feature ownership,
small domain-independent utilities, and focused stateful classes. The installed
`biomnibench-agent` CLI and saved artifact schemas remain stable. Internal Python
module paths and legacy script entry points are not compatibility surfaces.

The refactor is behavior-preserving. It must retain the current submission
revision semantics, including true solver-session continuation, judge feedback,
stream-retry recovery, concurrent batch execution, score plotting, restart and
resume behavior, and score attestation.

## Design Pressure

The current flat package obscures ownership:

- `common.py` mixes progress rendering, paths, prompts, pricing, run configs,
  workspaces, task discovery, completion checks, and event parsing.
- `judge_runner.py` combines target discovery, secure filesystem access, judge
  execution, score validation, summarization, and orchestration in one class.
- `revision_controller.py` combines workflow transitions with durable-state and
  event persistence.
- Rubric generation, bundle validation, task snapshots, and compilation are
  spread across large modules with partially overlapping helpers.
- `cli.py` owns both argument construction and workflow-specific configuration
  conversion.
- The tracked script entry points duplicate the installed CLI or encode a
  machine-specific one-off investigation.

The variation points are external execution, artifact persistence, target
discovery, and workflow coordination. Those responsibilities benefit from
focused classes. Parsing, validation, formatting, hashing, and text operations
remain direct functions unless they require durable state or an injected
dependency.

## Package Architecture

The package will be organized by feature:

```text
src/rubric_gen/biomnibench/
  __init__.py
  __main__.py
  cli.py
  utils/
    __init__.py
    paths.py
    json_io.py
    hashing.py
    text.py
    progress.py
  agent/
    __init__.py
    models.py
    adapters.py
    sessions.py
    workspaces.py
    costs.py
    runners.py
  judging/
    __init__.py
    models.py
    discovery.py
    artifacts.py
    executor.py
    scoring.py
    runner.py
  revision/
    __init__.py
    models.py
    store.py
    artifacts.py
    feedback.py
    judge.py
    controller.py
  rubrics/
    __init__.py
    models.py
    snapshots.py
    schemas.py
    bundles.py
    prompts.py
    compiler.py
    retrospective.py
  perturbation/
    __init__.py
    models.py
    gemini.py
    runner.py
  visualization/
    __init__.py
    revisions.py
    comparisons.py
```

This is a target ownership map, not a requirement that every file contain a
class. A file is created only when the existing responsibility has enough code
to stand on its own. Tiny modules that would merely forward a single function
are folded into their feature package.

## Utility Boundary

`utils/` replaces the catch-all `common.py`, but it must not become another
domain dumping ground.

- `paths.py` owns repository-root and project-relative path resolution.
- `json_io.py` owns strict JSON-object reads and atomic JSON writes whose
  semantics are identical across features.
- `hashing.py` owns deterministic byte, text, and streaming file hashes.
- `text.py` owns domain-independent bounded-text operations.
- `progress.py` owns the optional `tqdm` terminal abstraction.

Agent prompts, pricing, run paths, task catalogs, rubric validation, artifact
sentinels, and score records remain in their domain packages. A utility is
shared only when at least two features need exactly the same contract.

## Agent Execution

The `agent/` package owns terminal-agent execution end to end:

- Immutable run configuration and result values live in `models.py`.
- Provider command construction remains behind the existing adapter strategy,
  with one registry responsible for selecting Gemini, Claude, or Codex.
- `sessions.py` owns persistent CLI session lifecycle, retry attempts, stream
  parsing, process signaling, and status emission.
- `workspaces.py` owns task discovery, validation, and workspace preparation.
- `costs.py` owns reported and estimated run-cost extraction.
- `runners.py` coordinates single-task and concurrent batch runs.

CLI argument namespaces do not enter this package. The CLI converts parsed
arguments into typed configs at the boundary.

## Judging

The current judge runner is decomposed through composition:

- `JudgeTargetDiscovery` resolves single and batch targets and validates target
  identity.
- `JudgeArtifactStore` owns secure output-directory traversal, race-resistant
  reads and writes, completed-record lookup, and score-attestation artifacts.
- `JudgeExecutor` resolves and invokes the task judge with the selected model.
- `JudgeRunner` coordinates attempts, concurrency, resumption, progress, and
  summary generation.
- Rubric score parsing and validation remain pure functions in `scoring.py`.

The judge source and runner hashes continue to identify the code that actually
performs execution and scoring. Refactoring must not weaken path, symlink,
ownership, or attestation checks.

## Submission Revision

The revision workflow remains a linear state machine driven by one solver
session and one judge:

```text
initialize submission
  -> judge boundary
  -> provide selected feedback to same solver session
  -> snapshot revised submission
  -> judge boundary
  -> repeat until configured round count
```

`RevisionController` owns phase transitions and coordination. `RevisionStore`
owns durable state, manifests, session identity, event append operations, and
resume reads. Artifact copying, hashing, read-only snapshots, owned-directory
removal, and live-root sentinels remain in `artifacts.py`. Feedback projection
and optimizer-judge integration remain separate domain services.

Stream-retry exhaustion recovery remains explicit workflow behavior. Process
crashes are not silently accepted. Resume and restart checks continue to reject
configuration or artifact identity mismatches.

## Rubrics

The `rubrics/` package owns both rubric workflows:

- Task-specific process-rubric compilation uses immutable task snapshots,
  structured schemas, sealed bundles, prompt construction, Gemini rewriting,
  provenance, and resumable publication.
- Retrospective process-rubric generation remains available as its current CLI
  command but is isolated in `retrospective.py`.
- Snapshot, schema, bundle, and prompt code is shared only where the two
  workflows have identical invariants.

Bundle validation and snapshot traversal remain strict because their outputs
define experiment provenance. Large validation modules may be split by schema
and storage responsibility, but validation rules and serialized formats do not
change.

## Perturbation and Visualization

Perturbation configuration and result values move to `perturbation/models.py`.
The Gemini-specific implementation moves to `gemini.py`, and concurrent
orchestration remains in `runner.py`.

Revision plots and judge-comparison plots become separate modules under
`visualization/`. They may share backend initialization and atomic image output,
but their domain-specific rendering remains separate.

## CLI and Error Boundary

`cli.py` remains the installed entrypoint. It registers the existing commands,
constructs typed configs, dispatches workflows, and translates domain errors to
CLI messages and exit codes. Domain packages must not raise `SystemExit` for
ordinary validation or execution errors.

Existing command names, argument names, defaults, help behavior, exit behavior,
progress behavior, and artifact layouts remain unchanged. `__main__.py` delegates
to `cli.main()` so local development can use:

```bash
python -m rubric_gen.biomnibench
```

No compatibility aliases will preserve the old internal module layout. Internal
call sites and tests will import the new owning module directly.

## Script Cleanup

The following tracked scripts are removed:

- `scripts/run_biomnibench_agents.py`, because it duplicates the installed CLI.
- `perturb_da124_l1.py`, because it contains a hardcoded local path and is a
  one-off trajectory inspection script rather than reusable repository code.

The empty `scripts/` directory is removed. Ignored Python cache files are not
part of the repository and have no compatibility significance.

## Migration Strategy

The refactor proceeds in independently verifiable slices:

1. Introduce `utils/` and replace identical cross-feature helpers.
2. Move the agent domain out of `common.py` and the flat agent modules.
3. Decompose judging into discovery, artifact, executor, and orchestration
   responsibilities.
4. Separate revision persistence from state-machine coordination.
5. Organize rubric compilation, snapshots, schemas, bundles, and retrospective
   generation.
6. Organize perturbation and visualization modules.
7. Thin the CLI, add `__main__.py`, remove redundant scripts, and update docs.
8. Remove obsolete flat modules only after all imports have migrated.

Each slice must preserve a runnable CLI. Existing uncommitted stream-recovery
and plotting changes are carried forward rather than overwritten.

## Verification

This refactor does not add broad new unit-test suites. Existing behavioral tests
are updated to import the new owning modules. New tests are added only when a
new boundary itself needs direct coverage, such as the module entrypoint or an
extracted artifact store.

Verification consists of:

- focused existing tests after each feature slice;
- CLI help and representative argument parsing for every subcommand;
- the complete existing test suite after integration;
- `python -m rubric_gen.biomnibench --help`;
- `git diff --check`;
- a repository search confirming no imports of removed flat modules and no
  references to removed scripts.

No live model calls are required for the refactor verification.

## Success Criteria

The refactor is complete when:

- the installed CLI and module entrypoint both load successfully;
- every existing CLI command retains its public arguments and dispatches to the
  same workflow behavior;
- serialized run, judge, rubric, perturbation, and revision artifacts retain
  their schemas and paths;
- stateful responsibilities have explicit owners and oversized orchestration
  classes no longer perform unrelated filesystem, discovery, and execution
  work;
- `common.py`, the obsolete flat implementation modules, and the redundant
  tracked scripts are gone;
- `utils/` contains only domain-independent code;
- the full test suite passes without weakening security, resume, recovery, or
  provenance checks;
- the README documents the final package layout and supported entrypoints.
