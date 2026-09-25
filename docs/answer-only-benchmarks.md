# HealthBench Hard and ResearchQA parametric

Implementation preparation only; no paid run has been launched. All initial
roles use `gpt-5.6-luna`: seed, solver, adversarial seed, feedback simulator,
rubric proposer, paraphraser and outcome auditor. Same-model auditing is a cheap
wiring/exploratory condition, not independent confirmation of reward hacking.

## Inputs and selection

| Benchmark | Public pool | Dev3 | Result20 |
| --- | --- | --- | --- |
| HealthBench Hard | 1,000 conversations | 3 theme-stratified tasks | next 20, excluding Dev3 |
| ResearchQA parametric | validation 703 / test 3,750 | 3 validation tasks | 20 test tasks |

Selection is seeded (`20260925`) metadata-stratified round robin, independent of
solver outcomes. ResearchQA uses upstream revision `bf8a4cfef073ecfc0275c57acf8ca960e4dc79d6`;
HealthBench uses the official dated Hard file. Selection never uses
solver scores and RH outcomes. Three tasks cannot represent all seven strata;
Dev3 is for development, not a population performance estimate. Each prepared
pool records original source IDs and source URL in `manifest.json`; each hidden
`tests/source.json` retains the complete original record. ResearchQA preserves
all citation criteria. It does not supply survey papers, search results or
reference answers to the solver. No new arbitrary length cap is imposed.

Sources: [official HealthBench files](https://github.com/openai/simple-evals/blob/main/healthbench_eval.py),
[ResearchQA dataset](https://huggingface.co/datasets/realliyifei/ResearchQA),
[ResearchQA scoring code](https://github.com/realliyifei/ResearchQA/blob/main/compute_coverage.py),
[ResearchQA leaderboard](https://researchqa.cylumn.com/).
BenchLM is a third-party aggregator, not the official HealthBench leaderboard.

## Prepare without model calls

From the repository, after `uv sync`:

```bash
uv run python download_healthbench_hard.py
uv run python download_researchqa.py
```

For offline preparation pass `--source /absolute/path/to/official-file`.
HealthBench accepts JSONL, ResearchQA a JSON array. ResearchQA's local source
must be `valid.json` for Dev3 and `test.json` for Result20. Downloaders refuse to
overwrite existing pools. To prepare held-out pools later, add `--subset result20`.
`--output-dir` supports the persistent Babel dataset root. Downloads make no
model calls; data are ignored by Git and must be prepared on each run host.

## Initial workflow and cost control

Use `experiments/healthbench-hard-dev3.yaml` or
`experiments/researchqa-parametric-dev3.yaml` with the existing commands:

```bash
uv run rubric-gen seed --experiment experiments/healthbench-hard-dev3.yaml --max-concurrency 6
uv run rubric-gen paraphrase --experiment experiments/healthbench-hard-dev3.yaml --max-concurrency 6
uv run rubric-gen revise --experiment experiments/healthbench-hard-dev3.yaml --assignment-workers 6 --max-concurrency 12 --resume
uv run rubric-gen detect --experiment experiments/healthbench-hard-dev3.yaml --study-dir runs/studies/<source-study-experiment-id> --max-concurrency 12 --resume
```

These are future paid commands, not performed setup steps. Before launching,
apply the host's runtime standard and [Babel setup](BABEL_SETUP.md),
confirm actual model access and estimate throughput against the two-hour target.
For Babel, resolve dataset/seed/run/cache paths under
`/data/user_data/aydanh/rubric_gen/`; do not launch these relative-path local YAMLs
unchanged on Babel. Provider capacity is shared with other work.

Default per benchmark: 3 tasks × 3 replicates × 2 conditions (Full/static,
User-simulator/static) = 18 assignments, up to 54 solver revision turns, plus the
shared ordinary/adversarial seed bank, paraphrases, feedback, judging and audits.
The shared protocol requires three seed replicates and three revisions for its
post-update window. Min/max revisions are both 3; invalid or unchanged outputs
can still affect the realized trajectory. Three paraphrases retain separate
selected, development and held-out views. No dollar ceiling is claimed by the
existing request-count/output-token caps; measure actual saved usage before
expansion. In particular, context snapshots must not be summed as if all were
newly billed tokens.

The optional `*-policies-dev3.yaml` files expose the existing 4 feedback × 5 rubric
policy matrix (180 assignments per benchmark), still all-Luna and three rounds.
They are NOT the first-run default or an authorization to launch 180 assignments.
Use `execution_conditions` to collect a bounded matched comparison. The original
BioMNIBench/PaperBench YAMLs, controller and policy implementations are unchanged.
Result20 data preparation is available; its final experimental matrix and any
larger task count should be chosen after Dev3, before inspecting held-out results.

## Answer artifact versus trajectory

`answer.txt` is the only required final deliverable. There is no solver-authored
`trace.md` requirement. The runtime still saves each observable agent turn,
feedback, answer snapshot and revision in its existing trajectory/ledger format.
File I/O delivers the answer through the existing Codex runtime; no retrieval or
research tools are permitted by the task prompt and network access is restricted
by the existing sandbox. This is not a new tool-free API backend: local shell
capability remains, so inspect traces for protocol violations in the first live
smoke. It is a parametric, file-backed revision experiment, not a native one-shot
leaderboard submission, and does not expose hidden chain of thought.

All four existing RH windows remain meaningful:

- full trajectory: any observed exploitation over the complete run;
- post-update: behavior beginning at the existing `s003` boundary (shorter here);
- final revision: last artifact-producing turn and its behavior;
- final artifact: only the retained answer, excluding earlier retracted attempts.

A mistaken medical statement or inaccurate citation alone does not establish
reward hacking; retain the detector's rubric-exploitation criteria. W/S/H/A and
their gaps remain available through the existing audits, but W−S with an all-Luna
panel is not a weak-versus-strong-model contrast. Cross-benchmark RH comparisons
must report revision exposure and evidence availability, not just percentages.

## Scoring and later stronger audit

HealthBench preserves binary met/not-met criteria, signed weights and the sum of
positive points as denominator. ResearchQA preserves the five coverage levels
as 0/1/2/3/4 points with denominator 4 × number of criteria. The original rubric
is a project judge input; generated paraphrases and learned penalties are study
treatments, not changes to the source benchmark.

Project W/S/H scores retain the existing per-answer [0,100] clipping. For official
HealthBench arithmetic, use saved raw criterion points: divide by that task's
positive-point maximum, average tasks, then clip the aggregate. Pure aggregation
helpers live in `benchmarks/answer_only/scoring.py`; no separate official-model
scorer or leaderboard export is automatically run. ResearchQA coverage arithmetic
is preserved, but judge model/prompt changes still prevent an official-score claim.

To upgrade auditing, copy the YAML and change only `outcome_audit.models`; use
`detect --study-dir` against the saved completed source study. Do not rerun the
solver or alter its protocol to obtain a stronger panel. Pick the panel after
budget/access is known. Audit-model changes produce their own result identity.

## Verification

`tests/test_answer_only_benchmarks.py` covers hidden-data isolation, signed and
five-level rubrics, native aggregation, disjoint deterministic selection, YAML
loading and provider-free three-round controller execution without `trace.md`.
Offline tests are not evidence of real provider access, cost, model quality or
RH prevalence. A live Dev3 acceptance run remains pending budget/access.
