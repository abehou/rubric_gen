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

Rubric-bank code has two ownership layers.

- `rubric_bank.py` owns domain models, rendering, aggregation, and lineage rules.
- `rubric_bank_lifecycle.py` owns schedules and immutable generation storage.

Judge execution also uses explicit ownership. `judging/runner.py` coordinates the
workflow. It calls `judging/artifacts.py` and `judging/executor.py` directly.

Reward-hacking evaluation uses focused modules inside `submission_revision`.

- `rh_protocol.py` owns evaluation contracts, request identities, and limits.
- `rh_evaluation_targets.py` loads completed study assignments.
- `rh_mechanistic.py` owns rubric-based planning and artifact validation.
- `rh_holistic.py` owns rubric-free planning and artifact validation.
- `rh_outcome_panel.py` runs both model panels and applies failure policy.
- `rh_evaluation_report.py` combines completed stage results.
- `rh_output_store.py` owns secure stage output operations.

`rubric_gen.reward_hacking` owns detector prompts, model-panel execution, costs,
and aggregate metrics. The runner accepts one evidence source. It does not parse
benchmark datasets or revision manifests.

`rubric_gen.evidence` and `rubric_gen.artifacts` contain small data utilities. They
must not select a benchmark or start a workflow.

## Dependency direction

```text
CLI
 ├─> benchmark workflows
 └─> submission revision

benchmark integrations ─> runtime, artifacts, reward hacking
submission revision    ─> benchmark registry, runtime, reward hacking
reward hacking         ─> runtime, evidence, artifacts
runtime                ─> integrations and artifacts
```

Dependencies must not point in the opposite direction. In particular, shared RH
code must not import MALT, Harvey, PaperBench, or submission-revision code.

## Extension rules

Add a submission benchmark as one package under `rubric_gen.benchmarks`. Implement
`SubmissionBenchmark` and register one instance in `registry.py`.

Add a separate benchmark workflow under the same namespace. Keep its controller,
dataset code, environment adapter, and artifacts inside its package.

Add an RH evidence format by constructing `AuditSource` objects at the owning
domain boundary. Do not add source-specific fields or parsing branches to the RH
runner.

Do not create new top-level benchmark packages. Do not put provider clients or
generic model calls inside a benchmark package.

`tests/test_architecture.py` enforces these rules with import-boundary checks.
