# Opus rubric response validation — v7 block strings

**Provider-free v7 verification passed. Live server compilation and scientific recovery are the next authorized stages; neither has run at this checkpoint.** The unchanged scientific panel contains 900/900 Sol and 760/900 Opus rubric judgments, all 120 revisions valid, and completed detector/holistic stages. Two saved v5 judgments are losslessly salvageable; 138 genuinely require provider responses.

This implementation uses Astra xhigh in the same isolated cardinality-repair checkout, based directly on durable v6 commit `57f54af532b9589c6f665321d562e16296d2c3fe` and original source `7178f1968594027c7c27960940029363f58f07b3`. The exact v7 commit is created after these provider-free checks and recorded in the live invocation receipt before generation. Moving upstream prompt changes and the separate CPU patch are excluded.

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

## Staged live execution plan

After the local source commit, the exact pinned commit—not a moving upstream merge—runs the two authorized scoped native smokes. First is the same `fre`, replicate 3, User-simulator-static, final heldout-2 306-criterion cell. After native publication/reuse succeeds, publish the two saved-response replays with provider generation forbidden. Then run the unique 872-criterion missing cell: `what-will-my-model-forget`, replicate 1, Full-static, final heldout-2.

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
