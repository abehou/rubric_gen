# Saved Opus response replay after the validated v8 recovery

2026-09-12, 12:10 EDT. Queue 6 provider-free validation passed before publication. The static Results20 audit has 900 valid Sol and 897 valid Opus rubric judgments; three missing canonical records have complete saved v8 responses. No new provider response is required to close this cohort.

## Evidence and bounded repair

Recovery job 10414690 completed 133 of 136 missing keys using 158 attempts (22 retries). Its three residual keys each exhausted three attempts. Of those nine terminal raw responses, two newline responses contain only 119 of 120 rows; seven serialize rows into a single pipe-delimited string. Five of the latter contain all 120 explicit ordered indices and valid judgments; two omit index 119. Four incomplete responses remain rejected.

| Original judgment key | Cell | Earliest complete saved attempt |
|---|---|---:|
| 0164cfe5c2eb1d5ff576b6b14fda387d | ftrl, User, replicate 3, final selected 0 | 2 |
| 5123ea33722de6bd82e6535b02c7117a | ftrl, User, replicate 1, final original | 2 |
| af2320beaa217729634458ea4a3d90d4 | ftrl, User, replicate 1, final heldout 3 | 1 |

Saved-response replay accepts this serialization only when every explicit index/level marker is unambiguous, present once, and ordered exactly 0 through N−1. It preserves the entire reason between markers and then invokes the existing strict decoder and canonical criterion validation. Overlapping or extra numeric markers, missing/reordered/duplicate indices, invalid levels, and empty reasons remain errors. Neither missing rows nor indices are inferred.

The live v8 decoder, provider schema, prompt, model, effort, output budget, streaming/inactivity behavior, retry count, score normalization and panel aggregation are unchanged. Historical v5 identical-block replay remains supported. The published usage provenance identifies the original saved response, attempt ledger and producer identity; raw generations and original valid record provenance are untouched.

Native saved-response discovery now consults the latest persisted summary as well as the initial manifest. This is necessary because the original manifest retains the v5 producer plan, while the failed recovery attempts have v8 producer keys. Existing native scientific scope and exact producer evidence/request checks remain enforced; an implementation change is not treated as a change to the scientific scoring task.

## Verification before scientific publication

- 686 provider-free tests passed in 138.05 seconds, including all nine real failed responses and transport/inactivity regressions. Five complete responses accepted; four incomplete responses rejected. No provider calls or scientific writes occurred.
- Native preparation validated all 120 completed revisions and reused 900 Sol plus 897 Opus records. All 897 Opus records and their 5,382 persisted record/artifact files remained byte-identical.
- Exactly three local publications are scheduled, from saved attempts 2, 2 and 1 above. Provider work: Sol 0, Opus 0, all four detector windows 0, absolute 0, pairwise 0. Detector reuse is 240 per window; absolute reuse 360; pairwise reuse 240.
- Real namespace native preparation and byte-preservation checks passed in 187.743 seconds with provider/network and scientific-write guards active. No audit lease was acquired by this dry validation.
- Focused coverage includes canonical score equivalence, no imputation, ambiguous marker rejection, historical v5 compatibility, mixed manifest/summary discovery, publication provenance, failed-publication retry without providers, and native missing-only scheduling.

The validation receipt is `runs/paperbench-nontrace-audit-closure-20260912/native-replay-dry.json`; the test receipt is `tests.out` alongside it. These are local operational receipts, not scientific outputs committed to Git.

## Publication

Publication must use a pinned commit containing this repair and the normal native `detect --resume` path against the unchanged static storage overlay. This report precedes publication; final coverage and the exact execution commit belong in the final scientific report and shared non-trace inventory. The three replay records must be marked as saved-response reuse with zero provider calls. Existing global audit ownership remains in force. No CPU-profile code is part of this repair.

## Terminal execution

Pinned repair `8226495fe88937cc613c02dd70b5253e58873e7f` was committed and pushed before native publication. Job10415061 completed successfully: exactly3 saved responses published, zero provider calls, Sol900/900 and Opus900/900, and all12,360 protected prior files byte-identical. Preparation216.206s, global lease admission286.021s, native execution121.660s, full preservation/publication workflow650.703s. Finalizer10415098 then passed all required coverage and produced the [complete final baseline report](selected-neutral-heldout-rigorous-results20-final.md).

The code also passed686 tests after selective integration in current core. Reporting uses existing native scoring-semantic compatibility and preserves all evidence/provenance checks;23 focused reporting tests and9 pinned-runtime tests passed. No CPU-profile code or live provider protocol changed.
