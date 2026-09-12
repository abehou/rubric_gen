# Opus rubric response validation — v8 live validation and native recovery

**Both v8 production smokes passed. Current scientific coverage: 120/120 valid revisions, Sol 900/900, Opus 764/900.** The two proven v5 saved responses were published with zero provider calls, followed by successful one-call 306/872 judgments. Exactly 136 Opus rubric judgments still need new responses; native missing-only recovery **10414690** is submitted. Detector and holistic stages remain complete. Final metrics remain withheld. Queue 2 dev3 revision jobs continue independently.

V5 permitted omitted/conflicting duplicate blocks; v6 failed Anthropic schema compilation; v7 compiled but returned 242 missing judgments in the 306-criterion smoke. The validated single-call representation removes all coarse-block fields and requires only `criteria_text` and `overall_reasoning` strings. The model must emit every explicit global index in order as `global_index|level_index|reason`. Local validation rejects incomplete, duplicate, reordered, invalid-level and empty-reason outputs without repair. This changes serialization only, retaining the full scientific request, model, effort, output budget, streaming transport and bounded retries.

## Two zero-provider saved-response publications

Native replay ran from `8bff72545f78f58cd93101043842a134fa04ad38` in Slurm step **10414497.2**, as one auxiliary worker within the existing PaperBench allocation; its revision dispatcher remained running. The reviewed replay path revalidated the persisted request and exact criterion coverage, accepted only fully identical redundant blocks, and published canonical records with original v5 producer provenance. Network/provider calls were forbidden and counted: **zero**. No criterion or score was inferred.

| Task / replicate / condition / final rubric | Criteria | Original judgment key / attempt | Canonical published key |
|---|---:|---|---|
| bam / 3 / user-simulator-static / holdout 4 | 255 | `b60365181808e6d81da0d4cc23bc4e61` / `attempt-002.json` | `5383cbb4b60ef4a2a9a32979f2376db0` |
| all-in-one / 2 / full-static / holdout 2 | 92 | `6daba9ad156ed63490ba3ad8651800ea` / `attempt-003.json` | `2dd7b7d2af6bc08df161808a0b1558ac` |

Each record's `usage.local_response_replay` retains the exact original attempt/response paths and producer identity. The original raw files were not changed or relabeled. Fresh native preparation recognizes both publications, all 900 Sol and 762 Opus records, and exactly 138 missing Opus jobs. Direct comparison found **5,460 pre-existing files unchanged**, including all 4,560 files of the original 760 valid Opus judgments. Elapsed replay/validation time was **603.586s**; audit admission wait was **0.001893s**. Private operational receipt: `runs/opus-two-v5-replays-queue3.json` in the pinned repair checkout.

## Current staged validation

**792 focused tests passed in 94.38s**, Slurm step `10414497.3`. Tests cover cardinalities 1, 63, 64, 67, 86, 92, 120, 145, 178, 255, 306, 403 and 872, historical/current canonical score equivalence, malformed and absent rows, the observed v7 omission, 760-valid/140-missing resume fixtures, no imputation, Sol behavior, and streaming/inactivity/capacity regression. One existing Python multiprocessing fork deprecation warning was emitted; no failure.

**Real native read-only validation passed**, Slurm step `10414497.4`, 234.615s. It revalidated all 120 completed revision targets, reused 900 Sol and 762 Opus judgments, and schedules exactly **138 missing Opus / zero Sol / zero valid Opus / zero detector / zero holistic** provider jobs. All 4572 files belonging to the 762 valid Opus records compare byte-identical. Scientific writes and network access were prohibited. Four detector windows retain 240 records each, absolute retains 360 and pairwise 240.

The implementation was committed and pushed before either live call at **`c6ec87b2fbcc3349d32625d2a8cfe78254d557fb`**, on the existing `paperbench-opus-cardinality-v7-20260912` lineage. No new cardinality branch was created. Both staged smokes below succeeded before native recovery submission; no multi-call evaluator, token-budget increase, or CPU-profile patch is included.

## V8 representation and measured complexity

Contract: `single-string-global-index-level-reason-v8`. The production Anthropic schema is exactly one object with required `criteria_text` and `overall_reasoning` properties, each `type: string`, with no additional properties. Its size is independent of rubric cardinality. The original v5/v6 schemas and format instructions compare exactly to their durable implementation; v7 is retained explicitly for historical replay/compatibility.

