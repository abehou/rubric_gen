# Architecture

The repository separates benchmark policy from shared execution code. A benchmark
owns its input format, output format, prompts, and environment rules.

## Package roles

`rubric_gen.benchmarks` contains all benchmark integrations.

- `biomnibench_da` defines the BiomniBench-DA submission contract.
- `paperbench_code_dev` defines the PaperBench Code-Dev contract and dataset loader.
- `harvey_lab` owns the Harvey harness-evolution workflow and Podman environment.
- `malt` owns the labeled MALT dataset preparation and evaluation command.
- `base.py` defines the common submission-benchmark contract.
- `registry.py` is the only submission-benchmark lookup table.

`rubric_gen.runtime` contains provider and process adapters. It does not select or
import benchmarks. Callers must pass prompts, required outputs, and session rules.

Codex scientific command environments explicitly select Matplotlib's noninteractive
`Agg` backend through `shell_environment_policy.set`. This applies inside both
one-shot and persistent sessions, where merely exporting an outer environment
variable would be filtered out; credential filtering and filesystem/network
permissions remain unchanged. It avoids native GUI initialization for background
plots but does not prevent task code from explicitly selecting another backend.
The persistent app-server proxy also prepends the invoking project's Python bin
directory, matching the one-shot adapter, so ordinary Python commands use the same
installed dependencies. Scientific command defaults set OpenBLAS, OpenMP and vecLib
thread counts to one to avoid nested numeric parallelism across many assignments;
these are library defaults, not a hard process/thread quota.

`rubric_gen.submission_revision` owns seed, revision, judging, and study workflows.
It selects a submission benchmark through the registry. Its audit adapter converts
completed revisions into blinded evidence sources.

Rubric generation has two ownership layers.

- `rubric_generation.py` owns the active-rubric model and criterion rendering.
- `rubric_generation_store.py` owns atomic self-contained generation storage.
- `pretreatment_rubrics.py` owns shared baseline compilation and exact installation.

Rubric evolution has explicit protocol and storage interfaces.

- `evolution.py` coordinates pairwise assessment, criterion induction, and validation.
- `evolution_artifacts.py` owns blinded artifact-history contracts.
- `evolution_assessment.py` owns the three assessment views, exact-ID response
  matching, and score-derived rubric-view preferences; rubric-free preferences
  remain model judgments.
- `evolution_protocol.py` owns criterion induction/application contracts and
  deterministic aggregate-margin admission.
- `evolution_provider.py` owns the structured provider contract and output type.
- `evolution_serialization.py` owns strict JSON and content-identity helpers.

Judge execution also uses explicit ownership. `judging/runner.py` coordinates the
workflow. It calls `judging/artifacts.py` and `judging/executor.py` directly.

Submission revision control also uses explicit ownership.

- `controller.py` coordinates the top-level revision state machine.
- `controller_setup.py` builds and validates runtime dependencies.
- `controller_scoring.py` owns judge checkpoints, reuse, feedback, and replay.
- `controller_workspace.py` owns live workspaces and sealed submissions.
- `controller_recovery.py` owns resume and interruption recovery.
- `controller_recovery_artifacts.py` validates recovery-only disk residue.

Randomized study execution and validation use separate owners.

- `study.py` owns concurrent assignment execution and its ledger.
- `study_layout.py` owns safe assignment paths.
- `study_validation.py` coordinates completed-revision validation.
- `study_validation_context.py` validates experiment identity and state.
- `study_validation_artifacts.py` validates generations, judgments, and feedback.

Rubric proposer invocation failures and generated-response validation failures are
distinct. Exhausted provider-call retries raise `RubricProposerProviderError`
without publishing a generation; only actual response-validation failures may use
the bounded rubric fallback protocol. Provider retries do not fabricate validation
repair instructions. The study's solver-group circuit counts both Codex session
health failures and proposer invocation failures, opening after three consecutive
failed assignments; it prevents queued assignments from starting, but does not
cancel already-running assignments. Successful assignments reset an unopened circuit.

Original-rubric ensemble execution uses two owners.

- `original_rubric_inputs.py` validates studies, targets, configuration, and jobs.
- `original_rubric.py` executes groups, resumes work, and publishes summaries.
- `original_rubric_summary.py` aggregates judge, assignment, and condition results.

Paraphrase generation separates the wire protocol from the workflow.

- `paraphrase_protocol.py` owns wording slots, prompts, schemas, and validation.
- `paraphrases.py` executes and resumes paraphrase pools.
- `paraphrase_validation.py` validates pools and resolves the fixed experiment selection.

The full-rubric judge separates its protocol from provider execution.

- `judging/full_rubric_protocol.py` owns bounds, schemas, parsing, and aggregation.
- `judging/full_rubric_judge.py` executes provider calls and writes results.

Revision evaluation uses focused modules in `submission_revision/evaluation`.

- `jobs.py` owns evaluation contracts, request identities, and limits.
- `config.py` owns the revision outcome-audit configuration.
- `targets.py` loads completed study assignments.
- `direct.py`, `evidence.py`, and `evidence_ledger.py` adapt full and fixed
  post-update revision windows. The ledger reads each chronological turn once.
- `rubric_score.py` owns rubric score planning and artifact validation.
- `absolute_score.py` owns rubric-free absolute scores.
- `pairwise_preference.py` owns pairwise preference scores.
- `score_execution.py` shares request execution and the combined resource cap.
- `runner.py` runs the model panels and applies failure policy.
- `store.py` owns secure stage output operations.

Each stage writes its own records and summary. No production module combines
the stages into a second report schema.

`rubric_gen.detection` owns detector prompts, model-panel execution, costs,
and aggregate metrics. Its panel workflow has explicit owners.

- `jobs.py` owns panel configuration and prepared-job contracts.
- `planning.py` sizes direct, chunked, and MALT monitor requests.
- `costs.py` owns usage normalization and provider pricing.
- `runner.py` coordinates standard request execution.
- `job_runner.py` owns one synchronous job and its atomic `score.json` artifact.

The direct detector returns a nonzero exit status if any planned record is
unsuccessful, including mixed successful/failed panels. Completed judgments,
validated cached judgments and legitimate abstentions remain successful; the
experiment audit handler still attempts every later stage before reporting an
overall failure. Exit status does not replace artifact-level coverage checks.

The runner accepts one evidence source. It does not parse benchmark datasets or
revision manifests.

`rubric_gen.evidence` and `rubric_gen.artifacts` contain small data utilities. They
must not select a benchmark or start a workflow.

## Dependency direction

```text
CLI
 ├─> benchmark workflows
 └─> submission revision

benchmark integrations ─> runtime, artifacts, detection
submission revision    ─> benchmark registry, runtime, detection
detection              ─> runtime, evidence, artifacts
runtime                ─> integrations and artifacts
```

Dependencies must not point in the opposite direction. Shared detection code
must not import MALT, Harvey, PaperBench, or submission-revision code.

## Extension rules

Add a submission benchmark as one package under `rubric_gen.benchmarks`. Implement
`SubmissionBenchmark` and register one instance in `registry.py`.

Add a separate benchmark workflow under the same namespace. Keep its controller,
dataset code, environment adapter, and artifacts inside its package.

Add a detection evidence format by constructing `AuditSource` objects at the owning
domain interface. Do not add source-specific fields or parsing branches to the
runner.

Do not create new top-level benchmark packages. Do not put provider clients or
generic model calls inside a benchmark package.

`tests/test_architecture.py` enforces these rules with import checks.
