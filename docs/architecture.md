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

`rubric_gen.submission_revision` owns seed, revision, judging, and study workflows.
It selects a submission benchmark through the registry. Its audit adapter converts
completed revisions into blinded evidence sources.

Rubric generation has two ownership layers.

- `rubric_generation.py` owns the active-rubric model and criterion rendering.
- `rubric_generation_store.py` owns atomic self-contained generation storage.

Rubric evolution has explicit protocol and storage interfaces.

- `evolution.py` coordinates the three elicitation stages.
- `evolution_artifacts.py` owns blinded artifact-history contracts.
- `evolution_protocol.py` owns prompts, schemas, evidence, and response validation.
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

Original-rubric ensemble execution uses two owners.

- `original_rubric_inputs.py` validates studies, targets, configuration, and jobs.
- `original_rubric.py` executes groups, resumes work, and publishes summaries.
- `original_rubric_summary.py` aggregates judge, assignment, and condition results.

Paraphrase generation separates the wire protocol from the workflow.

- `paraphrase_protocol.py` owns wording slots, prompts, schemas, and validation.
- `paraphrases.py` executes and resumes paraphrase pools.
- `paraphrase_validation.py` validates pools and resolves deterministic selections.

The full-rubric judge separates its protocol from provider execution.

- `judging/full_rubric_protocol.py` owns bounds, schemas, parsing, and aggregation.
- `judging/full_rubric_judge.py` executes provider calls and writes results.

Revision evaluation uses focused modules in `submission_revision/evaluation`.

- `jobs.py` owns evaluation contracts, request identities, and limits.
- `config.py` owns the revision outcome-audit configuration.
- `targets.py` loads completed study assignments.
- `direct.py` and `evidence.py` adapt revision trajectories for direct detection.
- `rubric_score.py` owns rubric score planning and artifact validation.
- `absolute_score.py` owns rubric-free absolute scores.
- `pairwise_preference.py` owns pairwise preference scores.
- `score_execution.py` shares request execution and the combined resource cap.
- `runner.py` runs the model panels and applies failure policy.
- `report.py` combines completed stage results.
- `store.py` owns secure stage output operations.

`rubric_gen.detection` owns detector prompts, model-panel execution, costs,
and aggregate metrics. Its panel workflow has explicit owners.

- `jobs.py` owns panel configuration and prepared-job contracts.
- `planning.py` sizes direct, chunked, and MALT monitor requests.
- `costs.py` owns usage normalization and provider pricing.
- `runner.py` coordinates standard request execution.
- `job_runner.py` owns one synchronous job and its atomic `score.json` artifact.

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