| Criteria | Version | JSON bytes | Object schemas | String schemas | Definitions | References | Patterns | Arrays |
|---:|---|---:|---:|---:|---:|---:|---:|---:|
| 306 | v5 | 2801 | 16 | 2 | 14 | 28 | 0 | 1 |
| 306 | v6 | 2915 | 16 | 2 | 14 | 31 | 1 | 0 |
| 306 | v7 | 413 | 2 | 6 | 0 | 0 | 0 | 0 |
| 306 | v8 | 182 | 1 | 2 | 0 | 0 | 0 | 0 |
| 872 | v5 | 2477 | 14 | 2 | 12 | 24 | 0 | 1 |
| 872 | v6 | 3017 | 14 | 2 | 12 | 36 | 1 | 0 |
| 872 | v7 | 761 | 2 | 15 | 0 | 0 | 0 | 0 |
| 872 | v8 | 182 | 1 | 2 | 0 | 0 | 0 | 0 |

The parser requires exactly N rows, the literal expected global index on each row, a nonnegative decimal level index, and a nonempty reason. Everything after the second pipe is retained as the reason; one terminal line ending is permitted but blank criterion rows are not discarded. The unchanged canonical validator checks each criterion's actual level choices and computes the same criterion records and normalized scores. Overall reasoning must be nonempty. No row, index, level or reason is synthesized.

V5/v6/v7/v8 valid outputs remain compatible only under the existing precise scientific bindings and canonical replay. Historical system-format instructions are reconstructed exactly; no old producer provenance is rewritten. OpenAI/Sol request behavior is unchanged. The provider-free suite covers canonical equivalence, the actual v7 omission shape, all requested criterion counts, exact resume preservation and existing streaming/inactivity behavior.

**Core integration verification:** The cumulative v7/v8 code/test patch was applied selectively to current `aydan-red-team` base `96e4ad0`, without stale branch merges or unrelated prompt/CPU edits. The same **792 focused tests passed again in 70.33s** (Slurm step `10414497.8`). Scientific execution remains pinned to `c6ec87b`, whose original experiment identity is unchanged.

## Successful production smokes and current native recovery

Slurm step **10414497.7** used the pinned production request/evaluator/stream/decoder/publisher. It ran one request worker in an auxiliary one-CPU step inside the existing 32-CPU PaperBench allocation, leaving the revision dispatcher intact. Each smoke was limited to exactly one provider attempt; the ordinary native three-attempt limit was restored afterward. Terminal raw responses were persisted by the native evaluator before optional telemetry writes.

| Criteria | Exact missing cell | Terminal status | Output tokens / budget | Provider-wrapper seconds | Native publication and fresh reuse |
|---:|---|---|---:|---:|---|
| 306 | fre / rep 3 / user-simulator-static / final heldout 2 | end_turn | 8,388 / 32,768 | 96.818 | Passed, exact 306/306 coverage |
| 872 | what-will-my-model-forget / rep 1 / full-static / final heldout 2 | end_turn | 18,472 / 32,768 | 170.830 | Passed, exact 872/872 coverage |

Both 182-byte schemas compiled. All criterion indices, actual level choices, reasons and overall reasoning validated; no absent field was inferred. The 306 published key is `c488d5154510aba53f51241a1ecee6aa`; the 872 key is `ac8dafe5eaf6ed08e322069936149f1b`. Fresh native preparation recognizes both, retains 900 Sol/764 Opus, and identifies only 136 missing Opus jobs. The complete receipts and exact canonical paths are in [the v8 compact evidence](opus-rubric-response-validation-v8.json).

Smokes: **two new Opus provider calls, zero retries, zero schema/count/provider failures, zero max_tokens cases, zero known-valid duplicate calls**. Neither provider-wrapper duration exceeded 300s. Total staged wall time was **435.837s**, comprising 60.988s initial preparation, 0.001311s audit admission, the two provider calls and final native revalidation. All **5,472** compared pre-existing files remain unchanged, including the two published historical replays. No revision or frozen input was modified.

Native recovery job **10414690** was submitted only after the helper exited successfully and released audit ownership. It uses the same exact pinned source and original storage overlay; the moving integration branch is not the scientific execution pin. Expected additional work is **136 Opus rubric judgments, zero Sol, zero already-valid Opus, zero detector/holistic**. The three-attempt bounded retry policy remains unchanged; actual recovery attempts will be counted from native telemetry. The 32-CPU/256-GiB Results20 allocation, 32 request workers, aggregate provider cap 60, streaming/300s inactivity timeout, 3600s subprocess safeguard and one global audit-study owner are unchanged. Scheduler admission and audit lease wait are distinct from provider execution time.

Executed submission (historical command; do not create a second dispatcher):

