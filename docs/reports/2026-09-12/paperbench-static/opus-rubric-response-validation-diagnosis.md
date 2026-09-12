# Opus rubric-response validation diagnosis

Completed census: **140 missing judgments, 420 persisted attempts, 419 saved terminal raw responses**. All 419 are valid JSON and satisfy the actual v5 provider schema stored with their request. This is a schema/cardinality reliability failure, not a blanket JSON truncation failure.

The audit is read-only evidence. No scientific record, completed revision, valid judgment, seed, paraphrase, or attempt ledger was changed, and no provider call was made. Slurm jobs 10413646 and 10413676 performed the census; the second also checked every duplicate block occurrence for leaf-content defects.

## Evidence and complete failure table

Base code: `7178f1968594027c7c27960940029363f58f07b3`. Audit: `/data/user_data/aydanh/rubric_gen/runs/paperbench-static-selected-neutral-heldout-rigorous-20260912/results20-seed-reuse-fixed/audit/paperbench-code-dev-factorial-r10-08ba4d2c0d00/rubric_score`. The saved native plan has 1,800 rubric judgments; 900 Sol and 760 Opus records are present. Missing keys were identified from that plan minus saved records, and their task/replicate/condition/role references were matched to the complete Sol panel using the existing exact artifact, rubric, review and answer identities.

The [complete 420-row attempt table](opus-rubric-response-validation-attempts.csv) includes every requested identity, exact exception, criterion/block counts, representation, JSON/schema validation, completion/stop evidence, usage/budget, omissions, duplicates, malformed tails/trees, truncation, leaf defects, cross-attempt repetition, and local-replay disposition. Raw paths are relative to the audit root above. Null/blank values mean unavailable evidence, not a negative finding. Shared initial-artifact judgments retain both condition references.

No raw provider responses or scientific scores are included in this report/table. The detailed private census remains at `runs/opus-census.json`; original responses remain at their persisted paths.

## Exact persisted exceptions

| Exception | Attempts |
|---|---:|
| `FullRubricJudgeError: count-safe block count does not exactly match the rubric` | 407 |
| `FullRubricJudgeError: keyed criterion has an invalid decimal level index` | 10 |
| `IncompleteProviderResponse: Anthropic response stopped before a complete answer: max_tokens` | 1 |
| `FullRubricJudgeError: rubric-score result for criterion_66 has an empty reason` | 1 |
| `FullRubricJudgeError: rubric-score overall reasoning must be nonempty` | 1 |

## What the responses actually contain

| Mutually exclusive response class | Attempts |
|---|---:|
| Conflicting duplicate blocks; leaf fields otherwise valid | 314 |
| Conflicting duplicates plus invalid indices and absent reasons | 80 |
| Conflicting duplicates plus absent reasons | 4 |
| Conflicting duplicates plus invalid indices | 1 |
| Identical duplicate blocks; complete unambiguous judgment | 2 |
| Omitted required full blocks | 6 |
| Correct block membership, but invalid indices and absent reasons | 10 |
| Correct block membership, but one empty criterion reason | 1 |
| Correct block membership, but empty overall reasoning | 1 |
| max_tokens stop; raw response not persisted | 1 |

Of the 407 count exceptions, **401 contain repeated block indices** and **6 omit blocks**. Of the repeated-block responses, 399 are ambiguous: 372 differ in at least one level prefix, and 27 retain the same level prefixes but have different evidence reasons. Only two repeat fully identical trees. The most common returned index list is `[0, 0]` (355 attempts), including rubrics that require exactly one full block.

The six omissions are five 145-criterion attempts returning only block 0 (missing block 1), and one 255-criterion attempt returning only block 0 (missing blocks 1 and 2). None can supply the absent criterion judgments locally.

Every saved response has the required tail with its exact tree shape. There are no malformed full trees, malformed/missing tails, wrong/out-of-range block identities, duplicate JSON object keys, or non-JSON saved responses. String-valued leaves can nevertheless be placeholders: `placeholder`, `x`, empty strings and alphabet sequences occur; they have no scored level and/or reason. These are absent judgments, not numeric formatting variants. Out-of-range level values and one `:0` prefix also occur within conflicting duplicate output.

