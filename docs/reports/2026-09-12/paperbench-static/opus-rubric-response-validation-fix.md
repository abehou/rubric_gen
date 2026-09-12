# Opus rubric-response cardinality repair

**Provider-free implementation and native dry validation passed. No scientific recovery was launched and no scientific judgment was published.** The existing 760 valid Opus rubric judgments remain reusable and byte-identical; 140 judgments remain unpublished, comprising two lossless local replays and 138 that require new Opus responses.

Implementation used Astra xhigh in a fresh isolated checkout based on `7178f1968594027c7c27960940029363f58f07b3`. The pinned repair commit is `57f54af532b9589c6f665321d562e16296d2c3fe`. The scientific execution checkout and the separate CPU-resource-audit checkout were not modified.

## Failure census and root cause

The [diagnosis](opus-rubric-response-validation-diagnosis.md), [420-attempt table](opus-rubric-response-validation-attempts.csv), and [criterion-count census](opus-rubric-response-validation-census.json) cover all 140 missing judgments and all three attempts each. Exact persisted exceptions were 407 block-count mismatches, 10 invalid decimal indices, one max_tokens termination, one empty criterion reason and one empty overall reason.

Actual response contents, including every duplicate block occurrence:

| Mutually exclusive response class | Attempts |
|---|---:|
| `duplicate_conflicting_blocks` | 314 |
| `omitted_blocks` | 6 |
| `duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason` | 80 |
| `invalid_leaf_index+empty_leaf_reason` | 10 |
| `no_saved_raw_max_tokens` | 1 |
| `duplicate_conflicting_blocks+empty_leaf_reason` | 4 |
| `empty_leaf_reason` | 1 |
| `duplicate_identical_blocks` | 2 |
| `duplicate_conflicting_blocks+invalid_leaf_index` | 1 |
| `empty_overall_reasoning` | 1 |

All 419 saved terminal outputs are JSON and pass the actual v5 provider schema. The v5 array allows arbitrary length and repeated enum-valued block indices: 401 attempts repeat indices, and six omit required blocks. Of the duplicate outputs, 399 contain conflicting values/reasons and only two contain fully identical redundant trees. Every saved tail and full tree has the required shape. Ninety-one attempts contain invalid leaf indices, often literal placeholders without reasons; these remain invalid judgments.

Three retries did not constrain the same under-specified structure: 129 judgments repeated the same exact exception on all three attempts. The failure concentrates in 86/87/92/120-criterion rubrics (95 judgments), not only the largest rubrics. One max_tokens response was rejected before raw persistence; its text and token usage cannot be reconstructed.

## Minimal representation change

The new `keyed-64-leaf-blocks-fixed-tail-index-pipe-reason-v6` contract changes `criteria.full_blocks` from an array of `{block_index, values}` to an object with required `block_0`, `block_1`, … properties. Each key references the same 64-leaf tree definition; the existing exact tail is retained. Missing, extra or wrong block keys fail the schema and decoder. Duplicate JSON keys fail before object decoding can collapse them.

A shared leaf-string pattern enforces the existing decimal-index, literal pipe and nonempty-reason syntax. The canonical validator still enforces each criterion’s actual level range, nonempty evidence reasons and nonempty overall reasoning. Placeholder strings, missing blocks, malformed tails and incomplete responses are never padded or inferred.