```bash
cd /home/aydanh/repos/rubric_gen/runs/babel-code/paperbench-opus-cardinality-20260912
sbatch --parsable --cpus-per-task=32 --mem=256G --job-name=pb-static-opus-v8-resume \
  scripts/babel/experiment.sbatch --profile results20 detect \
  --experiment ../paperbench-results20-seed-reuse-fixed-20260912-clone/experiments/babel/paperbench-static-selected-neutral-heldout-rigorous-results20-seed-reuse-fixed.yaml \
  --resume
```

Keep this checkout pinned while job10414690 depends on it. Later queues should inspect this owner and use only native missing-only resume after any terminal failure; never rerun completed work. If full intended coverage reaches 900/900 Sol and 900/900 Opus, compute the previously withheld static Results20 metrics and update the final scientific report. No final means or confidence intervals are claimed before coverage completes.

The historical v7 report below records the earlier stopped attempt; its held commands and 760-judgment state are historical, superseded by the current coverage and owner above.

## Historical v7 report (unchanged evidence)

### Opus rubric response validation — v7 block strings

**V7 compiles on Anthropic, but the 306-criterion smoke did not produce a complete scientific judgment. Recovery remains blocked.** The stream ended normally with only indices 0–63 present, three empty full blocks, and a literal `x` tail. All 242 remaining criterion judgments are absent; local validation correctly rejected the response. No score was published or imputed, and the 872 smoke, two local salvage publications, and bulk recovery were not launched.

Exact v7 execution commit: `8bff72545f78f58cd93101043842a134fa04ad38`, committed after provider-free tests/dry validation and pushed before generation to `origin/paperbench-opus-cardinality-v7-20260912`. It is based directly on durable v6 commit `57f54af532b9589c6f665321d562e16296d2c3fe` and original scientific source `7178f1968594027c7c27960940029363f58f07b3`; moving upstream prompts and the separate CPU patch are excluded. Implementation used Astra xhigh in the same isolated repair checkout.

Scientific coverage remains **120/120 valid revisions (60 per condition), Sol 900/900 and Opus 760/900**, with detector/holistic stages complete. Two historical responses remain losslessly salvageable, and 138 judgments genuinely need new provider responses. Final metrics remain withheld.

## Observed failures and v6 server boundary

The [diagnosis](opus-rubric-response-validation-diagnosis.md), [420-attempt table](opus-rubric-response-validation-attempts.csv), and [criterion-count census](opus-rubric-response-validation-census.json) cover all 140 missing v5 judgments. Their exact exception distribution remains: 407 block-count errors, 10 invalid decimal indices, one max_tokens termination, one empty criterion reason and one empty overall reason.

| Actual mutually exclusive saved-response class | Attempts |
|---|---:|
| Conflicting duplicate blocks only | 314 |
| Conflicting duplicates + invalid indices + empty reasons | 80 |
| Conflicting duplicates + empty reasons | 4 |
| Conflicting duplicates + invalid indices | 1 |
| Identical redundant duplicate blocks | 2 |
| Omitted blocks | 6 |
| Exact block structure + invalid indices + empty reasons | 10 |
| Empty criterion reason | 1 |
| Empty overall reasoning | 1 |
| max_tokens, no saved generation | 1 |

All 419 saved raw responses pass the original v5 schema. V5's array permitted duplicates/omissions; 129 judgments repeated the exact exception across all three attempts. V6 replaced that array with required keyed binary trees and a leaf pattern, but the actual 306-criterion production smoke failed Anthropic server compilation: job `10414045`, request `req_011CeyXrNhwP8iStoSLkn1mh`, HTTP 400 **`Schema is too complex.`** One call, no publication, no bulk recovery. Its schema was locally valid and 2,915 bytes; the server did not identify which internal compiler limit it exceeded.

## V7: small required string blocks, exact local validation

Contract: `required-block-strings-global-index-level-reason-v7`.

The provider schema has only a top-level object, a `criteria` object of required string fields, and an `overall_reasoning` string. Full blocks cover 64 criteria each; `tail` exists only for the remainder. Every block property is exactly `{"type":"string"}`. There are no trees, definitions, references, patterns, enums, arrays, or criterion objects in the v7 provider schema.

At 306 criteria, `criteria` requires `block_0` through `block_3` and `tail`. At 872, it requires `block_0` through `block_12` and `tail`. Each string contains exact lines `global_index|level_index|reason` in criterion-contract order.

Local decoding rejects missing/extra/duplicate object keys; wrong line counts; absent, repeated, reordered or wrong global indices; nondecimal/negative level indices; and empty reasons or overall reasoning. The existing canonical parser enforces each criterion's actual level options and performs unchanged normalization. Everything after the second pipe remains the reason, including additional pipes. One terminal line ending is accepted as a terminator; blank criterion rows are never discarded or filled. No missing criterion/index/score is inferred.