There are 129 judgments whose three attempts have the same exact exception; 68 also repeat the same detailed defect class across all three attempts. Reissuing the unchanged under-constrained schema therefore reproduced the error rather than enforcing block membership.

## Criterion-count distribution

Columns separate the dominant block defects from the remaining failures; duplicates with leaf defects remain in the duplicate column.

| Criteria | Missing judgments | Conflicting-duplicate attempts | Identical-duplicate attempts | Omitted-block attempts | Other attempts |
|---:|---:|---:|---:|---:|---:|
| 67 | 5 | 15 | 0 | 0 | 0 |
| 70 | 7 | 21 | 0 | 0 | 0 |
| 77 | 10 | 30 | 0 | 0 | 0 |
| 86 | 33 | 95 | 0 | 0 | 4 |
| 87 | 21 | 63 | 0 | 0 | 0 |
| 92 | 21 | 60 | 1 | 0 | 2 |
| 120 | 20 | 60 | 0 | 0 | 0 |
| 126 | 5 | 14 | 0 | 0 | 1 |
| 145 | 6 | 12 | 0 | 5 | 1 |
| 178 | 1 | 2 | 0 | 0 | 1 |
| 255 | 8 | 21 | 1 | 1 | 1 |
| 306 | 2 | 6 | 0 | 0 | 0 |
| 872 | 1 | 0 | 0 | 0 | 3 |

The dominant failures are small rubrics: 86, 87, 92 and 120 criteria account for 95 of the 140 missing judgments. Only one missing judgment has 872 criteria; 403 remains a required regression size rather than an observed missing-judgment count in this run.

## Terminal status, tokens and retained evidence

The 419 saved generations were persisted after the pinned streaming transport observed `message_stop` and accepted `end_turn`. The raw generation envelope does not separately store stop_reason, so the table labels this inference explicitly. The attempt ledger still says `remote_completion: unknown` after local decoding fails; that field alone is not evidence of an unfinished stream.

All 419 saved responses used fewer output tokens than their unchanged individual budgets; recorded output usage ranges from 1,294 to 23,731 tokens. One 872-criterion attempt raised `IncompleteProviderResponse: ... max_tokens` before the terminal-generation save point. Its partial response and usage were not retained; neither can be reconstructed. The exception establishes token-limit termination, but there is no raw text to inspect or salvage.

## Schema mechanism and earlier validation

The current `indexed-64-leaf-blocks-fixed-tail-index-pipe-reason-v5` format uses an array of `{block_index, values}` objects. The schema restricts each index to an allowed enum and each values tree to 64 leaves, but neither the exact array length nor index uniqueness is provider-enforced. The tail is structurally fixed. Every extra duplicate block in the census is therefore legal under the transmitted schema; every required leaf across the full rubric is not guaranteed.