This uses required coarse properties and local references rather than an expanded per-criterion schema. Anthropic documents these schema features, but also internal compiled-grammar limits. Local schema tests do not establish server compilation acceptance or future success rates; no provider compilation probe was authorized in this session. [Provider schema constraints](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#json-schema-limitations).

## Scientific invariants and provenance

Every new attempt still makes one call with the complete unchanged rubric and artifact evidence, `claude-opus-5`, the same low reasoning effort, output-token budget, evidence requirements and score normalization. The scientific system instructions are unchanged; only their wire-format paragraph changes. Sol’s prompt, schema, request parameters and scoring behavior are unchanged. The real replay checked all scientific request settings for all 419 saved responses.

Valid records use the existing semantic-reuse machinery: it binds task/artifact/rubric/review/answer/model identities, validates original artifact receipts and replays canonical scoring. The only additional compatibility rule reconstructs the exact recorded v5 format paragraph with the unchanged scientific instructions and requires its exact prompt identity. It does not accept arbitrary source/prompt hashes or rewrite original provenance.

The saved 900 Sol and 760 Opus records retain their original keys and bytes. Missing work receives current implementation keys, so a repaired wire contract has its own existing three-attempt budget; all exhausted v5 attempts remain intact. Repeating resume on unchanged repaired code cannot replenish that budget. No retry constant was raised.

An explicit saved-v5 replay path accepts only redundant identical trees with complete canonical judgments. It verifies the persisted request, model, rubric, evidence, engine seed, token budget, format and original attempt identity. Future publication would record actual v5 execution and cite the original response, attempt and producer identity in `usage.local_response_replay`; it does not pretend that the old response used v6. Normal decoders continue to reject duplicate blocks.

Streaming, the 300-second network-inactivity timeout, the 3,600-second subprocess safety ceiling, durable terminal raw-response preservation and provider-aware bounded retries remain unchanged. No revision, detector, holistic, seed, paraphrase, role-mapping, aggregation or CPU-profile code is changed.

## Verification

- Pinned implementation tests: **239 passed**, Slurm job `10413730`.
- Broader provider-free scoring/evaluation regression suite: **272 passed**, job `10413761`; this also exercised the patch integrated with upstream `31d6ed8`.
- Final review-merge regression: **272 passed**, job `10413829`, after preserving the subsequent upstream `270bd61` commit; the four repair modules and two focused test files remained identical to the pinned repair.
- Cardinality and canonical equivalence: 1, 2, 63, 64, 65, 67, 70, 77, 86, 87, 92, 120, 126, 128, 145, 178, 255, 306, 403, 872 and 1,000 criteria; both old valid and new valid representations produce identical canonical records and scores.
- Adversarial structure: missing/extra/wrong/duplicate blocks, missing/malformed tails, malformed full trees, placeholders, invalid indices and empty reasons rejected without imputation.
- Native fixture: 900 expected Opus judgments, 760 valid and 140 exhausted; exactly 140 remain pending. With two complete saved duplicate-only responses, fake generation is invoked for 138. Valid files and original attempt evidence remain byte-identical, and a subsequent resume invokes no generation.
- Exact request/provenance tampering and bounded exhaustion are tested; Sol and existing streaming/inactivity tests pass.

## Real raw replay and native dry scheduling

Job `10413729` replayed every available failed raw response through the patched decoder without publication or provider access. **Two of 419 raw responses are losslessly accepted**, belonging to two distinct missing judgments; 417 remain invalid, and one of the 420 attempts has no saved raw. [Replay receipt](opus-rubric-response-validation-replay.json).

Pinned native dry job `10413786` validated all 120 completed revisions, all saved stage coverage, original plan compatibility, and all 760 Opus record bytes plus their artifacts (4,560 files compared directly). Scientific filesystem mutations and network connections were blocked. It stopped at the native preparation/dispatch boundary; no stage execution or publication occurred. [Dry scheduling receipt](opus-rubric-response-validation-dry.json).

| Stage | Sol provider judgments scheduled | Opus provider judgments scheduled | Local replay publications pending |
|---|---:|---:|---:|
| Rubric score | 0 | 138 | 2 |
| Full-trajectory detector | 0 | 0 | 0 |
| Post-update detector | 0 | 0 | 0 |
| Final-artifact detector | 0 | 0 | 0 |
| Final-revision detector | 0 | 0 | 0 |
| Holistic absolute score | 0 | 0 | 0 |
| Pairwise preference | 0 | 0 | 0 |

Thus 760/760 valid Opus judgments and 900/900 Sol judgments schedule no provider work. The missing-publication count is 140; the genuinely provider-needed count is 138. No completed revision is scheduled.

## Recovery source and recommended command — not executed

Use pinned repair commit `57f54af532b9589c6f665321d562e16296d2c3fe`, built directly on `7178f196…` and retained in the implementation checkout below. Review publication merges that commit into `origin/aydan-red-team` without dropping concurrent history. **The review branch tip is not the pinned recovery source:** upstream `31d6ed8` changes the prompt-derived identity of this historical YAML to `76239bfd8268`. Two early dry checks stopped before loading outputs for that reason; no experiment identity was overridden and no scientific output was created. The pinned source naturally resolves the required `08ba4d2c0d00` identity.

The existing overlay remains at its original path because the completed study binds that exact YAML path. From the pinned implementation checkout:

```bash
cd /home/aydanh/repos/rubric_gen/runs/babel-code/paperbench-opus-cardinality-20260912
sbatch --parsable --cpus-per-task=32 --mem=256G \
  --job-name=pb-results20-opus-cardinality-resume \
  scripts/babel/experiment.sbatch --profile results20 detect \
  --experiment /home/aydanh/repos/rubric_gen/runs/babel-code/paperbench-results20-seed-reuse-fixed-20260912-clone/experiments/babel/paperbench-static-selected-neutral-heldout-rigorous-results20-seed-reuse-fixed.yaml \
  --resume
```

Expected existing profile: 32 Slurm CPUs, 256 GiB, 32 request workers, shared aggregate provider reservation cap 60, and one global audit-study owner. The separate proposed 4-CPU audit profile is neither included nor adopted here. Counts above are unique judgments: 138 new Opus responses are needed initially, with the unchanged bounded retry policy if an attempt fails.

This command is a recommendation for later authorization. This implementation session stops after the review push; it launches none of those recovery calls. Final Results20 metrics remain unavailable until the actual complete audit panel is published and validated.