## Measured provider schema structure

| Criteria | Version | UTF-8 JSON bytes | Object schemas | String schemas | Definitions | References | Patterns | Arrays |
|---:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 306 | v5 | 2801 | 16 | 2 | 14 | 28 | 0 | 1 |
| 306 | v6 | 2915 | 16 | 2 | 14 | 31 | 1 | 0 |
| 306 | v7 | 413 | 2 | 6 | 0 | 0 | 0 | 0 |
| 872 | v5 | 2477 | 14 | 2 | 12 | 24 | 0 | 1 |
| 872 | v6 | 3017 | 14 | 2 | 12 | 36 | 1 | 0 |
| 872 | v7 | 761 | 2 | 15 | 0 | 0 | 0 | 0 |

Sizes use the production canonical JSON serializer and Anthropic schema adapter. Structural counts describe the stored schema graph, without expanding references or an unbounded array. V7 has no hidden schema expansion: only six string properties total at 306 and fifteen at 872, including overall reasoning. The schema measurement also verifies that the historical v5/v6 schemas and format instructions remain byte-for-byte equivalent to their durable source. Measurement job: `10414167`; local receipt: `runs/opus-schema-sizes-v7.json`.

## Scientific compatibility and historical replay

Only the Anthropic output representation and its format paragraph change. The complete rubric, criterion order, artifact/review/answer evidence, model `claude-opus-5`, low effort, output-token budget, one-call-per-attempt policy, scientific evaluation instructions, normalized canonical scores, and aggregation are unchanged. Sol's schema, system instructions, execution settings and scientific behavior remain unchanged.

Native compatibility reconstructs the exact recorded v5, v6 or v7 format paragraph with the unchanged scientific instructions. It continues binding the actual model, rubric, evidence, effort, budget, grading identity, original artifact receipts and canonical score replay. It does not relabel or rewrite old provenance, and accepts no arbitrary prompt/source whitelist.

The same two v5 identical-duplicate responses remain salvageable. Explicit replay verifies the complete saved request and accepts only identical redundant blocks with every criterion already present. Conflicting duplicate blocks and all incomplete outputs still fail. No salvage publication occurred during implementation or dry validation.

The original three-attempt budget, durable attempt/raw-response preservation, streaming, 300-second network-inactivity semantics and subprocess safeguards are unchanged. Representation changes receive normal current implementation identities; unchanged v7 resume cannot reset its attempt budget. The failed v6 schema-compilation attempt remains preserved under its original identity.

## Provider-free verification

- **460 tests passed**, job `10414171` (88.04 seconds), spanning v7, historical cardinality/replay, rubric judges, native evaluation/resume, capacity and streaming/inactivity. The initial run exposed three old-wire mock fixtures; those fixtures were updated, with no production-source change in response.
- V7 exact cardinality and adversarial cases at 1, 63, 64, 67, 86, 92, 120, 145, 178, 255, 306, 403 and 872 criteria; additional historical/current round trips cover 2, 65, 70, 77, 87, 126, 128 and 1,000.
- Equivalent v5/v6/v7 fixtures produce identical canonical criterion records, signed criterion scores and normalized totals. Sparse criterion identifiers preserve contract order; reason pipes remain intact.
- Native fixture: 900 expected Opus, 760 valid and 140 exhausted; two local replays leave 138 fake provider calls. Existing files and mtimes remain unchanged; another resume calls no provider. Explicit valid v5/v6/v7 provenance reuse and scientific-setting tamper rejection pass.
- Real replay job `10414164`: all 419 saved generations and scientific request settings checked; exactly two lossless replays, 417 rejected saved outputs, one unsaved max_tokens attempt. No provider call or publication.
- Native read-only dry job `10414163`: all 120 revisions load, 900 Sol and 760 Opus are reusable, and all 760 Opus judgments plus their 4,560 files compare directly byte-identical. Scientific writes and network connections were blocked. No lease or execution/publication stage ran.

| Native dry stage | Sol provider work | Opus provider work | Local replay publications |
|---|---:|---:|---:|
| Rubric score | 0 | 138 | 2 |
| Four detector windows | 0 | 0 | 0 |
| Holistic absolute + pairwise | 0 | 0 | 0 |

## Live 306 outcome — schema accepted, incomplete output

Job `10414183` used the exact pinned v7 production request, evaluator, decoder and normal publisher path. It targeted `fre`, replicate 3, User-simulator-static, final heldout variant 2—the same 306-criterion cell as the v6 compilation failure.