Anthropic documents required object properties, `additionalProperties: false` and local schema references, while fixed array bounds beyond minItems 0/1 are unsupported. A required object property for each coarse block can enforce membership without a separate expanded schema for every criterion. The provider also has internal compiled-grammar limits, so provider-free schema validation does not prove server compilation acceptance. [Anthropic structured-output constraints](https://platform.claude.com/docs/en/build-with-claude/structured-outputs#json-schema-limitations).

The earlier `keyed-validation.md` and `v5-recovery.md` evidence records rejected expanded per-criterion formats, a v4 145-criterion success with an 872-criterion compilation rejection, and v5 145/872 successes. That v5 report expressly described block count as locally enforced. Two successful probes did not establish reliability at Results20 scale; this census exposes the remaining structural freedom.

## Lossless local salvage

**Two judgments are locally salvageable with zero provider calls.** Every required criterion judgment and nonempty reason already exists; repeated trees are identical at every leaf. Removing redundant identical occurrences preserves the complete canonical result. Conflicting duplicates, placeholders, missing blocks, absent reasons, and the unsaved token-limited response remain rejected.

| Judgment key | Attempt | Task / replicate / condition / role | Criteria | Returned indices |
|---|---:|---|---:|---|
| `6daba9ad156ed63490ba3ad8651800ea` | 3 | all-in-one / 2 / full-static / {"name": "holdout", "variant_index": 2} | 92 | `[0, 0]` |
| `b60365181808e6d81da0d4cc23bc4e61` | 2 | bam / 3 / user-simulator-static / {"name": "holdout", "variant_index": 4} | 255 | `[0, 1, 2, 0]` |

No recovered record was published. At this checkpoint there are still 140 unpublished Opus judgments: two complete saved outputs can be replayed locally, and **138 genuinely require a new Opus response**. The implementation report will record native scheduling and replay validation separately.

## Per-judgment repetition and disposition

The companion attempt table carries all task, condition and rubric-role fields. This index covers every missing semantic key and its three detailed classes.

| Judgment key | Task | Replicate | Criteria | Attempt classes (1 / 2 / 3) | Same exact error all 3 | Local salvage |
|---|---|---:|---:|---|---|---|
| `00208351bcc03ddc883e8aa34342f7cb` | bam | 2 | 255 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / omitted_blocks | True | False |
| `0063cc67d1309eec183e3a7a7b1cbb94` | bam | 3 | 255 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `02118c75f168ac461eea3de85a1bb0ee` | sample-specific-masks | 3 | 87 | duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks | True | False |
| `03379456e8e12b612fb898c47e622b1b` | all-in-one | 1 | 92 | invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | False | False |
| `057bcf22486ef11bea9a14ddd6d75c9e` | ftrl | 1 | 120 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `098edaa2603c7d0d4b9e5e52f2249070` | test-time-model-adaptation | 3 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `0ed19654a267c2e81bec132be563d88c` | test-time-model-adaptation | 2 | 86 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks | True | False |
| `0f0fc852d2d7e15c1d8f14b21bb68206` | sapg | 2 | 77 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `1003aa647a36bcdb9c61ea5530321dde` | test-time-model-adaptation | 3 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks | True | False |
| `10d3c15942e763ee0f8352a847e6221a` | test-time-model-adaptation | 2 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `13b5606972cf570a2c79835bf2d8fe64` | what-will-my-model-forget | 1 | 872 | invalid_leaf_index+empty_leaf_reason / invalid_leaf_index+empty_leaf_reason / no_saved_raw_max_tokens | False | False |
| `156426434c5c24d9c809fa500f3c5fdc` | sapg | 2 | 77 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `1d42921319a929184fe6e3967bbc2aba` | adaptive-pruning | 3 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `1f0bee87edff2c1e04f10dfcb9004b95` | sapg | 1 | 77 | duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks | True | False |
| `20d78a3438f7ff5ae423fb7e26feacba` | adaptive-pruning | 2 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `2273904141a5cbbbc78e5983926cf6b1` | ftrl | 1 | 120 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `23fd41881161edd440cb19e358a6a00d` | test-time-model-adaptation | 2 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `24765fae5417a24195ab4f715fb117e8` | ftrl | 2 | 120 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `266a6da1747425e4070726439c4ac7ed` | ftrl | 2 | 120 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `282827ccb7be972f8bdd625aa1bb5ab8` | all-in-one | 3 | 92 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `2f0a9a506de62bd87507da689dffb5bd` | all-in-one | 2 | 92 | duplicate_conflicting_blocks+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `3230c9f4c21f9ebea9660b6c3e79cbe2` | rice | 1 | 178 | invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks | False | False |
| `34cad87acf345d299312d6327b48ac99` | all-in-one | 3 | 92 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `350dcbbcf2c8f1e441c512072aae91a1` | ftrl | 2 | 120 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `36bd6c4cdb97993fc83b9386035073e3` | stay-on-topic-with-classifier-free-guidance | 1 | 70 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `3bfeb9acd3ef62fab7624eb58215916f` | sample-specific-masks | 3 | 87 | duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `3c9e6207fd2f0427924f7e0adba2f0c2` | robust-clip | 1 | 70 | duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks | True | False |
| `3f047d2c32456013e80ae6f095b2d24e` | adaptive-pruning | 2 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `3fabdedd6cf2839c377a79e5a2adf7d8` | ftrl | 1 | 120 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `42a247e1ab4413872fc7086e77de005c` | all-in-one | 1 | 92 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `438f5d823a0999092d166d1814933a75` | sapg | 3 | 77 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `45097ee3906197696e1219a25c7202e5` | test-time-model-adaptation | 1 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `4531a8eb106b7988424d16c54c7b6b19` | all-in-one | 3 | 92 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `48dcbf3e389c38750e9b2328c1327976` | test-time-model-adaptation | 1 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `49904e8a93b4a23b56453327025dbc6a` | ftrl | 1 | 120 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `4e4271fa7fae29f062e916451ea8e442` | sapg | 2 | 77 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `54ff2906a7619ae26f291714e2e37a28` | test-time-model-adaptation | 3 | 86 | empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | False | False |
| `555bff485f50ebfbd6628edadfc07fc7` | adaptive-pruning | 2 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / invalid_leaf_index+empty_leaf_reason | False | False |
| `561e7cdc7d78dc199a7225b6e4f40715` | ftrl | 2 | 120 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `5723aebb8f3c750b26597fe2fd3c9ab2` | sample-specific-masks | 2 | 87 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `5b39cc7ac87ebe216e45285b4de5a48b` | sample-specific-masks | 2 | 87 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `5b53a44de9ec570018a24d52946afaac` | sample-specific-masks | 2 | 87 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `5bce44447894c9b3a7057b6b604715f4` | ftrl | 1 | 120 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `5cefb7d7919ffe90e450eb1aa76bb7ae` | all-in-one | 1 | 92 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `5cfc12e476c577f984839c1d10d2ad09` | sample-specific-masks | 2 | 87 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks | True | False |
| `5de93a25e72c675ba475745ed18885ca` | all-in-one | 2 | 92 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks+empty_leaf_reason | True | False |
| `5e282b68fae19bae3937c1ebe8385283` | test-time-model-adaptation | 3 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks | True | False |
| `603317475d8a6f9532416a8da7f76edb` | sequential-neural-score-estimation | 1 | 67 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `6397a2fad79e886a30dc03abba2144de` | adaptive-pruning | 1 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `63c5e46ce62699abdf6c42d5f8c7f78d` | ftrl | 1 | 120 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `65dbd10c4959f37567222a4ea6d78896` | sample-specific-masks | 1 | 87 | duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks | True | False |
| `671bfcc04296b82c17a86a9183168ac1` | robust-clip | 3 | 70 | duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks | True | False |
| `6982a220d26cd1ca9a716085b3d99675` | adaptive-pruning | 1 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `6daba9ad156ed63490ba3ad8651800ea` | all-in-one | 2 | 92 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_identical_blocks | True | True |
| `6eba49ba9f49013786f0cfeceb848288` | pinn | 3 | 126 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `71859d66fd117220391434ab385e6107` | test-time-model-adaptation | 1 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks | True | False |
| `72846d608e399fb37b5ecadb53059430` | test-time-model-adaptation | 2 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `7325770911b279038ca097e0b00aae8c` | sapg | 1 | 77 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `762abba4c26aca3675e26b9d99a4c1be` | sample-specific-masks | 3 | 87 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks+invalid_leaf_index | True | False |
| `7893ca7098544d65b14ea3df2f13b216` | bam | 2 | 255 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `7df12ec22b0baaa442b8f1ce74ec55fb` | ftrl | 2 | 120 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `7f71b0561fe648834c277af799d9a8b4` | adaptive-pruning | 3 | 86 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `81f14e321ecff49c0eea0cc592176b94` | ftrl | 3 | 120 | duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks | True | False |
| `8258beb2df21336c80e9134a20797b8b` | sapg | 2 | 77 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `82ebf80d703a81a3653083ed99e5b040` | test-time-model-adaptation | 2 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks | True | False |
| `842967280c6338b2e5106e678312e37b` | pinn | 1 | 126 | duplicate_conflicting_blocks / invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks | False | False |
| `88d259ad1a8e204329e0223c7dd677ae` | all-in-one | 3 | 92 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `896e994ee6fc5899115340459cb0191e` | test-time-model-adaptation | 3 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `8a47a535dc534c02dca76450669ce1db` | all-in-one | 3 | 92 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `921233d03c03a71cd636bc9c6e22db55` | adaptive-pruning | 2 | 86 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `940175de794df3fa843cb04b1af503f7` | bbox | 2 | 145 | duplicate_conflicting_blocks / omitted_blocks / omitted_blocks | True | False |
| `9959a4aa9332f722ffb519d653ae9861` | adaptive-pruning | 3 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `996fb8c22d27c7bf753389b5a6c59705` | ftrl | 3 | 120 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `a226fdaeef98d3d0a6631403ac7396fc` | test-time-model-adaptation | 3 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `a2b8c007f25ea841744bf77a9e0681f0` | test-time-model-adaptation | 3 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `a69643f0a40d59f45dc231e2c95d963b` | fre | 2 | 306 | duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `a6e9d59cb05bcba39a6c00ea63e1ebc9` | sample-specific-masks | 1 | 87 | duplicate_conflicting_blocks / duplicate_conflicting_blocks+empty_leaf_reason / duplicate_conflicting_blocks | True | False |
| `abcb0c2a015d5d741f6e3394c90c5b88` | ftrl | 2 | 120 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `ac9a5b5aa3916e25e1d835ccb6e11574` | adaptive-pruning | 1 | 86 | duplicate_conflicting_blocks / invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks | False | False |
| `adfe3b59360c01294550f85baa1999c0` | bam | 2 | 255 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `af3ad3528cbb4688f90db976c05005c7` | pinn | 3 | 126 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `afcfc9b9f6f391acd22333ad3297c558` | pinn | 2 | 126 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `b105c87b05f0a3dfad8f82e3d8229c76` | ftrl | 3 | 120 | duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks | True | False |
| `b13345a622f2758b63f5f90c7bf861ee` | bam | 2 | 255 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `b2067955b8b38f5cd0f8847629e5ef95` | sample-specific-masks | 2 | 87 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `b44b776df0a66c2733739d15487cce17` | test-time-model-adaptation | 1 | 86 | empty_overall_reasoning / duplicate_conflicting_blocks / duplicate_conflicting_blocks | False | False |
| `b4709e9da62249a23f8f758bcc5972aa` | sapg | 3 | 77 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `b60365181808e6d81da0d4cc23bc4e61` | bam | 3 | 255 | invalid_leaf_index+empty_leaf_reason / duplicate_identical_blocks / duplicate_conflicting_blocks | False | True |
| `b706450e04a36678d6d749df899015f4` | all-in-one | 2 | 92 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `ba7b38e240915aa11c734054a64612f7` | ftrl | 2 | 120 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `bafd6271037fae65d7880de7015a096d` | sequential-neural-score-estimation | 2 | 67 | duplicate_conflicting_blocks+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `bb55492897294701f558440cc832c652` | sequential-neural-score-estimation | 3 | 67 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `bd3dff8d2c6dd9300ff9bdb9655d27ef` | bam | 1 | 255 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `bd94e02ee6d190bcdebdcbfafaac77c1` | sample-specific-masks | 3 | 87 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `bfd0ac2a2c15f3fbe4474afa84567e05` | all-in-one | 2 | 92 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `bfe4418b0090e1b3c18e2581b8520bb8` | adaptive-pruning | 2 | 86 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `c3632b83ae160c882fc24961f0e55359` | stay-on-topic-with-classifier-free-guidance | 1 | 70 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `c40085fb7d4471a935baf68d958b378c` | ftrl | 2 | 120 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `c84785528f64089d33e7e12a8f8599d6` | sample-specific-masks | 3 | 87 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `caa9f121800d22032d431516167bc177` | bbox | 3 | 145 | duplicate_conflicting_blocks / omitted_blocks / duplicate_conflicting_blocks | True | False |
| `cc5beb4c13ab51b75b0c37076c5c38e1` | all-in-one | 1 | 92 | duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks | True | False |
| `ce4a7612d746030b2c821843607ce2d3` | sample-specific-masks | 2 | 87 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `ce73604abeb1e320f8a2de13647c84e2` | sample-specific-masks | 2 | 87 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `ceed604b836a8769d47e26934e385656` | all-in-one | 1 | 92 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `d2bc9deab2f57188668fc1f7211954f9` | sample-specific-masks | 2 | 87 | duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `d46c5c6ec60959fc1fa85b04da931296` | bbox | 1 | 145 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `d5ae4b8999468594397cf85023bce7a1` | sapg | 3 | 77 | duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks | True | False |
| `d8241bb9abd934b5fe0ab56064ab2f64` | adaptive-pruning | 3 | 86 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `daff87056581b41b130b5978ce888291` | test-time-model-adaptation | 1 | 86 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `dba66fc9e2af382461cec1c219406450` | sample-specific-masks | 1 | 87 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `dbea74d7b6bb0e52ee6c06c05121b7a4` | robust-clip | 3 | 70 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `dd98285501dad53f4e6284520d0720ea` | bbox | 3 | 145 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | False | False |
| `de24bfa3b2d40ca12d721a002ef5ed84` | all-in-one | 2 | 92 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `e1ff4311e3a2b003322ef547df72a788` | test-time-model-adaptation | 1 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `e3f2c87da43d661bb47f9477c98c6412` | ftrl | 3 | 120 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `e5288d6f26919758de1d3f1cbc8347d1` | sample-specific-masks | 2 | 87 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `e52c2f2211aa4e55188d4664e2433ac5` | all-in-one | 3 | 92 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `e6d7c4085334ef6137a4d79ee120e3cc` | bbox | 1 | 145 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `e76597cc97441b292d5c9a4c6b253de5` | test-time-model-adaptation | 1 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `e814bb6e8a076283478c9b440c691376` | sample-specific-masks | 1 | 87 | duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks | True | False |
| `ea3e59b21966b4e467367d26b74bb124` | test-time-model-adaptation | 2 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `ea994d8a93c0af2a207109a9c7cf9d82` | test-time-model-adaptation | 2 | 86 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `eb4b8f11dcf930424c9ac9216b9d8bf9` | pinn | 1 | 126 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `ebf6d08e9e4871957c50b8785a208926` | bbox | 1 | 145 | omitted_blocks / duplicate_conflicting_blocks / omitted_blocks | True | False |
| `ef2ce3fb253ced5bc2608d690e6d487d` | sapg | 3 | 77 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `efd84ab9bf6f9d0e1288ff8709406052` | sample-specific-masks | 3 | 87 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `f2520584c31aa060cc112d4066de9a80` | sequential-neural-score-estimation | 3 | 67 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `f29509012415c90603093e68a8bb07a1` | stay-on-topic-with-classifier-free-guidance | 2 | 70 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `f3af060886c00631d7f7fcd100483f35` | sample-specific-masks | 2 | 87 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `f4bf8b2f407523f55e35e1a34a7363cc` | ftrl | 1 | 120 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason | True | False |
| `f6fe12f784011d1e4920ebe069ad263f` | fre | 3 | 306 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `f763c0e2bb36cbaff2d65489d8bb5f0c` | bam | 1 | 255 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `f857f8bfea5a29638cdd8b6ef3bc7914` | all-in-one | 3 | 92 | duplicate_conflicting_blocks+invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `f86d85e05800c916d9a2141f34aba1eb` | all-in-one | 2 | 92 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `f8a910ba640c39ff1f38080f5f7120e8` | all-in-one | 1 | 92 | duplicate_conflicting_blocks / invalid_leaf_index+empty_leaf_reason / duplicate_conflicting_blocks | False | False |
| `f92c635a6365ab32616cbfce62dd4e19` | all-in-one | 1 | 92 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `fa02d781fcff487079139b3835bc013d` | ftrl | 1 | 120 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `fbaafcb95d33aaf48a9a2d982073f4ec` | robust-clip | 1 | 70 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `fca1d6f0a39486da1372dac69913cdd4` | sequential-neural-score-estimation | 1 | 67 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |
| `fdca9397afa95a7961869098d3acd846` | sample-specific-masks | 1 | 87 | duplicate_conflicting_blocks / duplicate_conflicting_blocks / duplicate_conflicting_blocks | True | False |

## V6 server compilation and v7 follow-up

The single authorized production smoke10414045 at57f54af used the 306-criterion fre/rep-003/User-simulator-static/final-heldout-2 cell. Anthropic rejected its required keyed binary-tree schema with HTTP400 `Schema is too complex.` (request `req_011CeyXrNhwP8iStoSLkn1mh`); no generation or score was published, and no bulk recovery ran.

This establishes a provider compiler limit beyond local schema validity; it does not identify an internal size threshold. V7 replaces each tree with a required plain string of explicit global-index/level-index/reason rows, preserving strict local scientific validation. See the updated [fix report](opus-rubric-response-validation-fix.md) for exact schema measurements, compatibility tests and staged live outcomes. The original140-judgment/420-attempt census above remains unchanged.