| Check | Result |
|---|---|
| Anthropic accepts schema | Yes; 413-byte v7 schema, no HTTP400 |
| Stream starts and completes | Yes; terminal `end_turn` |
| `block_0` | 64 rows, global indices 0–63, valid level indices and nonempty reasons |
| `block_1`, `block_2`, `block_3` | Empty strings, zero rows each |
| `tail` | Literal `x`, no parseable criterion row |
| Missing criterion judgments | **242**, indices64–305 |
| Extra/duplicate global indices | Zero |
| Output tokens / unchanged budget | **2,441 / 32,768** |
| max_tokens termination | No |
| Canonical validation/publication | Rejected; no record published |
| New provider attempts / retries | **1 / 0** |
| Two saved-v5 salvage publications | **0**; still pending |
| 872 live smoke | Not run; required306 success was not reached |
| Bulk recovery | Not launched |

Exact native failure: `RuntimeError: rubric-score rubric judge failed after 1 attempts: block-string rubric block_1 must contain exactly 64 criterion lines`.

The incomplete response is not locally salvageable: the missing242 judgments do not exist in the provider output. This is a **response omission/placeholder failure**, separate from the resolved306 server-compilation obstacle and separate from output-length truncation. The 872 schema's local size is measured, but its live server/response behavior remains untested. No conclusion about 872 live compilation or max_tokens is claimed.

The one-attempt smoke cap was honored. The ordinary three-attempt runtime policy was not raised or reset; only current v7 attempt001 was consumed. The unsuccessful smoke does not satisfy the user's prerequisite for later stages. No alternate prompt, schema workaround, token-budget increase, or second scientific cell was attempted.

Runtime: **96s Slurm wall time**, 58.340s preparation, 0.001132s audit admission, and 36.071s provider execution. Job ended `FAILED`, exit `1:0`. Peak smoke provider concurrency was one. All **5,460** compared existing files remain byte-identical, including all **4,560** files of the760 valid Opus judgments and all900 Sol record files; zero known-valid judgments were called twice.

The terminal raw response is preserved at `/data/user_data/aydanh/rubric_gen/runs/paperbench-static-selected-neutral-heldout-rigorous-20260912/results20-seed-reuse-fixed/audit/paperbench-code-dev-factorial-r10-08ba4d2c0d00/rubric_score/artifacts/1bad50364cf98268e4413885244f14d0/evaluations/s010/c5ce196753c83460890e874043d325de3783e22f2c50326962ace391397b994f/05cbed204892d10cd71bd5fbbeb0511f.attempts/attempt-001.response.json`. Its native attempt/failure records remain beside it. The [compact smoke receipt](opus-rubric-response-validation-v7-smoke.json) records source identity, exact settings/error, usage, row census and preservation. Read-only inspection10414205 made no provider calls or scientific writes.

## Conditional recovery plan — held

The following plan remains conditional on a complete306 smoke; that prerequisite was not met. Scientific execution must continue to use the exact pinned source rather than a moving upstream merge. First is the same `fre`, replicate 3, User-simulator-static, final heldout-2 306-criterion cell. After native publication/reuse succeeds, publish the two saved-response replays with provider generation forbidden. Then run the unique 872-criterion missing cell: `what-will-my-model-forget`, replicate 1, Full-static, final heldout-2.

Each smoke is limited to one real provider attempt, using the production evaluator, streaming transport, decoder and publisher. A schema-compilation error stops further calls. Output max_tokens is reported separately and never raises the token budget. Normal bulk retries remain three.

If both smokes and both local replays publish, Opus coverage becomes 764/900 and normal native resume should require **136 additional unique Opus judgments**, with zero Sol/known-valid/detector/holistic work. Actual attempts may include the existing bounded retries. Expected allocation remains the unmodified Results20 profile: 32 CPUs, 256 GiB, 32 request workers, global provider cap 60, one global audit owner. Scoped smokes use one request worker.

```bash
cd /home/aydanh/repos/rubric_gen/runs/babel-code/paperbench-opus-cardinality-20260912
sbatch --parsable --cpus-per-task=32 --mem=256G \
  scripts/babel/experiment.sbatch --profile results20 detect \
  --experiment ../paperbench-results20-seed-reuse-fixed-20260912-clone/experiments/babel/paperbench-static-selected-neutral-heldout-rigorous-results20-seed-reuse-fixed.yaml \
  --resume
```

This command is conditional on successful live smokes. Final Results20 metrics remain withheld until actual 900/900 Sol and 900/900 Opus coverage is complete. No CPU-profile change, scientific redesign, revision rerun, or unrelated upstream prompt change is included.
